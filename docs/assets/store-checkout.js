/**
 * PiWalletSV store checkout — calls store.dev / store API from purchase buttons.
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

  function setBusy(btn, busy) {
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
      throw new Error(data.error || "checkout failed");
    }
    return data;
  }

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
      }
    });
  });

  // BSV pending page: poll order status
  const pendingEl = document.getElementById("piwalletsv-bsv-pending");
  if (pendingEl && apiUrl) {
    const orderId = new URLSearchParams(window.location.search).get("order_id");
    if (!orderId) {
      pendingEl.textContent = "Missing order_id in URL.";
      return;
    }

    async function refresh() {
      const resp = await fetch(apiUrl + "/v1/orders/" + encodeURIComponent(orderId));
      const data = await resp.json();
      if (!resp.ok) {
        pendingEl.textContent = data.error || "Could not load order.";
        return;
      }
      pendingEl.querySelector("[data-order-status]").textContent = data.status;
      if (data.bsv_address) {
        pendingEl.querySelector("[data-bsv-address]").textContent = data.bsv_address;
      }
      if (data.bsv_amount_sats) {
        pendingEl.querySelector("[data-bsv-amount]").textContent = String(data.bsv_amount_sats);
      }
      if (data.bsv_reference) {
        pendingEl.querySelector("[data-bsv-reference]").textContent = data.bsv_reference;
      }
      if (data.status === "paid" || data.status === "fulfilled") {
        pendingEl.querySelector("[data-paid-note]").hidden = false;
      }
    }

    refresh();
    setInterval(refresh, 15000);
  }
})();
