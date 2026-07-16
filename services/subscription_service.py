from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Mapping


class SubscriptionSource(StrEnum):
    FREE = "free"
    TRIAL = "trial"
    WEB = "web"
    ANDROID = "android"
    IOS = "ios"


class SubscriptionState(StrEnum):
    INACTIVE = "inactive"
    TRIAL = "trial"
    ACTIVE = "active"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUNDED = "refunded"


@dataclass(frozen=True)
class EntitlementSnapshot:
    source: SubscriptionSource
    state: SubscriptionState
    is_full_access: bool
    product_id: str = ""
    renews_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SubscriptionService:
    """Normalizes web and future store subscriptions without validating receipts on-device."""

    WEB_PROVIDERS = {"asaas", "mercado_pago"}

    def __init__(self, google_product_id: str = "", apple_product_id: str = "") -> None:
        self.google_product_id = google_product_id.strip()
        self.apple_product_id = apple_product_id.strip()

    def snapshot(self, user: Mapping, provider: str = "") -> EntitlementSnapshot:
        provider = provider.strip().lower()
        status = str(user.get("subscription_status") or "").strip().lower()
        full = (
            user.get("role") == "admin"
            or user.get("account_type") == "completa"
            or status in {"ativa", "active", "trial"}
        )
        if provider == "google_play":
            source = SubscriptionSource.ANDROID
            product_id = self.google_product_id
        elif provider == "apple":
            source = SubscriptionSource.IOS
            product_id = self.apple_product_id
        elif provider in self.WEB_PROVIDERS:
            source = SubscriptionSource.WEB
            product_id = ""
        elif status in {"teste", "trial"}:
            source = SubscriptionSource.TRIAL
            product_id = ""
        else:
            source = SubscriptionSource.FREE
            product_id = ""

        normalized_state = {
            "ativa": SubscriptionState.ACTIVE,
            "active": SubscriptionState.ACTIVE,
            "teste": SubscriptionState.TRIAL,
            "trial": SubscriptionState.TRIAL,
            "cancelada": SubscriptionState.CANCELED,
            "canceled": SubscriptionState.CANCELED,
            "cancelled": SubscriptionState.CANCELED,
            "vencida": SubscriptionState.EXPIRED,
            "expired": SubscriptionState.EXPIRED,
            "reembolsada": SubscriptionState.REFUNDED,
            "refunded": SubscriptionState.REFUNDED,
        }.get(status, SubscriptionState.INACTIVE)
        return EntitlementSnapshot(
            source=source,
            state=normalized_state,
            is_full_access=bool(full),
            product_id=product_id,
            renews_at=user.get("subscription_renews_at"),
        )

    @property
    def store_products_configured(self) -> dict[str, bool]:
        return {
            "android": bool(self.google_product_id),
            "ios": bool(self.apple_product_id),
        }
