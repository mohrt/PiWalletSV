# Checkout with BSV

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     data-dev-banner="{{ store_dev_banner }}"
     hidden></div>

<form id="piwalletsv-bsv-checkout-form" class="piwalletsv-bsv-checkout-form">

<div id="piwalletsv-bsv-email-step" class="piwalletsv-bsv-email-step">
  <p>Enter your email address.</p>
  <label>
    Email
    <input type="email" name="customer_email" id="piwalletsv-bsv-email" required autocomplete="email" />
  </label>
  <p class="piwalletsv-bsv-email-hint">We will send a verification link before you can pay.</p>
  <button type="button" class="md-button" id="piwalletsv-bsv-send-verify">Send verification link</button>
  <p class="piwalletsv-store-note" id="piwalletsv-bsv-verify-sent" hidden>Check your inbox for a link from PiWalletSV. Didn’t get it? Click Resend verification link.</p>
</div>

<div id="piwalletsv-bsv-shipping-step" class="piwalletsv-bsv-shipping-step" hidden>
  <p class="piwalletsv-bsv-email-verified">
    Email: <strong data-verified-email>…</strong>
    <button type="button" class="piwalletsv-bsv-change-email" id="piwalletsv-bsv-change-email">
      Use a different email
    </button>
  </p>

<label>
  Country
  <select name="country" id="piwalletsv-bsv-country" required autocomplete="country">
    <option value="" selected disabled>Select country…</option>
    <option value="US">United States</option>
    <option value="CA">Canada</option>
    <option value="GB">United Kingdom</option>
    <option value="AU">Australia</option>
    <option value="AT">Austria</option>
    <option value="BE">Belgium</option>
    <option value="CZ">Czechia</option>
    <option value="DK">Denmark</option>
    <option value="FI">Finland</option>
    <option value="FR">France</option>
    <option value="DE">Germany</option>
    <option value="IE">Ireland</option>
    <option value="IT">Italy</option>
    <option value="LU">Luxembourg</option>
    <option value="NL">Netherlands</option>
    <option value="NZ">New Zealand</option>
    <option value="NO">Norway</option>
    <option value="PL">Poland</option>
    <option value="PT">Portugal</option>
    <option value="ES">Spain</option>
    <option value="SE">Sweden</option>
    <option value="CH">Switzerland</option>
  </select>
</label>

<label>
  Ship to name
  <input type="text" name="shipping_name" required autocomplete="name" />
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
  <span data-state-label>State</span>
  <input type="text" name="state" autocomplete="address-level1" />
</label>

<label>
  <span data-postal-label>ZIP code</span>
  <input type="text" name="postal_code" required autocomplete="postal-code" placeholder="78701" />
</label>

<p id="piwalletsv-bsv-checkout-product" hidden>
  Item: <strong data-product-label>…</strong>
</p>

<div id="piwalletsv-bsv-checkout-quote" class="piwalletsv-bsv-quote" hidden>
  <h2>Order total</h2>
  <p>Shipping: <span data-quote-shipping>…</span></p>
  <p>Tax: <span data-quote-tax>…</span></p>
  <p><strong>Total USD: <span data-quote-total>…</span></strong></p>
  <p><strong>Total BSV: <span data-quote-bsv>…</span></strong></p>
</div>

<p id="piwalletsv-bsv-address-check" class="piwalletsv-bsv-address-check" hidden>
  Checking address…
</p>

<p class="piwalletsv-store-error" id="piwalletsv-bsv-checkout-error" hidden></p>

<button type="button" class="md-button md-button--primary" id="piwalletsv-bsv-validate-address">
  Validate Address
</button>

<button type="button" class="md-button md-button--primary" id="piwalletsv-bsv-checkout-submit" hidden disabled aria-disabled="true" title="Validate your shipping address first">
  Continue to payment
</button>
</div>

</form>

<div id="piwalletsv-bsv-address-modal" class="piwalletsv-addr-modal" hidden>
  <div class="piwalletsv-addr-modal__backdrop" data-addr-dismiss tabindex="-1"></div>
  <div
    class="piwalletsv-addr-modal__panel"
    role="dialog"
    aria-modal="true"
    aria-labelledby="piwalletsv-bsv-address-modal-title"
  >
    <h2 id="piwalletsv-bsv-address-modal-title">Use corrected address?</h2>
    <p>We found a corrected shipping address. Use this instead?</p>
    <div class="piwalletsv-addr-modal__address" data-corrected-address></div>
    <div class="piwalletsv-addr-modal__actions">
      <button type="button" class="md-button md-button--primary" data-addr-accept>Use corrected address</button>
      <button type="button" class="md-button" data-addr-reject>No, edit my address</button>
    </div>
  </div>
</div>

<p><a href="../purchase/shop.md">Back to shop</a></p>
