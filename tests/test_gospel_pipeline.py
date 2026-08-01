from __future__ import annotations

from pathlib import Path

import pytest

from services.answer_service import AnswerService, format_sources
from services.auth_repository import AuthRepository
from services.gospel_policy import (
    CATENA_COLLECTION,
    GOSPEL_QUERY,
    ORDINARY_QUERY,
    classify_gospel_query,
)
from services.response_planning import build_response_plan
from services.response_quality import PatristicAttributionValidator
from services.retrieval_orchestrator import RetrievalOrchestrator
from services.semantic_cache import SemanticCache
from services.vector_store import LocalVectorStore


@pytest.mark.parametrize(
    ("question", "episode", "reference"),
    (
        ("Explique Mateus 5,1-12.", "bem_aventurancas", "Mt 5,1–12"),
        ("Explique a parábola do filho pródigo.", "filho_prodigo", "Lc 15,11–32"),
        ("Qual é o significado da multiplicação dos pães?", "multiplicacao_paes", "Jo 6,1–15"),
        ("Prepare uma homilia sobre os discípulos de Emaús.", "emaus", "Lc 24,13–35"),
        ("Por que Jesus chorou diante do túmulo de Lázaro?", "ressurreicao_lazaro", "Jo 11,1–46"),
    ),
)
def test_gospel_classifier_recognizes_references_traditional_names_and_indirect_questions(
    question: str,
    episode: str,
    reference: str,
):
    context = classify_gospel_query(question)

    assert context.classification == GOSPEL_QUERY
    assert context.episode_key == episode
    assert reference in context.passage_references


def test_non_gospel_query_keeps_the_ordinary_pipeline():
    context = classify_gospel_query("Explique o dogma da Imaculada Conceição.")

    assert context.classification == ORDINARY_QUERY
    assert context.passages == ()


def test_broad_passion_is_decomposed_and_pastoral_request_stays_gospel():
    passion = build_response_plan("Explique a Paixão de Cristo segundo os Padres da Igreja.")
    homily = build_response_plan("Prepare uma homilia sobre os discípulos de Emaús.")

    assert passion.is_gospel is True
    assert passion.composite is True
    assert passion.active_components == (
        "Última Ceia", "Getsêmani", "prisão", "julgamento religioso",
        "julgamento perante Pilatos", "flagelação", "coroação de espinhos",
        "caminho do Calvário", "Crucifixão", "palavras na Cruz", "morte", "sepultamento",
    )
    assert passion.gospel.parallel_references == ("Mc 14–15", "Lc 22–23", "Jo 18–19")
    assert homily.is_gospel is True
    assert "pastoral" in homily.intents


def test_catena_indexing_adds_structured_metadata_authors_and_adjacency(tmp_path: Path):
    documents = tmp_path / "Documentos"
    documents.mkdir()
    catena = """# Catena Áurea
# Evangelho segundo São Mateus
## Capítulo 5
### Lição 1
> Vendo aquelas multidões, Jesus subiu à montanha. 2 Então abriu a boca e ensinava. 3 Bem-aventurados os pobres em espírito.

**Agostinho, sobre o Sermão do Senhor**: A montanha indica a altura dos preceitos e a humildade abre o Reino.

**Crisóstomo, sobre Mateus**: Cristo ensina aos discípulos e, por eles, dirige a palavra a todos.

**Jerônimo, sobre Mateus**: Os pobres em espírito não buscam vanglória, mas recebem o Reino.

**Ambrósio, sobre Lucas**: A bem-aventurança conduz da pobreza à plenitude da justiça.

**Gregório, Moralia**: A humildade guarda os bens espirituais contra a soberba.

**Beda**: A subida ao monte manifesta a sublimidade da doutrina evangélica.

**Orígenes**: O discípulo sobe espiritualmente quando acolhe a palavra de Cristo.

**Hilário**: A promessa do Reino revela a dignidade dos filhos de Deus.

**Remígio**: Sentar-se para ensinar convém à autoridade do Mestre divino.

**Pseudo-Crisóstomo sobre Mateus**: A multidão ouve, mas os discípulos se aproximam para viver o ensinamento.
"""
    (documents / "Catena Áurea - Santo Tomás de Aquino.md").write_text(catena, encoding="utf-8")
    store = LocalVectorStore(documents, tmp_path / "indice.sqlite", 220, 25)

    status = store.index_documents()
    results, diagnostics = store.search_ordered(
        "Bem-aventuranças pobres em espírito",
        limit=30,
        minimum_score=0,
        source_filter=("catena aurea",),
        metadata_filters={"collection": CATENA_COLLECTION, "gospel": "Mateus", "chapter": 5},
        include_diagnostics=True,
    )

    assert status["catena_aurea"]["documentos"] == 1
    assert status["catena_aurea"]["trechos"] >= 10
    assert diagnostics["structured_metadata_filters"]["collection"] == CATENA_COLLECTION
    assert results
    assert all(item["collection"] == CATENA_COLLECTION for item in results)
    assert all(item["gospel"] == "Mateus" and item["chapter"] == 5 for item in results)
    assert any("Agostinho" in item.get("patristic_authors", []) for item in results)
    assert any(item.get("previous_chunk_id") or item.get("next_chunk_id") for item in results)


