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
  type ImportWalletMode,
  serializeWalletBackup,
  walletBackupBytesToJson,
} from "../lib/wallet-backup.js";
import { startPw1Scan, type Pw1ScanHandle } from "../lib/camera-scan-pw1.js";
import {
  clearPw1QrCanvas,
  startPw1QrPlayback,
  type Pw1QrPlayback,
} from "../lib/pw1-qr-playback.js";
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
        <details class="backup-section" id="backupSection">
          <summary>Backup &amp; migration</summary>
          <p class="muted-line">
            Move paired wallets to another phone or browser (xpub and labels
            only — no seed phrases or private keys).
          </p>

          <details class="backup-fold" id="backupFold-export">
            <summary>Export</summary>
            <div class="backup-fold-body">
            <div class="backup-tabs backup-sub-tabs" role="tablist" aria-label="Export method">
              <button type="button" class="backup-tab active" role="tab"
                data-export-tab="qr" aria-selected="true" aria-controls="exportTab-qr">
                Transfer QR
              </button>
              <button type="button" class="backup-tab" role="tab"
                data-export-tab="json" aria-selected="false" aria-controls="exportTab-json">
                View / copy JSON
              </button>
            </div>
            <div id="exportTab-qr" class="backup-tab-panel" role="tabpanel">
              <div class="actions">
                <button id="exportQrToggle" class="primary" type="button">
                  Show transfer QR
                </button>
              </div>
              <div id="exportQrPanel" class="backup-qr-panel" hidden>
                <p class="muted-line">
                  Point the other phone at this animated QR.
                </p>
                <canvas id="exportQrCanvas" width="320" height="320"></canvas>
                <p id="exportQrProgress" class="muted-line">Frame 1 / 1</p>
                <div class="actions">
                  <button id="exportQrPause" type="button">Pause</button>
                </div>
              </div>
            </div>
            <div id="exportTab-json" class="backup-tab-panel" role="tabpanel" hidden>
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
              <button type="button" class="backup-tab active" role="tab"
                data-import-tab="qr" aria-selected="true" aria-controls="importTab-qr">
                Scan transfer QR
              </button>
              <button type="button" class="backup-tab" role="tab"
                data-import-tab="json" aria-selected="false" aria-controls="importTab-json">
                JSON file / paste
              </button>
            </div>
            <div id="importTab-qr" class="backup-tab-panel" role="tabpanel">
              <div class="actions">
                <button id="importQrToggle" class="primary" type="button">
                  Scan transfer QR
                </button>
              </div>
              <div id="importQrPanel" class="backup-scan-panel" hidden>
                <video id="importQrVideo" playsinline muted autoplay></video>
                <p id="importQrStatus" class="muted-line" aria-live="polite"></p>
                <p id="importQrProgress" class="muted-line"></p>
              </div>
            </div>
            <div id="importTab-json" class="backup-tab-panel" role="tabpanel" hidden>
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

          <p id="backupStatus" class="muted-line" aria-live="polite"></p>
        </details>
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
  const $exportDownload   = root.querySelector<HTMLButtonElement>("#exportDownload")!;
  const $exportCopy       = root.querySelector<HTMLButtonElement>("#exportCopy")!;
  const $exportQrToggle   = root.querySelector<HTMLButtonElement>("#exportQrToggle")!;
  const $exportQrPanel    = root.querySelector<HTMLElement>("#exportQrPanel")!;
  const $exportQrCanvas   = root.querySelector<HTMLCanvasElement>("#exportQrCanvas")!;
  const $exportQrProgress = root.querySelector<HTMLElement>("#exportQrProgress")!;
  const $exportQrPause    = root.querySelector<HTMLButtonElement>("#exportQrPause")!;
  const $exportJsonView   = root.querySelector<HTMLTextAreaElement>("#exportJsonView")!;
  const $importFile       = root.querySelector<HTMLInputElement>("#importWalletsFile")!;
  const $importPaste      = root.querySelector<HTMLTextAreaElement>("#importPasteJson")!;
  const $importPasteBtn   = root.querySelector<HTMLButtonElement>("#importPasteBtn")!;
  const $importPasteClear = root.querySelector<HTMLButtonElement>("#importPasteClear")!;
  const $importQrToggle   = root.querySelector<HTMLButtonElement>("#importQrToggle")!;
  const $importQrPanel    = root.querySelector<HTMLElement>("#importQrPanel")!;
  const $importQrVideo    = root.querySelector<HTMLVideoElement>("#importQrVideo")!;
  const $importQrStatus   = root.querySelector<HTMLElement>("#importQrStatus")!;
  const $importQrProgress = root.querySelector<HTMLElement>("#importQrProgress")!;
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
  let importQrScan: Pw1ScanHandle | null = null;
  let pendingReplaceRaw: string | null = null;

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

  function applyImportResult(result: Awaited<ReturnType<typeof importWalletBackup>>): void {
    const summary = formatImportWalletResult(result);
    setBackupStatus(
      summary,
      result.failed.length > 0 && result.imported === 0,
    );
    if (result.imported > 0) flashSaved();
  }

  async function loadBackupJson(): Promise<string> {
    const file = await buildWalletBackupFile();
    return serializeWalletBackup(file);
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
    if (tab !== "qr" && isExportQrVisible()) stopExportQr();
    root.querySelector<HTMLElement>("#exportTab-qr")!.hidden = tab !== "qr";
    root.querySelector<HTMLElement>("#exportTab-json")!.hidden = tab !== "json";
    root.querySelectorAll<HTMLButtonElement>("[data-export-tab]").forEach((btn) => {
      const active = btn.dataset.exportTab === tab;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
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
    if (tab !== "qr" && isImportQrActive()) stopImportQrScan();
    root.querySelector<HTMLElement>("#importTab-qr")!.hidden = tab !== "qr";
    root.querySelector<HTMLElement>("#importTab-json")!.hidden = tab !== "json";
    root.querySelectorAll<HTMLButtonElement>("[data-import-tab]").forEach((btn) => {
      const active = btn.dataset.importTab === tab;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
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

  function stopExportQr(): void {
    exportQrPlayback?.stop();
    exportQrPlayback = null;
    clearPw1QrCanvas($exportQrCanvas);
    $exportQrPanel.hidden = true;
    $exportQrPause.textContent = "Pause";
    $exportQrToggle.textContent = "Show transfer QR";
  }

  function stopImportQrScan(): void {
    importQrScan?.stop();
    importQrScan = null;
    $importQrVideo.srcObject = null;
    $importQrPanel.hidden = true;
    $importQrProgress.textContent = "";
    $importQrStatus.textContent = "";
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
      const { lines, walletCount } = await buildWalletBackupPw1Lines();
      if (lines.length === 0) {
        setBackupStatus("Nothing to show — no paired wallets yet.", true);
        return;
      }
      exportQrPlayback = await startPw1QrPlayback($exportQrCanvas, lines, {
        onFrame: (idx, total) => {
          $exportQrProgress.textContent = `Frame ${idx} / ${total}`;
        },
      });
      $exportQrPanel.hidden = false;
      $exportQrPause.textContent = "Pause";
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

  $exportQrPause.addEventListener("click", () => {
    if (!exportQrPlayback) return;
    if (exportQrPlayback.isRunning()) {
      exportQrPlayback.pause();
      $exportQrPause.textContent = "Resume";
    } else {
      exportQrPlayback.resume();
      $exportQrPause.textContent = "Pause";
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
    $importQrToggle.disabled = true;
    $importQrToggle.textContent = "Stop scanning";
    $importQrPanel.hidden = true;
    void (async () => {
      importQrScan = await startPw1Scan(
        $importQrVideo,
        (received, total) => {
          $importQrProgress.textContent = total
            ? `Frame ${received} / ${total}`
            : received > 0
              ? `${received} frame${received > 1 ? "s" : ""} received…`
              : "";
        },
        (bytes) => {
          stopImportQrScan();
          void runImportBytes(bytes);
        },
        (err) => {
          stopImportQrScan();
          setBackupStatus(err, true);
        },
      );
      $importQrPanel.hidden = false;
      $importQrStatus.textContent = "Scanning for transfer QR…";
      $importQrToggle.disabled = false;
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
    stopExportQr();
    stopImportQrScan();
  };
}
