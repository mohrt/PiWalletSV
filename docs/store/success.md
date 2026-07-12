# Order received

Thank you. Your payment is being confirmed.

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     data-dev-banner=""
     hidden></div>

<div id="piwalletsv-order-success">

<p data-missing-order-id hidden>
  Missing order ID in URL. Use the link from checkout or look up your order on
  [Order status](order-status.md).
</p>

<p>
  <strong>Status:</strong> <span data-order-status-label>Confirming payment…</span>
  (updates every 15 seconds)
</p>

If you paid by card, Stripe will email a receipt once payment is confirmed. The receipt
includes a **Track your PiWalletSV order** link to this page (with your order ID prefilled).

<p><strong>Order ID:</strong> <span id="piwalletsv-order-id">—</span></p>

<p data-paid-note hidden>
  <strong>Payment confirmed.</strong> We will ship within a few business days. Tracking appears on
  <a href="order-status.md">Order status</a> when your label is purchased.
</p>

<p data-tracking-note hidden>
  <strong>Tracking available:</strong>
  <a data-tracking-link href="#" target="_blank" rel="noopener">Track package</a>
</p>

<p>
  <a id="piwalletsv-track-order" class="md-button md-button--primary" href="/store/order-status/">
    Track order status
  </a>
</p>

</div>

[Back to purchase options](../purchase.md)
