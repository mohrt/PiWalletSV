"""Stripe Checkout session creation."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import stripe

from datetime import UTC, datetime

from store.catalog_loader import CatalogError, get_product
from store.fulfill import fulfill_order
from store.http_utils import error_response, json_response
from store.orders import create_order, new_order_id, update_order

log = logging.getLogger(__name__)


def handle_checkout_stripe(body: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    origin = settings["allowed_origin"]
    sku = (body.get("sku") or "").strip()
    if not sku:
        return error_response(400, "sku is required", origin=origin)

    if not settings["stripe_secret_key"]:
        return error_response(503, "stripe is not configured", origin=origin)
    if not settings["table_name"]:
        return error_response(503, "orders table is not configured", origin=origin)

    try:
        product = get_product(settings["catalog"], sku)
    except CatalogError as exc:
        return error_response(400, str(exc), origin=origin)

    price_id = product.get("stripe_price_id", "")
    if not price_id or price_id.startswith("price_REPLACE"):
        return error_response(
            503,
            "stripe price id not configured for this sku",
            origin=origin,
        )

    order_id = new_order_id()
    create_order(
        settings["table_name"],
        {
            "order_id": order_id,
            "sku": sku,
            "product_name": product["name"],
            "status": "pending_stripe",
            "payment_method": "stripe",
            "price_usd_cents": product["price_usd_cents"],
        },
    )

    stripe.api_key = settings["stripe_secret_key"]
    success_qs = urlencode({"order_id": order_id})
    success_url = settings["docs_success_url"]
    if "?" in success_url:
        success_url = f"{success_url}&{success_qs}"
    else:
        success_url = f"{success_url}?{success_qs}"

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=settings["docs_cancel_url"],
        client_reference_id=order_id,
        metadata={"order_id": order_id, "sku": sku},
        shipping_address_collection={"allowed_countries": ["US", "CA", "GB", "AU", "DE", "FR"]},
    )

    update_order(
        settings["table_name"],
        order_id,
        {"stripe_session_id": session.id},
    )

    return json_response(
        200,
        {"order_id": order_id, "checkout_url": session.url},
        origin=origin,
    )


def mark_stripe_paid(
    table_name: str,
    order_id: str,
    *,
    session: dict[str, Any],
    fulfillment_enabled: bool,
) -> dict[str, Any]:
    shipping = session.get("shipping_details") or session.get("customer_details") or {}
    address = shipping.get("address")
    email = (session.get("customer_details") or {}).get("email")
    updates: dict[str, Any] = {
        "status": "paid",
        "paid_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    if email:
        updates["customer_email"] = email
    if address:
        updates["shipping_address"] = address
    order = update_order(table_name, order_id, updates)
    log_entry = fulfill_order(order, enabled=fulfillment_enabled)
    return update_order(
        table_name,
        order_id,
        {
            "status": "fulfilled" if fulfillment_enabled else "paid",
            "fulfillment_log": log_entry,
        },
    )
