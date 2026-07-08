/**
 * Customer order status — lookup by order ID, poll while payment pending.
 */
(function () {
  const cfgEl = document.getElementById("piwalletsv-store-config");
  const root = document.getElementById("piwalletsv-order-status");
  if (!cfgEl || !root) {
    return;
  }

  const apiUrl = (cfgEl.dataset.apiUrl || "").replace(/\/$/, "");
  if (!apiUrl) {
    root.textContent = "Order lookup is not configured for this build.";
    return;
  }

  const form = root.querySelector("[data-order-lookup-form]");
  const input = root.querySelector("[data-order-id-input]");
  const errorEl = root.querySelector("[data-order-error]");
  const detailEl = root.querySelector("[data-order-detail]");
  let pollTimer = null;

  function formatUsd(cents) {
    if (cents == null) {
      return "—";
    }
    return "$" + (cents / 100).toFixed(2);
  }

  function formatWhen(iso) {
    if (!iso) {
      return "—";
    }
    return iso.replace("T", " ").replace("+00:00", " UTC");
  }

  function statusLabel(data) {
    const status = data.status || "";
    if (status === "cancelled") {
      return "Cancelled";
    }
    if (status === "shipped" || (data.shipment && data.shipment.tracking_number)) {
      return "Shipped";
    }
    if (status === "paid" || status === "fulfilled") {
      return "Paid — preparing shipment";
    }
    if (status === "pending_bsv") {
      return "Awaiting BSV payment";
    }
    if (status === "pending_stripe") {
      return "Awaiting card payment";
    }
    return status || "Unknown";
  }

  function statusHint(data) {
    const status = data.status || "";
    if (status === "pending_bsv") {
      return "Contact @PiWalletSV on X with your order ID to arrange payment. This page refreshes automatically.";
    }
    if (status === "pending_stripe") {
      return "If you just paid by card, confirmation usually takes under a minute.";
    }
    if (status === "paid" || status === "fulfilled") {
      return "We ship within a few business days. Tracking will appear here when the label is purchased.";
    }
    if (status === "shipped" || (data.shipment && data.shipment.tracking_number)) {
      return "Your package is on the way.";
    }
    if (status === "cancelled") {
      return "This order was cancelled. Contact @PiWalletSV on X if you think this is a mistake.";
    }
    return "";
  }

  function showError(message) {
    if (!errorEl) {
      return;
    }
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }

  function clearPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function schedulePoll(orderId) {
    clearPoll();
    pollTimer = setInterval(function () {
      loadOrder(orderId, { quiet: true });
    }, 30000);
  }

  function renderOrder(data) {
    if (!detailEl) {
      return;
    }
    detailEl.hidden = false;
    detailEl.querySelector("[data-order-status-label]").textContent = statusLabel(data);
    detailEl.querySelector("[data-order-status-hint]").textContent = statusHint(data);
    detailEl.querySelector("[data-order-id]").textContent = data.order_id || "—";
    detailEl.querySelector("[data-product-name]").textContent = data.product_name || "—";

    const itemEl = detailEl.querySelector("[data-item-usd]");
    if (itemEl) {
      const itemCents =
        data.item_subtotal_cents != null ? data.item_subtotal_cents : data.price_usd_cents;
      itemEl.textContent = formatUsd(itemCents);
    }

    const hasBreakdown =
      data.payment_method === "stripe" &&
      (data.total_cents != null || data.shipping_cents != null || data.tax_cents != null);

    detailEl.querySelectorAll("[data-order-breakdown-row]").forEach(function (row) {
      row.hidden = !hasBreakdown;
    });

    const shippingEl = detailEl.querySelector("[data-shipping-usd]");
    if (shippingEl) {
      shippingEl.textContent =
        data.shipping_cents != null
          ? formatUsd(data.shipping_cents) +
            (data.shipping_label ? " (" + data.shipping_label + ")" : "")
          : "—";
    }
    const taxEl = detailEl.querySelector("[data-tax-usd]");
    if (taxEl) {
      taxEl.textContent = data.tax_cents != null ? formatUsd(data.tax_cents) : "—";
    }
    const totalEl = detailEl.querySelector("[data-total-usd]");
    if (totalEl) {
      totalEl.textContent = data.total_cents != null ? formatUsd(data.total_cents) : "—";
    }

    detailEl.querySelector("[data-payment-method]").textContent = data.payment_method || "—";
    detailEl.querySelector("[data-created-at]").textContent = formatWhen(data.created_at);
    detailEl.querySelector("[data-paid-at]").textContent = formatWhen(data.paid_at);

    const bsvRefRow = detailEl.querySelector("[data-bsv-ref-row]");
    if (bsvRefRow) {
      if (data.bsv_reference) {
        bsvRefRow.hidden = false;
        bsvRefRow.querySelector("[data-bsv-reference]").textContent = data.bsv_reference;
      } else {
        bsvRefRow.hidden = true;
      }
    }

    const trackingSection = detailEl.querySelector("[data-tracking-section]");
    const shipment = data.shipment;
    if (trackingSection) {
      if (shipment && shipment.tracking_number) {
        trackingSection.hidden = false;
        trackingSection.querySelector("[data-carrier]").textContent = shipment.carrier || "Carrier";
        trackingSection.querySelector("[data-tracking-number]").textContent = shipment.tracking_number;
        const shippedAt = trackingSection.querySelector("[data-shipped-at]");
        if (shippedAt) {
          shippedAt.textContent = formatWhen(shipment.shipped_at);
        }
        const trackLink = trackingSection.querySelector("[data-tracking-link]");
        if (trackLink) {
          if (shipment.tracking_url) {
            trackLink.href = shipment.tracking_url;
            trackLink.hidden = false;
          } else {
            trackLink.hidden = true;
          }
        }
      } else {
        trackingSection.hidden = true;
      }
    }

    const pending = data.status === "pending_bsv" || data.status === "pending_stripe";
    if (pending) {
      schedulePoll(data.order_id);
    } else {
      clearPoll();
    }
  }

  async function loadOrder(orderId, options) {
    const quiet = options && options.quiet;
    if (!quiet) {
      showError("");
    }
    try {
      const resp = await fetch(apiUrl + "/v1/orders/" + encodeURIComponent(orderId));
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        if (!quiet) {
          showError(data.error || "Order not found. Check the ID and try again.");
          if (detailEl) {
            detailEl.hidden = true;
          }
          clearPoll();
        }
        return;
      }
      renderOrder(data);
      if (input) {
        input.value = orderId;
      }
      const url = new URL(window.location.href);
      if (url.searchParams.get("order_id") !== orderId) {
        url.searchParams.set("order_id", orderId);
        window.history.replaceState({}, "", url.toString());
      }
    } catch (err) {
      if (!quiet) {
        showError(err.message || String(err));
      }
    }
  }

  if (form && input) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      const orderId = input.value.trim();
      if (!orderId) {
        showError("Enter your order ID.");
        return;
      }
      loadOrder(orderId);
    });
  }

  const initialId = new URLSearchParams(window.location.search).get("order_id");
  if (initialId) {
    if (input) {
      input.value = initialId;
    }
    loadOrder(initialId);
  }
})();
