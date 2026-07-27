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
  let pollTimer = null;

  function formatUsd(cents) {
    if (cents == null) {
      return "—";
    }
    return "$" + (cents / 100).toFixed(2);
  }

  function displayProductName(name) {
    return String(name || "")
      .replace(/\s*\(Round\s*1\)\s*/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function formatWhen(iso) {
    if (!iso) {
      return "—";
    }
    return iso.replace("T", " ").replace("+00:00", " UTC");
  }

  function safeHttpsHref(url) {
    const raw = String(url || "").trim();
    if (!/^https:\/\//i.test(raw)) {
      return "";
    }
    try {
      const parsed = new URL(raw);
      if (parsed.protocol !== "https:") {
        return "";
      }
      return parsed.href;
    } catch (_err) {
      return "";
    }
  }

  function setText(el, text) {
    if (el) {
      el.textContent = text;
    }
  }

  function detailEl() {
    return root.querySelector("[data-order-detail]");
  }

  function statusLabel(data) {
    const status = data.status || "";
    if (status === "cancelled") {
      return "Cancelled";
    }
    if (status === "shipped") {
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
      return "Tracking appears here once your package is in the mail.";
    }
    if (status === "shipped") {
      return "Your package is on the way.";
    }
    if (status === "cancelled") {
      return "This order was cancelled.";
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
    const detail = detailEl();
    if (!detail) {
      showError("Order status layout is missing on this page.");
      return;
    }
    detail.hidden = false;

    setText(detail.querySelector("[data-order-status-label]"), statusLabel(data));
    setText(detail.querySelector("[data-order-status-hint]"), statusHint(data));
    setText(detail.querySelector("[data-order-id-display]"), data.order_id || "—");
    setText(detail.querySelector("[data-product-name]"), displayProductName(data.product_name || "—") || "—");

    const itemEl = detail.querySelector("[data-item-usd]");
    if (itemEl) {
      const itemCents =
        data.item_subtotal_cents != null ? data.item_subtotal_cents : data.price_usd_cents;
      setText(itemEl, formatUsd(itemCents));
    }

    const hasBreakdown =
      data.payment_method === "stripe" &&
      (data.total_cents != null || data.shipping_cents != null || data.tax_cents != null);

    detail.querySelectorAll("[data-order-breakdown-row]").forEach(function (row) {
      row.hidden = !hasBreakdown;
    });

    const shippingEl = detail.querySelector("[data-shipping-usd]");
    if (shippingEl) {
      setText(
        shippingEl,
        data.shipping_cents != null
          ? formatUsd(data.shipping_cents) +
              (data.shipping_label ? " (" + data.shipping_label + ")" : "")
          : "—"
      );
    }
    const taxEl = detail.querySelector("[data-tax-usd]");
    if (taxEl) {
      setText(taxEl, data.tax_cents != null ? formatUsd(data.tax_cents) : "—");
    }
    const totalEl = detail.querySelector("[data-total-usd]");
    if (totalEl) {
      setText(totalEl, data.total_cents != null ? formatUsd(data.total_cents) : "—");
    }

    setText(detail.querySelector("[data-payment-method]"), data.payment_method || "—");
    setText(detail.querySelector("[data-created-at]"), formatWhen(data.created_at));
    setText(detail.querySelector("[data-paid-at]"), formatWhen(data.paid_at));

    const bsvRefRow = detail.querySelector("[data-bsv-ref-row]");
    if (bsvRefRow) {
      if (data.bsv_reference) {
        bsvRefRow.hidden = false;
        setText(bsvRefRow.querySelector("[data-bsv-reference]"), data.bsv_reference);
      } else {
        bsvRefRow.hidden = true;
      }
    }

    const trackingSection = detail.querySelector("[data-tracking-section]");
    const shipment = data.shipment;
    if (trackingSection) {
      if (shipment && shipment.tracking_number) {
        trackingSection.hidden = false;
        setText(trackingSection.querySelector("[data-carrier]"), shipment.carrier || "Carrier");
        setText(trackingSection.querySelector("[data-tracking-number]"), shipment.tracking_number);
        setText(trackingSection.querySelector("[data-shipped-at]"), formatWhen(shipment.shipped_at));
        const trackLink = trackingSection.querySelector("[data-tracking-link]");
        if (trackLink) {
          const safeUrl = shipment.tracking_url ? safeHttpsHref(shipment.tracking_url) : "";
          if (safeUrl) {
            trackLink.href = safeUrl;
            trackLink.rel = "noopener noreferrer";
            trackLink.target = "_blank";
            trackLink.hidden = false;
          } else {
            trackLink.removeAttribute("href");
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
          const detail = detailEl();
          if (detail) {
            detail.hidden = true;
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
