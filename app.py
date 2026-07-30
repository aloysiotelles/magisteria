from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import html
import time
import json
import logging
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from config import BASE_DIR, settings
from services.answer_service import (
    AnswerService,
    BROAD_TOPIC_MESSAGE,
    LOW_CONFIDENCE_MESSAGE,
    TECHNICAL_FAILURE_MESSAGE,
    format_abnt_references,
    format_sources,
)
from services.auth_repository import AuthRepository
from services.email_service import EmailService
from services.localization import LanguageCode, answer_message, normalize_language
from services.presentation_service import PresentationService, safe_filename
from services.asaas_service import AsaasError, AsaasService
from services.mercado_pago_service import MercadoPagoError, MercadoPagoService
from services.vector_store import LocalVectorStore
from services.query_analysis import QueryType, analyze_query
from services.rag_diagnostics import RAGDiagnosticsRepository, new_request_id, redact_query
from services.subscription_service import SubscriptionService
from services.google_play_billing_service import (
    GooglePlayBillingError,
    GooglePlayBillingService,
)
from services.response_planning import PROFILE_INSTRUCTIONS, ResponsePlan, build_response_plan
from services.response_quality import CoverageValidator
from services.retrieval_orchestrator import RetrievalOrchestrator
from services.search_history import UserSearchHistory
from services.semantic_cache import SemanticCache

APP_VERSION = "0.9.2"
logger = logging.getLogger(__name__)

vector_store = LocalVectorStore(
    settings.DOCUMENTS_DIR,
    settings.INDEX_FILE,
    settings.CHUNK_SIZE,
    settings.CHUNK_OVERLAP,
)
answer_service = AnswerService(settings.OPENAI_API_KEY, settings.OPENAI_MODEL, settings.OPENAI_REVIEW_MODEL)
auth_repository = AuthRepository(
    settings.APP_DATABASE_FILE,
    admin_bootstrap_password=settings.ADMIN_BOOTSTRAP_PASSWORD,
)
rag_diagnostics = RAGDiagnosticsRepository(
    settings.APP_DATABASE_FILE,
    settings.RAG_DEBUG,
    settings.RAG_DIAGNOSTIC_RETENTION_DAYS,
)
presentation_service = PresentationService(
    settings.OPENAI_API_KEY,
    settings.OPENAI_MODEL,
    settings.OPENAI_IMAGE_MODEL,
    settings.IMAGE_CONCURRENCY,
    settings.IMAGE_QUALITY,
)
mercado_pago_service = MercadoPagoService(
    settings.MERCADO_PAGO_ACCESS_TOKEN,
    settings.MERCADO_PAGO_WEBHOOK_SECRET,
    settings.MERCADO_PAGO_PRICE,
    settings.MERCADO_PAGO_CURRENCY,
    settings.APP_PUBLIC_URL,
)
asaas_service = AsaasService(
    settings.ASAAS_API_KEY,
    settings.ASAAS_WEBHOOK_TOKEN,
    settings.ASAAS_PRICE,
    settings.APP_PUBLIC_URL,
    settings.ASAAS_API_BASE_URL,
    settings.ASAAS_BILLING_TYPE,
    settings.ASAAS_CALLBACK_ENABLED,
)
subscription_service = SubscriptionService(
    settings.GOOGLE_PLAY_PRODUCT_ID,
    settings.APPLE_PRODUCT_ID,
)
email_service = EmailService(
    settings.GMAIL_OAUTH_CLIENT_ID,
    settings.GMAIL_OAUTH_CLIENT_SECRET,
    settings.GMAIL_OAUTH_REFRESH_TOKEN,
    settings.GMAIL_SENDER_EMAIL,
    settings.APP_PUBLIC_URL,
)
semantic_cache = SemanticCache(
    settings.APP_DATABASE_FILE,
    settings.SEMANTIC_CACHE_TTL_SECONDS,
)
search_history = UserSearchHistory(
    settings.APP_DATABASE_FILE,
    retention_days=settings.SEARCH_HISTORY_RETENTION_DAYS,
    store_original_query=settings.STORE_ORIGINAL_SEARCH_QUERIES,
)
retrieval_orchestrator = RetrievalOrchestrator(vector_store, semantic_cache)
coverage_validator = CoverageValidator()


def active_search_history() -> UserSearchHistory:
    if Path(search_history.database_file).resolve() == Path(auth_repository.database_file).resolve():
        return search_history
    return UserSearchHistory(
        auth_repository.database_file,
        retention_days=settings.SEARCH_HISTORY_RETENTION_DAYS,
        store_original_query=settings.STORE_ORIGINAL_SEARCH_QUERIES,
    )
google_play_billing_service = GooglePlayBillingService(
    settings.GOOGLE_SERVICE_ACCOUNT_CREDENTIALS,
    settings.GOOGLE_PLAY_PACKAGE_NAME,
    settings.GOOGLE_PLAY_PRODUCT_ID,
)
index_lock = asyncio.Lock()
indexing_state = {
    "ativa": False,
    "processados": 0,
    "total": 0,
    "percentual": 0,
    "arquivo_atual": "",
    "segundos_restantes": None,
    "erro": None,
    "inicio": None,
}


def update_indexing_progress(processed: int, total: int, current_file: str) -> None:
    elapsed = time.monotonic() - indexing_state["inicio"] if indexing_state["inicio"] else 0
    percentage = round((processed / total) * 100) if total else 0
    remaining = None
    if processed > 0 and total > processed:
        remaining = round((elapsed / processed) * (total - processed))
    indexing_state.update(
        processados=processed,
        total=total,
        percentual=percentage,
        arquivo_atual=current_file,
        segundos_restantes=remaining,
    )


