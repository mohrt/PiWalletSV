"""DynamoDB order persistence."""

from __future__ import annotations

import json
import os
import secrets
import string
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr

_ALPHABET = string.ascii_uppercase + string.digits


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _table(table_name: str):
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def new_order_id() -> str:
    return str(uuid.uuid4())


def new_bsv_reference() -> str:
    """Short human-readable payment reference for BSV memos."""
    return "PW-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


def create_order(table_name: str, item: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    record = {
        "order_id": item["order_id"],
        "sku": item["sku"],
        "product_name": item["product_name"],
        "status": item["status"],
        "payment_method": item["payment_method"],
        "price_usd_cents": item["price_usd_cents"],
        "created_at": now,
        "updated_at": now,
    }
    for key in (
        "stripe_session_id",
        "bsv_amount_sats",
        "bsv_reference",
        "customer_email",
        "shipping_address",
        "paid_at",
        "fulfillment_log",
        "payment_txid",
    ):
        if key in item and item[key] is not None:
            record[key] = item[key]
    _table(table_name).put_item(Item=record)
    return record


def get_order(table_name: str, order_id: str) -> dict[str, Any] | None:
    resp = _table(table_name).get_item(Key={"order_id": order_id})
    return resp.get("Item")


def update_order(table_name: str, order_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    updates = dict(updates)
    updates["updated_at"] = _now_iso()
    expr_names: dict[str, str] = {}
    expr_values: dict[str, Any] = {}
    parts: list[str] = []
    for idx, (key, value) in enumerate(updates.items()):
        name = f"#k{idx}"
        val = f":v{idx}"
        expr_names[name] = key
        expr_values[val] = value
        parts.append(f"{name} = {val}")
    expression = "SET " + ", ".join(parts)
    resp = _table(table_name).update_item(
        Key={"order_id": order_id},
        UpdateExpression=expression,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )
    return resp["Attributes"]


def find_order_by_stripe_session(table_name: str, session_id: str) -> dict[str, Any] | None:
    # v1: scan by stripe_session_id (low volume). Replace with GSI if volume grows.
    table = _table(table_name)
    resp = table.scan(FilterExpression=Attr("stripe_session_id").eq(session_id))
    items = resp.get("Items", [])
    return items[0] if items else None


def _json_number(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == int(value) else float(value)
    return value


def public_order_view(order: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to expose to the browser."""
    return {
        "order_id": order["order_id"],
        "sku": order["sku"],
        "product_name": order["product_name"],
        "status": order["status"],
        "payment_method": order["payment_method"],
        "price_usd_cents": _json_number(order.get("price_usd_cents")),
        "bsv_amount_sats": _json_number(order.get("bsv_amount_sats")),
        "bsv_reference": order.get("bsv_reference"),
        "created_at": order.get("created_at"),
        "paid_at": order.get("paid_at"),
    }
