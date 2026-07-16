from __future__ import annotations

from collections import Counter, OrderedDict
from collections.abc import Callable
import copy
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
import unicodedata

from services.document_loader import discover_documents, load_document
from services.query_analysis import QueryAnalysis, QueryType, analyze_query


TOKEN_PATTERN = re.compile(r"[a-z0-9à-ÿ]{2,}", re.IGNORECASE)
QUERY_STOPWORDS = {
    "que", "como", "qual", "quais", "uma", "uns", "das", "dos", "para", "por", "com",
    "sem", "sobre", "segundo", "partir", "ensina", "ensinam", "igreja", "documento", "documentos",
    "diz", "dizem", "fala", "falam", "trata", "tratam", "explique", "explica", "catolica", "catolico",
    "compendio", "fonte", "obra", "livro",
}
INDEX_CONTEXT_STOPWORDS = QUERY_STOPWORDS | {
    "ainda", "assim", "deus", "homem", "homens", "meio", "nao", "nem", "nos",
    "pelo", "pode", "poder", "ser", "sob",
}
SOURCE_HINTS = {
    "catecismo": ("catecismo",), "cic": ("catecismo",),
    "biblia": ("biblia",), "sagrada escritura": ("biblia",), "missal": ("missal",),
    "suma": ("suma teologica",), "doutrina social": ("doutrina social", "doutrina-social"),
    "compendio da doutrina social": ("doutrina social", "doutrina-social"),
    "fe explicada": ("a fe explicada", "fe explicada"),
    "a fe": ("a fe explicada", "fe explicada"),
    "compendio de simbolos": ("simbolos", "definicoes", "declaracoes-de-fe-e-moral"),
    "simbolos": ("simbolos", "definicoes", "declaracoes-de-fe-e-moral"),
    "denzinger": ("simbolos", "definicoes", "declaracoes-de-fe-e-moral"),
    "d sistema": ("simbolos definicoes", "declaracoes-de-fe-e-moral"),
}
QUERY_EXPANSIONS = {
    "pecado": {
        "pecados", "transgressao", "culpa", "conversao", "penitencia", "perdao",
        "mortal", "venial", "original",
    },
    "eucaristia": {
        "missa", "comunhao", "sacramento", "altar", "consagracao", "transubstanciacao",
    },
    "maria": {
        "virgem", "theotokos", "assuncao", "imaculada", "intercessao", "magnificat",
    },
    "graca": {"dom", "salvacao", "santificacao", "justificacao", "redenção"},
    "purgatorio": {"purificacao", "mortos", "escatologia", "vida eterna"},
    "confissao": {"penitencia", "reconciliacao", "absolvicao", "contricao", "pecados"},
    "trindade": {"pai", "filho", "espirito", "unidade", "tres pessoas"},
    "batismo": {"baptismo", "iniciacao", "agua", "regeneracao", "sacramento"},
    "baptismo": {"batismo", "iniciacao", "agua", "regeneracao", "sacramento"},
    "ressurreicao": {"ressuscitou", "ressuscitar", "pascoa", "vida eterna"},
    "indulgencia": {"pena temporal", "remissao", "penitencia", "purgatorio"},
    "matrimonio": {
        "casamento", "conjugal", "conjuges", "esposos", "esposo", "esposa",
        "matrimonial", "indissolubilidade", "fecundidade", "familia", "consentimento",
        "sacramento", "uniao",
    },
    "casamento": {
        "matrimonio", "conjugal", "conjuges", "esposos", "matrimonial",
        "indissolubilidade", "fecundidade", "familia", "consentimento", "sacramento",
    },
    "conjuges": {"matrimonio", "casamento", "esposos", "conjugal", "familia"},
    "esposos": {"matrimonio", "casamento", "conjuges", "conjugal", "familia"},
    "familia": {"matrimonio", "casamento", "conjuges", "esposos", "filhos"},
    "divorcio": {"matrimonio", "casamento", "indissolubilidade", "conjuges"},
}
TOPIC_REFERENCE_RANGES = {
    "matrimonio": ((1601, 1605, 1.25), (1606, 1666, 0.7), (2360, 2379, 0.35), (2201, 2233, 0.25)),
    "casamento": ((1601, 1605, 1.25), (1606, 1666, 0.7), (2360, 2379, 0.35), (2201, 2233, 0.25)),
    "conjuges": ((1601, 1605, 0.9), (1606, 1666, 0.55), (2360, 2379, 0.35)),
    "esposos": ((1601, 1605, 0.9), (1606, 1666, 0.55), (2360, 2379, 0.35)),
    "familia": ((2201, 2233, 0.55), (1601, 1605, 0.35), (1606, 1666, 0.25)),
    "dignidade": ((105, 159, 0.75), (132, 134, 0.95), (1700, 1706, 0.65), (1929, 1933, 0.55)),
    "humana": ((105, 159, 0.35), (132, 134, 0.55), (1700, 1706, 0.35), (1929, 1933, 0.3)),
    "trabalho": ((255, 322, 0.85), (270, 275, 1.0), (2427, 2436, 0.55)),
    "solidariedade": ((192, 196, 0.95), (332, 333, 0.5), (1939, 1942, 0.55)),
    "subsidiariedade": ((185, 188, 0.95),),
    "comum": ((164, 170, 0.7), (1905, 1912, 0.55)),
}
ORDERED_SOURCES = (
    ("Catecismo da Igreja Católica", ("catecismo",), 5),
    ("Bíblia Ave Maria — citações bíblicas", ("biblia ave maria", "biblia"), 4),
    ("Compêndio Vaticano II", ("compendio vaticano ii", "vaticano ii"), 3),
    ("Compêndio da Doutrina Social da Igreja", ("doutrina-social", "doutrina social"), 2),
    ("A Fé Explicada", ("a fe explicada", "fe explicada"), 2),
    ("Compêndio dos símbolos, definições e declarações", ("simbolos", "definicoes"), 2),
    ("Suma Teológica", ("suma teologica", "suma-teologica", "suma"), 2),
)
SINGLE_TERM_ORDERED_SOURCES = (
    ("Catecismo da Igreja Católica", ("catecismo",), 5),
    ("Compêndio dos símbolos, definições e declarações", ("simbolos", "definicoes"), 3),
    ("A Fé Explicada", ("a fe explicada", "fe explicada"), 3),
    ("Bíblia Ave Maria — citações bíblicas", ("biblia ave maria", "biblia"), 2),
    ("Compêndio Vaticano II", ("compendio vaticano ii", "vaticano ii"), 2),
    ("Compêndio da Doutrina Social da Igreja", ("doutrina-social", "doutrina social"), 2),
    ("Suma Teológica", ("suma teologica", "suma-teologica", "suma"), 2),
)
NOMINAL_INDEX_SOURCES = SINGLE_TERM_ORDERED_SOURCES[:3]
BIBLE_QUERY_EXPANSIONS = {
    "caridade": {"amor", "amar", "amou"}, "sacramento": {"batismo", "eucaristia", "ceia"},
    "sacramentos": {"batismo", "eucaristia", "ceia"}, "perdao": {"perdoar", "misericordia"},
    "esperanca": {"esperar", "ressurreicao"},
}
BIBLE_REFERENCE_PATTERN = re.compile(
    r"\b(?:Gn|Ex|Êx|Lv|Nm|Dt|Js|Jz|Rt|1Sm|2Sm|1Rs|2Rs|1Cr|2Cr|Esd|Ne|Tb|Jt|Est|"
    r"1Mc|2Mc|Jó|Sl|Pr|Ecl|Ct|Sb|Eclo|Is|Jr|Lm|Br|Ez|Dn|Os|Jl|Am|Ab|Jn|Mq|Na|Hab|"
    r"Sf|Ag|Zc|Ml|Mt|Mc|Lc|Jo|At|Rm|1Cor|2Cor|Gl|Ef|Fl|Cl|1Ts|2Ts|1Tm|2Tm|Tt|Fm|"
    r"Hb|Tg|1Pd|2Pd|1Jo|2Jo|3Jo|Jd|Ap)\s*\d{1,3}\s*,\s*\d{1,3}(?:[-–.]\d{1,3})*",
    re.IGNORECASE,
)
INDEXED_SOURCE_HINTS = (
    "catecismo",
    "doutrina social",
    "compendio-da-doutrina-social",
    "simbolos definicoes",
    "declaracoes-de-fe-e-moral",
    "a fe explicada",
)
SYSTEMATIC_INDEX_CODE_PATTERN = re.compile(r"\b[A-Z]:\d+[a-z]{0,3}(?:\d+)?\b")


