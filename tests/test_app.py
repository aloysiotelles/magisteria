from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import asyncio
import time

import pymupdf

from fastapi.testclient import TestClient

import app as application
from services.answer_service import AnswerService, NOT_FOUND_MESSAGE, format_abnt_references, format_sources
from services.vector_store import LocalVectorStore
from services.document_loader import load_document
from services.presentation_service import PresentationService, safe_filename


def authenticated_client() -> TestClient:
    client = TestClient(application.app)
    response = client.post("/login", data={"email": "Admin", "senha": "3510"})
    assert response.status_code == 200
    return client


def test_vector_store_indexes_and_finds_txt(tmp_path: Path):
    documents = tmp_path / "Documentos"
    documents.mkdir()
    (documents / "catequese.txt").write_text(
        "A esperança cristã está fundada na ressurreição de Jesus Cristo.", encoding="utf-8"
    )
    store = LocalVectorStore(documents, tmp_path / "index" / "indice.json", 300, 40)
    progress = []
    status = store.index_documents(lambda current, total, name: progress.append((current, total, name)))
    results = store.search("Em que está fundada a esperança cristã?", minimum_score=0.01)

    assert status["documentos"] == 1
    assert status["trechos"] == 1
    assert results[0]["source"] == "catequese.txt"
    assert progress[-1] == (1, 1, "catequese.txt")

    with patch("services.vector_store.load_document", side_effect=AssertionError("não deveria reler")):
        repeated_status = store.index_documents()

    assert repeated_status["documentos"] == 1
    assert repeated_status["trechos"] == 1


def test_pdf_fast_reader(tmp_path: Path):
    documents = tmp_path / "Documentos"
    documents.mkdir()
    pdf_path = documents / "fonte.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Documento pastoral de teste")
        pdf.save(pdf_path)

    sections = list(load_document(pdf_path, documents))

    assert sections[0].source == "fonte.pdf"
    assert sections[0].location == "página 1"
    assert "Documento pastoral" in sections[0].text
def test_explicit_source_name_filters_results(tmp_path: Path):
    documents = tmp_path / "Documentos"
    documents.mkdir()
    (documents / "Catecismo.txt").write_text("Os sacramentos comunicam a graça de Cristo.", encoding="utf-8")
    (documents / "Outro livro.txt").write_text("Os sacramentos são sinais importantes.", encoding="utf-8")
    store = LocalVectorStore(documents, tmp_path / "indice.json", 300, 40)
    store.index_documents()

    results = store.search("O que o Catecismo ensina sobre os sacramentos?", minimum_score=0)

    assert results
    assert {item["source"] for item in results} == {"Catecismo.txt"}


def test_editorial_source_order(tmp_path: Path):
    documents = tmp_path / "Documentos"
    documents.mkdir()
    fixtures = {
        "Catecismo da Igreja Católica.txt": "A caridade nasce do amor de Deus.",
        "compendio-dos-simbolos-definicoes-e-declaracoes-de-fe-e-moral.txt": "A caridade é uma virtude.",
        "compendio-da-doutrina-social-da-igreja.txt": "A caridade orienta a vida social.",
        "Suma Teológica.txt": "A caridade une a pessoa a Deus.",
        "Bíblia Ave Maria - Edição de Estudo.txt": "A caridade é paciente.",
        "Compêndio Vaticano II.txt": "A caridade manifesta a comunhão da Igreja.",
        "Documento complementar.txt": "A caridade transforma a comunidade.",
    }
    for name, text in fixtures.items():
        (documents / name).write_text(text, encoding="utf-8")
    store = LocalVectorStore(documents, tmp_path / "indice.json", 300, 40)
    store.index_documents()

    results = store.search_ordered("O que é a caridade?", minimum_score=0)

    categories = list(dict.fromkeys(item["categoria"] for item in results))
    assert categories[:6] == [
        "Catecismo da Igreja Católica",
        "Compêndio dos símbolos, definições e declarações",
        "Compêndio da Doutrina Social da Igreja",
        "Suma Teológica",
        "Bíblia Ave Maria — citações bíblicas",
        "Compêndio Vaticano II",
    ]
    assert categories[-1] == "Demais documentos"


