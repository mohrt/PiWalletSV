/**
 * Donation page — allocate next HD receive address from the store API.
 */
(function () {
  const cfgEl = document.getElementById("piwalletsv-store-config");
  const root = document.getElementById("piwalletsv-donate");
  if (!cfgEl || !root) {
    return;
  }

  const apiUrl = (cfgEl.dataset.apiUrl || "").replace(/\/$/, "");
  if (!apiUrl) {
    root.textContent = "Donations are not configured for this build.";
    return;
  }

  const STORAGE_KEY = "piwalletsv_donate_address_v1";
  const errorEl = root.querySelector("[data-donate-error]");
  const panel = root.querySelector("[data-donate-panel]");
  const loadingEl = root.querySelector("[data-donate-loading]");
  const networkEl = root.querySelector("[data-donate-network]");
  const addressEl = root.querySelector("[data-donate-address]");
  const qrWrap = root.querySelector(".piwalletsv-bsv-qr-wrap");
  const copyBtn = root.querySelector("[data-copy-address]");

  function showError(msg) {
    if (!errorEl) {
      return;
    }
    if (!msg) {
      errorEl.hidden = true;
      errorEl.textContent = "";
      return;
    }
    errorEl.hidden = false;
    errorEl.textContent = msg;
  }

  function renderQr(uri, attempt) {
    const qrImg = root.querySelector("[data-donate-qr]");
    if (!qrImg || !uri) {
      return;
    }
    if (typeof window.qrcode !== "function") {
      if ((attempt || 0) < 20) {
        setTimeout(function () {
          renderQr(uri, (attempt || 0) + 1);
        }, 50);
      }
      return;
    }
    try {
      const qr = window.qrcode(0, "M");
      qr.addData(uri);
      qr.make();
      qrImg.src = qr.createDataURL(6, 12);
      qrImg.alt = "QR code for BSV donation";
      qrImg.removeAttribute("hidden");
      qrImg.hidden = false;
      if (qrWrap) {
        qrWrap.hidden = false;
      }
    } catch (_err) {
      qrImg.hidden = true;
      if (qrWrap) {
        qrWrap.hidden = true;
      }
    }
  }

  function showAddress(data) {
    if (loadingEl) {
      loadingEl.hidden = true;
    }
    if (panel) {
      panel.hidden = false;
    }
    if (networkEl) {
      const net =
        data.network === "mainnet"
          ? "Bitcoin SV mainnet"
          : "Bitcoin SV testnet (dev)";
      networkEl.textContent = "Network: " + net;
    }
    if (addressEl) {
      addressEl.textContent = data.address || "";
    }
    const uri = data.uri || (data.address ? "bitcoin:" + data.address : "");
    // Defer so the panel is visible and any late script init can finish.
    setTimeout(function () {
      renderQr(uri, 0);
    }, 0);
  }

  function readCached() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return null;
      }
      const data = JSON.parse(raw);
      if (!data || !data.address) {
        return null;
      }
      if (!data.uri && data.address) {
        data.uri = "bitcoin:" + data.address;
      }
      return data;
    } catch (_err) {
      return null;
    }
  }

  function writeCached(data) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (_err) {
      /* ignore quota / private mode */
    }
  }

  function setCopyFeedback(btn, ok) {
    if (!btn.dataset.copyLabel) {
      btn.dataset.copyLabel = btn.getAttribute("aria-label") || "Copy";
    }
    const idle = btn.dataset.copyLabel;
    const message = ok ? "Copied" : "Copy failed";
    btn.classList.toggle("is-copied", ok);
    btn.classList.toggle("is-copy-failed", !ok);
    btn.setAttribute("aria-label", message);
    btn.setAttribute("title", message);

    let badge =
      btn.parentElement &&
      btn.parentElement.querySelector(".piwalletsv-bsv-copy-feedback");
    if (!badge && btn.parentElement) {
      badge = document.createElement("span");
      badge.className = "piwalletsv-bsv-copy-feedback";
      badge.setAttribute("aria-live", "polite");
      btn.parentElement.appendChild(badge);
    }
    if (badge) {
      badge.textContent = message;
      badge.classList.toggle("is-copy-failed", !ok);
      badge.hidden = false;
    }

    clearTimeout(btn._copyFeedbackTimer);
    btn._copyFeedbackTimer = setTimeout(function () {
      btn.classList.remove("is-copied", "is-copy-failed");
      btn.setAttribute("aria-label", idle);
      btn.setAttribute("title", idle);
      if (badge) {
        badge.hidden = true;
        badge.classList.remove("is-copy-failed");
      }
    }, 1800);
  }

  async function allocate() {
    showError("");
    const cached = readCached();
    if (cached) {
      showAddress(cached);
      return;
    }
    if (loadingEl) {
      loadingEl.hidden = false;
    }
    if (panel) {
      panel.hidden = true;
    }
    if (qrWrap) {
      qrWrap.hidden = true;
    }
    try {
      const resp = await fetch(apiUrl + "/v1/donate/address", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        throw new Error(data.error || "could not allocate donation address");
      }
      writeCached(data);
      showAddress(data);
    } catch (err) {
      if (loadingEl) {
        loadingEl.hidden = true;
      }
      showError(err.message || String(err));
    }
  }

  if (qrWrap) {
    qrWrap.hidden = true;
  }

  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      const text = addressEl ? addressEl.textContent : "";
      if (!text || !navigator.clipboard) {
        setCopyFeedback(copyBtn, false);
        return;
      }
      navigator.clipboard.writeText(text).then(
        function () {
          setCopyFeedback(copyBtn, true);
        },
        function () {
          setCopyFeedback(copyBtn, false);
        }
      );
    });
  }

  allocate();
})();
