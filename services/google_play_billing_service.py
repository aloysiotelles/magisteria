from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Callable
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)


class GooglePlayBillingError(RuntimeError):
    """Safe error returned when Google Play cannot validate a subscription."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class VerifiedGoogleSubscription:
    product_id: str
    purchase_token: str
    store_state: str
    is_entitled: bool
    acknowledged: bool
    started_at: str | None
    expires_at: str | None
    is_test_purchase: bool

    def to_dict(self) -> dict:
        return asdict(self)


class GooglePlayBillingService:
    API_BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3"
    AUTH_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
    ENTITLED_STATES = {
        "SUBSCRIPTION_STATE_ACTIVE",
        "SUBSCRIPTION_STATE_CANCELED",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
    }
    STATE_NAMES = {
        "SUBSCRIPTION_STATE_PENDING": "pending",
        "SUBSCRIPTION_STATE_ACTIVE": "active",
        "SUBSCRIPTION_STATE_PAUSED": "paused",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace_period",
        "SUBSCRIPTION_STATE_ON_HOLD": "on_hold",
        "SUBSCRIPTION_STATE_CANCELED": "canceled",
        "SUBSCRIPTION_STATE_EXPIRED": "expired",
        "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED": "pending_canceled",
    }

    def __init__(
        self,
        credentials_json: str,
        package_name: str,
        product_id: str,
        *,
        timeout_seconds: float = 12,
        access_token_provider: Callable[[], str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.credentials_json = credentials_json.strip()
        self.package_name = package_name.strip()
        self.product_id = product_id.strip()
        self.timeout_seconds = timeout_seconds
        self._access_token_provider = access_token_provider
        self._transport = transport
        self._credentials = None

    @property
    def configured(self) -> bool:
        return bool(
            self.package_name
            and self.product_id
            and (self.credentials_json or self._access_token_provider)
        )

    async def verify_subscription(
        self,
        product_id: str,
        purchase_token: str,
    ) -> VerifiedGoogleSubscription:
        if not self.configured:
            raise GooglePlayBillingError(
                "A verificacao de compras do Google Play ainda nao foi configurada.",
                status_code=503,
            )
        product_id = product_id.strip()
        purchase_token = purchase_token.strip()
        if product_id != self.product_id:
            raise GooglePlayBillingError("Produto de assinatura invalido.", status_code=400)
        if not purchase_token or len(purchase_token) > 4096:
            raise GooglePlayBillingError("Comprovante de compra invalido.", status_code=400)

        payload = await self._request(
            "GET",
            "/applications/"
            f"{quote(self.package_name, safe='')}/purchases/subscriptionsv2/tokens/"
            f"{quote(purchase_token, safe='')}",
        )
        line_items = payload.get("lineItems") if isinstance(payload.get("lineItems"), list) else []
        matching_items = [
            item
            for item in line_items
            if isinstance(item, dict) and str(item.get("productId") or "") == product_id
        ]
        if not matching_items:
            raise GooglePlayBillingError(
                "A compra nao corresponde a assinatura do MAGISTERIA.",
                status_code=400,
            )

        expiry_values = [
            str(item.get("expiryTime") or "").strip()
            for item in matching_items
            if str(item.get("expiryTime") or "").strip()
        ]
        expires_at = max(expiry_values, key=self._timestamp) if expiry_values else None
        raw_state = str(payload.get("subscriptionState") or "SUBSCRIPTION_STATE_UNSPECIFIED")
        entitled = raw_state in self.ENTITLED_STATES and bool(
            expires_at and self._timestamp(expires_at) > datetime.now(timezone.utc)
        )
        acknowledged = (
            str(payload.get("acknowledgementState") or "")
            == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
        )
        if entitled and not acknowledged:
            await self._request(
                "POST",
                "/applications/"
                f"{quote(self.package_name, safe='')}/purchases/subscriptions/"
                f"{quote(product_id, safe='')}/tokens/{quote(purchase_token, safe='')}:acknowledge",
                json={},
                expect_empty=True,
            )
            acknowledged = True

        return VerifiedGoogleSubscription(
            product_id=product_id,
            purchase_token=purchase_token,
            store_state=self.STATE_NAMES.get(raw_state, "unknown"),
            is_entitled=entitled,
            acknowledged=acknowledged,
            started_at=str(payload.get("startTime") or "").strip() or None,
            expires_at=expires_at,
            is_test_purchase=isinstance(payload.get("testPurchase"), dict),
        )

    async def _request(self, method: str, path: str, *, expect_empty: bool = False, **kwargs) -> dict:
        access_token = await asyncio.to_thread(self._access_token)
        try:
            async with httpx.AsyncClient(
                base_url=self.API_BASE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            logger.warning("Falha de rede ao consultar o Google Play: %s", exc)
            raise GooglePlayBillingError(
                "O Google Play esta temporariamente indisponivel. Tente novamente."
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "Google Play respondeu HTTP %s (request_id=%s): %.800s",
                response.status_code,
                response.headers.get("x-guploader-uploadid", ""),
                response.text,
            )
            if response.status_code in {401, 403}:
                raise GooglePlayBillingError(
                    "A verificacao de compras do Google Play precisa ser reconfigurada.",
                    status_code=503,
                )
            if response.status_code in {400, 404, 410}:
                raise GooglePlayBillingError(
                    "A compra nao foi reconhecida pelo Google Play.",
                    status_code=400,
                )
            raise GooglePlayBillingError("O Google Play nao conseguiu validar a compra agora.")
        if expect_empty or response.status_code == 204 or not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise GooglePlayBillingError("O Google Play devolveu uma resposta invalida.") from exc
        if not isinstance(data, dict):
            raise GooglePlayBillingError("O Google Play devolveu uma resposta invalida.")
        return data

    def _access_token(self) -> str:
        if self._access_token_provider:
            token = self._access_token_provider().strip()
            if not token:
                raise GooglePlayBillingError("Credencial do Google Play indisponivel.", status_code=503)
            return token
        try:
            from google.auth.transport.requests import Request as GoogleAuthRequest
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover - protected by deployment dependencies
            raise GooglePlayBillingError(
                "O servidor nao possui o componente de verificacao do Google Play.",
                status_code=503,
            ) from exc
        if self._credentials is None:
            try:
                self._credentials = service_account.Credentials.from_service_account_info(
                    self._credentials_info(),
                    scopes=[self.AUTH_SCOPE],
                )
            except (ValueError, TypeError, KeyError) as exc:
                raise GooglePlayBillingError(
                    "A credencial de compras do Google Play e invalida.",
                    status_code=503,
                ) from exc
        if not self._credentials.valid:
            try:
                self._credentials.refresh(GoogleAuthRequest())
            except Exception as exc:
                logger.warning("Nao foi possivel renovar a credencial do Google Play: %s", exc)
                raise GooglePlayBillingError(
                    "A credencial de compras do Google Play nao pode ser renovada.",
                    status_code=503,
                ) from exc
        return str(self._credentials.token or "")

    def _credentials_info(self) -> dict:
        raw = self.credentials_json.strip()
        candidates = [raw]
        try:
            decoded = base64.b64decode(raw, validate=True).decode("utf-8")
            candidates.append(decoded)
        except (ValueError, UnicodeDecodeError):
            pass
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("type") == "service_account":
                return data
        raise GooglePlayBillingError(
            "A credencial de compras do Google Play e invalida.",
            status_code=503,
        )

    @staticmethod
    def _timestamp(value: str) -> datetime:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise GooglePlayBillingError(
                "O Google Play devolveu uma data de assinatura invalida."
            ) from exc
