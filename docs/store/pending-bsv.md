# Pay with BSV

Send **exactly** the satoshi amount shown below to the receive address for this order. Payment is detected automatically.

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     data-dev-banner="{{ store_dev_banner }}"
     hidden></div>

<div id="piwalletsv-bsv-pending">

<div class="piwalletsv-bsv-waiting" data-waiting-banner hidden>
  <span class="piwalletsv-bsv-waiting-spinner" aria-hidden="true"></span>
  <div>
    <strong data-waiting-title>Waiting for payment</strong>
    <p class="piwalletsv-bsv-waiting-copy" data-waiting-copy>
      This page checks the blockchain every 15 seconds. Keep it open after you send.
    </p>
  </div>
</div>

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

<div class="piwalletsv-bsv-pay-card">
  <div class="piwalletsv-bsv-qr-wrap">
    <img data-bsv-qr hidden width="220" height="220" alt="" />
  </div>

  <div class="piwalletsv-bsv-pay-fields">
    <div class="piwalletsv-bsv-field">
      <span class="piwalletsv-bsv-field-label">Amount (sats)</span>
      <div class="piwalletsv-bsv-value-row">
        <strong class="piwalletsv-bsv-value" data-bsv-sats>…</strong>
        <button type="button" class="piwalletsv-bsv-icon-copy" data-copy-sats aria-label="Copy sats" title="Copy sats">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path fill="currentColor" d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
        </button>
      </div>
    </div>

    <div class="piwalletsv-bsv-field">
      <span class="piwalletsv-bsv-field-label">Amount (BSV)</span>
      <div class="piwalletsv-bsv-value-row">
        <span class="piwalletsv-bsv-value" data-bsv-amount>…</span>
        <button type="button" class="piwalletsv-bsv-icon-copy" data-copy-bsv aria-label="Copy BSV amount" title="Copy BSV amount">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path fill="currentColor" d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
        </button>
      </div>
    </div>

    <div class="piwalletsv-bsv-field">
      <span class="piwalletsv-bsv-field-label">Receive address</span>
      <div class="piwalletsv-bsv-value-row">
        <code class="piwalletsv-bsv-address" data-bsv-address>…</code>
        <button type="button" class="piwalletsv-bsv-icon-copy" data-copy-address aria-label="Copy address" title="Copy address">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path fill="currentColor" d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
        </button>
      </div>
    </div>

    <div class="piwalletsv-bsv-field piwalletsv-bsv-uri-row" hidden>
      <span class="piwalletsv-bsv-field-label">Payment URI</span>
      <div class="piwalletsv-bsv-value-row">
        <code class="piwalletsv-bsv-uri" data-bsv-uri>…</code>
        <button type="button" class="piwalletsv-bsv-icon-copy" data-copy-uri aria-label="Copy payment URI" title="Copy payment URI">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path fill="currentColor" d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
        </button>
      </div>
    </div>
  </div>
</div>

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

<div class="piwalletsv-bsv-cancel" data-cancel-block hidden>
  <button type="button" class="md-button" id="piwalletsv-bsv-cancel">Cancel order</button>
  <div class="piwalletsv-bsv-cancel-panel" data-cancel-panel hidden>
    <p>Cancel this unpaid order and release reserved stock? Do this only if you will not pay.</p>
    <div class="piwalletsv-bsv-cancel-actions">
      <button type="button" class="md-button md-button--primary" data-cancel-confirm>Yes, cancel order</button>
      <button type="button" class="md-button" data-cancel-back>Keep waiting</button>
    </div>
  </div>
  <p class="piwalletsv-store-error" data-cancel-error hidden></p>
</div>

<p data-paid-note hidden>
  <strong>Payment confirmed.</strong> Thank you — we will follow up when your order ships.
</p>

<p data-cancelled-note hidden>
  This order was cancelled. Start a new checkout from the
  <a href="../purchase.md">purchase page</a> if you still want to buy.
</p>

<p class="piwalletsv-bsv-fallback">
  Problems paying? Message <a href="https://x.com/PiWalletSV" target="_blank" rel="noopener">@PiWalletSV on X</a>
  with your order ID.
</p>

</div>

[Back to purchase options](../purchase.md)
