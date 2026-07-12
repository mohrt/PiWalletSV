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
  const devBanner = cfgEl.dataset.devBanner || "";
  const orderId = new URLSearchParams(window.location.search).get("order_id");

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

  function satsToBsvDisplay(sats) {
    return (Number(sats) / 100000000).toFixed(8).replace(/\.?0+$/, "") + " BSV";
  }

  function satsToBsvUri(sats) {
    return (Number(sats) / 100000000).toFixed(8);
  }

  function setCopyFeedback(btn, ok) {
    const prev = btn.textContent;
    btn.textContent = ok ? "Copied" : "Copy failed";
    setTimeout(function () {
      btn.textContent = prev;
    }, 1500);
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

  const track = document.getElementById("piwalletsv-bsv-track-order");
  if (track) {
    track.href = "/store/order-status/?order_id=" + encodeURIComponent(orderId);
  }

  let lastPaySats = null;

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

  async function refresh() {
    const resp = await fetch(apiUrl + "/v1/orders/" + encodeURIComponent(orderId));
    const data = await resp.json();
    if (!resp.ok) {
      pendingEl.textContent = data.error || "Could not load order.";
      return;
    }

    const statusEl = pendingEl.querySelector("[data-order-status]");
    if (statusEl) {
      statusEl.textContent = data.status;
    }
    if (data.product_name) {
      const productEl = pendingEl.querySelector("[data-product-name]");
      if (productEl) {
        productEl.textContent = data.product_name;
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
      if (payBlock && !isPaid) {
        payBlock.hidden = false;
      }
      bindCopy(pendingEl.querySelector("[data-copy-address]"), function () {
        return data.bsv_receive_address;
      });

      let qrSats = expected;
      if (!isPaid && received > 0 && expected != null && received < expected) {
        qrSats = expected - received;
      }
      if (!isPaid && qrSats != null && qrSats !== lastPaySats) {
        lastPaySats = qrSats;
        updateQr(data.bsv_receive_address, qrSats);
      } else if (!isPaid && qrSats != null && lastPaySats == null) {
        lastPaySats = qrSats;
        updateQr(data.bsv_receive_address, qrSats);
      }
    }

    const partialNote = pendingEl.querySelector("[data-partial-note]");
    if (partialNote && !isPaid && expected != null && received > 0 && received < expected) {
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

    const paidNote = pendingEl.querySelector("[data-paid-note]");
    if (paidNote) {
      paidNote.hidden = !isPaid;
    }
    const payBlock = pendingEl.querySelector("[data-pay-instructions]");
    if (payBlock && isPaid) {
      payBlock.hidden = true;
    }
    if (data.status === "cancelled") {
      const cancelNote = pendingEl.querySelector("[data-cancelled-note]");
      if (cancelNote) {
        cancelNote.hidden = false;
      }
    }
  }

  refresh();
  setInterval(refresh, 15000);
})();
