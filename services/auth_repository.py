from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3

SESSION_DAYS = 30
PASSWORD_ITERATIONS = 260_000


class AuthRepository:
    def __init__(self, database_file: Path):
        self.database_file = database_file
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_file, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    account_type TEXT NOT NULL DEFAULT 'gratuita',
                    subscription_status TEXT NOT NULL DEFAULT 'inativa',
                    subscription_started_at TEXT,
                    subscription_renews_at TEXT,
                    payment_provider_subscription_id TEXT,
                    daily_query_count INTEGER NOT NULL DEFAULT 0,
                    last_query_date TEXT,
                    script_generation_count INTEGER NOT NULL DEFAULT 0,
                    presentation_generation_count INTEGER NOT NULL DEFAULT 0,
                    total_access_count INTEGER NOT NULL DEFAULT 0,
                    last_access_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS indexed_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    uploaded_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
        self.ensure_admin()

    def ensure_admin(self) -> None:
        admin = self.find_user_by_login("Admin")
        password_hash = self.hash_password("3510")
        now = self._now()
        with self._connect() as db:
            if admin:
                db.execute(
                    """
                    UPDATE users
                    SET full_name = 'Administrador', password_hash = ?, role = 'admin', account_type = 'completa',
                        subscription_status = 'ativa'
                    WHERE id = ?
                    """,
                    (password_hash, admin["id"]),
                )
                return
            db.execute(
                """
                INSERT INTO users (
                    full_name, email, password_hash, role, account_type, subscription_status,
                    subscription_started_at, subscription_renews_at, created_at
                ) VALUES (?, ?, ?, 'admin', 'completa', 'ativa', ?, ?, ?)
                """,
                ("Administrador", "Admin", password_hash, now, now, now),
            )

    def create_user(self, full_name: str, email: str, password: str) -> tuple[bool, str]:
        full_name = full_name.strip()
        email = email.strip()
        if len(full_name) < 3:
            return False, "Informe o nome completo."
        if "@" not in email or "." not in email:
            return False, "Informe um email valido."
        if len(password) < 6:
            return False, "A senha deve ter pelo menos 6 caracteres."
        try:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO users (full_name, email, password_hash, account_type, subscription_status, created_at)
                    VALUES (?, ?, ?, 'gratuita', 'inativa', ?)
                    """,
                    (full_name, email, self.hash_password(password), self._now()),
                )
        except sqlite3.IntegrityError:
            return False, "Este email ja esta cadastrado."
        return True, "Cadastro criado com sucesso."

    def authenticate(self, login: str, password: str) -> sqlite3.Row | None:
        user = self.find_user_by_login(login)
        if user and self.verify_password(password, user["password_hash"]):
            return user
        return None

    def find_user_by_login(self, login: str) -> sqlite3.Row | None:
        login = login.strip()
        with self._connect() as db:
            return db.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (login,)).fetchone()

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=SESSION_DAYS)
        with self._connect() as db:
            db.execute("INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)", (token, user_id, now.isoformat(), expires.isoformat()))
            db.execute("UPDATE users SET total_access_count = total_access_count + 1, last_access_at = ? WHERE id = ?", (now.isoformat(), user_id))
        return token

    def get_user_by_session(self, token: str) -> sqlite3.Row | None:
        if not token:
            return None
        now = self._now()
        with self._connect() as db:
            row = db.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ? AND sessions.expires_at > ?",
                (token, now),
            ).fetchone()
            if not row:
                db.execute("DELETE FROM sessions WHERE token = ? OR expires_at <= ?", (token, now))
            return row

    def delete_session(self, token: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def increment_usage(self, user_id: int, field: str) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as db:
            if field == "query":
                user = db.execute("SELECT last_query_date FROM users WHERE id = ?", (user_id,)).fetchone()
                if user and user["last_query_date"] == today:
                    db.execute("UPDATE users SET daily_query_count = daily_query_count + 1, last_query_date = ? WHERE id = ?", (today, user_id))
                else:
                    db.execute("UPDATE users SET daily_query_count = 1, last_query_date = ? WHERE id = ?", (today, user_id))
            elif field == "script":
                db.execute("UPDATE users SET script_generation_count = script_generation_count + 1 WHERE id = ?", (user_id,))
            elif field == "presentation":
                db.execute("UPDATE users SET presentation_generation_count = presentation_generation_count + 1 WHERE id = ?", (user_id,))

    def list_users(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT id, full_name, email, role, account_type, subscription_status,
                       total_access_count, last_access_at, daily_query_count, last_query_date,
                       script_generation_count, presentation_generation_count, created_at
                FROM users ORDER BY created_at DESC
            """).fetchall()
        return [dict(row) for row in rows]

    def register_document(self, source: str, filename: str, file_type: str) -> None:
        now = self._now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO indexed_documents(source, filename, file_type, is_active, uploaded_at, updated_at)
                VALUES(?, ?, ?, 1, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    filename = excluded.filename,
                    file_type = excluded.file_type,
                    is_active = 1,
                    updated_at = excluded.updated_at
                """,
                (source, filename, file_type, now, now),
            )

    def set_document_active(self, source: str, active: bool) -> None:
        with self._connect() as db:
            db.execute("UPDATE indexed_documents SET is_active = ?, updated_at = ? WHERE source = ?", (1 if active else 0, self._now(), source))

    def list_documents(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT source, filename, file_type, is_active, uploaded_at, updated_at FROM indexed_documents ORDER BY filename COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]

    def inactive_sources(self) -> tuple[str, ...]:
        with self._connect() as db:
            rows = db.execute("SELECT source FROM indexed_documents WHERE is_active = 0").fetchall()
        return tuple(row["source"] for row in rows)

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
        return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        try:
            algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
