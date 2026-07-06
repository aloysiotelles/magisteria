from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from pathlib import Path
import unicodedata

from services.document_loader import discover_documents, load_document


TOKEN_PATTERN = re.compile(r"[a-z0-9à-ÿ]{2,}", re.IGNORECASE)
QUERY_STOPWORDS = {
    "que", "como", "qual", "quais", "uma", "uns", "das", "dos", "para", "por", "com",
    "sem", "sobre", "segundo", "partir", "ensina", "ensinam", "igreja", "documento", "documentos",
}
SOURCE_HINTS = {
    "catecismo": ("catecismo",), "biblia": ("biblia",), "missal": ("missal",),
    "suma": ("suma teologica",), "doutrina social": ("doutrina social",),
    "d sistema": ("simbolos definicoes",),
}
ORDERED_SOURCES = (
    ("Catecismo da Igreja Católica", ("catecismo",), 5),
    ("Compêndio dos símbolos, definições e declarações", ("simbolos", "definicoes"), 2),
    ("Compêndio da Doutrina Social da Igreja", ("doutrina-social", "doutrina social"), 2),
    ("Suma Teológica", ("suma teologica", "suma-teologica", "suma"), 2),
    ("Bíblia Ave Maria — citações bíblicas", ("biblia ave maria", "biblia"), 4),
    ("Compêndio Vaticano II", ("compendio vaticano ii", "vaticano ii"), 3),
)
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


class LocalVectorStore:
    """Indice SQLite/FTS em disco, adequado a bases grandes e pouca memoria."""

    def __init__(self, documents_dir: Path, index_file: Path, chunk_size: int, overlap: int):
        self.documents_dir = documents_dir
        self.index_file = index_file
        self.chunk_size = chunk_size
        self.overlap = overlap
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
        return self.status()

    def _candidate_rows(self, query: str, limit: int = 300) -> list[dict]:
        terms = [term for term in TOKEN_PATTERN.findall(self._normalize(query)) if term not in QUERY_STOPWORDS and len(term) > 2]
        expanded = set(terms)
        for term in terms:
            expanded.update(BIBLE_QUERY_EXPANSIONS.get(term, set()))
        if not expanded:
            return []
        expression = " OR ".join(f'"{term}"' for term in sorted(expanded))
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,source,location,text,bm25(chunks) rank FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT ?",
                (expression, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, query: str, limit: int = 6, minimum_score: float = 0.08,
               source_filter: tuple[str, ...] | None = None, excluded_sources: tuple[str, ...] = ()) -> list[dict]:
        normalized_query = self._normalize(query)
        terms = {t for t in TOKEN_PATTERN.findall(normalized_query) if t not in QUERY_STOPWORDS and len(t) > 2}
        preferred = source_filter or self._preferred_sources(normalized_query)
        if preferred:
            terms -= {t for hint in preferred for t in TOKEN_PATTERN.findall(hint)}
        ranked = []
        for row in self._candidate_rows(query):
            source_norm = self._normalize(row["source"])
            if preferred and not any(hint in source_norm for hint in preferred):
                continue
            if excluded_sources and any(hint in source_norm for hint in excluded_sources):
                continue
            text_terms = set(TOKEN_PATTERN.findall(self._normalize(row["text"])))
            coverage = len(terms & text_terms) / max(len(terms), 1)
            if coverage < minimum_score:
                continue
            ranked.append({**row, "score": round(coverage + (0.18 if preferred else 0), 4)})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return self._diversify(ranked, limit, bool(preferred))

    def search_ordered(self, query: str, limit: int = 14, minimum_score: float = 0.08) -> list[dict]:
        candidates = self.search(query, limit=300, minimum_score=minimum_score)
        buckets = [[] for _ in range(len(ORDERED_SOURCES) + 1)]
        for item in candidates:
            normalized = self._normalize(item["source"])
            bucket = len(ORDERED_SOURCES)
            for index, (_, hints, _) in enumerate(ORDERED_SOURCES):
                if any(self._normalize(hint) in normalized for hint in hints):
                    bucket = index
                    break
            buckets[bucket].append(item)
        selected = []
        for order, ((label, _, quota), bucket) in enumerate(zip(ORDERED_SOURCES, buckets), 1):
            selected.extend({**item, "ordem": order, "categoria": label} for item in bucket[:quota])
        remaining = max(limit - len(selected), 0)
        selected.extend(
            {**item, "ordem": len(ORDERED_SOURCES) + 1, "categoria": "Demais documentos"}
            for item in buckets[-1][:remaining]
        )
        return self._enrich_references(selected[:limit])

    def _enrich_references(self, results: list[dict]) -> list[dict]:
        for item in results:
            normalized = self._normalize(item["source"])
            text = item.get("text", "")
            refs = []
            if "catecismo" in normalized:
                refs = re.findall(r"(?:^|\n)\s*(\d{1,4})\.\s", text)
            elif "biblia" in normalized:
                refs = [re.sub(r"\s*,\s*", ",", match.group()) for match in BIBLE_REFERENCE_PATTERN.finditer(text)]
            item["referencias"] = list(dict.fromkeys(refs))[:12]
        return results

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
