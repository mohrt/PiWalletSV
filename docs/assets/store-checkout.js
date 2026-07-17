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

  if (devBanner && !document.querySelector(".piwalletsv-store-banner")) {
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
      ".md-typeset .piwalletsv-store-actions button.md-button:disabled," +
      ".md-typeset .piwalletsv-store-actions button.md-button.piwalletsv-store-oos{" +
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

  function selectedShipCountry() {
    const select = document.querySelector("[data-store-ship-country]");
    const country = ((select && select.value) || "").trim().toUpperCase();
    if (!country || country.length !== 2) {
      return null;
    }
    return country;
  }

  function shippingZoneForCountry(country) {
    return country === "US" ? "US" : "international";
  }

  function applyCheckoutEnabled() {
    const countryOk = selectedShipCountry() !== null;
    document.querySelectorAll("[data-store-checkout]").forEach(function (btn) {
      if (btn.classList.contains("piwalletsv-store-oos")) {
        return;
      }
      btn.disabled = !countryOk;
      if (countryOk) {
        btn.removeAttribute("aria-disabled");
        btn.removeAttribute("title");
      } else {
        btn.setAttribute("aria-disabled", "true");
        btn.title = "Select where to ship first";
      }
    });
  }

  function applyStockUi() {
    document.querySelectorAll("[data-store-stock]").forEach(function (el) {
      const sku = el.getAttribute("data-store-stock");
      const info = stockBySku[sku];
      if (!info) {
        el.hidden = true;
        return;
      }
      el.hidden = false;
      if (!info.track_inventory || info.in_stock) {
        el.className = "piwalletsv-store-stock piwalletsv-store-stock--in";
        el.textContent = "IN STOCK";
      } else {
        el.className = "piwalletsv-store-stock piwalletsv-store-stock--out";
        el.textContent = "OUT OF STOCK";
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
      btn.classList.remove("piwalletsv-store-oos");
      if (info && info.track_inventory && !info.in_stock) {
        btn.disabled = true;
        btn.classList.add("piwalletsv-store-oos");
        btn.setAttribute("aria-disabled", "true");
        btn.title = "Out of stock";
        return;
      }
    });
    applyCheckoutEnabled();
  }

  async function loadInventory() {
    try {
      const resp = await fetch(apiUrl + "/v1/inventory");
      const data = await resp.json();
      if (!resp.ok) {
        applyCheckoutEnabled();
        return;
      }
      (data.products || []).forEach(function (p) {
        stockBySku[p.sku] = p;
      });
      applyStockUi();
    } catch (_err) {
      applyCheckoutEnabled();
    }
  }

  async function postCheckout(path, sku, shippingZone) {
    const resp = await fetch(apiUrl + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sku: sku, shipping_zone: shippingZone }),
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

  const countrySelect = document.querySelector("[data-store-ship-country]");
  if (countrySelect) {
    countrySelect.addEventListener("change", applyCheckoutEnabled);
  }
  applyCheckoutEnabled();
  loadInventory();

  document.querySelectorAll("[data-store-checkout]").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      const sku = btn.getAttribute("data-sku");
      const method = btn.getAttribute("data-store-checkout");
      if (!sku || !method) {
        return;
      }
      const country = selectedShipCountry();
      if (!country) {
        showError(btn, "Select where to ship first.");
        return;
      }
      const zone = shippingZoneForCountry(country);
      setBusy(btn, true);
      try {
        if (method === "stripe") {
          const data = await postCheckout("/v1/checkout/stripe", sku, zone);
          if (data.checkout_url) {
            window.location.href = data.checkout_url;
            return;
          }
          throw new Error("missing checkout URL");
        }
        if (method === "bsv") {
          window.location.href =
            "/store/checkout-bsv/?sku=" +
            encodeURIComponent(sku) +
            "&country=" +
            encodeURIComponent(country);
          return;
        }
      } catch (err) {
        showError(btn, err.message || String(err));
        setBusy(btn, false);
        applyCheckoutEnabled();
        if ((err.message || "").indexOf("Out of stock") >= 0) {
          loadInventory();
        }
      }
    });
  });

  // Success page: one-shot status (Checkout only redirects here after payment)
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

      void (async function loadSuccess() {
        const resp = await fetch(apiUrl + "/v1/orders/" + encodeURIComponent(orderId));
        const data = await resp.json();
        if (!resp.ok) {
          return;
        }
        const statusEl = successEl.querySelector("[data-order-status-label]");
        if (statusEl) {
          if (data.status === "shipped") {
            statusEl.textContent = "Shipped";
          } else if (data.status === "fulfilled") {
            statusEl.textContent = "Ready to ship";
          } else if (data.status === "cancelled") {
            statusEl.textContent = "Cancelled";
          } else if (data.status === "refunded") {
            statusEl.textContent = "Refunded";
          } else {
            statusEl.textContent = "Payment confirmed";
          }
        }
        const trackingNote = successEl.querySelector("[data-tracking-note]");
        if (trackingNote) {
          const safeUrl =
            data.shipment && data.shipment.tracking_url
              ? (function (url) {
                  const raw = String(url || "").trim();
                  if (!/^https:\/\//i.test(raw)) {
                    return "";
                  }
                  try {
                    const parsed = new URL(raw);
                    return parsed.protocol === "https:" ? parsed.href : "";
                  } catch (_err) {
                    return "";
                  }
                })(data.shipment.tracking_url)
              : "";
          trackingNote.hidden = !safeUrl;
          if (!trackingNote.hidden) {
            const link = trackingNote.querySelector("[data-tracking-link]");
            if (link) {
              link.href = safeUrl;
              link.rel = "noopener noreferrer";
              link.target = "_blank";
            }
          }
        }
      })();
    }
  }
})();
