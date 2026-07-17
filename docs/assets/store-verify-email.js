/**
 * BSV checkout email verification landing page.
 */
(function () {
  const cfgEl = document.getElementById("piwalletsv-store-config");
  const statusEl = document.getElementById("piwalletsv-verify-email-status");
  const errorEl = document.getElementById("piwalletsv-verify-email-error");

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

      var prev = {};
      try {
        prev = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "{}") || {};
      } catch (_err) {
        prev = {};
      }
      var country = (
        prev.country ||
        sessionStorage.getItem("piwalletsv_bsv_ship_country") ||
        ""
      )
        .toString()
        .trim()
        .toUpperCase();
      sessionStorage.setItem(
        SESSION_KEY,
        JSON.stringify({
          customer_email: data.customer_email,
          email_verification_token: data.email_verification_token,
          country: country || prev.country || undefined,
        })
      );
      if (country) {
        sessionStorage.setItem("piwalletsv_bsv_ship_country", country);
      }

      var next =
        "/store/checkout-bsv/?sku=" + encodeURIComponent(sku || "full-kit");
      if (country && country.length === 2) {
        next += "&country=" + encodeURIComponent(country);
      }
      window.location.replace(next);
    } catch (err) {
      showError(err.message || String(err));
    }
  }

  verify();
})();