def test_catena_metadata_migration_rolls_back_without_deleting_indexed_documents(tmp_path: Path):
    documents = tmp_path / "Documentos"
    documents.mkdir()
    (documents / "Catena Áurea.md").write_text(
        "# Catena Áurea\n# Evangelho segundo São Lucas\n## Capítulo 15\n### Lição 1\n"
        "> Um homem tinha dois filhos.\n\n**Agostinho**: A misericórdia acolhe quem retorna.",
        encoding="utf-8",
    )
    store = LocalVectorStore(documents, tmp_path / "indice.sqlite", 220, 25)
    store.index_documents()
    rollback = Path(__file__).resolve().parents[1] / "vector_migrations" / "0001_catena_chunk_metadata.down.sql"

    with store._connect() as db:
        chunk_count_before = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        db.executescript(rollback.read_text(encoding="utf-8"))
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        chunk_count_after = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    assert "chunk_metadata" not in tables
    assert chunk_count_before == chunk_count_after > 0


class GospelFakeVectorStore:
    def __init__(self, *, catena_available: bool = True):
        self.corpus_version = "corpus-1"
        self.catena_version = "catena-1"
        self.catena_available = catena_available
        self.calls: list[dict] = []
        self.index_file = Path("gospel-fake.sqlite")

    def status(self):
        return {"ultima_atualizacao": self.corpus_version}

    def collection_version(self, collection: str):
        assert collection == CATENA_COLLECTION
        return self.catena_version

    def search_ordered(self, query: str, **kwargs):
        call = {"query": query, **kwargs}
        self.calls.append(call)
        source_filter = tuple(kwargs.get("source_filter") or ())
        metadata = dict(kwargs.get("metadata_filters") or {})
        if any("catena" in value for value in source_filter):
            if not self.catena_available:
                return [], {"candidates_fused": 0, "final_count": 0, "candidate_counts": {}}
            gospel = str(metadata.get("gospel") or "Mateus")
            chapter = int(metadata.get("chapter") or 14)
            names = (
                "Agostinho", "Crisóstomo", "Jerônimo", "Ambrósio", "Gregório",
                "Beda", "Orígenes", "Hilário", "Remígio", "Pseudo-Crisóstomo",
            )
            chunks = []
            for number, author in enumerate(names, 1):
                chunks.append({
                    "id": f"catena-{gospel}-{chapter}-{number}",
                    "source": "Catena Áurea - Santo Tomás de Aquino.md",
                    "location": f"{gospel} {chapter}, lição {number}",
                    "text": f"**{author}**: comentário materialmente distinto {number} sobre Cristo, fé e vida espiritual.",
                    "score": 1.0 - number / 100,
                    "score_normalized": 0.8,
                    "collection": CATENA_COLLECTION,
                    "work": "Catena Áurea",
                    "compiler": "Santo Tomás de Aquino",
                    "gospel": gospel,
                    "chapter": chapter,
                    "verse_start": metadata.get("verse_start"),
                    "verse_end": metadata.get("verse_end"),
                    "patristic_author": author,
                    "patristic_authors": [author],
                    "attributions": [{"author": author, "source_work": "", "label": author}],
                    "referencias": [f"{gospel} {chapter}"],
                })
            return chunks[: kwargs.get("limit", 14)], {
                "candidates_fused": len(chunks),
                "final_count": min(len(chunks), kwargs.get("limit", 14)),
                "candidate_counts": {"structured_metadata": len(chunks)},
            }
        if any(value in {"biblia", "sagrada escritura"} for value in source_filter):
            chunks = [{
                "id": "scripture-1",
                "source": "Bíblia Ave Maria.txt",
                "location": "Evangelho",
                "text": "Jesus tomou os pães, deu graças e os distribuiu à multidão.",
                "score": 0.95,
                "score_normalized": 0.75,
                "referencias": ["Jo 6,11"],
            }]
        else:
            chunks = [{
                "id": f"repository-{len(self.calls)}",
                "source": "Catecismo da Igreja Católica.txt",
                "location": "§ 1335",
                "text": "Os milagres da multiplicação dos pães prefiguram a superabundância da Eucaristia.",
                "score": 0.8,
                "score_normalized": 0.68,
                "referencias": ["1335"],
            }]
        return chunks, {"candidates_fused": len(chunks), "final_count": len(chunks), "candidate_counts": {}}

    def fetch_adjacent_chunks(self, chunk_ids, **kwargs):
        if not self.catena_available or not chunk_ids:
            return []
        return [{
            "id": "catena-adjacent",
            "source": "Catena Áurea - Santo Tomás de Aquino.md",
            "location": "continuação",
            "text": "**Teofilacto**: comentário adjacente que completa a interpretação patrística.",
            "score": 0.45,
            "score_normalized": 0.31,
            "collection": CATENA_COLLECTION,
            "work": "Catena Áurea",
            "compiler": "Santo Tomás de Aquino",
            "gospel": "João",
            "chapter": 6,
            "patristic_authors": ["Teofilacto"],
            "attributions": [{"author": "Teofilacto", "source_work": "", "label": "Teofilacto"}],
        }]


