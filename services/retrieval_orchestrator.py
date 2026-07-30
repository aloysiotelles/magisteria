from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import re

from services.catholic_taxonomy import fold_text
from services.query_analysis import analyze_query
from services.response_planning import ResponsePlan
from services.semantic_cache import SemanticCache


TOKEN_PATTERN = re.compile(r"[a-z0-9à-ÿ]{3,}", re.IGNORECASE)


@dataclass(frozen=True)
class RetrievalBundle:
    chunks: list[dict]
    diagnostics: dict
    cache_hit: bool
    corpus_version: str


class DocumentReranker:
    SOURCE_PRIORITIES = (
        (1, ("biblia", "sagrada escritura")),
        (2, ("catecismo",)),
        (3, ("compendio",)),
        (4, ("direito canonico", "codigo de direito")),
        (5, ("concilio", "vaticano ii", "simbolos", "dogma", "denzinger")),
        (6, ("enciclica",)),
        (7, ("exortacao",)),
        (8, ("constituicao apostolica", "carta apostolica", "pontificio")),
        (9, ("dicasterio", "congregacao", "doutrina da fe")),
        (10, ("padres da igreja",)),
        (11, ("doutor da igreja", "suma teologica")),
        (12, ("missal", "liturgia")),
        (13, ("cnbb", "episcopal")),
    )

    @classmethod
    def authority_level(cls, source: str) -> int:
        normalized = fold_text(source)
        for level, hints in cls.SOURCE_PRIORITIES:
            if any(hint in normalized for hint in hints):
                return level
        return 14

    @classmethod
    def rank(
        cls,
        chunks: list[dict],
        plan: ResponsePlan,
        technical_source_hints: tuple[str, ...] = (),
    ) -> list[dict]:
        topic_terms = set(TOKEN_PATTERN.findall(fold_text(plan.theme)))
        ranked: list[dict] = []
        for chunk in chunks:
            text_terms = set(TOKEN_PATTERN.findall(fold_text(str(chunk.get("text") or ""))))
            overlap = len(topic_terms & text_terms) / max(len(topic_terms), 1)
            authority = cls.authority_level(str(chunk.get("source") or ""))
            retrieval_score = float(chunk.get("score_normalized") or chunk.get("score") or 0)
            summary_bonus = 0.08 if str(chunk.get("source") or "") in technical_source_hints else 0
            combined = retrieval_score + overlap * 0.35 + (15 - authority) * 0.025 + summary_bonus
            ranked.append({**chunk, "authority_level": authority, "orchestrated_score": round(combined, 4)})
        return sorted(ranked, key=lambda item: (item["orchestrated_score"], -item["authority_level"]), reverse=True)


class ContextDeduplicator:
    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(TOKEN_PATTERN.findall(fold_text(text)))

    def deduplicate(self, chunks: list[dict], threshold: float = 0.86) -> list[dict]:
        selected: list[dict] = []
        fingerprints: set[str] = set()
        token_sets: list[set[str]] = []
        for chunk in chunks:
            clean = re.sub(r"\s+", " ", str(chunk.get("text") or "")).strip()
            if not clean:
                continue
            fingerprint = hashlib.sha256(fold_text(clean).encode("utf-8")).hexdigest()
            if fingerprint in fingerprints:
                continue
            tokens = self._tokens(clean)
            duplicate_index = -1
            for index, existing in enumerate(token_sets):
                union = len(tokens | existing)
                if union and len(tokens & existing) / union >= threshold:
                    duplicate_index = index
                    break
            if duplicate_index >= 0:
                component = str(chunk.get("component") or "Visão geral")
                merged = selected[duplicate_index]
                components = list(merged.get("components") or (merged.get("component"),))
                if component not in components:
                    components.append(component)
                merged["components"] = tuple(item for item in components if item)
                continue
            fingerprints.add(fingerprint)
            token_sets.append(tokens)
            selected.append({**chunk, "text": clean, "components": (str(chunk.get("component") or "Visão geral"),)})
        return selected


