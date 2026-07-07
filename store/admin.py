"""Admin routes — manual BSV payment confirmation."""

from __future__ import annotations

import json
from typing import Any

from store.fulfill import fulfill_order
from store.http_utils import error_response, json_response
from store.orders import get_order, update_order


def _check_admin(event: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any] | None:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    key = headers.get("x-admin-key", "")
    expected = settings.get("admin_api_key", "")
    if not expected or key != expected:
        return error_response(401, "unauthorized", origin=settings["allowed_origin"])
    return None


def handle_mark_paid(
    event: dict[str, Any],
    order_id: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    origin = settings["allowed_origin"]
    denied = _check_admin(event, settings)
    if denied:
        return denied

    order = get_order(settings["table_name"], order_id)
    if order is None:
        return error_response(404, "order not found", origin=origin)

    if order.get("status") in {"paid", "fulfilled"}:
        return json_response(200, {"order_id": order_id, "status": order["status"]}, origin=origin)

    body: dict[str, Any] = {}
    raw = event.get("body") or ""
    if raw:
        if event.get("isBase64Encoded"):
            import base64

            raw = base64.b64decode(raw).decode("utf-8")
        body = json.loads(raw)

    updates: dict[str, Any] = {"status": "paid", "paid_at": order.get("updated_at")}
    txid = (body.get("txid") or "").strip()
    if txid:
        updates["payment_txid"] = txid

    order = update_order(settings["table_name"], order_id, updates)
    log_entry = fulfill_order(order, enabled=settings["fulfillment_enabled"])
    order = update_order(
        settings["table_name"],
        order_id,
        {
            "status": "fulfilled" if settings["fulfillment_enabled"] else "paid",
            "fulfillment_log": log_entry,
        },
    )
    return json_response(
        200,
        {"order_id": order_id, "status": order["status"], "fulfillment_log": log_entry},
        origin=origin,
    )
