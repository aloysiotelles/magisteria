from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from services.response_planning import ResponsePlan


class UserSearchHistory:
    """Owner-scoped consultation history with configurable retention."""

    def __init__(
        self,
        database_file: Path,
        *,
        retention_days: int = 365,
        store_original_query: bool = True,
    ):
        self.database_file = database_file
        self.retention_days = min(max(int(retention_days), 1), 3650)
        self.store_original_query = bool(store_original_query)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_file, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _purge(self, db: sqlite3.Connection) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
        db.execute("DELETE FROM user_search_history WHERE last_searched_at < ?", (cutoff,))

    def record(self, user_id: int, query: str, plan: ResponsePlan) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        original_query = query.strip()[:2000] if self.store_original_query else None
        with self._connect() as db:
            self._purge(db)
            db.execute(
                """
                INSERT INTO user_search_history(
                    user_id,original_query,normalized_topic,display_title,topic_category,
                    depth_level,language,created_at,last_searched_at,search_count,deleted_at
                ) VALUES(?,?,?,?,?,?,?,?,?,1,NULL)
                ON CONFLICT(user_id,normalized_topic) DO UPDATE SET
                    original_query=COALESCE(excluded.original_query,user_search_history.original_query),
                    display_title=excluded.display_title,
                    topic_category=excluded.topic_category,
                    depth_level=excluded.depth_level,
                    language=excluded.language,
                    last_searched_at=excluded.last_searched_at,
                    search_count=user_search_history.search_count + 1,
                    deleted_at=NULL
                """,
                (
                    user_id, original_query, plan.topic_key, plan.display_title[:160], plan.category,
                    plan.depth, plan.language, now, now,
                ),
            )
            row = db.execute(
                "SELECT * FROM user_search_history WHERE user_id = ? AND normalized_topic = ?",
                (user_id, plan.topic_key),
            ).fetchone()
        return self._public_row(row)

    def list(
        self,
        user_id: int,
        *,
        search: str = "",
        sort: str = "date",
        limit: int = 100,
    ) -> list[dict]:
        order = "search_count DESC, last_searched_at DESC" if sort == "frequency" else "last_searched_at DESC"
        limit = min(max(int(limit), 1), 200)
        pattern = f"%{search.strip()[:120]}%"
        with self._connect() as db:
            self._purge(db)
            rows = db.execute(
                f"""
                SELECT * FROM user_search_history
                WHERE user_id = ? AND deleted_at IS NULL
                  AND (? = '%%' OR display_title LIKE ? COLLATE NOCASE OR normalized_topic LIKE ? COLLATE NOCASE)
                ORDER BY {order} LIMIT ?
                """,
                (user_id, pattern, pattern, pattern, limit),
            ).fetchall()
        return [self._public_row(row) for row in rows]

    def get_for_requery(self, user_id: int, history_id: int) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM user_search_history WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                (history_id, user_id),
            ).fetchone()
        if not row:
            return None
        item = self._public_row(row)
        item["query"] = row["original_query"] or self.reconstruct_query(
            str(row["display_title"]), str(row["depth_level"])
        )
        return item

    def delete(self, user_id: int, history_id: int) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE user_search_history SET deleted_at = ? WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), history_id, user_id),
            )
            return bool(cursor.rowcount)

    def clear(self, user_id: int) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE user_search_history SET deleted_at = ? WHERE user_id = ? AND deleted_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), user_id),
            )
            return int(cursor.rowcount or 0)

    @staticmethod
    def reconstruct_query(display_title: str, depth: str) -> str:
        if depth == "resumido":
            return f"Faça um resumo de {display_title}, incluindo todos os seus componentes principais."
        if depth == "aprofundado":
            return f"Explique {display_title} e detalhe cada um de seus componentes."
        return f"Explique {display_title} de modo claro e fundamentado."

    @staticmethod
    def _public_row(row: sqlite3.Row) -> dict:
        return {
            "id": int(row["id"]),
            "normalized_topic": row["normalized_topic"],
            "display_title": row["display_title"],
            "topic_category": row["topic_category"],
            "depth_level": row["depth_level"],
            "language": row["language"],
            "created_at": row["created_at"],
            "last_searched_at": row["last_searched_at"],
            "search_count": int(row["search_count"]),
            "repeated": int(row["search_count"]) > 1,
        }