class TokenBudgetManager:
    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(len(str(text or "")) // 4, 1)

    def select(self, chunks: list[dict], plan: ResponsePlan) -> list[dict]:
        budget = plan.max_context_tokens
        selected: list[dict] = []
        used_ids: set[str] = set()
        consumed = 0

        # Reserve one evidentiary chunk per active component before filling by rank.
        for component in plan.active_components:
            candidate = next((
                item for item in chunks
                if component in (item.get("components") or (item.get("component"),))
            ), None)
            if not candidate:
                continue
            identifier = str(candidate.get("id") or id(candidate))
            cost = self.estimate_tokens(candidate.get("text", ""))
            if consumed + cost <= budget:
                selected.append(candidate)
                used_ids.add(identifier)
                consumed += cost

        per_component = Counter(str(item.get("component") or "geral") for item in selected)
        component_limit = 1 if plan.depth == "resumido" else (3 if plan.depth == "aprofundado" else 2)
        for candidate in chunks:
            identifier = str(candidate.get("id") or id(candidate))
            if identifier in used_ids:
                continue
            component = str(candidate.get("component") or "geral")
            if per_component[component] >= component_limit:
                continue
            cost = self.estimate_tokens(candidate.get("text", ""))
            if consumed + cost > budget:
                continue
            selected.append(candidate)
            used_ids.add(identifier)
            per_component[component] += 1
            consumed += cost
        return selected


class RetrievalOrchestrator:
    REFERENCE_DOCUMENTS = (
        ("catecismo", "Catecismo da Igreja Católica"),
        ("compendio", "Compêndio do Catecismo da Igreja Católica"),
        ("codigo de direito canonico", "Código de Direito Canônico"),
        ("dei verbum", "Dei Verbum"),
        ("lumen gentium", "Lumen Gentium"),
        ("sacrosanctum concilium", "Sacrosanctum Concilium"),
        ("gaudium et spes", "Gaudium et Spes"),
        ("dignitatis humanae", "Dignitatis Humanae"),
        ("unitatis redintegratio", "Unitatis Redintegratio"),
        ("nostra aetate", "Nostra Aetate"),
        ("evangelii gaudium", "Evangelii Gaudium"),
        ("fidei depositum", "Fidei Depositum"),
    )

    def __init__(self, vector_store, semantic_cache: SemanticCache):
        self.vector_store = vector_store
        self.semantic_cache = semantic_cache
        self.reranker = DocumentReranker()
        self.deduplicator = ContextDeduplicator()
        self.token_budget = TokenBudgetManager()

    def corpus_version(self) -> str:
        status = self.vector_store.status()
        version = str(status.get("ultima_atualizacao") or "")
        if version:
            return version
        try:
            stat = self.vector_store.index_file.stat()
            return f"{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            return "empty"

    def retrieve(
        self,
        search_query: str,
        plan: ResponsePlan,
        *,
        minimum_score: float,
        excluded_sources: tuple[str, ...] = (),
    ) -> RetrievalBundle:
        corpus_version = self.corpus_version()
        technical_hints = self.semantic_cache.technical_source_hints(plan.topic_key, corpus_version)
        cached = self.semantic_cache.get(plan, corpus_version)
        if cached:
            chunks = self.token_budget.select(
                self.reranker.rank(cached["chunks"], plan, technical_hints), plan
            )
            return RetrievalBundle(
                chunks=chunks,
                diagnostics=self._diagnostics(search_query, plan, chunks, [], True),
                cache_hit=True,
                corpus_version=corpus_version,
            )

        traces: list[dict] = []
        candidates: list[dict] = []
        general_limit = 5 if plan.depth == "resumido" else (8 if plan.composite else 6)
        general = self._search(search_query, general_limit, minimum_score, excluded_sources)
        general_chunks, general_trace = general
        candidates.extend({**chunk, "component": "Visão geral"} for chunk in general_chunks)
        traces.append(general_trace)

        # Segunda passagem orientada por taxonomia, títulos e tipos documentais.
        # O armazenamento vetorial executa, dentro de cada chamada, busca lexical,
        # expansão semântica, metadados de título e orientação por índices.
        taxonomy_query = (
            f"{plan.theme}. Categorias e subtítulos: {', '.join(plan.dimensions)}. "
            f"Fontes: {', '.join(plan.source_types)}"
        )
        taxonomy_chunks, taxonomy_trace = self._search(
            taxonomy_query,
            general_limit,
            max(minimum_score * 0.75, 0.02),
            excluded_sources,
        )
        candidates.extend({**chunk, "component": "Taxonomia e fontes"} for chunk in taxonomy_chunks)
        traces.append(taxonomy_trace)

        if plan.composite:
            component_limit = 1 if plan.depth == "resumido" else 3
            dimension_hint = ", ".join(plan.dimensions[:4])
            for component in plan.active_components:
                query = f"{plan.theme}: {component}. {dimension_hint}"
                found, trace = self._search(query, component_limit, max(minimum_score * 0.7, 0.02), excluded_sources)
                candidates.extend({**chunk, "component": component} for chunk in found)
                traces.append(trace)

        # Segue referências documentais explícitas encontradas nos primeiros
        # resultados e incorpora o documento citado antes do reranqueamento final.
        reference_queries = self._reference_queries(candidates, plan.theme)
        for query in reference_queries:
            found, trace = self._search(
                query,
                3,
                max(minimum_score * 0.65, 0.015),
                excluded_sources,
            )
            candidates.extend({**chunk, "component": "Referência cruzada"} for chunk in found)
            traces.append({**trace, "reference_follow_up": query})

        ranked = self.reranker.rank(candidates, plan, technical_hints)
        deduplicated = self.deduplicator.deduplicate(ranked)
        selected = self.token_budget.select(deduplicated, plan)
        self.semantic_cache.put(plan, corpus_version, selected)
        diagnostics = self._diagnostics(search_query, plan, selected, traces, False)
        return RetrievalBundle(selected, diagnostics, False, corpus_version)

    @classmethod
    def _reference_queries(cls, chunks: list[dict], theme: str) -> tuple[str, ...]:
        queries: list[str] = []
        for chunk in chunks:
            text = fold_text(str(chunk.get("text") or ""))
            source = fold_text(str(chunk.get("source") or ""))
            for alias, title in cls.REFERENCE_DOCUMENTS:
                if alias not in text or alias in source:
                    continue
                query = f"{title}: {theme}"
                if query not in queries:
                    queries.append(query)
                if len(queries) >= 8:
                    return tuple(queries)
        return tuple(queries)

    def _search(
        self,
        query: str,
        limit: int,
        minimum_score: float,
        excluded_sources: tuple[str, ...],
    ) -> tuple[list[dict], dict]:
        result = self.vector_store.search_ordered(
            query,
            limit=max(limit, 1),
            minimum_score=minimum_score,
            excluded_sources=excluded_sources,
            include_diagnostics=True,
        )
        if isinstance(result, tuple):
            return result
        return result, {"candidate_counts": {}, "candidates_fused": len(result), "final_count": len(result)}

    @staticmethod
    def _diagnostics(
        query: str,
        plan: ResponsePlan,
        chunks: list[dict],
        traces: list[dict],
        cache_hit: bool,
    ) -> dict:
        candidate_count = sum(int(trace.get("candidates_fused", 0)) for trace in traces)
        return {
            "query": {
                **analyze_query(query).to_dict(),
                "intent_types": list(plan.intents),
                "depth_level": plan.depth,
                "topic_category": plan.category,
            },
            "candidate_counts": {
                "layered_searches": len(traces),
                "all_candidates": candidate_count,
            },
            "candidates_fused": candidate_count or len(chunks),
            "reranking": [
                {
                    "id": item.get("id"), "source": item.get("source"),
                    "score": item.get("orchestrated_score", item.get("score", 0)),
                    "score_normalized": item.get("score_normalized", 0),
                    "authority_level": item.get("authority_level", 14),
                    "component": item.get("component", "Visão geral"),
                }
                for item in chunks
            ],
            "selected_chunks": [
                {"id": item.get("id"), "source": item.get("source"), "component": item.get("component")}
                for item in chunks
            ],
            "final_count": len(chunks),
            "cache_hit": cache_hit,
            "plan": plan.to_dict(),
        }
