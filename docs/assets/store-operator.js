/**
 * PiWalletSV store operator console — orders, stock, mark paid / cancel.
 */
(function () {
  const STORAGE_KEY = "piwalletsv_operator_key";
  const cfgEl = document.getElementById("piwalletsv-store-config");
  const root = document.getElementById("piwalletsv-operator");
  if (!cfgEl || !root) {
    return;
  }

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

  function formatUsd(cents) {
    if (cents == null) {
      return "—";
    }
    return "$" + (cents / 100).toFixed(2);
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
    const input = el("input", "piwalletsv-operator-input");
    input.type = "password";
    input.autocomplete = "off";
    input.placeholder = "Admin API key";
    const err = el("p", "piwalletsv-operator-error");
    err.hidden = true;
    const btn = el("button", "md-button md-button--primary", "Continue");
    btn.type = "button";
    btn.addEventListener("click", function () {
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
        btn.click();
      }
    });
    panel.appendChild(input);
    panel.appendChild(btn);
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
        card.appendChild(el("p", null, "Available: " + (p.available ?? 0)));
        const form = el("div", "piwalletsv-operator-stock-form");
        const setInput = el("input", "piwalletsv-operator-input");
        setInput.type = "number";
        setInput.min = "0";
        setInput.placeholder = "Set count";
        const setBtn = el("button", "md-button md-button--primary", "Set");
        setBtn.type = "button";
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
        const addInput = el("input", "piwalletsv-operator-input");
        addInput.type = "number";
        addInput.min = "0";
        addInput.placeholder = "Add units";
        const addBtn = el("button", "md-button", "Add");
        addBtn.type = "button";
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
        form.appendChild(setInput);
        form.appendChild(setBtn);
        form.appendChild(addInput);
        form.appendChild(addBtn);
        card.appendChild(form);
      } else {
        card.appendChild(el("p", null, "Not tracked — always in stock"));
      }
      grid.appendChild(card);
    });

    section.appendChild(grid);
    return section;
  }

  function renderOrders(orders) {
    const section = el("section", "piwalletsv-operator-section");
    const head = el("div", "piwalletsv-operator-section-head");
    head.appendChild(el("h2", null, "Orders"));
    const refreshBtn = el("button", "md-button", "Refresh");
    refreshBtn.type = "button";
    refreshBtn.addEventListener("click", function () {
      refresh().catch(function (e) {
        alert(e.message || String(e));
      });
    });
    head.appendChild(refreshBtn);
    section.appendChild(head);

    if (!orders.length) {
      section.appendChild(el("p", null, "No orders yet."));
      return section;
    }

    const table = el("table", "piwalletsv-operator-table");
    const thead = el("thead");
    const headerRow = el("tr");
    ["Created", "Order", "Product", "Pay", "Status", "Total", "Customer", "Ship to", "Actions"].forEach(
      function (col) {
        headerRow.appendChild(el("th", null, col));
      }
    );
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = el("tbody");
    orders.forEach(function (order) {
      const tr = el("tr");
      tr.appendChild(el("td", null, (order.created_at || "").replace("T", " ").replace("+00:00", " UTC")));
      const idCell = el("td");
      const code = el("code");
      code.textContent = order.order_id;
      idCell.appendChild(code);
      if (order.bsv_reference) {
        idCell.appendChild(el("div", "piwalletsv-operator-sub", order.bsv_reference));
      }
      tr.appendChild(idCell);
      tr.appendChild(el("td", null, order.product_name || order.sku));
      tr.appendChild(el("td", null, order.payment_method || "—"));
      tr.appendChild(el("td", null, order.status || "—"));
      tr.appendChild(
        el(
          "td",
          null,
          formatUsd(order.total_cents != null ? order.total_cents : order.price_usd_cents)
        )
      );
      tr.appendChild(el("td", null, order.customer_email || "—"));
      tr.appendChild(el("td", "piwalletsv-operator-address", formatAddress(order.shipping_address)));

      const actions = el("td", "piwalletsv-operator-actions");
      if (order.status === "pending_bsv" || order.status === "pending_stripe") {
        const paidBtn = el("button", "md-button md-button--primary", "Mark paid");
        paidBtn.type = "button";
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
        const cancelBtn = el("button", "md-button", "Cancel");
        cancelBtn.type = "button";
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
        actions.appendChild(paidBtn);
        actions.appendChild(cancelBtn);
      } else if (
        order.status === "paid" ||
        order.status === "fulfilled" ||
        order.status === "shipped"
      ) {
        const shipBtn = el(
          "button",
          "md-button md-button--primary",
          order.status === "shipped" ? "Update tracking" : "Mark shipped"
        );
        shipBtn.type = "button";
        shipBtn.addEventListener("click", function () {
          const shipment = order.shipment || {};
          const carrier =
            window.prompt("Carrier (USPS, UPS, FedEx, DHL):", shipment.carrier || "USPS") || "";
          if (!carrier.trim()) {
            return;
          }
          const tracking =
            window.prompt("Tracking number:", shipment.tracking_number || "") || "";
          if (!tracking.trim()) {
            return;
          }
          const trackingUrl =
            window.prompt("Tracking URL (optional — auto-guessed if blank):", shipment.tracking_url || "") ||
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
        actions.appendChild(shipBtn);
        if (order.shipment && order.shipment.tracking_number) {
          actions.appendChild(
            el("span", "piwalletsv-operator-sub", order.shipment.tracking_number)
          );
        }
      } else {
        actions.appendChild(el("span", "piwalletsv-operator-muted", "—"));
      }
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    section.appendChild(table);
    return section;
  }

  async function loadDashboard() {
    const inv = await api("GET", "/v1/inventory");
    const orders = await api("GET", "/v1/admin/orders?limit=100");
    root.replaceChildren();

    const top = el("div", "piwalletsv-operator-top");
    top.appendChild(el("h1", null, "Store operator"));
    const signOut = el("button", "md-button", "Sign out");
    signOut.type = "button";
    signOut.addEventListener("click", function () {
      sessionStorage.removeItem(STORAGE_KEY);
      adminKey = "";
      renderLogin();
    });
    top.appendChild(signOut);
    root.appendChild(top);

    root.appendChild(renderInventory(inv.products || []));
    root.appendChild(renderOrders(orders.orders || []));
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
