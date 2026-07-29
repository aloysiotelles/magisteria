from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
import pytest

import app as application
from services.auth_repository import AuthRepository
from services.google_play_billing_service import (
    GooglePlayBillingService,
    VerifiedGoogleSubscription,
)


def test_google_play_service_verifies_product_and_acknowledges_purchase():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "startTime": "2026-07-01T12:00:00Z",
                    "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
                    "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
                    "lineItems": [
                        {
                            "productId": "magisteria_completa",
                            "expiryTime": "2099-08-01T12:00:00Z",
                            "autoRenewingPlan": {"autoRenewEnabled": True},
                        }
                    ],
                    "testPurchase": {},
                },
            )
        return httpx.Response(204)

    service = GooglePlayBillingService(
        "",
        "br.com.aloysiotelles.magisteria",
        "magisteria_completa",
        access_token_provider=lambda: "test-access-token",
        transport=httpx.MockTransport(handler),
    )
    verified = asyncio.run(service.verify_subscription("magisteria_completa", "purchase-token"))

    assert verified.is_entitled is True
    assert verified.acknowledged is True
    assert verified.store_state == "active"
    assert verified.is_test_purchase is True
    assert [method for method, _ in calls] == ["GET", "POST"]
    assert calls[1][1].endswith("/purchase-token:acknowledge")


def test_store_purchase_cannot_be_reused_by_another_account(tmp_path: Path):
    repository = AuthRepository(tmp_path / "store.sqlite")
    assert repository.create_user("Primeiro Usuario", "primeiro@example.com", "SenhaForte1")[0]
    assert repository.create_user("Segundo Usuario", "segundo@example.com", "SenhaForte1")[0]
    first = repository.find_user_by_login("primeiro@example.com")
    second = repository.find_user_by_login("segundo@example.com")

    promoted = repository.apply_store_subscription(
        first["id"],
        provider="google_play",
        product_id="magisteria_completa",
        purchase_token="unique-google-token",
        store_state="active",
        is_entitled=True,
        acknowledged=True,
        started_at="2026-07-01T12:00:00Z",
        expires_at="2099-08-01T12:00:00Z",
    )
    assert promoted["account_type"] == "completa"
    assert promoted["subscription_status"] == "ativa"

    with pytest.raises(ValueError, match="outra conta"):
        repository.apply_store_subscription(
            second["id"],
            provider="google_play",
            product_id="magisteria_completa",
            purchase_token="unique-google-token",
            store_state="active",
            is_entitled=True,
            acknowledged=True,
            started_at="2026-07-01T12:00:00Z",
            expires_at="2099-08-01T12:00:00Z",
        )

    downgraded = repository.clear_store_entitlement(first["id"], "google_play")
    assert downgraded["account_type"] == "gratuita"
    assert downgraded["subscription_status"] == "vencida"


def test_mobile_google_purchase_endpoint_activates_full_access(tmp_path: Path, monkeypatch):
    repository = AuthRepository(tmp_path / "mobile-store.sqlite")
    monkeypatch.setattr(application, "auth_repository", repository)

    class FakeGooglePlayBillingService:
        configured = True

        async def verify_subscription(self, product_id: str, purchase_token: str):
            assert product_id == "magisteria_completa"
            assert purchase_token == "verified-token"
            return VerifiedGoogleSubscription(
                product_id=product_id,
                purchase_token=purchase_token,
                store_state="active",
                is_entitled=True,
                acknowledged=True,
                started_at="2026-07-01T12:00:00Z",
                expires_at="2099-08-01T12:00:00Z",
                is_test_purchase=True,
            )

    monkeypatch.setattr(application, "google_play_billing_service", FakeGooglePlayBillingService())
    client = TestClient(application.app)
    registered = client.post(
        "/api/v1/mobile/auth/register",
        json={
            "full_name": "Assinante Mobile",
            "email": "assinante@example.com",
            "password": "SenhaForte1",
        },
    )
    assert registered.status_code == 201
    access_token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    verified = client.post(
        "/api/v1/mobile/subscription/google/verify",
        headers=headers,
        json={"product_id": "magisteria_completa", "purchase_token": "verified-token"},
    )

    assert verified.status_code == 200
    assert verified.json()["user"]["subscription"]["is_full_access"] is True
    subscription = client.get("/api/v1/mobile/subscription", headers=headers)
    assert subscription.status_code == 200
    assert subscription.json()["entitlement"]["source"] == "android"
    assert subscription.json()["google_play"]["available"] is True
