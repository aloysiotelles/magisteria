from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as application

from services.auth_repository import AuthRepository
from services.response_planning import DepthLevel, build_response_plan
from services.response_quality import CoverageValidator
from services.retrieval_orchestrator import RetrievalOrchestrator
from services.search_history import UserSearchHistory
from services.semantic_cache import SemanticCache


@pytest.mark.parametrize(
    ("question", "topic", "depth", "component_count"),
    (
        ("Explique a Santíssima Trindade e cada uma das Pessoas Divinas.", "trindade", "aprofundado", 7),
        ("Explique os Dez Mandamentos.", "dez_mandamentos", "aprofundado", 10),
        ("Quais são os sete sacramentos?", "sacramentos", "aprofundado", 7),
        ("Faça um resumo dos sete sacramentos.", "sacramentos", "resumido", 7),
        ("Explique os dogmas marianos e detalhe cada um.", "dogmas_marianos", "aprofundado", 4),
    ),
)
def test_required_composite_queries_are_planned(question, topic, depth, component_count):
    plan = build_response_plan(question)

    assert plan.topic_key == topic
    assert plan.depth == depth
    assert plan.composite is True
    assert len(plan.components) == component_count
    assert plan.introduction_required is True
    assert plan.source_types


def test_bible_uses_catholic_canon_without_omitting_items():
    plan = build_response_plan("Explique a Bíblia Católica, suas divisões e cada livro.")

    assert plan.topic_key == "biblia_catolica"
    assert len(plan.components) == 73
    assert "Tobias" in plan.components
    assert "2 Macabeus" in plan.components
    assert plan.continuation_required is False
    assert plan.active_components == plan.components
    assert plan.max_output_tokens > 5000


def test_simple_prayer_query_remains_economical():
    plan = build_response_plan("O que é oração?")

    assert plan.depth == DepthLevel.EXPLANATORY.value
    assert plan.composite is False
    assert plan.components == ()
    assert plan.max_context_tokens < build_response_plan("Explique os Dez Mandamentos.").max_context_tokens
    assert plan.max_output_tokens < 2400  # limite fixo anterior


def test_implicit_composite_query_uses_taxonomy():
    plan = build_response_plan("Quero compreender os sacramentos da Igreja Católica.")

    assert plan.topic_key == "sacramentos"
    assert plan.composite is True
    assert plan.components[0] == "Batismo"
    assert plan.components[-1] == "Matrimônio"


def test_closed_set_topic_alone_still_requires_the_complete_set():
    plan = build_response_plan("Sacramentos")

    assert plan.composite is True
    assert len(plan.active_components) == 7


def test_singular_sacrament_definition_does_not_expand_to_all_seven():
    plan = build_response_plan("O que é um sacramento?")

    assert plan.topic_key != "sacramentos"
    assert plan.composite is False


@pytest.mark.parametrize(
    ("question", "topic", "count"),
    (
        ("Explique os cinco mandamentos da Igreja.", "mandamentos_igreja", 5),
        ("Explique as virtudes teologais.", "virtudes_teologais", 3),
        ("Explique as obras de misericórdia corporais.", "obras_misericordia_corporais", 7),
        ("Explique os 21 concílios ecumênicos.", "concilios_ecumenicos", 21),
        ("Explique os documentos do Vaticano II.", "documentos_vaticano_ii", 16),
    ),
)
def test_additional_closed_sets_activate_every_canonical_item(question, topic, count):
    plan = build_response_plan(question)

    assert plan.topic_key == topic
    assert plan.closed_set is True
    assert len(plan.components) == count
    assert plan.active_components == plan.components


def test_open_historical_catalog_declares_scope_instead_of_inventing_closed_list():
    plan = build_response_plan("Explique as encíclicas da Igreja.")

    assert plan.topic_key == "catalogos_documentais"
    assert plan.composite is True
    assert plan.closed_set is False
    assert "não possui uma enumeração universal" in plan.catalog_scope


def test_semantically_equivalent_sacrament_queries_share_document_signature():
    queries = (
        "Quais são os sacramentos?",
        "Explique os sete sacramentos.",
        "O que são os sacramentos católicos?",
        "Faça um estudo sobre cada sacramento.",
    )
    plans = [build_response_plan(query) for query in queries]

    assert all(plan.topic_key == "sacramentos" for plan in plans)
    assert all(plan.composite for plan in plans)
    assert len({plan.semantic_signature for plan in plans}) == 1


