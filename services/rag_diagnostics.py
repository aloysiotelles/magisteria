from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid


EMAIL_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
LONG_NUMBER_PATTERN = re.compile(r"\b\d{6,}\b")
SECRET_PATTERN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]+|Bearer\s+\S+)\b", re.IGNORECASE)


def new_request_id() -> str:
    return uuid.uuid4().hex


def redact_query(text: str) -> str:
    redacted = EMAIL_PATTERN.sub("[email]", text)
    redacted = LONG_NUMBER_PATTERN.sub("[numero]", redacted)
    redacted = SECRET_PATTERN.sub("[segredo]", redacted)
    return redacted[:500]


def numeric_metrics(value: object) -> dict[str, int | float | bool | None]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key)[:80]: item
        for key, item in value.items()
        if isinstance(item, (int, float, bool)) or item is None
    }


class RAGDiagnosticsRepository:
    def __init__(self, database_file: Path, debug: bool = False, retention_days: int = 14):
        self.database_file = database_file
        self.debug = debug
        self.retention_days = min(max(int(retention_days), 1), 90)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_file, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_diagnostics (
                    request_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    normalized_query TEXT NOT NULL,
                    query_type TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    final_count INTEGER NOT NULL DEFAULT 0,
                    best_score REAL,
                    documents_json TEXT NOT NULL DEFAULT '[]',
                    filters_json TEXT NOT NULL DEFAULT '[]',
                    validator_json TEXT NOT NULL DEFAULT '{}',
                    final_reason TEXT NOT NULL DEFAULT '',
                    context_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost REAL,
                    depth_level TEXT NOT NULL DEFAULT 'explicativo',
                    topic_category TEXT NOT NULL DEFAULT 'catequese_geral',
                    strategy_version TEXT NOT NULL DEFAULT 'legacy',
                    component_count INTEGER NOT NULL DEFAULT 0,
                    retrieved_chunk_count INTEGER NOT NULL DEFAULT 0,
                    input_tokens_estimated INTEGER NOT NULL DEFAULT 0,
                    output_tokens_estimated INTEGER NOT NULL DEFAULT 0,
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    coverage_failures INTEGER NOT NULL DEFAULT 0,
                    citation_errors INTEGER NOT NULL DEFAULT 0,
                    regenerated INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    trace_json TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_diagnostics_created_at ON rag_diagnostics(created_at)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(rag_diagnostics)").fetchall()}
            additions = {
                "depth_level": "TEXT NOT NULL DEFAULT 'explicativo'",
                "topic_category": "TEXT NOT NULL DEFAULT 'catequese_geral'",
                "strategy_version": "TEXT NOT NULL DEFAULT 'legacy'",
                "component_count": "INTEGER NOT NULL DEFAULT 0",
                "retrieved_chunk_count": "INTEGER NOT NULL DEFAULT 0",
                "input_tokens_estimated": "INTEGER NOT NULL DEFAULT 0",
                "output_tokens_estimated": "INTEGER NOT NULL DEFAULT 0",
                "cache_hit": "INTEGER NOT NULL DEFAULT 0",
                "coverage_failures": "INTEGER NOT NULL DEFAULT 0",
                "citation_errors": "INTEGER NOT NULL DEFAULT 0",
                "regenerated": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, definition in additions.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE rag_diagnostics ADD COLUMN {name} {definition}")
            # Remove legacy free-form diagnostic text during the schema migration.
            db.execute(
                """UPDATE rag_diagnostics
                   SET query_text = '', normalized_query = '', documents_json = '[]', filters_json = '[]',
                       validator_json = '{}', final_reason = '', error = NULL, trace_json = '{}'"""
            )
            self._purge_expired(db)

    def _purge_expired(self, db: sqlite3.Connection) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
        db.execute("DELETE FROM rag_diagnostics WHERE created_at < ?", (cutoff,))

    def record(
        self,
        request_id: str,
        query: str,
        diagnostics: dict,
        duration_ms: int,
        status: str,
        validator: dict | None = None,
        final_reason: str = "",
        context_tokens: int = 0,
        estimated_cost: float | None = None,
        error: str | None = None,
        depth_level: str = "explicativo",
        topic_category: str = "catequese_geral",
        strategy_version: str = "legacy",
        component_count: int = 0,
        retrieved_chunk_count: int = 0,
        input_tokens_estimated: int = 0,
        output_tokens_estimated: int = 0,
        cache_hit: bool = False,
        coverage_failures: int = 0,
        citation_errors: int = 0,
        regenerated: bool = False,
    ) -> None:
        query_data = diagnostics.get("query", {})
        reranking = diagnostics.get("reranking", [])
        selected = diagnostics.get("selected_chunks", [])
        best_score = max((float(item.get("score", 0)) for item in reranking), default=None)
        trace = {
            "candidate_counts": numeric_metrics(diagnostics.get("candidate_counts")),
            "threshold_policy": numeric_metrics(diagnostics.get("threshold_policy")),
            "embedding": numeric_metrics(diagnostics.get("embedding")),
            "gospel_policy": {
                "query_classification": str(diagnostics.get("query_classification") or "ORDINARY_QUERY")[:40],
                "identified_gospel_passages": [
                    str(value)[:40] for value in diagnostics.get("identified_gospel_passages", [])[:24]
                ],
                "catena_search_executed": bool(diagnostics.get("catena_search_executed")),
                "catena_policy_satisfied_by_cache": bool(diagnostics.get("catena_policy_satisfied_by_cache")),
                "catena_chunks_retrieved": int(diagnostics.get("catena_chunks_retrieved", 0)),
                "patristic_authors_retrieved": [
                    str(value)[:100] for value in diagnostics.get("patristic_authors_retrieved", [])[:60]
                ],
                "parallel_passages_searched": [
                    str(value)[:40] for value in diagnostics.get("parallel_passages_searched", [])[:24]
                ],
                "adjacent_chunks_loaded": int(diagnostics.get("adjacent_chunks_loaded", 0)),
                "complementary_repository_search_executed": bool(
                    diagnostics.get("complementary_repository_search_executed")
                ),
                "sources_used": [
                    str(value)[:240] for value in diagnostics.get("sources_used", [])[:80]
                ],
                "coverage_score": float(diagnostics.get("coverage_score", 0) or 0),
                "citation_validation_status": str(diagnostics.get("citation_validation_status") or "")[:60],
                "completeness_validation_status": str(
                    diagnostics.get("completeness_validation_status") or ""
                )[:60],
            },
        }
        validator_decision = str((validator or {}).get("decision", ""))[:80]
        with self._connect() as db:
            self._purge_expired(db)
            db.execute(
                """
                INSERT OR REPLACE INTO rag_diagnostics(
                    request_id,created_at,query_text,normalized_query,query_type,duration_ms,status,
                    candidate_count,final_count,best_score,documents_json,filters_json,validator_json,
                    final_reason,context_tokens,estimated_cost,depth_level,topic_category,strategy_version,component_count,
                    retrieved_chunk_count,input_tokens_estimated,output_tokens_estimated,cache_hit,
                    coverage_failures,citation_errors,regenerated,error,trace_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    request_id,
                    datetime.now(timezone.utc).isoformat(),
                    "",
                    "",
                    str(
                        diagnostics.get("query_classification")
                        or query_data.get("query_classification")
                        or query_data.get("query_type", "")
                    ),
                    max(int(duration_ms), 0),
                    status,
                    int(diagnostics.get("candidates_fused", 0)),
                    int(diagnostics.get("final_count", len(selected))),
                    best_score,
                    "[]",
                    "[]",
                    json.dumps({"decision": validator_decision}, ensure_ascii=False),
                    "",
                    max(int(context_tokens), 0),
                    estimated_cost,
                    str(depth_level)[:40],
                    str(topic_category)[:80],
                    str(strategy_version)[:80],
                    max(int(component_count), 0),
                    max(int(retrieved_chunk_count), 0),
                    max(int(input_tokens_estimated), 0),
                    max(int(output_tokens_estimated), 0),
                    1 if cache_hit else 0,
                    max(int(coverage_failures), 0),
                    max(int(citation_errors), 0),
                    1 if regenerated else 0,
                    ("recorded" if error else None),
                    json.dumps(trace, ensure_ascii=False),
                ),
            )

    def recent(self, limit: int = 100) -> list[dict]:
        limit = min(max(int(limit), 1), 500)
        with self._connect() as db:
            self._purge_expired(db)
            rows = db.execute(
                "SELECT * FROM rag_diagnostics ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            for field in ("documents_json", "filters_json", "validator_json", "trace_json"):
                value = item.pop(field)
                item[field.removesuffix("_json")] = json.loads(value or "null")
            results.append(item)
        return results

    def aggregate(self, days: int = 30) -> dict:
        days = min(max(int(days), 1), 365)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT COUNT(*) AS query_count,
                       AVG(retrieved_chunk_count) AS average_chunks,
                       AVG(input_tokens_estimated) AS average_input_tokens,
                       AVG(output_tokens_estimated) AS average_output_tokens,
                       AVG(duration_ms) AS average_duration_ms,
                       AVG(estimated_cost) AS average_estimated_cost,
                       SUM(cache_hit) AS cache_hits,
                       SUM(CASE WHEN depth_level = 'aprofundado' THEN 1 ELSE 0 END) AS composite_queries,
                       SUM(CASE WHEN depth_level != 'aprofundado' THEN 1 ELSE 0 END) AS simple_queries,
                       SUM(coverage_failures) AS coverage_failures,
                       SUM(citation_errors) AS citation_errors,
                       SUM(regenerated) AS regenerated_answers,
                       SUM(CASE WHEN status = 'technical_failure' THEN 1 ELSE 0 END) AS generation_errors
                FROM rag_diagnostics WHERE created_at >= ?
                """,
                (cutoff,),
            ).fetchone()
            categories = db.execute(
                """
                SELECT topic_category, COUNT(*) AS total
                FROM rag_diagnostics WHERE created_at >= ?
                GROUP BY topic_category ORDER BY total DESC, topic_category LIMIT 10
                """,
                (cutoff,),
            ).fetchall()
            strategies = db.execute(
                """
                SELECT strategy_version, COUNT(*) AS query_count,
                       AVG(retrieved_chunk_count) AS average_chunks,
                       AVG(context_tokens) AS average_context_tokens,
                       AVG(NULLIF(input_tokens_estimated, 0)) AS average_input_tokens,
                       AVG(NULLIF(output_tokens_estimated, 0)) AS average_output_tokens,
                       SUM(CASE WHEN input_tokens_estimated > 0 OR output_tokens_estimated > 0 THEN 1 ELSE 0 END)
                           AS measured_model_token_queries,
                       AVG(estimated_cost) AS average_estimated_cost,
                       AVG(duration_ms) AS average_duration_ms
                FROM rag_diagnostics WHERE created_at >= ?
                GROUP BY strategy_version ORDER BY strategy_version
                """,
                (cutoff,),
            ).fetchall()
        count = int(row["query_count"] or 0)
        return {
            "period_days": days,
            "query_count": count,
            "average_documents_retrieved": round(float(row["average_chunks"] or 0), 2),
            "average_input_tokens": round(float(row["average_input_tokens"] or 0), 2),
            "average_output_tokens": round(float(row["average_output_tokens"] or 0), 2),
            "average_duration_ms": round(float(row["average_duration_ms"] or 0), 2),
            "average_estimated_cost": round(float(row["average_estimated_cost"] or 0), 8),
            "cache_reuse_rate": round(int(row["cache_hits"] or 0) / count, 4) if count else 0,
            "simple_queries": int(row["simple_queries"] or 0),
            "composite_queries": int(row["composite_queries"] or 0),
            "coverage_failures": int(row["coverage_failures"] or 0),
            "citation_errors": int(row["citation_errors"] or 0),
            "regenerated_answers": int(row["regenerated_answers"] or 0),
            "generation_errors": int(row["generation_errors"] or 0),
            "top_topic_categories": [
                {"category": item["topic_category"], "count": int(item["total"])}
                for item in categories
            ],
            "strategy_comparison": [
                {
                    "strategy_version": item["strategy_version"],
                    "query_count": int(item["query_count"]),
                    "average_documents_retrieved": round(float(item["average_chunks"] or 0), 2),
                    "average_context_tokens": round(float(item["average_context_tokens"] or 0), 2),
                    "average_input_tokens": round(float(item["average_input_tokens"] or 0), 2),
                    "average_output_tokens": round(float(item["average_output_tokens"] or 0), 2),
                    "measured_model_token_queries": int(item["measured_model_token_queries"] or 0),
                    "average_estimated_cost": round(float(item["average_estimated_cost"] or 0), 8),
                    "average_duration_ms": round(float(item["average_duration_ms"] or 0), 2),
                }
                for item in strategies
            ],
        }
