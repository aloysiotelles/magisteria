from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import html
import time
import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from config import BASE_DIR, settings
from services.answer_service import AnswerService, format_abnt_references, format_sources
from services.auth_repository import AuthRepository
from services.document_loader import discover_documents
from services.presentation_service import PresentationService, safe_filename
from services.vector_store import LocalVectorStore

APP_VERSION = "0.5.3"
logger = logging.getLogger(__name__)

vector_store = LocalVectorStore(
    settings.DOCUMENTS_DIR,
    settings.INDEX_FILE,
    settings.CHUNK_SIZE,
    settings.CHUNK_OVERLAP,
)
answer_service = AnswerService(settings.OPENAI_API_KEY, settings.OPENAI_MODEL)
auth_repository = AuthRepository(settings.APP_DATABASE_FILE)
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
            auth_repository.sync_documents(discover_documents(settings.DOCUMENTS_DIR), settings.DOCUMENTS_DIR)
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

AUTH_COOKIE = "magisteria_session"
PUBLIC_PATHS = {"/health", "/status", "/versao", "/login", "/cadastro"}
PUBLIC_PREFIXES = ("/static/",)


@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return await call_next(request)

    user = auth_repository.get_user_by_session(request.cookies.get(AUTH_COOKIE, ""))
    if user:
        request.state.user = user
        if path.startswith("/admin") and user["role"] != "admin":
            return JSONResponse({"detail": "Acesso administrativo restrito."}, status_code=403)
        return await call_next(request)
    if request.method == "GET":
        return RedirectResponse(url="/login", status_code=303)
    return JSONResponse({"detail": "Autenticacao necessaria."}, status_code=401)


def current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Autenticacao necessaria.")
    return dict(user)


def require_admin(request: Request) -> dict:
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso administrativo restrito.")
    return user


def form_value(fields: dict[str, list[str]], key: str) -> str:
    return fields.get(key, [""])[0].strip()


def auth_page(title: str, intro: str, action: str, fields: str, footer: str, message: str = "", error: bool = False) -> HTMLResponse:
    notice = f'<p class="{"erro" if error else "sucesso"}">{html.escape(message)}</p>' if message else ""
    return HTMLResponse(f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} - MAGISTERIA</title><style>
