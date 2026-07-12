# Store operator

Password-protected operator console for **orders**, **stock**, and **mark paid / cancel**.
Not linked in the public nav — bookmark this URL.

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     hidden></div>

<div id="piwalletsv-operator" class="piwalletsv-operator-root">
  <p>Loading…</p>
</div>

<script src="/assets/store-operator.js?v=4"></script>

Sign in with your **admin API key** (provided separately — not published in this repo).
The key stays in your browser session until you sign out.

**Capabilities:**

- View **stock** for tracked SKUs (set absolute count or add units)
- List **recent orders** with shipping address and BSV reference
- **Mark paid** (BSV or manual card follow-up)
- **Cancel** pending orders (releases reserved kit stock)
- **Download label** (Easyship PDF — open in Preview to print)
- **Mark dropped in mail** / **Mark shipped** with carrier + tracking (customers see it on [order status](/store/order-status/))

Card orders normally become `paid` automatically via Stripe webhook.

When Easyship buys a label, click **Download label**, open the PDF in **Preview**, then **Mark dropped in mail** after you post the package.
Customers can look up status on the [order status](/store/order-status/) page.
