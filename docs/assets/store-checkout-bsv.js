/**
 * BSV checkout — email verification, shipping, live quote, pending payment page.
 */
(function () {
  const cfgEl = document.getElementById("piwalletsv-store-config");
  const form = document.getElementById("piwalletsv-bsv-checkout-form");
  if (!cfgEl || !form) {
    return;
  }

  const apiUrl = (cfgEl.dataset.apiUrl || "").replace(/\/$/, "");
  const devBanner = cfgEl.dataset.devBanner || "";
  const params = new URLSearchParams(window.location.search);
  const sku = (params.get("sku") || "").trim();
  const emailStep = document.getElementById("piwalletsv-bsv-email-step");
  const shippingStep = document.getElementById("piwalletsv-bsv-shipping-step");
  const emailInput = document.getElementById("piwalletsv-bsv-email");
  const sendVerifyBtn = document.getElementById("piwalletsv-bsv-send-verify");
  const verifySentEl = document.getElementById("piwalletsv-bsv-verify-sent");
  const verifiedEmailEl = shippingStep && shippingStep.querySelector("[data-verified-email]");
  const submitBtn = document.getElementById("piwalletsv-bsv-checkout-submit");
  const errorEl = document.getElementById("piwalletsv-bsv-checkout-error");
  const productEl = document.getElementById("piwalletsv-bsv-checkout-product");
  const stockEl = document.getElementById("piwalletsv-bsv-checkout-stock");
  const quoteEl = document.getElementById("piwalletsv-bsv-checkout-quote");

  const SESSION_KEY = "piwalletsv_bsv_email_verification";

  if (devBanner) {
    const banner = document.createElement("div");
    banner.className = "piwalletsv-store-banner";
    banner.textContent = devBanner;
    const main = document.querySelector(".md-content");
    if (main && main.firstChild) {
      main.insertBefore(banner, main.firstChild);
    }
  }

  function formatUsd(cents) {
    return "$" + (Number(cents) / 100).toFixed(2);
  }

  function showError(message) {
    if (!errorEl) {
      return;
    }
    errorEl.hidden = !message;
    errorEl.textContent = message || "";
  }

  function setBusy(busy) {
    if (submitBtn) {
      submitBtn.disabled = busy;
      submitBtn.setAttribute("aria-busy", busy ? "true" : "false");
    }
    if (sendVerifyBtn) {
      sendVerifyBtn.disabled = busy;
    }
  }

  function readSession() {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (!raw) {
        return null;
      }
      return JSON.parse(raw);
    } catch (_err) {
      return null;
    }
  }

  function writeSession(data) {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(data));
  }

  function applyVerifiedSession(session) {
    if (!session || !session.customer_email || !session.email_verification_token) {
      return;
    }
    if (emailInput) {
      emailInput.value = session.customer_email;
      emailInput.readOnly = true;
    }
    if (verifiedEmailEl) {
      verifiedEmailEl.textContent = session.customer_email;
    }
    if (emailStep) {
      emailStep.hidden = true;
    }
    if (shippingStep) {
      shippingStep.hidden = false;
    }
  }

  function checkoutBodyFromForm() {
    const session = readSession();
    const fd = new FormData(form);
    return {
      sku: sku,
      customer_email: session ? session.customer_email : String(fd.get("customer_email") || "").trim(),
      email_verification_token: session ? session.email_verification_token : "",
      shipping_name: String(fd.get("shipping_name") || "").trim(),
      shipping_address: {
        line1: String(fd.get("line1") || "").trim(),
        line2: String(fd.get("line2") || "").trim(),
        city: String(fd.get("city") || "").trim(),
        state: String(fd.get("state") || "").trim(),
        postal_code: String(fd.get("postal_code") || "").trim(),
        country: String(fd.get("country") || "").trim().toUpperCase(),
      },
    };
  }

  function canQuote(body) {
    const a = body.shipping_address;
    return (
      body.customer_email &&
      body.email_verification_token &&
      a.line1 &&
      a.city &&
      a.postal_code &&
      a.country &&
      a.country.length === 2
    );
  }

  let quoteTimer = null;

  function scheduleQuote() {
    if (!quoteEl) {
      return;
    }
    clearTimeout(quoteTimer);
    quoteTimer = setTimeout(refreshQuote, 400);
  }

  async function refreshQuote() {
    if (!quoteEl) {
      return;
    }
    const body = checkoutBodyFromForm();
    if (!canQuote(body)) {
      quoteEl.hidden = true;
      return;
    }
    try {
      const resp = await fetch(apiUrl + "/v1/checkout/bsv/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        quoteEl.hidden = true;
        if (data.error) {
          showError(data.error);
        }
        return;
      }
      showError("");
      quoteEl.hidden = false;
      const shipEl = quoteEl.querySelector("[data-quote-shipping]");
      const taxEl = quoteEl.querySelector("[data-quote-tax]");
      const totalEl = quoteEl.querySelector("[data-quote-total]");
      const satsEl = quoteEl.querySelector("[data-quote-sats]");
      if (shipEl) {
        shipEl.textContent =
          (data.shipping_label || "Shipping") + " — " + formatUsd(data.shipping_cents || 0);
      }
      if (taxEl) {
        taxEl.textContent = formatUsd(data.tax_cents || 0);
      }
      if (totalEl) {
        totalEl.textContent = formatUsd(data.total_cents || 0);
      }
      if (satsEl && data.bsv_amount_sats != null) {
        satsEl.textContent = String(data.bsv_amount_sats) + " sats (exact)";
      }
    } catch (_err) {
      quoteEl.hidden = true;
    }
  }

  async function sendVerification() {
    showError("");
    const email = emailInput ? String(emailInput.value || "").trim() : "";
    if (!email || email.indexOf("@") < 0) {
      showError("Enter a valid email address.");
      return;
    }
    setBusy(true);
    try {
      const resp = await fetch(apiUrl + "/v1/checkout/bsv/request-verification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_email: email }),
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        throw new Error(data.error || "could not send verification email");
      }
      if (verifySentEl) {
        verifySentEl.hidden = false;
      }
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!sku) {
    showError("Missing sku in URL. Open checkout from the purchase page.");
    setBusy(true);
    return;
  }

  if (!apiUrl) {
    showError("Store API URL is not configured for this build.");
    setBusy(true);
    return;
  }

  const existing = readSession();
  if (existing) {
    applyVerifiedSession(existing);
  }

  if (sendVerifyBtn) {
    sendVerifyBtn.addEventListener("click", sendVerification);
  }

  if (shippingStep) {
    shippingStep.querySelectorAll("input, select").forEach(function (input) {
      input.addEventListener("input", scheduleQuote);
      input.addEventListener("change", scheduleQuote);
    });
  }

  async function loadInventory() {
    try {
      const resp = await fetch(apiUrl + "/v1/inventory");
      const data = await resp.json();
      if (!resp.ok) {
        return;
      }
      const product = (data.products || []).find(function (p) {
        return p.sku === sku;
      });
      if (!product) {
        showError("Unknown product: " + sku);
        setBusy(true);
        return;
      }
      if (productEl) {
        productEl.hidden = false;
        const label = productEl.querySelector("[data-product-label]");
        if (label) {
          label.textContent = product.name || sku;
        }
      }
      if (product.track_inventory && stockEl) {
        stockEl.hidden = false;
        if (product.in_stock) {
          stockEl.className = "piwalletsv-store-stock piwalletsv-store-stock--in";
          stockEl.textContent =
            product.available === 1
              ? "1 kit left in this batch."
              : product.available + " kits left in this batch.";
        } else {
          stockEl.className = "piwalletsv-store-stock piwalletsv-store-stock--out";
          stockEl.textContent = "Out of stock for this batch.";
          showError("Out of stock — this batch is sold out.");
          setBusy(true);
        }
      }
    } catch (_err) {
      /* allow submit if inventory fetch fails */
    }
  }

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    if (!readSession()) {
      showError("Verify your email before continuing.");
      return;
    }
    showError("");
    setBusy(true);
    const body = checkoutBodyFromForm();
    try {
      const resp = await fetch(apiUrl + "/v1/checkout/bsv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
      sessionStorage.removeItem(SESSION_KEY);
      if (data.pending_url) {
        window.location.href = data.pending_url;
        return;
      }
      throw new Error("missing pending URL");
    } catch (err) {
      showError(err.message || String(err));
      setBusy(false);
    }
  });

  loadInventory();
})();
