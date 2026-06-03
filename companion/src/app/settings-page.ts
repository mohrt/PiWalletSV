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
import {
  buildWalletBackupFile,
  importWalletBackup,
  serializeWalletBackup,
} from "../lib/wallet-backup.js";
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
  return Number.isInteger(stored) && stored >= 0 ? stored : DEFAULT_FEE_RATE_SATSKB;
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

  root.innerHTML = `
    <main class="page">
      ${renderHeader("Settings", "settings")}

      <p id="settingsSavedBanner" class="settings-saved-banner" hidden>✓ Settings saved</p>

      <section class="card">
        <h2>Send defaults</h2>

        <label class="field">
          <span>Default fee tier</span>
          <select id="settingsFeeTierSelect" class="fee-tier-select">
            <option value="economy"${sel("economy", feeTier)}>Economy</option>
            <option value="standard"${sel("standard", feeTier)}>Standard</option>
            <option value="priority"${sel("priority", feeTier)}>Priority</option>
            <option value="custom"${sel("custom", feeTier)}>Custom…</option>
          </select>
          <p class="muted-line send-fee-loading" id="feeRateLoading">Loading current rates…</p>
        </label>
        <div id="settingsFeeCustomRow" class="fee-custom-row"${feeTier === "custom" ? "" : " hidden"}>
          <label class="field">
            <span>Custom rate (sat/kB)</span>
            <input id="sCustomRate" type="number" min="0" step="1"
              value="${customFeeRate}"
              placeholder="${DEFAULT_FEE_RATE_SATSKB}" />
          </label>
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
        <h2>Offline use</h2>
        <p class="muted-line">
          After the first load, the app shell and your paired wallets stay
          cached in this browser. You can open wallets and view the last
          cached balance or history without network access.
        </p>
        <p class="muted-line">
          Live balance scans, transaction history, fee estimates, and broadcast
          need internet. Camera pairing works offline once the app is loaded,
          but chain data always requires connectivity.
        </p>
      </section>

      <section class="card">
        <h2>Backup &amp; migration</h2>
        <p class="muted-line">
          Export a JSON file of your paired wallets (xpub and labels only —
          no seed phrases or private keys). Import it on another phone or
          after clearing browser data to avoid re-scanning the Pi.
        </p>
        <div class="actions">
          <button id="exportWallets" class="primary" type="button">
            Export paired wallets
          </button>
          <label class="button-like">
            Import backup…
            <input id="importWalletsFile" type="file" accept=".json,application/json" hidden />
          </label>
        </div>
        <p id="backupStatus" class="muted-line" aria-live="polite"></p>
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
  const $feeTierSelect   = root.querySelector<HTMLSelectElement>("#settingsFeeTierSelect")!;
  const $feeCustomRow    = root.querySelector<HTMLElement>("#settingsFeeCustomRow")!;
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
  const $exportWallets   = root.querySelector<HTMLButtonElement>("#exportWallets")!;
  const $importFile      = root.querySelector<HTMLInputElement>("#importWalletsFile")!;
  const $backupStatus    = root.querySelector<HTMLElement>("#backupStatus")!;

  // ---- saved flash ----
  let savedTimer: ReturnType<typeof setTimeout> | null = null;
  function flashSaved(): void {
    $savedBanner.hidden = false;
    if (savedTimer) clearTimeout(savedTimer);
    savedTimer = setTimeout(() => { $savedBanner.hidden = true; savedTimer = null; }, 2000);
  }

  let feeRec: FeeRecommendation | null = null;

  function refreshFeeTierLabels(): void {
    const economy = feeRec?.economy ?? DEFAULT_FEE_RATE_SATSKB;
    const standard = feeRec?.standard ?? DEFAULT_FEE_RATE_SATSKB;
    const priority = feeRec?.priority ?? DEFAULT_FEE_RATE_SATSKB * 5;
    const tier = $feeTierSelect.value;

    function fmtOptionLabel(name: string, rate: number): string {
      return `${name} — ${formatFeeRate(rate)}`;
    }

    for (const [value, name, rate] of [
      ["economy", "Economy", economy],
      ["standard", "Standard", standard],
      ["priority", "Priority", priority],
    ] as const) {
      const opt = $feeTierSelect.querySelector<HTMLOptionElement>(`option[value="${value}"]`);
      if (opt) opt.textContent = fmtOptionLabel(name, rate);
    }

    const customOpt = $feeTierSelect.querySelector<HTMLOptionElement>('option[value="custom"]');
    if (customOpt) {
      const parsed = parseInt($customRateInput.value, 10);
      const customRate = Number.isInteger(parsed) && parsed >= 0
        ? parsed
        : getDefaultCustomFeeRate();
      customOpt.textContent = tier === "custom"
        ? fmtOptionLabel("Custom", customRate)
        : "Custom…";
    }
    $feeTierSelect.value = tier;
  }

  function onSettingsFeeTierChanged(): void {
    $feeCustomRow.hidden = $feeTierSelect.value !== "custom";
    localStorage.setItem(KEY_DEFAULT_FEE_TIER, $feeTierSelect.value);
    refreshFeeTierLabels();
    flashSaved();
  }

  $feeTierSelect.addEventListener("change", onSettingsFeeTierChanged);

  $customRateInput.addEventListener("input", () => {
    if ($feeTierSelect.value === "custom") refreshFeeTierLabels();
  });

  $customRateInput.addEventListener("blur", () => {
    const rate = parseInt($customRateInput.value, 10);
    if (Number.isInteger(rate) && rate >= 0) {
      localStorage.setItem(KEY_CUSTOM_FEE_RATE, String(rate));
      refreshFeeTierLabels();
      flashSaved();
    }
  });

  // ---- load live fee rates from WoC mainnet ----
  void (async () => {
    try {
      const woc = new WocClient({ baseUrl: effectiveWocBase("main") });
      feeRec = await fetchFeeRecommendation(woc);
    } catch { /* use defaults */ }

    refreshFeeTierLabels();
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

  // ---- wallet backup export / import ----
  function setBackupStatus(msg: string, isError = false): void {
    $backupStatus.textContent = msg;
    $backupStatus.classList.toggle("error", isError);
  }

  $exportWallets.addEventListener("click", async () => {
    $exportWallets.disabled = true;
    setBackupStatus("");
    try {
      const file = await buildWalletBackupFile();
      const json = serializeWalletBackup(file);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ts = new Date().toISOString().replace(/[:.]/g, "-");
      a.download = `piwallet-paired-wallets-${ts}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setBackupStatus(
        file.wallets.length === 0
          ? "Exported empty backup — no paired wallets yet."
          : `Exported ${file.wallets.length} wallet${file.wallets.length === 1 ? "" : "s"}.`,
      );
      flashSaved();
    } catch (e) {
      setBackupStatus(`export failed: ${(e as Error).message}`, true);
    } finally {
      $exportWallets.disabled = false;
    }
  });

  $importFile.addEventListener("change", () => {
    const file = $importFile.files?.[0];
    $importFile.value = "";
    if (!file) return;
    void (async () => {
      setBackupStatus("Importing…");
      try {
        const raw = await file.text();
        const result = await importWalletBackup(raw);
        const parts: string[] = [];
        if (result.imported > 0) {
          parts.push(
            `imported ${result.imported} wallet${result.imported === 1 ? "" : "s"}`,
          );
        }
        if (result.skippedDuplicates > 0) {
          parts.push(
            `skipped ${result.skippedDuplicates} duplicate${result.skippedDuplicates === 1 ? "" : "s"}`,
          );
        }
        if (result.failed.length > 0) {
          parts.push(
            `${result.failed.length} failed (${result.failed.map((f) => f.label).join(", ")})`,
          );
        }
        const summary = parts.length > 0 ? parts.join("; ") + "." : "Nothing to import.";
        setBackupStatus(summary, result.failed.length > 0 && result.imported === 0);
        if (result.imported > 0) flashSaved();
      } catch (e) {
        setBackupStatus(`import failed: ${(e as Error).message}`, true);
      }
    })();
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