def test_editorial_bonus_does_not_make_irrelevant_chunk_relevant(tmp_path: Path):
    documents = tmp_path / "Documentos"
    documents.mkdir()
    (documents / "Catecismo da Igreja Católica.txt").write_text(
        "A música litúrgica acompanha a celebração.", encoding="utf-8"
    )
    store = LocalVectorStore(documents, tmp_path / "indice.json", 300, 40)
    store.index_documents()

    results = store.search_ordered(
        "Explique detalhadamente a engenharia de foguetes interplanetários.",
        minimum_score=0.08,
    )

    assert results == []


def test_stream_continues_after_output_limit(monkeypatch):
    class AsyncEvents:
        def __init__(self, events):
            self.events = iter(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.events)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeResponses:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            response_id = f"resposta-{self.calls}"
            events = [
                SimpleNamespace(type="response.created", response=SimpleNamespace(id=response_id)),
                SimpleNamespace(type="response.output_text.delta", delta="Texto interrompido" if self.calls == 1 else " e concluído."),
                SimpleNamespace(
                    type="response.incomplete" if self.calls == 1 else "response.completed",
                    response=SimpleNamespace(id=response_id),
                ),
            ]
            return AsyncEvents(events)

    fake_responses = FakeResponses()
    monkeypatch.setattr(
        "services.answer_service.AsyncOpenAI",
        lambda api_key: SimpleNamespace(responses=fake_responses),
    )
    service = AnswerService("chave", "modelo")
    chunks = [{"source": "Catecismo.txt", "location": "página 1", "text": "Trecho", "score": 1.0}]

    async def collect():
        return "".join([part async for part in service.stream_answer("Pergunta", chunks)])

    answer = asyncio.run(collect())

    assert answer == "Texto interrompido e concluído."
    assert fake_responses.calls == 2


def test_answer_prompt_requires_consolidated_text():
    service = AnswerService("chave", "modelo")
    chunks = [{"source": "Catecismo.txt", "location": "página 1", "text": "Trecho", "score": 1.0}]

    instructions = service._request_arguments("Pergunta", chunks, [])["instructions"]

    assert "uma única síntese consolidada" in instructions
    assert "Não informe nem liste as fontes no corpo" in instructions


def test_source_references_use_document_specific_locators():
    chunks = [
        {"source": "Catecismo da Igreja Católica.pdf", "location": "página 1", "text": "", "score": 1.0, "referencias": ["1210", "1211", "1212"], "categoria": "Catecismo"},
        {"source": "Bíblia Ave Maria - Edição de Estudo.pdf", "location": "São João, página 2", "text": "", "score": 1.0, "referencias": ["Jo 1,2-5"], "categoria": "Bíblia"},
        {"source": "Compêndio Vaticano II.pdf", "location": "página 16", "text": "", "score": 1.0, "referencias": ["Lumen Gentium, n. 1"], "categoria": "Compêndio Vaticano II"},
    ]

    sources = format_sources(chunks)
    abnt = format_abnt_references(chunks)

    assert sources[0]["local"] == "§§ 1210–1212"
    assert sources[1]["local"] == "Jo 1,2-5"
    assert sources[2]["local"] == "Lumen Gentium, n. 1"
    assert "IGREJA CATÓLICA" in abnt
    assert "BÍBLIA. Português." in abnt
    assert "CONCÍLIO VATICANO II" in abnt


def test_routes_and_closed_base_behavior(monkeypatch):
    client = authenticated_client()
    monkeypatch.setattr(application.vector_store, "search_ordered", lambda *args, **kwargs: [])

    assert client.get("/").status_code == 200
    assert client.get("/health").json()["status"] == "ok"
    status_response = client.get("/status")
    assert status_response.status_code == 200
    assert {"documentos", "trechos", "ultima_atualizacao", "erros"} <= set(status_response.json())
    documents_response = client.get("/documentos")
    assert documents_response.status_code == 200
    assert "documentos" in documents_response.json()
    version_response = client.get("/versao")
    assert version_response.status_code == 200
    assert version_response.json()["versao"] == application.APP_VERSION

    answer_response = client.post("/perguntar", json={"pergunta": "Assunto ausente na base"})
    assert answer_response.status_code == 200
    assert answer_response.json() == {"resposta": NOT_FOUND_MESSAGE, "fontes": []}
    stream_response = client.post("/perguntar-stream", json={"pergunta": "Assunto ausente na base"})
    assert stream_response.status_code == 200
    assert '"tipo": "texto"' in stream_response.text
    assert NOT_FOUND_MESSAGE in stream_response.text


