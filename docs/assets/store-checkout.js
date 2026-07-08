/**
 * PiWalletSV store checkout — calls store API from purchase buttons.
 */
(function () {
  const cfgEl = document.getElementById("piwalletsv-store-config");
  if (!cfgEl) {
    return;
  }

  const apiUrl = (cfgEl.dataset.apiUrl || "").replace(/\/$/, "");
  const devBanner = cfgEl.dataset.devBanner || "";

  if (devBanner) {
    const banner = document.createElement("div");
    banner.className = "piwalletsv-store-banner";
    banner.textContent = devBanner;
    const main = document.querySelector(".md-content");
    if (main && main.firstChild) {
      main.insertBefore(banner, main.firstChild);
    }
  }

  if (!apiUrl) {
    document.querySelectorAll("[data-store-checkout]").forEach(function (btn) {
      btn.disabled = true;
      btn.title = "Store API URL not configured for this build";
    });
    return;
  }

  (function injectOosStyles() {
    const id = "piwalletsv-store-oos-styles";
    if (document.getElementById(id)) {
      return;
    }
    const el = document.createElement("style");
    el.id = id;
    el.textContent =
      ".md-typeset .piwalletsv-store-actions button.md-button.piwalletsv-store-oos," +
      ".md-typeset .piwalletsv-store-actions button.md-button:disabled.piwalletsv-store-oos{" +
      "cursor:not-allowed!important;filter:grayscale(.45)!important;opacity:.5!important;" +
      "pointer-events:none!important;box-shadow:none!important}";
    document.head.appendChild(el);
  })();

  const stockBySku = {};

  function setBusy(btn, busy) {
    if (btn.classList.contains("piwalletsv-store-oos")) {
      return;
    }
    btn.disabled = busy;
    btn.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function showError(btn, message) {
    let el = btn.parentElement.querySelector(".piwalletsv-store-error");
    if (!el) {
      el = document.createElement("p");
      el.className = "piwalletsv-store-error";
      btn.parentElement.appendChild(el);
    }
    el.textContent = message;
  }

  function formatUsd(cents) {
    return "$" + (cents / 100).toFixed(2);
  }

  function applyStockUi() {
    document.querySelectorAll("[data-store-stock]").forEach(function (el) {
      const sku = el.getAttribute("data-store-stock");
      const info = stockBySku[sku];
      if (!info || !info.track_inventory) {
        el.hidden = true;
        return;
      }
      el.hidden = false;
      if (info.in_stock) {
        el.className = "piwalletsv-store-stock piwalletsv-store-stock--in";
        el.textContent =
          info.available === 1
            ? "1 kit left in this batch."
            : info.available + " kits left in this batch.";
      } else {
        el.className = "piwalletsv-store-stock piwalletsv-store-stock--out";
        el.textContent = "Out of stock for this batch.";
      }
    });

    document.querySelectorAll("[data-store-follow]").forEach(function (el) {
      const sku = el.getAttribute("data-store-follow");
      const info = stockBySku[sku];
      const oos = info && info.track_inventory && !info.in_stock;
      el.hidden = !oos;
    });

    document.querySelectorAll("[data-store-checkout]").forEach(function (btn) {
      const sku = btn.getAttribute("data-sku");
      const info = stockBySku[sku];
      if (!info || !info.track_inventory) {
        return;
      }
      if (!info.in_stock) {
        btn.disabled = true;
        btn.classList.add("piwalletsv-store-oos");
        btn.setAttribute("aria-disabled", "true");
        btn.title = "Out of stock";
      }
    });
  }

  async function loadInventory() {
    try {
      const resp = await fetch(apiUrl + "/v1/inventory");
      const data = await resp.json();
      if (!resp.ok) {
        return;
      }
      (data.products || []).forEach(function (p) {
        stockBySku[p.sku] = p;
      });
      applyStockUi();
    } catch (_err) {
      /* leave buttons enabled if inventory fetch fails */
    }
  }

  async function postCheckout(path, sku) {
    const resp = await fetch(apiUrl + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sku: sku }),
    });
    const data = await resp.json().catch(function () {
      return {};
    });
    if (!resp.ok) {
      if (resp.status === 409) {
        throw new Error("Out of stock — this batch is sold out.");
      }
      throw new Error(data.error || "checkout failed");
    }
    return data;
  }

  loadInventory();

  document.querySelectorAll("[data-store-checkout]").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      const sku = btn.getAttribute("data-sku");
      const method = btn.getAttribute("data-store-checkout");
      if (!sku || !method) {
        return;
      }
      setBusy(btn, true);
      try {
        if (method === "stripe") {
          const data = await postCheckout("/v1/checkout/stripe", sku);
          if (data.checkout_url) {
            window.location.href = data.checkout_url;
            return;
          }
          throw new Error("missing checkout URL");
        }
        if (method === "bsv") {
          const data = await postCheckout("/v1/checkout/bsv", sku);
          if (data.pending_url) {
            window.location.href = data.pending_url;
            return;
          }
          throw new Error("missing pending URL");
        }
      } catch (err) {
        showError(btn, err.message || String(err));
        setBusy(btn, false);
        if ((err.message || "").indexOf("Out of stock") >= 0) {
          loadInventory();
        }
      }
    });
  });

  // Card success page: poll order status while payment confirms
  const successEl = document.getElementById("piwalletsv-order-success");
  if (successEl && apiUrl) {
    const orderId = new URLSearchParams(window.location.search).get("order_id");
    if (!orderId) {
      const note = successEl.querySelector("[data-missing-order-id]");
      if (note) {
        note.hidden = false;
      }
    } else {
      const idEl = document.getElementById("piwalletsv-order-id");
      if (idEl) {
        idEl.textContent = orderId;
      }
      const track = document.getElementById("piwalletsv-track-order");
      if (track) {
        track.href = "/store/order-status/?order_id=" + encodeURIComponent(orderId);
      }

      async function refreshSuccess() {
        const resp = await fetch(apiUrl + "/v1/orders/" + encodeURIComponent(orderId));
        const data = await resp.json();
        if (!resp.ok) {
          return;
        }
        const statusEl = successEl.querySelector("[data-order-status-label]");
        if (statusEl) {
          if (data.status === "paid" || data.status === "fulfilled") {
            statusEl.textContent = "Payment confirmed";
          } else if (data.status === "shipped") {
            statusEl.textContent = "Shipped";
          } else if (data.status === "pending_stripe") {
            statusEl.textContent = "Confirming payment…";
          } else {
            statusEl.textContent = data.status || "—";
          }
        }
        const paidNote = successEl.querySelector("[data-paid-note]");
        if (paidNote) {
          paidNote.hidden = !(data.status === "paid" || data.status === "fulfilled" || data.status === "shipped");
        }
        const trackingNote = successEl.querySelector("[data-tracking-note]");
        if (trackingNote) {
          trackingNote.hidden = !(data.shipment && data.shipment.tracking_url);
          if (!trackingNote.hidden) {
            const link = trackingNote.querySelector("[data-tracking-link]");
            if (link) {
              link.href = data.shipment.tracking_url;
            }
          }
        }
      }

      refreshSuccess();
      setInterval(refreshSuccess, 15000);
    }
  }

  // BSV pending page: poll order status
  const pendingEl = document.getElementById("piwalletsv-bsv-pending");
  if (pendingEl && apiUrl) {
    const orderId = new URLSearchParams(window.location.search).get("order_id");
    if (!orderId) {
      pendingEl.textContent = "Missing order_id in URL.";
      return;
    }

    pendingEl.querySelector("[data-order-id]").textContent = orderId;

    async function refresh() {
      const resp = await fetch(apiUrl + "/v1/orders/" + encodeURIComponent(orderId));
      const data = await resp.json();
      if (!resp.ok) {
        pendingEl.textContent = data.error || "Could not load order.";
        return;
      }
      pendingEl.querySelector("[data-order-status]").textContent = data.status;
      if (data.product_name) {
        pendingEl.querySelector("[data-product-name]").textContent = data.product_name;
      }
      if (data.price_usd_cents != null) {
        pendingEl.querySelector("[data-price-usd]").textContent = formatUsd(data.price_usd_cents);
      }
      if (data.status === "paid" || data.status === "fulfilled" || data.status === "shipped") {
        pendingEl.querySelector("[data-paid-note]").hidden = false;
      }
    }

    refresh();
    setInterval(refresh, 15000);
  }
})();
