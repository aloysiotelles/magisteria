from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import time
import json
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from config import BASE_DIR, settings
from services.answer_service import AnswerService, format_abnt_references, format_sources
from services.presentation_service import PresentationService, safe_filename
from services.vector_store import LocalVectorStore

APP_VERSION = "0.5.1"
logger = logging.getLogger(__name__)

vector_store = LocalVectorStore(
    settings.DOCUMENTS_DIR,
    settings.INDEX_FILE,
    settings.CHUNK_SIZE,
    settings.CHUNK_OVERLAP,
)
answer_service = AnswerService(settings.OPENAI_API_KEY, settings.OPENAI_MODEL)
presentation_service = PresentationService(
    settings.OPENAI_API_KEY,
    settings.OPENAI_MODEL,
    settings.OPENAI_IMAGE_MODEL,
    settings.IMAGE_CONCURRENCY,
    settings.IMAGE_QUALITY,
)
index_lock = asyncio.Lock()
indexing_state = {
    "ativa": False,
    "processados": 0,
    "total": 0,
    "percentual": 0,
    "arquivo_atual": "",
    "segundos_restantes": None,
    "erro": None,
    "inicio": None,
}


def update_indexing_progress(processed: int, total: int, current_file: str) -> None:
    elapsed = time.monotonic() - indexing_state["inicio"] if indexing_state["inicio"] else 0
    percentage = round((processed / total) * 100) if total else 0
    remaining = None
    if processed > 0 and total > processed:
        remaining = round((elapsed / processed) * (total - processed))
    indexing_state.update(
        processados=processed,
        total=total,
        percentual=percentage,
        arquivo_atual=current_file,
        segundos_restantes=remaining,
    )


async def perform_indexing() -> dict:
    indexing_state.update(
        ativa=True,
        processados=0,
        total=0,
        percentual=0,
        arquivo_atual="Preparando documentos",
        segundos_restantes=None,
        erro=None,
        inicio=time.monotonic(),
    )
    try:
        async with index_lock:
            result = await asyncio.to_thread(vector_store.index_documents, update_indexing_progress)
        indexing_state.update(ativa=False, percentual=100, arquivo_atual="Base atualizada")
        return result
    except Exception as exc:
        indexing_state.update(ativa=False, erro=str(exc), arquivo_atual="Falha na atualização")
        raise


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Inicia a reconstrução da base sem impedir a exibição do progresso."""
    indexing_task = asyncio.create_task(perform_indexing())
    yield
    if not indexing_task.done():
        await indexing_task


app = FastAPI(
    title="MAGISTERIA",
    description="Pesquisa pastoral em uma base documental fechada.",
    version=APP_VERSION,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


class ConversationTurn(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000)
    resposta: str = Field(min_length=1, max_length=8000)


class QuestionRequest(BaseModel):
    pergunta: str = Field(min_length=3, max_length=2000)
    historico: list[ConversationTurn] = Field(default_factory=list, max_length=6)


class PresentationRequest(BaseModel):
    titulo: str = Field(min_length=3, max_length=300)
    resposta: str = Field(min_length=20, max_length=16000)


def retrieval_query(payload: QuestionRequest) -> str:
    question = payload.pergunta.strip()
    if payload.historico and len(question.split()) <= 12:
        return f"{payload.historico[-1].pergunta} {question}"
    return question


def ordered_chunks(payload: QuestionRequest) -> list[dict]:
    return vector_store.search_ordered(
        retrieval_query(payload),
        limit=max(settings.MAX_CONTEXT_CHUNKS, 16),
        minimum_score=settings.MIN_RELEVANCE_SCORE,
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/perguntar")
async def ask(payload: QuestionRequest):
    if indexing_state["ativa"]:
        raise HTTPException(status_code=503, detail="A base documental ainda está sendo atualizada.")
    question = payload.pergunta.strip()
    chunks = await asyncio.to_thread(ordered_chunks, payload)
    history = [turn.model_dump() for turn in payload.historico]
    try:
        answer = await answer_service.answer(question, chunks, history)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Não foi possível consultar o serviço de IA agora.") from exc
    return {"resposta": answer, "fontes": format_sources(chunks)}


@app.post("/perguntar-stream")
async def ask_stream(payload: QuestionRequest):
    if indexing_state["ativa"]:
        raise HTTPException(status_code=503, detail="A base documental ainda está sendo atualizada.")

    question = payload.pergunta.strip()
    chunks = await asyncio.to_thread(ordered_chunks, payload)
    history = [turn.model_dump() for turn in payload.historico]
    if chunks and not answer_service.api_key:
        raise HTTPException(status_code=503, detail="A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")

    async def events():
        yield json.dumps(
            {
                "tipo": "fontes",
                "fontes": format_sources(chunks),
                "referencias_abnt": format_abnt_references(chunks),
            },
            ensure_ascii=False,
        ) + "\n"
        try:
            async for delta in answer_service.stream_answer(question, chunks, history):
                yield json.dumps({"tipo": "texto", "texto": delta}, ensure_ascii=False) + "\n"
            yield json.dumps({"tipo": "fim"}) + "\n"
        except asyncio.CancelledError:
            logger.info("Transmissão cancelada pelo navegador.")
            raise
        except Exception:
            logger.exception("Falha durante a geração da resposta em fluxo.")
            yield json.dumps(
                {"tipo": "erro", "mensagem": "Não foi possível consultar o serviço de IA agora."},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/indexar")
async def index_documents():
    if index_lock.locked():
        raise HTTPException(status_code=409, detail="A base documental já está sendo atualizada.")
    status = await perform_indexing()
    return {"mensagem": "Base documental atualizada com sucesso.", "status": status}


@app.post("/criar-roteiro")
async def create_script(payload: PresentationRequest):
    try:
        topics = await presentation_service.create_outline(payload.titulo, payload.resposta)
        content = await asyncio.to_thread(presentation_service.create_docx, payload.titulo, topics)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao criar roteiro.")
        raise HTTPException(status_code=502, detail="Não foi possível criar o roteiro agora.") from exc
    filename = safe_filename(payload.titulo, "roteiro.docx")
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/criar-slides")
async def create_slides(payload: PresentationRequest):
    try:
        plan = await presentation_service.create_plan(payload.titulo, payload.resposta)
        content = await presentation_service.create_pptx(
            payload.titulo,
            plan["topicos"],
            plan["titulo_curto"],
            plan["frase_final"],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao criar apresentação.")
        raise HTTPException(status_code=502, detail="Não foi possível criar os slides com imagens agora.") from exc
    filename = safe_filename(payload.titulo, "slides.pptx")
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/status")
async def status():
    return {**vector_store.status(), "indexacao": {key: value for key, value in indexing_state.items() if key != "inicio"}}


@app.get("/health", include_in_schema=False)
async def health():
    """Health check leve para o Railway; independe da indexacao e da OpenAI."""
    return {"status": "ok", "versao": APP_VERSION}


@app.get("/documentos")
async def documents():
    return {"documentos": vector_store.document_names()}


@app.get("/versao")
async def version():
    return {"versao": APP_VERSION}
