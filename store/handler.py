"""AWS Lambda entry point for the PiWalletSV store API."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from store.admin import handle_mark_paid
from store.checkout_bsv import handle_checkout_bsv
from store.checkout_stripe import handle_checkout_stripe
from store.config import load_settings
from store.get_order import handle_get_order
from store.http_utils import error_response, options_response
from store.stripe_webhook import handle_stripe_webhook

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

_MARK_PAID_RE = re.compile(r"^/v1/admin/orders/([^/]+)/mark-paid$")
_GET_ORDER_RE = re.compile(r"^/v1/orders/([^/]+)$")


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or ""
    if not raw:
        return {}
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    try:
        settings = load_settings()
    except FileNotFoundError as exc:
        log.exception("config error")
        return error_response(503, str(exc), origin="*")

    origin = settings["allowed_origin"]
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method") or event.get(
        "httpMethod",
        "GET",
    )
    path = event.get("rawPath") or event.get("path") or "/"

    if method == "OPTIONS":
        return options_response(origin=origin)

    try:
        if method == "POST" and path == "/v1/checkout/stripe":
            return handle_checkout_stripe(_parse_body(event), settings)
        if method == "POST" and path == "/v1/checkout/bsv":
            return handle_checkout_bsv(_parse_body(event), settings)
        if method == "POST" and path == "/v1/webhooks/stripe":
            return handle_stripe_webhook(event, settings)
        if method == "POST":
            match = _MARK_PAID_RE.match(path)
            if match:
                return handle_mark_paid(event, match.group(1), settings)
        if method == "GET":
            match = _GET_ORDER_RE.match(path)
            if match:
                return handle_get_order(match.group(1), settings)
    except json.JSONDecodeError:
        return error_response(400, "invalid json body", origin=origin)
    except Exception:
        log.exception("unhandled error on %s %s", method, path)
        return error_response(500, "internal error", origin=origin)

    return error_response(404, "not found", origin=origin)