def test_coverage_validator_requires_every_component_and_real_source_markers():
    plan = build_response_plan("Explique os dogmas marianos e detalhe cada um.")
    explanation = (
        "A formulação é apresentada com contexto, significado cristológico, relação com a vida da Igreja "
        "e distinções doutrinais suficientes para evitar uma menção meramente nominal. "
    )
    answer = "\n".join((
        f"Maternidade divina: {explanation * 2}[F1].",
        f"Virgindade perpétua: {explanation * 2}[F2].",
        f"Imaculada Conceição: {explanation * 2}[F3].",
        f"Assunção: {explanation * 2}[F4].",
    ))

    result = CoverageValidator().validate_answer(plan, answer, 4)
    invalid = CoverageValidator().validate_answer(plan, answer.replace("[F4]", "[F9]"), 4)

    assert result.passed is True
    assert invalid.passed is False
    assert invalid.invalid_citations == ("F9",)


class FakeVectorStore:
    def __init__(self):
        self.version = "corpus-1"
        self.calls: list[str] = []
        self.index_file = Path("indice-teste.sqlite")

    def status(self):
        return {"ultima_atualizacao": self.version}

    def search_ordered(self, query, **kwargs):
        self.calls.append(query)
        index = len(self.calls)
        chunk = {
            "id": f"chunk-{index}",
            "source": "Catecismo da Igreja Católica.txt",
            "location": f"§ {100 + index}",
            "text": f"Evidência documental específica para {query}.",
            "score": 1.0,
            "score_normalized": 0.8,
            "ordem": 1,
            "categoria": "Catecismo da Igreja Católica",
            "referencias": [str(100 + index)],
        }
        return [chunk], {
            "candidates_fused": 1,
            "final_count": 1,
            "candidate_counts": {"lexical": 1},
        }


def test_layered_retrieval_cache_and_corpus_invalidation(tmp_path: Path):
    database = tmp_path / "magisteria.sqlite"
    AuthRepository(database)
    cache = SemanticCache(database, 3600)
    vector = FakeVectorStore()
    orchestrator = RetrievalOrchestrator(vector, cache)
    plan = build_response_plan("Quais são os sete sacramentos?")
    similar_plan = build_response_plan("O que são os sacramentos católicos?")

    first = orchestrator.retrieve("sete sacramentos", plan, minimum_score=0.01)
    calls_after_first = len(vector.calls)
    second = orchestrator.retrieve(
        "O que são os sacramentos católicos?", similar_plan, minimum_score=0.01
    )
    with cache._connect() as db:
        cached_payload = db.execute("SELECT chunks_json FROM semantic_cache_entries").fetchone()[0]
        summary = db.execute(
            "SELECT subtopics_json, keywords_json, related_documents_json "
            "FROM document_technical_summaries"
        ).fetchone()
    vector.version = "corpus-2"
    third = orchestrator.retrieve("sete sacramentos", plan, minimum_score=0.01)

    assert first.cache_hit is False
    assert calls_after_first == 9  # visão geral + taxonomia + um bloco por sacramento
    assert second.cache_hit is True
    assert "answer" not in cached_payload.lower()
    assert "Batismo" in summary[0]
    assert "sacramentos" in summary[1].lower()
    assert summary[2] == "[]"
    assert len(vector.calls) > calls_after_first
    assert third.cache_hit is False


def test_history_is_private_requeryable_and_consolidates_duplicates(tmp_path: Path):
    database = tmp_path / "history.sqlite"
    repository = AuthRepository(database)
    assert repository.create_user("Primeiro Usuario", "first@example.com", "SenhaForte1")[0]
    assert repository.create_user("Segundo Usuario", "second@example.com", "SenhaForte1")[0]
    first_user = repository.find_user_by_login("first@example.com")
    second_user = repository.find_user_by_login("second@example.com")
    history = UserSearchHistory(database, store_original_query=True)
    plan = build_response_plan("Explique os dogmas marianos e detalhe cada um.")

    saved = history.record(first_user["id"], "Explique os dogmas marianos e detalhe cada um.", plan)
    repeated = history.record(first_user["id"], "Quero estudar todos os dogmas marianos.", plan)

    assert len(history.list(first_user["id"])) == 1
    assert repeated["search_count"] == 2
    assert history.list(second_user["id"]) == []
    assert history.get_for_requery(second_user["id"], saved["id"]) is None
    assert history.get_for_requery(first_user["id"], saved["id"])["query"].startswith("Quero estudar")
    assert history.delete(second_user["id"], saved["id"]) is False
    assert history.delete(first_user["id"], saved["id"]) is True