def _orchestrator(tmp_path: Path, vector: GospelFakeVectorStore) -> RetrievalOrchestrator:
    database = tmp_path / "magisteria.sqlite"
    AuthRepository(database)
    return RetrievalOrchestrator(vector, SemanticCache(database, 3600))


def test_catena_search_is_exclusive_first_iterative_and_covers_parallel_gospels(tmp_path: Path):
    vector = GospelFakeVectorStore()
    orchestrator = _orchestrator(tmp_path, vector)
    plan = build_response_plan("Qual o significado da multiplicação dos pães?")

    bundle = orchestrator.retrieve("multiplicação dos pães", plan, minimum_score=0.01)
    first_complement = next(
        index for index, call in enumerate(vector.calls)
        if not any("catena" in value for value in tuple(call.get("source_filter") or ()))
    )

    assert all(
        any("catena" in value for value in tuple(call.get("source_filter") or ()))
        for call in vector.calls[:first_complement]
    )
    assert bundle.diagnostics["catena_search_executed"] is True
    assert bundle.diagnostics["catena_filter_applied"] is True
    assert bundle.diagnostics["catena_chunks_retrieved"] >= 10
    assert bundle.diagnostics["adjacent_chunks_loaded"] == 1
    assert bundle.diagnostics["parallel_passages_searched"] == [
        "Mc 6,30–44", "Lc 9,10–17", "Jo 6,1–15"
    ]
    searched_pairs = {
        (call.get("metadata_filters") or {}).get("gospel")
        for call in vector.calls[:first_complement]
    }
    assert {"Mateus", "Marcos", "Lucas", "João"} <= searched_pairs
    assert any(chunk.get("collection") == CATENA_COLLECTION for chunk in bundle.chunks)
    assert any(chunk.get("gospel_priority") == 1 for chunk in bundle.chunks)


def test_gospel_cache_key_includes_catena_version_and_policy(tmp_path: Path):
    vector = GospelFakeVectorStore()
    orchestrator = _orchestrator(tmp_path, vector)
    plan = build_response_plan("Explique a parábola do filho pródigo.")

    first = orchestrator.retrieve("filho pródigo", plan, minimum_score=0.01)
    calls_after_first = len(vector.calls)
    second = orchestrator.retrieve("filho pródigo", plan, minimum_score=0.01)
    vector.catena_version = "catena-2"
    third = orchestrator.retrieve("filho pródigo", plan, minimum_score=0.01)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(vector.calls) == calls_after_first * 2
    assert third.cache_hit is False


def test_catena_failure_is_retried_logged_in_diagnostics_and_never_faked(tmp_path: Path):
    vector = GospelFakeVectorStore(catena_available=False)
    orchestrator = _orchestrator(tmp_path, vector)
    plan = build_response_plan("Prepare uma homilia sobre os discípulos de Emaús.")

    bundle = orchestrator.retrieve("discípulos de Emaús", plan, minimum_score=0.01)
    arguments = AnswerService("", "test-model")._request_arguments(
        "Prepare uma homilia sobre os discípulos de Emaús.", bundle.chunks, [], [], "pt-BR", plan
    )

    assert bundle.diagnostics["catena_chunks_retrieved"] == 0
    assert bundle.diagnostics["complementary_repository_search_executed"] is True
    assert bundle.diagnostics["completeness_validation_status"] == "incomplete_after_retries"
    assert bundle.diagnostics["catena_exhaustion"]["searches"] >= 1
    assert "não diga que ela foi consultada" in arguments["instructions"].lower()


def test_unconfirmed_patristic_author_is_not_accepted_and_sources_remain_traceable():
    chunks = [{
        "id": "anonymous-catena",
        "source": "Catena Áurea - Santo Tomás de Aquino.md",
        "location": "Lc 15, lição 3",
        "text": "O comentário reunido na Catena observa a misericórdia do pai.",
        "score": 1.0,
        "collection": CATENA_COLLECTION,
        "work": "Catena Áurea",
        "compiler": "Santo Tomás de Aquino",
        "gospel": "Lucas",
        "chapter": 15,
        "referencias": ["Lc 15,11–32"],
        "patristic_authors": [],
        "citation_index": 1,
    }]
    validator = PatristicAttributionValidator()

    assert validator.validate("Segundo Santo Agostinho, o pai representa Deus [F1].", chunks) == ("agostinho",)
    assert validator.validate("O comentário reunido na Catena Áurea observa a misericórdia [F1].", chunks) == ()
    source = format_sources(chunks)[0]
    assert source["colecao"] == CATENA_COLLECTION
    assert source["compilador"] == "Santo Tomás de Aquino"
    assert source["passagens_evangelicas"] == ["Lc 15,11–32"]
    assert source["autores_patristicos"] == []
