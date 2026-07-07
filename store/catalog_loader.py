"""Product catalog helpers."""

from __future__ import annotations

from typing import Any


class CatalogError(Exception):
    """Invalid SKU or catalog configuration."""


def get_product(catalog: dict[str, Any], sku: str) -> dict[str, Any]:
    for product in catalog.get("products", []):
        if product.get("sku") == sku and product.get("active", True):
            return product
    raise CatalogError(f"unknown or inactive sku: {sku}")
