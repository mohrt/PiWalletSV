/**
 * BSV pending payment page — USD breakdown, exact sats, QR, partial recovery.
 */
(function () {
  const cfgEl = document.getElementById("piwalletsv-store-config");
  const pendingEl = document.getElementById("piwalletsv-bsv-pending");
  if (!cfgEl || !pendingEl) {
    return;
  }

  const apiUrl = (cfgEl.dataset.apiUrl || "").replace(/\/$/, "");
  const orderId = new URLSearchParams(window.location.search).get("order_id");
  const debug =
    !!cfgEl.dataset.devBanner ||
    /\.dev\./.test(window.location.hostname) ||
    /\.dev\./.test(apiUrl) ||
    new URLSearchParams(window.location.search).get("debug") === "1";

  function debugLog() {
    if (!debug) {
      return;
    }
    const args = Array.prototype.slice.call(arguments);
    args.unshift("[bsv-pending]");
    console.log.apply(console, args);
  }

  function displayProductName(name) {
    return String(name || "")
      .replace(/\s*\(Round\s*1\)\s*/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function formatUsd(cents) {
    return "$" + (Number(cents) / 100).toFixed(2);
  }

  function satsToBsvDisplay(sats) {
    return (Number(sats) / 100000000).toFixed(8).replace(/\.?0+$/, "") + " BSV";
  }

  function satsToBsvUri(sats) {
    return (Number(sats) / 100000000).toFixed(8);
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
    btn.setAttribute("data-feedback", message);

    let badge = btn.parentElement && btn.parentElement.querySelector(".piwalletsv-bsv-copy-feedback");
    if (!badge && btn.parentElement) {
      badge = document.createElement("span");
      badge.className = "piwalletsv-bsv-copy-feedback";
      badge.setAttribute("aria-live", "polite");
      btn.parentElement.appendChild(badge);
    }
    if (badge) {
      badge.textContent = message;
      badge.classList.toggle("is-copied", ok);
      badge.classList.toggle("is-copy-failed", !ok);
      badge.hidden = false;
    }

    clearTimeout(btn._copyFeedbackTimer);
    btn._copyFeedbackTimer = setTimeout(function () {
      btn.classList.remove("is-copied", "is-copy-failed");
      btn.removeAttribute("data-feedback");
      btn.setAttribute("aria-label", idle);
      btn.setAttribute("title", idle);
      if (badge) {
        badge.hidden = true;
        badge.classList.remove("is-copied", "is-copy-failed");
      }
    }, 1800);
  }

  function bindCopy(btn, getText) {
    if (!btn || btn.dataset.bound) {
      return;
    }
    btn.dataset.bound = "1";
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(getText()).then(
        function () {
          setCopyFeedback(btn, true);
        },
        function () {
          setCopyFeedback(btn, false);
        }
      );
    });
  }

  if (!orderId) {
    pendingEl.textContent = "Missing order_id in URL.";
    return;
  }

  if (!apiUrl) {
    pendingEl.textContent = "Store API URL is not configured for this build.";
    return;
  }

  const orderIdEl = pendingEl.querySelector("[data-order-id]");
  if (orderIdEl) {
    orderIdEl.textContent = orderId;
  }

  let lastPaySats = null;
  let pollTimer = null;
  let cancelling = false;

  const waitingBanner = pendingEl.querySelector("[data-waiting-banner]");
  const waitingTitle = pendingEl.querySelector("[data-waiting-title]");
  const waitingCopy = pendingEl.querySelector("[data-waiting-copy]");
  const cancelBlock = pendingEl.querySelector("[data-cancel-block]");
  const cancelBtn = document.getElementById("piwalletsv-bsv-cancel");
  const cancelPanel = pendingEl.querySelector("[data-cancel-panel]");
  const cancelConfirm = pendingEl.querySelector("[data-cancel-confirm]");
  const cancelBack = pendingEl.querySelector("[data-cancel-back]");
  const cancelError = pendingEl.querySelector("[data-cancel-error]");

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function showCancelError(message) {
    if (!cancelError) {
      return;
    }
    cancelError.hidden = !message;
    cancelError.textContent = message || "";
  }

  function setWaitingState(kind) {
    if (!waitingBanner) {
      return;
    }
    if (!kind) {
      waitingBanner.hidden = true;
      return;
    }
    waitingBanner.hidden = false;
    waitingBanner.classList.toggle("is-partial", kind === "partial");
    if (waitingTitle) {
      waitingTitle.textContent =
        kind === "partial" ? "Waiting for remaining payment" : "Waiting for payment";
    }
    if (waitingCopy) {
      waitingCopy.textContent =
        kind === "partial"
          ? "Partial funds detected. Send the remaining sats to the same address."
          : "This page checks the blockchain every 15 seconds. Keep it open after you send.";
    }
  }

  function updateQr(address, sats) {
    const qrImg = pendingEl.querySelector("[data-bsv-qr]");
    const uriRow = pendingEl.querySelector(".piwalletsv-bsv-uri-row");
    const uriEl = pendingEl.querySelector("[data-bsv-uri]");
    if (!qrImg || sats == null) {
      return;
    }
    const uri = "bitcoin:" + address + "?amount=" + satsToBsvUri(sats);
    qrImg.src =
      "https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=" +
      encodeURIComponent(uri);
    qrImg.alt = "QR code for BSV payment";
    qrImg.hidden = false;
    if (uriRow) {
      uriRow.hidden = false;
    }
    if (uriEl) {
      uriEl.textContent = uri;
    }
    bindCopy(pendingEl.querySelector("[data-copy-uri]"), function () {
      return uri;
    });
  }

  async function cancelOrder() {
    showCancelError("");
    cancelling = true;
    if (cancelConfirm) {
      cancelConfirm.disabled = true;
      cancelConfirm.setAttribute("aria-busy", "true");
    }
    if (cancelBack) {
      cancelBack.disabled = true;
    }
    try {
      const resp = await fetch(
        apiUrl + "/v1/orders/" + encodeURIComponent(orderId) + "/cancel",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        }
      );
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        throw new Error(data.error || "could not cancel order");
      }
      stopPolling();
      await refresh();
    } catch (err) {
      showCancelError(err.message || String(err));
      cancelling = false;
      if (cancelConfirm) {
        cancelConfirm.disabled = false;
        cancelConfirm.setAttribute("aria-busy", "false");
      }
      if (cancelBack) {
        cancelBack.disabled = false;
      }
    }
  }

  if (cancelBtn && cancelPanel) {
    cancelBtn.addEventListener("click", function () {
      showCancelError("");
      cancelPanel.hidden = false;
      cancelBtn.hidden = true;
    });
  }
  if (cancelBack && cancelPanel && cancelBtn) {
    cancelBack.addEventListener("click", function () {
      cancelPanel.hidden = true;
      cancelBtn.hidden = false;
      showCancelError("");
    });
  }
  if (cancelConfirm) {
    cancelConfirm.addEventListener("click", cancelOrder);
  }

  async function refresh() {
    const url = apiUrl + "/v1/orders/" + encodeURIComponent(orderId);
    debugLog("poll", url);
    const resp = await fetch(url);
    const data = await resp.json();
    debugLog("poll result", {
      http: resp.status,
      status: data.status,
      bsv_amount_sats: data.bsv_amount_sats,
      bsv_received_sats: data.bsv_received_sats,
      bsv_payment_state: data.bsv_payment_state,
      bsv_receive_address: data.bsv_receive_address,
      error: data.error,
    });
    if (!resp.ok) {
      pendingEl.textContent = data.error || "Could not load order.";
      stopPolling();
      return;
    }

    const statusEl = pendingEl.querySelector("[data-order-status]");
    if (statusEl) {
      statusEl.textContent = data.status;
    }
    if (data.product_name) {
      const productEl = pendingEl.querySelector("[data-product-name]");
      if (productEl) {
        productEl.textContent = displayProductName(data.product_name);
      }
    }
    if (data.bsv_reference) {
      const refEl = pendingEl.querySelector("[data-bsv-reference]");
      if (refEl) {
        refEl.textContent = data.bsv_reference;
      }
    }

    function showUsdRow(name, text) {
      const row = pendingEl.querySelector('[data-usd-row="' + name + '"]');
      const el = pendingEl.querySelector("[data-usd-" + name + "]");
      if (row && el && text != null) {
        row.hidden = false;
        el.textContent = text;
      }
    }

    if (data.item_subtotal_cents != null) {
      showUsdRow("item", formatUsd(data.item_subtotal_cents));
    }
    if (data.shipping_cents != null) {
      const label = data.shipping_label ? data.shipping_label + " — " : "";
      showUsdRow("shipping", label + formatUsd(data.shipping_cents));
    }
    if (data.tax_cents != null) {
      showUsdRow("tax", formatUsd(data.tax_cents));
    }
    if (data.total_cents != null) {
      showUsdRow("total", formatUsd(data.total_cents));
    }

    const expected = data.bsv_amount_sats != null ? Number(data.bsv_amount_sats) : null;
    const received = data.bsv_received_sats != null ? Number(data.bsv_received_sats) : 0;
    const isPaid =
      data.status === "paid" || data.status === "fulfilled" || data.status === "shipped";
    const isCancelled = data.status === "cancelled";
    const isPartial =
      !isPaid && !isCancelled && expected != null && received > 0 && received < expected;
    const canCancel = data.status === "pending_bsv" && received === 0;

    if (expected != null) {
      const satsEl = pendingEl.querySelector("[data-bsv-sats]");
      const bsvEl = pendingEl.querySelector("[data-bsv-amount]");
      if (satsEl) {
        satsEl.textContent = String(expected) + " sats";
      }
      if (bsvEl) {
        bsvEl.textContent = satsToBsvDisplay(expected);
      }
      bindCopy(pendingEl.querySelector("[data-copy-sats]"), function () {
        return String(expected);
      });
      bindCopy(pendingEl.querySelector("[data-copy-bsv]"), function () {
        return satsToBsvUri(expected);
      });
    }

    if (data.bsv_receive_address) {
      const addrEl = pendingEl.querySelector("[data-bsv-address]");
      const payBlock = pendingEl.querySelector("[data-pay-instructions]");
      if (addrEl) {
        addrEl.textContent = data.bsv_receive_address;
      }
      if (payBlock && !isPaid && !isCancelled) {
        payBlock.hidden = false;
      }
      bindCopy(pendingEl.querySelector("[data-copy-address]"), function () {
        return data.bsv_receive_address;
      });

      let qrSats = expected;
      if (!isPaid && received > 0 && expected != null && received < expected) {
        qrSats = expected - received;
      }
      if (!isPaid && !isCancelled && qrSats != null && qrSats !== lastPaySats) {
        lastPaySats = qrSats;
        updateQr(data.bsv_receive_address, qrSats);
      } else if (!isPaid && !isCancelled && qrSats != null && lastPaySats == null) {
        lastPaySats = qrSats;
        updateQr(data.bsv_receive_address, qrSats);
      }
    }

    const partialNote = pendingEl.querySelector("[data-partial-note]");
    if (partialNote && isPartial) {
      partialNote.hidden = false;
      const recvEl = partialNote.querySelector("[data-partial-received]");
      const reqEl = partialNote.querySelector("[data-partial-required]");
      const shortEl = partialNote.querySelector("[data-partial-shortfall]");
      if (recvEl) {
        recvEl.textContent = String(received);
      }
      if (reqEl) {
        reqEl.textContent = String(expected);
      }
      if (shortEl) {
        shortEl.textContent = String(expected - received);
      }
    } else if (partialNote) {
      partialNote.hidden = true;
    }

    if (isPaid) {
      debugLog("payment confirmed — redirecting to success");
      stopPolling();
      window.location.replace(
        "/store/success/?order_id=" + encodeURIComponent(orderId)
      );
      return;
    }

    if (isCancelled) {
      debugLog("order cancelled — stopping poll");
      stopPolling();
      setWaitingState(null);
      const payBlock = pendingEl.querySelector("[data-pay-instructions]");
      if (payBlock) {
        payBlock.hidden = true;
      }
      if (cancelBlock) {
        cancelBlock.hidden = true;
      }
      const cancelNote = pendingEl.querySelector("[data-cancelled-note]");
      if (cancelNote) {
        cancelNote.hidden = false;
      }
      return;
    }

    setWaitingState(isPartial ? "partial" : "waiting");
    if (cancelBlock) {
      cancelBlock.hidden = !canCancel;
      if (!canCancel && cancelPanel) {
        cancelPanel.hidden = true;
        if (cancelBtn) {
          cancelBtn.hidden = false;
        }
      }
    }
  }

  if (debug) {
    debugLog("debug logging enabled", { orderId: orderId, apiUrl: apiUrl });
  }
  refresh();
  pollTimer = setInterval(function () {
    if (!cancelling) {
      refresh();
    }
  }, 15000);
})();
