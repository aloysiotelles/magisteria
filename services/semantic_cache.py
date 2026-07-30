from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from services.catholic_taxonomy import fold_text
from services.response_planning import ResponsePlan


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _authority_level(source: str) -> int:
    normalized = fold_text(source)
    priorities = (
        (1, ("biblia", "sagrada escritura")),
        (2, ("concilio", "vaticano ii")),
        (3, ("simbolos", "dogma", "denzinger")),
        (4, ("catecismo",)),
        (5, ("codigo de direito canonico", "direito canonico")),
        (6, ("enciclica", "exortacao", "carta apostolica", "papa", "pontificio")),
        (7, ("dicasterio", "congregacao", "doutrina da fe")),
        (8, ("missal", "liturgia")),
        (9, ("padres da igreja", "doutor da igreja", "suma teologica")),
        (10, ("cnbb", "episcopal")),
    )
    for level, hints in priorities:
        if any(hint in normalized for hint in hints):
            return level
    return 11


class SemanticCache:
    """Caches plans and documentary evidence, never generated answers."""

    def __init__(self, database_file: Path, ttl_seconds: int = 86_400):
        self.database_file = database_file
        self.ttl_seconds = max(int(ttl_seconds), 60)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_file, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _cache_key(plan: ResponsePlan, corpus_version: str) -> str:
        material = "|".join((
            plan.semantic_signature,
            corpus_version,
            plan.taxonomy_version,
            plan.strategy_version,
        ))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def get(self, plan: ResponsePlan, corpus_version: str) -> dict | None:
        now = _utcnow().isoformat()
        key = self._cache_key(plan, corpus_version)
        with self._connect() as db:
            db.execute("DELETE FROM semantic_cache_entries WHERE expires_at <= ?", (now,))
            row = db.execute(
                """
                SELECT * FROM semantic_cache_entries
                WHERE cache_key = ? AND corpus_version = ? AND taxonomy_version = ?
                  AND strategy_version = ? AND expires_at > ?
                """,
                (key, corpus_version, plan.taxonomy_version, plan.strategy_version, now),
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE semantic_cache_entries SET hit_count = hit_count + 1, last_hit_at = ? WHERE cache_key = ?",
                (now, key),
            )
        return {
            "plan": json.loads(row["plan_json"]),
            "chunks": json.loads(row["chunks_json"]),
            "document_ids": json.loads(row["document_ids_json"]),
            "references": json.loads(row["references_json"]),
        }

    def put(self, plan: ResponsePlan, corpus_version: str, chunks: list[dict]) -> None:
        now = _utcnow()
        expires = now + timedelta(seconds=self.ttl_seconds)
        key = self._cache_key(plan, corpus_version)
        safe_chunks = [
            {
                field: chunk.get(field)
                for field in (
                    "id", "source", "location", "text", "score", "score_normalized",
                    "ordem", "categoria", "referencias", "component", "components",
                )
                if chunk.get(field) is not None
            }
            for chunk in chunks
        ]
        document_ids = list(dict.fromkeys(str(chunk.get("id") or "") for chunk in chunks if chunk.get("id")))
        references = list(dict.fromkeys(
            reference
            for chunk in chunks
            for reference in (chunk.get("referencias") or [])
        ))
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO semantic_cache_entries(
                    cache_key,topic_key,semantic_signature,plan_json,chunks_json,
                    document_ids_json,references_json,corpus_version,taxonomy_version,
                    strategy_version,created_at,expires_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    plan_json=excluded.plan_json,
                    chunks_json=excluded.chunks_json,
                    document_ids_json=excluded.document_ids_json,
                    references_json=excluded.references_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at
                """,
                (
                    key, plan.topic_key, plan.semantic_signature,
                    json.dumps(plan.to_dict(), ensure_ascii=False),
                    json.dumps(safe_chunks, ensure_ascii=False),
                    json.dumps(document_ids, ensure_ascii=False),
                    json.dumps(references, ensure_ascii=False),
                    corpus_version, plan.taxonomy_version, plan.strategy_version,
                    now.isoformat(), expires.isoformat(),
                ),
            )
            self._update_document_summaries(db, plan, corpus_version, chunks, now.isoformat())

    def _update_document_summaries(
        self,
        db: sqlite3.Connection,
        plan: ResponsePlan,
        corpus_version: str,
        chunks: list[dict],
        now: str,
    ) -> None:
        by_source: dict[str, list[dict]] = {}
        for chunk in chunks:
            by_source.setdefault(str(chunk.get("source") or "Documento"), []).append(chunk)
        all_sources = tuple(by_source)
        for source, source_chunks in by_source.items():
            references = list(dict.fromkeys(
                reference
                for chunk in source_chunks
                for reference in (chunk.get("referencias") or [])
            ))
            best = max(source_chunks, key=lambda item: float(item.get("score") or 0))
            excerpt = re.sub(r"\s+", " ", str(best.get("text") or "")).strip()[:1500]
            subtopics = list(plan.active_components or plan.components)
            keywords = list(dict.fromkeys((plan.theme, *subtopics, *plan.dimensions)))[:24]
            related_documents = [item for item in all_sources if item != source][:12]
            author_or_authority = str(
                best.get("author_or_authority") or best.get("author") or best.get("authority") or ""
            )[:240]
            document_date = str(best.get("document_date") or best.get("date") or "")[:80]
            db.execute(
                """
                INSERT INTO document_technical_summaries(
                    source,title,document_type,author_or_authority,document_date,authority_level,
                    topics_json,subtopics_json,doctrinal_claims_json,keywords_json,
                    related_documents_json,references_json,relevant_excerpt,locator,
                    corpus_version,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source) DO UPDATE SET
                    author_or_authority=excluded.author_or_authority,
                    document_date=excluded.document_date,
                    authority_level=excluded.authority_level,
                    topics_json=excluded.topics_json,
                    subtopics_json=excluded.subtopics_json,
                    doctrinal_claims_json=excluded.doctrinal_claims_json,
                    keywords_json=excluded.keywords_json,
                    related_documents_json=excluded.related_documents_json,
                    references_json=excluded.references_json,
                    relevant_excerpt=excluded.relevant_excerpt,
                    locator=excluded.locator,
                    corpus_version=excluded.corpus_version,
                    use_count=document_technical_summaries.use_count + 1,
                    updated_at=excluded.updated_at
                """,
                (
                    source, Path(source).stem.replace("_", " ").replace("-", " "),
                    Path(source).suffix.lstrip(".").upper() or "Documento",
                    author_or_authority, document_date, _authority_level(source),
                    json.dumps([plan.topic_key], ensure_ascii=False),
                    json.dumps(subtopics, ensure_ascii=False),
                    json.dumps([], ensure_ascii=False),
                    json.dumps(keywords, ensure_ascii=False),
                    json.dumps(related_documents, ensure_ascii=False),
                    json.dumps(references, ensure_ascii=False), excerpt,
                    str(best.get("location") or ""), corpus_version, now,
                ),
            )

    def invalidate_all(self) -> int:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM semantic_cache_entries")
            return int(cursor.rowcount or 0)

    def technical_source_hints(
        self,
        topic_key: str,
        corpus_version: str,
        limit: int = 8,
    ) -> tuple[str, ...]:
        pattern = f'%"{topic_key}"%'
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT source FROM document_technical_summaries
                WHERE corpus_version = ? AND topics_json LIKE ?
                ORDER BY authority_level, use_count DESC LIMIT ?
                """,
                (corpus_version, pattern, min(max(int(limit), 1), 20)),
            ).fetchall()
        return tuple(str(row["source"]) for row in rows)
