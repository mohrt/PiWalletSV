# Order status

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     hidden></div>

<div id="piwalletsv-order-status" class="piwalletsv-order-status">

<form class="piwalletsv-order-lookup" data-order-lookup-form>
  <label for="piwalletsv-order-id-input">Order ID</label>
  <div class="piwalletsv-order-lookup-row">
    <input id="piwalletsv-order-id-input"
           class="piwalletsv-order-id-input"
           type="text"
           data-order-id-input
           placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000"
           autocomplete="off"
           spellcheck="false">
    <button class="md-button md-button--primary" type="submit">Look up</button>
  </div>
</form>

<p class="piwalletsv-order-error" data-order-error hidden></p>

<div class="piwalletsv-order-detail" data-order-detail hidden>

<h2 class="piwalletsv-order-status-heading"><span data-order-status-label>—</span></h2>

<p class="piwalletsv-order-hint" data-order-status-hint></p>

<table class="piwalletsv-order-table">
  <tbody>
    <tr>
      <th scope="row">Order ID</th>
      <td><code data-order-id-display>—</code></td>
    </tr>
    <tr data-bsv-ref-row hidden>
      <th scope="row">BSV reference</th>
      <td><code data-bsv-reference>—</code></td>
    </tr>
    <tr>
      <th scope="row">Item</th>
      <td><span data-product-name>—</span></td>
    </tr>
    <tr>
      <th scope="row">Item price</th>
      <td><span data-item-usd>—</span></td>
    </tr>
    <tr data-order-breakdown-row>
      <th scope="row">Shipping</th>
      <td><span data-shipping-usd>—</span></td>
    </tr>
    <tr data-order-breakdown-row>
      <th scope="row">Tax</th>
      <td><span data-tax-usd>—</span></td>
    </tr>
    <tr class="piwalletsv-order-total-row" data-order-breakdown-row>
      <th scope="row">Total charged</th>
      <td><strong data-total-usd>—</strong></td>
    </tr>
    <tr>
      <th scope="row">Payment</th>
      <td><span data-payment-method>—</span></td>
    </tr>
    <tr>
      <th scope="row">Placed</th>
      <td><span data-created-at>—</span></td>
    </tr>
    <tr>
      <th scope="row">Paid</th>
      <td><span data-paid-at>—</span></td>
    </tr>
  </tbody>
</table>

<div class="piwalletsv-order-tracking" data-tracking-section hidden>

<h3 class="piwalletsv-order-tracking-heading">Tracking</h3>

<table class="piwalletsv-order-table">
  <tbody>
    <tr>
      <th scope="row">Carrier</th>
      <td><span data-carrier>—</span></td>
    </tr>
    <tr>
      <th scope="row">Tracking number</th>
      <td><code data-tracking-number>—</code></td>
    </tr>
    <tr>
      <th scope="row">Shipped</th>
      <td><span data-shipped-at>—</span></td>
    </tr>
  </tbody>
</table>

<p>
  <a class="md-button md-button--primary"
     data-tracking-link
     href="#"
     target="_blank"
     rel="noopener">
    Track package
  </a>
</p>

</div>

</div>

</div>

<script src="/assets/store-order-status.js?v=bsv-ref-row"></script>

Questions? [@PiWalletSV on X](https://x.com/PiWalletSV)

[Back to shop](../purchase/shop.md)