async def perform_indexing() -> dict:
    indexing_state.update(
        ativa=True,
        processados=0,
        total=0,
        percentual=0,
        arquivo_atual="Preparando documentos",
        segundos_restantes=None,
        erro=None,
        inicio=time.monotonic(),
    )
    try:
        async with index_lock:
            result = await asyncio.to_thread(vector_store.index_documents, update_indexing_progress)
            if result.get("acervo_alterado"):
                await asyncio.to_thread(semantic_cache.invalidate_all)
        indexing_state.update(ativa=False, percentual=100, arquivo_atual="Base atualizada")
        return result
    except Exception as exc:
        indexing_state.update(ativa=False, erro=str(exc), arquivo_atual="Falha na atualização")
        raise


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Inicia a reconstrução da base sem impedir a exibição do progresso."""
    indexing_task = asyncio.create_task(perform_indexing())
    yield
    if not indexing_task.done():
        await indexing_task


app = FastAPI(
    title="MAGISTERIA",
    description="Pesquisa pastoral em uma base documental fechada.",
    version=APP_VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.MOBILE_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "X-Request-ID",
        "X-Path", "X-Offset", "X-Complete",
    ],
)
rate_limit_buckets: dict[str, deque[float]] = defaultdict(deque)
rate_limit_lock = asyncio.Lock()
RATE_LIMIT_RULES = {
    "/login": (20, 300),
    "/cadastro": (10, 300),
    "/esqueci-senha": (5, 300),
    "/redefinir-senha": (10, 300),
    "/api/v1/mobile/auth/login": (20, 300),
    "/api/v1/mobile/auth/register": (10, 300),
    "/api/v1/mobile/auth/password/forgot": (5, 300),
    "/api/v1/mobile/auth/password/reset": (10, 300),
    "/perguntar": (30, 60),
    "/perguntar-stream": (30, 60),
    "/api/v1/ask": (30, 60),
    "/api/v1/ask-stream": (30, 60),
    "/criar-roteiro": (6, 60),
    "/criar-slides": (6, 60),
    "/admin/upload-chunk": (120, 60),
}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    rule = RATE_LIMIT_RULES.get(request.url.path)
    if not settings.RATE_LIMIT_ENABLED or not rule or request.method == "OPTIONS":
        return await call_next(request)
    limit, window_seconds = rule
    client_host = request.client.host if request.client else "unknown"
    key = f"{client_host}:{request.url.path}"
    now = time.monotonic()
    async with rate_limit_lock:
        bucket = rate_limit_buckets[key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, round(window_seconds - (now - bucket[0])))
            return JSONResponse(
                {"detail": "Muitas solicitacoes. Aguarde antes de tentar novamente."},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)
    return await call_next(request)

AUTH_COOKIE = "magisteria_session"
PUBLIC_PATHS = {
    "/health",
    "/status",
    "/versao",
    "/login",
    "/cadastro",
    "/esqueci-senha",
    "/redefinir-senha",
    "/webhooks/mercadopago",
    "/webhooks/asaas",
    "/api/v1/mobile/auth/login",
    "/api/v1/mobile/auth/register",
    "/api/v1/mobile/auth/refresh",
    "/api/v1/mobile/auth/password/forgot",
    "/api/v1/mobile/auth/password/reset",
    "/privacy",
    "/terms",
    "/support",
    "/account-deletion",
    "/app-version",
}
PUBLIC_PREFIXES = ("/static/",)
FREE_CUPON_CODES = {code.strip().upper() for code in os.getenv("FREE_ACCESS_COUPONS", "").split(",") if code.strip()}


def current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Autenticacao necessaria.")
    return dict(user)


def require_admin(request: Request) -> dict:
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso administrativo restrito.")
    return user


def form_value(fields: dict[str, list[str]], key: str) -> str:
    return fields.get(key, [""])[0].strip()


def is_full_access(user: dict) -> bool:
    return user["role"] == "admin" or user["account_type"] == "completa" or user["subscription_status"] == "ativa"


def subscription_summary(user: dict) -> dict:
    return {
        "account_type": user["account_type"],
        "subscription_status": user["subscription_status"],
        "is_full_access": is_full_access(user),
        "daily_query_count": user["daily_query_count"],
        "script_generation_count": user["script_generation_count"],
        "presentation_generation_count": user["presentation_generation_count"],
    }


def formatted_payment_price() -> str:
    value = f"{asaas_service.price:.2f}".replace(".", ",")
    if asaas_service.currency == "BRL":
        return f"R$ {value}"
    return f"{asaas_service.currency} {value}"


def active_payment_provider() -> tuple[str, object]:
    """O Asaas e o unico provedor disponivel para novas assinaturas."""
    return "asaas", asaas_service


def _asaas_internal_status(provider_status: str, event_type: str = "") -> str:
    status = provider_status.strip().upper()
    event = event_type.strip().upper()
    if event == "PAYMENT_DELETED":
        return "cancelled"
    if ("REFUND" in event and event != "PAYMENT_REFUND_DENIED") or status in {
        "REFUNDED", "REFUND_IN_PROGRESS", "PARTIALLY_REFUNDED"
    }:
        return "refunded"
    if "CHARGEBACK" in event or "CHARGEBACK" in status:
        return "charged_back"
    if status in {"CONFIRMED", "RECEIVED", "RECEIVED_IN_CASH"}:
        return "approved"
    if event in {"PAYMENT_CREDIT_CARD_CAPTURE_REFUSED", "PAYMENT_REPROVED_BY_RISK_ANALYSIS"}:
        return "rejected"
    if event == "PAYMENT_RECEIVED_IN_CASH_UNDONE":
        return "cancelled"
    return status.lower() or "unknown"


def valid_cpf_cnpj(value: str) -> bool:
    digits = "".join(character for character in str(value) if character.isdigit())
    if len(digits) not in {11, 14} or len(set(digits)) == 1:
        return False

    def check_digit(numbers: str, weights: list[int]) -> str:
        remainder = sum(int(number) * weight for number, weight in zip(numbers, weights)) % 11
        return "0" if remainder < 2 else str(11 - remainder)

    if len(digits) == 11:
        first = check_digit(digits[:9], list(range(10, 1, -1)))
        second = check_digit(digits[:9] + first, list(range(11, 1, -1)))
        return digits[-2:] == first + second
    first_weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    second_weights = [6] + first_weights
    first = check_digit(digits[:12], first_weights)
    second = check_digit(digits[:12] + first, second_weights)
    return digits[-2:] == first + second


async def reconcile_asaas_payment(
    payment_id: str,
    expected_user_id: int | None = None,
    event_type: str = "",
) -> dict:
    """Consulta o Asaas e so libera acesso apos validar vinculo, valor e status."""
    payment = await asaas_service.get_payment(payment_id)
    provider_payment_id = str(payment.get("id") or "").strip()
    reference = str(payment.get("externalReference") or "").strip()
    subscription_id = str(payment.get("subscription") or "").strip()
    provider_status = str(payment.get("status") or "").strip()
    raw_amount = payment.get("value")
    if not provider_payment_id or not subscription_id or raw_amount is None:
        raise ValueError("Pagamento do Asaas sem os dados necessarios para conciliacao.")

    subscription = await asaas_service.get_subscription(subscription_id)
    reference = reference or str(subscription.get("externalReference") or "").strip()
    if not reference:
        raise ValueError("Pagamento do Asaas sem referencia do MAGISTERIA.")
    order, amount = _validated_subscription_order(reference, raw_amount, "BRL", expected_user_id)
    if str(order.get("provider") or "") != "asaas":
        raise ValueError("Pagamento pertence a outro provedor.")
    if str(order.get("provider_preference_id") or "") != subscription_id:
        raise ValueError("Pagamento nao pertence a assinatura Asaas vinculada.")
    if str(subscription.get("externalReference") or "").strip() != reference:
        raise ValueError("Assinatura Asaas com referencia divergente.")

    status = _asaas_internal_status(provider_status, event_type)
    updated = auth_repository.apply_subscription_invoice(
        reference,
        subscription_id,
        provider_payment_id,
        provider_payment_id,
        status,
        provider_status or event_type,
        f"{amount:.2f}",
        "BRL",
        renews_at=str(subscription.get("nextDueDate") or "").strip() or None,
    )
    return {"payment_id": provider_payment_id, "status": status, "order": dict(updated)}


async def reconcile_mercado_pago_payment(payment_id: str, expected_user_id: int | None = None) -> dict:
    """Concilia um pagamento recorrente usando a assinatura previamente vinculada."""
    payment = await mercado_pago_service.get_payment(payment_id)
    provider_payment_id = str(payment.get("id") or "").strip()
    reference = str(payment.get("external_reference") or "").strip()
    status = str(payment.get("status") or "").strip().lower()
    status_detail = str(payment.get("status_detail") or "").strip()
    currency = str(payment.get("currency_id") or "").strip().upper()
    raw_amount = payment.get("transaction_amount")
    if not provider_payment_id or not reference or not status or raw_amount is None:
        raise ValueError("Pagamento sem os dados necessarios para conciliacao.")

    order = auth_repository.get_payment_order(reference)
    if not order:
        raise ValueError("Pagamento sem referencia criada pelo MAGISTERIA.")
    if expected_user_id is not None and order["user_id"] != expected_user_id:
        raise ValueError("Pagamento pertence a outro usuario.")
    try:
        paid_amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
        expected_amount = Decimal(str(order["expected_amount"])).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Valor de pagamento invalido.") from exc
    if paid_amount != expected_amount or currency != str(order["currency"]).upper():
        logger.warning(
            "Pagamento %s rejeitado na conciliacao: recebido=%s %s esperado=%s %s",
            provider_payment_id,
            paid_amount,
            currency,
            expected_amount,
            order["currency"],
        )
        raise ValueError("Valor ou moeda do pagamento nao conferem.")

    subscription_id = str(order["provider_preference_id"] or "").strip()
    if not subscription_id:
        raise ValueError("Pedido sem assinatura vinculada.")
    subscription = await mercado_pago_service.get_subscription(subscription_id)
    if str(subscription.get("external_reference") or "").strip() != reference:
        raise ValueError("Assinatura com referencia divergente.")
    updated_order = auth_repository.apply_subscription_invoice(
        reference,
        subscription_id,
        provider_payment_id,
        provider_payment_id,
        status,
        status_detail,
        f"{paid_amount:.2f}",
        currency,
        renews_at=str(subscription.get("next_payment_date") or "").strip() or None,
    )
    return {"payment_id": provider_payment_id, "status": status, "order": dict(updated_order)}


def _validated_subscription_order(
    reference: str,
    raw_amount: object,
    currency: str,
    expected_user_id: int | None = None,
) -> tuple[dict, Decimal]:
    order_row = auth_repository.get_payment_order(reference)
    if not order_row:
        raise ValueError("Assinatura sem referencia criada pelo MAGISTERIA.")
    order = dict(order_row)
    if expected_user_id is not None and order["user_id"] != expected_user_id:
        raise ValueError("Assinatura pertence a outro usuario.")
    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
        expected = Decimal(str(order["expected_amount"])).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("Valor de assinatura invalido.") from exc
    if amount != expected or currency.upper() != str(order["currency"]).upper():
        raise ValueError("Valor ou moeda da assinatura nao conferem.")
    return order, amount


async def reconcile_mercado_pago_subscription(
    subscription_id: str, expected_user_id: int | None = None
) -> dict:
    subscription = await mercado_pago_service.get_subscription(subscription_id)
    provider_id = str(subscription.get("id") or "").strip()
    reference = str(subscription.get("external_reference") or "").strip()
    status = str(subscription.get("status") or "").strip().lower()
    recurring = subscription.get("auto_recurring") if isinstance(subscription.get("auto_recurring"), dict) else {}
    raw_amount = recurring.get("transaction_amount")
    currency = str(recurring.get("currency_id") or "").strip().upper()
    if not provider_id or not reference or not status or raw_amount is None:
        raise ValueError("Assinatura sem os dados necessarios para conciliacao.")
    order, amount = _validated_subscription_order(reference, raw_amount, currency, expected_user_id)
    if order["provider_preference_id"] not in {None, provider_id}:
        raise ValueError("Pedido vinculado a outra assinatura.")
    updated = auth_repository.apply_provider_subscription(
        reference,
        provider_id,
        status,
        f"{amount:.2f}",
        currency,
        started_at=str(subscription.get("date_created") or "").strip() or None,
        renews_at=str(subscription.get("next_payment_date") or "").strip() or None,
    )
    return {"subscription_id": provider_id, "status": status, "order": dict(updated)}


async def reconcile_mercado_pago_invoice(invoice_id: str) -> dict:
    invoice = await mercado_pago_service.get_authorized_payment(invoice_id)
    provider_invoice_id = str(invoice.get("id") or invoice_id).strip()
    subscription_id = str(invoice.get("preapproval_id") or "").strip()
    reference = str(invoice.get("external_reference") or "").strip()
    currency = str(invoice.get("currency_id") or "").strip().upper()
    raw_amount = invoice.get("transaction_amount")
    payment = invoice.get("payment") if isinstance(invoice.get("payment"), dict) else {}
    payment_id = str(payment.get("id") or "").strip()
    status = str(payment.get("status") or invoice.get("status") or "").strip().lower()
    status_detail = str(payment.get("status_detail") or invoice.get("summarized") or "").strip()
    if not subscription_id or not reference or not status or raw_amount is None:
        raise ValueError("Fatura recorrente sem os dados necessarios para conciliacao.")
    order, amount = _validated_subscription_order(reference, raw_amount, currency)
    if str(order["provider_preference_id"] or "") != subscription_id:
        raise ValueError("Fatura nao pertence a assinatura vinculada.")
    subscription = await mercado_pago_service.get_subscription(subscription_id)
    updated = auth_repository.apply_subscription_invoice(
        reference,
        subscription_id,
        provider_invoice_id,
        payment_id,
        status,
        status_detail,
        f"{amount:.2f}",
        currency,
        renews_at=str(subscription.get("next_payment_date") or "").strip() or None,
    )
    return {"invoice_id": provider_invoice_id, "status": status, "order": dict(updated)}


@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    if path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return await call_next(request)
    authorization = request.headers.get("Authorization", "")
    scheme, _, credential = authorization.partition(" ")
    user = (
        auth_repository.get_user_by_access_token(credential.strip())
        if scheme.lower() == "bearer" and credential.strip()
        else auth_repository.get_user_by_session(request.cookies.get(AUTH_COOKIE, ""))
    )
    if user:
        request.state.user = user
        if path.startswith("/admin") and user["role"] != "admin":
            return JSONResponse({"detail": "Acesso administrativo restrito."}, status_code=403)
        return await call_next(request)
    if request.method == "GET" and not path.startswith("/api/"):
        return RedirectResponse(url="/login", status_code=303)
    return JSONResponse({"detail": "Autenticacao necessaria."}, status_code=401)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; font-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if forwarded_proto == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def auth_page(title: str, intro: str, action: str, fields: str, footer: str, message: str = "", error: bool = False) -> HTMLResponse:
    notice = f'<p class="{"erro" if error else "sucesso"}">{html.escape(message)}</p>' if message else ""
    return HTMLResponse(f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} - MAGISTERIA</title><style>
body{{font-family:system-ui;background:#f3efe7;display:grid;place-items:center;min-height:100vh;margin:0;color:#251d16}}
form{{background:white;padding:2rem;border-radius:18px;box-shadow:0 12px 40px #0002;width:min(420px,86vw);text-align:center}}
input,button{{box-sizing:border-box;width:100%;padding:.9rem;margin-top:8px;border-radius:10px;font-size:1rem}}
input{{border:1px solid #9a8c7b}}button{{border:0;background:#173f2a;color:white;font-weight:700;cursor:pointer}}
a{{color:#a52a20;font-weight:700;text-decoration:none}}.erro{{color:#a11}}.sucesso{{color:#17613a}}h1{{margin:.2rem 0;color:#173f2a}}
.auth-logo{{width:128px;height:128px;object-fit:cover;border-radius:50%;filter:drop-shadow(0 8px 14px #0002);margin-bottom:.7rem}}
.auth-slogan{{color:#173f2a;font-weight:800;line-height:1.45;margin:.25rem 0 1rem}}.auth-slogan strong{{color:#a52a20}}
</style></head><body><form method="post" action="{action}"><img class="auth-logo" src="/static/logo-magisteria.png" alt="Logo MAGISTERIA"><h1>MAGISTERIA</h1>
<p class="auth-slogan">Gaste tempo <strong>EVANGELIZANDO</strong>, não pesquisando</p>
<p>{html.escape(intro)}</p>{notice}{fields}<button type="submit">{html.escape(title)}</button><p>{footer}</p></form></body></html>""")


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(erro: str = "", cadastrado: str = "", redefinida: str = ""):
    message = (
        "Login ou senha incorretos."
        if erro
        else "Cadastro criado. Entre para continuar."
        if cadastrado
        else "Senha redefinida. Entre novamente."
        if redefinida
        else ""
    )
    fields = """
<input type="text" name="email" placeholder="Email ou Admin" required autofocus>
<input type="password" name="senha" placeholder="Senha" required>
"""
    footer = (
        'Ainda nao tem conta? <a href="/cadastro">Criar cadastro</a>.<br>'
        '<a href="/esqueci-senha">Esqueci minha senha</a>.'
    )
    return auth_page(
        "Entrar", "Acesse com email e senha.", "/login", fields,
        footer, message, bool(erro),
    )


