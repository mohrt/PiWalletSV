# Order received

Thank you. Your payment is being confirmed.

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     data-dev-banner=""
     hidden></div>

If you paid by card, Stripe will email a receipt. Order status updates automatically
once the payment webhook is processed (usually within a minute).

**Order ID:** <span id="piwalletsv-order-id">—</span>

[Back to purchase options](../purchase.md)

<script>
(function () {
  const id = new URLSearchParams(window.location.search).get("order_id");
  if (id) {
    document.getElementById("piwalletsv-order-id").textContent = id;
  }
})();
</script>
