"""Store API tests (DynamoDB via moto; Stripe mocked)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from store.handler import lambda_handler

TABLE = "piwallet-store-orders-test"
ADMIN_KEY = "test-admin-key"


@pytest.fixture(autouse=True)
def store_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("CATALOG_ENV", "dev")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("BSV_RECEIVE_ADDRESS", "1TestBsvAddress")
    monkeypatch.setenv("FULFILLMENT_ENABLED", "false")
    monkeypatch.setenv("STORE_PUBLIC_URL", "https://store.dev.piwalletsv.com")
    monkeypatch.setenv("DOCS_SUCCESS_URL", "https://dev.piwalletsv.com/store/success/")
    monkeypatch.setenv("DOCS_CANCEL_URL", "https://dev.piwalletsv.com/store/cancel/")
    monkeypatch.setenv("ALLOWED_ORIGIN", "https://dev.piwalletsv.com")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    from store.config import load_settings

    load_settings.cache_clear()


@pytest.fixture
def dynamodb_table() -> str:
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "order_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "order_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield TABLE


def _event(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict:
    payload = {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "headers": headers or {},
    }
    if body is not None:
        payload["body"] = json.dumps(body)
    return payload


def test_checkout_bsv_creates_pending_order(dynamodb_table: str) -> None:
    resp = lambda_handler(_event("POST", "/v1/checkout/bsv", {"sku": "case-only"}), None)
    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["status"] == "pending_bsv"
    assert data["bsv_address"] == "1TestBsvAddress"
    assert data["bsv_reference"].startswith("PW-")


def test_get_order(dynamodb_table: str) -> None:
    created = lambda_handler(_event("POST", "/v1/checkout/bsv", {"sku": "case-only"}), None)
    order_id = json.loads(created["body"])["order_id"]
    resp = lambda_handler(_event("GET", f"/v1/orders/{order_id}"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["order_id"] == order_id


def test_stripe_checkout_requires_configured_price(dynamodb_table: str) -> None:
    resp = lambda_handler(_event("POST", "/v1/checkout/stripe", {"sku": "full-kit"}), None)
    assert resp["statusCode"] == 503
    assert "price id" in json.loads(resp["body"])["error"]


@patch("store.checkout_stripe.stripe.checkout.Session.create")
@patch("store.checkout_stripe.get_product")
def test_stripe_checkout_success(
    mock_get_product: MagicMock,
    mock_create: MagicMock,
    dynamodb_table: str,
) -> None:
    mock_get_product.return_value = {
        "sku": "full-kit",
        "name": "Full Kit",
        "price_usd_cents": 14900,
        "stripe_price_id": "price_test_full",
    }
    mock_create.return_value = MagicMock(id="cs_test_1", url="https://checkout.stripe.com/test")
    resp = lambda_handler(_event("POST", "/v1/checkout/stripe", {"sku": "full-kit"}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["checkout_url"].startswith("https://checkout.stripe.com")
    mock_create.assert_called_once()


@patch("store.stripe_webhook.stripe.Webhook.construct_event")
def test_stripe_webhook_marks_paid(
    mock_construct: MagicMock,
    dynamodb_table: str,
) -> None:
    with patch("store.checkout_stripe.get_product") as gp:
        gp.return_value = {
            "sku": "case-only",
            "name": "Case",
            "price_usd_cents": 3500,
            "stripe_price_id": "price_test_case",
            "bsv_amount_sats": 1,
        }
        with patch("store.checkout_stripe.stripe.checkout.Session.create") as mock_create:
            mock_create.return_value = MagicMock(id="cs_test_2", url="https://checkout.stripe.com/x")
            checkout = lambda_handler(
                _event("POST", "/v1/checkout/stripe", {"sku": "case-only"}),
                None,
            )
    order_id = json.loads(checkout["body"])["order_id"]

    mock_construct.return_value = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_2",
                "metadata": {"order_id": order_id},
                "client_reference_id": order_id,
                "customer_details": {"email": "buyer@example.com"},
            },
        },
    }
    resp = lambda_handler(
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/v1/webhooks/stripe",
            "headers": {"stripe-signature": "sig"},
            "body": "{}",
        },
        None,
    )
    assert resp["statusCode"] == 200
    got = lambda_handler(_event("GET", f"/v1/orders/{order_id}"), None)
    assert json.loads(got["body"])["status"] == "paid"


def test_admin_mark_paid(dynamodb_table: str) -> None:
    created = lambda_handler(_event("POST", "/v1/checkout/bsv", {"sku": "case-only"}), None)
    order_id = json.loads(created["body"])["order_id"]
    resp = lambda_handler(
        _event(
            "POST",
            f"/v1/admin/orders/{order_id}/mark-paid",
            {"txid": "abc123"},
            {"x-admin-key": ADMIN_KEY},
        ),
        None,
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "paid"
