/**
 * Settings page (`#/settings`).
 *
 * Persists preferences in localStorage (no IndexedDB needed — these
 * are global companion settings, not per-wallet data).
 *
 * Settings:
 *   - Default fee tier (economy / standard / priority / custom sat/kB)
 *   - Fiat currency for balance toggle (USD / EUR / AUD / GBP)
 *   - Default network for new wallet pairings (main / test)
 *   - Clear all data (removes all IndexedDB wallets + localStorage)
 */
import { renderHeader } from "./nav.js";
import { _clearAllWallets } from "../lib/wallets.js";
import { WocClient, effectiveWocBase } from "../lib/woc.js";
import {
  DEFAULT_FEE_RATE_SATSKB,
  type FeeRecommendation,
  fetchFeeRecommendation,
  formatFeeRate,
} from "../lib/fee.js";

// localStorage keys
const KEY_DEFAULT_FEE_TIER   = "piwallet.settings.defaultFeeTier";
const KEY_CUSTOM_FEE_RATE    = "piwallet.settings.customFeeRate";
const KEY_FIAT_CURRENCY      = "piwallet.settings.fiatCurrency";
const KEY_DEFAULT_NETWORK    = "piwallet.settings.defaultNetwork";

export type FeeTier = "economy" | "standard" | "priority" | "custom";
export type FiatCurrency = "USD" | "EUR" | "AUD" | "GBP";
export type DefaultNetwork = "main" | "test";

export function getDefaultFeeTier(): FeeTier {
  return (localStorage.getItem(KEY_DEFAULT_FEE_TIER) as FeeTier) ?? "standard";
}

export function getDefaultCustomFeeRate(): number {
  const stored = parseInt(localStorage.getItem(KEY_CUSTOM_FEE_RATE) ?? "", 10);
  return Number.isInteger(stored) && stored > 0 ? stored : DEFAULT_FEE_RATE_SATSKB;
}

export function getFiatCurrency(): FiatCurrency {
  return (localStorage.getItem(KEY_FIAT_CURRENCY) as FiatCurrency) ?? "USD";
}

export function getDefaultNetwork(): DefaultNetwork {
  return (localStorage.getItem(KEY_DEFAULT_NETWORK) as DefaultNetwork) ?? "main";
}

