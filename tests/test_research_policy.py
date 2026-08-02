from pathlib import Path

from services.answer_service import AnswerService
from services.auth_repository import AuthRepository
from services.research_policy import build_research_directive, match_doctrine_profile
from services.response_planning import build_response_plan
from services.retrieval_orchestrator import RetrievalOrchestrator
from services.semantic_cache import SemanticCache


def test_structured_doctrine_uses_exact_catechism_range_and_complete_aspects():
    question = "Aprofunde completamente o Quinto Mandamento."
    plan = build_response_plan(question)
    directive = build_research_directive(question, plan)

    assert plan.topic_key == "mandamento_5"
    assert plan.composite
    assert "aborto" in plan.components
    assert "eutanásia" in plan.components
    assert directive.catechism_ranges == ("CIC 2258–2330",)
    assert {lane.key for lane in directive.source_lanes} == {
        "catechism_mandamento_5", "faith_explained", "summa",
    }


def test_all_sacraments_receive_individual_catechism_research_lanes():
    question = "Explique todos os sete sacramentos."
    plan = build_response_plan(question)
    directive = build_research_directive(question, plan)

    catechism_lanes = [lane for lane in directive.source_lanes if lane.key.startswith("catechism_")]
    assert len(plan.components) == 7
    assert len(catechism_lanes) == 7
    assert "CIC 1113–1134" in directive.catechism_ranges
    assert "CIC 1213–1284" in directive.catechism_ranges
    assert "CIC 1601–1666" in directive.catechism_ranges


def test_complete_our_father_includes_intro_address_petitions_and_doxology():
    question = "Explique completamente o Pai-Nosso."
    plan = build_response_plan(question)
    directive = build_research_directive(question, plan)

    assert plan.topic_key == "pai_nosso"
    assert len(plan.components) == 10
    assert plan.components[0] == "Introdução à Oração do Senhor"
    assert plan.components[-1] == "Doxologia e Amém"
    assert "CIC 2759–2865" in directive.catechism_ranges
    assert "CIC 2855–2865" in directive.catechism_ranges


def test_specific_creed_article_does_not_expand_to_all_twelve_articles():
    question = "Explique o décimo primeiro artigo do Credo."
    plan = build_response_plan(question)
    profile = match_doctrine_profile(question)
    directive = build_research_directive(question, plan)

    assert profile and profile.key == "credo_11"
    assert plan.topic_key == "credo_11"
    assert not plan.composite
    assert directive.catechism_ranges == ("CIC 988–1019",)


def test_answer_prompt_contains_source_integration_and_final_validation():
    question = "Aprofunde o Oitavo Mandamento."
    plan = build_response_plan(question)
    request = AnswerService("key", "model")._request_arguments(
        question,
        [{
            "source": "Catecismo da Igreja Católica.txt",
            "location": "CIC 2464–2513",
            "text": "O oitavo mandamento proíbe falsear a verdade.",
            "score": 1.0,
        }],
        [],
        plan=plan,
    )

    instructions = request["instructions"]
    assert "DIRETRIZ GERAL DE PESQUISA E RESPOSTA" in instructions
    assert "A Fé Explicada" in instructions
    assert "Suma Teológica" in instructions
    assert "CIC 2464–2513" in instructions
    assert "Não exponha chunks" in instructions
    assert "DIRETRIZ INTERNA DE PESQUISA E VALIDAÇÃO" in request["input"]


class _PolicyVectorStore:
    def __init__(self, index_file: Path):
        self.index_file = index_file
        self.calls: list[dict] = []

    def status(self):
        return {"ultima_atualizacao": "policy-test"}

    def search_ordered(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        hints = tuple(kwargs.get("source_filter") or ())
        if "catecismo" in hints:
            source = "Catecismo da Igreja Católica.txt"
        elif "suma" in hints:
            source = "Suma Teológica.txt"
        elif "a fe explicada" in hints:
            source = "A Fé Explicada.txt"
        else:
            source = "Documento magisterial.txt"
        item = {
            "id": f"{len(self.calls)}-{source}",
            "source": source,
            "location": "página 1",
            "text": f"{query} contém desenvolvimento doutrinal suficiente para a pesquisa.",
            "score": 1.0,
            "score_normalized": 0.9,
        }
        result = [item]
        diagnostics = {"candidates_fused": 1, "candidate_counts": {}, "final_count": 1}
        return (result, diagnostics) if kwargs.get("include_diagnostics") else result


def test_retrieval_executes_and_keeps_mandatory_source_lanes(tmp_path: Path):
    question = "Aprofunde completamente o Quinto Mandamento."
    plan = build_response_plan(question)
    cache_file = tmp_path / "cache.sqlite"
    AuthRepository(cache_file)
    vector = _PolicyVectorStore(tmp_path / "index.sqlite")
    orchestrator = RetrievalOrchestrator(vector, SemanticCache(cache_file))

    bundle = orchestrator.retrieve(question, plan, minimum_score=0.08)

    filters = [tuple(call.get("source_filter") or ()) for call in vector.calls]
    assert ("catecismo",) in filters
    assert ("a fe explicada", "fe explicada") in filters
    assert ("suma teologica", "suma") in filters
    selected_sources = {chunk["source"] for chunk in bundle.chunks}
    assert "Catecismo da Igreja Católica.txt" in selected_sources
    assert "A Fé Explicada.txt" in selected_sources
    assert "Suma Teológica.txt" in selected_sources
    assert bundle.diagnostics["research_policy"]["profile_key"] == "mandamento_5"
