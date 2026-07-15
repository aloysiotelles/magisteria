from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import re
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
                CREATE TABLE IF NOT EXISTS payment_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL DEFAULT 'mercado_pago',
                    provider_preference_id TEXT UNIQUE,
                    approved_payment_id TEXT UNIQUE,
                    expected_amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'created',
                    status_detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payment_transactions (
                    provider_payment_id TEXT PRIMARY KEY,
                    payment_order_id INTEGER NOT NULL REFERENCES payment_orders(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    status_detail TEXT,
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_payment_orders_user_id
                    ON payment_orders(user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS payment_webhook_events (
                    provider TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY(provider, event_id)
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(payment_orders)").fetchall()}
            if "provider" not in columns:
                db.execute(
                    "ALTER TABLE payment_orders ADD COLUMN provider TEXT NOT NULL DEFAULT 'mercado_pago'"
                )
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
                    SET full_name = 'Administrador', role = 'admin', account_type = 'completa',
                        subscription_status = 'ativa'
                    WHERE id = ?
                    """,
                    (admin["id"],),
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
        valid, message = self.validate_password_strength(password)
        if not valid:
            return False, message
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

    def get_user(self, user_id: int) -> sqlite3.Row | None:
        with self._connect() as db:
            return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def create_payment_order(
        self,
        user_id: int,
        expected_amount: str,
        currency: str,
        provider: str = "mercado_pago",
    ) -> sqlite3.Row:
        now = self._now()
        reference = f"mag-{secrets.token_urlsafe(24)}"
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO payment_orders(
                    reference, user_id, provider, expected_amount, currency, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'created', ?, ?)
                """,
                (reference, user_id, provider.strip().lower(), expected_amount, currency.upper(), now, now),
            )
            return db.execute("SELECT * FROM payment_orders WHERE reference = ?", (reference,)).fetchone()

    def attach_payment_preference(self, reference: str, preference_id: str) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE payment_orders
                SET provider_preference_id = ?, status = 'pending', updated_at = ?
                WHERE reference = ?
                """,
                (preference_id, self._now(), reference),
            )

    def apply_provider_subscription(
        self,
        reference: str,
        subscription_id: str,
        status: str,
        amount: str,
        currency: str,
        *,
        started_at: str | None = None,
        renews_at: str | None = None,
    ) -> sqlite3.Row:
        """Concilia a assinatura consultada na API e sincroniza o acesso do usuario."""
        status = status.strip().lower()
        order_status = "approved" if status == "authorized" else (status or "unknown")
        now = self._now()
        with self._connect() as db:
            order = db.execute(
                "SELECT * FROM payment_orders WHERE reference = ?", (reference,)
            ).fetchone()
            if not order:
                raise ValueError("Referencia de assinatura desconhecida.")
            if order["provider_preference_id"] not in {None, subscription_id}:
                raise ValueError("Pedido ja vinculado a outra assinatura.")

            db.execute(
                """
                UPDATE payment_orders
                SET provider_preference_id = ?, status = ?, status_detail = ?, updated_at = ?
                WHERE id = ?
                """,
                (subscription_id, order_status, status[:500], now, order["id"]),
            )

            if status == "authorized":
                db.execute(
                    """
                    UPDATE users
                    SET account_type = 'completa', subscription_status = 'ativa',
                        payment_provider_subscription_id = ?,
                        subscription_started_at = COALESCE(subscription_started_at, ?),
                        subscription_renews_at = ?
                    WHERE id = ?
                    """,
                    (subscription_id, started_at or now, renews_at, order["user_id"]),
                )
            elif status in {"paused", "cancelled", "cancelled_by_collector"}:
                db.execute(
                    """
                    UPDATE users
                    SET account_type = 'gratuita', subscription_status = ?,
                        subscription_renews_at = NULL
                    WHERE id = ? AND payment_provider_subscription_id = ?
                    """,
                    ("pausada" if status == "paused" else "cancelada", order["user_id"], subscription_id),
                )

            return db.execute("SELECT * FROM payment_orders WHERE id = ?", (order["id"],)).fetchone()

    def apply_subscription_invoice(
        self,
        reference: str,
        subscription_id: str,
        invoice_id: str,
        payment_id: str,
        status: str,
        status_detail: str,
        amount: str,
        currency: str,
        *,
        renews_at: str | None = None,
    ) -> sqlite3.Row:
        """Registra uma mensalidade de forma idempotente e aplica seu efeito no acesso."""
        status = status.strip().lower()
        now = self._now()
        transaction_id = payment_id or f"invoice-{invoice_id}"
        with self._connect() as db:
            order = db.execute(
                "SELECT * FROM payment_orders WHERE reference = ?", (reference,)
            ).fetchone()
            if not order:
                raise ValueError("Referencia de assinatura desconhecida.")
            if order["provider_preference_id"] != subscription_id:
                raise ValueError("Fatura nao pertence a assinatura vinculada ao pedido.")
            existing = db.execute(
                "SELECT payment_order_id FROM payment_transactions WHERE provider_payment_id = ?",
                (transaction_id,),
            ).fetchone()
            if existing and existing["payment_order_id"] != order["id"]:
                raise ValueError("Pagamento ja vinculado a outra assinatura.")

            db.execute(
                """
                INSERT INTO payment_transactions(
                    provider_payment_id, payment_order_id, status, status_detail,
                    amount, currency, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_payment_id) DO UPDATE SET
                    status = excluded.status,
                    status_detail = excluded.status_detail,
                    amount = excluded.amount,
                    currency = excluded.currency,
                    processed_at = excluded.processed_at
                """,
                (transaction_id, order["id"], status, status_detail[:500], amount, currency, now),
            )

            if status == "approved":
                db.execute(
                    """
                    UPDATE payment_orders
                    SET status = 'approved', status_detail = ?, approved_payment_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status_detail[:500], payment_id or None, now, order["id"]),
                )
                db.execute(
                    """
                    UPDATE users
                    SET account_type = 'completa', subscription_status = 'ativa',
                        payment_provider_subscription_id = ?,
                        subscription_started_at = COALESCE(subscription_started_at, ?),
                        subscription_renews_at = ?
                    WHERE id = ?
                    """,
                    (subscription_id, now, renews_at, order["user_id"]),
                )
            elif status in {"refunded", "charged_back", "cancelled"}:
                db.execute(
                    "UPDATE payment_orders SET status = ?, status_detail = ?, updated_at = ? WHERE id = ?",
                    (status, status_detail[:500], now, order["id"]),
                )
                db.execute(
                    """
                    UPDATE users
                    SET account_type = 'gratuita', subscription_status = 'inativa',
                        subscription_renews_at = NULL
                    WHERE id = ? AND payment_provider_subscription_id = ?
                    """,
                    (order["user_id"], subscription_id),
                )
            elif order["status"] != "approved":
                db.execute(
                    "UPDATE payment_orders SET status = ?, status_detail = ?, updated_at = ? WHERE id = ?",
                    (status or "unknown", status_detail[:500], now, order["id"]),
                )

            return db.execute("SELECT * FROM payment_orders WHERE id = ?", (order["id"],)).fetchone()

    def mark_payment_order_error(self, reference: str, detail: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE payment_orders SET status = 'error', status_detail = ?, updated_at = ? WHERE reference = ?",
                (detail[:500], self._now(), reference),
            )

    def get_payment_order(self, reference: str) -> sqlite3.Row | None:
        with self._connect() as db:
            return db.execute("SELECT * FROM payment_orders WHERE reference = ?", (reference,)).fetchone()

    def get_latest_payment_order(self, user_id: int, provider: str | None = None) -> sqlite3.Row | None:
        with self._connect() as db:
            if provider:
                return db.execute(
                    """SELECT * FROM payment_orders
                       WHERE user_id = ? AND provider = ?
                       ORDER BY created_at DESC, id DESC LIMIT 1""",
                    (user_id, provider.strip().lower()),
                ).fetchone()
            return db.execute(
                "SELECT * FROM payment_orders WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (user_id,),
            ).fetchone()

    def webhook_event_processed(self, provider: str, event_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM payment_webhook_events WHERE provider = ? AND event_id = ?",
                (provider.strip().lower(), event_id.strip()),
            ).fetchone()
        return bool(row)

    def record_webhook_event(self, provider: str, event_id: str, event_type: str) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO payment_webhook_events(provider, event_id, event_type, processed_at)
                   VALUES (?, ?, ?, ?)""",
                (provider.strip().lower(), event_id.strip(), event_type.strip(), self._now()),
            )

    def apply_provider_payment(
        self,
        reference: str,
        payment_id: str,
        status: str,
        status_detail: str,
        amount: str,
        currency: str,
    ) -> sqlite3.Row:
        """Registra um pagamento de forma idempotente e recalcula o acesso relacionado."""
        status = status.strip().lower()
        status_detail = status_detail.strip().lower()
        grants_access = status == "approved" or (status == "charged_back" and status_detail == "reimbursed")
        now = self._now()
        with self._connect() as db:
            order = db.execute(
                "SELECT * FROM payment_orders WHERE reference = ?",
                (reference,),
            ).fetchone()
            if not order:
                raise ValueError("Referencia de pagamento desconhecida.")
            existing = db.execute(
                "SELECT payment_order_id FROM payment_transactions WHERE provider_payment_id = ?",
                (payment_id,),
            ).fetchone()
            if existing and existing["payment_order_id"] != order["id"]:
                raise ValueError("Pagamento ja vinculado a outra referencia.")

            db.execute(
                """
                INSERT INTO payment_transactions(
                    provider_payment_id, payment_order_id, status, status_detail,
                    amount, currency, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_payment_id) DO UPDATE SET
                    status = excluded.status,
                    status_detail = excluded.status_detail,
                    amount = excluded.amount,
                    currency = excluded.currency,
                    processed_at = excluded.processed_at
                """,
                (payment_id, order["id"], status, status_detail[:500], amount, currency, now),
            )

            if grants_access:
                db.execute(
                    """
                    UPDATE payment_orders
                    SET status = 'approved', status_detail = ?, approved_payment_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status_detail[:500], payment_id, now, order["id"]),
                )
                db.execute(
                    """
                    UPDATE users
                    SET account_type = 'completa', subscription_status = 'ativa',
                        payment_provider_subscription_id = ?,
                        subscription_started_at = COALESCE(subscription_started_at, ?),
                        subscription_renews_at = NULL
                    WHERE id = ?
                    """,
                    (payment_id, now, order["user_id"]),
                )
            elif status in {"refunded", "charged_back", "cancelled"} and order["approved_payment_id"] == payment_id:
                db.execute(
                    "UPDATE payment_orders SET status = ?, status_detail = ?, updated_at = ? WHERE id = ?",
                    (status, status_detail[:500], now, order["id"]),
                )
                fallback = db.execute(
                    """
                    SELECT approved_payment_id FROM payment_orders
                    WHERE user_id = ? AND id != ? AND status = 'approved'
                    ORDER BY updated_at DESC, id DESC LIMIT 1
                    """,
                    (order["user_id"], order["id"]),
                ).fetchone()
                if fallback:
                    db.execute(
                        """
                        UPDATE users SET account_type = 'completa', subscription_status = 'ativa',
                            payment_provider_subscription_id = ?
                        WHERE id = ? AND payment_provider_subscription_id = ?
                        """,
                        (fallback["approved_payment_id"], order["user_id"], payment_id),
                    )
                else:
                    db.execute(
                        """
                        UPDATE users
                        SET account_type = 'gratuita', subscription_status = 'inativa',
                            payment_provider_subscription_id = NULL, subscription_renews_at = NULL
                        WHERE id = ? AND payment_provider_subscription_id = ?
                        """,
                        (order["user_id"], payment_id),
                    )
            elif order["status"] != "approved":
                db.execute(
                    "UPDATE payment_orders SET status = ?, status_detail = ?, updated_at = ? WHERE id = ?",
                    (status or "unknown", status_detail[:500], now, order["id"]),
                )

            return db.execute("SELECT * FROM payment_orders WHERE id = ?", (order["id"],)).fetchone()

    def update_subscription(
        self,
        user_id: int,
        *,
        account_type: str | None = None,
        subscription_status: str | None = None,
        payment_provider_subscription_id: str | None = None,
        started_at: str | None = None,
        renews_at: str | None = None,
    ) -> None:
        assignments: list[str] = []
        values: list[str] = []
        if account_type is not None:
            assignments.append("account_type = ?")
            values.append(account_type)
        if subscription_status is not None:
            assignments.append("subscription_status = ?")
            values.append(subscription_status)
        if payment_provider_subscription_id is not None:
            assignments.append("payment_provider_subscription_id = ?")
            values.append(payment_provider_subscription_id)
        if started_at is not None:
            assignments.append("subscription_started_at = ?")
            values.append(started_at)
        if renews_at is not None:
            assignments.append("subscription_renews_at = ?")
            values.append(renews_at)
        if not assignments:
            return
        values.append(str(user_id))
        with self._connect() as db:
            db.execute(f"UPDATE users SET {', '.join(assignments)} WHERE id = ?", values)

    def activate_full_access(self, user_id: int, provider_subscription_id: str | None = None) -> None:
        now = self._now()
        self.update_subscription(
            user_id,
            account_type="completa",
            subscription_status="ativa",
            payment_provider_subscription_id=provider_subscription_id,
            started_at=now,
            renews_at=None,
        )

    def apply_coupon_access(self, user_id: int, coupon_code: str) -> None:
        now = self._now()
        self.update_subscription(
            user_id,
            account_type="completa",
            subscription_status="ativa",
            payment_provider_subscription_id=f"cupom:{coupon_code}",
            started_at=now,
            renews_at=None,
        )

    def set_free_access_review(self, allow_free_access: bool) -> None:
        account_type = "gratuita" if allow_free_access else "completa"
        status = "inativa" if allow_free_access else "ativa"
        with self._connect() as db:
            db.execute(
                "UPDATE users SET account_type = ?, subscription_status = ? WHERE role != 'admin'",
                (account_type, status),
            )

    def can_use_query(self, user: sqlite3.Row) -> tuple[bool, str]:
        if user["role"] == "admin" or user["account_type"] == "completa" or user["subscription_status"] == "ativa":
            return True, ""
        today = datetime.now(timezone.utc).date().isoformat()
        if user["last_query_date"] != today:
            return True, ""
        if int(user["daily_query_count"] or 0) >= 3:
            return False, "A versão gratuita permite apenas 3 consultas por dia."
        return True, ""

    def can_generate_presentation(self, user: sqlite3.Row, kind: str) -> tuple[bool, str]:
        if user["role"] == "admin" or user["account_type"] == "completa" or user["subscription_status"] == "ativa":
            return True, ""
        field = "script_generation_count" if kind == "script" else "presentation_generation_count"
        limit_label = "roteiro" if kind == "script" else "slide"
        if int(user[field] or 0) >= 1:
            return False, f"A versão gratuita permite apenas 1 {limit_label}."
        return True, ""

    def authenticate(self, login: str, password: str) -> sqlite3.Row | None:
        user = self.find_user_by_login(login)
        if user and self.verify_password(password, user["password_hash"]):
            return user
        return None

    def change_password(self, user_id: int, current_password: str, new_password: str) -> tuple[bool, str]:
        with self._connect() as db:
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                return False, "Usuario nao encontrado."
            if not self.verify_password(current_password, user["password_hash"]):
                return False, "A senha atual nao confere."

            valid, message = self.validate_password_strength(new_password)
            if not valid:
                return False, message

            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (self.hash_password(new_password), user_id))
        return True, "Senha alterada com sucesso."

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
    def validate_password_strength(password: str) -> tuple[bool, str]:
        if len(password) < 8:
            return False, "A senha deve ter pelo menos 8 caracteres."
        if not re.search(r"\d", password):
            return False, "A senha deve conter pelo menos um numero."
        if not re.search(r"[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ]", password):
            return False, "A senha deve conter pelo menos uma letra maiuscula."
        if not re.search(r"[a-záéíóúàâêôãõç]", password):
            return False, "A senha deve conter pelo menos uma letra minuscula."
        return True, ""

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
