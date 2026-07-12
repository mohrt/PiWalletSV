# Checkout with BSV

Enter your email and shipping address to continue.

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     data-dev-banner="{{ store_dev_banner }}"
     hidden></div>

<p class="piwalletsv-store-stock" id="piwalletsv-bsv-checkout-stock" hidden></p>

<form id="piwalletsv-bsv-checkout-form" class="piwalletsv-bsv-checkout-form">

<div id="piwalletsv-bsv-email-step" class="piwalletsv-bsv-email-step">
  <label>
    Email
    <input type="email" name="customer_email" id="piwalletsv-bsv-email" required autocomplete="email" />
  </label>
  <p class="piwalletsv-bsv-email-hint">We will send a verification link before you can pay.</p>
  <button type="button" class="md-button" id="piwalletsv-bsv-send-verify">Send verification link</button>
  <p class="piwalletsv-store-note" id="piwalletsv-bsv-verify-sent" hidden>Check your inbox for a link from PiWalletSV.</p>
</div>

<div id="piwalletsv-bsv-shipping-step" class="piwalletsv-bsv-shipping-step" hidden>
  <p class="piwalletsv-bsv-email-verified">
    Email verified: <strong data-verified-email>…</strong>
  </p>

<label>
  Ship to name
  <input type="text" name="shipping_name" autocomplete="name" />
</label>

<label>
  Address line 1
  <input type="text" name="line1" required autocomplete="address-line1" />
</label>

<label>
  Address line 2
  <input type="text" name="line2" autocomplete="address-line2" />
</label>

<label>
  City
  <input type="text" name="city" required autocomplete="address-level2" />
</label>

<label>
  State / province
  <input type="text" name="state" autocomplete="address-level1" />
</label>

<label>
  Postal code
  <input type="text" name="postal_code" required autocomplete="postal-code" />
</label>

<label>
  Country
  <select name="country" required autocomplete="country">
    <option value="US" selected>United States</option>
    <option value="CA">Canada</option>
    <option value="GB">United Kingdom</option>
    <option value="AU">Australia</option>
    <option value="DE">Germany</option>
    <option value="FR">France</option>
  </select>
</label>

<p id="piwalletsv-bsv-checkout-product" hidden>
  Item: <strong data-product-label>…</strong>
</p>

<div id="piwalletsv-bsv-checkout-quote" class="piwalletsv-bsv-quote" hidden>
  <h2>Order total</h2>
  <p>Shipping: <span data-quote-shipping>…</span></p>
  <p>Tax: <span data-quote-tax>…</span></p>
  <p><strong>Total USD: <span data-quote-total>…</span></strong></p>
  <p class="piwalletsv-bsv-exact-warning">
    You will pay <strong data-quote-sats>…</strong>. Send <strong>exactly</strong> that many satoshis.
  </p>
</div>

<p class="piwalletsv-store-error" id="piwalletsv-bsv-checkout-error" hidden></p>

<button type="submit" class="md-button md-button--primary" id="piwalletsv-bsv-checkout-submit">
  Continue to payment
</button>
</div>

</form>

<p><a href="../purchase.md">Back to purchase options</a></p>