body{{font-family:system-ui;background:#f3efe7;display:grid;place-items:center;min-height:100vh;margin:0;color:#251d16}}
form{{background:white;padding:2rem;border-radius:18px;box-shadow:0 12px 40px #0002;width:min(400px,86vw)}}
input,button{{box-sizing:border-box;width:100%;padding:.9rem;margin-top:.8rem;border-radius:10px;font-size:1rem}}
input{{border:1px solid #9a8c7b}}button{{border:0;background:#173f2a;color:white;font-weight:700;cursor:pointer}}
a{{color:#a52a20;font-weight:700;text-decoration:none}}.erro{{color:#a11}}.sucesso{{color:#17613a}}h1{{margin:.2rem 0;color:#173f2a}}
</style></head><body><form method="post" action="{action}"><h1>MAGISTERIA</h1>
<p>{html.escape(intro)}</p>{notice}{fields}<button type="submit">{html.escape(title)}</button><p>{footer}</p></form></body></html>""")


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(erro: str = "", cadastrado: str = ""):
    message = "Login ou senha incorretos." if erro else ("Cadastro criado. Entre para continuar." if cadastrado else "")
    fields = """
<input type="text" name="email" placeholder="Email ou Admin" required autofocus>
<input type="password" name="senha" placeholder="Senha" required>
"""
    return auth_page("Entrar", "Acesse com email e senha.", "/login", fields, 'Ainda nao tem conta? <a href="/cadastro">Criar cadastro</a>.', message, bool(erro))


@app.post("/login", include_in_schema=False)
async def login(request: Request):
    fields = parse_qs((await request.body()).decode("utf-8"))
    user = auth_repository.authenticate(form_value(fields, "email"), form_value(fields, "senha"))
    if not user:
        return RedirectResponse(url="/login?erro=1", status_code=303)
    response = RedirectResponse(url="/", status_code=303)
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    response.set_cookie(
        AUTH_COOKIE,
        auth_repository.create_session(user["id"]),
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        secure=forwarded_proto == "https",
        samesite="lax",
    )
    return response


@app.get("/cadastro", response_class=HTMLResponse, include_in_schema=False)
async def register_page(erro: str = ""):
    fields = """
<input type="text" name="nome" placeholder="Nome completo" required autofocus>
<input type="email" name="email" placeholder="Email" required>
<input type="password" name="senha" placeholder="Senha" required minlength="6">
"""
    return auth_page("Criar cadastro", "Crie sua conta gratuita.", "/cadastro", fields, 'Ja tem conta? <a href="/login">Entrar</a>.', erro, bool(erro))


@app.post("/cadastro", include_in_schema=False)
async def register(request: Request):
    fields = parse_qs((await request.body()).decode("utf-8"))
    ok, message = auth_repository.create_user(
        form_value(fields, "nome"),
        form_value(fields, "email"),
        form_value(fields, "senha"),
    )
    if not ok:
        return RedirectResponse(url=f"/cadastro?erro={quote(message)}", status_code=303)
    return RedirectResponse(url="/login?cadastrado=1", status_code=303)


@app.post("/logout", include_in_schema=False)
async def logout(request: Request):
    auth_repository.delete_session(request.cookies.get(AUTH_COOKIE, ""))
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE)
    return response


@app.post("/admin/upload-chunk", include_in_schema=False)
async def upload_document_chunk(request: Request):
    require_admin(request)
    filename = Path(unquote(request.headers.get("x-filename", ""))).name
    if not filename or Path(filename).suffix.lower() not in {".pdf", ".docx", ".txt"}:
        raise HTTPException(status_code=400, detail="Nome ou formato de arquivo invalido.")
    try:
        offset = int(request.headers.get("x-offset", "0"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Offset invalido.") from exc
    uploads_dir = settings.DOCUMENTS_DIR / ".uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    partial = uploads_dir / f"{filename}.part"
    if offset == 0 and partial.exists():
        partial.unlink()
    current_size = partial.stat().st_size if partial.exists() else 0
    if current_size != offset:
        raise HTTPException(status_code=409, detail={"offset_esperado": current_size})
    chunk = await request.body()
    with partial.open("ab") as output:
        output.write(chunk)
    if request.headers.get("x-complete") == "1":
        destination = settings.DOCUMENTS_DIR / filename
        partial.replace(destination)
        auth_repository.register_document(filename, filename, destination.suffix.lower().lstrip("."))
        await perform_indexing()
        return {"arquivo": filename, "concluido": True, "bytes": destination.stat().st_size}
    return {"arquivo": filename, "concluido": False, "bytes": current_size + len(chunk)}
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
        excluded_sources=auth_repository.inactive_sources(),
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"user": current_user(request)})


@app.post("/perguntar")
async def ask(payload: QuestionRequest, request: Request):
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
    auth_repository.increment_usage(current_user(request)["id"], "query")
    return {"resposta": answer, "fontes": format_sources(chunks)}


@app.post("/perguntar-stream")
async def ask_stream(payload: QuestionRequest, request: Request):
    if indexing_state["ativa"]:
        raise HTTPException(status_code=503, detail="A base documental ainda está sendo atualizada.")

    question = payload.pergunta.strip()
    chunks = await asyncio.to_thread(ordered_chunks, payload)
    history = [turn.model_dump() for turn in payload.historico]
    if chunks and not answer_service.api_key:
        raise HTTPException(status_code=503, detail="A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")
    auth_repository.increment_usage(current_user(request)["id"], "query")

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
async def index_documents(request: Request):
    require_admin(request)
    if index_lock.locked():
        raise HTTPException(status_code=409, detail="A base documental já está sendo atualizada.")
    status = await perform_indexing()
    return {"mensagem": "Base documental atualizada com sucesso.", "status": status}


@app.post("/criar-roteiro")
async def create_script(payload: PresentationRequest, request: Request):
    try:
        topics = await presentation_service.create_outline(payload.titulo, payload.resposta)
        content = await asyncio.to_thread(presentation_service.create_docx, payload.titulo, topics)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao criar roteiro.")
        raise HTTPException(status_code=502, detail="Não foi possível criar o roteiro agora.") from exc
    auth_repository.increment_usage(current_user(request)["id"], "script")
    filename = safe_filename(payload.titulo, "roteiro.docx")
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/criar-slides")
async def create_slides(payload: PresentationRequest, request: Request):
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
    auth_repository.increment_usage(current_user(request)["id"], "presentation")
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
    auth_repository.sync_documents(discover_documents(settings.DOCUMENTS_DIR), settings.DOCUMENTS_DIR)
    active = [item["source"] for item in auth_repository.list_documents() if item["is_active"]]
    return {"documentos": active}


@app.get("/me")
async def me(request: Request):
    user = current_user(request)
    return {
        "nome": user["full_name"],
        "email": user["email"],
        "admin": user["role"] == "admin",
        "tipo_conta": user["account_type"],
        "status_assinatura": user["subscription_status"],
    }


@app.get("/admin/estatisticas")
async def admin_statistics(request: Request):
    require_admin(request)
    return {"usuarios": auth_repository.list_users()}


@app.get("/admin/base-documental")
async def admin_document_base(request: Request):
    require_admin(request)
    auth_repository.sync_documents(discover_documents(settings.DOCUMENTS_DIR), settings.DOCUMENTS_DIR)
    return {"documentos": auth_repository.list_documents()}


@app.post("/admin/base-documental/desativar")
async def deactivate_document(payload: dict, request: Request):
    require_admin(request)
    source = str(payload.get("source", "")).strip()
    if not source:
        raise HTTPException(status_code=400, detail="Documento invalido.")
    auth_repository.set_document_active(source, False)
    return {"mensagem": "Documento desativado para novas consultas."}


@app.post("/admin/base-documental/ativar")
async def activate_document(payload: dict, request: Request):
    require_admin(request)
    source = str(payload.get("source", "")).strip()
    if not source:
        raise HTTPException(status_code=400, detail="Documento invalido.")
    auth_repository.set_document_active(source, True)
    return {"mensagem": "Documento ativado para novas consultas."}


@app.post("/admin/base-documental/reindexar")
async def reindex_document_base(request: Request):
    require_admin(request)
    if index_lock.locked():
        raise HTTPException(status_code=409, detail="A base documental ja esta sendo atualizada.")
    status = await perform_indexing()
    return {"mensagem": "Base documental reindexada.", "status": status}


@app.get("/versao")
async def version():
    return {"versao": APP_VERSION}
