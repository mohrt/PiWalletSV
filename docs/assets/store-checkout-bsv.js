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

  const COUNTRY_FIELD_COPY = {
    US: { state: "State", postal: "ZIP code", postalPlaceholder: "78701" },
    CA: { state: "Province", postal: "Postal code", postalPlaceholder: "A1A 1A1" },
    GB: { state: "County (optional)", postal: "Postcode", postalPlaceholder: "SW1A 1AA" },
    AU: { state: "State / territory", postal: "Postcode", postalPlaceholder: "2000" },
    DE: { state: "Region (optional)", postal: "Postcode", postalPlaceholder: "10115" },
    FR: { state: "Region (optional)", postal: "Postcode", postalPlaceholder: "75001" },
  };

  function formatUsd(cents) {
    return "$" + (Number(cents) / 100).toFixed(2);
  }

  function displayProductName(name) {
    return String(name || "")
      .replace(/\s*\(Round\s*1\)\s*/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function satsToBsvDisplay(sats) {
    return (Number(sats) / 100000000).toFixed(8).replace(/\.?0+$/, "") + " BSV";
  }

  function applyCountryFieldCopy(country) {
    const copy = COUNTRY_FIELD_COPY[country] || COUNTRY_FIELD_COPY.US;
    const stateLabel = form.querySelector("[data-state-label]");
    const postalLabel = form.querySelector("[data-postal-label]");
    const postalInput = form.querySelector('input[name="postal_code"]');
    if (stateLabel) {
      stateLabel.textContent = copy.state;
    }
    if (postalLabel) {
      postalLabel.textContent = copy.postal;
    }
    if (postalInput) {
      postalInput.placeholder = copy.postalPlaceholder;
    }
  }

  function showError(message) {
    if (!errorEl) {
      return;
    }
    errorEl.hidden = !message;
    errorEl.textContent = message || "";
  }

  function setBusy(busy, activeBtn) {
    if (submitBtn) {
      submitBtn.disabled = busy;
      submitBtn.setAttribute(
        "aria-busy",
        busy && (!activeBtn || activeBtn === submitBtn) ? "true" : "false"
      );
    }
    if (sendVerifyBtn) {
      sendVerifyBtn.disabled = busy;
      sendVerifyBtn.setAttribute(
        "aria-busy",
        busy && activeBtn === sendVerifyBtn ? "true" : "false"
      );
    }
  }

  function tokenExpiresAt(token) {
    if (!token || token.indexOf(".") < 0) {
      return null;
    }
    try {
      const bodyPart = token.split(".")[0];
      const pad = "===".slice((bodyPart.length + 3) % 4);
      const json = atob(bodyPart.replace(/-/g, "+").replace(/_/g, "/") + pad);
      const payload = JSON.parse(json);
      const exp = payload && payload.exp;
      return typeof exp === "number" ? exp : null;
    } catch (_err) {
      return null;
    }
  }

  function isSessionTokenExpired(session) {
    if (!session || !session.email_verification_token) {
      return true;
    }
    const exp = tokenExpiresAt(session.email_verification_token);
    if (exp == null) {
      return true;
    }
    return exp < Math.floor(Date.now() / 1000);
  }

  function isAuthTokenError(message) {
    const text = String(message || "").toLowerCase();
    return (
      text.indexOf("token expired") >= 0 ||
      text.indexOf("invalid token") >= 0 ||
      text.indexOf("token signature") >= 0 ||
      text.indexOf("token purpose") >= 0 ||
      text.indexOf("token does not match") >= 0 ||
      text.indexOf("verify your email") >= 0
    );
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

  function clearSession() {
    sessionStorage.removeItem(SESSION_KEY);
  }

  function resetToEmailStep(message) {
    clearSession();
    if (quoteEl) {
      quoteEl.hidden = true;
    }
    if (shippingStep) {
      shippingStep.hidden = true;
    }
    if (emailStep) {
      emailStep.hidden = false;
    }
    if (emailInput) {
      emailInput.readOnly = false;
    }
    if (verifySentEl) {
      verifySentEl.hidden = true;
    }
    if (verifiedEmailEl) {
      verifiedEmailEl.textContent = "…";
    }
    showError(
      message || "Your email verification expired. Send a new link to continue."
    );
    setBusy(false);
  }

  function handleAuthFailure(message) {
    if (!isAuthTokenError(message)) {
      return false;
    }
    resetToEmailStep(
      "Your email verification expired. Send a new link to continue."
    );
    return true;
  }

  function applyVerifiedSession(session) {
    if (!session || !session.customer_email || !session.email_verification_token) {
      return;
    }
    if (isSessionTokenExpired(session)) {
      resetToEmailStep();
      if (emailInput && session.customer_email) {
        emailInput.value = session.customer_email;
      }
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
        if (data.error && handleAuthFailure(data.error)) {
          return;
        }
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
      const bsvEl = quoteEl.querySelector("[data-quote-bsv]");
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
      if (bsvEl && data.bsv_amount_sats != null) {
        bsvEl.textContent = satsToBsvDisplay(data.bsv_amount_sats);
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
    setBusy(true, sendVerifyBtn);
    try {
      const payload = { customer_email: email };
      if (sku) {
        payload.sku = sku;
      }
      const resp = await fetch(apiUrl + "/v1/checkout/bsv/request-verification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        throw new Error(data.error || "could not send verification email");
      }
      if (sendVerifyBtn) {
        sendVerifyBtn.textContent = "Resend verification link";
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

  const existing = readSession();
  if (existing) {
    applyVerifiedSession(existing);
  }

  if (!sku) {
    if (existing) {
      const next = new URL(window.location.href);
      next.searchParams.set("sku", "full-kit");
      window.location.replace(next.toString());
      return;
    }
    showError("Missing sku in URL. Open checkout from the purchase page.");
    setBusy(true);
    return;
  }

  if (!apiUrl) {
    showError("Store API URL is not configured for this build.");
    setBusy(true);
    return;
  }

  if (sendVerifyBtn) {
    sendVerifyBtn.addEventListener("click", sendVerification);
  }

  if (shippingStep) {
    const countrySelect = form.querySelector('select[name="country"]');
    if (countrySelect) {
      applyCountryFieldCopy(countrySelect.value);
      countrySelect.addEventListener("change", function () {
        applyCountryFieldCopy(countrySelect.value);
      });
    }
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
          label.textContent = displayProductName(product.name || sku);
        }
      }
      if (product.track_inventory) {
        if (!product.in_stock) {
          showError("Out of stock — this batch is sold out.");
          setBusy(true);
        }
      }
      if (stockEl) {
        stockEl.hidden = true;
      }
    } catch (_err) {
      /* allow submit if inventory fetch fails */
    }
  }

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    const session = readSession();
    if (!session || isSessionTokenExpired(session)) {
      resetToEmailStep(
        session
          ? undefined
          : "Verify your email before continuing."
      );
      if (session && session.customer_email && emailInput) {
        emailInput.value = session.customer_email;
      }
      return;
    }
    showError("");
    setBusy(true, submitBtn);
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
      clearSession();
      if (data.pending_url) {
        window.location.href = data.pending_url;
        return;
      }
      throw new Error("missing pending URL");
    } catch (err) {
      if (handleAuthFailure(err.message)) {
        if (session.customer_email && emailInput) {
          emailInput.value = session.customer_email;
        }
        return;
      }
      showError(err.message || String(err));
      setBusy(false);
    }
  });

  loadInventory();
})();
