# Pay with BSV

Send **exactly** the satoshi amount shown below to the receive address for this order. Payment is detected automatically.

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
      <th scope="row">Reference</th>
      <td><code data-bsv-reference>…</code></td>
    </tr>
    <tr>
      <th scope="row">Item</th>
      <td><span data-product-name>…</span></td>
    </tr>
    <tr data-usd-row="item" hidden>
      <th scope="row">Item subtotal</th>
      <td><span data-usd-item>…</span></td>
    </tr>
    <tr data-usd-row="shipping" hidden>
      <th scope="row">Shipping</th>
      <td><span data-usd-shipping>…</span></td>
    </tr>
    <tr data-usd-row="tax" hidden>
      <th scope="row">Tax</th>
      <td><span data-usd-tax>…</span></td>
    </tr>
    <tr data-usd-row="total" hidden>
      <th scope="row">Total (USD)</th>
      <td><strong data-usd-total>…</strong></td>
    </tr>
  </tbody>
</table>

<div class="piwalletsv-bsv-pay" data-pay-instructions hidden>

<h2>Send payment</h2>

<p class="piwalletsv-bsv-exact-warning">
  Send <strong>exactly</strong> this amount (sat-for-sat). Wrong amounts delay your order.
</p>

<p class="piwalletsv-bsv-amount">
  <strong data-bsv-sats>…</strong>
  <span class="piwalletsv-bsv-amount-sub">(<span data-bsv-amount>…</span>)</span>
  <button type="button" class="md-button piwalletsv-bsv-copy" data-copy-sats>Copy sats</button>
  <button type="button" class="md-button piwalletsv-bsv-copy" data-copy-bsv>Copy BSV</button>
</p>

<p class="piwalletsv-bsv-address-row">
  <code class="piwalletsv-bsv-address" data-bsv-address>…</code>
  <button type="button" class="md-button piwalletsv-bsv-copy" data-copy-address>Copy address</button>
</p>

<p class="piwalletsv-bsv-uri-row" hidden>
  <code class="piwalletsv-bsv-uri" data-bsv-uri>…</code>
  <button type="button" class="md-button piwalletsv-bsv-copy" data-copy-uri>Copy payment URI</button>
</p>

<p class="piwalletsv-bsv-qr-wrap">
  <img data-bsv-qr hidden width="220" height="220" alt="" />
</p>

<p class="piwalletsv-bsv-hint">
  Scan the QR code to prefill address and amount in your wallet — <strong>verify the amount before sending</strong>.
  Uses the standard <code>bitcoin:</code> payment URI (BIP21).
</p>

</div>

<div class="piwalletsv-bsv-partial" data-partial-note hidden>
  <p>
    <strong>Partial payment received.</strong>
    Received <span data-partial-received>…</span> of <span data-partial-required>…</span> sats.
    Send <strong>exactly <span data-partial-shortfall>…</span> more sats</strong> to the same address above.
  </p>
</div>

<p data-paid-note hidden>
  <strong>Payment confirmed.</strong> Thank you — we will follow up when your order ships.
</p>

<p data-cancelled-note hidden>
  This order was cancelled (expired or voided). Start a new checkout from the
  <a href="../purchase.md">purchase page</a> if you still want to buy.
</p>

<p class="piwalletsv-bsv-fallback">
  Problems paying? Message <a href="https://x.com/PiWalletSV" target="_blank" rel="noopener">@PiWalletSV on X</a>
  with your order ID.
</p>

</div>

This page refreshes every 15 seconds until payment is confirmed.

<p>
  <a id="piwalletsv-bsv-track-order" class="md-button" href="/store/order-status/">
    Full order status page
  </a>
</p>

[Back to purchase options](../purchase.md)
