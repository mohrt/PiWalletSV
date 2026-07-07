"""Stripe webhook handler."""

from __future__ import annotations

import json
import logging
from typing import Any

import stripe

from store.checkout_stripe import mark_stripe_paid
from store.http_utils import error_response, json_response
from store.orders import find_order_by_stripe_session, get_order

log = logging.getLogger(__name__)


def handle_stripe_webhook(event: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    origin = settings["allowed_origin"]
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    sig = headers.get("stripe-signature", "")
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    if not settings["stripe_webhook_secret"]:
        return error_response(503, "stripe webhook secret is not configured", origin=origin)

    try:
        stripe_event = stripe.Webhook.construct_event(
            raw_body,
            sig,
            settings["stripe_webhook_secret"],
        )
    except ValueError:
        return error_response(400, "invalid payload", origin=origin)
    except stripe.SignatureVerificationError:
        return error_response(400, "invalid signature", origin=origin)

    if stripe_event["type"] != "checkout.session.completed":
        return json_response(200, {"received": True, "ignored": stripe_event["type"]}, origin=origin)

    session = stripe_event["data"]["object"]
    order_id = (session.get("metadata") or {}).get("order_id") or session.get("client_reference_id")
    table_name = settings["table_name"]

    order = get_order(table_name, order_id) if order_id else None
    if order is None:
        order = find_order_by_stripe_session(table_name, session.get("id", ""))
    if order is None:
        log.warning("webhook for unknown session %s", session.get("id"))
        return error_response(404, "order not found", origin=origin)

    if order.get("status") in {"paid", "fulfilled"}:
        return json_response(200, {"received": True, "duplicate": True}, origin=origin)

    mark_stripe_paid(
        table_name,
        order["order_id"],
        session=session,
        fulfillment_enabled=settings["fulfillment_enabled"],
    )
    return json_response(200, {"received": True}, origin=origin)
