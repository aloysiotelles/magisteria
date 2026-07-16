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
from services.localization import LanguageCode, answer_message, normalize_language
from services.presentation_service import PresentationService, safe_filename
from services.asaas_service import AsaasError, AsaasService
from services.mercado_pago_service import MercadoPagoError, MercadoPagoService
from services.vector_store import LocalVectorStore
from services.query_analysis import QueryType, analyze_query
from services.rag_diagnostics import RAGDiagnosticsRepository, new_request_id, redact_query
from services.subscription_service import SubscriptionService

APP_VERSION = "0.8.0"
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
    "/api/v1/mobile/auth/login": (20, 300),
    "/api/v1/mobile/auth/register": (10, 300),
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
    "/webhooks/mercadopago",
    "/webhooks/asaas",
    "/api/v1/mobile/auth/login",
    "/api/v1/mobile/auth/register",
    "/api/v1/mobile/auth/refresh",
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
async def login_page(erro: str = "", cadastrado: str = ""):
    message = "Login ou senha incorretos." if erro else ("Cadastro criado. Entre para continuar." if cadastrado else "")
    fields = """
<input type="text" name="email" placeholder="Email ou Admin" required autofocus>
<input type="password" name="senha" placeholder="Senha" required>
"""
    return auth_page("Entrar", "Acesse com email e senha.", "/login", fields, 'Ainda nao tem conta? <a href="/cadastro">Criar cadastro</a>.', message, bool(erro))


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


@app.post("/logout", include_in_schema=False)
async def logout(request: Request):
    auth_repository.delete_session(request.cookies.get(AUTH_COOKIE, ""))
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE, secure=settings.COOKIE_SECURE, samesite="lax")
    return response


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
async def login_page(erro: str = "", cadastrado: str = ""):
    message = "Login ou senha incorretos." if erro else ("Cadastro criado. Entre para continuar." if cadastrado else "")
    fields = """
<input type="text" name="email" placeholder="Email ou Admin" required autofocus>
<input type="password" name="senha" placeholder="Senha" required>
"""
    return auth_page("Entrar", "Acesse com email e senha.", "/login", fields, 'Ainda nao tem conta? <a href="/cadastro">Criar cadastro</a>.', message, bool(erro))


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


class AccountDeletionRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    confirmation: str = Field(min_length=1, max_length=40)


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
    entitlement = subscription_service.snapshot(user, str(order["provider"] if order else ""))
    return {
        "entitlement": entitlement.to_dict(),
        "store_products_configured": subscription_service.store_products_configured,
    }


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