class LocalVectorStore:
    """Indice SQLite/FTS em disco, adequado a bases grandes e pouca memoria."""

    def __init__(self, documents_dir: Path, index_file: Path, chunk_size: int, overlap: int):
        self.documents_dir = documents_dir
        self.index_file = index_file
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._search_cache: OrderedDict[tuple, tuple[float, object]] = OrderedDict()
        self._search_cache_lock = threading.RLock()
        self._search_cache_ttl = 600
        self._search_cache_limit = 128
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self._prepare_database_file()
        self._initialize()

    def _prepare_database_file(self) -> None:
        if not self.index_file.exists():
            return
        try:
            if self.index_file.read_bytes()[:16] == b"SQLite format 3\x00":
                return
        except OSError:
            pass
        legacy = self.index_file.with_suffix(self.index_file.suffix + ".legacy-json")
        legacy.unlink(missing_ok=True)
        self.index_file.replace(legacy)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.index_file, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS files (
                    source TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                    id UNINDEXED, source UNINDEXED, location UNINDEXED, text,
                    tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TABLE IF NOT EXISTS errors (source TEXT, error TEXT);
            """)

    def index_documents(self, progress_callback: Callable[[int, int, str], None] | None = None) -> dict:
        documents = discover_documents(self.documents_dir)
        names = [path.relative_to(self.documents_dir).as_posix() for path in documents]
        if progress_callback:
            progress_callback(0, len(documents), "Preparando documentos")
        with self._connect() as db:
            known = {row["source"]: (row["size"], row["mtime_ns"]) for row in db.execute("SELECT * FROM files")}
            for removed in set(known) - set(names):
                db.execute("DELETE FROM chunks WHERE source = ?", (removed,))
                db.execute("DELETE FROM files WHERE source = ?", (removed,))
            for position, path in enumerate(documents, 1):
                source = path.relative_to(self.documents_dir).as_posix()
                stat = path.stat()
                fingerprint = (stat.st_size, stat.st_mtime_ns)
                if known.get(source) == fingerprint:
                    if progress_callback:
                        progress_callback(position, len(documents), f"Reutilizado: {path.name}")
                    continue
                if progress_callback:
                    progress_callback(position - 1, len(documents), f"Lendo {position} de {len(documents)}: {path.name}")
                db.execute("DELETE FROM chunks WHERE source = ?", (source,))
                db.execute("DELETE FROM errors WHERE source = ?", (source,))
                try:
                    rows = []
                    for section in load_document(path, self.documents_dir):
                        for number, text in enumerate(self._split_text(section.text), 1):
                            chunk_id = hashlib.sha256(f"{source}|{section.location}|{number}|{text}".encode()).hexdigest()[:20]
                            rows.append((chunk_id, source, section.location, text))
                            if len(rows) >= 100:
                                db.executemany("INSERT INTO chunks(id,source,location,text) VALUES(?,?,?,?)", rows)
                                rows.clear()
                    if rows:
                        db.executemany("INSERT INTO chunks(id,source,location,text) VALUES(?,?,?,?)", rows)
                    db.execute(
                        "INSERT OR REPLACE INTO files(source,size,mtime_ns) VALUES(?,?,?)",
                        (source, *fingerprint),
                    )
                except Exception as exc:
                    db.execute("INSERT INTO errors(source,error) VALUES(?,?)", (source, str(exc)))
                db.commit()
                if progress_callback:
                    progress_callback(position, len(documents), path.name)
            updated = datetime.now(timezone.utc).isoformat()
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('updated_at',?)", (updated,))
        with self._search_cache_lock:
            self._search_cache.clear()
        return self.status()

    def _cached_search(self, key: tuple):
        now = time.monotonic()
        with self._search_cache_lock:
            cached = self._search_cache.get(key)
            if cached is None:
                return None
            created, value = cached
            if now - created > self._search_cache_ttl:
                self._search_cache.pop(key, None)
                return None
            self._search_cache.move_to_end(key)
            return copy.deepcopy(value)

    def _cache_search(self, key: tuple, value):
        with self._search_cache_lock:
            self._search_cache[key] = (time.monotonic(), copy.deepcopy(value))
            self._search_cache.move_to_end(key)
            while len(self._search_cache) > self._search_cache_limit:
                self._search_cache.popitem(last=False)
        return value

    def _query_terms(self, query: str, preferred: tuple[str, ...] = ()) -> tuple[set[str], set[str]]:
        terms = {
            term for term in TOKEN_PATTERN.findall(self._normalize(query))
            if term not in QUERY_STOPWORDS and len(term) >= 2
        }
        if preferred:
            terms -= {
                term
                for hint in preferred
                for term in TOKEN_PATTERN.findall(self._normalize(hint))
            }
        expanded = set(terms)
        for term in terms:
            expanded.update(QUERY_EXPANSIONS.get(term, set()))
            expanded.update(BIBLE_QUERY_EXPANSIONS.get(term, set()))
        return terms, expanded

    def _candidate_rows(
        self,
        query: str,
        limit: int | None = None,
        preferred: tuple[str, ...] = (),
        additional_terms: set[str] | None = None,
    ) -> list[dict]:
        _, expanded = self._query_terms(query, preferred)
        expanded.update(additional_terms or set())
        if not expanded:
            return []
        limit = limit or (1200 if preferred else 2000)
        expression = " OR ".join(f"{term}*" for term in sorted(expanded))
        with self._connect() as db:
            if preferred:
                sources = [
                    row[0] for row in db.execute("SELECT source FROM files")
                    if self._source_matches(self._normalize(row[0]), preferred)
                ]
                if not sources:
                    return []
                placeholders = ",".join("?" for _ in sources)
                rows = db.execute(
                    "SELECT id,source,location,text,bm25(chunks) rank FROM chunks "
                    f"WHERE chunks MATCH ? AND source IN ({placeholders}) ORDER BY rank LIMIT ?",
                    (expression, *sources, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id,source,location,text,bm25(chunks) rank "
                    "FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT ?",
                    (expression, limit),
                ).fetchall()
        candidates = []
        for position, row in enumerate(rows, 1):
            item = dict(row)
            item["fts_position"] = position
            candidates.append(item)
        return candidates

    def _exact_candidate_rows(
        self,
        analysis: QueryAnalysis,
        preferred: tuple[str, ...] = (),
        limit: int = 500,
    ) -> list[dict]:
        """Executa a via lexical estrita sem substituir a consulta original."""
        if not analysis.lexical_terms:
            return []
        phrase = " ".join(analysis.lexical_terms).replace('"', '""')
        expression = f'"{phrase}"'
        return self._fts_rows(expression, preferred, limit)

    def _variant_candidate_rows(
        self,
        analysis: QueryAnalysis,
        preferred: tuple[str, ...] = (),
        limit: int = 900,
    ) -> list[dict]:
        if not analysis.variants:
            return []
        expression = " OR ".join(f'"{term}"' for term in analysis.variants)
        return self._fts_rows(expression, preferred, limit)

    def _semantic_expansion_rows(
        self,
        analysis: QueryAnalysis,
        preferred: tuple[str, ...] = (),
        limit: int = 600,
    ) -> list[dict]:
        related: set[str] = set()
        for term in analysis.lexical_terms:
            related.update(QUERY_EXPANSIONS.get(term, set()))
            related.update(BIBLE_QUERY_EXPANSIONS.get(term, set()))
        related -= set(analysis.variants)
        if not related:
            return []
        tokens = {
            token
            for phrase in related
            for token in TOKEN_PATTERN.findall(self._normalize(phrase))
            if token not in QUERY_STOPWORDS and len(token) >= 2
        }
        if not tokens:
            return []
        expression = " OR ".join(f'"{term}"' for term in sorted(tokens))
        return self._fts_rows(expression, preferred, limit)

    def _fts_rows(self, expression: str, preferred: tuple[str, ...], limit: int) -> list[dict]:
        with self._connect() as db:
            if preferred:
                sources = [
                    row[0] for row in db.execute("SELECT source FROM files")
                    if self._source_matches(self._normalize(row[0]), preferred)
                ]
                if not sources:
                    return []
                placeholders = ",".join("?" for _ in sources)
                rows = db.execute(
                    "SELECT id,source,location,text,bm25(chunks) rank FROM chunks "
                    f"WHERE chunks MATCH ? AND source IN ({placeholders}) ORDER BY rank LIMIT ?",
                    (expression, *sources, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id,source,location,text,bm25(chunks) rank "
                    "FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT ?",
                    (expression, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def _metadata_candidate_rows(
        self,
        analysis: QueryAnalysis,
        preferred: tuple[str, ...] = (),
        limit_per_source: int = 24,
    ) -> list[dict]:
        if not analysis.lexical_terms:
            return []
        matches: list[dict] = []
        with self._connect() as db:
            sources = [row[0] for row in db.execute("SELECT source FROM files ORDER BY source COLLATE NOCASE")]
            for source in sources:
                source_norm = self._normalize(source)
                if preferred and not self._source_matches(source_norm, preferred):
                    continue
                if not all(term in source_norm for term in analysis.lexical_terms):
                    continue
                rows = db.execute(
                    "SELECT id,source,location,text,0.0 rank FROM chunks WHERE source = ? LIMIT ?",
                    (source, limit_per_source),
                ).fetchall()
                matches.extend(dict(row) for row in rows)
        return matches

    @staticmethod
    def _fuse_rankings(rankings: list[tuple[str, float, list[dict]]]) -> list[dict]:
        """Reciprocal Rank Fusion evita comparar BM25, bônus editoriais e metadados."""
        fused: dict[str, dict] = {}
        for strategy, weight, rows in rankings:
            for position, row in enumerate(rows, 1):
                item = fused.setdefault(
                    row["id"],
                    {**row, "rrf_score": 0.0, "retrieval_strategies": [], "original_scores": {}},
                )
                item["rrf_score"] += weight / (60 + position)
                item["retrieval_strategies"].append(strategy)
                item["original_scores"][strategy] = row.get("rank")
        return list(fused.values())

    def search(self, query: str, limit: int = 6, minimum_score: float = 0.08,
               source_filter: tuple[str, ...] | None = None, excluded_sources: tuple[str, ...] = (),
               include_diagnostics: bool = False):
        analysis = analyze_query(query)
        normalized_query = analysis.folded
        preferred = source_filter or self._preferred_sources(normalized_query)
        cache_key = (
            normalized_query,
            limit,
            round(float(minimum_score), 6),
            tuple(preferred),
            tuple(excluded_sources),
            bool(include_diagnostics),
        )
        cached = self._cached_search(cache_key)
        if cached is not None:
            return cached
        terms, expanded_terms = self._query_terms(query, preferred)
        index_guidance = self._index_guidance(query, preferred, excluded_sources)
        single_term = self._single_query_term(query)
        nominal_term = self._nominal_query_term(query)
        context_terms = self._guidance_context_terms(terms, index_guidance) if nominal_term else set()
        expanded_terms.update(context_terms)
        exact_rows = self._exact_candidate_rows(analysis, preferred)
        variant_rows = self._variant_candidate_rows(analysis, preferred)
        expansion_rows = self._semantic_expansion_rows(analysis, preferred)
        metadata_rows = self._metadata_candidate_rows(analysis, preferred)
        guidance_rows = self._guided_candidate_rows(index_guidance, preferred) if nominal_term else []
        anchor_rows = self._nominal_anchor_rows(nominal_term, preferred, excluded_sources) if nominal_term else []
        # Fallback global obrigatório: uma via editorial nunca substitui a busca em toda a base.
        global_rows = self._candidate_rows(query, limit=1200, additional_terms=context_terms)
        rankings = [
            ("lexical_exact", 2.4, exact_rows),
            ("lexical_variant", 1.7, variant_rows),
            ("semantic_expansion", 0.75, expansion_rows),
            ("title_metadata", 2.1, metadata_rows),
            ("index_guidance", 1.9, guidance_rows),
            ("nominal_anchor", 2.0, anchor_rows),
            ("global_fallback", 1.0, global_rows),
        ]
        candidate_rows = self._fuse_rankings(rankings)
        ranked: list[dict] = []
        eliminated: list[dict] = []
        for row in candidate_rows:
            source_norm = self._normalize(row["source"])
            if preferred and not self._source_matches(source_norm, preferred):
                eliminated.append({"id": row["id"], "reason": "metadata_filter"})
                continue
            if self._source_is_excluded(row["source"], excluded_sources):
                eliminated.append({"id": row["id"], "reason": "inactive_source"})
                continue
            text_norm = self._normalize(row["text"])
            text_terms = set(TOKEN_PATTERN.findall(text_norm))
            coverage = len(terms & text_terms) / max(len(terms), 1)
            variant_hits = len(set(analysis.variants) & text_terms)
            expanded_hits = len(expanded_terms & text_terms)
            frequency = sum(text_norm.count(term) for term in expanded_terms)
            heading_bonus = 0.12 if any(term in text_norm[:260] for term in terms | expanded_terms) else 0
            source_bonus = 0.22 if preferred else 0
            anchor_bonus = self._topic_anchor_bonus(terms, self._paragraph_numbers(text_norm))
            index_bonus = self._index_guidance_bonus(source_norm, text_norm, index_guidance)
            nominal_bonus = self._nominal_match_bonus(nominal_term, row["text"])
            strategies = set(row.get("retrieval_strategies", []))
            protected = bool(
                coverage or variant_hits or index_bonus or nominal_bonus
                or strategies & {"lexical_exact", "title_metadata", "index_guidance", "nominal_anchor"}
            )
            if not protected and expanded_hits == 0:
                eliminated.append({"id": row["id"], "reason": "no_query_evidence"})
                continue
            note_penalty = self._note_fragment_penalty(text_norm)
            score = (
                coverage + min(frequency, 10) * 0.035 + row.get("rrf_score", 0) * 8 + heading_bonus
                + source_bonus + anchor_bonus + index_bonus + nominal_bonus - note_penalty
            )
            ranked.append({
                **row,
                "score": round(score, 4),
                "score_normalized": round(max(score, 0) / (1 + max(score, 0)), 4),
                "_index_chunk": self._looks_like_index_chunk(source_norm, row["text"]),
            })
        ranked.sort(key=lambda item: (item["score"], item.get("rrf_score", 0)), reverse=True)
        substantive_sources = {item["source"] for item in ranked if not item["_index_chunk"]}
        ranked = [
            item for item in ranked
            if not item["_index_chunk"] or item["source"] not in substantive_sources
        ]
        for item in ranked:
            item.pop("_index_chunk", None)
        results = self._diversify(ranked, limit, bool(preferred))
        diagnostics = {
            "query": analysis.to_dict(),
            "embedding": {
                "model": None,
                "dimension": 0,
                "status": "not_configured_fts5_hybrid",
            },
            "collection": str(self.index_file),
            "metadata_filters": list(preferred),
            "excluded_sources": list(excluded_sources),
            "minimum_score_requested": minimum_score,
            "threshold_policy": "dynamic_exact_and_lexical_matches_are_protected",
            "candidate_counts": {name: len(rows) for name, _, rows in rankings},
            "candidates_fused": len(candidate_rows),
            "eliminated": eliminated[:200] if include_diagnostics else [],
            "reranking": [
                {
                    "id": item["id"],
                    "source": item["source"],
                    "score": item["score"],
                    "score_normalized": item["score_normalized"],
                    "strategies": item.get("retrieval_strategies", []),
                }
                for item in results
            ],
        }
        value = (results, diagnostics) if include_diagnostics else results
        return self._cache_search(cache_key, value)

    def search_ordered(
        self,
        query: str,
        limit: int = 14,
        minimum_score: float = 0.08,
        excluded_sources: tuple[str, ...] = (),
        include_diagnostics: bool = False,
    ):
        source_order = SINGLE_TERM_ORDERED_SOURCES if self._single_query_term(query) else ORDERED_SOURCES
        search_result = self.search(
            query,
            limit=300,
            minimum_score=minimum_score,
            excluded_sources=excluded_sources,
            include_diagnostics=include_diagnostics,
        )
        if include_diagnostics:
            candidates, diagnostics = search_result
        else:
            candidates, diagnostics = search_result, None
        buckets = [[] for _ in range(len(source_order) + 1)]
        for item in candidates:
            normalized = self._normalize(item["source"])
            bucket = len(source_order)
            for index, (_, hints, _) in enumerate(source_order):
                if any(self._normalize(hint) in normalized for hint in hints):
                    bucket = index
                    break
            buckets[bucket].append(item)
        selected = []
        for order, ((label, _, quota), bucket) in enumerate(zip(source_order, buckets), 1):
            selected.extend({**item, "ordem": order, "categoria": label} for item in bucket[:quota])
        remaining = max(limit - len(selected), 0)
        selected.extend(
            {**item, "ordem": len(source_order) + 1, "categoria": "Demais documentos"}
            for item in buckets[-1][:remaining]
        )
        ordered = self._enrich_references(selected[:limit])
        if diagnostics is not None:
            diagnostics["selected_chunks"] = [
                {
                    "id": item["id"],
                    "source": item["source"],
                    "location": item["location"],
                    "score": item["score"],
                    "strategies": item.get("retrieval_strategies", []),
                }
                for item in ordered
            ]
            diagnostics["final_count"] = len(ordered)
            return ordered, diagnostics
        return ordered

    def _enrich_references(self, results: list[dict]) -> list[dict]:
        for item in results:
            normalized = self._normalize(item["source"])
            text = item.get("text", "")
            refs = []
            if "catecismo" in normalized:
                refs = re.findall(r"(?:^|\n)\s*(\d{1,4})\.\s", text)
                if not refs:
                    refs = re.findall(r"\b(1[0-9]{3}|2[0-8][0-9]{2})\.\s", text)
            elif "biblia" in normalized:
                refs = [re.sub(r"\s*,\s*", ",", match.group()) for match in BIBLE_REFERENCE_PATTERN.finditer(text)]
            item["referencias"] = list(dict.fromkeys(refs))[:12]
        return results

    def _index_guidance(
        self,
        query: str,
        preferred: tuple[str, ...] = (),
        excluded_sources: tuple[str, ...] = (),
    ) -> dict[str, dict[str, set[str]]]:
        """Consulta primeiro os indices das obras que possuem mapa interno.

        Alguns PDFs convertidos ficam com paginas fora de ordem. Por isso esta etapa nao
        tenta confiar na posicao fisica do arquivo: ela procura linhas de indice, extrai
        referencias internas e depois usa essas referencias para favorecer os trechos
        doutrinais correspondentes.
        """
        nominal_term = self._nominal_query_term(query)
        if nominal_term:
            return self._nominal_index_guidance(nominal_term, preferred, excluded_sources)

        terms, expanded_terms = self._query_terms(query, preferred)
        lookup_terms = terms | expanded_terms
        if not lookup_terms:
            return {}
        expression = " OR ".join(f"{term}*" for term in sorted(lookup_terms))
        guidance: dict[str, dict[str, set[str]]] = {}
        with self._connect() as db:
            rows = db.execute(
                "SELECT source,location,text,bm25(chunks) rank FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT 700",
                (expression,),
            ).fetchall()

        for row in rows:
            source = row["source"]
            source_norm = self._normalize(source)
            if not self._is_indexed_source(source_norm):
                continue
            if preferred and not self._source_matches(source_norm, preferred):
                continue
            if excluded_sources and any(hint in source_norm for hint in excluded_sources):
                continue
            text = row["text"]
            if not self._looks_like_index_chunk(source_norm, text):
                continue
            item = guidance.setdefault(source_norm, {"paragraphs": set(), "pages": set(), "codes": set(), "headings": set()})
            for line in text.splitlines():
                line_norm = self._normalize(line)
                if not line_norm.strip() or not any(term in line_norm for term in lookup_terms):
                    continue
                item["paragraphs"].update(self._extract_index_paragraphs(line_norm))
                item["pages"].update(self._extract_index_pages(source_norm, line_norm))
                item["codes"].update(code.lower() for code in SYSTEMATIC_INDEX_CODE_PATTERN.findall(line))
                heading = re.sub(r"\.{2,}.*$", "", line_norm)
                heading = re.sub(r"\b\d{1,4}[a-z]?\b", "", heading)
                heading = re.sub(r"\s+", " ", heading).strip(" .;:-")
                if 4 <= len(heading) <= 90:
                    item["headings"].add(heading)
        return guidance

    def _nominal_index_guidance(
        self,
        term: str,
        preferred: tuple[str, ...] = (),
        excluded_sources: tuple[str, ...] = (),
    ) -> dict[str, dict[str, set[str]]]:
        """Procura uma palavra isolada nos três índices, na ordem editorial."""
        expression = f'"{term}"'
        guidance: dict[str, dict[str, set[str]]] = {}
        with self._connect() as db:
            sources = [row[0] for row in db.execute("SELECT source FROM files ORDER BY source COLLATE NOCASE")]
            for _, hints, _ in NOMINAL_INDEX_SOURCES:
                if preferred and not any(self._source_matches(self._normalize(hint), preferred) for hint in hints):
                    continue
                matching_sources = [
                    source for source in sources
                    if self._source_matches(self._normalize(source), hints)
                    and not self._source_is_excluded(source, excluded_sources)
                ]
                for source in matching_sources:
                    rows = db.execute(
                        "SELECT source,location,text,bm25(chunks) rank "
                        "FROM chunks WHERE chunks MATCH ? AND source = ? ORDER BY rank LIMIT 700",
                        (expression, source),
                    ).fetchall()
                    self._collect_index_guidance(rows, {term}, guidance)
        return {
            source: item for source, item in guidance.items()
            if any(item.values())
        }

    def _collect_index_guidance(
        self,
        rows,
        lookup_terms: set[str],
        guidance: dict[str, dict[str, set[str]]],
    ) -> None:
        for row in rows:
            source = row["source"]
            source_norm = self._normalize(source)
            text = row["text"]
            if not self._looks_like_index_chunk(source_norm, text):
                continue
            item = guidance.setdefault(
                source_norm,
                {"paragraphs": set(), "pages": set(), "codes": set(), "headings": set()},
            )
            for line in text.splitlines():
                line_norm = self._normalize(line)
                if not line_norm.strip() or not any(
                    re.search(rf"\b{re.escape(term)}\b", line_norm) for term in lookup_terms
                ):
                    continue
                item["paragraphs"].update(self._extract_index_paragraphs(line_norm))
                item["pages"].update(self._extract_index_pages(source_norm, line_norm))
                item["codes"].update(code.lower() for code in SYSTEMATIC_INDEX_CODE_PATTERN.findall(line))
                heading = re.sub(r"\.{2,}.*$", "", line_norm)
                heading = re.sub(r"\b\d{1,4}[a-z]?\b", "", heading)
                heading = re.sub(r"\s+", " ", heading).strip(" .;:-")
                if 4 <= len(heading) <= 90:
                    item["headings"].add(heading)

    def _guided_candidate_rows(
        self,
        guidance: dict[str, dict[str, set[str]]],
        preferred: tuple[str, ...] = (),
    ) -> list[dict]:
        """Recupera o conteúdo apontado pelo sumário, mesmo sem repetir o termo."""
        candidates: list[dict] = []
        with self._connect() as db:
            for source_norm, item in guidance.items():
                if preferred and not self._source_matches(source_norm, preferred):
                    continue
                source_row = db.execute(
                    "SELECT source FROM files WHERE lower(source) = lower(?)",
                    (source_norm,),
                ).fetchone()
                if source_row is None:
                    source_row = next(
                        (row for row in db.execute("SELECT source FROM files") if self._normalize(row[0]) == source_norm),
                        None,
                    )
                if source_row is None:
                    continue
                source = source_row[0]
                lookup_tokens = set(list(item["paragraphs"])[:120])
                lookup_tokens.update(list(item["pages"])[:30])
                for code in item["codes"]:
                    lookup_tokens.update(token for token in TOKEN_PATTERN.findall(code) if len(token) >= 2)
                lookup_tokens.update(list(self._guidance_context_terms(set(), {source_norm: item}))[:30])
                if not lookup_tokens:
                    continue
                expression = " OR ".join(f'"{token}"' for token in sorted(lookup_tokens))
                rows = db.execute(
                    "SELECT id,source,location,text,bm25(chunks) rank "
                    "FROM chunks WHERE chunks MATCH ? AND source = ? ORDER BY rank LIMIT 240",
                    (expression, source),
                ).fetchall()
                for row in rows:
                    row_dict = dict(row)
                    text_norm = self._normalize(row_dict["text"])
                    if self._looks_like_index_chunk(source_norm, row_dict["text"]):
                        continue
                    if self._index_guidance_bonus(source_norm, text_norm, guidance) > 0:
                        candidates.append(row_dict)
        return candidates

    def _nominal_anchor_rows(
        self,
        term: str,
        preferred: tuple[str, ...] = (),
        excluded_sources: tuple[str, ...] = (),
    ) -> list[dict]:
        """Inclui definições e títulos que podem ficar além do corte normal do FTS."""
        expression = f'"{term}"'
        anchored: list[dict] = []
        with self._connect() as db:
            all_sources = [row[0] for row in db.execute("SELECT source FROM files ORDER BY source COLLATE NOCASE")]
            priority_sources: list[str] = []
            for _, hints, _ in NOMINAL_INDEX_SOURCES:
                priority_sources.extend(
                    source for source in all_sources
                    if source not in priority_sources
                    and self._source_matches(self._normalize(source), hints)
                )
            for source in priority_sources:
                source_norm = self._normalize(source)
                if preferred and not self._source_matches(source_norm, preferred):
                    continue
                if self._source_is_excluded(source, excluded_sources):
                    continue
                rows = db.execute(
                    "SELECT id,source,location,text,bm25(chunks) rank "
                    "FROM chunks WHERE chunks MATCH ? AND source = ? ORDER BY rank LIMIT 360",
                    (expression, source),
                ).fetchall()
                for row in rows:
                    row_dict = dict(row)
                    bonus = self._nominal_match_bonus(term, row_dict["text"])
                    if bonus >= 0.9:
                        row_dict["_nominal_anchor_bonus"] = bonus
                        anchored.append(row_dict)
        anchored.sort(key=lambda item: (item["_nominal_anchor_bonus"], -item["rank"]), reverse=True)
        for item in anchored:
            item.pop("_nominal_anchor_bonus", None)
        return anchored[:240]

    @classmethod
    def _guidance_context_terms(
        cls,
        query_terms: set[str],
        guidance: dict[str, dict[str, set[str]]],
    ) -> set[str]:
        counts: Counter[str] = Counter()
        for item in guidance.values():
            for heading in item["headings"]:
                counts.update(
                    term for term in TOKEN_PATTERN.findall(cls._normalize(heading))
                    if len(term) > 3
                    and term not in INDEX_CONTEXT_STOPWORDS
                    and term not in query_terms
                    and not any(character.isdigit() for character in term)
                )
        return {term for term, _ in counts.most_common(18)}

    @classmethod
    def _single_query_term(cls, query: str) -> str | None:
        tokens = TOKEN_PATTERN.findall(cls._normalize(query).strip())
        if len(tokens) != 1 or tokens[0] in QUERY_STOPWORDS or len(tokens[0]) < 2:
            return None
        return tokens[0]

    @classmethod
    def _nominal_query_term(cls, query: str) -> str | None:
        """Reconhece uma palavra isolada ou uma pergunta curta que pede sua definição."""
        single_term = cls._single_query_term(query)
        if single_term:
            return single_term

        normalized = re.sub(r"\s+", " ", cls._normalize(query)).strip(" .?!:;")
        definition_patterns = (
            r"^(?:o )?que e (?:o |a )?(.+)$",
            r"^(?:o )?que significa (?:o |a )?(.+)$",
            r"^defina (?:o |a )?(.+)$",
            r"^definicao (?:de|do|da) (?:o |a )?(.+)$",
            r"^qual (?:e )?a definicao (?:de|do|da) (?:o |a )?(.+)$",
        )
        for pattern in definition_patterns:
            match = re.match(pattern, normalized)
            if not match:
                continue
            subject_tokens = [
                token for token in TOKEN_PATTERN.findall(match.group(1))
                if token not in QUERY_STOPWORDS and len(token) >= 2
            ]
            if len(subject_tokens) == 1:
                return subject_tokens[0]
        return None

    @classmethod
    def _nominal_match_bonus(cls, term: str | None, text: str) -> float:
        """Favorece definições e títulos nominais, em vez de ocorrências periféricas."""
        if not term:
            return 0.0
        text_norm = cls._normalize(text)
        escaped = re.escape(term)
        if re.search(rf"\bdefinicao\s+(?:de|do|da)\s+(?:o\s+|a\s+)?{escaped}\b", text_norm):
            return 1.7
        if re.search(rf"\bo\s+que\s+e\s+(?:o\s+|a\s+)?{escaped}\b", text_norm):
            return 1.55
        for raw_line in text.splitlines():
            line_norm = cls._normalize(raw_line).strip(" .;:-")
            if not re.search(rf"\b{escaped}\b", line_norm):
                continue
            if re.fullmatch(rf"(?:[ivxlcdm]+[.)]?\s*)?(?:o\s+|a\s+)?{escaped}", line_norm):
                return 1.35
            if len(line_norm) <= 120 and re.search(
                rf"\b(?:definicao|essencia|natureza|raizes|origem)\b.*\b{escaped}\b|"
                rf"\b{escaped}\b.*\b(?:definicao|essencia|natureza|raizes|origem)\b",
                line_norm,
            ):
                return 1.15
        if re.search(rf"\b{escaped}\s+e\s+(?:uma|um|a|o)\b", text_norm):
            return 0.9
        return 0.0

    @classmethod
    def _source_is_excluded(cls, source: str, excluded_sources: tuple[str, ...]) -> bool:
        source_norm = cls._normalize(source)
        return any(cls._normalize(excluded) in source_norm for excluded in excluded_sources)

    @staticmethod
    def _extract_index_paragraphs(line_norm: str) -> set[str]:
        references: set[str] = set()
        for start, end in re.findall(r"\b(?:a)?(\d{3,4})\s*[-–]\s*(?:a)?(\d{3,4})", line_norm):
            start_number, end_number = int(start), int(end)
            if 100 <= start_number <= end_number <= 9999 and end_number - start_number <= 80:
                references.update(str(value) for value in range(start_number, end_number + 1))
        for value in re.findall(r"\b(?:a)?(\d{3,4})(?:s|[a-z])?\b", line_norm):
            number = int(value)
            if 100 <= number <= 9999:
                references.add(str(number))
        return references

    @staticmethod
    def _extract_index_pages(source_norm: str, line_norm: str) -> set[str]:
        if "a fe explicada" not in source_norm:
            return set()
        pages = set()
        dotted = re.search(r"\.{2,}\s*(\d{1,3})\s*$", line_norm)
        if dotted:
            pages.add(dotted.group(1))
        return pages

    @classmethod
    def _is_indexed_source(cls, source_norm: str) -> bool:
        return cls._source_matches(source_norm, INDEXED_SOURCE_HINTS)

    @classmethod
    def _source_matches(cls, source_norm: str, hints: tuple[str, ...]) -> bool:
        source_loose = re.sub(r"[-_]+", " ", source_norm)
        return any(cls._normalize(hint) in source_norm or cls._normalize(hint) in source_loose for hint in hints)

    @classmethod
    def _looks_like_index_chunk(cls, source_norm: str, text: str) -> bool:
        text_norm = cls._normalize(text)
        if "indice" in text_norm or "sumario" in text_norm:
            return True
        if "a fe explicada" in source_norm and re.search(r"\.{4,}\s*\d{1,3}\b", text_norm):
            return True
        if "simbolos" in source_norm or "declaracoes-de-fe-e-moral" in source_norm:
            if "indice sistematico" in text_norm:
                return True
            if len(SYSTEMATIC_INDEX_CODE_PATTERN.findall(text)) >= 2:
                return True
            if re.search(r"\bcf\.\s*[A-Z]:\d", text):
                return True
        return False

    @staticmethod
    def _index_guidance_bonus(source_norm: str, text_norm: str, guidance: dict[str, dict[str, set[str]]]) -> float:
        item = guidance.get(source_norm)
        if not item:
            return 0.0
        bonus = 0.0
        paragraph_numbers = set(re.findall(r"\b(\d{3,4})\.\s", text_norm))
        if item["paragraphs"] & paragraph_numbers:
            bonus += 0.9
        elif any(f"{reference}." in text_norm[:1200] for reference in item["paragraphs"]):
            bonus += 0.55
        if item["pages"] and any(
            re.search(rf"(?:pagina|p.gina|\[p\.)\s*{re.escape(page)}\b", text_norm)
            for page in item["pages"]
        ):
            bonus += 0.75
        codes = {code.lower() for code in SYSTEMATIC_INDEX_CODE_PATTERN.findall(text_norm.upper())}
        if item["codes"] & codes:
            bonus += 0.65
        if item["headings"] and any(heading and heading in text_norm[:900] for heading in item["headings"]):
            bonus += 0.25
        return min(bonus, 1.35)

    @staticmethod
    def _note_fragment_penalty(text_norm: str) -> float:
        opening = text_norm[:360]
        if "## pagina" in opening and ("aas " in opening or opening.count("cf.") >= 2 or len(re.findall(r"\[\d{2,4}\]", opening)) >= 2):
            return 0.45
        return 0.0

    @staticmethod
    def _paragraph_numbers(normalized_text: str) -> set[int]:
        return {
            int(value)
            for value in re.findall(r"(?:^|\n|\s)(\d{1,4})\.\s", normalized_text)
            if value.isdigit()
        }

    @staticmethod
    def _topic_anchor_bonus(terms: set[str], paragraph_numbers: set[int]) -> float:
        bonus = 0.0
        for term in terms:
            for start, end, value in TOPIC_REFERENCE_RANGES.get(term, ()):
                if any(start <= number <= end for number in paragraph_numbers):
                    bonus = max(bonus, value)
        return bonus

    def status(self) -> dict:
        with self._connect() as db:
            documents = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            updated = db.execute("SELECT value FROM metadata WHERE key='updated_at'").fetchone()
            errors = [{"arquivo": row["source"], "erro": row["error"]} for row in db.execute("SELECT * FROM errors")]
        return {"documentos": documents, "trechos": chunks, "ultima_atualizacao": updated[0] if updated else None, "erros": errors}

    def document_names(self) -> list[str]:
        with self._connect() as db:
            return [row[0] for row in db.execute("SELECT source FROM files ORDER BY source COLLATE NOCASE")]

    @classmethod
    def _preferred_sources(cls, normalized_query: str) -> tuple[str, ...]:
        matches = []
        for query_hint, source_hints in SOURCE_HINTS.items():
            if query_hint in normalized_query:
                matches.extend(source_hints)
        return tuple(matches)

    @staticmethod
    def _diversify(ranked: list[dict], limit: int, explicit: bool) -> list[dict]:
        selected, per_source = [], Counter()
        source_limit = limit if explicit else max(2, (limit + 1) // 2)
        for item in ranked:
            if per_source[item["source"]] >= source_limit:
                continue
            selected.append(item)
            per_source[item["source"]] += 1
            if len(selected) == limit:
                break
        return selected

    def _split_text(self, text: str) -> list[str]:
        clean = re.sub(r"[ \t]+", " ", text)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        if len(clean) <= self.chunk_size:
            return [clean] if clean else []
        chunks, start = [], 0
        while start < len(clean):
            end = min(start + self.chunk_size, len(clean))
            if end < len(clean):
                boundary = max(clean.rfind(". ", start, end), clean.rfind("\n", start, end))
                if boundary > start + self.chunk_size // 2:
                    end = boundary + 1
            chunk = clean[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(clean):
                break
            start = max(end - self.overlap, start + 1)
        return chunks

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.lower())
        return "".join(character for character in normalized if not unicodedata.combining(character))
