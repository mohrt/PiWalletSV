# Store operator

Password-protected operator console for **orders**, **stock**, and **mark paid / cancel**.
Not linked in the public nav — bookmark this URL.

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     hidden></div>

<div id="piwalletsv-operator" class="piwalletsv-operator-root">
  <p>Loading…</p>
</div>

<script src="/assets/store-operator.js"></script>

Sign in with your **admin API key** (provided separately — not published in this repo).
The key stays in your browser session until you sign out.

**Capabilities:**

- View **stock** for tracked SKUs (set absolute count or add units)
- List **recent orders** with shipping address and BSV reference
- **Mark paid** (BSV or manual card follow-up)
- **Cancel** pending orders (releases reserved kit stock)
- **Mark shipped** with carrier + tracking (customers see it on [order status](/store/order-status/))

Card orders normally become `paid` automatically via Stripe webhook.

When you buy a label in Easyship, use **Mark shipped** and enter carrier + tracking number.
Customers can look up status on the [order status](/store/order-status/) page.
