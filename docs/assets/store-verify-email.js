/**
 * BSV checkout email verification landing page.
 */
(function () {
  const cfgEl = document.getElementById("piwalletsv-store-config");
  const statusEl = document.getElementById("piwalletsv-verify-email-status");
  const errorEl = document.getElementById("piwalletsv-verify-email-error");
  const successEl = document.getElementById("piwalletsv-verify-email-success");
  const continueLink = document.getElementById("piwalletsv-verify-email-continue");

  if (!cfgEl || !statusEl) {
    return;
  }

  const apiUrl = (cfgEl.dataset.apiUrl || "").replace(/\/$/, "");
  const params = new URLSearchParams(window.location.search);
  const token = (params.get("token") || "").trim();
  const sku = (params.get("sku") || "").trim();
  const SESSION_KEY = "piwalletsv_bsv_email_verification";

  function showError(message) {
    statusEl.hidden = true;
    if (errorEl) {
      errorEl.hidden = false;
      errorEl.textContent = message;
    }
  }

  async function verify() {
    if (!apiUrl) {
      showError("Store API URL is not configured for this build.");
      return;
    }
    if (!token) {
      showError("Missing verification token. Request a new link from checkout.");
      return;
    }

    try {
      const resp = await fetch(
        apiUrl + "/v1/checkout/bsv/verify-email?" + new URLSearchParams({ token: token }).toString()
      );
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        throw new Error(data.error || "verification failed");
      }

      sessionStorage.setItem(
        SESSION_KEY,
        JSON.stringify({
          customer_email: data.customer_email,
          email_verification_token: data.email_verification_token,
        })
      );

      statusEl.hidden = true;
      if (successEl) {
        successEl.hidden = false;
      }
      if (continueLink) {
        const href =
          "/store/checkout-bsv/?sku=" + encodeURIComponent(sku || "full-kit");
        continueLink.href = href;
      }
    } catch (err) {
      showError(err.message || String(err));
    }
  }

  verify();
})();
