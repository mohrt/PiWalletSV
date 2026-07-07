"""BSV checkout — creates pending order with manual payment instructions."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from store.catalog_loader import CatalogError, get_product
from store.http_utils import error_response, json_response
from store.orders import create_order, new_bsv_reference, new_order_id, public_order_view


def handle_checkout_bsv(body: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    origin = settings["allowed_origin"]
    sku = (body.get("sku") or "").strip()
    if not sku:
        return error_response(400, "sku is required", origin=origin)

    if not settings["bsv_receive_address"]:
        return error_response(503, "bsv receive address is not configured", origin=origin)
    if not settings["table_name"]:
        return error_response(503, "orders table is not configured", origin=origin)

    try:
        product = get_product(settings["catalog"], sku)
    except CatalogError as exc:
        return error_response(400, str(exc), origin=origin)

    order_id = new_order_id()
    reference = new_bsv_reference()
    order = create_order(
        settings["table_name"],
        {
            "order_id": order_id,
            "sku": sku,
            "product_name": product["name"],
            "status": "pending_bsv",
            "payment_method": "bsv",
            "price_usd_cents": product["price_usd_cents"],
            "bsv_amount_sats": product["bsv_amount_sats"],
            "bsv_reference": reference,
        },
    )

    pending_qs = urlencode({"order_id": order_id})
    pending_url = settings["docs_bsv_pending_url"]
    if "?" in pending_url:
        pending_url = f"{pending_url}&{pending_qs}"
    else:
        pending_url = f"{pending_url}?{pending_qs}"

    payload = {
        **public_order_view(order),
        "bsv_address": settings["bsv_receive_address"],
        "pending_url": pending_url,
    }
    return json_response(200, payload, origin=origin)
