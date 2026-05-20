/**
 * Settings page (`#/settings`).
 *
 * Persists preferences in localStorage (no IndexedDB needed — these
 * are global companion settings, not per-wallet data).
 *
 * Settings:
 *   - Default fee tier (economy / standard / priority)
 *   - Fiat currency for balance toggle (USD / EUR / AUD / GBP)
 *   - Default network for new wallet pairings (main / test)
 *   - Clear all data (removes all IndexedDB wallets + localStorage)
 */
import { renderHeader } from "./nav.js";
import { _clearAllWallets } from "../lib/wallets.js";

// localStorage keys
const KEY_DEFAULT_FEE_TIER = "piwallet.settings.defaultFeeTier";
const KEY_FIAT_CURRENCY = "piwallet.settings.fiatCurrency";
const KEY_DEFAULT_NETWORK = "piwallet.settings.defaultNetwork";

export type FeeTier = "economy" | "standard" | "priority";
export type FiatCurrency = "USD" | "EUR" | "AUD" | "GBP";
export type DefaultNetwork = "main" | "test";

export function getDefaultFeeTier(): FeeTier {
  return (localStorage.getItem(KEY_DEFAULT_FEE_TIER) as FeeTier) ?? "standard";
}

export function getFiatCurrency(): FiatCurrency {
  return (localStorage.getItem(KEY_FIAT_CURRENCY) as FiatCurrency) ?? "USD";
}

export function getDefaultNetwork(): DefaultNetwork {
  return (localStorage.getItem(KEY_DEFAULT_NETWORK) as DefaultNetwork) ?? "main";
}

export function mountSettingsPage(root: HTMLElement): () => void {
  const feeTier = getDefaultFeeTier();
  const fiatCurrency = getFiatCurrency();
  const defaultNetwork = getDefaultNetwork();

  root.innerHTML = `
    <main class="page">
      ${renderHeader("Settings", "settings")}

      <section class="card">
        <h2>Send defaults</h2>

        <label class="field">
          <span>Default fee tier</span>
          <select id="defaultFeeTier">
            <option value="economy"${feeTier === "economy" ? " selected" : ""}>Economy (cheapest)</option>
            <option value="standard"${feeTier === "standard" ? " selected" : ""}>Standard (recommended)</option>
            <option value="priority"${feeTier === "priority" ? " selected" : ""}>Priority (fastest)</option>
          </select>
        </label>

        <label class="field">
          <span>Default network for new pairings</span>
          <select id="defaultNetwork">
            <option value="main"${defaultNetwork === "main" ? " selected" : ""}>Mainnet (BSV)</option>
            <option value="test"${defaultNetwork === "test" ? " selected" : ""}>Testnet (TBSV)</option>
          </select>
        </label>
      </section>

      <section class="card">
        <h2>Display</h2>

        <label class="field">
          <span>Fiat currency (for balance toggle)</span>
          <select id="fiatCurrency">
            <option value="USD"${fiatCurrency === "USD" ? " selected" : ""}>USD — US Dollar</option>
            <option value="EUR"${fiatCurrency === "EUR" ? " selected" : ""}>EUR — Euro</option>
            <option value="GBP"${fiatCurrency === "GBP" ? " selected" : ""}>GBP — British Pound</option>
            <option value="AUD"${fiatCurrency === "AUD" ? " selected" : ""}>AUD — Australian Dollar</option>
          </select>
        </label>
      </section>

      <section class="card">
        <h2>Data</h2>
        <p class="muted-line">
          Remove all paired wallets and companion preferences from this
          browser. This does <strong>not</strong> affect the Pi device —
          your keys and wallets remain on the Pi.
        </p>
        <div id="clearStrip" hidden>
          <p class="remove-confirm-msg">
            This will remove all paired wallets from this browser.
            You can re-pair by scanning your Pi again.
          </p>
          <div class="actions">
            <button id="clearConfirm" class="primary danger" type="button">Yes, clear all data</button>
            <button id="clearCancel" type="button">Cancel</button>
          </div>
        </div>
        <div class="actions" id="clearActions">
          <button id="clearBtn" type="button">Clear all data</button>
        </div>
        <p id="clearStatus" class="muted-line"></p>
      </section>
    </main>
  `;

  const $feeTier = root.querySelector<HTMLSelectElement>("#defaultFeeTier")!;
  const $fiat = root.querySelector<HTMLSelectElement>("#fiatCurrency")!;
  const $network = root.querySelector<HTMLSelectElement>("#defaultNetwork")!;
  const $clearBtn = root.querySelector<HTMLButtonElement>("#clearBtn")!;
  const $clearStrip = root.querySelector<HTMLElement>("#clearStrip")!;
  const $clearActions = root.querySelector<HTMLElement>("#clearActions")!;
  const $clearConfirm = root.querySelector<HTMLButtonElement>("#clearConfirm")!;
  const $clearCancel = root.querySelector<HTMLButtonElement>("#clearCancel")!;
  const $clearStatus = root.querySelector<HTMLElement>("#clearStatus")!;

  $feeTier.addEventListener("change", () => {
    localStorage.setItem(KEY_DEFAULT_FEE_TIER, $feeTier.value);
  });

  $fiat.addEventListener("change", () => {
    localStorage.setItem(KEY_FIAT_CURRENCY, $fiat.value);
  });

  $network.addEventListener("change", () => {
    localStorage.setItem(KEY_DEFAULT_NETWORK, $network.value);
  });

  $clearBtn.addEventListener("click", () => {
    $clearActions.hidden = true;
    $clearStrip.hidden = false;
  });

  $clearCancel.addEventListener("click", () => {
    $clearStrip.hidden = true;
    $clearActions.hidden = false;
  });

  $clearConfirm.addEventListener("click", async () => {
    $clearConfirm.disabled = true;
    $clearConfirm.textContent = "Clearing…";
    try {
      await _clearAllWallets();
      // Clear all piwallet.* localStorage keys
      const keysToRemove: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k?.startsWith("piwallet.")) keysToRemove.push(k);
      }
      for (const k of keysToRemove) localStorage.removeItem(k);
      $clearStatus.classList.remove("error");
      $clearStatus.textContent = "All data cleared. Redirecting to wallets…";
      setTimeout(() => {
        window.location.hash = "#/wallets";
      }, 1500);
    } catch (e) {
      $clearStatus.classList.add("error");
      $clearStatus.textContent = `clear failed: ${(e as Error).message}`;
      $clearConfirm.disabled = false;
      $clearConfirm.textContent = "Yes, clear all data";
    }
  });

  return () => {};
}