def test_question_validation():
    client = authenticated_client()
    assert client.post("/perguntar", json={"pergunta": "x"}).status_code == 422


def test_startup_reindexes_documents(monkeypatch):
    calls = []
    monkeypatch.setattr(application.vector_store, "index_documents", lambda *args: calls.append(True) or {})

    with TestClient(application.app):
        pass

    assert calls == [True]


def test_script_and_slides_routes(monkeypatch):
    client = authenticated_client()
    topics = [{"titulo": "Esperança", "sintese": "Síntese pastoral.", "pontos": ["Primeiro ponto", "Segundo ponto"]}]

    async def outline(*args):
        return topics

    async def plan(*args):
        return {"titulo_curto": "Esperança que transforma", "frase_final": "A esperança renova a vida.", "topicos": topics}

    async def slides(*args):
        return b"pptx"

    monkeypatch.setattr(application.presentation_service, "create_outline", outline)
    monkeypatch.setattr(application.presentation_service, "create_plan", plan)
    monkeypatch.setattr(application.presentation_service, "create_pptx", slides)
    payload = {"titulo": "A esperança cristã", "resposta": "Conteúdo suficientemente longo para gerar materiais."}
    docx = client.post("/criar-roteiro", json=payload)
    pptx = client.post("/criar-slides", json=payload)

    assert docx.status_code == 200
    assert docx.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert pptx.status_code == 200
    assert pptx.content == b"pptx"


def test_generated_docx_and_safe_filename():
    service = PresentationService("", "modelo")
    content = service.create_docx("Fé e esperança", [{"titulo": "Abertura", "sintese": "Uma síntese.", "pontos": ["Um", "Dois"]}])
    assert content.startswith(b"PK")
    assert safe_filename("Fé e esperança", "roteiro.docx") == "fe-e-esperanca-roteiro.docx"


def test_slide_images_are_generated_in_parallel(monkeypatch):
    service = PresentationService("", "modelo", image_concurrency=4)

    async def fake_image(*args):
        await asyncio.sleep(0.05)
        return object()

    monkeypatch.setattr(service, "_generate_image", fake_image)
    topics = [{"titulo": str(index)} for index in range(4)]
    started = time.monotonic()
    images = asyncio.run(service._generate_images("Título", topics))

    assert len(images) == 4
    assert time.monotonic() - started < 0.15


def test_one_failed_image_is_retried_without_losing_the_others(monkeypatch):
    service = PresentationService("", "modelo", image_concurrency=3)
    attempts = {"instavel": 0}

    async def fake_image(_, topic):
        if topic["titulo"] == "instavel":
            attempts["instavel"] += 1
            if attempts["instavel"] == 1:
                raise ValueError("falha temporária")
        return topic["titulo"]

    async def no_wait(*args):
        return None

    monkeypatch.setattr(service, "_generate_image", fake_image)
    monkeypatch.setattr("services.presentation_service.asyncio.sleep", no_wait)
    topics = [{"titulo": "estavel"}, {"titulo": "instavel"}]

    images = asyncio.run(service._generate_images("Título", topics))

    assert images == ["estavel", "instavel"]
    assert attempts["instavel"] == 2
def test_cover_and_closing_images_are_not_hidden_by_black_shapes():
    from io import BytesIO
    from PIL import Image
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    image = BytesIO()
    Image.new("RGB", (320, 180), (120, 90, 60)).save(image, "JPEG")
    image.seek(0)
    prs = Presentation()
    PresentationService._add_title_slide(prs, "Título breve", image)
    image.seek(0)
    PresentationService._add_closing_slide(prs, "Síntese final.", image)

    for slide in (prs.slides[-2], prs.slides[-1]):
        assert slide.shapes[0].shape_type == MSO_SHAPE_TYPE.PICTURE
        assert all(shape.shape_type in {MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.TEXT_BOX} for shape in slide.shapes)


def test_password_protects_application_and_health_is_public():
    client = TestClient(application.app)
    assert client.get("/health").status_code == 200
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.post("/login", data={"email": "Admin", "senha": "3510"}).status_code == 200
    assert client.get("/").status_code == 200