@app.post("/login", include_in_schema=False)
async def login(request: Request):
    fields = parse_qs((await request.body()).decode("utf-8"))
    user = auth_repository.authenticate(form_value(fields, "email"), form_value(fields, "senha"))
    if not user:
        return RedirectResponse(url="/login?erro=1", status_code=303)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        AUTH_COOKIE,
        auth_repository.create_session(user["id"]),
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
    )
    return response


@app.get("/cadastro", response_class=HTMLResponse, include_in_schema=False)
async def register_page(erro: str = ""):
    fields = """
<input type="text" name="nome" placeholder="Nome completo" required autofocus>
<input type="email" name="email" placeholder="Email" required>
<input type="password" name="senha" placeholder="Senha forte" required minlength="8"
       pattern="(?=.*[a-záéíóúàâêôãõç])(?=.*[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ])(?=.*[0-9]).{8,}"
       title="Use pelo menos 8 caracteres, com uma letra maiúscula, uma minúscula e um número.">
"""
    return auth_page("Criar cadastro", "Crie sua conta gratuita.", "/cadastro", fields, 'Ja tem conta? <a href="/login">Entrar</a>.', erro, bool(erro))


@app.post("/cadastro", include_in_schema=False)
async def register(request: Request):
    fields = parse_qs((await request.body()).decode("utf-8"))
    ok, message = auth_repository.create_user(form_value(fields, "nome"), form_value(fields, "email"), form_value(fields, "senha"))
    if not ok:
        return RedirectResponse(url=f"/cadastro?erro={quote(message)}", status_code=303)
    return RedirectResponse(url="/login?cadastrado=1", status_code=303)


async def send_password_reset_if_registered(email: str) -> None:
    if not email_service.configured:
        raise HTTPException(
            status_code=503,
            detail="O envio de email para recuperacao ainda nao esta configurado.",
        )
    issued = await asyncio.to_thread(auth_repository.issue_password_reset_token, email)
    if not issued:
        return
    token, user = issued
    try:
        await email_service.send_password_reset(user["full_name"], user["email"], token)
    except Exception as exc:
        await asyncio.to_thread(auth_repository.discard_password_reset_token, token)
        logger.exception("Falha ao enviar email de redefinicao de senha.")
        raise HTTPException(
            status_code=503,
            detail="Nao foi possivel enviar o email agora. Tente novamente em alguns minutos.",
        ) from exc


@app.get("/esqueci-senha", response_class=HTMLResponse, include_in_schema=False)
async def forgot_password_page():
    fields = '<input type="email" name="email" placeholder="Email cadastrado" required autofocus>'
    return auth_page(
        "Enviar link seguro",
        "Informe o email cadastrado para receber um link de redefinicao.",
        "/esqueci-senha",
        fields,
        '<a href="/login">Voltar para entrar</a>.',
    )


@app.post("/esqueci-senha", response_class=HTMLResponse, include_in_schema=False)
async def forgot_password(request: Request):
    fields = parse_qs((await request.body()).decode("utf-8"))
    await send_password_reset_if_registered(form_value(fields, "email"))
    return auth_page(
        "Solicitacao recebida",
        "Se o email estiver cadastrado, enviaremos um link seguro que expira em 30 minutos.",
        "/esqueci-senha",
        '<input type="email" name="email" placeholder="Email cadastrado" required>',
        '<a href="/login">Voltar para entrar</a>.',
        "Verifique sua caixa de entrada e a pasta de spam.",
    )


def reset_password_page(token: str, message: str = "", error: bool = False) -> HTMLResponse:
    safe_token = html.escape(token, quote=True)
    fields = f"""
<input type="hidden" name="token" value="{safe_token}">
<input type="password" name="nova_senha" placeholder="Nova senha" required minlength="8"
       pattern="(?=.*[a-záéíóúàâêôãõç])(?=.*[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ])(?=.*[0-9]).{{8,}}"
       title="Use pelo menos 8 caracteres, com uma letra maiúscula, uma minúscula e um número." autofocus>
<input type="password" name="confirmar_senha" placeholder="Confirmar nova senha" required minlength="8">
"""
    return auth_page(
        "Criar nova senha",
        "Use pelo menos 8 caracteres, com uma letra maiuscula, uma minuscula e um numero.",
        "/redefinir-senha",
        fields,
        '<a href="/login">Voltar para entrar</a>.',
        message,
        error,
    )


@app.get("/redefinir-senha", response_class=HTMLResponse, include_in_schema=False)
async def reset_password_form(token: str = ""):
    if len(token.strip()) < 20:
        return reset_password_page("", "Este link e invalido ou esta incompleto.", True)
    return reset_password_page(token.strip())


@app.post("/redefinir-senha", include_in_schema=False)
async def reset_password(request: Request):
    fields = parse_qs((await request.body()).decode("utf-8"))
    token = form_value(fields, "token")
    password = form_value(fields, "nova_senha")
    confirmation = form_value(fields, "confirmar_senha")
    if password != confirmation:
        return reset_password_page(token, "A confirmacao da nova senha nao confere.", True)
    ok, message = await asyncio.to_thread(
        auth_repository.reset_password_with_token,
        token,
        password,
    )
    if not ok:
        return reset_password_page(token, message, True)
    return RedirectResponse(url="/login?redefinida=1", status_code=303)


@app.post("/logout", include_in_schema=False)
async def logout(request: Request):
    auth_repository.delete_session(request.cookies.get(AUTH_COOKIE, ""))
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE, secure=settings.COOKIE_SECURE, samesite="lax")
    return response


@app.post("/alterar-senha")
async def change_password(request: Request):
    user = current_user(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    current_password = str(
        payload.get("senha_atual")
        or payload.get("current_password")
        or payload.get("currentPassword")
        or payload.get("senhaAtual")
        or ""
    )
    new_password = str(
        payload.get("nova_senha")
        or payload.get("new_password")
        or payload.get("newPassword")
        or payload.get("novaSenha")
        or ""
    )
    confirm_password = str(
        payload.get("confirmar_senha")
        or payload.get("confirm_password")
        or payload.get("confirmPassword")
        or payload.get("confirmarSenha")
        or ""
    )
    if not current_password:
        raise HTTPException(status_code=400, detail="Informe a senha atual.")
    if not new_password:
        raise HTTPException(status_code=400, detail="Informe a nova senha.")
    if not confirm_password:
        raise HTTPException(status_code=400, detail="Confirme a nova senha.")
    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="A confirmacao da nova senha nao confere.")
    ok, message = auth_repository.change_password(user["id"], current_password, new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"mensagem": message}


