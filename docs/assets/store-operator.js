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

  function btn(label, primary) {
    const node = el(
      "button",
      "piwalletsv-operator-btn" + (primary ? " piwalletsv-operator-btn--primary" : ""),
      label
    );
    node.type = "button";
    return node;
  }

  function shortId(id) {
    if (!id || id.length <= 12) {
      return id || "—";
    }
    return id.slice(0, 8) + "…";
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
      formatAddress(order.shipping_address),
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

  function appendOrderActions(order, container) {
    if (order.status === "pending_bsv" || order.status === "pending_stripe") {
      const paidBtn = btn("Mark paid", true);
      paidBtn.addEventListener("click", function () {
        const txid =
          order.payment_method === "bsv"
            ? window.prompt("BSV txid (optional):", "") || ""
            : "";
        paidBtn.disabled = true;
        api("POST", "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/mark-paid", {
          txid: txid.trim() || undefined,
        })
          .then(refresh)
          .catch(function (e) {
            alert(e.message || String(e));
          })
          .finally(function () {
            paidBtn.disabled = false;
          });
      });
      const cancelBtn = btn("Cancel", false);
      cancelBtn.classList.add("piwalletsv-operator-btn--danger");
      cancelBtn.addEventListener("click", function () {
        if (!window.confirm("Cancel order and release stock if reserved?")) {
          return;
        }
        cancelBtn.disabled = true;
        api("POST", "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/cancel", {})
          .then(refresh)
          .catch(function (e) {
            alert(e.message || String(e));
          })
          .finally(function () {
            cancelBtn.disabled = false;
          });
      });
      container.appendChild(paidBtn);
      container.appendChild(cancelBtn);
      return;
    }

    if (order.status === "paid" || order.status === "fulfilled" || order.status === "shipped") {
      const label = order.label || {};
      const shipment = order.shipment || {};
      const hasLabel = !!(label.tracking_number || shipment.tracking_number);
      const easyshipId = order.easyship_shipment_id || "";
      if (easyshipId) {
        const printBtn = btn("Download label", false);
        printBtn.addEventListener("click", function () {
          printBtn.disabled = true;
          downloadLabelPdf(order.order_id, easyshipId)
            .catch(function (e) {
              alert(e.message || String(e));
            })
            .finally(function () {
              printBtn.disabled = false;
            });
        });
        container.appendChild(printBtn);
      }
      const shipBtn = btn(
        order.status === "shipped" ? "Update tracking" : hasLabel ? "Mark dropped in mail" : "Mark shipped",
        true
      );
      shipBtn.addEventListener("click", function () {
        const carrierSource = shipment.carrier || label.carrier || "USPS";
        const trackingSource = shipment.tracking_number || label.tracking_number || "";
        const urlSource = shipment.tracking_url || label.tracking_url || "";
        if (hasLabel && order.status !== "shipped") {
          if (!window.confirm("Mark this order shipped? Use this after you drop the package in the mail.")) {
            return;
          }
          shipBtn.disabled = true;
          api("POST", "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/ship", {})
            .then(refresh)
            .catch(function (e) {
              alert(e.message || String(e));
            })
            .finally(function () {
              shipBtn.disabled = false;
            });
          return;
        }
        const carrier =
          window.prompt("Carrier (USPS, UPS, FedEx, DHL):", carrierSource) || "";
        if (!carrier.trim()) {
          return;
        }
        const tracking =
          window.prompt("Tracking number:", trackingSource) || "";
        if (!tracking.trim()) {
          return;
        }
        const trackingUrl =
          window.prompt("Tracking URL (optional — auto-guessed if blank):", urlSource) ||
          "";
        shipBtn.disabled = true;
        api("POST", "/v1/admin/orders/" + encodeURIComponent(order.order_id) + "/ship", {
          carrier: carrier.trim(),
          tracking_number: tracking.trim(),
          tracking_url: trackingUrl.trim() || undefined,
        })
          .then(refresh)
          .catch(function (e) {
            alert(e.message || String(e));
          })
          .finally(function () {
            shipBtn.disabled = false;
          });
      });
      container.appendChild(shipBtn);
      if (hasLabel) {
        const note = label.tracking_number || shipment.tracking_number;
        container.appendChild(
          el(
            "span",
            "piwalletsv-operator-sub",
            order.status === "shipped" ? note : "Label: " + note
          )
        );
      }
      return;
    }

    container.appendChild(el("span", "piwalletsv-operator-muted", "—"));
  }

  function renderOrderCard(order) {
    const card = el("article", "piwalletsv-operator-order-card");
    const head = el("div", "piwalletsv-operator-order-head");
    const headMain = el("div", "piwalletsv-operator-order-head-main");
    const idCode = el("code", "piwalletsv-operator-order-id");
    idCode.textContent = shortId(order.order_id);
    idCode.title = order.order_id || "";
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
    meta.appendChild(metaRow("Product", order.product_name || order.sku || "—"));
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
    const addr = formatAddress(order.shipping_address);
    if (addr !== "—") {
      meta.appendChild(metaRow("Ship to", addr));
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
    const filename = (shipmentId || shortId(orderId)) + "-label.pdf";
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

  function renderLogin() {
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
        err.textContent = e.message || String(e);
        err.hidden = false;
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
    searchInput.placeholder = "Order ID, email, product, tracking…";
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
    searchInput.addEventListener("input", paintOrders);
    searchInput.addEventListener("search", paintOrders);
    paintOrders();

    return section;
  }

  async function loadDashboard() {
    const inv = await api("GET", "/v1/inventory");
    const orders = await api("GET", "/v1/admin/orders?limit=100");
    root.replaceChildren();

    const top = el("div", "piwalletsv-operator-top");
    top.appendChild(el("h1", null, "Store operator"));
    const signOut = btn("Sign out", false);
    signOut.addEventListener("click", function () {
      sessionStorage.removeItem(STORAGE_KEY);
      adminKey = "";
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