def test_account_deletion_cascades_search_history(tmp_path: Path):
    database = tmp_path / "delete-history.sqlite"
    repository = AuthRepository(database)
    assert repository.create_user("Usuario Teste", "delete-history@example.com", "SenhaForte1")[0]
    user = repository.find_user_by_login("delete-history@example.com")
    history = UserSearchHistory(database)
    history.record(user["id"], "O que é oração?", build_response_plan("O que é oração?"))

    assert repository.delete_account(user["id"], "SenhaForte1")[0] is True
    assert history.list(user["id"]) == []


def test_mobile_history_endpoints_enforce_owner_and_requery(tmp_path: Path, monkeypatch):
    database = tmp_path / "history-api.sqlite"
    repository = AuthRepository(database)
    monkeypatch.setattr(application, "auth_repository", repository)
    assert repository.create_user("Primeiro Usuario", "history-one@example.com", "SenhaForte1")[0]
    assert repository.create_user("Segundo Usuario", "history-two@example.com", "SenhaForte1")[0]
    first = repository.find_user_by_login("history-one@example.com")
    history = UserSearchHistory(database)
    saved = history.record(
        first["id"],
        "Explique os Dez Mandamentos.",
        build_response_plan("Explique os Dez Mandamentos."),
    )
    client = TestClient(application.app)

    def login(email: str) -> dict[str, str]:
        payload = client.post(
            "/api/v1/mobile/auth/login",
            json={"email": email, "password": "SenhaForte1"},
        ).json()
        return {"Authorization": f"Bearer {payload['access_token']}"}

    first_headers = login("history-one@example.com")
    second_headers = login("history-two@example.com")

    assert client.get("/api/v1/mobile/history", headers=first_headers).json()["items"][0]["id"] == saved["id"]
    assert client.get("/api/v1/mobile/history", headers=second_headers).json()["items"] == []
    assert client.get(
        f"/api/v1/mobile/history/{saved['id']}/requery", headers=second_headers
    ).status_code == 404
    requery = client.get(
        f"/api/v1/mobile/history/{saved['id']}/requery", headers=first_headers
    )
    assert requery.status_code == 200
    assert requery.json()["query"] == "Explique os Dez Mandamentos."
    assert client.delete(
        f"/api/v1/mobile/history/{saved['id']}", headers=second_headers
    ).status_code == 404
    assert client.delete(
        f"/api/v1/mobile/history/{saved['id']}", headers=first_headers
    ).status_code == 204


def test_composite_query_migration_has_safe_feature_rollback(tmp_path: Path):
    database = tmp_path / "rollback.sqlite"
    repository = AuthRepository(database)
    migration_dir = Path(__file__).resolve().parents[1] / "migrations"

    with repository._connect() as db:
        assert db.execute(
            "SELECT 1 FROM schema_migrations WHERE version = '0001_composite_queries'"
        ).fetchone()
        assert db.execute(
            "SELECT 1 FROM schema_migrations WHERE version = '0002_document_summary_index'"
        ).fetchone()
        assert db.execute(
            "SELECT 1 FROM schema_migrations WHERE version = '0003_document_summary_metadata'"
        ).fetchone()
        db.executescript(
            (migration_dir / "0003_document_summary_metadata.down.sql").read_text(encoding="utf-8")
        )
        db.executescript(
            (migration_dir / "0002_document_summary_index.down.sql").read_text(encoding="utf-8")
        )
        db.executescript((migration_dir / "0001_composite_queries.down.sql").read_text(encoding="utf-8"))
        tables = {
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        applied_versions = {
            row[0] for row in db.execute("SELECT version FROM schema_migrations").fetchall()
        }

    assert "users" in tables
    assert "user_search_history" not in tables
    assert "semantic_cache_entries" not in tables
    assert "document_technical_summaries" not in tables
    assert "0001_composite_queries" not in applied_versions
    assert "0002_document_summary_index" not in applied_versions
    assert "0003_document_summary_metadata" not in applied_versions
