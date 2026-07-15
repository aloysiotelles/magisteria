from __future__ import annotations

import asyncio
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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from config import BASE_DIR, settings
from services.answer_service import AnswerService, format_abnt_references, format_sources
from services.auth_repository import AuthRepository
from services.presentation_service import PresentationService, safe_filename
from services.asaas_service import AsaasError, AsaasService
from services.mercado_pago_service import MercadoPagoError, MercadoPagoService
from services.vector_store import LocalVectorStore

APP_VERSION = "0.6.2"
logger = logging.getLogger(__name__)

vector_store = LocalVectorStore(
    settings.DOCUMENTS_DIR,
    settings.INDEX_FILE,
    settings.CHUNK_SIZE,
    settings.CHUNK_OVERLAP,
)
answer_service = AnswerService(settings.OPENAI_API_KEY, settings.OPENAI_MODEL, settings.OPENAI_REVIEW_MODEL)
auth_repository = AuthRepository(settings.APP_DATABASE_FILE)
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

AUTH_COOKIE = "magisteria_session"
PUBLIC_PATHS = {
    "/health",
    "/status",
    "/versao",
    "/login",
    "/cadastro",
    "/webhooks/mercadopago",
    "/webhooks/asaas",
}
PUBLIC_PREFIXES = ("/static/",)
FREE_CUPON_CODES = {code.strip() for code in os.getenv("FREE_ACCESS_COUPONS", "").split(",") if code.strip()}


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
    response.set_cookie(AUTH_COOKIE, auth_repository.create_session(user["id"]), max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
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
    response.delete_cookie(AUTH_COOKIE)
    return response


@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return await call_next(request)
    user = auth_repository.get_user_by_session(request.cookies.get(AUTH_COOKIE, ""))
    if user:
        request.state.user = user
        if path.startswith("/admin") and user["role"] != "admin":
            return JSONResponse({"detail": "Acesso administrativo restrito."}, status_code=403)
        return await call_next(request)
    if request.method == "GET":
        return RedirectResponse(url="/login", status_code=303)
    return JSONResponse({"detail": "Autenticacao necessaria."}, status_code=401)


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
    response.set_cookie(AUTH_COOKIE, auth_repository.create_session(user["id"]), max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
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
    response.delete_cookie(AUTH_COOKIE)
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
    code = str(payload.get("cupom", "")).strip()
    if not code:
        raise HTTPException(status_code=400, detail="Informe o cupom.")
    if not FREE_CUPON_CODES:
        raise HTTPException(status_code=503, detail="Nenhum cupom está configurado.")
    if code not in FREE_CUPON_CODES:
        raise HTTPException(status_code=400, detail="Cupom inválido.")
    auth_repository.apply_coupon_access(user["id"], code)
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
    pergunta: str = Field(min_length=3, max_length=2000)
    historico: list[ConversationTurn] = Field(default_factory=list, max_length=6)


class PasswordChangeRequest(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=200)
    nova_senha: str = Field(min_length=8, max_length=200)
    confirmar_senha: str = Field(min_length=8, max_length=200)


class PresentationRequest(BaseModel):
    titulo: str = Field(min_length=3, max_length=300)
    resposta: str = Field(min_length=20, max_length=16000)


def retrieval_query(payload: QuestionRequest) -> str:
    question = payload.pergunta.strip()
    if payload.historico and len(question.split()) <= 12:
        return f"{payload.historico[-1].pergunta} {question}"
    return question


def ordered_chunks(payload: QuestionRequest) -> list[dict]:
    return vector_store.search_ordered(
        retrieval_query(payload),
        limit=max(settings.MAX_CONTEXT_CHUNKS, 16),
        minimum_score=settings.MIN_RELEVANCE_SCORE,
        excluded_sources=auth_repository.inactive_sources(),
    )


def homily_style_chunks(payload: QuestionRequest) -> list[dict]:
    chunks = vector_store.search(
        retrieval_query(payload),
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
    allowed, message = auth_repository.can_use_query(user)
    if not allowed:
        raise HTTPException(status_code=403, detail=message)
    question = payload.pergunta.strip()
    chunks = await asyncio.to_thread(ordered_chunks, payload)
    style_chunks = await asyncio.to_thread(homily_style_chunks, payload) if chunks else []
    history = [turn.model_dump() for turn in payload.historico]
    try:
        result = await answer_service.answer_with_review(question, chunks, history, style_chunks)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Não foi possível consultar o serviço de IA agora.") from exc
    auth_repository.increment_usage(user["id"], "query")
    return {
        "resposta": result["resposta"],
        "status_revisao": result["status_revisao"],
        "motivo_revisao": result["motivo_revisao"],
        "fontes": format_sources(chunks),
    }


@app.post("/perguntar-stream")
async def ask_stream(payload: QuestionRequest, request: Request):
    if indexing_state["ativa"]:
        raise HTTPException(status_code=503, detail="A base documental ainda está sendo atualizada.")
    user = current_user(request)
    allowed, message = auth_repository.can_use_query(user)
    if not allowed:
        raise HTTPException(status_code=403, detail=message)

    question = payload.pergunta.strip()
    chunks = await asyncio.to_thread(ordered_chunks, payload)
    style_chunks = await asyncio.to_thread(homily_style_chunks, payload) if chunks else []
    history = [turn.model_dump() for turn in payload.historico]
    if chunks and not answer_service.api_key:
        raise HTTPException(status_code=503, detail="A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")
    auth_repository.increment_usage(user["id"], "query")
    async def events():
        yield json.dumps(
            {
                "tipo": "fontes",
                "fontes": format_sources(chunks),
                "referencias_abnt": format_abnt_references(chunks),
            },
            ensure_ascii=False,
        ) + "\n"
        try:
            result = await answer_service.answer_with_review(question, chunks, history, style_chunks)
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
            yield json.dumps(
                {"tipo": "erro", "mensagem": "Não foi possível consultar o serviço de IA agora."},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/indexar")
async def index_documents():
    if index_lock.locked():
        raise HTTPException(status_code=409, detail="A base documental já está sendo atualizada.")
    status = await perform_indexing()
    return {"mensagem": "Base documental atualizada com sucesso.", "status": status}


@app.post("/criar-roteiro")
async def create_script(payload: PresentationRequest, request: Request):
    user = current_user(request)
    allowed, message = auth_repository.can_generate_presentation(user, "script")
    if not allowed:
        raise HTTPException(status_code=403, detail=message)
    try:
        topics = await presentation_service.create_outline(payload.titulo, payload.resposta)
        content = await asyncio.to_thread(presentation_service.create_docx, payload.titulo, topics)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao criar roteiro.")
        raise HTTPException(status_code=502, detail="Não foi possível criar o roteiro agora.") from exc
    auth_repository.increment_usage(user["id"], "script")
    filename = safe_filename(payload.titulo, "roteiro.docx")
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/criar-slides")
async def create_slides(payload: PresentationRequest, request: Request):
    user = current_user(request)
    allowed, message = auth_repository.can_generate_presentation(user, "presentation")
    if not allowed:
        raise HTTPException(status_code=403, detail=message)
    try:
        plan = await presentation_service.create_plan(payload.titulo, payload.resposta)
        content = await presentation_service.create_pptx(
            payload.titulo,
            plan["topicos"],
            plan["titulo_curto"],
            plan["frase_final"],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha ao criar apresentação.")
        raise HTTPException(status_code=502, detail="Não foi possível criar os slides com imagens agora.") from exc
    auth_repository.increment_usage(user["id"], "presentation")
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


@app.get("/admin/estatisticas")
async def admin_statistics(request: Request):
    require_admin(request)
    return {"usuarios": auth_repository.list_users()}


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
