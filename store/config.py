"""Runtime configuration from Lambda environment variables."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def load_settings() -> dict[str, Any]:
    catalog_env = _env("CATALOG_ENV", "dev")
    catalog_path = Path(__file__).resolve().parent / "catalog" / f"products.{catalog_env}.json"
    if not catalog_path.is_file():
        msg = f"catalog file missing: {catalog_path.name}"
        raise FileNotFoundError(msg)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    return {
        "table_name": _env("TABLE_NAME"),
        "catalog": catalog,
        "catalog_env": catalog_env,
        "stripe_secret_key": _env("STRIPE_SECRET_KEY"),
        "stripe_webhook_secret": _env("STRIPE_WEBHOOK_SECRET"),
        "admin_api_key": _env("ADMIN_API_KEY"),
        "bsv_receive_address": _env("BSV_RECEIVE_ADDRESS"),
        "fulfillment_enabled": _env_bool("FULFILLMENT_ENABLED", False),
        "store_public_url": _env("STORE_PUBLIC_URL").rstrip("/"),
        "docs_success_url": _env("DOCS_SUCCESS_URL"),
        "docs_cancel_url": _env("DOCS_CANCEL_URL"),
        "docs_bsv_pending_url": _env(
            "DOCS_BSV_PENDING_URL",
            "https://dev.piwalletsv.com/store/pending-bsv/",
        ),
        "allowed_origin": _env("ALLOWED_ORIGIN", "https://dev.piwalletsv.com"),
    }
