from __future__ import annotations

from datetime import date
from decimal import Decimal
import hmac
import logging
from urllib.parse import quote, urljoin

import httpx


logger = logging.getLogger(__name__)


class AsaasError(RuntimeError):
    """Falha segura e apresentavel na integracao com o Asaas."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class AsaasService:
    SANDBOX_URL = "https://api-sandbox.asaas.com/v3"
    PRODUCTION_URL = "https://api.asaas.com/v3"

    def __init__(
        self,
        api_key: str,
        webhook_token: str,
        price: Decimal,
        public_url: str,
        api_base_url: str = SANDBOX_URL,
        billing_type: str = "UNDEFINED",
        enable_callback: bool = True,
        *,
        timeout_seconds: float = 4,
    ) -> None:
        self.api_key = api_key.strip()
        self.webhook_token = webhook_token.strip()
        self.price = price
        self.currency = "BRL"
        self.public_url = public_url.strip().rstrip("/")
        self.api_base_url = api_base_url.strip().rstrip("/") or self.SANDBOX_URL
        self.billing_type = billing_type.strip().upper() or "UNDEFINED"
        self.enable_callback = enable_callback
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(
            self.api_key
            and self.webhook_token
            and self.public_url.startswith("https://")
            and self.price > 0
            and self.billing_type in {"UNDEFINED", "BOLETO", "CREDIT_CARD", "PIX"}
            and self.api_base_url in {self.SANDBOX_URL, self.PRODUCTION_URL}
        )

    @property
    def sandbox(self) -> bool:
        return self.api_base_url == self.SANDBOX_URL

    def _headers(self) -> dict[str, str]:
        return {
            "access_token": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "MagisterIA/0.6 (assinaturas; suporte@magisteria.app)",
        }

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self.api_key:
            raise AsaasError("O Asaas ainda nao foi configurado.")
        try:
            async with httpx.AsyncClient(
                base_url=self.api_base_url,
                headers=self._headers(),
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            logger.warning("Falha de rede ao consultar o Asaas: %s", exc)
            raise AsaasError("O Asaas esta temporariamente indisponivel.") from exc

        if response.status_code >= 400:
            request_id = response.headers.get("asaas-request-id") or response.headers.get("x-request-id", "")
            logger.warning(
                "Asaas respondeu HTTP %s (request_id=%s): %.800s",
                response.status_code,
                request_id,
                response.text,
            )
            if response.status_code in {401, 403}:
                raise AsaasError("As credenciais do Asaas precisam ser revisadas.")
            if response.status_code == 404:
                raise AsaasError("O recurso informado nao foi encontrado no Asaas.", status_code=404)
            detail = self._safe_error_detail(response)
            raise AsaasError(detail or "O Asaas nao conseguiu processar a solicitacao agora.", status_code=400 if response.status_code == 400 else 502)
        try:
            data = response.json()
        except ValueError as exc:
            raise AsaasError("O Asaas devolveu uma resposta invalida.") from exc
        if not isinstance(data, dict):
            raise AsaasError("O Asaas devolveu uma resposta invalida.")
        return data

    @staticmethod
    def _safe_error_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        errors = data.get("errors") if isinstance(data, dict) else None
        if not isinstance(errors, list):
            return ""
        messages = [str(item.get("description") or "").strip() for item in errors if isinstance(item, dict)]
        messages = [message for message in messages if message]
        return " ".join(messages)[:500]

    async def get_or_create_customer(self, user: dict) -> dict:
        user_id = str(user.get("id") or "").strip()
        full_name = str(user.get("full_name") or "").strip()
        email = str(user.get("email") or "").strip()
        if not user_id or not full_name or not email:
            raise AsaasError("Nome e e-mail do cadastro sao necessarios para criar a assinatura.", status_code=400)
        external_reference = f"magisteria-user-{user_id}"
        result = await self._request(
            "GET",
            "/customers",
            params={"externalReference": external_reference, "limit": 1},
        )
        customers = result.get("data") if isinstance(result.get("data"), list) else []
        if customers and isinstance(customers[0], dict) and customers[0].get("id"):
            return customers[0]
        return await self._request(
            "POST",
            "/customers",
            json={
                "name": full_name,
                "email": email,
                "externalReference": external_reference,
                "notificationDisabled": False,
            },
        )

    async def create_subscription(self, customer_id: str, external_reference: str) -> dict:
        if not self.configured:
            raise AsaasError("O pagamento ainda nao foi configurado pelo administrador.")
        customer_id = self._validated_identifier(customer_id, "cliente")
        callback_url = urljoin(f"{self.public_url}/", "assinatura/retorno")
        payload = {
            "customer": customer_id,
            "billingType": self.billing_type,
            "value": float(self.price),
            "nextDueDate": date.today().isoformat(),
            "cycle": "MONTHLY",
            "description": "MAGISTERIA - assinatura mensal",
            "externalReference": external_reference,
        }
        if self.enable_callback:
            payload["callback"] = {"successUrl": callback_url, "autoRedirect": True}
        subscription = await self._request(
            "POST",
            "/subscriptions",
            json=payload,
        )
        subscription_id = str(subscription.get("id") or "").strip()
        if not subscription_id:
            raise AsaasError("O Asaas nao devolveu o identificador da assinatura.")
        payment = await self.get_first_subscription_payment(subscription_id)
        checkout_url = str(payment.get("invoiceUrl") or "").strip()
        if not checkout_url.startswith("https://"):
            raise AsaasError("O Asaas nao devolveu um link de pagamento valido.")
        return {
            "id": subscription_id,
            "checkout_url": checkout_url,
            "payment_id": str(payment.get("id") or "").strip(),
            "external_reference": external_reference,
        }

    async def get_first_subscription_payment(self, subscription_id: str) -> dict:
        subscription_id = self._validated_identifier(subscription_id, "assinatura")
        result = await self._request(
            "GET",
            f"/subscriptions/{quote(subscription_id, safe='')}/payments",
            params={"limit": 1, "offset": 0},
        )
        payments = result.get("data") if isinstance(result.get("data"), list) else []
        if not payments or not isinstance(payments[0], dict):
            raise AsaasError("O Asaas ainda nao gerou a primeira cobranca da assinatura.")
        return payments[0]

    async def get_payment(self, payment_id: str) -> dict:
        payment_id = self._validated_identifier(payment_id, "pagamento")
        return await self._request("GET", f"/payments/{quote(payment_id, safe='')}")

    async def get_subscription(self, subscription_id: str) -> dict:
        subscription_id = self._validated_identifier(subscription_id, "assinatura")
        return await self._request("GET", f"/subscriptions/{quote(subscription_id, safe='')}")

    def validate_webhook_token(self, received_token: str | None) -> bool:
        if not self.webhook_token or not received_token:
            return False
        return hmac.compare_digest(self.webhook_token, received_token.strip())

    @staticmethod
    def _validated_identifier(value: str, label: str) -> str:
        value = str(value).strip()
        if not value or len(value) > 100 or not value.replace("-", "").replace("_", "").isalnum():
            raise AsaasError(f"Identificador de {label} invalido.", status_code=400)
        return value
