from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3

SESSION_DAYS = 30
MOBILE_ACCESS_MINUTES = 15
MOBILE_REFRESH_DAYS = 30
PASSWORD_ITERATIONS = 260_000
COUPON_DURATIONS = {
    "dia": timedelta(days=1),
    "semana": timedelta(days=7),
}
COUPON_VALIDITY_PERIODS = {*COUPON_DURATIONS, "mes"}


class AuthRepository:
    def __init__(self, database_file: Path, admin_bootstrap_password: str = ""):
        self.database_file = database_file
        self.admin_bootstrap_password = admin_bootstrap_password.strip()
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
                CREATE TABLE IF NOT EXISTS mobile_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_type TEXT NOT NULL CHECK(token_type IN ('access', 'refresh')),
                    family_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    replaced_by_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_mobile_tokens_user_family
                    ON mobile_tokens(user_id, family_id, token_type, expires_at);
                CREATE TABLE IF NOT EXISTS account_deletion_audit (
                    event_id TEXT PRIMARY KEY,
                    requested_at TEXT NOT NULL,
                    subscription_source TEXT NOT NULL,
                    subscription_status TEXT NOT NULL
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
                CREATE TABLE IF NOT EXISTS coupons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    validity_period TEXT NOT NULL,
                    valid_until TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS coupon_redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    coupon_id INTEGER NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    redeemed_at TEXT NOT NULL,
                    revoked_at TEXT,
                    revoked_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    UNIQUE(coupon_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_user
                    ON coupon_redemptions(user_id, revoked_at);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(payment_orders)").fetchall()}
            if "provider" not in columns:
                db.execute(
                    "ALTER TABLE payment_orders ADD COLUMN provider TEXT NOT NULL DEFAULT 'mercado_pago'"
                )
        self.ensure_admin(self.admin_bootstrap_password)

    def ensure_admin(self, bootstrap_password: str = "") -> None:
        """Create the administrator only from an explicit bootstrap secret."""
        admin = self.find_user_by_login("Admin")
        if admin:
            if admin["role"] != "admin":
                raise RuntimeError("O login reservado Admin ja pertence a uma conta sem privilegio.")
            return
        if not bootstrap_password:
            return
        valid, message = self.validate_password_strength(bootstrap_password)
        if not valid:
            raise RuntimeError(f"ADMIN_BOOTSTRAP_PASSWORD invalida: {message}")
        now = self._now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO users (
                    full_name, email, password_hash, role, account_type, subscription_status,
                    subscription_started_at, subscription_renews_at, created_at
                ) VALUES (?, ?, ?, 'admin', 'completa', 'ativa', ?, ?, ?)
                """,
                ("Administrador", "Admin", self.hash_password(bootstrap_password), now, now, now),
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

    def create_coupon(self, code: str, validity_period: str, created_by_user_id: int) -> dict:
        normalized_code = self._normalize_coupon_code(code)
        validity_period = validity_period.strip().lower()
        if validity_period not in COUPON_VALIDITY_PERIODS:
            raise ValueError("Escolha a validade de um dia, uma semana ou um mês.")
        now = datetime.now(timezone.utc)
        valid_until = self._coupon_valid_until(now, validity_period)
        try:
            with self._connect() as db:
                cursor = db.execute(
                    """
                    INSERT INTO coupons(code, validity_period, valid_until, created_by_user_id, created_at)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (normalized_code, validity_period, valid_until.isoformat(), created_by_user_id, now.isoformat()),
                )
                coupon_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("Já existe um cupom com essa palavra.") from exc
        return next(coupon for coupon in self.list_coupons() if coupon["id"] == coupon_id)

    def list_coupons(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT coupons.id, coupons.code, coupons.validity_period, coupons.valid_until,
                       coupons.is_active, coupons.created_at,
                       COUNT(coupon_redemptions.id) AS total_redemptions,
                       SUM(CASE WHEN coupon_redemptions.id IS NOT NULL
                                    AND coupon_redemptions.revoked_at IS NULL THEN 1 ELSE 0 END) AS active_redemptions
                FROM coupons
                LEFT JOIN coupon_redemptions ON coupon_redemptions.coupon_id = coupons.id
                GROUP BY coupons.id
                ORDER BY coupons.created_at DESC
                """
            ).fetchall()
        coupons = []
        for row in rows:
            item = dict(row)
            valid_until = datetime.fromisoformat(item["valid_until"])
            item["status"] = "ativo" if item["is_active"] and valid_until > now else "vencido"
            item["total_redemptions"] = int(item["total_redemptions"] or 0)
            item["active_redemptions"] = int(item["active_redemptions"] or 0)
            coupons.append(item)
        return coupons

    def redeem_coupon(self, user_id: int, code: str) -> dict:
        normalized_code = self._normalize_coupon_code(code)
        now = datetime.now(timezone.utc)
        with self._connect() as db:
            coupon = db.execute(
                "SELECT * FROM coupons WHERE code = ? COLLATE NOCASE",
                (normalized_code,),
            ).fetchone()
            if coupon is None:
                raise LookupError("Cupom inválido.")
            if not coupon["is_active"] or datetime.fromisoformat(coupon["valid_until"]) <= now:
                raise ValueError("Este cupom esta vencido.")
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None:
                raise ValueError("Usuário não encontrado.")
            if user["role"] == "admin" or user["account_type"] == "completa" or user["subscription_status"] == "ativa":
                raise ValueError("Seu acesso já está completo.")
            previous = db.execute(
                "SELECT id FROM coupon_redemptions WHERE coupon_id = ? AND user_id = ?",
                (coupon["id"], user_id),
            ).fetchone()
            if previous:
                raise ValueError("Este cupom já foi usado por esta conta.")
            db.execute(
                "INSERT INTO coupon_redemptions(coupon_id,user_id,redeemed_at) VALUES(?,?,?)",
                (coupon["id"], user_id, now.isoformat()),
            )
            db.execute(
                """
                UPDATE users
                SET account_type = 'completa', subscription_status = 'ativa',
                    payment_provider_subscription_id = ?, subscription_started_at = ?,
                    subscription_renews_at = NULL
                WHERE id = ?
                """,
                (f"cupom:{coupon['code']}", now.isoformat(), user_id),
            )
        return dict(coupon)

    def revoke_coupon_access(self, user_id: int, revoked_by_user_id: int) -> dict:
        now = self._now()
        with self._connect() as db:
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None:
                raise ValueError("Usuário não encontrado.")
            provider_reference = str(user["payment_provider_subscription_id"] or "")
            if user["role"] == "admin" or not provider_reference.startswith("cupom:"):
                raise ValueError("Este usuário não possui acesso completo por cupom.")
            db.execute(
                """
                UPDATE coupon_redemptions
                SET revoked_at = ?, revoked_by_user_id = ?
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (now, revoked_by_user_id, user_id),
            )
            db.execute(
                """
                UPDATE users
                SET account_type = 'gratuita', subscription_status = 'inativa',
                    payment_provider_subscription_id = NULL, subscription_started_at = NULL,
                    subscription_renews_at = NULL
                WHERE id = ?
                """,
                (user_id,),
            )
        return dict(self.get_user(user_id))

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
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            db.execute("UPDATE mobile_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (self._now(), user_id))
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

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _insert_mobile_token_pair(
        self,
        db: sqlite3.Connection,
        user_id: int,
        family_id: str,
    ) -> dict[str, str | int]:
        now = datetime.now(timezone.utc)
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(48)
        access_expires = now + timedelta(minutes=MOBILE_ACCESS_MINUTES)
        refresh_expires = now + timedelta(days=MOBILE_REFRESH_DAYS)
        db.executemany(
            """INSERT INTO mobile_tokens(
                   token_hash,user_id,token_type,family_id,created_at,expires_at
               ) VALUES(?,?,?,?,?,?)""",
            (
                (
                    self._token_hash(access_token), user_id, "access", family_id,
                    now.isoformat(), access_expires.isoformat(),
                ),
                (
                    self._token_hash(refresh_token), user_id, "refresh", family_id,
                    now.isoformat(), refresh_expires.isoformat(),
                ),
            ),
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": MOBILE_ACCESS_MINUTES * 60,
        }

    def issue_mobile_tokens(self, user_id: int) -> dict[str, str | int]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
                raise ValueError("Usuario nao encontrado.")
            return self._insert_mobile_token_pair(db, user_id, secrets.token_urlsafe(24))

    def get_user_by_access_token(self, token: str) -> sqlite3.Row | None:
        if not token:
            return None
        now = self._now()
        token_hash = self._token_hash(token)
        with self._connect() as db:
            return db.execute(
                """SELECT users.* FROM mobile_tokens
                   JOIN users ON users.id = mobile_tokens.user_id
                   WHERE mobile_tokens.token_hash = ?
                     AND mobile_tokens.token_type = 'access'
                     AND mobile_tokens.revoked_at IS NULL
                     AND mobile_tokens.expires_at > ?""",
                (token_hash, now),
            ).fetchone()

    def rotate_mobile_refresh_token(self, refresh_token: str) -> dict[str, str | int] | None:
        if not refresh_token:
            return None
        token_hash = self._token_hash(refresh_token)
        now = self._now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM mobile_tokens WHERE token_hash = ? AND token_type = 'refresh'",
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            if row["revoked_at"] or row["expires_at"] <= now:
                db.execute(
                    "UPDATE mobile_tokens SET revoked_at = COALESCE(revoked_at, ?) WHERE family_id = ?",
                    (now, row["family_id"]),
                )
                return None
            replacement = self._insert_mobile_token_pair(db, row["user_id"], row["family_id"])
            db.execute(
                "UPDATE mobile_tokens SET revoked_at = ?, replaced_by_hash = ? WHERE token_hash = ?",
                (now, self._token_hash(str(replacement["refresh_token"])), token_hash),
            )
            return replacement

    def revoke_mobile_tokens(self, access_token: str = "", refresh_token: str = "") -> None:
        hashes = [self._token_hash(token) for token in (access_token, refresh_token) if token]
        if not hashes:
            return
        with self._connect() as db:
            placeholders = ",".join("?" for _ in hashes)
            families = db.execute(
                f"SELECT DISTINCT family_id FROM mobile_tokens WHERE token_hash IN ({placeholders})",
                hashes,
            ).fetchall()
            for family in families:
                db.execute(
                    "UPDATE mobile_tokens SET revoked_at = COALESCE(revoked_at, ?) WHERE family_id = ?",
                    (self._now(), family["family_id"]),
                )

    def delete_account(self, user_id: int, password: str) -> tuple[bool, str, dict]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user or not self.verify_password(password, user["password_hash"]):
                return False, "A senha atual nao confere.", {}
            latest = db.execute(
                "SELECT provider FROM payment_orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            source = str(latest["provider"] if latest else "none")
            summary = {
                "subscription_source": source,
                "subscription_status": str(user["subscription_status"]),
            }
            db.execute(
                """INSERT INTO account_deletion_audit(
                       event_id,requested_at,subscription_source,subscription_status
                   ) VALUES(?,?,?,?)""",
                (secrets.token_urlsafe(24), self._now(), source, summary["subscription_status"]),
            )
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True, "Conta excluida com sucesso.", summary

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

    def reserve_usage(self, user_id: int, field: str) -> tuple[bool, str]:
        """Reserve one unit of work in a single serialized transaction."""
        if field not in {"query", "script", "presentation"}:
            raise ValueError("Tipo de uso invalido.")
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                return False, "Usuario nao encontrado."
            unlimited = (
                user["role"] == "admin"
                or user["account_type"] == "completa"
                or user["subscription_status"] == "ativa"
            )
            if field == "query":
                current = int(user["daily_query_count"] or 0) if user["last_query_date"] == today else 0
                if not unlimited and current >= 3:
                    return False, "A versao gratuita permite apenas 3 consultas por dia."
                db.execute(
                    "UPDATE users SET daily_query_count = ?, last_query_date = ? WHERE id = ?",
                    (current + 1, today, user_id),
                )
            else:
                column = "script_generation_count" if field == "script" else "presentation_generation_count"
                current = int(user[column] or 0)
                if not unlimited and current >= 1:
                    label = "roteiro" if field == "script" else "slide"
                    return False, f"A versao gratuita permite apenas 1 {label}."
                db.execute(f"UPDATE users SET {column} = {column} + 1 WHERE id = ?", (user_id,))
        return True, ""

    def release_usage(self, user_id: int, field: str) -> None:
        """Return a reservation when work fails before producing a result."""
        if field not in {"query", "script", "presentation"}:
            raise ValueError("Tipo de uso invalido.")
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if field == "query":
                db.execute(
                    """UPDATE users
                       SET daily_query_count = MAX(daily_query_count - 1, 0)
                       WHERE id = ? AND last_query_date = ?""",
                    (user_id, today),
                )
            else:
                column = "script_generation_count" if field == "script" else "presentation_generation_count"
                db.execute(
                    f"UPDATE users SET {column} = MAX({column} - 1, 0) WHERE id = ?",
                    (user_id,),
                )

    def list_users(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT id, full_name, email, role, account_type, subscription_status,
                       payment_provider_subscription_id, subscription_started_at,
                       total_access_count, last_access_at, daily_query_count, last_query_date,
                       script_generation_count, presentation_generation_count, created_at
                FROM users ORDER BY created_at DESC
            """).fetchall()
        users = []
        for row in rows:
            item = dict(row)
            provider_reference = str(item.pop("payment_provider_subscription_id") or "")
            item["coupon_code"] = provider_reference.removeprefix("cupom:") if provider_reference.startswith("cupom:") else None
            item["access_origin"] = "cupom" if item["coupon_code"] else ("pagamento" if provider_reference else "cadastro")
            item["can_revoke_coupon"] = bool(
                item["coupon_code"]
                and item["role"] != "admin"
                and (item["account_type"] == "completa" or item["subscription_status"] == "ativa")
            )
            users.append(item)
        return users

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
    def _normalize_coupon_code(code: str) -> str:
        normalized = str(code or "").strip().upper()
        if not 1 <= len(normalized) <= 40 or not re.fullmatch(r"[^\W_]+", normalized, re.UNICODE):
            raise ValueError("O cupom deve ser uma única palavra de até 40 caracteres.")
        return normalized

    @staticmethod
    def _coupon_valid_until(created_at: datetime, validity_period: str) -> datetime:
        if validity_period in COUPON_DURATIONS:
            return created_at + COUPON_DURATIONS[validity_period]
        next_month = 1 if created_at.month == 12 else created_at.month + 1
        next_year = created_at.year + 1 if created_at.month == 12 else created_at.year
        next_day = min(created_at.day, monthrange(next_year, next_month)[1])
        return created_at.replace(year=next_year, month=next_month, day=next_day)

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
