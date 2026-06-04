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
import { _clearAllWallets, listWallets } from "../lib/wallets.js";
import {
  buildWalletBackupFile,
  buildWalletBackupPw1Lines,
  formatImportWalletResult,
  importWalletBackup,
  importWalletBackupBytes,
  type BackupExportScope,
  type ImportWalletMode,
  serializeWalletBackup,
  walletBackupBytesToJson,
} from "../lib/wallet-backup.js";
import {
  APP_VERSION,
  BACKUP_FORMAT_VERSION,
  formatAppVersion,
} from "../lib/version.js";
import { mountCameraScanner, type CameraScannerHandle } from "./camera-scanner.js";
import {
  clearPw1QrCanvas,
  startPw1QrPlayback,
  wirePw1QrControls,
  type Pw1QrPlayback,
} from "../lib/pw1-qr-playback.js";
import { WocClient, effectiveWocBase } from "../lib/woc.js";
import {
  DEFAULT_FEE_RATE_SATSKB,
  type FeeRecommendation,
  fetchFeeRecommendation,
  formatFeeRate,
} from "../lib/fee.js";

import {
  KEY_CUSTOM_FEE_RATE,
  KEY_DEFAULT_FEE_TIER,
  KEY_DEFAULT_NETWORK,
  KEY_FIAT_CURRENCY,
  getDefaultCustomFeeRate as readCustomFeeRate,
  getDefaultFeeTier,
  getDefaultNetwork,
  getFiatCurrency,
  getThemePreference,
  type ThemePreference,
} from "../lib/companion-settings.js";
import {
  getAddressBook,
  removeAddressBookEntry,
  updateAddressBookLabel,
  upsertAddressBookEntry,
} from "../lib/address-book.js";
import { getFeeHistory } from "../lib/fee-history.js";
import { relativeTimeFrom } from "../lib/relative-time.js";
import { setThemePreference } from "../lib/theme.js";

export type { FeeTier, FiatCurrency, DefaultNetwork } from "../lib/companion-settings.js";
export { getDefaultFeeTier, getFiatCurrency, getDefaultNetwork } from "../lib/companion-settings.js";

export function getDefaultCustomFeeRate(): number {
  return readCustomFeeRate(DEFAULT_FEE_RATE_SATSKB);
}

