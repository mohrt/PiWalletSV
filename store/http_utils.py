"""API Gateway HTTP API response helpers."""

from __future__ import annotations

import json
from typing import Any


def cors_headers(origin: str) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": "content-type,x-admin-key",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    }


def json_response(
    status_code: int,
    body: dict[str, Any] | list[Any],
    *,
    origin: str,
) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            **cors_headers(origin),
        },
        "body": json.dumps(body),
    }


def error_response(
    status_code: int,
    message: str,
    *,
    origin: str,
) -> dict[str, Any]:
    return json_response(status_code, {"error": message}, origin=origin)


def options_response(*, origin: str) -> dict[str, Any]:
    return {
        "statusCode": 204,
        "headers": cors_headers(origin),
        "body": "",
    }
