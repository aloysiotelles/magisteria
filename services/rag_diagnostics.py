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
                    error TEXT,
                    trace_json TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_diagnostics_created_at ON rag_diagnostics(created_at)"
            )
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
    ) -> None:
        query_data = diagnostics.get("query", {})
        reranking = diagnostics.get("reranking", [])
        selected = diagnostics.get("selected_chunks", [])
        best_score = max((float(item.get("score", 0)) for item in reranking), default=None)
        trace = {
            "candidate_counts": numeric_metrics(diagnostics.get("candidate_counts")),
            "threshold_policy": numeric_metrics(diagnostics.get("threshold_policy")),
            "embedding": numeric_metrics(diagnostics.get("embedding")),
        }
        validator_decision = str((validator or {}).get("decision", ""))[:80]
        with self._connect() as db:
            self._purge_expired(db)
            db.execute(
                """
                INSERT OR REPLACE INTO rag_diagnostics(
                    request_id,created_at,query_text,normalized_query,query_type,duration_ms,status,
                    candidate_count,final_count,best_score,documents_json,filters_json,validator_json,
                    final_reason,context_tokens,estimated_cost,error,trace_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    request_id,
                    datetime.now(timezone.utc).isoformat(),
                    "",
                    "",
                    str(query_data.get("query_type", "")),
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
