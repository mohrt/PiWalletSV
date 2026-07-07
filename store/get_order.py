"""GET /v1/orders/{id} — public order status."""

from __future__ import annotations

from store.http_utils import error_response, json_response
from store.orders import get_order, public_order_view


def handle_get_order(order_id: str, settings: dict) -> dict:
    origin = settings["allowed_origin"]
    order = get_order(settings["table_name"], order_id)
    if order is None:
        return error_response(404, "order not found", origin=origin)
    payload = public_order_view(order)
    if order.get("payment_method") == "bsv" and order.get("status") == "pending_bsv":
        payload["bsv_address"] = settings["bsv_receive_address"]
    return json_response(200, payload, origin=origin)