export function mountSettingsPage(root: HTMLElement): () => void {
  const feeTier        = getDefaultFeeTier();
  const customFeeRate  = getDefaultCustomFeeRate();
  const fiatCurrency   = getFiatCurrency();
  const defaultNetwork = getDefaultNetwork();
  const themePref        = getThemePreference();

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
          <div id="feeHistoryBlock" hidden>
            <p class="muted-line" style="margin-top:0.75rem">Recent standard-tier samples (local)</p>
            <table class="fee-history-table" id="feeHistoryTable">
              <thead>
                <tr><th>When</th><th>Standard</th><th>Source</th></tr>
              </thead>
              <tbody id="feeHistoryBody"></tbody>
            </table>
          </div>
        </label>
        <div id="settingsFeeCustomRow" class="fee-custom-row"${feeTier === "custom" ? "" : " hidden"}>
          <label class="field">
            <span>Custom rate (sat/kB)</span>
            <input id="sCustomRate" type="number" min="0" step="1"
              value="${customFeeRate}"
              placeholder="${DEFAULT_FEE_RATE_SATSKB}"
              aria-describedby="customRateStatus" />
            <p id="customRateStatus" class="muted-line" aria-live="polite"></p>
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
          <span>Theme</span>
          <select id="themePreference">
            <option value="dark"${sel("dark", themePref)}>Dark</option>
            <option value="light"${sel("light", themePref)}>Light</option>
            <option value="system"${sel("system", themePref)}>System</option>
          </select>
        </label>

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
        <h2>Address book</h2>
        <p class="muted-line">
          Saved send recipients, scoped by network. Addresses are added after
          a successful send; edit labels here or pick them on the Send tab.
        </p>
        <label class="field">
          <span>Add address manually</span>
          <input id="addressBookAddInput" type="text" autocomplete="off"
            placeholder="1… or m… / n…" spellcheck="false" />
        </label>
        <label class="field">
          <span>Label (optional)</span>
          <input id="addressBookAddLabel" type="text" maxlength="48"
            autocomplete="off" spellcheck="false" />
        </label>
        <label class="field">
          <span>Network</span>
          <select id="addressBookAddNetwork">
            <option value="main"${sel("main", defaultNetwork)}>Mainnet</option>
            <option value="test"${sel("test", defaultNetwork)}>Testnet</option>
          </select>
        </label>
        <div class="actions">
          <button id="addressBookAddBtn" type="button" class="primary">Save address</button>
        </div>
        <p id="addressBookAddStatus" class="muted-line" aria-live="polite"></p>
        <ul id="addressBookList" class="address-book-list"></ul>
        <p id="addressBookEmpty" class="muted-line">No saved addresses yet.</p>
      </section>

      <section class="card">
        <details class="backup-section" id="backupSection">
          <summary>Backup &amp; migration</summary>

          <details class="backup-fold" id="backupFold-export">
            <summary>Export</summary>
            <div class="backup-fold-body">
            <fieldset class="import-mode-field export-scope-field">
              <legend>Export includes</legend>
              <label>
                <input type="radio" name="exportScope" value="wallets-only" />
                Wallets only
              </label>
              <label>
                <input type="radio" name="exportScope" value="wallets-and-settings" checked />
                Wallets and settings
              </label>
            </fieldset>
            <p class="muted-line export-scope-hint">
              Wallets only: pairing metadata and receive index. With settings:
              fee tier, fiat currency, list sort, and cached balances/history.
            </p>
            <div class="backup-tabs backup-sub-tabs" role="tablist" aria-label="Export method">
              <button type="button" class="backup-tab active" role="tab" id="exportTabBtn-qr"
                data-export-tab="qr" aria-selected="true" aria-controls="exportTab-qr" tabindex="0">
                Transfer QR
              </button>
              <button type="button" class="backup-tab" role="tab" id="exportTabBtn-json"
                data-export-tab="json" aria-selected="false" aria-controls="exportTab-json" tabindex="-1">
                View / copy JSON
              </button>
            </div>
            <div id="exportTab-qr" class="backup-tab-panel" role="tabpanel"
              aria-labelledby="exportTabBtn-qr" tabindex="0">
              <div class="actions">
                <button id="exportQrToggle" class="primary" type="button">
                  Show transfer QR
                </button>
              </div>
              <div id="exportQrPanel" class="backup-qr-panel" hidden>
                <p id="exportQrHint" class="muted-line">
                  Point the other phone at this animated QR.
                </p>
                <canvas id="exportQrCanvas" width="320" height="320"></canvas>
                <p id="exportQrProgress" class="muted-line">Frame 1 / 1</p>
                <div class="actions pw1-qr-controls">
                  <button id="exportQrPrev" type="button" hidden>Previous</button>
                  <button id="exportQrNext" type="button" hidden>Next</button>
                  <button id="exportQrPause" type="button">Pause</button>
                </div>
              </div>
            </div>
            <div id="exportTab-json" class="backup-tab-panel" role="tabpanel"
              aria-labelledby="exportTabBtn-json" tabindex="-1" hidden>
              <div class="backup-json-row">
                <textarea id="exportJsonView" class="hex-blob" rows="8" readonly
                  spellcheck="false" autocorrect="off"
                  aria-label="Exported wallet backup JSON"></textarea>
                <div class="backup-json-actions">
                  <button id="exportDownload" type="button" class="icon-btn"
                    title="Download JSON" aria-label="Download JSON">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"
                      fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                      aria-hidden="true">
                      <path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>
                    </svg>
                  </button>
                  <button id="exportCopy" type="button" class="icon-btn"
                    title="Copy JSON" aria-label="Copy JSON">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"
                      fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                      aria-hidden="true">
                      <rect x="9" y="9" width="13" height="13" rx="2"/>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                    </svg>
                  </button>
                </div>
              </div>
            </div>
            </div>
          </details>

          <details class="backup-fold" id="backupFold-import">
            <summary>Import</summary>
            <div class="backup-fold-body">
            <fieldset class="import-mode-field">
              <legend>Import mode</legend>
              <label>
                <input type="radio" name="importMode" value="merge" checked />
                Add to existing wallets
              </label>
              <label>
                <input type="radio" name="importMode" value="replace" />
                Replace all wallets on this device
              </label>
            </fieldset>
            <p id="importReplaceWarning" class="warning-text" hidden>
              Replace removes every paired wallet in this browser before
              importing the backup. This cannot be undone.
            </p>
            <div id="importReplaceStrip" hidden>
              <p id="importReplaceMsg" class="remove-confirm-msg warning-text"></p>
              <div class="actions">
                <button id="importReplaceConfirm" class="danger" type="button">
                  Yes, replace and import
                </button>
                <button id="importReplaceCancel" type="button">Cancel</button>
              </div>
            </div>
            <div class="backup-tabs backup-sub-tabs" role="tablist" aria-label="Import method">
              <button type="button" class="backup-tab active" role="tab" id="importTabBtn-qr"
                data-import-tab="qr" aria-selected="true" aria-controls="importTab-qr" tabindex="0">
                Scan transfer QR
              </button>
              <button type="button" class="backup-tab" role="tab" id="importTabBtn-json"
                data-import-tab="json" aria-selected="false" aria-controls="importTab-json" tabindex="-1">
                JSON file / paste
              </button>
            </div>
            <div id="importTab-qr" class="backup-tab-panel" role="tabpanel"
              aria-labelledby="importTabBtn-qr" tabindex="0">
              <div class="actions">
                <button id="importQrToggle" class="primary" type="button">
                  Scan transfer QR
                </button>
              </div>
              <div id="importQrPanel" class="backup-scan-panel" hidden>
                <div id="importQrHost"></div>
              </div>
            </div>
            <div id="importTab-json" class="backup-tab-panel" role="tabpanel"
              aria-labelledby="importTabBtn-json" tabindex="-1" hidden>
              <label class="button-like">
                Choose JSON file…
                <input id="importWalletsFile" type="file"
                  accept=".json,application/json" hidden />
              </label>
              <textarea id="importPasteJson" class="hex-blob" rows="6"
                placeholder='{"format":"piwallet-companion-wallets",…}'
                spellcheck="false" autocorrect="off" autocomplete="off"></textarea>
              <div class="actions">
                <button id="importPasteBtn" class="primary" type="button">
                  Import pasted JSON
                </button>
                <button id="importPasteClear" type="button">Clear</button>
              </div>
            </div>
            </div>
          </details>

          <p class="muted-line backup-format-note">
            Backup format v${BACKUP_FORMAT_VERSION} (companion
            ${formatAppVersion(APP_VERSION)}). Import requires this version or
            newer; older apps cannot read backups from newer versions.
          </p>
          <p id="backupStatus" class="muted-line" aria-live="polite"></p>
        </details>
      </section>

      <section class="card">
        <h2>About</h2>
        <p class="muted-line">
          Companion ${formatAppVersion(APP_VERSION)}
        </p>
        <p class="muted-line">
          Pair with PiWalletSV on your Pi device. The Pi shows its version
          on Settings.
        </p>
        <p class="muted-line">
          Cached balances and history from your last scan remain visible
          offline. Refreshing balances, sending, pairing, and scanning
          transfer QRs require network access.
        </p>
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
  const $themePref       = root.querySelector<HTMLSelectElement>("#themePreference")!;
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
  const $customRateStatus = root.querySelector<HTMLElement>("#customRateStatus")!;
  const $feeHistoryBlock  = root.querySelector<HTMLElement>("#feeHistoryBlock")!;
  const $feeHistoryBody   = root.querySelector<HTMLElement>("#feeHistoryBody")!;
  const $addressBookList  = root.querySelector<HTMLElement>("#addressBookList")!;
  const $addressBookEmpty = root.querySelector<HTMLElement>("#addressBookEmpty")!;
  const $addressBookAddInput = root.querySelector<HTMLInputElement>("#addressBookAddInput")!;
  const $addressBookAddLabel = root.querySelector<HTMLInputElement>("#addressBookAddLabel")!;
  const $addressBookAddNetwork = root.querySelector<HTMLSelectElement>("#addressBookAddNetwork")!;
  const $addressBookAddBtn = root.querySelector<HTMLButtonElement>("#addressBookAddBtn")!;
  const $addressBookAddStatus = root.querySelector<HTMLElement>("#addressBookAddStatus")!;
  const $exportDownload   = root.querySelector<HTMLButtonElement>("#exportDownload")!;
  const $exportCopy       = root.querySelector<HTMLButtonElement>("#exportCopy")!;
  const $exportQrToggle   = root.querySelector<HTMLButtonElement>("#exportQrToggle")!;
  const $exportQrPanel    = root.querySelector<HTMLElement>("#exportQrPanel")!;
  const $exportQrCanvas   = root.querySelector<HTMLCanvasElement>("#exportQrCanvas")!;
  const $exportQrProgress = root.querySelector<HTMLElement>("#exportQrProgress")!;
  const $exportQrPause    = root.querySelector<HTMLButtonElement>("#exportQrPause")!;
  const $exportQrPrev     = root.querySelector<HTMLButtonElement>("#exportQrPrev")!;
  const $exportQrNext     = root.querySelector<HTMLButtonElement>("#exportQrNext")!;
  const $exportQrHint     = root.querySelector<HTMLElement>("#exportQrHint")!;
  const $exportJsonView   = root.querySelector<HTMLTextAreaElement>("#exportJsonView")!;
  const $importFile       = root.querySelector<HTMLInputElement>("#importWalletsFile")!;
  const $importPaste      = root.querySelector<HTMLTextAreaElement>("#importPasteJson")!;
  const $importPasteBtn   = root.querySelector<HTMLButtonElement>("#importPasteBtn")!;
  const $importPasteClear = root.querySelector<HTMLButtonElement>("#importPasteClear")!;
  const $importQrToggle   = root.querySelector<HTMLButtonElement>("#importQrToggle")!;
  const $importQrPanel    = root.querySelector<HTMLElement>("#importQrPanel")!;
  const $importQrHost     = root.querySelector<HTMLElement>("#importQrHost")!;
  const $importReplaceWarning = root.querySelector<HTMLElement>("#importReplaceWarning")!;
  const $importReplaceStrip = root.querySelector<HTMLElement>("#importReplaceStrip")!;
  const $importReplaceMsg = root.querySelector<HTMLElement>("#importReplaceMsg")!;
  const $importReplaceConfirm = root.querySelector<HTMLButtonElement>("#importReplaceConfirm")!;
  const $importReplaceCancel = root.querySelector<HTMLButtonElement>("#importReplaceCancel")!;
  const $backupSection    = root.querySelector<HTMLDetailsElement>("#backupSection")!;
  const $backupExportFold = root.querySelector<HTMLDetailsElement>("#backupFold-export")!;
  const $backupImportFold = root.querySelector<HTMLDetailsElement>("#backupFold-import")!;
  const $backupStatus     = root.querySelector<HTMLElement>("#backupStatus")!;

  let exportQrPlayback: Pw1QrPlayback | null = null;
  let exportQrUnwire: (() => void) | null = null;
  let importQrScan: CameraScannerHandle | null = null;
  let pendingReplaceRaw: string | null = null;

  // ---- saved flash ----
  const SAVED_BANNER_DEFAULT = "✓ Settings saved";
  let savedTimer: ReturnType<typeof setTimeout> | null = null;
  function flashSaved(message = SAVED_BANNER_DEFAULT): void {
    $savedBanner.textContent = message;
    $savedBanner.hidden = false;
    if (savedTimer) clearTimeout(savedTimer);
    savedTimer = setTimeout(() => {
      $savedBanner.hidden = true;
      $savedBanner.textContent = SAVED_BANNER_DEFAULT;
      savedTimer = null;
    }, 2000);
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
    const isCustom = $feeTierSelect.value === "custom";
    $feeCustomRow.hidden = !isCustom;
    if (!isCustom) setCustomRateStatus("");
    localStorage.setItem(KEY_DEFAULT_FEE_TIER, $feeTierSelect.value);
    refreshFeeTierLabels();
    flashSaved();
  }

  $feeTierSelect.addEventListener("change", onSettingsFeeTierChanged);

  function setCustomRateStatus(msg: string, isError = false): void {
    $customRateStatus.textContent = msg;
    $customRateStatus.classList.toggle("error", isError);
    if (isError) {
      $customRateInput.setAttribute("aria-invalid", "true");
    } else {
      $customRateInput.removeAttribute("aria-invalid");
    }
  }

  function parseCustomRateInput(): number | null {
    const rate = parseInt($customRateInput.value, 10);
    if (!Number.isInteger(rate) || rate < 0) return null;
    return rate;
  }

  function trySaveCustomRate(): boolean {
    const rate = parseCustomRateInput();
    if (rate === null) {
      const trimmed = $customRateInput.value.trim();
      if ($feeTierSelect.value === "custom" && trimmed === "") {
        setCustomRateStatus("Enter a custom fee rate (sat/kB)", true);
      } else if (trimmed !== "") {
        setCustomRateStatus("Enter a whole number ≥ 0", true);
      }
      return false;
    }
    setCustomRateStatus("");
    localStorage.setItem(KEY_CUSTOM_FEE_RATE, String(rate));
    refreshFeeTierLabels();
    flashSaved();
    return true;
  }

  $customRateInput.addEventListener("input", () => {
    if ($feeTierSelect.value === "custom") refreshFeeTierLabels();
    if (parseCustomRateInput() !== null) setCustomRateStatus("");
  });

  $customRateInput.addEventListener("blur", () => {
    trySaveCustomRate();
  });

  $customRateInput.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    trySaveCustomRate();
    $customRateInput.blur();
  });


  function renderFeeHistory(): void {
    const history = getFeeHistory().slice().reverse().slice(0, 12);
    if (history.length === 0) {
      $feeHistoryBlock.hidden = true;
      return;
    }
    $feeHistoryBlock.hidden = false;
    $feeHistoryBody.innerHTML = history
      .map(
        (s) =>
          `<tr>` +
          `<td>${escapeHtml(relativeTimeFrom(s.at))}</td>` +
          `<td>${escapeHtml(formatFeeRate(s.standard))}</td>` +
          `<td>${s.fromApi ? "WoC" : "default"}</td>` +
          `</tr>`,
      )
      .join("");
  }

  function escapeHtml(s: string): string {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderAddressBookList(): void {
    const entries = getAddressBook();
    $addressBookEmpty.hidden = entries.length > 0;
    $addressBookList.innerHTML = entries
      .map((e) => {
        const net = e.network === "test" ? "testnet" : "mainnet";
        const label = escapeHtml(e.label || "—");
        const addr = escapeHtml(e.address);
        return (
          `<li class="address-book-item" data-address="${addr}" data-network="${e.network}">` +
          `<input class="address-book-label-input" type="text" maxlength="48" ` +
          `value="${label === "—" ? "" : label}" placeholder="Label" ` +
          `aria-label="Label for ${addr}" />` +
          `<code>${addr}</code>` +
          `<span class="muted-line">${net}</span>` +
          `<button type="button" class="address-book-remove" aria-label="Remove saved address">Remove</button>` +
          `</li>`
        );
      })
      .join("");
  }

  $themePref.addEventListener("change", () => {
    setThemePreference($themePref.value as ThemePreference);
    flashSaved();
  });

  $addressBookList.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>(".address-book-remove");
    if (!btn) return;
    const li = btn.closest<HTMLElement>(".address-book-item");
    if (!li) return;
    const address = li.dataset.address ?? "";
    const network = (li.dataset.network ?? "main") as "main" | "test";
    removeAddressBookEntry(address, network);
    renderAddressBookList();
    flashSaved();
  });

  $addressBookList.addEventListener("change", (e) => {
    const input = e.target as HTMLInputElement;
    if (!input.classList.contains("address-book-label-input")) return;
    const li = input.closest<HTMLElement>(".address-book-item");
    if (!li) return;
    updateAddressBookLabel(
      li.dataset.address ?? "",
      (li.dataset.network ?? "main") as "main" | "test",
      input.value,
    );
    flashSaved();
  });

  $addressBookAddBtn.addEventListener("click", () => {
    const raw = $addressBookAddInput.value.trim();
    const network = $addressBookAddNetwork.value as "main" | "test";
    $addressBookAddStatus.classList.remove("error");
    if (!raw) {
      $addressBookAddStatus.classList.add("error");
      $addressBookAddStatus.textContent = "enter an address";
      return;
    }
    if (!/^[13mn][a-km-zA-HJ-NP-Z1-9]{20,}$/.test(raw)) {
      $addressBookAddStatus.classList.add("error");
      $addressBookAddStatus.textContent = "does not look like a BSV address";
      return;
    }
    upsertAddressBookEntry(raw, network, $addressBookAddLabel.value.trim());
    $addressBookAddInput.value = "";
    $addressBookAddLabel.value = "";
    $addressBookAddStatus.textContent = "Saved.";
    renderAddressBookList();
    flashSaved();
  });

  renderAddressBookList();

  // ---- load live fee rates from WoC mainnet ----
  void (async () => {
    try {
      const woc = new WocClient({ baseUrl: effectiveWocBase("main") });
      feeRec = await fetchFeeRecommendation(woc);
    } catch { /* use defaults */ }

    refreshFeeTierLabels();
    renderFeeHistory();
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

  function applyImportResult(result: Awaited<ReturnType<typeof importWalletBackup>>): void {
    const summary = formatImportWalletResult(result);
    const isError = result.failed.length > 0 && result.imported === 0;
    setBackupStatus(summary, isError);
    if (!isError) flashSaved("✓ Import complete");
  }

  async function loadBackupJson(): Promise<string> {
    const file = await buildWalletBackupFile({ scope: getExportScope() });
    return serializeWalletBackup(file);
  }

  function getExportScope(): BackupExportScope {
    const checked = root.querySelector<HTMLInputElement>(
      'input[name="exportScope"]:checked',
    );
    return checked?.value === "wallets-only"
      ? "wallets-only"
      : "wallets-and-settings";
  }

  function onExportScopeChange(): void {
    if (isExportQrVisible()) stopExportQr();
    if (isExportJsonTabActive()) void refreshExportJsonView();
  }

  for (const r of root.querySelectorAll<HTMLInputElement>('input[name="exportScope"]')) {
    r.addEventListener("change", onExportScopeChange);
  }

  function getImportMode(): ImportWalletMode {
    const checked = root.querySelector<HTMLInputElement>(
      'input[name="importMode"]:checked',
    );
    return checked?.value === "replace" ? "replace" : "merge";
  }

  function syncImportModeUi(): void {
    const replace = getImportMode() === "replace";
    $importReplaceWarning.hidden = !replace;
    if (!replace) hideReplaceStrip();
  }

  function hideReplaceStrip(): void {
    pendingReplaceRaw = null;
    $importReplaceStrip.hidden = true;
    $importReplaceMsg.textContent = "";
  }

  for (const r of root.querySelectorAll<HTMLInputElement>('input[name="importMode"]')) {
    r.addEventListener("change", syncImportModeUi);
  }
  syncImportModeUi();

  type ExportBackupTab = "qr" | "json";
  type ImportBackupTab = "qr" | "json";

  let activeExportTab: ExportBackupTab = "qr";
  let activeImportTab: ImportBackupTab = "qr";

  function syncBackupSubTabFocus(
    attr: "data-export-tab" | "data-import-tab",
    active: string,
    panelPrefix: string,
  ): void {
    root.querySelectorAll<HTMLButtonElement>(`[${attr}]`).forEach((btn) => {
      const selected = btn.getAttribute(attr) === active;
      btn.setAttribute("aria-selected", selected ? "true" : "false");
      btn.tabIndex = selected ? 0 : -1;
    });
    root.querySelectorAll<HTMLElement>(`.backup-tab-panel[id^="${panelPrefix}"]`).forEach((panel) => {
      panel.tabIndex = panel.id === `${panelPrefix}${active}` ? 0 : -1;
    });
  }

  function bindBackupSubTabNav(
    tablistSelector: string,
    attr: "data-export-tab" | "data-import-tab",
    tabs: readonly string[],
    getActive: () => string,
    switchTab: (tab: string) => void,
  ): void {
    root.querySelector<HTMLElement>(tablistSelector)?.addEventListener("keydown", (e) => {
      const ke = e as KeyboardEvent;
      if (ke.key !== "ArrowLeft" && ke.key !== "ArrowRight") return;
      ke.preventDefault();
      const active = getActive();
      const idx = tabs.indexOf(active);
      if (idx < 0) return;
      const next =
        ke.key === "ArrowRight"
          ? tabs[(idx + 1) % tabs.length]
          : tabs[(idx - 1 + tabs.length) % tabs.length];
      switchTab(next);
      root.querySelector<HTMLButtonElement>(`[${attr}="${next}"]`)?.focus();
    });
  }


  function isExportJsonTabActive(): boolean {
    return root.querySelector<HTMLButtonElement>('[data-export-tab="json"]')
      ?.classList.contains("active") ?? false;
  }

  function onExportFoldToggle(): void {
    if (!$backupExportFold.open) {
      stopExportQr();
      return;
    }
    if (isExportJsonTabActive()) void refreshExportJsonView();
  }

  function onImportFoldToggle(): void {
    if (!$backupImportFold.open) {
      stopImportQrScan();
      hideReplaceStrip();
    }
  }

  $backupExportFold.addEventListener("toggle", onExportFoldToggle);
  $backupImportFold.addEventListener("toggle", onImportFoldToggle);

  $backupSection.addEventListener("toggle", () => {
    if (!$backupSection.open) {
      stopExportQr();
      stopImportQrScan();
      hideReplaceStrip();
    }
  });

  function switchExportTab(tab: ExportBackupTab): void {
    activeExportTab = tab;
    if (tab !== "qr" && isExportQrVisible()) stopExportQr();
    root.querySelector<HTMLElement>("#exportTab-qr")!.hidden = tab !== "qr";
    root.querySelector<HTMLElement>("#exportTab-json")!.hidden = tab !== "json";
    root.querySelectorAll<HTMLButtonElement>("[data-export-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.exportTab === tab);
    });
    syncBackupSubTabFocus("data-export-tab", tab, "exportTab-");
    if (tab === "json") void refreshExportJsonView();
  }

  async function refreshExportJsonView(): Promise<void> {
    $exportJsonView.value = "Loading…";
    try {
      $exportJsonView.value = await loadBackupJson();
    } catch (e) {
      $exportJsonView.value = "";
      setBackupStatus(`export failed: ${(e as Error).message}`, true);
    }
  }

  function switchImportTab(tab: ImportBackupTab): void {
    activeImportTab = tab;
    if (tab !== "qr" && isImportQrActive()) stopImportQrScan();
    root.querySelector<HTMLElement>("#importTab-qr")!.hidden = tab !== "qr";
    root.querySelector<HTMLElement>("#importTab-json")!.hidden = tab !== "json";
    root.querySelectorAll<HTMLButtonElement>("[data-import-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.importTab === tab);
    });
    syncBackupSubTabFocus("data-import-tab", tab, "importTab-");
  }

  root.querySelectorAll<HTMLButtonElement>("[data-export-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchExportTab(btn.dataset.exportTab as ExportBackupTab);
    });
  });

  root.querySelectorAll<HTMLButtonElement>("[data-import-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchImportTab(btn.dataset.importTab as ImportBackupTab);
    });
  });

  bindBackupSubTabNav(
    '[aria-label="Export method"]',
    "data-export-tab",
    ["qr", "json"],
    () => activeExportTab,
    (tab) => switchExportTab(tab as ExportBackupTab),
  );
  bindBackupSubTabNav(
    '[aria-label="Import method"]',
    "data-import-tab",
    ["qr", "json"],
    () => activeImportTab,
    (tab) => switchImportTab(tab as ImportBackupTab),
  );

  function stopExportQr(): void {
    exportQrUnwire?.();
    exportQrUnwire = null;
    exportQrPlayback?.stop();
    exportQrPlayback = null;
    clearPw1QrCanvas($exportQrCanvas);
    $exportQrPanel.hidden = true;
    $exportQrPause.textContent = "Pause";
    $exportQrPause.hidden = false;
    $exportQrPrev.hidden = true;
    $exportQrNext.hidden = true;
    $exportQrToggle.textContent = "Show transfer QR";
  }

  function stopImportQrScan(): void {
    importQrScan?.destroy();
    importQrScan = null;
    $importQrPanel.hidden = true;
    $importQrToggle.textContent = "Scan transfer QR";
    $importQrToggle.disabled = false;
  }

  function isExportQrVisible(): boolean {
    return exportQrPlayback !== null;
  }

  function isImportQrActive(): boolean {
    return importQrScan !== null;
  }

  async function runImportRaw(raw: string, confirmed = false): Promise<void> {
    hideReplaceStrip();
    const mode = getImportMode();
    if (mode === "replace" && !confirmed) {
      const existing = await listWallets();
      if (existing.length > 0) {
        pendingReplaceRaw = raw;
        $importReplaceMsg.textContent =
          `Replace ${existing.length} existing wallet${existing.length === 1 ? "" : "s"} with this backup?`;
        $importReplaceStrip.hidden = false;
        return;
      }
    }

    setBackupStatus("Importing…");
    try {
      const result = await importWalletBackup(raw.trim(), { mode });
      applyImportResult(result);
    } catch (e) {
      setBackupStatus(`import failed: ${(e as Error).message}`, true);
    }
  }

  async function runImportBytes(bytes: Uint8Array, confirmed = false): Promise<void> {
    hideReplaceStrip();
    const mode = getImportMode();
    if (mode === "replace" && !confirmed) {
      const existing = await listWallets();
      if (existing.length > 0) {
        pendingReplaceRaw = walletBackupBytesToJson(bytes);
        $importReplaceMsg.textContent =
          `Replace ${existing.length} existing wallet${existing.length === 1 ? "" : "s"} with this backup?`;
        $importReplaceStrip.hidden = false;
        return;
      }
    }

    setBackupStatus("Importing…");
    try {
      const result = await importWalletBackupBytes(bytes, { mode });
      applyImportResult(result);
    } catch (e) {
      setBackupStatus(
        `scan import failed: ${(e as Error).message}. ` +
          "Make sure you scanned the transfer QR from Settings on the other phone.",
        true,
      );
    }
  }

  $importReplaceConfirm.addEventListener("click", () => {
    const raw = pendingReplaceRaw;
    if (!raw) return;
    void runImportRaw(raw, true);
  });

  $importReplaceCancel.addEventListener("click", hideReplaceStrip);

  $exportDownload.addEventListener("click", async () => {
    $exportDownload.disabled = true;
    setBackupStatus("");
    try {
      const json = $exportJsonView.value.trim() || await loadBackupJson();
      if (json === "Loading…") {
        setBackupStatus("JSON still loading — try again in a moment", true);
        return;
      }
      $exportJsonView.value = json;
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
      const count = (JSON.parse(json) as { wallets: unknown[] }).wallets.length;
      setBackupStatus(
        count === 0
          ? "Downloaded empty backup — no paired wallets yet."
          : `Downloaded JSON for ${count} wallet${count === 1 ? "" : "s"}.`,
      );
      flashSaved();
    } catch (e) {
      setBackupStatus(`export failed: ${(e as Error).message}`, true);
    } finally {
      $exportDownload.disabled = false;
    }
  });

  $exportCopy.addEventListener("click", async () => {
    $exportCopy.disabled = true;
    setBackupStatus("");
    try {
      const json = $exportJsonView.value.trim() || await loadBackupJson();
      if (json === "Loading…") {
        setBackupStatus("JSON still loading — try again in a moment", true);
        return;
      }
      await navigator.clipboard.writeText(json);
      const count = (JSON.parse(json) as { wallets: unknown[] }).wallets.length;
      setBackupStatus(
        count === 0
          ? "Copied empty backup JSON."
          : `Copied JSON for ${count} wallet${count === 1 ? "" : "s"}.`,
      );
      flashSaved();
    } catch (e) {
      setBackupStatus(`copy failed: ${(e as Error).message}`, true);
    } finally {
      $exportCopy.disabled = false;
    }
  });

  $exportQrToggle.addEventListener("click", async () => {
    if (isExportQrVisible()) {
      stopExportQr();
      return;
    }
    $exportQrToggle.disabled = true;
    setBackupStatus("");
    $exportQrPanel.hidden = true;
    try {
      const { lines, walletCount } = await buildWalletBackupPw1Lines({
        scope: getExportScope(),
      });
      if (lines.length === 0) {
        setBackupStatus("Nothing to show — no paired wallets yet.", true);
        return;
      }
      exportQrPlayback = await startPw1QrPlayback($exportQrCanvas, lines, {
        onFrame: (idx, total) => {
          $exportQrProgress.textContent = `Frame ${idx} / ${total}`;
        },
      });
      exportQrUnwire = wirePw1QrControls(exportQrPlayback, {
        autoToggle: $exportQrPause,
        prev: $exportQrPrev,
        next: $exportQrNext,
        hint: $exportQrHint,
        autoHint: "Point the other phone at this animated QR.",
      });
      $exportQrPanel.hidden = false;
      $exportQrToggle.textContent = "Hide transfer QR";
      setBackupStatus(
        `Showing transfer QR (${lines.length} frame${lines.length === 1 ? "" : "s"}, ${walletCount} wallet${walletCount === 1 ? "" : "s"}).`,
      );
    } catch (e) {
      stopExportQr();
      setBackupStatus(`QR export failed: ${(e as Error).message}`, true);
    } finally {
      $exportQrToggle.disabled = false;
    }
  });

  $importFile.addEventListener("change", () => {
    const file = $importFile.files?.[0];
    $importFile.value = "";
    if (!file) return;
    void (async () => {
      try {
        const raw = await file.text();
        $importPaste.value = raw;
        await runImportRaw(raw);
      } catch (e) {
        setBackupStatus(`import failed: ${(e as Error).message}`, true);
      }
    })();
  });

  $importPasteBtn.addEventListener("click", () => {
    const raw = $importPaste.value.trim();
    if (!raw) {
      setBackupStatus("paste a JSON backup first", true);
      return;
    }
    void runImportRaw(raw);
  });

  $importPasteClear.addEventListener("click", () => {
    $importPaste.value = "";
    $importPaste.focus();
    setBackupStatus("");
  });

  $importQrToggle.addEventListener("click", () => {
    if (isImportQrActive()) {
      stopImportQrScan();
      return;
    }
    $importQrToggle.textContent = "Stop scanning";
    $importQrPanel.hidden = false;
    importQrScan = mountCameraScanner($importQrHost, {
      workflow: "settings-backup",
      variant: "compact",
      autoStart: true,
      labels: {
        scanning: "Scanning for transfer QR…",
        cancel: "Cancel",
      },
      onAccept: (validation) => {
        if (validation.result.workflow === "settings-backup") {
          stopImportQrScan();
          void runImportBytes(validation.result.bytes);
        }
      },
      onStopped: () => stopImportQrScan(),
    });
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
    stopExportQr();
    stopImportQrScan();
  };
}
