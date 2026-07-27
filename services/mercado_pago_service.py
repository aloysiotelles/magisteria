from __future__ import annotations

from decimal import Decimal
import hashlib
import hmac
import logging
from urllib.parse import quote, urljoin

import httpx


logger = logging.getLogger(__name__)


class MercadoPagoError(RuntimeError):
    """Falha segura e apresentavel na integracao com o Mercado Pago."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class MercadoPagoService:
    API_BASE_URL = "https://api.mercadopago.com"

    def __init__(
        self,
        access_token: str,
        webhook_secret: str,
        price: Decimal,
        currency: str,
        public_url: str,
        *,
        timeout_seconds: float = 12,
    ) -> None:
        self.access_token = access_token.strip()
        self.webhook_secret = webhook_secret.strip()
        self.price = price
        self.currency = currency.strip().upper() or "BRL"
        self.public_url = public_url.strip().rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._collector_email: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.webhook_secret and self.public_url and self.price > 0)

    @property
    def webhook_signature_configured(self) -> bool:
        return bool(self.webhook_secret)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self.access_token:
            raise MercadoPagoError("O Mercado Pago ainda nao foi configurado.")
        try:
            async with httpx.AsyncClient(
                base_url=self.API_BASE_URL,
                headers=self._headers(),
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            logger.warning("Falha de rede ao consultar o Mercado Pago: %s", exc)
            raise MercadoPagoError("O Mercado Pago esta temporariamente indisponivel.") from exc

        if response.status_code >= 400:
            request_id = response.headers.get("x-request-id", "")
            logger.warning(
                "Mercado Pago respondeu HTTP %s (request_id=%s): %.500s",
                response.status_code,
                request_id,
                response.text,
            )
            if response.status_code in {401, 403}:
                raise MercadoPagoError("As credenciais do Mercado Pago precisam ser revisadas.")
            if response.status_code == 404:
                raise MercadoPagoError("O pagamento informado nao foi encontrado no Mercado Pago.")
            if (
                response.status_code == 400
                and "payer and collector cannot be the same user" in response.text.lower()
            ):
                raise MercadoPagoError(
                    "Nao e possivel assinar usando a mesma conta do Mercado Pago que recebe os pagamentos. "
                    "Entre com outra conta para concluir a assinatura.",
                    status_code=400,
                )
            raise MercadoPagoError("O Mercado Pago nao conseguiu processar a solicitacao agora.")
        try:
            data = response.json()
        except ValueError as exc:
            raise MercadoPagoError("O Mercado Pago devolveu uma resposta invalida.") from exc
        if not isinstance(data, dict):
            raise MercadoPagoError("O Mercado Pago devolveu uma resposta invalida.")
        return data

    async def get_collector_email(self) -> str:
        """Retorna o e-mail da conta que recebe os pagamentos, sem expô-lo ao cliente."""
        if self._collector_email is None:
            profile = await self._request("GET", "/users/me")
            self._collector_email = str(profile.get("email") or "").strip().casefold()
        return self._collector_email

    async def create_subscription(self, user: dict, external_reference: str) -> dict:
        if not self.configured:
            raise MercadoPagoError("O pagamento ainda nao foi configurado pelo administrador.")
        payer_email = str(user.get("email") or "").strip()
        if not payer_email:
            raise MercadoPagoError("Seu e-mail de cadastro e necessario para criar a assinatura.", status_code=400)
        collector_email = await self.get_collector_email()
        if collector_email and payer_email.casefold() == collector_email:
            raise MercadoPagoError(
                "Nao e possivel assinar usando a mesma conta do Mercado Pago que recebe os pagamentos. "
                "Entre com outra conta para concluir a assinatura.",
                status_code=400,
            )
        base = f"{self.public_url}/"
        payload = {
            "reason": "MAGISTERIA - assinatura mensal",
            "external_reference": external_reference,
            "payer_email": payer_email,
            "auto_recurring": {
                "frequency": 1,
                "frequency_type": "months",
                "transaction_amount": float(self.price),
                "currency_id": self.currency,
            },
            "back_url": urljoin(base, "assinatura/retorno"),
            "status": "pending",
        }
        subscription = await self._request("POST", "/preapproval", json=payload)
        subscription_id = str(subscription.get("id") or "").strip()
        checkout_url = str(subscription.get("init_point") or "").strip()
        if not subscription_id or not checkout_url.startswith("https://"):
            raise MercadoPagoError("O Mercado Pago nao devolveu um link de assinatura valido.")
        return {
            "id": subscription_id,
            "checkout_url": checkout_url,
            "external_reference": external_reference,
        }

    async def get_subscription(self, subscription_id: str) -> dict:
        subscription_id = self._validated_identifier(subscription_id, "assinatura")
        return await self._request("GET", f"/preapproval/{quote(subscription_id, safe='')}")

    async def get_authorized_payment(self, invoice_id: str) -> dict:
        invoice_id = self._validated_identifier(invoice_id, "fatura")
        return await self._request("GET", f"/authorized_payments/{quote(invoice_id, safe='')}")

    async def get_payment(self, payment_id: str) -> dict:
        payment_id = self._validated_identifier(payment_id, "pagamento")
        return await self._request("GET", f"/v1/payments/{quote(payment_id, safe='')}")

    @staticmethod
    def _validated_identifier(value: str, label: str) -> str:
        value = str(value).strip()
        if not value or len(value) > 100 or not value.replace("-", "").isalnum():
            raise MercadoPagoError(f"Identificador de {label} invalido.")
        return value

    def validate_webhook_signature(
        self,
        x_signature: str | None,
        x_request_id: str | None,
        data_id: str | None,
    ) -> bool:
        """Valida o manifesto HMAC documentado para Webhooks do Mercado Pago."""
        if not self.webhook_secret:
            return False
        if not x_signature or not x_request_id or not data_id:
            return False

        parts: dict[str, str] = {}
        for part in x_signature.split(","):
            key, separator, value = part.strip().partition("=")
            if separator and key and value:
                parts[key] = value
        timestamp = parts.get("ts")
        received_hash = parts.get("v1")
        if not timestamp or not received_hash:
            return False

        manifest = f"id:{str(data_id).lower()};request-id:{x_request_id};ts:{timestamp};"
        expected_hash = hmac.new(
            self.webhook_secret.encode("utf-8"),
            manifest.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_hash, received_hash)