def provisional_page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">
        <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
        <title>{html.escape(title)} - MAGISTERIA</title></head>
        <body><main><h1>{html.escape(title)}</h1><p><strong>Texto provisÃ³rio sujeito a revisÃ£o jurÃ­dica.</strong></p>
        <p>{html.escape(body)}</p><p>Contato provisÃ³rio: suporte a definir pelo proprietÃ¡rio.</p></main></body></html>"""
    )


@app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_page():
    return provisional_page("PolÃ­tica de privacidade", "Descreve dados de conta, consultas, documentos e pagamentos tratados para operar o serviÃ§o.")


@app.get("/terms", response_class=HTMLResponse, include_in_schema=False)
async def terms_page():
    return provisional_page("Termos de uso", "Define provisoriamente as condiÃ§Ãµes de acesso, limites de uso e responsabilidades do serviÃ§o.")


@app.get("/support", response_class=HTMLResponse, include_in_schema=False)
async def support_page():
    return provisional_page("Suporte", "Canal pÃºblico provisÃ³rio para ajuda com acesso, assinatura, privacidade e exclusÃ£o de conta.")


@app.get("/account-deletion", response_class=HTMLResponse, include_in_schema=False)
async def account_deletion_page():
    return provisional_page("ExclusÃ£o de conta", "A exclusÃ£o estÃ¡ disponÃ­vel dentro do aplicativo em Perfil e remove a conta apÃ³s reautenticaÃ§Ã£o.")


@app.get("/app-version")
async def public_app_version():
    return {"version": APP_VERSION, "platforms": ["web", "android", "ios"]}


def retrieval_query(payload: QuestionRequest) -> str:
    question = payload.pergunta.strip()
    if payload.historico and len(question.split()) <= 12:
        return f"{payload.historico[-1].pergunta} {question}"
    return question


def ordered_chunks(payload: QuestionRequest, query_override: str | None = None) -> list[dict]:
    return vector_store.search_ordered(
        query_override or retrieval_query(payload),
        limit=max(settings.MAX_CONTEXT_CHUNKS, 16),
        minimum_score=settings.MIN_RELEVANCE_SCORE,
        excluded_sources=auth_repository.inactive_sources(),
    )


def ordered_chunks_with_diagnostics(
    payload: QuestionRequest,
    query_override: str | None = None,
) -> tuple[list[dict], dict]:
    search_query = query_override or retrieval_query(payload)
    result = vector_store.search_ordered(
        search_query,
        limit=max(settings.MAX_CONTEXT_CHUNKS, 16),
        minimum_score=settings.MIN_RELEVANCE_SCORE,
        excluded_sources=auth_repository.inactive_sources(),
        include_diagnostics=True,
    )
    if isinstance(result, tuple):
        chunks, diagnostics = result
        if settings.RAG_DEBUG:
            logger.info(
                "rag_retrieval=%s",
                json.dumps(
                    {
                        "query": redact_query(payload.pergunta),
                        "type": diagnostics.get("query", {}).get("query_type"),
                        "candidate_counts": diagnostics.get("candidate_counts", {}),
                        "selected_count": len(diagnostics.get("selected_chunks", [])),
                        "threshold_policy": diagnostics.get("threshold_policy"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
        return chunks, diagnostics
    analysis = analyze_query(search_query)
    return result, {
        "query": analysis.to_dict(),
        "candidate_counts": {},
        "candidates_fused": len(result),
        "reranking": [],
        "selected_chunks": [],
        "final_count": len(result),
    }


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
        ordered_chunks_with_diagnostics, payload, search_query_pt
    )
    if chunks:
        style_chunks = await asyncio.to_thread(
            homily_style_chunks, payload, search_query_pt
        ) if language != "pt-BR" else await asyncio.to_thread(homily_style_chunks, payload)
    else:
        style_chunks = []
    history = [turn.model_dump() for turn in payload.historico]
    try:
        result = await answer_service.answer_with_review(
            question, chunks, history, style_chunks, language
        )
    except RuntimeError as exc:
        await asyncio.to_thread(
            rag_diagnostics.record, request_id, question, diagnostics,
            round((time.monotonic() - started) * 1000), "technical_failure",
            error=str(exc), final_reason=TECHNICAL_FAILURE_MESSAGE,
            context_tokens=estimated_context_tokens(chunks),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        await asyncio.to_thread(
            rag_diagnostics.record, request_id, question, diagnostics,
            round((time.monotonic() - started) * 1000), "technical_failure",
            error=type(exc).__name__, final_reason=TECHNICAL_FAILURE_MESSAGE,
            context_tokens=estimated_context_tokens(chunks),
        )
        raise HTTPException(status_code=502, detail=answer_message("technical_failure", language)) from exc
    await asyncio.to_thread(
        rag_diagnostics.record, request_id, question, diagnostics,
        round((time.monotonic() - started) * 1000),
        "success" if chunks else "no_documents",
        validator={"decision": result["status_revisao"], "reason": result["motivo_revisao"]},
        final_reason=result["motivo_revisao"],
        context_tokens=estimated_context_tokens(chunks),
    )
    return {
        "request_id": request_id,
        "resposta": result["resposta"],
        "status_revisao": result["status_revisao"],
        "motivo_revisao": result["motivo_revisao"],
        "mensagem_busca": retrieval_notice(chunks, diagnostics, language),
        "fontes": format_sources(chunks),
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
        ordered_chunks_with_diagnostics, payload, search_query_pt
    )
    if chunks:
        style_chunks = await asyncio.to_thread(
            homily_style_chunks, payload, search_query_pt
        ) if language != "pt-BR" else await asyncio.to_thread(homily_style_chunks, payload)
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
                question, chunks, history, style_chunks, language
            )
            await asyncio.to_thread(
                rag_diagnostics.record, request_id, question, diagnostics,
                round((time.monotonic() - started) * 1000),
                "success" if chunks else "no_documents",
                validator={"decision": result["status_revisao"], "reason": result["motivo_revisao"]},
                final_reason=result["motivo_revisao"],
                context_tokens=estimated_context_tokens(chunks),
            )
            yield json.dumps(
                {
                    "tipo": "texto",
                    "texto": result["resposta"],
                    "status_revisao": result["status_revisao"],
                    "motivo_revisao": result["motivo_revisao"],
                },
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
    return {"mensagem": "Documento desativado para novas consultas."}


@app.post("/admin/base-documental/ativar")
async def activate_document(payload: dict, request: Request):
    require_admin(request)
    source = str(payload.get("source", "")).strip()
    if not source:
        raise HTTPException(status_code=400, detail="Documento invalido.")
    auth_repository.set_document_active(source, True)
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
