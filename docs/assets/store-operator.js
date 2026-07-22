/**
 * PiWalletSV store operator console — orders, stock, mark paid / cancel.
 */
(function () {
  const STORAGE_KEY = "piwalletsv_operator_key";
  const ORDER_FILTER_KEY = "piwalletsv_operator_order_filter";
  const ORDER_SEARCH_KEY = "piwalletsv_operator_order_search";
  const cfgEl = document.getElementById("piwalletsv-store-config");
  const root = document.getElementById("piwalletsv-operator");
  if (!cfgEl || !root) {
    return;
  }

  document.body.classList.add("piwalletsv-operator-page");

  const apiUrl = (cfgEl.dataset.apiUrl || "").replace(/\/$/, "");
  if (!apiUrl) {
    root.textContent = "Store API URL is not configured for this build.";
    return;
  }

  const isStoreDev =
    apiUrl.indexOf("store.dev.piwalletsv.com") >= 0 ||
    apiUrl.indexOf("localhost") >= 0 ||
    apiUrl.indexOf("127.0.0.1") >= 0;

  const DEV_STATUSES = [
    "pending_bsv",
    "pending_stripe",
    "paid",
    "fulfilled",
    "shipped",
    "cancelled",
    "refunded",
  ];

  let adminKey = sessionStorage.getItem(STORAGE_KEY) || "";

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text != null) {
      node.textContent = text;
    }
    return node;
  }

  function setBusy(button, busy) {
    if (!button) {
      return;
    }
    button.disabled = !!busy;
    button.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function btn(label, primary) {
    const node = el(
      "button",
      "piwalletsv-operator-btn" + (primary ? " piwalletsv-operator-btn--primary" : ""),
      label
    );
    node.type = "button";
    return node;
  }

  function orderStatusUrl(orderId) {
    if (!orderId) {
      return "";
    }
    return "/store/order-status/?order_id=" + encodeURIComponent(orderId);
  }

  function appendStatusPageLink(order, container) {
    const url = orderStatusUrl(order && order.order_id);
    if (!url) {
      return;
    }
    const statusBtn = btn("Status", false);
    statusBtn.title = "Open customer order status page";
    statusBtn.addEventListener("click", function () {
      window.open(url, "_blank", "noopener,noreferrer");
    });
    container.appendChild(statusBtn);
  }

  function shortId(id) {
    if (!id || id.length <= 12) {
      return id || "—";
    }
    return id.slice(0, 8) + "…";
  }

  function displayProductName(name) {
    return String(name || "")
      .replace(/\s*\(Round\s*1\)\s*/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function statusClass(status) {
    if (!status) {
      return "";
    }
    if (status === "shipped") {
      return "piwalletsv-operator-badge--shipped";
    }
    if (status === "paid" || status === "fulfilled") {
      return "piwalletsv-operator-badge--paid";
    }
    if (status.indexOf("pending") === 0) {
      return "piwalletsv-operator-badge--pending";
    }
    if (status === "cancelled") {
      return "piwalletsv-operator-badge--cancelled";
    }
    if (status === "refunded") {
      return "piwalletsv-operator-badge--refunded";
    }
    return "";
  }

  function needsAction(order) {
    const status = order.status || "";
    return (
      status === "pending_bsv" ||
      status === "pending_stripe" ||
      status === "paid" ||
      status === "fulfilled"
    );
  }

  const ORDER_FILTERS = [
    { id: "action", label: "Needs action" },
    { id: "all", label: "All orders" },
    { id: "pending_stripe", label: "Pending Stripe" },
    { id: "pending_bsv", label: "Pending BSV" },
    { id: "paid", label: "Paid" },
    { id: "fulfilled", label: "Fulfilled" },
    { id: "shipped", label: "Shipped" },
    { id: "refunded", label: "Refunded" },
    { id: "cancelled", label: "Cancelled" },
  ];

  function filterLabel(filterId) {
    const match = ORDER_FILTERS.find(function (item) {
      return item.id === filterId;
    });
    return match ? match.label : "Orders";
  }

  function filterOrders(orders, filterId) {
    if (filterId === "all") {
      return orders;
    }
    if (filterId === "action") {
      return orders.filter(needsAction);
    }
    return orders.filter(function (order) {
      return (order.status || "") === filterId;
    });
  }

  function orderSearchText(order) {
    const shipment = order.shipment || {};
    const parts = [
      order.order_id,
      order.sku,
      order.product_name,
      order.customer_email,
      order.bsv_reference,
      order.status,
      order.payment_method,
      order.stripe_session_id,
      order.stripe_payment_intent_id,
      shipment.tracking_number,
      shipment.carrier,
      formatShipTo(order),
    ];
    return parts
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
  }

  function matchesSearch(order, query) {
    const q = (query || "").trim().toLowerCase();
    if (!q) {
      return true;
    }
    return orderSearchText(order).indexOf(q) !== -1;
  }

  function applyOrderFilters(orders, filterId, searchQuery) {
    return filterOrders(orders, filterId).filter(function (order) {
      return matchesSearch(order, searchQuery);
    });
  }

  function emptyOrdersMessage(filterId, searchQuery) {
    if ((searchQuery || "").trim()) {
      return "No orders match your search.";
    }
    return emptyFilterMessage(filterId);
  }

  function emptyFilterMessage(filterId) {
    return "No " + filterLabel(filterId).toLowerCase() + ".";
  }

  function formatUsd(cents) {
    if (cents == null) {
      return "—";
    }
    return "$" + (cents / 100).toFixed(2);
  }

  function formatWhen(iso) {
    if (!iso) {
      return "—";
    }
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
      return iso.replace("T", " ").replace("+00:00", " UTC");
    }
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function paymentMetaValue(order) {
    const method = (order.payment_method || "—").toUpperCase();
    const stripeUrl =
      order.payment_method === "stripe" ? order.stripe_dashboard_url || null : null;
    if (!stripeUrl) {
      return method;
    }
    const wrap = el("span", "piwalletsv-operator-payment");
    wrap.appendChild(document.createTextNode(method + " · "));
    const link = el("a", "piwalletsv-operator-stripe-link", "View payment");
    link.href = stripeUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    wrap.appendChild(link);
    return wrap;
  }

  function metaRow(label, value, extraClass) {
    const row = el("div", "piwalletsv-operator-order-meta-row" + (extraClass ? " " + extraClass : ""));
    row.appendChild(el("dt", "piwalletsv-operator-order-meta-label", label));
    const dd = el("dd", "piwalletsv-operator-order-meta-value");
    if (typeof value === "string") {
      dd.textContent = value;
    } else if (value) {
      dd.appendChild(value);
    } else {
      dd.textContent = "—";
    }
    row.appendChild(dd);
    return row;
  }

  function setActionError(container, message) {
    let err = container.querySelector(".piwalletsv-operator-action-error");
    if (!message) {
      if (err) {
        err.remove();
      }
      return;
    }
    if (!err) {
      err = el("p", "piwalletsv-operator-action-error");
      container.appendChild(err);
    }
    err.textContent = message;
  }

  function clearPanels(container) {
    container.querySelectorAll(".piwalletsv-operator-panel").forEach(function (node) {
      node.remove();
    });
    setActionError(container, "");
  }

  function appendCancelAction(order, container, copy) {
    const cancelBtn = btn("Cancel order", false);
    cancelBtn.classList.add("piwalletsv-operator-btn--danger");
    cancelBtn.addEventListener("click", function () {
      clearPanels(container);
      const panel = el("div", "piwalletsv-operator-panel");
      panel.appendChild(
        el(
          "p",
          "piwalletsv-operator-panel-copy",
          copy || "Cancel this order? This is logged in order history."
        )
      );
      const row = el("div", "piwalletsv-operator-panel-actions");
      const confirmCancel = btn("Yes, cancel", false);
      confirmCancel.classList.add("piwalletsv-operator-btn--danger");
      const keep = btn("Keep order", false);
      confirmCancel.addEventListener("click", function () {
        setBusy(confirmCancel, true);
        keep.disabled = true;
        api("POST", "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/cancel", {})
          .then(refresh)
          .catch(function (e) {
            setActionError(container, e.message || String(e));
            setBusy(confirmCancel, false);
            keep.disabled = false;
          });
      });
      keep.addEventListener("click", function () {
        clearPanels(container);
      });
      row.appendChild(confirmCancel);
      row.appendChild(keep);
      panel.appendChild(row);
      container.appendChild(panel);
    });
    container.appendChild(cancelBtn);
  }

  function appendDevTools(order, container) {
    if (!isStoreDev) {
      return;
    }
    const tools = el("div", "piwalletsv-operator-dev-tools");
    tools.appendChild(el("p", "piwalletsv-operator-dev-label", "Dev tools"));

    const canSetSats =
      order.status === "pending_bsv" && !(Number(order.bsv_received_sats) > 0);
    if (canSetSats) {
      const row = el("div", "piwalletsv-operator-panel-actions");
      const input = el("input", "piwalletsv-operator-input");
      input.type = "number";
      input.min = "1";
      input.step = "1";
      input.value = "1000";
      input.setAttribute("aria-label", "BSV amount sats");
      const apply = btn("Set BSV amount", false);
      apply.addEventListener("click", function () {
        const sats = parseInt(String(input.value || "").trim(), 10);
        if (!sats || sats < 1) {
          setActionError(container, "Enter a positive sat amount.");
          return;
        }
        apply.disabled = true;
        api(
          "POST",
          "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/set-bsv-amount",
          { bsv_amount_sats: sats }
        )
          .then(refresh)
          .catch(function (e) {
            setActionError(container, e.message || String(e));
            apply.disabled = false;
          });
      });
      const quick = btn("1000 sats", true);
      quick.addEventListener("click", function () {
        quick.disabled = true;
        apply.disabled = true;
        api(
          "POST",
          "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/set-bsv-amount",
          { bsv_amount_sats: 1000 }
        )
          .then(refresh)
          .catch(function (e) {
            setActionError(container, e.message || String(e));
            quick.disabled = false;
            apply.disabled = false;
          });
      });
      row.appendChild(quick);
      row.appendChild(input);
      row.appendChild(apply);
      tools.appendChild(row);
    }

    const statusRow = el("div", "piwalletsv-operator-panel-actions");
    const select = el("select", "piwalletsv-operator-select");
    DEV_STATUSES.forEach(function (status) {
      const opt = document.createElement("option");
      opt.value = status;
      opt.textContent = status;
      if (status === order.status) {
        opt.selected = true;
      }
      select.appendChild(opt);
    });
    const setStatus = btn("Set status", false);
    setStatus.addEventListener("click", function () {
      const next = select.value;
      if (!next || next === order.status) {
        return;
      }
      setStatus.disabled = true;
      api(
        "POST",
        "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/set-status",
        { status: next }
      )
        .then(refresh)
        .catch(function (e) {
          setActionError(container, e.message || String(e));
          setStatus.disabled = false;
        });
    });
    statusRow.appendChild(select);
    statusRow.appendChild(setStatus);
    tools.appendChild(statusRow);
    container.appendChild(tools);
  }

  function appendOrderActions(order, container, options) {
    const opts = options || {};
    const onDetail = !!opts.detail;
    appendDevTools(order, container);
    if (onDetail || order.status === "shipped") {
      appendStatusPageLink(order, container);
    }
    if (order.status === "pending_bsv" || order.status === "pending_stripe") {
      const paidBtn = btn("Mark paid", true);
      paidBtn.addEventListener("click", function () {
        clearPanels(container);
        if (order.payment_method !== "bsv") {
          paidBtn.disabled = true;
          api("POST", "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/mark-paid", {})
            .then(refresh)
            .catch(function (e) {
              setActionError(container, e.message || String(e));
              paidBtn.disabled = false;
            });
          return;
        }
        const panel = el("div", "piwalletsv-operator-panel");
        panel.appendChild(
          el("p", "piwalletsv-operator-panel-copy", "Optional BSV transaction id:")
        );
        const txInput = el("input", "piwalletsv-operator-input piwalletsv-operator-input--wide");
        txInput.type = "text";
        txInput.placeholder = "txid (optional)";
        panel.appendChild(txInput);
        const row = el("div", "piwalletsv-operator-panel-actions");
        const confirmPaid = btn("Confirm paid", true);
        const cancelPaid = btn("Back", false);
        confirmPaid.addEventListener("click", function () {
          confirmPaid.disabled = true;
          cancelPaid.disabled = true;
          api("POST", "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/mark-paid", {
            txid: (txInput.value || "").trim() || undefined,
          })
            .then(refresh)
            .catch(function (e) {
              setActionError(container, e.message || String(e));
              confirmPaid.disabled = false;
              cancelPaid.disabled = false;
            });
        });
        cancelPaid.addEventListener("click", function () {
          clearPanels(container);
        });
        row.appendChild(confirmPaid);
        row.appendChild(cancelPaid);
        panel.appendChild(row);
        container.appendChild(panel);
      });

      container.appendChild(paidBtn);
      appendCancelAction(
        order,
        container,
        "Cancel this unpaid order and release reserved stock? Logged in order history."
      );
      return;
    }

    if (order.status === "paid" || order.status === "fulfilled" || order.status === "shipped") {
      const label = order.label || {};
      const shipment = order.shipment || {};
      const labelReady = !!(label.purchased_at);
      const hasLabel = !!(labelReady || label.tracking_number || shipment.tracking_number);
      const labelShipmentId =
        order.label_shipment_id ||
        order.shippo_transaction_id ||
        order.easyship_shipment_id ||
        "";

      if ((order.status === "paid" || order.status === "fulfilled") && !labelReady) {
        const ratesPanel = el("div", "piwalletsv-operator-rates");
        ratesPanel.hidden = true;
        let selectedRateId = "";

        const ratesBtn = btn("Get shipping rates", false);
        const buyBtn = btn("Buy label", true);
        buyBtn.title = "Buy cheapest rate under the label cap (or the rate you selected)";

        function formatRateAmount(amount, currency) {
          if (amount == null || isNaN(Number(amount))) {
            return "—";
          }
          const cur = currency || "USD";
          if (String(cur).toUpperCase() === "USD") {
            return "$" + Number(amount).toFixed(2);
          }
          return Number(amount).toFixed(2) + " " + cur;
        }

        function renderRates(quote) {
          ratesPanel.innerHTML = "";
          ratesPanel.hidden = false;
          selectedRateId = "";

          const charged = order.shipping_cents;
          const chargedLabel = order.shipping_label || "Shipping charged";
          if (charged != null) {
            ratesPanel.appendChild(
              el(
                "p",
                "piwalletsv-operator-rates-note",
                "Customer paid " +
                  formatUsd(charged) +
                  (chargedLabel ? " (" + chargedLabel + ")" : "") +
                  ". Cap $" +
                  Number(quote.label_max_amount_usd || 25).toFixed(2) +
                  "."
              )
            );
          } else {
            ratesPanel.appendChild(
              el(
                "p",
                "piwalletsv-operator-rates-note",
                "Label purchase cap $" +
                  Number(quote.label_max_amount_usd || 25).toFixed(2) +
                  ". Select a rate or Buy label for cheapest under cap."
              )
            );
          }

          const list = el("div", "piwalletsv-operator-rates-list");
          const rates = quote.rates || [];
          if (!rates.length) {
            list.appendChild(el("p", "piwalletsv-operator-rates-note", "No rates returned."));
          }
          rates.forEach(function (rate) {
            const row = el("label", "piwalletsv-operator-rate-row");
            if (!rate.affordable) {
              row.className += " piwalletsv-operator-rate-row--over-cap";
            }
            const radio = document.createElement("input");
            radio.type = "radio";
            radio.name = "label-rate-" + order.order_id;
            radio.value = rate.rate_object_id || "";
            radio.disabled = !rate.affordable;
            radio.addEventListener("change", function () {
              if (radio.checked) {
                selectedRateId = radio.value;
                buyBtn.textContent = "Buy selected label";
              }
            });
            const text = el(
              "span",
              null,
              (rate.provider || "Carrier") +
                (rate.service ? " · " + rate.service : "") +
                " — " +
                formatRateAmount(rate.amount, rate.currency) +
                (rate.affordable ? "" : " (over cap)")
            );
            row.appendChild(radio);
            row.appendChild(text);
            list.appendChild(row);
          });
          ratesPanel.appendChild(list);
        }

        ratesBtn.addEventListener("click", function () {
          clearPanels(container);
          setBusy(ratesBtn, true);
          api(
            "GET",
            "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/label-rates"
          )
            .then(function (quote) {
              renderRates(quote);
            })
            .catch(function (e) {
              setActionError(container, e.message || String(e));
            })
            .finally(function () {
              setBusy(ratesBtn, false);
            });
        });

        buyBtn.addEventListener("click", function () {
          clearPanels(container);
          setBusy(buyBtn, true);
          const body = selectedRateId ? { rate_object_id: selectedRateId } : {};
          api(
            "POST",
            "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/fulfill",
            body
          )
            .then(refresh)
            .catch(function (e) {
              setActionError(container, e.message || String(e));
              setBusy(buyBtn, false);
            });
        });

        container.appendChild(ratesBtn);
        container.appendChild(buyBtn);
        container.appendChild(ratesPanel);
      }

      if (labelReady && labelShipmentId) {
        const printBtn = btn("Download label", false);
        printBtn.addEventListener("click", function () {
          clearPanels(container);
          setBusy(printBtn, true);
          downloadLabelPdf(order.order_id, labelShipmentId)
            .catch(function (e) {
              setActionError(container, e.message || String(e));
            })
            .finally(function () {
              setBusy(printBtn, false);
            });
        });
        container.appendChild(printBtn);
      }

      if (hasLabel && order.status !== "shipped") {
        const dropBtn = btn("Mark dropped in mail", true);
        dropBtn.addEventListener("click", function () {
          clearPanels(container);
          dropBtn.disabled = true;
          api("POST", "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/ship", {})
            .then(refresh)
            .catch(function (e) {
              setActionError(container, e.message || String(e));
              dropBtn.disabled = false;
            });
        });
        container.appendChild(dropBtn);
      } else {
        const shipBtn = btn(
          order.status === "shipped" ? "Update tracking" : "Enter tracking",
          !hasLabel
        );
        shipBtn.addEventListener("click", function () {
          clearPanels(container);
          const carrierSource = shipment.carrier || label.carrier || "USPS";
          const trackingSource = shipment.tracking_number || label.tracking_number || "";
          const urlSource = shipment.tracking_url || label.tracking_url || "";
          const panel = el("div", "piwalletsv-operator-panel");
          panel.appendChild(el("p", "piwalletsv-operator-panel-copy", "Shipping details"));

          function field(labelText, inputEl) {
            const wrap = el("label", "piwalletsv-operator-field");
            wrap.appendChild(el("span", "piwalletsv-operator-label", labelText));
            wrap.appendChild(inputEl);
            return wrap;
          }

          const carrierInput = el("input", "piwalletsv-operator-input piwalletsv-operator-input--wide");
          carrierInput.value = carrierSource;
          carrierInput.placeholder = "USPS, UPS, FedEx, DHL";
          const trackingInput = el("input", "piwalletsv-operator-input piwalletsv-operator-input--wide");
          trackingInput.value = trackingSource;
          trackingInput.placeholder = "Tracking number";
          const urlInput = el("input", "piwalletsv-operator-input piwalletsv-operator-input--wide");
          urlInput.value = urlSource;
          urlInput.placeholder = "Tracking URL (optional)";
          panel.appendChild(field("Carrier", carrierInput));
          panel.appendChild(field("Tracking number", trackingInput));
          panel.appendChild(field("Tracking URL", urlInput));

          const row = el("div", "piwalletsv-operator-panel-actions");
          const save = btn(order.status === "shipped" ? "Save tracking" : "Mark shipped", true);
          const back = btn("Back", false);
          save.addEventListener("click", function () {
            const carrier = (carrierInput.value || "").trim();
            const tracking = (trackingInput.value || "").trim();
            if (!carrier || !tracking) {
              setActionError(container, "Carrier and tracking number are required.");
              return;
            }
            save.disabled = true;
            back.disabled = true;
            api("POST", "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/ship", {
              carrier: carrier,
              tracking_number: tracking,
              tracking_url: (urlInput.value || "").trim() || undefined,
            })
              .then(refresh)
              .catch(function (e) {
                setActionError(container, e.message || String(e));
                save.disabled = false;
                back.disabled = false;
              });
          });
          back.addEventListener("click", function () {
            clearPanels(container);
          });
          row.appendChild(save);
          row.appendChild(back);
          panel.appendChild(row);
          container.appendChild(panel);
        });
        container.appendChild(shipBtn);
      }

      if (
        onDetail &&
        (order.status === "paid" || order.status === "fulfilled")
      ) {
        appendCancelAction(
          order,
          container,
          "Cancel this order (does not refund payment — use Mark refunded after money is returned)? Logged in order history."
        );
      }

      if (
        onDetail &&
        (order.status === "paid" || order.status === "fulfilled" || order.status === "shipped")
      ) {
        const refundBtn = btn("Mark refunded", false);
        refundBtn.addEventListener("click", function () {
          clearPanels(container);
          const panel = el("div", "piwalletsv-operator-panel");
          panel.appendChild(
            el(
              "p",
              "piwalletsv-operator-panel-copy",
              order.payment_method === "stripe"
                ? "Confirm after you refund in Stripe Dashboard. This only sets status to refunded."
                : "Confirm after you complete the BSV refund offline. This only sets status to refunded."
            )
          );
          if (order.stripe_dashboard_url) {
            const dash = el("p", "piwalletsv-operator-panel-copy");
            const link = el("a", "piwalletsv-operator-stripe-link", "Open Stripe payment");
            link.href = order.stripe_dashboard_url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            dash.appendChild(link);
            panel.appendChild(dash);
          }
          const row = el("div", "piwalletsv-operator-panel-actions");
          const confirm = btn("Confirm refunded", true);
          const back = btn("Back", false);
          confirm.addEventListener("click", function () {
            setBusy(confirm, true);
            back.disabled = true;
            api(
              "POST",
              "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/mark-refunded",
              {}
            )
              .then(refresh)
              .catch(function (e) {
                setActionError(container, e.message || String(e));
                setBusy(confirm, false);
                back.disabled = false;
              });
          });
          back.addEventListener("click", function () {
            clearPanels(container);
          });
          row.appendChild(confirm);
          row.appendChild(back);
          panel.appendChild(row);
          container.appendChild(panel);
        });
        container.appendChild(refundBtn);
      }
      return;
    }

    container.appendChild(el("span", "piwalletsv-operator-muted", "—"));
  }

  function selectedOrderIdFromUrl() {
    try {
      return new URLSearchParams(window.location.search).get("order_id") || "";
    } catch (err) {
      return "";
    }
  }

  function setOrderIdInUrl(orderId) {
    const url = new URL(window.location.href);
    if (orderId) {
      url.searchParams.set("order_id", orderId);
    } else {
      url.searchParams.delete("order_id");
    }
    history.replaceState({}, "", url.pathname + url.search + url.hash);
  }

  function openOrderDetail(orderId) {
    setOrderIdInUrl(orderId);
    return loadDashboard();
  }

  function renderEventHistory(events) {
    const section = el("section", "piwalletsv-operator-history");
    section.appendChild(el("h3", null, "Order history"));
    const list = el("ol", "piwalletsv-operator-chronicle");
    const items = Array.isArray(events) ? events : [];
    if (!items.length) {
      section.appendChild(el("p", "piwalletsv-operator-empty", "No events recorded yet."));
      return section;
    }
    items.forEach(function (evt) {
      const li = el("li", "piwalletsv-operator-chronicle-item");
      li.appendChild(el("time", "piwalletsv-operator-chronicle-at", formatWhen(evt.at)));
      li.appendChild(el("strong", "piwalletsv-operator-chronicle-type", evt.type || "—"));
      if (evt.detail) {
        li.appendChild(el("span", "piwalletsv-operator-chronicle-detail", evt.detail));
      }
      list.appendChild(li);
    });
    section.appendChild(list);
    return section;
  }

  function renderOrderDetail(order) {
    const wrap = el("div", "piwalletsv-operator-detail");
    const top = el("div", "piwalletsv-operator-top");
    top.appendChild(el("h1", null, "Order detail"));
    const back = btn("Back to orders", false);
    back.addEventListener("click", function () {
      setOrderIdInUrl("");
      loadDashboard().catch(function (e) {
        alert(e.message || String(e));
      });
    });
    top.appendChild(back);
    wrap.appendChild(top);

    const card = el("article", "piwalletsv-operator-order-card piwalletsv-operator-order-card--detail");
    const head = el("div", "piwalletsv-operator-order-head");
    const headMain = el("div", "piwalletsv-operator-order-head-main");
    const idCode = el("code", "piwalletsv-operator-order-id");
    idCode.textContent = order.order_id || "—";
    headMain.appendChild(idCode);
    headMain.appendChild(
      el("span", "piwalletsv-operator-badge " + statusClass(order.status), order.status || "—")
    );
    head.appendChild(headMain);
    head.appendChild(
      el(
        "span",
        "piwalletsv-operator-order-total",
        formatUsd(order.total_cents != null ? order.total_cents : order.price_usd_cents)
      )
    );
    card.appendChild(head);

    const meta = el("dl", "piwalletsv-operator-order-meta");
    meta.appendChild(metaRow("Product", displayProductName(order.product_name || order.sku || "—") || "—"));
    meta.appendChild(metaRow("Payment", paymentMetaValue(order)));
    meta.appendChild(metaRow("Created", formatWhen(order.created_at)));
    meta.appendChild(metaRow("Paid", formatWhen(order.paid_at)));
    if (order.refunded_at) {
      meta.appendChild(metaRow("Refunded", formatWhen(order.refunded_at)));
    }
    if (order.customer_email) {
      meta.appendChild(metaRow("Customer", order.customer_email));
    }
    const shipTo = formatShipTo(order);
    if (shipTo !== "—") {
      meta.appendChild(metaRow("Ship to", shipTo));
    }
    if (order.payment_txid) {
      meta.appendChild(metaRow("Payment txid", order.payment_txid));
    }
    if (order.bsv_reference) {
      meta.appendChild(metaRow("BSV ref", order.bsv_reference));
    }
    if (order.bsv_receive_address) {
      meta.appendChild(metaRow("BSV address", order.bsv_receive_address));
    }
    if (order.bsv_amount_sats != null) {
      let amountLabel = String(order.bsv_amount_sats) + " sats";
      if (
        order.bsv_amount_sats_original != null &&
        Number(order.bsv_amount_sats_original) !== Number(order.bsv_amount_sats)
      ) {
        amountLabel += " (was " + order.bsv_amount_sats_original + ")";
      }
      meta.appendChild(metaRow("BSV amount", amountLabel));
    }
    if (order.bsv_received_sats != null) {
      meta.appendChild(metaRow("BSV received", String(order.bsv_received_sats) + " sats"));
    }
    if (order.item_subtotal_cents != null) {
      meta.appendChild(metaRow("Subtotal", formatUsd(order.item_subtotal_cents)));
    }
    if (order.shipping_cents != null) {
      meta.appendChild(metaRow(order.shipping_label || "Shipping", formatUsd(order.shipping_cents)));
    }
    if (order.tax_cents != null) {
      meta.appendChild(metaRow("Tax", formatUsd(order.tax_cents)));
    }
    if (order.fulfillment_log) {
      meta.appendChild(metaRow("Fulfillment log", order.fulfillment_log));
    }
    if (order.easyship_shipment_id) {
      meta.appendChild(metaRow("Easyship ID", order.easyship_shipment_id));
    }
    const labelInfo = order.label || {};
    const shipInfo = order.shipment || {};
    const labelTracking = labelInfo.tracking_number || shipInfo.tracking_number;
    if (labelTracking) {
      meta.appendChild(metaRow("Label", labelTracking));
    }
    if (labelInfo.carrier || shipInfo.carrier) {
      meta.appendChild(metaRow("Carrier", labelInfo.carrier || shipInfo.carrier));
    }
    card.appendChild(meta);

    const actions = el("div", "piwalletsv-operator-actions");
    appendOrderActions(order, actions, { detail: true });
    card.appendChild(actions);
    wrap.appendChild(card);
    wrap.appendChild(renderEventHistory(order.events));
    return wrap;
  }

  function renderOrderCard(order) {
    const card = el("article", "piwalletsv-operator-order-card");
    const head = el("div", "piwalletsv-operator-order-head");
    const headMain = el("div", "piwalletsv-operator-order-head-main");
    const idCode = el("code", "piwalletsv-operator-order-id piwalletsv-operator-order-id--link");
    idCode.textContent = shortId(order.order_id);
    idCode.title = (order.order_id || "") + " — open detail";
    idCode.tabIndex = 0;
    idCode.addEventListener("click", function () {
      openOrderDetail(order.order_id).catch(function (e) {
        alert(e.message || String(e));
      });
    });
    idCode.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        idCode.click();
      }
    });
    headMain.appendChild(idCode);
    headMain.appendChild(
      el("span", "piwalletsv-operator-badge " + statusClass(order.status), order.status || "—")
    );
    head.appendChild(headMain);
    const headSide = el("div", "piwalletsv-operator-order-head-side");
    headSide.appendChild(
      el(
        "span",
        "piwalletsv-operator-order-total",
        formatUsd(order.total_cents != null ? order.total_cents : order.price_usd_cents)
      )
    );
    headSide.appendChild(el("span", "piwalletsv-operator-order-when", formatWhen(order.created_at)));
    head.appendChild(headSide);
    card.appendChild(head);

    const meta = el("dl", "piwalletsv-operator-order-meta");
    meta.appendChild(metaRow("Product", displayProductName(order.product_name || order.sku || "—") || "—"));
    meta.appendChild(metaRow("Payment", paymentMetaValue(order)));
    if (order.bsv_reference) {
      meta.appendChild(metaRow("BSV ref", order.bsv_reference));
    }
    if (
      order.payment_method === "bsv" &&
      order.status === "pending_bsv" &&
      order.bsv_received_sats > 0 &&
      order.bsv_amount_sats != null &&
      order.bsv_received_sats < order.bsv_amount_sats
    ) {
      meta.appendChild(
        metaRow(
          "BSV partial",
          order.bsv_received_sats + " / " + order.bsv_amount_sats + " sats"
        )
      );
    }
    if (order.bsv_overpaid_sats > 0) {
      meta.appendChild(metaRow("BSV overpay", "+" + order.bsv_overpaid_sats + " sats"));
    }
    if (order.customer_email) {
      meta.appendChild(metaRow("Customer", order.customer_email));
    }
    const shipTo = formatShipTo(order);
    if (shipTo !== "—") {
      meta.appendChild(metaRow("Ship to", shipTo));
    }
    card.appendChild(meta);

    const actions = el("div", "piwalletsv-operator-actions");
    appendOrderActions(order, actions);
    card.appendChild(actions);
    return card;
  }

  function formatAddress(addr) {
    if (!addr || typeof addr !== "object") {
      return "—";
    }
    const parts = [
      addr.line1,
      addr.line2,
      addr.city,
      addr.state,
      addr.postal_code,
      addr.country,
    ].filter(Boolean);
    return parts.join(", ") || "—";
  }

  function formatShipTo(order) {
    const name = String((order && order.shipping_name) || "").trim();
    const addr = formatAddress(order && order.shipping_address);
    if (name && addr !== "—") {
      return name + ", " + addr;
    }
    return name || addr;
  }

  async function api(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    if (adminKey) {
      headers["X-Admin-Key"] = adminKey;
    }
    const resp = await fetch(apiUrl + path, {
      method: method,
      headers: headers,
      body: body != null ? JSON.stringify(body) : undefined,
    });
    const data = await resp.json().catch(function () {
      return {};
    });
    if (!resp.ok) {
      throw new Error(data.error || resp.statusText || "request failed");
    }
    return data;
  }

  async function downloadLabelPdf(orderId, shipmentId) {
    const headers = {};
    if (adminKey) {
      headers["X-Admin-Key"] = adminKey;
    }
    const resp = await fetch(
      apiUrl + "/v1/admin/orders/" + encodeURIComponent(orderId) + "/label",
      { headers: headers }
    );
    if (!resp.ok) {
      const data = await resp.json().catch(function () {
        return {};
      });
      throw new Error(data.error || resp.statusText || "label download failed");
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const orderPrefix = (orderId || "").slice(0, 8);
    const filename =
      (shipmentId ? shipmentId + "-" + orderPrefix : orderPrefix || "label") + ".pdf";
    const link = el("a");
    link.href = url;
    link.download = filename;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 60000);
  }

  function renderLogin(errorMessage) {
    root.replaceChildren();
    const panel = el("div", "piwalletsv-operator-login");
    panel.appendChild(el("h2", null, "Operator sign-in"));
    panel.appendChild(
      el(
        "p",
        "piwalletsv-operator-hint",
        "Enter your admin API key (stored in this browser session only)."
      )
    );
    const form = el("div", "piwalletsv-operator-form");
    const label = el("label", "piwalletsv-operator-label", "Admin API key");
    const input = el("input", "piwalletsv-operator-input piwalletsv-operator-input--wide");
    label.htmlFor = "piwalletsv-operator-key-input";
    input.id = "piwalletsv-operator-key-input";
    input.type = "password";
    input.autocomplete = "off";
    input.placeholder = "Paste key from SSM";
    const err = el("p", "piwalletsv-operator-error");
    err.hidden = true;
    if (errorMessage) {
      err.textContent = errorMessage;
      err.hidden = false;
    }
    const continueBtn = btn("Continue", true);
    continueBtn.addEventListener("click", function () {
      adminKey = input.value.trim();
      if (!adminKey) {
        err.textContent = "Key required";
        err.hidden = false;
        return;
      }
      sessionStorage.setItem(STORAGE_KEY, adminKey);
      loadDashboard().catch(function (e) {
        sessionStorage.removeItem(STORAGE_KEY);
        adminKey = "";
        renderLogin(e.message || String(e));
      });
    });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        continueBtn.click();
      }
    });
    form.appendChild(label);
    form.appendChild(input);
    form.appendChild(continueBtn);
    panel.appendChild(form);
    panel.appendChild(err);
    root.appendChild(panel);
    input.focus();
  }

  function renderInventory(products) {
    const section = el("section", "piwalletsv-operator-section");
    section.appendChild(el("h2", null, "Stock"));
    const grid = el("div", "piwalletsv-operator-stock-grid");

    products.forEach(function (p) {
      const card = el("div", "piwalletsv-operator-stock-card");
      card.appendChild(el("h3", null, p.name || p.sku));
      if (p.track_inventory) {
        const avail = p.available ?? 0;
        const count = el("p", "piwalletsv-operator-stock-count");
        count.appendChild(el("span", "piwalletsv-operator-stock-count-label", "Available"));
        const countVal = el("span", "piwalletsv-operator-stock-count-value", String(avail));
        count.appendChild(countVal);
        card.appendChild(count);

        const form = el("div", "piwalletsv-operator-stock-form");
        const setField = el("div", "piwalletsv-operator-field");
        setField.appendChild(el("span", "piwalletsv-operator-label", "Set absolute count"));
        const setRow = el("div", "piwalletsv-operator-input-row");
        const setInput = el("input", "piwalletsv-operator-input");
        setInput.type = "number";
        setInput.min = "0";
        setInput.inputMode = "numeric";
        setInput.placeholder = "e.g. 9";
        setInput.setAttribute("aria-label", "Set stock count for " + (p.name || p.sku));
        const setBtn = btn("Set", true);
        setBtn.addEventListener("click", function () {
          const val = parseInt(setInput.value, 10);
          if (Number.isNaN(val) || val < 0) {
            return;
          }
          setBtn.disabled = true;
          api("POST", "/v1/admin/inventory/" + encodeURIComponent(p.sku), {
            available: val,
          })
            .then(refresh)
            .catch(function (e) {
              alert(e.message || String(e));
            })
            .finally(function () {
              setBtn.disabled = false;
            });
        });
        setRow.appendChild(setInput);
        setRow.appendChild(setBtn);
        setField.appendChild(setRow);
        form.appendChild(setField);

        const addField = el("div", "piwalletsv-operator-field");
        addField.appendChild(el("span", "piwalletsv-operator-label", "Add units"));
        const addRow = el("div", "piwalletsv-operator-input-row");
        const addInput = el("input", "piwalletsv-operator-input");
        addInput.type = "number";
        addInput.min = "0";
        addInput.inputMode = "numeric";
        addInput.placeholder = "e.g. 5";
        addInput.setAttribute("aria-label", "Add stock for " + (p.name || p.sku));
        const addBtn = btn("Add", false);
        addBtn.addEventListener("click", function () {
          const val = parseInt(addInput.value, 10);
          if (Number.isNaN(val) || val < 0) {
            return;
          }
          addBtn.disabled = true;
          api("POST", "/v1/admin/inventory/" + encodeURIComponent(p.sku), { add: val })
            .then(refresh)
            .catch(function (e) {
              alert(e.message || String(e));
            })
            .finally(function () {
              addBtn.disabled = false;
            });
        });
        addRow.appendChild(addInput);
        addRow.appendChild(addBtn);
        addField.appendChild(addRow);
        form.appendChild(addField);
        card.appendChild(form);
      } else {
        card.appendChild(el("p", null, "Not tracked — always in stock"));
      }
      grid.appendChild(card);
    });

    section.appendChild(grid);
    return section;
  }

  function looksLikeOrderId(value) {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      (value || "").trim()
    );
  }

  function tryOpenOrderFromSearch(query) {
    const id = (query || "").trim();
    if (!looksLikeOrderId(id)) {
      return false;
    }
    sessionStorage.setItem(ORDER_SEARCH_KEY, "");
    openOrderDetail(id).catch(function (e) {
      alert(e.message || "Order not found: " + String(e));
    });
    return true;
  }

  function renderOrders(orders, filter, search) {
    const section = el("section", "piwalletsv-operator-section");
    const head = el("div", "piwalletsv-operator-section-head");
    head.appendChild(el("h2", null, "Orders"));
    const headActions = el("div", "piwalletsv-operator-section-actions");
    const refreshBtn = btn("Refresh", false);
    refreshBtn.addEventListener("click", function () {
      refresh().catch(function (e) {
        alert(e.message || String(e));
      });
    });
    headActions.appendChild(refreshBtn);
    head.appendChild(headActions);
    section.appendChild(head);

    const filters = el("div", "piwalletsv-operator-filters");
    const filterState =
      filter ||
      sessionStorage.getItem(ORDER_FILTER_KEY) ||
      "action";
    const searchState =
      search != null ? search : sessionStorage.getItem(ORDER_SEARCH_KEY) || "";

    const filterField = el("div", "piwalletsv-operator-filter-field");
    const filterLabelEl = el("label", "piwalletsv-operator-label", "Show orders");
    const filterSelect = el("select", "piwalletsv-operator-select");
    filterLabelEl.htmlFor = "piwalletsv-operator-order-filter";
    filterSelect.id = "piwalletsv-operator-order-filter";
    ORDER_FILTERS.forEach(function (item) {
      const option = el("option", null, item.label);
      option.value = item.id;
      if (item.id === filterState) {
        option.selected = true;
      }
      filterSelect.appendChild(option);
    });
    filterField.appendChild(filterLabelEl);
    filterField.appendChild(filterSelect);
    filters.appendChild(filterField);

    const searchField = el("div", "piwalletsv-operator-filter-field piwalletsv-operator-search-field");
    const searchLabelEl = el("label", "piwalletsv-operator-label", "Search");
    const searchInput = el("input", "piwalletsv-operator-input piwalletsv-operator-input--wide");
    searchLabelEl.htmlFor = "piwalletsv-operator-order-search";
    searchInput.id = "piwalletsv-operator-order-search";
    searchInput.type = "search";
    searchInput.placeholder = "Order ID (opens any order), email, product, tracking…";
    searchInput.autocomplete = "off";
    searchInput.spellcheck = false;
    searchInput.value = searchState;
    searchField.appendChild(searchLabelEl);
    searchField.appendChild(searchInput);
    filters.appendChild(searchField);

    const countNote = el("span", "piwalletsv-operator-filter-count");
    filters.appendChild(countNote);
    section.appendChild(filters);

    const emptyEl = el("p", "piwalletsv-operator-empty");
    emptyEl.hidden = true;
    section.appendChild(emptyEl);

    const list = el("div", "piwalletsv-operator-order-list");
    section.appendChild(list);

    function paintOrders() {
      const filterId = filterSelect.value || "action";
      const query = searchInput.value || "";
      sessionStorage.setItem(ORDER_FILTER_KEY, filterId);
      sessionStorage.setItem(ORDER_SEARCH_KEY, query);

      const visible = applyOrderFilters(orders, filterId, query);
      countNote.textContent = visible.length + " of " + orders.length + " loaded";

      list.replaceChildren();
      if (!visible.length) {
        emptyEl.textContent = emptyOrdersMessage(filterId, query);
        emptyEl.hidden = false;
        list.hidden = true;
        return;
      }

      emptyEl.hidden = true;
      list.hidden = false;
      visible.forEach(function (order) {
        list.appendChild(renderOrderCard(order));
      });
    }

    filterSelect.addEventListener("change", paintOrders);
    searchInput.addEventListener("input", function () {
      if (tryOpenOrderFromSearch(searchInput.value)) {
        return;
      }
      paintOrders();
    });
    searchInput.addEventListener("search", function () {
      if (tryOpenOrderFromSearch(searchInput.value)) {
        return;
      }
      paintOrders();
    });
    searchInput.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && tryOpenOrderFromSearch(searchInput.value)) {
        ev.preventDefault();
      }
    });
    paintOrders();

    return section;
  }

  async function loadDashboard() {
    renderLoading();
    const selectedId = selectedOrderIdFromUrl();
    if (selectedId) {
      const order = await api("GET", "/v1/admin/orders/" + encodeURIComponent(selectedId));
      root.replaceChildren();
      root.appendChild(renderOrderDetail(order));
      return;
    }

    const inv = await api("GET", "/v1/inventory");
    const orders = await api("GET", "/v1/admin/orders?limit=100");
    root.replaceChildren();

    const top = el("div", "piwalletsv-operator-top");
    top.appendChild(el("h1", null, "Store operator"));
    const signOut = btn("Sign out", false);
    signOut.addEventListener("click", function () {
      sessionStorage.removeItem(STORAGE_KEY);
      adminKey = "";
      setOrderIdInUrl("");
      renderLogin();
    });
    top.appendChild(signOut);
    root.appendChild(top);

    root.appendChild(renderInventory(inv.products || []));
    root.appendChild(
      renderOrders(
        orders.orders || [],
        sessionStorage.getItem(ORDER_FILTER_KEY) || "action",
        sessionStorage.getItem(ORDER_SEARCH_KEY) || ""
      )
    );
  }

  function renderLoading() {
    root.replaceChildren();
    const wrap = el("div", "piwalletsv-operator-loading");
    wrap.setAttribute("role", "status");
    wrap.setAttribute("aria-live", "polite");
    const spinner = el("div", "piwalletsv-operator-loading-spinner");
    spinner.setAttribute("aria-hidden", "true");
    wrap.appendChild(spinner);
    wrap.appendChild(el("p", null, "Loading…"));
    root.appendChild(wrap);
  }

  function refresh() {
    return loadDashboard();
  }

  if (adminKey) {
    loadDashboard().catch(function () {
      sessionStorage.removeItem(STORAGE_KEY);
      adminKey = "";
      renderLogin();
    });
  } else {
    renderLogin();
  }
})();
