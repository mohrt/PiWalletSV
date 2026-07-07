# Pay with BSV

Send the exact amount below to the address shown. Include the **payment reference**
in the transaction memo/note so we can match your order.

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     data-dev-banner="{{ store_dev_banner }}"
     hidden></div>

<div id="piwalletsv-bsv-pending">

| Field | Value |
|-------|--------|
| Status | <span data-order-status>loading…</span> |
| BSV address | <code data-bsv-address>…</code> |
| Amount (sats) | <code data-bsv-amount>…</code> |
| Payment reference | <code data-bsv-reference>…</code> |

<p data-paid-note hidden>
  **Payment confirmed.** Thank you — we will follow up when your order ships.
</p>

</div>

BSV orders are confirmed **manually** after we verify payment on chain (usually within
24 hours). This page refreshes every 15 seconds.

[Back to purchase options](../purchase.md)
