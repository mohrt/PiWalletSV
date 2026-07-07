"""Post-payment fulfillment hook."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def fulfill_order(order: dict[str, Any], *, enabled: bool) -> str:
    """Run fulfillment when an order is paid.

    Dev stacks set ``FULFILLMENT_ENABLED=false`` — log only, no ship.
    """
    order_id = order["order_id"]
    if not enabled:
        msg = f"fulfillment disabled; order {order_id} logged only"
        log.info(msg)
        return msg
    # Prod: call EasyShip Create Shipment API here.
    msg = f"fulfillment stub for order {order_id}"
    log.info(msg)
    return msg