@app.get("/assinatura")
async def subscription_info(request: Request):
    user = current_user(request)
    provider_name, provider_service = active_payment_provider()
    latest_order = auth_repository.get_latest_payment_order(user["id"], provider_name)
    return {
        "usuario": {
            "nome": user["full_name"],
            "plano": "completo" if is_full_access(user) else "gratuito",
            "limites": {
                "consultas_por_dia": 3,
                "roteiros": 1,
                "slides": 1,
            },
        },
        "pagamento": {
            "provedor": "Asaas" if provider_name == "asaas" else "Mercado Pago",
            "disponivel": provider_service.configured,
            "valor": f"{formatted_payment_price()} por mês" if provider_service.price > 0 else None,
            "valor_base": formatted_payment_price() if provider_service.price > 0 else None,
            "status": latest_order["status"] if latest_order else None,
            "confirmacao": "A liberação completa ocorre depois da confirmação da assinatura pelo Asaas.",
        },
    }


@app.post("/assinatura/checkout")
async def create_subscription_checkout(request: Request):
    user = current_user(request)
    if is_full_access(user):
        raise HTTPException(status_code=409, detail="Seu acesso já está completo.")
    provider_name, provider_service = active_payment_provider()
    if not provider_service.configured:
        raise HTTPException(status_code=503, detail="O pagamento ainda não foi configurado pelo administrador.")

    if provider_name == "asaas":
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {}
        document = "".join(
            character for character in str(payload.get("cpf_cnpj") or "") if character.isdigit()
        )
        if not valid_cpf_cnpj(document):
            raise HTTPException(status_code=400, detail="Informe um CPF ou CNPJ válido.")
        latest_order = auth_repository.get_latest_payment_order(user["id"], "asaas")
        if latest_order and latest_order["status"] == "pending" and latest_order["provider_preference_id"]:
            try:
                payment = await asaas_service.get_first_subscription_payment(
                    latest_order["provider_preference_id"]
                )
                checkout_url = str(payment.get("invoiceUrl") or "").strip()
                if checkout_url.startswith("https://"):
                    return {"checkout_url": checkout_url, "referencia": latest_order["reference"]}
            except AsaasError:
                pass

        order = auth_repository.create_payment_order(
            user["id"],
            f"{asaas_service.price:.2f}",
            asaas_service.currency,
            "asaas",
        )
        try:
            customer = await asaas_service.get_or_create_customer(user, document)
            subscription = await asaas_service.create_subscription(customer["id"], order["reference"])
        except (AsaasError, KeyError) as exc:
            message = str(exc) if isinstance(exc, AsaasError) else "O Asaas devolveu dados incompletos do cliente."
            auth_repository.mark_payment_order_error(order["reference"], message)
            status_code = exc.status_code if isinstance(exc, AsaasError) else 502
            raise HTTPException(status_code=status_code, detail=message) from exc
        auth_repository.attach_payment_preference(order["reference"], subscription["id"])
        return {"checkout_url": subscription["checkout_url"], "referencia": order["reference"]}

@app.get("/admin/pagamentos/{operation_id}")
async def payment_diagnostic(operation_id: str, request: Request):
    """Consulta administrativa, sem dados pessoais, para diagnosticar recusas do provedor."""
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso administrativo necessario.")
    provider_name, _ = active_payment_provider()
    if provider_name == "asaas":
        payment = await asaas_service.get_payment(operation_id)
        return {
            "provedor": "asaas",
            "id": str(payment.get("id") or ""),
            "status": str(payment.get("status") or ""),
            "billing_type": str(payment.get("billingType") or ""),
            "value": payment.get("value"),
            "currency": "BRL",
            "external_reference": str(payment.get("externalReference") or ""),
            "subscription": str(payment.get("subscription") or ""),
        }
    payment = await mercado_pago_service.get_payment(operation_id)
    return {
        "provedor": "mercado_pago",
        "id": str(payment.get("id") or ""),
        "status": str(payment.get("status") or ""),
        "status_detail": str(payment.get("status_detail") or ""),
        "payment_method": str(payment.get("payment_method_id") or ""),
        "payment_type": str(payment.get("payment_type_id") or ""),
        "transaction_amount": payment.get("transaction_amount"),
        "currency": str(payment.get("currency_id") or ""),
        "external_reference": str(payment.get("external_reference") or ""),
    }


@app.get("/assinatura/retorno", include_in_schema=False)
async def subscription_return(request: Request):
    user = current_user(request)
    provider_name, _ = active_payment_provider()
    if provider_name == "asaas":
        latest_order = auth_repository.get_latest_payment_order(user["id"], "asaas")
        result = "pendente"
        if latest_order and latest_order["provider_preference_id"]:
            try:
                payment = await asaas_service.get_first_subscription_payment(
                    latest_order["provider_preference_id"]
                )
                reconciliation = await reconcile_asaas_payment(str(payment.get("id") or ""), user["id"])
                result = "aprovado" if reconciliation["status"] == "approved" else reconciliation["status"]
            except (AsaasError, ValueError) as exc:
                logger.warning("Retorno do Asaas não conciliado para usuário %s: %s", user["id"], exc)
        return RedirectResponse(url=f"/?pagamento={quote(result)}", status_code=303)

    subscription_id = str(
        request.query_params.get("preapproval_id")
        or request.query_params.get("subscription_id")
        or ""
    ).strip()
    result = str(request.query_params.get("resultado") or "pendente").strip().lower()
    if not subscription_id:
        latest_order = auth_repository.get_latest_payment_order(user["id"])
        subscription_id = str(latest_order["provider_preference_id"] or "").strip() if latest_order else ""
    if subscription_id:
        try:
            reconciliation = await reconcile_mercado_pago_subscription(subscription_id, user["id"])
            result = "aprovado" if reconciliation["status"] == "authorized" else reconciliation["status"]
        except (MercadoPagoError, ValueError) as exc:
            logger.warning("Retorno de pagamento não conciliado para usuário %s: %s", user["id"], exc)
    return RedirectResponse(url=f"/?pagamento={quote(result)}", status_code=303)


@app.post("/assinatura/cupom")
async def redeem_coupon(request: Request):
    user = current_user(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    code = str(payload.get("cupom", "")).strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Informe o cupom.")
    try:
        auth_repository.redeem_coupon(user["id"], code)
    except LookupError:
        if code not in FREE_CUPON_CODES:
            raise HTTPException(status_code=400, detail="Cupom inválido.")
        auth_repository.apply_coupon_access(user["id"], code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = auth_repository.get_user(user["id"])
    return {"mensagem": "Acesso completo liberado pelo cupom.", "usuario": subscription_summary(dict(updated))}


@app.post("/webhooks/asaas")
async def asaas_webhook(request: Request):
    if not asaas_service.validate_webhook_token(request.headers.get("asaas-access-token")):
        raise HTTPException(status_code=401, detail="Token do webhook inválido.")
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Notificação do Asaas inválida.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Notificação do Asaas inválida.")

    event_id = str(payload.get("id") or "").strip()
    event_type = str(payload.get("event") or "").strip().upper()
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
    payment_id = str(payment.get("id") or "").strip()
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Notificação do Asaas incompleta.")
    if auth_repository.webhook_event_processed("asaas", event_id):
        return {"mensagem": "Notificação já processada."}
    if not event_type.startswith("PAYMENT_"):
        auth_repository.record_webhook_event("asaas", event_id, event_type)
        return {"mensagem": "Evento ignorado."}
    if not payment_id:
        raise HTTPException(status_code=400, detail="Notificação do Asaas sem pagamento.")

    try:
        result = await reconcile_asaas_payment(payment_id, event_type=event_type)
    except ValueError as exc:
        logger.warning("Webhook do Asaas sem vínculo válido: %s", exc)
        auth_repository.record_webhook_event("asaas", event_id, event_type)
        return {"mensagem": "Evento sem vínculo válido; ignorado."}
    except AsaasError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    auth_repository.record_webhook_event("asaas", event_id, event_type)
    return {"mensagem": "Notificação processada.", "status": result["status"]}


@app.post("/webhooks/mercadopago")
async def mercadopago_webhook(request: Request):
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    topic = str(payload.get("type") or request.query_params.get("type") or request.query_params.get("topic") or "").lower()
    topic = {"subscription": "subscription_preapproval", "invoice": "subscription_authorized_payment"}.get(topic, topic)
    accepted_topics = {"payment", "subscription_preapproval", "subscription_authorized_payment"}
    if topic and topic not in accepted_topics:
        return {"mensagem": "Evento ignorado."}

    signed_data_id = request.query_params.get("data.id")
    resource_id = str(signed_data_id or data.get("id") or request.query_params.get("id") or "").strip()
    if not mercado_pago_service.validate_webhook_signature(
        request.headers.get("x-signature"),
        request.headers.get("x-request-id"),
        signed_data_id,
    ):
        raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.")
    if not resource_id:
        raise HTTPException(status_code=400, detail="Notificação do Mercado Pago incompleta.")

    try:
        if topic == "subscription_preapproval":
            result = await reconcile_mercado_pago_subscription(resource_id)
        elif topic == "subscription_authorized_payment":
            result = await reconcile_mercado_pago_invoice(resource_id)
        else:
            result = await reconcile_mercado_pago_payment(resource_id)
    except ValueError as exc:
        logger.warning("Webhook do Mercado Pago ignorado: %s", exc)
        return {"mensagem": "Evento sem vínculo válido; ignorado."}
    except MercadoPagoError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"mensagem": "Notificação processada.", "status": result["status"]}
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


class ConversationTurn(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000)
    resposta: str = Field(min_length=1, max_length=8000)


class QuestionRequest(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000)
    historico: list[ConversationTurn] = Field(default_factory=list, max_length=6)
    idioma: LanguageCode = "pt-BR"
    perfil: str = Field(default="adulto_leigo", pattern="^(" + "|".join(PROFILE_INSTRUCTIONS) + ")$")


class PasswordChangeRequest(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=200)
    nova_senha: str = Field(min_length=8, max_length=200)
    confirmar_senha: str = Field(min_length=8, max_length=200)


class PresentationRequest(BaseModel):
    titulo: str = Field(min_length=3, max_length=300)
    resposta: str = Field(min_length=20, max_length=16000)
    idioma: LanguageCode = "pt-BR"


class MobileLoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class MobileRegisterRequest(BaseModel):
    full_name: str = Field(min_length=3, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class MobileRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=500)


class MobileLogoutRequest(BaseModel):
    refresh_token: str = Field(default="", max_length=500)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    new_password: str = Field(min_length=8, max_length=200)
    confirm_password: str = Field(min_length=8, max_length=200)


class AccountDeletionRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    confirmation: str = Field(min_length=1, max_length=40)


class GooglePlayPurchaseRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=200)
    purchase_token: str = Field(min_length=1, max_length=4096)


