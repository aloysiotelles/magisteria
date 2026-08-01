from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import logging
import re

from services.catholic_taxonomy import fold_text
from services.gospel_policy import (
    CATENA_COLLECTION,
    CATENA_SOURCE_HINTS,
    GospelPassage,
    assess_gospel_retrieval,
    passage_covered,
    patristic_authors,
)
from services.query_analysis import analyze_query
from services.response_planning import ResponsePlan
from services.semantic_cache import SemanticCache


logger = logging.getLogger(__name__)


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
            gospel_priority = int(chunk.get("gospel_priority") or 20)
            gospel_bonus = (21 - gospel_priority) * 0.06 if plan.is_gospel else 0
            combined = retrieval_score + overlap * 0.35 + (15 - authority) * 0.025 + summary_bonus + gospel_bonus
            ranked.append({
                **chunk,
                "authority_level": authority,
                "gospel_priority": gospel_priority,
                "orchestrated_score": round(combined, 4),
            })
        if plan.is_gospel:
            return sorted(
                ranked,
                key=lambda item: (
                    -item["gospel_priority"],
                    item["orchestrated_score"],
                    -item["authority_level"],
                ),
                reverse=True,
            )
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
                authors = list(merged.get("patristic_authors") or ())
                incoming_authors = chunk.get("patristic_authors") or ()
                if isinstance(incoming_authors, str):
                    incoming_authors = (incoming_authors,)
                for author in incoming_authors:
                    if author not in authors:
                        authors.append(author)
                if authors:
                    merged["patristic_authors"] = authors
                attributions = list(merged.get("attributions") or ())
                for attribution in chunk.get("attributions") or ():
                    if attribution not in attributions:
                        attributions.append(attribution)
                if attributions:
                    merged["attributions"] = attributions
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
        collection_version = self._catena_collection_version() if plan.is_gospel else ""
        technical_hints = self.semantic_cache.technical_source_hints(plan.topic_key, corpus_version)
        cached = self.semantic_cache.get(plan, corpus_version, collection_version)
        if cached:
            ranked_cached = self.reranker.rank(cached["chunks"], plan, technical_hints)
            chunks = (
                self._select_gospel_context(ranked_cached, plan)
                if plan.is_gospel
                else self.token_budget.select(ranked_cached, plan)
            )
            diagnostics = self._diagnostics(search_query, plan, chunks, [], True)
            if plan.is_gospel:
                diagnostics.update(self._cached_gospel_diagnostics(plan, chunks, collection_version))
            return RetrievalBundle(
                chunks=chunks,
                diagnostics=diagnostics,
                cache_hit=True,
                corpus_version=corpus_version,
            )

        if plan.is_gospel:
            return self._retrieve_gospel(
                search_query,
                plan,
                corpus_version,
                collection_version,
                technical_hints,
                minimum_score,
                excluded_sources,
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

    def _catena_collection_version(self) -> str:
        collection_version = getattr(self.vector_store, "collection_version", None)
        if not callable(collection_version):
            return "unknown"
        try:
            return str(collection_version(CATENA_COLLECTION) or "missing")
        except Exception:
            logger.exception("catena_collection_version_failed")
            return "unknown"

    @staticmethod
    def _expanded_passages(passages: tuple[GospelPassage, ...]) -> tuple[GospelPassage, ...]:
        expanded: list[GospelPassage] = []
        for passage in passages:
            end = passage.chapter_end or passage.chapter
            for chapter in range(passage.chapter, end + 1):
                candidate = GospelPassage(
                    passage.gospel,
                    chapter,
                    passage.verse_start if chapter == passage.chapter else None,
                    passage.verse_end if chapter == passage.chapter else None,
                )
                if candidate.cache_key not in {item.cache_key for item in expanded}:
                    expanded.append(candidate)
        return tuple(expanded)

    def _retrieve_gospel(
        self,
        search_query: str,
        plan: ResponsePlan,
        corpus_version: str,
        collection_version: str,
        technical_hints: tuple[str, ...],
        minimum_score: float,
        excluded_sources: tuple[str, ...],
    ) -> RetrievalBundle:
        traces: list[dict] = []
        catena_candidates: list[dict] = []
        candidate_ids: set[str] = set()
        search_passages = self._expanded_passages(plan.gospel.passages)
        query_entries: list[tuple[str, GospelPassage | None]] = [
            (f"{plan.gospel.episode}. {search_query}", None)
        ]
        terms = ", ".join(plan.gospel.search_terms[:8])
        for passage in search_passages:
            query_entries.append((f"{passage.reference}. {plan.gospel.episode}. {terms}", passage))
        for component in plan.gospel.components:
            query_entries.append((f"{plan.gospel.episode}: {component}. {terms}", None))
        unique_entries: list[tuple[str, GospelPassage | None]] = []
        seen_queries: set[tuple[str, str]] = set()
        for query, passage in query_entries:
            key = (fold_text(query), passage.cache_key if passage else "")
            if key in seen_queries:
                continue
            seen_queries.add(key)
            unique_entries.append((query, passage))

        max_rounds = 4 if plan.depth == "aprofundado" else 3
        max_queries = min(max(16, len(search_passages) * 4 + len(plan.gospel.components)), 48)
        max_candidates = 260 if plan.depth == "aprofundado" else 160
        round_entries = unique_entries[:max_queries]
        rounds_executed = 0
        searches_executed = 0
        termination_reason = "coverage_complete"
        missing_passages = list(search_passages)

        # Every call in this loop is collection-restricted. No repository-wide
        # search can execute until the loop and adjacent-chunk expansion finish.
        for round_number in range(1, max_rounds + 1):
            rounds_executed = round_number
            result_limit = min(14 * (2 ** (round_number - 1)), 56)
            novel_this_round = 0
            saturated = False
            for query, passage in round_entries:
                metadata_filters: dict[str, object] = {"collection": CATENA_COLLECTION}
                if passage:
                    metadata_filters.update(gospel=passage.gospel, chapter=passage.chapter)
                    if passage.verse_start is not None:
                        metadata_filters["verse_start"] = passage.verse_start
                    if passage.verse_end is not None:
                        metadata_filters["verse_end"] = passage.verse_end
                found, trace = self._search(
                    query,
                    result_limit,
                    max(minimum_score * 0.45, 0.01),
                    excluded_sources,
                    source_filter=CATENA_SOURCE_HINTS,
                    metadata_filters=metadata_filters,
                )
                searches_executed += 1
                saturated = saturated or len(found) >= result_limit
                traces.append({
                    **trace,
                    "stage": "catena_exclusive",
                    "round": round_number,
                    "passage": passage.reference if passage else "",
                })
                for chunk in found:
                    identifier = str(chunk.get("id") or "")
                    if identifier and identifier in candidate_ids:
                        continue
                    if identifier:
                        candidate_ids.add(identifier)
                    role, priority = self._catena_role(plan, passage, chunk)
                    catena_candidates.append({
                        **chunk,
                        "component": role,
                        "gospel_role": role,
                        "gospel_priority": priority,
                        "gospel_reference": passage.reference if passage else "",
                    })
                    novel_this_round += 1
                    if len(catena_candidates) >= max_candidates:
                        break
                if len(catena_candidates) >= max_candidates:
                    termination_reason = "technical_candidate_cap"
                    break

            missing_passages = [
                passage for passage in search_passages
                if not passage_covered(passage, catena_candidates)
            ]
            if len(catena_candidates) >= max_candidates:
                break
            if not missing_passages and not saturated:
                termination_reason = "coverage_complete_no_more_ranked_results"
                break
            if novel_this_round == 0:
                termination_reason = "no_novel_results"
                break
            if missing_passages:
                round_entries = [
                    (
                        f"{passage.reference}. {plan.gospel.episode}. "
                        f"{', '.join(plan.gospel.search_terms)}. passagens paralelas",
                        passage,
                    )
                    for passage in missing_passages
                ]
            else:
                round_entries = [
                    (f"{passage.reference}. {plan.gospel.episode}. comentários dos Padres", passage)
                    for passage in search_passages
                ]
        else:
            termination_reason = "technical_round_cap"

        adjacent_chunks: list[dict] = []
        adjacent_loader = getattr(self.vector_store, "fetch_adjacent_chunks", None)
        if callable(adjacent_loader) and catena_candidates:
            adjacent_chunks = adjacent_loader(
                [str(chunk.get("id")) for chunk in catena_candidates if chunk.get("id")],
                radius=1,
                collection=CATENA_COLLECTION,
                limit=min(max_candidates, 180),
            )
            for chunk in adjacent_chunks:
                role, priority = self._catena_role(plan, None, chunk)
                catena_candidates.append({
                    **chunk,
                    "component": role,
                    "gospel_role": role,
                    "gospel_priority": priority,
                })

        catena_ranked = self.reranker.rank(catena_candidates, plan, technical_hints)
        catena_chunks = self.deduplicator.deduplicate(catena_ranked)
        authors = patristic_authors(catena_chunks)
        patristic_synthesis = self._patristic_synthesis(plan, catena_chunks, authors)

        if not catena_chunks:
            logger.warning(
                "catena_retrieval_exhausted_without_results episode=%s passages=%s rounds=%s searches=%s",
                plan.gospel.episode_key,
                ",".join(plan.gospel.passage_references),
                rounds_executed,
                searches_executed,
            )

        repository_candidates, repository_traces = self._retrieve_gospel_repository(
            search_query,
            plan,
            patristic_synthesis,
            minimum_score,
            excluded_sources,
        )
        traces.extend(repository_traces)
        repository_ranked = self.reranker.rank(repository_candidates, plan, technical_hints)
        repository_chunks = self.deduplicator.deduplicate(repository_ranked)
        selected = self._select_gospel_context([*catena_chunks, *repository_chunks], plan)

        completeness = assess_gospel_retrieval(
            plan.gospel,
            catena_chunks,
            repository_chunks,
            catena_search_executed=True,
            parallel_passages_searched=bool(plan.gospel.parallel_passages),
            adjacent_chunks_loaded=len(adjacent_chunks),
            synthesis_created=True,
            complementary_search_executed=True,
        )
        self.semantic_cache.put(
            plan,
            corpus_version,
            selected,
            collection_version,
        )
        diagnostics = self._diagnostics(search_query, plan, selected, traces, False)
        diagnostics.update({
            "query_classification": plan.gospel.classification,
            "identified_gospel_passages": list(plan.gospel.passage_references),
            "catena_search_executed": True,
            "catena_filter_applied": True,
            "catena_chunks_retrieved": len(catena_chunks),
            "patristic_authors_retrieved": list(authors),
            "parallel_passages_searched": list(plan.gospel.parallel_references),
            "adjacent_chunks_loaded": len(adjacent_chunks),
            "complementary_repository_search_executed": True,
            "sources_used": list(dict.fromkeys(str(chunk.get("source") or "") for chunk in selected)),
            "coverage_score": completeness.coverage_score,
            "citation_validation_status": "pending_generation",
            "completeness_validation_status": "passed" if completeness.passed else "incomplete_after_retries",
            "gospel_completeness": completeness.to_dict(),
            "patristic_synthesis": patristic_synthesis,
            "catena_collection_version": collection_version,
            "catena_exhaustion": {
                "rounds": rounds_executed,
                "searches": searches_executed,
                "missing_passages": [passage.reference for passage in missing_passages],
                "termination_reason": termination_reason,
                "max_rounds": max_rounds,
                "max_candidates": max_candidates,
            },
        })
        return RetrievalBundle(selected, diagnostics, False, corpus_version)

    @staticmethod
    def _catena_role(
        plan: ResponsePlan,
        passage: GospelPassage | None,
        chunk: dict,
    ) -> tuple[str, int]:
        candidate = passage
        if candidate is None and chunk.get("gospel") and chunk.get("chapter"):
            candidate = GospelPassage(
                str(chunk.get("gospel")),
                int(chunk.get("chapter")),
                chunk.get("verse_start"),
                chunk.get("verse_end"),
            )
        if candidate and any(candidate.overlaps(primary) for primary in plan.gospel.primary_passages):
            return "Catena Áurea — passagem principal", 2
        if candidate and any(candidate.overlaps(parallel) for parallel in plan.gospel.parallel_passages):
            return "Catena Áurea — passagem paralela", 3
        return "Catena Áurea — comentário patrístico relacionado", 4

    def _retrieve_gospel_repository(
        self,
        search_query: str,
        plan: ResponsePlan,
        patristic_synthesis: dict,
        minimum_score: float,
        excluded_sources: tuple[str, ...],
    ) -> tuple[list[dict], list[dict]]:
        candidates: list[dict] = []
        traces: list[dict] = []
        repository_exclusions = tuple(dict.fromkeys((*excluded_sources, *CATENA_SOURCE_HINTS)))
        references = ", ".join(plan.gospel.passage_references)

        scripture, trace = self._search(
            f"{references}. {plan.gospel.episode}. {search_query}",
            10 if plan.depth != "resumido" else 6,
            max(minimum_score * 0.5, 0.01),
            repository_exclusions,
            source_filter=("biblia", "sagrada escritura"),
        )
        candidates.extend(self._tag_repository_chunk(chunk, "Texto bíblico") for chunk in scripture)
        traces.append({**trace, "stage": "complementary_scripture"})

        general, trace = self._search(
            search_query,
            10 if plan.depth != "resumido" else 6,
            minimum_score,
            repository_exclusions,
        )
        candidates.extend(self._tag_repository_chunk(chunk, "Complementação doutrinal") for chunk in general)
        traces.append({**trace, "stage": "complementary_repository"})

        synthesis_query = (
            f"{plan.gospel.episode}. {references}. "
            f"Temas patrísticos: {', '.join(patristic_synthesis.get('dimensions', []))}. "
            "Sagrada Escritura, Catecismo, Magistério, Padres, Doutores e Liturgia."
        )
        thematic, trace = self._search(
            synthesis_query,
            12 if plan.depth == "aprofundado" else 8,
            max(minimum_score * 0.7, 0.015),
            repository_exclusions,
        )
        candidates.extend(self._tag_repository_chunk(chunk, "Complementação doutrinal") for chunk in thematic)
        traces.append({**trace, "stage": "complementary_patristic_synthesis"})

        if plan.gospel.components:
            for component in plan.gospel.components:
                found, trace = self._search(
                    f"{plan.gospel.episode}: {component}. {references}",
                    2 if plan.depth == "aprofundado" else 1,
                    max(minimum_score * 0.6, 0.01),
                    repository_exclusions,
                )
                candidates.extend(self._tag_repository_chunk(chunk, component) for chunk in found)
                traces.append({**trace, "stage": "complementary_component", "component": component})
        return candidates, traces

    @staticmethod
    def _tag_repository_chunk(chunk: dict, component: str) -> dict:
        normalized = fold_text(str(chunk.get("source") or ""))
        if "biblia" in normalized or "sagrada escritura" in normalized:
            priority, role = 1, "Sagrada Escritura"
        elif "catecismo" in normalized:
            priority, role = 5, "Catecismo da Igreja Católica"
        elif any(term in normalized for term in (
            "concilio", "vaticano", "enciclica", "exortacao", "carta apostolica",
            "constituicao apostolica", "dicasterio", "doutrina da fe", "pontificio",
        )):
            priority, role = 6, "Magistério"
        elif any(term in normalized for term in ("padres da igreja", "patristica", "doutor", "suma")):
            priority, role = 7, "Outras fontes patrísticas e teológicas"
        elif any(term in normalized for term in ("missal", "liturgia")):
            priority, role = 8, "Liturgia"
        else:
            priority, role = 9, "Demais fontes do acervo"
        return {
            **chunk,
            "component": component,
            "gospel_role": role,
            "gospel_priority": priority,
        }

    @staticmethod
    def _patristic_synthesis(
        plan: ResponsePlan,
        chunks: list[dict],
        authors: tuple[str, ...],
    ) -> dict:
        combined = fold_text(" ".join(str(chunk.get("text") or "") for chunk in chunks))
        dimension_terms = {
            "sentido literal": ("literal", "historia", "narrativa"),
            "cristologia": ("cristo", "filho", "verbo", "senhor"),
            "sentido moral": ("virtude", "pecado", "costumes", "vida"),
            "sentido espiritual": ("espiritual", "misterio", "alma"),
            "Igreja": ("igreja", "apostolo", "discipulo"),
            "sacramentos": ("sacramento", "batismo", "eucaristia"),
            "escatologia": ("juizo", "eterno", "ressurreicao", "gloria"),
        }
        dimensions = [
            name for name, terms in dimension_terms.items()
            if any(term in combined for term in terms)
        ]
        return {
            "episode": plan.gospel.episode,
            "passages_covered": [
                passage.reference for passage in plan.gospel.passages
                if passage_covered(passage, chunks)
            ],
            "authors": list(authors),
            "dimensions": dimensions,
            "distinct_chunks": len(chunks),
        }

    def _select_gospel_context(self, chunks: list[dict], plan: ResponsePlan) -> list[dict]:
        ranked = self.reranker.rank(chunks, plan)
        scripture = [chunk for chunk in ranked if int(chunk.get("gospel_priority") or 20) == 1]
        catena = [chunk for chunk in ranked if 2 <= int(chunk.get("gospel_priority") or 20) <= 4]
        remaining = [chunk for chunk in ranked if int(chunk.get("gospel_priority") or 20) > 4]
        budget = plan.max_context_tokens
        selected_scripture: list[dict] = []
        selected_catena: list[dict] = []
        selected_remaining: list[dict] = []
        used_ids: set[str] = set()

        def fill(candidates: list[dict], target: int, output: list[dict]) -> int:
            consumed = 0
            for candidate in candidates:
                identifier = str(candidate.get("id") or id(candidate))
                if identifier in used_ids:
                    continue
                cost = self.token_budget.estimate_tokens(candidate.get("text", ""))
                if consumed + cost > target:
                    continue
                output.append(candidate)
                used_ids.add(identifier)
                consumed += cost
            return consumed

        scripture_cost = fill(scripture, max(int(budget * 0.16), 800), selected_scripture)

        # Before rank filling, reserve one Catena chunk for every identified
        # passage and for as many distinct explicitly-labelled authors as fit.
        catena_anchors: list[dict] = []
        for passage in self._expanded_passages(plan.gospel.passages):
            anchor = next((chunk for chunk in catena if passage_covered(passage, [chunk])), None)
            if anchor and anchor not in catena_anchors:
                catena_anchors.append(anchor)
        represented_authors: set[str] = set()
        for chunk in catena:
            names = chunk.get("patristic_authors") or ()
            if isinstance(names, str):
                names = (names,)
            if any(fold_text(str(name)) not in represented_authors for name in names):
                catena_anchors.append(chunk)
                represented_authors.update(fold_text(str(name)) for name in names)
            if len(represented_authors) >= 24:
                break
        catena_candidates = list(dict.fromkeys(id(item) for item in catena_anchors))
        anchor_by_identity = {id(item): item for item in catena_anchors}
        ordered_catena = [anchor_by_identity[value] for value in catena_candidates]
        ordered_catena.extend(item for item in catena if id(item) not in anchor_by_identity)
        catena_target = max(int(budget * 0.68), 2800) if catena else 0
        catena_cost = fill(ordered_catena, catena_target, selected_catena)
        remaining_budget = max(budget - scripture_cost - catena_cost, 0)
        fill(remaining, remaining_budget, selected_remaining)

        selected = [*selected_scripture, *selected_catena, *selected_remaining]
        for chunk in selected:
            priority = int(chunk.get("gospel_priority") or 20)
            chunk["ordem"] = priority
            if priority == 1:
                chunk["categoria"] = "Sagrada Escritura"
            elif priority == 2:
                chunk["categoria"] = "Catena Áurea — passagem principal"
            elif priority == 3:
                chunk["categoria"] = "Catena Áurea — passagens paralelas"
            elif priority == 4:
                chunk["categoria"] = "Catena Áurea — tradição patrística"
            elif priority == 5:
                chunk["categoria"] = "Catecismo da Igreja Católica"
            elif priority == 6:
                chunk["categoria"] = "Magistério"
        return selected

    @staticmethod
    def _cached_gospel_diagnostics(
        plan: ResponsePlan,
        chunks: list[dict],
        collection_version: str,
    ) -> dict:
        catena_chunks = [chunk for chunk in chunks if chunk.get("collection") == CATENA_COLLECTION]
        return {
            "query_classification": plan.gospel.classification,
            "identified_gospel_passages": list(plan.gospel.passage_references),
            "catena_search_executed": False,
            "catena_policy_satisfied_by_cache": True,
            "catena_filter_applied": True,
            "catena_chunks_retrieved": len(catena_chunks),
            "patristic_authors_retrieved": list(patristic_authors(catena_chunks)),
            "parallel_passages_searched": list(plan.gospel.parallel_references),
            "adjacent_chunks_loaded": 0,
            "complementary_repository_search_executed": False,
            "sources_used": list(dict.fromkeys(str(chunk.get("source") or "") for chunk in chunks)),
            "coverage_score": 1.0,
            "citation_validation_status": "pending_generation",
            "completeness_validation_status": "satisfied_by_versioned_cache",
            "catena_collection_version": collection_version,
        }

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
        *,
        source_filter: tuple[str, ...] | None = None,
        metadata_filters: dict | None = None,
    ) -> tuple[list[dict], dict]:
        result = self.vector_store.search_ordered(
            query,
            limit=max(limit, 1),
            minimum_score=minimum_score,
            excluded_sources=excluded_sources,
            include_diagnostics=True,
            source_filter=source_filter,
            metadata_filters=metadata_filters,
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
                "query_classification": plan.gospel.classification,
                "identified_gospel_passages": list(plan.gospel.passage_references),
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
