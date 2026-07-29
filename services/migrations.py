from __future__ import annotations

from pathlib import Path
import sqlite3


def apply_migrations(connection: sqlite3.Connection, migrations_dir: Path) -> list[str]:
    """Apply ordered SQLite migrations exactly once.

    Baseline tables are still created by the existing repositories so older
    installations remain bootable. New, independently reversible structures
    live in versioned ``*.up.sql`` files.
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        str(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    executed: list[str] = []
    for path in sorted(migrations_dir.glob("*.up.sql")):
        version = path.name.removesuffix(".up.sql")
        if version in applied:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO schema_migrations(version) VALUES(?)", (version,))
        executed.append(version)
    return executed