class GooglePlaySyncRequest(BaseModel):
    purchases: list[GooglePlayPurchaseRequest] = Field(default_factory=list, max_length=10)


def mobile_user_payload(user: dict) -> dict:
    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"],
        "subscription": subscription_summary(user),
    }


def bearer_credential(request: Request) -> str:
    scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
    return credential.strip() if scheme.lower() == "bearer" else ""


@app.post("/api/v1/mobile/auth/login")
async def mobile_login(payload: MobileLoginRequest):
    user = await asyncio.to_thread(auth_repository.authenticate, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos.")
    tokens = await asyncio.to_thread(auth_repository.issue_mobile_tokens, user["id"])
    return {**tokens, "user": mobile_user_payload(dict(user))}


@app.post("/api/v1/mobile/auth/register", status_code=201)
async def mobile_register(payload: MobileRegisterRequest):
    ok, message = await asyncio.to_thread(
        auth_repository.create_user,
        payload.full_name,
        payload.email,
        payload.password,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    user = await asyncio.to_thread(auth_repository.authenticate, payload.email, payload.password)
    tokens = await asyncio.to_thread(auth_repository.issue_mobile_tokens, user["id"])
    return {**tokens, "user": mobile_user_payload(dict(user))}


@app.post("/api/v1/mobile/auth/password/forgot")
async def mobile_forgot_password(payload: ForgotPasswordRequest):
    await send_password_reset_if_registered(payload.email)
    return {
        "message": (
            "Se o email estiver cadastrado, enviaremos um link seguro para criar uma nova senha. "
            "Verifique tambem a pasta de spam."
        )
    }


@app.post("/api/v1/mobile/auth/password/reset")
async def mobile_reset_password(payload: ResetPasswordRequest):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="A confirmacao da nova senha nao confere.")
    ok, message = await asyncio.to_thread(
        auth_repository.reset_password_with_token,
        payload.token,
        payload.new_password,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}


@app.post("/api/v1/mobile/auth/refresh")
async def mobile_refresh(payload: MobileRefreshRequest):
    tokens = await asyncio.to_thread(auth_repository.rotate_mobile_refresh_token, payload.refresh_token)
    if not tokens:
        raise HTTPException(status_code=401, detail="Sessao expirada. Entre novamente.")
    return tokens


@app.post("/api/v1/mobile/auth/logout", status_code=204)
async def mobile_logout(payload: MobileLogoutRequest, request: Request):
    await asyncio.to_thread(
        auth_repository.revoke_mobile_tokens,
        bearer_credential(request),
        payload.refresh_token,
    )
    return Response(status_code=204)


@app.get("/api/v1/mobile/me")
async def mobile_me(request: Request):
    return {"user": mobile_user_payload(current_user(request))}


@app.get("/api/v1/mobile/subscription")
async def mobile_subscription(request: Request):
    user = current_user(request)
    order = await asyncio.to_thread(auth_repository.get_latest_payment_order, user["id"])
    store_subscription = await asyncio.to_thread(
        auth_repository.get_store_subscription_for_user,
        user["id"],
        "google_play",
    )
    provider = "google_play" if store_subscription else str(order["provider"] if order else "")
    entitlement = subscription_service.snapshot(user, provider)
    return {
        "entitlement": entitlement.to_dict(),
        "store_products_configured": subscription_service.store_products_configured,
        "google_play": {
            "available": google_play_billing_service.configured,
            "package_name": settings.GOOGLE_PLAY_PACKAGE_NAME,
            "product_id": settings.GOOGLE_PLAY_PRODUCT_ID,
            "store_state": str(store_subscription["store_state"] if store_subscription else ""),
        },
    }


@app.post("/api/v1/mobile/subscription/coupon")
async def mobile_redeem_coupon(payload: dict, request: Request):
    user = current_user(request)
    code = str(payload.get("coupon") or payload.get("cupom") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Informe o cupom.")
    try:
        await asyncio.to_thread(auth_repository.redeem_coupon, user["id"], code)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = await asyncio.to_thread(auth_repository.get_user, user["id"])
    return {
        "message": "Acesso completo liberado pelo cupom.",
        "user": mobile_user_payload(dict(updated)),
    }


async def verify_google_play_purchase(user_id: int, purchase: GooglePlayPurchaseRequest) -> dict:
    try:
        verified = await google_play_billing_service.verify_subscription(
            purchase.product_id,
            purchase.purchase_token,
        )
        return await asyncio.to_thread(
            auth_repository.apply_store_subscription,
            user_id,
            provider="google_play",
            **verified.to_dict(),
        )
    except GooglePlayBillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/mobile/subscription/google/verify")
async def mobile_verify_google_subscription(
    payload: GooglePlayPurchaseRequest,
    request: Request,
):
    user = current_user(request)
    updated = await verify_google_play_purchase(user["id"], payload)
    store = await asyncio.to_thread(
        auth_repository.get_store_subscription_for_user,
        user["id"],
        "google_play",
    )
    return {
        "message": (
            "Assinatura confirmada. Seu acesso completo esta ativo."
            if is_full_access(updated)
            else "A compra ainda aguarda confirmacao do Google Play."
        ),
        "user": mobile_user_payload(updated),
        "store": store,
    }


@app.post("/api/v1/mobile/subscription/google/sync")
async def mobile_sync_google_subscription(payload: GooglePlaySyncRequest, request: Request):
    user = current_user(request)
    updated = dict(user)
    if payload.purchases:
        for purchase in payload.purchases:
            updated = await verify_google_play_purchase(user["id"], purchase)
    else:
        updated = await asyncio.to_thread(
            auth_repository.clear_store_entitlement,
            user["id"],
            "google_play",
        )
    return {"user": mobile_user_payload(updated)}


@app.delete("/api/v1/mobile/account")
async def mobile_delete_account(payload: AccountDeletionRequest, request: Request):
    user = current_user(request)
    if user["role"] == "admin":
        raise HTTPException(status_code=409, detail="A conta administrativa deve ser transferida antes da exclusao.")
    if payload.confirmation.strip().upper() != "EXCLUIR":
        raise HTTPException(status_code=400, detail="Digite EXCLUIR para confirmar.")
    ok, message, subscription = await asyncio.to_thread(
        auth_repository.delete_account,
        user["id"],
        payload.password,
    )
    if not ok:
        raise HTTPException(status_code=401, detail=message)
    return {"message": message, "subscription": subscription}


@app.get("/api/v1/mobile/history")
async def mobile_search_history(
    request: Request,
    search: str = "",
    sort: str = "date",
    limit: int = 100,
):
    user = current_user(request)
    if sort not in {"date", "frequency"}:
        raise HTTPException(status_code=400, detail="Ordenação de histórico inválida.")
    items = await asyncio.to_thread(
        active_search_history().list,
        user["id"],
        search=search,
        sort=sort,
        limit=limit,
    )
    return {"items": items}


@app.get("/api/v1/mobile/history/{history_id}/requery")
async def mobile_requery_history(history_id: int, request: Request):
    user = current_user(request)
    item = await asyncio.to_thread(active_search_history().get_for_requery, user["id"], history_id)
    if not item:
        raise HTTPException(status_code=404, detail="Consulta do histórico não encontrada.")
    # The client must submit this query through the normal ask endpoint. No old
    # answer is returned, so corpus version and semantic cache are checked again.
    return item


@app.delete("/api/v1/mobile/history/{history_id}", status_code=204)
async def mobile_delete_history_item(history_id: int, request: Request):
    user = current_user(request)
    deleted = await asyncio.to_thread(active_search_history().delete, user["id"], history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Consulta do histórico não encontrada.")
    return Response(status_code=204)


@app.delete("/api/v1/mobile/history", status_code=204)
async def mobile_clear_history(request: Request):
    user = current_user(request)
    await asyncio.to_thread(active_search_history().clear, user["id"])
    return Response(status_code=204)


PUBLIC_CONTROLLER = "Aloysio Telles de Moraes Netto"
PUBLIC_SUPPORT_EMAIL = "aplicativo.magisteria@gmail.com"


def public_information_page(
    title: str,
    intro: str,
    sections: list[tuple[str, str]],
) -> HTMLResponse:
    section_html = "".join(
        f"<section><h2>{html.escape(heading)}</h2><p>{html.escape(content)}</p></section>"
        for heading, content in sections
    )
    email = html.escape(PUBLIC_SUPPORT_EMAIL)
    return HTMLResponse(
        f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <meta name="color-scheme" content="light">
        <title>{html.escape(title)} - MAGISTERIA</title>
        <link rel="stylesheet" href="/static/legal.css"></head><body><main>
        <h1>{html.escape(title)}</h1><p class="meta">MAGISTERIA · última atualização: 27 de julho de 2026</p>
        <p>{html.escape(intro)}</p>{section_html}
        <section><h2>Controlador e contato</h2><p>Responsável: {html.escape(PUBLIC_CONTROLLER)}.<br>
        E-mail: <a href="mailto:{email}">{email}</a>. Nunca envie sua senha por e-mail.</p></section>
        <nav aria-label="Informações legais"><a href="/privacy">Privacidade</a><a href="/terms">Termos</a>
        <a href="/support">Suporte</a><a href="/account-deletion">Exclusão de conta</a></nav>
        </main></body></html>"""
    )


@app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_page():
    return public_information_page(
        "Política de privacidade",
        "Esta política explica como o MAGISTERIA trata dados pessoais ao oferecer seus serviços web e Android.",
        [
            ("Dados tratados", "Dados de cadastro e autenticação, como nome, e-mail e hash da senha; perguntas e conteúdos enviados para gerar respostas; histórico privado de temas consultados; dados de uso, franquias, sessões e diagnósticos técnicos limitados; e informações de assinatura ou pagamento quando esse recurso for utilizado."),
            ("Finalidades", "Os dados são usados para criar e proteger a conta, fornecer respostas e arquivos solicitados, aplicar limites de uso, prestar suporte, prevenir abuso, manter o serviço e cumprir obrigações legais."),
            ("Operadores e compartilhamento", "Dados necessários podem ser processados por provedores de hospedagem, inteligência artificial, e-mail, pagamento e distribuição do aplicativo. Não vendemos dados pessoais. Cada provedor recebe somente o necessário para sua função e está sujeito às respectivas políticas e contratos."),
            ("Histórico e cache", "O histórico pertence exclusivamente à conta autenticada, pode ser excluído por item ou integralmente e tem retenção configurável. O cache reutiliza somente classificação e evidências documentais, nunca a resposta gerada nem dados pessoais do histórico."),
            ("Retenção", "Dados da conta são mantidos enquanto ela estiver ativa. Sessões e tokens expiram ou são revogados. Diagnósticos técnicos tipados têm retenção padrão de 14 dias e não guardam o texto aberto da consulta. O histórico tem retenção padrão de 365 dias. Registros mínimos podem ser preservados quando necessários para segurança, prevenção a fraude ou obrigação legal."),
            ("Segurança", "Usamos HTTPS, senhas derivadas por hash, tokens móveis rotativos armazenados de forma segura, controles de acesso e limitação de requisições. Nenhum sistema é totalmente imune a incidentes, mas adotamos medidas proporcionais aos riscos."),
            ("Seus direitos", "Você pode solicitar acesso, correção, informação, oposição ou exclusão de dados pelos canais desta página, conforme a legislação aplicável. A exclusão também pode ser iniciada no aplicativo."),
            ("Crianças e adolescentes", "O serviço não deve ser usado para criar uma conta por pessoa sem capacidade legal ou autorização de seu responsável. Responsáveis podem contatar o suporte para exercer direitos sobre dados."),
            ("Alterações", "Esta política pode ser atualizada para refletir mudanças no serviço ou na legislação. A data da versão vigente é exibida no início da página."),
        ],
    )


@app.get("/terms", response_class=HTMLResponse, include_in_schema=False)
async def terms_page():
    return public_information_page(
        "Termos de uso",
        "Ao criar uma conta ou utilizar o MAGISTERIA, você concorda com estes termos.",
        [
            ("Serviço", "O MAGISTERIA oferece pesquisa e geração assistida por inteligência artificial para estudo e preparação de conteúdos. Recursos, limites e disponibilidade podem variar por plano e versão."),
            ("Conta", "Você deve fornecer dados verdadeiros, manter sua senha em sigilo e comunicar acessos indevidos. A conta é pessoal e não deve ser cedida."),
            ("Uso responsável", "É proibido usar o serviço para violar leis, direitos de terceiros, controles de segurança, limites técnicos ou para distribuir conteúdo malicioso. Abusos podem levar à suspensão."),
            ("Conteúdo gerado", "Respostas de inteligência artificial podem conter imprecisões. O usuário deve revisar fontes e resultados antes de uso pastoral, acadêmico, profissional ou público. O serviço não substitui orientação especializada."),
            ("Planos e pagamentos", "Eventuais preços, renovações, cancelamentos e reembolsos são apresentados no canal de contratação aplicável. Compras digitais no Android somente serão oferecidas por mecanismos permitidos pelo Google Play."),
            ("Disponibilidade", "Podem ocorrer manutenções, indisponibilidades de rede e mudanças em integrações de terceiros. Buscamos continuidade, mas não garantimos operação ininterrupta."),
            ("Privacidade e encerramento", "O tratamento de dados segue a Política de privacidade. Você pode encerrar a conta pelo aplicativo ou pelo canal de exclusão publicado."),
            ("Alterações", "Os termos podem ser atualizados quando o serviço mudar. O uso posterior à comunicação de mudanças relevantes representa aceitação da versão vigente, quando permitido por lei."),
        ],
    )


@app.get("/support", response_class=HTMLResponse, include_in_schema=False)
async def support_page():
    return public_information_page(
        "Suporte",
        "Para ajuda com cadastro, acesso, funcionamento, privacidade, assinatura ou exclusão, envie uma mensagem para aplicativo.magisteria@gmail.com.",
        [
            ("Como pedir ajuda", "Informe o e-mail da conta, a plataforma Android, uma descrição objetiva do problema e, se possível, a versão do aplicativo. Não envie senha, código de recuperação, token ou dados bancários."),
            ("Acesso e segurança", "Se suspeitar de acesso indevido, altere a senha assim que possível e descreva o ocorrido ao suporte."),
            ("Privacidade", "Solicitações relacionadas a dados pessoais podem ser feitas pelo mesmo e-mail e serão atendidas após validação razoável de identidade."),
        ],
    )


@app.get("/account-deletion", response_class=HTMLResponse, include_in_schema=False)
async def account_deletion_page():
    return public_information_page(
        "Exclusão de conta",
        "Usuários do MAGISTERIA podem solicitar a exclusão da conta e dos dados associados pelo aplicativo ou por e-mail.",
        [
            ("No aplicativo", "Abra Perfil, selecione Excluir conta, confirme sua senha e digite EXCLUIR. A conta é removida após a reautenticação e você retorna à tela de entrada."),
            ("Sem acesso ao aplicativo", "Envie um e-mail de aplicativo.magisteria@gmail.com com o assunto Solicitação de exclusão de conta MAGISTERIA e informe o e-mail cadastrado. Não envie sua senha. Poderemos solicitar uma confirmação razoável de identidade."),
            ("Dados excluídos", "São eliminados o cadastro, sessões, tokens móveis, franquias e demais registros diretamente vinculados à conta, salvo informações cuja retenção seja necessária por segurança, prevenção a fraude ou obrigação legal."),
            ("Assinaturas", "Se existir assinatura ativa contratada por outro canal, solicite também o cancelamento nesse canal antes de excluir a conta. A exclusão da conta não substitui automaticamente o cancelamento externo enquanto não houver integração de cobrança ativa no Android."),
            ("Prazo", "A exclusão confirmada dentro do aplicativo é processada imediatamente. Pedidos por e-mail são processados após validação de identidade e dentro dos prazos legais aplicáveis."),
        ],
    )


@app.get("/app-version")
async def public_app_version():
    return {"version": APP_VERSION, "platforms": ["web", "android", "ios"]}


def retrieval_query(payload: QuestionRequest) -> str:
    question = payload.pergunta.strip()
    if payload.historico and len(question.split()) <= 12:
        return f"{payload.historico[-1].pergunta} {question}"
    return question


def ordered_chunks(
    payload: QuestionRequest,
    query_override: str | None = None,
    plan: ResponsePlan | None = None,
) -> list[dict]:
    chunks, _ = ordered_chunks_with_diagnostics(payload, query_override, plan)
    return chunks


def ordered_chunks_with_diagnostics(
    payload: QuestionRequest,
    query_override: str | None = None,
    plan: ResponsePlan | None = None,
) -> tuple[list[dict], dict]:
    search_query = query_override or retrieval_query(payload)
    selected_plan = plan or build_response_plan(
        payload.pergunta,
        normalize_language(payload.idioma),
        payload.perfil,
    )
    bundle = retrieval_orchestrator.retrieve(
        search_query,
        selected_plan,
        minimum_score=settings.MIN_RELEVANCE_SCORE,
        excluded_sources=auth_repository.inactive_sources(),
    )
    diagnostics = bundle.diagnostics
    if settings.RAG_DEBUG:
        logger.info(
            "rag_retrieval=%s",
            json.dumps(
                {
                    "query": redact_query(payload.pergunta),
                    "type": diagnostics.get("query", {}).get("query_type"),
                    "depth": selected_plan.depth,
                    "components": len(selected_plan.active_components),
                    "candidate_counts": diagnostics.get("candidate_counts", {}),
                    "selected_count": len(diagnostics.get("selected_chunks", [])),
                    "cache_hit": bundle.cache_hit,
                },
                ensure_ascii=False,
                default=str,
            ),
        )
    return bundle.chunks, diagnostics


def retrieval_notice(chunks: list[dict], diagnostics: dict, language: str = "pt-BR") -> str:
    if not chunks:
        return ""
    query_type = diagnostics.get("query", {}).get("query_type")
    if query_type in {QueryType.TERM.value, QueryType.PHRASE.value}:
        return answer_message("broad_topic", language)
    reranking = diagnostics.get("reranking", [])
    best = max((float(item.get("score_normalized", 0)) for item in reranking), default=0)
    strong_lexical = any("lexical_exact" in item.get("strategies", []) for item in reranking[:5])
    if best < 0.25 and not strong_lexical:
        return answer_message("low_confidence", language)
    return ""


def estimated_context_tokens(chunks: list[dict]) -> int:
    return sum(max(len(str(chunk.get("text", ""))) // 4, 1) for chunk in chunks)


def estimated_model_cost(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * settings.OPENAI_INPUT_COST_PER_MILLION
        + output_tokens * settings.OPENAI_OUTPUT_COST_PER_MILLION
    ) / 1_000_000


def actually_used_chunks(chunks: list[dict], result: dict) -> list[dict]:
    indexes = {
        int(index) for index in result.get("used_source_indexes", [])
        if isinstance(index, int) or str(index).isdigit()
    }
    selected = [
        {**chunk, "citation_index": position}
        for position, chunk in enumerate(chunks, 1)
        if position in indexes
    ]
    return selected or [
        {**chunk, "citation_index": position}
        for position, chunk in enumerate(chunks, 1)
    ]


def response_metadata(plan: ResponsePlan, diagnostics: dict, result: dict) -> dict:
    remaining = list(plan.components[len(plan.active_components):])
    continuation_query = ""
    if remaining:
        continuation_query = (
            f"Continue o estudo de {plan.display_title}, detalhando agora: "
            + ", ".join(remaining[:10])
        )
    return {
        "plan": {
            "topic": plan.display_title,
            "category": plan.category,
            "depth": plan.depth,
            "composite": plan.composite,
            "components": list(plan.components),
            "covered_components": list(plan.active_components),
            "continuation_required": plan.continuation_required,
        },
        "suggestions": list(plan.suggestions),
        "continuation_query": continuation_query,
        "cache_hit": bool(diagnostics.get("cache_hit")),
        "coverage": result.get("coverage", {}),
    }


def homily_style_chunks(payload: QuestionRequest, query_override: str | None = None) -> list[dict]:
    chunks = vector_store.search(
        query_override or retrieval_query(payload),
        limit=3,
        minimum_score=0.02,
        source_filter=("joao-paulo-ii-homilias", "homilias"),
        excluded_sources=auth_repository.inactive_sources(),
    )
    if chunks:
        return chunks
    return vector_store.search(
        "Cristo Igreja Deus homem amor esperança fé",
        limit=3,
        minimum_score=0,
        source_filter=("joao-paulo-ii-homilias", "homilias"),
        excluded_sources=auth_repository.inactive_sources(),
    )


def public_document_names() -> list[str]:
    inactive = set(auth_repository.inactive_sources())
    names = [name for name in vector_store.document_names() if name not in inactive]
    consolidated: list[str] = []
    has_homilies = False
    for name in names:
        normalized = name.lower()
        if "joao-paulo-ii-homilias" in normalized or "homilia" in normalized:
            has_homilies = True
            continue
        consolidated.append(name)
    if has_homilies:
        consolidated.append("Homilias de São João Paulo II")
    return sorted(dict.fromkeys(consolidated), key=str.casefold)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"user": current_user(request), "app_version": APP_VERSION},
    )


@app.post("/perguntar")
async def ask(payload: QuestionRequest, request: Request):
    if indexing_state["ativa"]:
        raise HTTPException(status_code=503, detail="A base documental ainda está sendo atualizada.")
    user = current_user(request)
    allowed, message = auth_repository.reserve_usage(user["id"], "query")
    if not allowed:
        raise HTTPException(status_code=403, detail=message)
    question = payload.pergunta.strip()
    language = normalize_language(payload.idioma)
    plan = build_response_plan(question, language, payload.perfil)
    request_id = new_request_id()
    started = time.monotonic()
    try:
        search_query_pt = retrieval_query(payload)
        if language != "pt-BR":
            search_query_pt = await answer_service.translate_query_to_portuguese(
                search_query_pt, language
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=answer_message("technical_failure", language)) from exc
    except Exception as exc:
        logger.exception("Falha ao traduzir a consulta para recuperação em português.")
        raise HTTPException(status_code=502, detail=answer_message("technical_failure", language)) from exc
    chunks, diagnostics = await asyncio.to_thread(
        ordered_chunks_with_diagnostics, payload, search_query_pt, plan
    )
    if chunks:
        needs_homily_style = "pastoral" in plan.intents
        style_chunks = (
            await asyncio.to_thread(homily_style_chunks, payload, search_query_pt)
            if needs_homily_style and language != "pt-BR"
            else await asyncio.to_thread(homily_style_chunks, payload)
            if needs_homily_style
            else []
        )
    else:
        style_chunks = []
    history = [turn.model_dump() for turn in payload.historico]
    try:
        result = await answer_service.answer_with_review(
            question, chunks, history, style_chunks, language, plan
        )
    except RuntimeError as exc:
        await asyncio.to_thread(
            rag_diagnostics.record, request_id, question, diagnostics,
            round((time.monotonic() - started) * 1000), "technical_failure",
            error=str(exc), final_reason=TECHNICAL_FAILURE_MESSAGE,
            context_tokens=estimated_context_tokens(chunks),
            depth_level=plan.depth, topic_category=plan.category, component_count=len(plan.active_components),
            strategy_version=plan.strategy_version, retrieved_chunk_count=len(chunks),
            cache_hit=bool(diagnostics.get("cache_hit")),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        await asyncio.to_thread(
            rag_diagnostics.record, request_id, question, diagnostics,
            round((time.monotonic() - started) * 1000), "technical_failure",
            error=type(exc).__name__, final_reason=TECHNICAL_FAILURE_MESSAGE,
            context_tokens=estimated_context_tokens(chunks),
            depth_level=plan.depth, topic_category=plan.category, component_count=len(plan.active_components),
            strategy_version=plan.strategy_version, retrieved_chunk_count=len(chunks),
            cache_hit=bool(diagnostics.get("cache_hit")),
        )
        raise HTTPException(status_code=502, detail=answer_message("technical_failure", language)) from exc
    used_chunks = actually_used_chunks(chunks, result)
    await asyncio.to_thread(active_search_history().record, user["id"], question, plan)
    await asyncio.to_thread(
        rag_diagnostics.record, request_id, question, diagnostics,
        round((time.monotonic() - started) * 1000),
        "success" if chunks else "no_documents",
        validator={"decision": result["status_revisao"], "reason": result["motivo_revisao"]},
        final_reason=result["motivo_revisao"],
        context_tokens=estimated_context_tokens(chunks),
        estimated_cost=estimated_model_cost(
            result.get("input_tokens_estimated", 0), result.get("output_tokens_estimated", 0)
        ),
        depth_level=plan.depth,
        topic_category=plan.category,
        strategy_version=plan.strategy_version,
        component_count=len(plan.active_components),
        retrieved_chunk_count=len(chunks),
        input_tokens_estimated=result.get("input_tokens_estimated", 0),
        output_tokens_estimated=result.get("output_tokens_estimated", 0),
        cache_hit=bool(diagnostics.get("cache_hit")),
        coverage_failures=result.get("coverage", {}).get("failure_count", 0),
        citation_errors=len(result.get("coverage", {}).get("invalid_citations", [])),
        regenerated=bool(result.get("regenerated")),
    )
    return {
        "request_id": request_id,
        "resposta": result["resposta"],
        "status_revisao": result["status_revisao"],
        "motivo_revisao": result["motivo_revisao"],
        "mensagem_busca": retrieval_notice(chunks, diagnostics, language),
        "fontes": format_sources(used_chunks),
        "metadados": response_metadata(plan, diagnostics, result),
    }


@app.post("/perguntar-stream")
async def ask_stream(payload: QuestionRequest, request: Request):
    if indexing_state["ativa"]:
        raise HTTPException(status_code=503, detail="A base documental ainda está sendo atualizada.")
    user = current_user(request)
    allowed, message = auth_repository.reserve_usage(user["id"], "query")
    if not allowed:
        raise HTTPException(status_code=403, detail=message)

    question = payload.pergunta.strip()
    language = normalize_language(payload.idioma)
    plan = build_response_plan(question, language, payload.perfil)
    request_id = new_request_id()
    started = time.monotonic()
    try:
        search_query_pt = retrieval_query(payload)
        if language != "pt-BR":
            search_query_pt = await answer_service.translate_query_to_portuguese(
                search_query_pt, language
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=answer_message("technical_failure", language)) from exc
    except Exception as exc:
        logger.exception("Falha ao traduzir a consulta para recuperação em português.")
        raise HTTPException(status_code=502, detail=answer_message("technical_failure", language)) from exc
    chunks, diagnostics = await asyncio.to_thread(
        ordered_chunks_with_diagnostics, payload, search_query_pt, plan
    )
    if chunks:
        needs_homily_style = "pastoral" in plan.intents
        style_chunks = (
            await asyncio.to_thread(homily_style_chunks, payload, search_query_pt)
            if needs_homily_style and language != "pt-BR"
            else await asyncio.to_thread(homily_style_chunks, payload)
            if needs_homily_style
            else []
        )
    else:
        style_chunks = []
    history = [turn.model_dump() for turn in payload.historico]
    if chunks and not answer_service.api_key:
        raise HTTPException(status_code=503, detail="A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")
    async def events():
        yield json.dumps(
            {
                "tipo": "fontes",
                "request_id": request_id,
                "mensagem_busca": retrieval_notice(chunks, diagnostics, language),
                "fontes": format_sources(chunks),
                "referencias_abnt": format_abnt_references(chunks),
            },
            ensure_ascii=False,
        ) + "\n"
        try:
            result = await answer_service.answer_with_review(
                question, chunks, history, style_chunks, language, plan
            )
            used_chunks = actually_used_chunks(chunks, result)
            await asyncio.to_thread(active_search_history().record, user["id"], question, plan)
            await asyncio.to_thread(
                rag_diagnostics.record, request_id, question, diagnostics,
                round((time.monotonic() - started) * 1000),
                "success" if chunks else "no_documents",
                validator={"decision": result["status_revisao"], "reason": result["motivo_revisao"]},
                final_reason=result["motivo_revisao"],
                context_tokens=estimated_context_tokens(chunks),
                estimated_cost=estimated_model_cost(
                    result.get("input_tokens_estimated", 0), result.get("output_tokens_estimated", 0)
                ),
                depth_level=plan.depth,
                topic_category=plan.category,
                strategy_version=plan.strategy_version,
                component_count=len(plan.active_components),
                retrieved_chunk_count=len(chunks),
                input_tokens_estimated=result.get("input_tokens_estimated", 0),
                output_tokens_estimated=result.get("output_tokens_estimated", 0),
                cache_hit=bool(diagnostics.get("cache_hit")),
                coverage_failures=result.get("coverage", {}).get("failure_count", 0),
                citation_errors=len(result.get("coverage", {}).get("invalid_citations", [])),
                regenerated=bool(result.get("regenerated")),
            )
            yield json.dumps(
                {
                    "tipo": "fontes",
                    "request_id": request_id,
                    "mensagem_busca": retrieval_notice(used_chunks, diagnostics, language),
                    "fontes": format_sources(used_chunks),
                    "referencias_abnt": format_abnt_references(used_chunks),
                },
                ensure_ascii=False,
            ) + "\n"
            yield json.dumps(
                {
                    "tipo": "texto",
                    "texto": result["resposta"],
                    "status_revisao": result["status_revisao"],
                    "motivo_revisao": result["motivo_revisao"],
                },
                ensure_ascii=False,
            ) + "\n"
            yield json.dumps(
                {"tipo": "metadados", **response_metadata(plan, diagnostics, result)},
                ensure_ascii=False,
            ) + "\n"
            yield json.dumps({"tipo": "fim"}) + "\n"
        except asyncio.CancelledError:
            logger.info("Transmissão cancelada pelo navegador.")
            raise
        except Exception:
            logger.exception("Falha durante a geração da resposta em fluxo.")
            await asyncio.to_thread(
                rag_diagnostics.record, request_id, question, diagnostics,
                round((time.monotonic() - started) * 1000), "technical_failure",
                error="answer_generation_failure", final_reason=TECHNICAL_FAILURE_MESSAGE,
                context_tokens=estimated_context_tokens(chunks),
                depth_level=plan.depth, topic_category=plan.category, component_count=len(plan.active_components),
                strategy_version=plan.strategy_version, retrieved_chunk_count=len(chunks),
                cache_hit=bool(diagnostics.get("cache_hit")),
            )
            yield json.dumps(
                {"tipo": "erro", "mensagem": answer_message("technical_failure", language)},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/api/v1/ask")
async def mobile_ask(payload: QuestionRequest, request: Request):
    return await ask(payload, request)


@app.post("/api/v1/ask-stream")
async def mobile_ask_stream(payload: QuestionRequest, request: Request):
    return await ask_stream(payload, request)


@app.post("/indexar")
async def index_documents(request: Request):
    require_admin(request)
    if index_lock.locked():
        raise HTTPException(status_code=409, detail="A base documental já está sendo atualizada.")
    status = await perform_indexing()
    return {"mensagem": "Base documental atualizada com sucesso.", "status": status}


@app.post("/criar-roteiro")
async def create_script(payload: PresentationRequest, request: Request):
    user = current_user(request)
    allowed, message = auth_repository.reserve_usage(user["id"], "script")
    if not allowed:
        raise HTTPException(status_code=403, detail=message)
    try:
        if payload.idioma == "pt-BR":
            topics = await presentation_service.create_outline(payload.titulo, payload.resposta)
            content = await asyncio.to_thread(presentation_service.create_docx, payload.titulo, topics)
        else:
            topics = await presentation_service.create_outline(payload.titulo, payload.resposta, payload.idioma)
            content = await asyncio.to_thread(
                presentation_service.create_docx, payload.titulo, topics, payload.idioma
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao criar roteiro.")
        raise HTTPException(status_code=502, detail="Não foi possível criar o roteiro agora.") from exc
    filename = safe_filename(payload.titulo, "roteiro.docx")
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/criar-slides")
async def create_slides(payload: PresentationRequest, request: Request):
    user = current_user(request)
    allowed, message = auth_repository.reserve_usage(user["id"], "presentation")
    if not allowed:
        raise HTTPException(status_code=403, detail=message)
    try:
        if payload.idioma == "pt-BR":
            plan = await presentation_service.create_plan(payload.titulo, payload.resposta)
            content = await presentation_service.create_pptx(
                payload.titulo,
                plan["topicos"],
                plan["titulo_curto"],
                plan["frase_final"],
            )
        else:
            plan = await presentation_service.create_plan(payload.titulo, payload.resposta, payload.idioma)
            content = await presentation_service.create_pptx(
                payload.titulo,
                plan["topicos"],
                plan["titulo_curto"],
                plan["frase_final"],
                payload.idioma,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao criar apresentação.")
        raise HTTPException(status_code=502, detail="Não foi possível criar os slides com imagens agora.") from exc
    filename = safe_filename(payload.titulo, "slides.pptx")
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/status")
async def status():
    return {**vector_store.status(), "indexacao": {key: value for key, value in indexing_state.items() if key != "inicio"}}


@app.get("/health", include_in_schema=False)
async def health():
    """Health check leve para o Railway; independe da indexacao e da OpenAI."""
    return {"status": "ok", "versao": APP_VERSION}


@app.get("/documentos")
async def documents():
    return {"documentos": public_document_names()}


@app.get("/api/v1/documents")
async def mobile_documents():
    return {"documents": public_document_names()}


@app.get("/admin/estatisticas")
async def admin_statistics(request: Request):
    require_admin(request)
    return {"usuarios": auth_repository.list_users()}


@app.get("/admin/cupons")
async def admin_coupons(request: Request):
    require_admin(request)
    return {"cupons": auth_repository.list_coupons()}


@app.post("/admin/cupons")
async def admin_create_coupon(payload: dict, request: Request):
    admin = require_admin(request)
    try:
        coupon = auth_repository.create_coupon(
            str(payload.get("cupom") or ""),
            str(payload.get("validade") or ""),
            admin["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"mensagem": "Cupom criado com sucesso.", "cupom": coupon}


@app.post("/admin/assinatura/revogar-cupom")
async def admin_revoke_coupon_access(payload: dict, request: Request):
    admin = require_admin(request)
    try:
        user_id = int(payload.get("usuario_id"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Usuário inválido.") from exc
    try:
        updated = auth_repository.revoke_coupon_access(user_id, admin["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "mensagem": "Acesso completo concedido por cupom revogado.",
        "usuario": subscription_summary(updated),
    }


@app.post("/admin/assinatura/controle-gratuito")
async def admin_free_access_control(payload: dict, request: Request):
    require_admin(request)
    allow_free_access = bool(payload.get("permitir", True))
    auth_repository.set_free_access_review(allow_free_access)
    return {"mensagem": "Controle da modalidade gratuita atualizado.", "permitir": allow_free_access}


@app.get("/admin/base-documental")
async def admin_document_base(request: Request):
    require_admin(request)
    return {"documentos": auth_repository.list_documents()}


@app.get("/admin/rag/diagnosticos")
async def admin_rag_diagnostics(request: Request, limit: int = 100):
    require_admin(request)
    return {"consultas": await asyncio.to_thread(rag_diagnostics.recent, limit)}


@app.get("/admin/rag/metricas")
async def admin_rag_metrics(request: Request, days: int = 30):
    require_admin(request)
    return await asyncio.to_thread(rag_diagnostics.aggregate, days)


@app.post("/admin/rag/repetir")
async def admin_repeat_rag(payload: dict, request: Request):
    require_admin(request)
    question = str(payload.get("pergunta") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Informe a consulta que deve ser repetida.")
    query_payload = QuestionRequest(pergunta=question)
    started = time.monotonic()
    chunks, diagnostics = await asyncio.to_thread(ordered_chunks_with_diagnostics, query_payload)
    return {
        "tempo_ms": round((time.monotonic() - started) * 1000),
        "fontes": format_sources(chunks),
        "diagnostico": diagnostics,
        "mensagem_busca": retrieval_notice(chunks, diagnostics),
        "cobrou_franquia": False,
    }


def safe_document_path(encoded_path: str) -> Path:
    relative = unquote(encoded_path).replace("\\", "/").strip("/")
    candidate = (settings.DOCUMENTS_DIR / relative).resolve()
    base = settings.DOCUMENTS_DIR.resolve()
    if not relative or candidate == base or base not in candidate.parents:
        raise HTTPException(status_code=400, detail="Caminho de documento invalido.")
    if candidate.suffix.lower() not in {".pdf", ".docx", ".txt", ".md", ".markdown"}:
        raise HTTPException(status_code=400, detail="Tipo de arquivo nao permitido.")
    return candidate


@app.post("/admin/upload-chunk")
async def upload_document_chunk(request: Request):
    require_admin(request)
    filename = request.headers.get("X-Path") or request.headers.get("X-Filename", "")
    target = safe_document_path(filename)
    try:
        offset = int(request.headers.get("X-Offset", "0"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Offset invalido.") from exc
    if offset < 0:
        raise HTTPException(status_code=400, detail="Offset invalido.")
    content = await request.body()
    if len(content) > settings.MAX_UPLOAD_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="Parte do arquivo excede o limite permitido.")
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "r+b" if target.exists() else "wb"
    with target.open(mode) as output:
        output.seek(offset)
        output.write(content)
        output.truncate(offset + len(content))
    return {
        "arquivo": target.relative_to(settings.DOCUMENTS_DIR).as_posix(),
        "bytes": offset + len(content),
        "completo": request.headers.get("X-Complete") == "1",
    }


@app.post("/admin/base-documental/desativar")
async def deactivate_document(payload: dict, request: Request):
    require_admin(request)
    source = str(payload.get("source", "")).strip()
    if not source:
        raise HTTPException(status_code=400, detail="Documento invalido.")
    auth_repository.set_document_active(source, False)
    await asyncio.to_thread(semantic_cache.invalidate_all)
    return {"mensagem": "Documento desativado para novas consultas."}


@app.post("/admin/base-documental/ativar")
async def activate_document(payload: dict, request: Request):
    require_admin(request)
    source = str(payload.get("source", "")).strip()
    if not source:
        raise HTTPException(status_code=400, detail="Documento invalido.")
    auth_repository.set_document_active(source, True)
    await asyncio.to_thread(semantic_cache.invalidate_all)
    return {"mensagem": "Documento ativado para novas consultas."}


@app.post("/admin/base-documental/reindexar")
async def reindex_document_base(request: Request):
    require_admin(request)
    if index_lock.locked():
        raise HTTPException(status_code=409, detail="A base documental ja esta sendo atualizada.")
    status = await perform_indexing()
    return {"mensagem": "Base documental reindexada.", "status": status}


@app.post("/admin/base-documental/limpar")
async def clear_document_base(request: Request):
    require_admin(request)
    if index_lock.locked():
        raise HTTPException(status_code=409, detail="A base documental ja esta sendo atualizada.")
    extensions = {".pdf", ".docx", ".txt", ".md", ".markdown"}
    removed: list[str] = []
    for path in settings.DOCUMENTS_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            removed.append(path.relative_to(settings.DOCUMENTS_DIR).as_posix())
            path.unlink()
    status = await perform_indexing()
    return {"mensagem": "Base documental limpa.", "removidos": removed, "status": status}


@app.get("/versao")
async def version():
    return {"versao": APP_VERSION}