export function mountSettingsPage(root: HTMLElement): () => void {
  const feeTier        = getDefaultFeeTier();
  const customFeeRate  = getDefaultCustomFeeRate();
  const fiatCurrency   = getFiatCurrency();
  const defaultNetwork = getDefaultNetwork();

  const sel = (v: string, cur: string) => v === cur ? " selected" : "";
  const chk = (v: string, cur: string) => v === cur ? " checked" : "";

  root.innerHTML = `
    <main class="page">
      ${renderHeader("Settings", "settings")}

      <p id="settingsSavedBanner" class="settings-saved-banner" hidden>✓ Settings saved</p>

      <section class="card">
        <h2>Send defaults</h2>

        <div class="field">
          <span class="field-label">Default fee tier</span>
          <p class="muted-line" id="feeRateLoading">Loading current rates…</p>
          <div class="fee-tiers" id="settingsFeeTiers">
            <label class="fee-tier${feeTier === "economy" ? " selected" : ""}">
              <input type="radio" name="settingsFeeTier" value="economy"${chk("economy", feeTier)} />
              <span class="fee-tier-label">Economy</span>
              <span class="fee-tier-rate" id="sEconomy">—</span>
              <span class="fee-tier-desc muted-line">slower, cheapest</span>
            </label>
            <label class="fee-tier${feeTier === "standard" ? " selected" : ""}">
              <input type="radio" name="settingsFeeTier" value="standard"${chk("standard", feeTier)} />
              <span class="fee-tier-label">Standard</span>
              <span class="fee-tier-rate" id="sStandard">—</span>
              <span class="fee-tier-desc muted-line">recommended</span>
            </label>
            <label class="fee-tier${feeTier === "priority" ? " selected" : ""}">
              <input type="radio" name="settingsFeeTier" value="priority"${chk("priority", feeTier)} />
              <span class="fee-tier-label">Priority</span>
              <span class="fee-tier-rate" id="sPriority">—</span>
              <span class="fee-tier-desc muted-line">fastest confirmation</span>
            </label>
            <label class="fee-tier fee-tier-custom${feeTier === "custom" ? " selected" : ""}">
              <input type="radio" name="settingsFeeTier" value="custom"${chk("custom", feeTier)} />
              <span class="fee-tier-label">Custom</span>
              <input id="sCustomRate" type="number" min="1" step="1"
                value="${customFeeRate}"
                class="fee-custom-input" />
              <span class="fee-tier-desc muted-line">sat/kB</span>
            </label>
          </div>
        </div>

        <label class="field" style="margin-top:1rem">
          <span>Default network for new pairings</span>
          <select id="defaultNetwork">
            <option value="main"${sel("main", defaultNetwork)}>Mainnet (BSV)</option>
            <option value="test"${sel("test", defaultNetwork)}>Testnet (TBSV)</option>
          </select>
        </label>
      </section>

      <section class="card">
        <h2>Display</h2>

        <label class="field">
          <span>Fiat currency (for balance toggle)</span>
          <select id="fiatCurrency">
            <option value="USD"${sel("USD", fiatCurrency)}>USD — US Dollar</option>
            <option value="EUR"${sel("EUR", fiatCurrency)}>EUR — Euro</option>
            <option value="GBP"${sel("GBP", fiatCurrency)}>GBP — British Pound</option>
            <option value="AUD"${sel("AUD", fiatCurrency)}>AUD — Australian Dollar</option>
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
          <p class="remove-confirm-msg warning-text">
            Are you sure? This will remove all paired wallets and preferences
            from this browser. You can re-pair by scanning your Pi again.
          </p>
          <div class="actions">
            <button id="clearConfirm" class="danger" type="button">Yes, clear all data</button>
            <button id="clearCancel" type="button">Cancel</button>
          </div>
        </div>
        <div class="actions" id="clearActions">
          <button id="clearBtn" class="danger-outline" type="button">Clear all data…</button>
        </div>
        <p id="clearStatus" class="muted-line"></p>
      </section>
    </main>
  `;

  // ---- element refs ----
  const $feeRateLoading  = root.querySelector<HTMLElement>("#feeRateLoading")!;
  const $fiat            = root.querySelector<HTMLSelectElement>("#fiatCurrency")!;
  const $network         = root.querySelector<HTMLSelectElement>("#defaultNetwork")!;
  const $clearBtn        = root.querySelector<HTMLButtonElement>("#clearBtn")!;
  const $clearStrip      = root.querySelector<HTMLElement>("#clearStrip")!;
  const $clearActions    = root.querySelector<HTMLElement>("#clearActions")!;
  const $clearConfirm    = root.querySelector<HTMLButtonElement>("#clearConfirm")!;
  const $clearCancel     = root.querySelector<HTMLButtonElement>("#clearCancel")!;
  const $clearStatus     = root.querySelector<HTMLElement>("#clearStatus")!;
  const $savedBanner     = root.querySelector<HTMLElement>("#settingsSavedBanner")!;
  const $customRateInput = root.querySelector<HTMLInputElement>("#sCustomRate")!;

  // ---- saved flash ----
  let savedTimer: ReturnType<typeof setTimeout> | null = null;
  function flashSaved(): void {
    $savedBanner.hidden = false;
    if (savedTimer) clearTimeout(savedTimer);
    savedTimer = setTimeout(() => { $savedBanner.hidden = true; savedTimer = null; }, 2000);
  }

  // ---- fee tier radios ----
  function highlightSelectedTier(): void {
    root.querySelectorAll<HTMLElement>(".fee-tier").forEach((el) => {
      const radio = el.querySelector<HTMLInputElement>("input[type=radio]");
      el.classList.toggle("selected", !!radio?.checked);
    });
  }

  root.querySelectorAll<HTMLInputElement>('input[name="settingsFeeTier"]').forEach((r) => {
    r.addEventListener("change", () => {
      highlightSelectedTier();
      localStorage.setItem(KEY_DEFAULT_FEE_TIER, r.value);
      flashSaved();
    });
  });

  $customRateInput.addEventListener("input", () => {
    const rate = parseInt($customRateInput.value, 10);
    if (Number.isInteger(rate) && rate > 0) {
      localStorage.setItem(KEY_CUSTOM_FEE_RATE, String(rate));
      flashSaved();
    }
  });

  // ---- load live fee rates from WoC mainnet ----
  void (async () => {
    let rec: FeeRecommendation | null = null;
    try {
      const woc = new WocClient({ baseUrl: effectiveWocBase("main") });
      rec = await fetchFeeRecommendation(woc);
    } catch { /* use defaults */ }

    const economy  = rec?.economy  ?? DEFAULT_FEE_RATE_SATSKB;
    const standard = rec?.standard ?? DEFAULT_FEE_RATE_SATSKB;
    const priority = rec?.priority ?? DEFAULT_FEE_RATE_SATSKB * 5;

    const $eco = root.querySelector<HTMLElement>("#sEconomy");
    const $std = root.querySelector<HTMLElement>("#sStandard");
    const $pri = root.querySelector<HTMLElement>("#sPriority");
    if ($eco) $eco.textContent = formatFeeRate(economy);
    if ($std) $std.textContent = formatFeeRate(standard);
    if ($pri) $pri.textContent = formatFeeRate(priority);
    $feeRateLoading.hidden = true;
  })();

  // ---- other settings ----
  $fiat.addEventListener("change", () => {
    localStorage.setItem(KEY_FIAT_CURRENCY, $fiat.value);
    flashSaved();
  });

  $network.addEventListener("change", () => {
    localStorage.setItem(KEY_DEFAULT_NETWORK, $network.value);
    flashSaved();
  });

  // ---- clear all data ----
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
      const keysToRemove: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k?.startsWith("piwallet.")) keysToRemove.push(k);
      }
      for (const k of keysToRemove) localStorage.removeItem(k);
      $clearStatus.classList.remove("error");
      $clearStatus.textContent = "All data cleared. Redirecting to wallets…";
      setTimeout(() => { window.location.hash = "#/wallets"; }, 1500);
    } catch (e) {
      $clearStatus.classList.add("error");
      $clearStatus.textContent = `clear failed: ${(e as Error).message}`;
      $clearConfirm.disabled = false;
      $clearConfirm.textContent = "Yes, clear all data";
    }
  });

  return () => {
    if (savedTimer) clearTimeout(savedTimer);
  };
}
