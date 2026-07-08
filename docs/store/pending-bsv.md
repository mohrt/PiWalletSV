# Arrange BSV payment

Your order is saved. **Contact [@PiWalletSV on X](https://x.com/PiWalletSV)** to arrange payment
(BSV address or HandCash alias). Include your **order ID** in the message — we cannot match
payment without it.

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     data-dev-banner="{{ store_dev_banner }}"
     hidden></div>

<div id="piwalletsv-bsv-pending">

<table class="piwalletsv-order-table">
  <tbody>
    <tr>
      <th scope="row">Status</th>
      <td><span data-order-status>loading…</span></td>
    </tr>
    <tr>
      <th scope="row">Order ID</th>
      <td><code data-order-id>…</code></td>
    </tr>
    <tr>
      <th scope="row">Item</th>
      <td><span data-product-name>…</span></td>
    </tr>
    <tr>
      <th scope="row">Price (USD)</th>
      <td><span data-price-usd>…</span></td>
    </tr>
  </tbody>
</table>

<p>
  <a class="md-button md-button--primary" href="https://x.com/PiWalletSV" target="_blank" rel="noopener">
    Message @PiWalletSV on X
  </a>
</p>

<p data-paid-note hidden>
  <strong>Payment confirmed.</strong> Thank you — we will follow up when your order ships.
</p>

</div>

After we confirm your BSV payment, this page updates automatically (refreshes every 15 seconds).

<p>
  <a id="piwalletsv-bsv-track-order" class="md-button" href="/store/order-status/">
    Full order status page
  </a>
</p>

<script>
(function () {
  const id = new URLSearchParams(window.location.search).get("order_id");
  const track = document.getElementById("piwalletsv-bsv-track-order");
  if (id && track) {
    track.href = "/store/order-status/?order_id=" + encodeURIComponent(id);
  }
})();
</script>

[Back to purchase options](../purchase.md)
