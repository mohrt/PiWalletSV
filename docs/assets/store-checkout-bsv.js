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
  const validateBtn = document.getElementById("piwalletsv-bsv-validate-address");
  const submitBtn = document.getElementById("piwalletsv-bsv-checkout-submit");
  const errorEl = document.getElementById("piwalletsv-bsv-checkout-error");
  const productEl = document.getElementById("piwalletsv-bsv-checkout-product");
  const stockEl = document.getElementById("piwalletsv-bsv-checkout-stock");
  const quoteEl = document.getElementById("piwalletsv-bsv-checkout-quote");
  const addressCheckEl = document.getElementById("piwalletsv-bsv-address-check");
  const addressModal = document.getElementById("piwalletsv-bsv-address-modal");
  const correctedAddressEl =
    addressModal && addressModal.querySelector("[data-corrected-address]");

  const SESSION_KEY = "piwalletsv_bsv_email_verification";
  const DEST_COUNTRY_KEY = "piwalletsv_bsv_ship_country";
  let addressValidated = false;
  let quoteSeq = 0;
  let submitting = false;
  let pendingCorrectedAddress = null;

  const COUNTRY_FIELD_COPY = {
    US: { state: "State", postal: "ZIP code", postalPlaceholder: "78701" },
    CA: { state: "Province", postal: "Postal code", postalPlaceholder: "A1A 1A1" },
    GB: { state: "County (optional)", postal: "Postcode", postalPlaceholder: "SW1A 1AA" },
    AU: { state: "State / territory", postal: "Postcode", postalPlaceholder: "2000" },
    DE: { state: "Region (optional)", postal: "Postcode", postalPlaceholder: "10115" },
    FR: { state: "Region (optional)", postal: "Postcode", postalPlaceholder: "75001" },
    NL: { state: "Province (optional)", postal: "Postcode", postalPlaceholder: "1012 AB" },
    BE: { state: "Province (optional)", postal: "Postcode", postalPlaceholder: "1000" },
    LU: { state: "Canton (optional)", postal: "Postcode", postalPlaceholder: "1009" },
    IE: { state: "County (optional)", postal: "Eircode", postalPlaceholder: "D02 AF30" },
    ES: { state: "Province (optional)", postal: "Postcode", postalPlaceholder: "28001" },
    PT: { state: "District (optional)", postal: "Postcode", postalPlaceholder: "1000-001" },
    IT: { state: "Province (optional)", postal: "Postcode", postalPlaceholder: "00118" },
    AT: { state: "State (optional)", postal: "Postcode", postalPlaceholder: "1010" },
    CH: { state: "Canton (optional)", postal: "Postcode", postalPlaceholder: "8001" },
    SE: { state: "County (optional)", postal: "Postcode", postalPlaceholder: "111 22" },
    NO: { state: "County (optional)", postal: "Postcode", postalPlaceholder: "0150" },
    DK: { state: "Region (optional)", postal: "Postcode", postalPlaceholder: "1050" },
    FI: { state: "Region (optional)", postal: "Postcode", postalPlaceholder: "00100" },
    PL: { state: "Province (optional)", postal: "Postcode", postalPlaceholder: "00-001" },
    CZ: { state: "Region (optional)", postal: "Postcode", postalPlaceholder: "110 00" },
    NZ: { state: "Region (optional)", postal: "Postcode", postalPlaceholder: "6011" },
  };

  const DEFAULT_FIELD_COPY = {
    state: "Region (optional)",
    postal: "Postal code",
    postalPlaceholder: "",
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
    const copy = COUNTRY_FIELD_COPY[country] || DEFAULT_FIELD_COPY;
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
      if (busy) {
        if (!activeBtn || activeBtn === submitBtn) {
          submitting = true;
          submitBtn.disabled = true;
          submitBtn.setAttribute(
            "aria-busy",
            !activeBtn || activeBtn === submitBtn ? "true" : "false"
          );
        }
      } else {
        submitting = false;
        submitBtn.setAttribute("aria-busy", "false");
        syncActionButtons();
      }
    }
    if (validateBtn) {
      validateBtn.disabled = busy;
      validateBtn.setAttribute(
        "aria-busy",
        busy && activeBtn === validateBtn ? "true" : "false"
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

  function syncActionButtons() {
    if (submitting) {
      return;
    }
    const checking =
      addressCheckEl &&
      !addressCheckEl.hidden &&
      addressCheckEl.getAttribute("aria-busy") === "true";

    if (validateBtn) {
      validateBtn.hidden = false;
      validateBtn.disabled = !!addressValidated || !!checking;
      validateBtn.setAttribute(
        "aria-busy",
        checking && !addressValidated ? "true" : "false"
      );
      if (addressValidated) {
        validateBtn.title = "Address already validated";
      } else if (checking) {
        validateBtn.title = "Checking address…";
      } else {
        validateBtn.removeAttribute("title");
      }
    }

    if (!submitBtn) {
      return;
    }
    const allow = !!addressValidated && !checking;
    submitBtn.hidden = !addressValidated;
    submitBtn.disabled = !allow;
    submitBtn.setAttribute("aria-disabled", allow ? "false" : "true");
    submitBtn.type = allow ? "submit" : "button";
    if (allow) {
      submitBtn.removeAttribute("title");
    } else if (checking) {
      submitBtn.title = "Checking address…";
    } else {
      submitBtn.title = "Validate your shipping address first";
    }
  }

  function setAddressChecking(checking) {
    if (addressCheckEl) {
      // Only surface this while a validate/quote request is in flight.
      addressCheckEl.hidden = !checking;
      addressCheckEl.setAttribute("aria-busy", checking ? "true" : "false");
      addressCheckEl.textContent = checking ? "Checking address…" : "";
    }
    if (submitBtn && !submitting) {
      if (checking) {
        submitBtn.disabled = true;
        submitBtn.setAttribute("aria-disabled", "true");
        submitBtn.type = "button";
        submitBtn.setAttribute("aria-busy", "true");
        submitBtn.title = "Checking address…";
      } else {
        submitBtn.setAttribute("aria-busy", "false");
      }
    }
    syncActionButtons();
  }

  function invalidateAddress() {
    addressValidated = false;
    pendingCorrectedAddress = null;
    if (quoteEl) {
      quoteEl.hidden = true;
    }
    syncActionButtons();
  }

  function formatAddressBlock(address) {
    const a = address || {};
    const lines = [];
    if (a.line1) {
      lines.push(a.line1);
    }
    if (a.line2) {
      lines.push(a.line2);
    }
    const cityLine = [a.city, a.state, a.postal_code].filter(Boolean).join(", ");
    if (cityLine) {
      lines.push(cityLine);
    }
    if (a.country) {
      lines.push(a.country);
    }
    return lines.join("\n");
  }

  function fillShippingAddress(address) {
    const a = address || {};
    const setVal = function (name, value) {
      const el = form.querySelector('[name="' + name + '"]');
      if (el) {
        el.value = value || "";
      }
    };
    setVal("line1", a.line1);
    setVal("line2", a.line2);
    setVal("city", a.city);
    setVal("state", a.state);
    setVal("postal_code", a.postal_code);
    if (a.country) {
      setVal("country", String(a.country).toUpperCase());
      applyCountryFieldCopy(String(a.country).toUpperCase());
    }
  }

  function openAddressModal(corrected) {
    pendingCorrectedAddress = corrected || null;
    if (!addressModal || !correctedAddressEl) {
      return;
    }
    correctedAddressEl.textContent = formatAddressBlock(corrected);
    addressModal.hidden = false;
    const acceptBtn = addressModal.querySelector("[data-addr-accept]");
    if (acceptBtn) {
      acceptBtn.focus();
    }
  }

  function closeAddressModal() {
    pendingCorrectedAddress = null;
    if (addressModal) {
      addressModal.hidden = true;
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
    const prev = readSession() || {};
    sessionStorage.setItem(
      SESSION_KEY,
      JSON.stringify(Object.assign({}, prev, data))
    );
  }

  function rememberShipCountry(code) {
    const country = String(code || "")
      .trim()
      .toUpperCase();
    if (country.length === 2) {
      sessionStorage.setItem(DEST_COUNTRY_KEY, country);
      writeSession({ country: country });
    }
  }

  function rememberedShipCountry() {
    const fromStore = (sessionStorage.getItem(DEST_COUNTRY_KEY) || "")
      .trim()
      .toUpperCase();
    if (fromStore.length === 2) {
      return fromStore;
    }
    const session = readSession();
    const fromSession = session && session.country
      ? String(session.country).trim().toUpperCase()
      : "";
    return fromSession.length === 2 ? fromSession : "";
  }

  function clearSession() {
    const country = rememberedShipCountry();
    sessionStorage.removeItem(SESSION_KEY);
    if (country) {
      sessionStorage.setItem(DEST_COUNTRY_KEY, country);
    }
  }

  function clearCheckoutState() {
    sessionStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(DEST_COUNTRY_KEY);
  }

  // Persist shop destination across email verify (redirect drops query params).
  (function stashDestinationFromQuery() {
    const fromQuery = (params.get("country") || "").trim().toUpperCase();
    if (fromQuery.length === 2) {
      rememberShipCountry(fromQuery);
    }
  })();

  function resetToEmailStep(message, options) {
    const opts = options || {};
    clearSession();
    closeAddressModal();
    invalidateAddress();
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
      if (opts.clearEmail) {
        emailInput.value = "";
      }
    }
    if (sendVerifyBtn) {
      sendVerifyBtn.textContent = "Send verification link";
    }
    if (verifySentEl) {
      verifySentEl.hidden = true;
    }
    if (verifiedEmailEl) {
      verifiedEmailEl.textContent = "…";
    }
    showError(
      message === undefined
        ? "Your email verification expired. Send a new link to continue."
        : message || ""
    );
    setBusy(false);
    if (opts.focusEmail && emailInput) {
      emailInput.focus();
    }
  }

  function changeEmail() {
    resetToEmailStep("", { clearEmail: true, focusEmail: true });
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

  function applyPreferredCountry() {
    if (!form) {
      return;
    }
    const countrySelect = form.querySelector('select[name="country"]');
    if (!countrySelect) {
      return;
    }
    const preferred =
      (params.get("country") || "").trim().toUpperCase() ||
      rememberedShipCountry();
    if (
      preferred &&
      countrySelect.querySelector('option[value="' + preferred + '"]')
    ) {
      countrySelect.value = preferred;
      rememberShipCountry(preferred);
    }
    applyCountryFieldCopy(countrySelect.value || "US");
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
      if (session.country) {
        rememberShipCountry(session.country);
      }
      applyPreferredCountry();
      invalidateAddress();
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
      body.shipping_name &&
      a.line1 &&
      a.city &&
      a.postal_code &&
      a.country &&
      a.country.length === 2
    );
  }

  function renderQuote(data) {
    if (!quoteEl) {
      return;
    }
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
  }

  async function fetchFullQuote(seq) {
    const body = checkoutBodyFromForm();
    if (!canQuote(body)) {
      invalidateAddress();
      setAddressChecking(false);
      return false;
    }
    setAddressChecking(true);
    try {
      const resp = await fetch(apiUrl + "/v1/checkout/bsv/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (seq !== quoteSeq) {
        return false;
      }
      if (!resp.ok) {
        invalidateAddress();
        setAddressChecking(false);
        if (data.error && handleAuthFailure(data.error)) {
          return false;
        }
        if (data.error) {
          showError(data.error);
        }
        return false;
      }
      showError("");
      addressValidated = true;
      renderQuote(data);
      setAddressChecking(false);
      syncActionButtons();
      return true;
    } catch (_err) {
      if (seq !== quoteSeq) {
        return false;
      }
      invalidateAddress();
      setAddressChecking(false);
      showError("Could not load quote. Try again.");
      return false;
    }
  }

  async function validateAddress() {
    showError("");
    closeAddressModal();
    const body = checkoutBodyFromForm();
    if (!canQuote(body)) {
      showError("Fill in name and a complete shipping address first.");
      return;
    }
    const seq = ++quoteSeq;
    setAddressChecking(true);
    if (validateBtn) {
      validateBtn.disabled = true;
      validateBtn.setAttribute("aria-busy", "true");
    }
    try {
      const validateResp = await fetch(apiUrl + "/v1/checkout/bsv/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({}, body, { validate_only: true })),
      });
      const validateData = await validateResp.json().catch(function () {
        return {};
      });
      if (seq !== quoteSeq) {
        return;
      }
      if (!validateResp.ok) {
        invalidateAddress();
        setAddressChecking(false);
        if (validateData.error && handleAuthFailure(validateData.error)) {
          return;
        }
        showError(validateData.error || "Address could not be verified.");
        return;
      }

      if (validateData.address_corrected && validateData.shipping_address) {
        setAddressChecking(false);
        if (validateBtn) {
          validateBtn.setAttribute("aria-busy", "false");
          validateBtn.disabled = false;
        }
        openAddressModal(validateData.shipping_address);
        return;
      }

      await fetchFullQuote(seq);
    } catch (_err) {
      if (seq !== quoteSeq) {
        return;
      }
      invalidateAddress();
      setAddressChecking(false);
      showError("Address check failed. Try again.");
    } finally {
      if (validateBtn && !addressValidated) {
        validateBtn.setAttribute("aria-busy", "false");
        validateBtn.disabled = false;
      }
    }
  }

  async function acceptCorrectedAddress() {
    if (!pendingCorrectedAddress) {
      closeAddressModal();
      return;
    }
    fillShippingAddress(pendingCorrectedAddress);
    closeAddressModal();
    const seq = ++quoteSeq;
    await fetchFullQuote(seq);
  }

  function rejectCorrectedAddress() {
    closeAddressModal();
    invalidateAddress();
    showError("");
    const line1 = form.querySelector('input[name="line1"]');
    if (line1) {
      line1.focus();
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
      const country = rememberedShipCountry();
      if (country) {
        payload.country = country;
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

  const changeEmailBtn = document.getElementById("piwalletsv-bsv-change-email");
  if (changeEmailBtn) {
    changeEmailBtn.addEventListener("click", changeEmail);
  }

  if (validateBtn) {
    validateBtn.addEventListener("click", validateAddress);
  }

  if (addressModal) {
    const acceptBtn = addressModal.querySelector("[data-addr-accept]");
    const rejectBtn = addressModal.querySelector("[data-addr-reject]");
    const dismissEls = addressModal.querySelectorAll("[data-addr-dismiss]");
    if (acceptBtn) {
      acceptBtn.addEventListener("click", acceptCorrectedAddress);
    }
    if (rejectBtn) {
      rejectBtn.addEventListener("click", rejectCorrectedAddress);
    }
    dismissEls.forEach(function (el) {
      el.addEventListener("click", rejectCorrectedAddress);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && addressModal && !addressModal.hidden) {
        rejectCorrectedAddress();
      }
    });
  }

  if (shippingStep) {
    const countrySelect = form.querySelector('select[name="country"]');
    if (countrySelect) {
      applyPreferredCountry();
      countrySelect.addEventListener("change", function () {
        rememberShipCountry(countrySelect.value || "");
        applyCountryFieldCopy(countrySelect.value || "US");
        invalidateAddress();
      });
    }
    shippingStep.querySelectorAll("input, select").forEach(function (input) {
      input.addEventListener("input", invalidateAddress);
      input.addEventListener("change", invalidateAddress);
    });
    invalidateAddress();
  }

  syncActionButtons();

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
    if (!addressValidated || submitting) {
      showError("Validate your shipping address first.");
      syncActionButtons();
      return;
    }
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
      clearCheckoutState();
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
