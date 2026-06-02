/**
 * Wallet detail page (`#/wallets/<id>`).
 *
 * Tabs: Balance · Send · Receive · History · Share
 *
 * Balance    – confirmed hero, pending sub-line, sats/fiat toggle, UTXO list.
 * Send       – 5-step flow: recipient → amount → fee tier → review → QR.
 * Receive    – current address QR + copy, prev/next, on-device verify badge.
 * History    – transaction list via Bitails, newest first.
 * Share      – animated xpub QR for pairing another companion.
 */
import QRCode from "qrcode";

import {
  CHANGE_BRANCH,
  RECEIVE_BRANCH,
  deriveAddress,
  deriveAddressBatch,
} from "../lib/derive.js";
import { DOCS_BASE_URL, PRICE_CACHE_TTL_MS } from "../lib/config.js";
import {
  KIND_XPUB,
  KIND_SIGNED,
  type SignedTxT,
  bytesToHex,
  encodeEnvelope,
  hexToBytes,
  decodeEnvelope,
} from "../lib/envelope.js";
import { CoinSelectError, selectUtxosGreedy } from "../lib/coin-select.js";
import { encodeMultipartLines } from "../pw1.js";
import { Transaction } from "@bsv/sdk";
import { ProofFetchError, fetchInputProof } from "../lib/proof-fetcher.js";
import { renderHeader } from "./nav.js";
import {
  ProposalBuilderError,
  buildUnsignedProposal,
} from "../lib/proposal.js";
import { splitConfirmedPending } from "../lib/balance-split.js";
import { scanWalletUtxos, scanNextReceiveIndex } from "../lib/utxo.js";
import { WocClient, WocError, effectiveWocBase } from "../lib/woc.js";
import {
  BitailsClient,
  effectiveBitailsBase,
} from "../lib/bitails.js";
import {
  type WalletRecord,
  getWallet,
  removeWallet,
  updateLabel,
  setLastScan,
  setLastHistory,
  setNextReceiveIndex,
  withDefaults,
} from "../lib/wallets.js";
import { fetchWalletHistory, formatTxTimestamp } from "../lib/history.js";
import {
  DEFAULT_FEE_RATE_SATSKB,
  type FeeRecommendation,
  fetchFeeRecommendation,
  formatFeeRate,
} from "../lib/fee.js";
import type { NetworkT } from "../lib/envelope.js";
import {
  getDefaultFeeTier,
  getDefaultCustomFeeRate,
  getFiatCurrency,
} from "./settings-page.js";
import {
  type CameraScanHandle,
  startCameraScan,
} from "../lib/camera-scan.js";
import {
  type Pw1ScanHandle,
  startPw1Scan,
} from "../lib/camera-scan-pw1.js";

const RECENT_WINDOW = 8;
const SATS_PER_BSV = 100_000_000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatSats(n: number): string {
  return `${n.toLocaleString("en-US")} sats`;
}

function formatBsv(n: number): string {
  return `${(n / SATS_PER_BSV).toFixed(8)} BSV`;
}

function relativeTimeFrom(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return iso;
  const ms = Date.now() - t;
  if (ms < 0) return new Date(iso).toLocaleString();
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

function shortTxid(txid: string): string {
  if (txid.length <= 16) return txid;
  return `${txid.slice(0, 8)}…${txid.slice(-8)}`;
}

function wrapHex(hex: string, width: number): string {
  if (width <= 0) return hex;
  const lines: string[] = [];
  for (let i = 0; i < hex.length; i += width) {
    lines.push(hex.slice(i, i + width));
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Send flow step type
// ---------------------------------------------------------------------------

type SendStep =
  | { step: "form" }
  | { step: "fee"; recipient: string; sats: number }
  | { step: "review"; recipient: string; sats: number; feeRate: number; feeSats: number; changeSats: number }
  | { step: "qr" };

// ---------------------------------------------------------------------------
// Main mount function
// ---------------------------------------------------------------------------

const VALID_TABS = new Set(["balance", "send", "receive", "history", "share"]);

export function mountWalletDetailPage(
  root: HTMLElement,
  walletId: string,
  initialTab?: string,
): () => void {
  let cancelled = false;
  let wallet:
    | (WalletRecord & { nextReceiveIndex: number; network: NetworkT })
    | null = null;
  let scanRunning = false;
  let historyRunning = false;
  let receiveIndexScanRunning = false;
  let woc: WocClient | null = null;
  let bitails: BitailsClient | null = null;
  let sendBusy = false;
  let sendStep: SendStep = { step: "form" };
  let feeRec: FeeRecommendation | null = null;
  let addrScanHandle: CameraScanHandle | null = null;
  let pw1ScanHandle: Pw1ScanHandle | null = null;
  let selectedFeeRate = DEFAULT_FEE_RATE_SATSKB;

  let proposalFrames: string[] | null = null;
  let proposalFrameIdx = 0;
  let proposalLastFrameAt = 0;
  let proposalRaf: number | null = null;

  let exportFrames: string[] | null = null;
  let exportFrameIdx = 0;
  let exportLastFrameAt = 0;
  let exportRaf: number | null = null;

  // Price cache for fiat/BSV display
  let bsvUsdPrice: number | null = null;
  let priceFetchedAt = 0;
  type DisplayUnit = "sats" | "bsv" | "fiat";
  let displayUnit: DisplayUnit = "sats";

  // Active tab
  type Tab = "balance" | "send" | "receive" | "history" | "share";
  let activeTab: Tab =
    initialTab && VALID_TABS.has(initialTab) ? (initialTab as Tab) : "balance";

  root.innerHTML = `
    <main class="page">
      ${renderHeader("Wallet detail", "wallets")}
      <section id="loadingCard" class="card">
        <p class="muted-line">Loading wallet…</p>
      </section>
    </main>
  `;

  void load();

  async function load(): Promise<void> {
    let rec: WalletRecord | null;
    try {
      rec = await getWallet(walletId);
    } catch (e) {
      renderError(`store error: ${(e as Error).message}`);
      return;
    }
    if (cancelled) return;
    if (!rec) {
      renderError(`No wallet with id <code>${escapeHtml(walletId)}</code>.`);
      return;
    }
    wallet = withDefaults(rec);
    const storedUnit = localStorage.getItem("piwallet.listUnit") as DisplayUnit | null;
    displayUnit = storedUnit ?? rec.displayUnit ?? "sats";
    renderShell();
    void renderReceive();
    void onRefreshBalance();
    if (activeTab === "receive") void refreshReceiveIndex();
  }

  function renderError(html: string): void {
    if (cancelled) return;
    root.querySelector("#loadingCard")!.innerHTML = `
      <p class="error">${html}</p>
      <p><a href="#/wallets">← Back to wallets</a></p>
    `;
  }

  // ---------------------------------------------------------------------------
  // Shell
  // ---------------------------------------------------------------------------

  function renderShell(): void {
    if (!wallet) return;
    const netBadge =
      wallet.network === "test"
        ? ' <span class="testnet-badge" title="This wallet is on BSV testnet (TBSV).">TESTNET</span>'
        : "";

    root.innerHTML = `
      <main class="page">
        ${renderHeader(escapeHtml(wallet.label), "wallets", netBadge)}

        <section class="card wallet-meta-card">
          <p class="muted-line">
            fingerprint <code>${wallet.fingerprint}</code> · ${escapeHtml(wallet.path)} ·
            ${wallet.network === "test" ? "BSV testnet" : "BSV mainnet"} ·
            paired ${new Date(wallet.addedAt).toLocaleString()}
          </p>
          <p><a href="#/wallets">← Back to wallets</a></p>
        </section>

        <nav class="tab-nav" role="tablist">
          <button role="tab" data-tab="balance" class="${activeTab === "balance" ? "active" : ""}">Balance</button>
          <button role="tab" data-tab="send" class="${activeTab === "send" ? "active" : ""}">Send</button>
          <button role="tab" data-tab="receive" class="${activeTab === "receive" ? "active" : ""}">Receive</button>
          <button role="tab" data-tab="history" class="${activeTab === "history" ? "active" : ""}">History</button>
          <button role="tab" data-tab="share" class="${activeTab === "share" ? "active" : ""}">Advanced</button>
          <select id="unitSelect" class="tab-unit-select">
            <option value="sats"${displayUnit === "sats" ? " selected" : ""}>sats</option>
            <option value="bsv"${displayUnit === "bsv" ? " selected" : ""}>BSV</option>
            <option value="fiat"${displayUnit === "fiat" ? " selected" : ""}>${getFiatCurrency()}</option>
          </select>
        </nav>

        <!-- Balance tab -->
        <section id="tab-balance" class="card tab-panel${activeTab === "balance" ? " active" : ""}" role="tabpanel">
          <div class="balance-hero-row">
            <div class="balance-hero">
              <button id="balanceToggle" class="balance-hero-value" type="button"
                title="Tap to toggle sats / USD">
                <span id="balanceHero">—</span>
              </button>
              <div id="balancePending" class="balance-pending" hidden></div>
              <div id="balanceBsv" class="muted-line balance-bsv"></div>
            </div>
            <div class="balance-actions">
              <button id="refreshBalance" class="primary" type="button">Refresh</button>
            </div>
          </div>
          <p class="muted-line" id="balanceMeta"></p>
          <p class="muted-line balance-status" id="balanceStatus"></p>
          <details id="utxoDetails" hidden>
            <summary>UTXOs (<span id="utxoCount">0</span>)</summary>
            <ul id="utxoList" class="utxo-list"></ul>
          </details>
        </section>

        <!-- Send tab -->
        <section id="tab-send" class="card tab-panel${activeTab === "send" ? " active" : ""}" role="tabpanel">
          <p class="send-balance-line muted-line">
            Balance: <span id="sendBalanceHero">—</span>
          </p>
          <div id="sendStep-form">
            <h2>Send</h2>
            <label class="field">
              <span>Recipient address</span>
              <div class="address-input-row">
                <input id="sendAddress" type="text" autocomplete="off"
                  placeholder="${wallet.network === "test" ? "m… or n… (testnet)" : "1… (mainnet)"}" />
                <button id="scanAddress" type="button" class="icon-btn" title="Scan address QR">
                  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"
                    fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
                    <rect x="3" y="14" width="7" height="7"/>
                    <path d="M14 14h3v3m0 4h4v-4m-4 0v-3h-3"/>
                  </svg>
                </button>
              </div>
            </label>
            <div id="addrScanWidget" hidden>
              <video id="addrScanVideo" class="addr-scan-video" playsinline muted autoplay></video>
              <p class="muted-line" id="addrScanStatus">Scanning for address QR…</p>
              <div class="actions">
                <button id="addrScanCancel" type="button">Cancel</button>
              </div>
            </div>
            <label class="field">
              <span>Amount</span>
              <div class="amount-row">
                <input id="sendAmount" type="number" min="0" step="any"
                  placeholder="0" />
                <select id="sendUnit" class="send-unit-select">
                  <option value="sats">sats</option>
                  <option value="bsv">BSV</option>
                  <option value="usd">USD</option>
                </select>
                <button id="sendMax" type="button" class="send-max-btn">Max</button>
              </div>
            </label>
            <p class="muted-line" id="sendFormStatus"></p>
            <div class="actions">
              <button id="sendNext" type="button" class="primary">Next →</button>
            </div>
          </div>

          <div id="sendStep-fee" hidden>
            <h2>Select fee</h2>
            <p class="muted-line" id="feeLoading">Loading fee rates…</p>
            <div id="feeTiers" class="fee-tiers" hidden>
              ${((): string => {
                const defTier = getDefaultFeeTier();
                const defCustom = getDefaultCustomFeeRate();
                const chk = (v: string) => v === defTier ? " checked" : "";
                const sel = (v: string) => v === defTier ? " selected" : "";
                return `
              <label class="fee-tier${sel("economy")}">
                <input type="radio" name="feeTier" value="economy"${chk("economy")} />
                <span class="fee-tier-label">Economy</span>
                <span class="fee-tier-rate" id="feeEconomy">—</span>
                <span class="fee-tier-desc muted-line">slower, cheapest</span>
              </label>
              <label class="fee-tier${sel("standard")}">
                <input type="radio" name="feeTier" value="standard"${chk("standard")} />
                <span class="fee-tier-label">Standard</span>
                <span class="fee-tier-rate" id="feeStandard">—</span>
                <span class="fee-tier-desc muted-line">recommended</span>
              </label>
              <label class="fee-tier${sel("priority")}">
                <input type="radio" name="feeTier" value="priority"${chk("priority")} />
                <span class="fee-tier-label">Priority</span>
                <span class="fee-tier-rate" id="feePriority">—</span>
                <span class="fee-tier-desc muted-line">fastest confirmation</span>
              </label>
              <label class="fee-tier fee-tier-custom${sel("custom")}">
                <input type="radio" name="feeTier" value="custom"${chk("custom")} />
                <span class="fee-tier-label">Custom</span>
                <input id="feeCustom" type="number" min="1" step="1"
                  value="${defCustom}"
                  placeholder="${DEFAULT_FEE_RATE_SATSKB}"
                  class="fee-custom-input" />
                <span class="fee-tier-desc muted-line">sat/kB</span>
                <span class="fee-tier-rate" id="feeCustomEst" style="margin-left:auto">—</span>
              </label>`;
              })()}
            </div>
            <div class="actions">
              <button id="feeBack" type="button">← Back</button>
              <button id="feeNext" type="button" class="primary">Review →</button>
            </div>
          </div>

          <div id="sendStep-review" hidden>
            <h2>Review</h2>
            <table class="review-table">
              <tr><td class="review-label">To</td><td id="reviewRecipient" class="review-value mono"></td></tr>
              <tr><td class="review-label">Amount</td><td id="reviewAmount" class="review-value"></td></tr>
              <tr><td class="review-label">Fee</td><td id="reviewFee" class="review-value"></td></tr>
              <tr><td class="review-label">Total out</td><td id="reviewTotal" class="review-value"></td></tr>
              <tr><td class="review-label">Change</td><td id="reviewChange" class="review-value"></td></tr>
              <tr><td class="review-label">Fee rate</td><td id="reviewFeeRate" class="review-value"></td></tr>
            </table>
            <p class="muted-line" id="reviewStatus"></p>
            <div class="actions">
              <button id="reviewBack" type="button">← Back</button>
              <button id="reviewConfirm" type="button" class="primary">Build QR →</button>
            </div>
          </div>

          <div id="sendStep-qr" hidden>
            <h2>Step 1 — show proposal to Pi</h2>
            <p class="muted-line">Point the Pi camera at this animated QR.</p>
            <canvas id="proposalQr" width="320" height="320"></canvas>
            <p class="muted-line">
              Frame <span id="proposalFrameIdx">0</span> /
              <span id="proposalFrameCount">0</span> ·
              <span id="proposalByteCount">0</span> bytes
            </p>
            <div class="actions">
              <button id="proposalToggle" type="button" class="primary">Pause</button>
              <button id="proposalDone" type="button">New send</button>
            </div>

            <hr class="section-divider" />

            <h2>Step 2 — scan Pi's signed response</h2>
            <p class="muted-line">
              After the Pi signs, point this camera at the Pi's response QR.
            </p>
            <div id="pw1ScanWidget" hidden>
              <video id="pw1ScanVideo" class="addr-scan-video" playsinline muted autoplay></video>
              <p class="muted-line" id="pw1ScanStatus">Scanning for signed TX…</p>
              <p class="muted-line" id="pw1ScanProgress"></p>
              <div class="actions">
                <button id="pw1ScanCancel" type="button">Cancel</button>
              </div>
            </div>
            <div id="pw1ScanActions" class="actions">
              <button id="pw1ScanStart" type="button" class="primary">Scan Pi's response</button>
            </div>

            <div id="broadcastWidget" hidden>
              <p id="broadcastInfo" class="muted-line"></p>
              <div class="actions">
                <button id="broadcastBtn" type="button" class="primary">Broadcast</button>
                <button id="proposalDone2" type="button">New send</button>
              </div>
              <p id="broadcastStatus" class="muted-line"></p>
            </div>

            <details class="advanced proposal-hex-details">
              <summary>Sign over SSH instead (paste hex)</summary>
              <p class="muted-line">
                Copy the hex below, then on the Pi run:<br>
                <code>piwallet sign --hex &lt;paste&gt; --wallet-id &lt;id&gt;</code><br>
                Then paste the signed hex on the
                <a href="#/scan/tx">Submit signed TX</a> page.
              </p>
              <textarea id="proposalHex" class="hex-blob" rows="6"
                readonly spellcheck="false" autocorrect="off"></textarea>
              <div class="actions">
                <button id="copyProposalHex" type="button" class="primary">Copy hex</button>
                <a href="#/scan/tx" class="primary-link">Submit signed TX →</a>
              </div>
              <p class="muted-line" id="proposalHexStatus"></p>
            </details>
          </div>
        </section>

        <!-- Receive tab -->
        <section id="tab-receive" class="card tab-panel${activeTab === "receive" ? " active" : ""}" role="tabpanel">
          <h2>Receive</h2>
          <p class="muted-line" id="receivePath"></p>
          <div class="receive-row">
            <canvas id="receiveQr" width="240" height="240"></canvas>
            <div class="receive-detail">
              <code id="receiveAddress" class="big-address"></code>
              <div class="actions">
                <button id="copyAddress" type="button">Copy address</button>
                <button id="prevIdx" type="button">← Previous</button>
                <button id="nextIdx" class="primary" type="button">Next address</button>
              </div>
              <p class="muted-line" id="receiveStatus"></p>
            </div>
          </div>
          <p class="verify-tip muted-line" id="verifyTip"></p>
          <section class="receive-list-section">
            <h3>Recent receive addresses</h3>
            <p class="muted-line">
              A window of 8 addresses around the current pointer (<span id="receiveWindowDesc">m/0/0</span>).
            </p>
            <ul id="receiveList" class="addr-list"></ul>
          </section>
        </section>

        <!-- History tab -->
        <section id="tab-history" class="card tab-panel${activeTab === "history" ? " active" : ""}" role="tabpanel">
          <div class="history-header">
            <h2>Transaction history</h2>
            <button id="refreshHistory" class="primary" type="button">Refresh</button>
          </div>
          <p class="muted-line" id="historyStatus"></p>
          <div id="historyEmpty" class="empty-state" hidden>
            <p>No transaction history yet.</p>
            <p class="muted-line">Click Refresh to fetch history from Bitails.</p>
          </div>
          <ul id="historyList" class="history-list"></ul>
        </section>

        <!-- Share tab -->
        <section id="tab-share" class="card tab-panel${activeTab === "share" ? " active" : ""}" role="tabpanel">
          <h2>Export to another companion</h2>
          <p class="muted-line">
            Show an animated QR so another companion can pair with this
            wallet. Only the public key (xpub) is shared — the spending
            key never leaves the Pi.
          </p>
          <div class="actions">
            <button id="exportShow" class="primary" type="button">Show export QR</button>
          </div>
          <div id="exportResult" hidden>
            <canvas id="exportQr" width="320" height="320"></canvas>
            <p class="muted-line">
              Frame <span id="exportFrameIdx">0</span> /
              <span id="exportFrameCount">0</span>
              — scan from <a href="#/scan">+ Add wallet</a> on another companion
            </p>
            <div class="actions">
              <button id="exportToggle" type="button" class="primary">Pause</button>
              <button id="exportHide" type="button">Hide</button>
            </div>
          </div>

          <h2 style="margin-top:1.5rem">Account xpub</h2>
          <p class="muted-line">
            The account-level extended public key. Safe to share — it
            cannot spend funds, only derive addresses.
          </p>
          <div class="actions">
            <button id="copyXpub" type="button">Copy xpub</button>
          </div>
          <p id="copyXpubStatus" class="muted-line"></p>

          <hr class="section-divider" />

          <h2>Rename wallet</h2>
          <p class="muted-line">Change the display label for this wallet.</p>
          <label class="field">
            <span>New label</span>
            <input id="renameInput" type="text" maxlength="64"
              autocorrect="off" spellcheck="false"
              value="${escapeHtml(wallet.label)}" />
          </label>
          <div class="actions">
            <button id="renameSaveBtn" type="button" class="primary">Save label</button>
          </div>
          <p id="renameStatus" class="muted-line"></p>

          <hr class="section-divider" />

          <h2>Remove wallet</h2>
          <p class="muted-line">
            Removes this watch-only wallet from the companion. The Pi device
            and your funds are completely unaffected — you can re-pair at any
            time.
          </p>
          <div id="removeWalletConfirm" hidden>
            <p class="remove-confirm-msg warning-text">
              Are you sure? This will remove
              <strong>${wallet.label}</strong> from the companion.
            </p>
            <div class="actions">
              <button id="removeWalletConfirmYes" type="button" class="danger">Remove wallet</button>
              <button id="removeWalletConfirmNo" type="button">Cancel</button>
            </div>
          </div>
          <div id="removeWalletActions" class="actions">
            <button id="removeWalletBtn" type="button" class="danger-outline">Remove wallet…</button>
          </div>
          <p id="removeWalletStatus" class="muted-line"></p>
        </section>
      </main>
    `;

    bindEvents();
    renderBalance();
    renderHistory();
  }

  // ---------------------------------------------------------------------------
  // Tab switching
  // ---------------------------------------------------------------------------

  function bindEvents(): void {
    root.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab as Tab;
        switchTab(tab);
      });
    });

    // Balance tab
    const $refresh = root.querySelector<HTMLButtonElement>("#refreshBalance");
    $refresh?.addEventListener("click", () => void onRefreshBalance());

    const $toggle = root.querySelector<HTMLButtonElement>("#balanceToggle");
    $toggle?.addEventListener("click", () => void onToggleDisplayUnit());

    root.querySelector<HTMLSelectElement>("#unitSelect")
      ?.addEventListener("change", (e) => void onUnitSelectChange((e.target as HTMLSelectElement).value as DisplayUnit));

    // Send tab
    root.querySelector<HTMLButtonElement>("#scanAddress")
      ?.addEventListener("click", () => void onStartAddrScan());
    root.querySelector<HTMLButtonElement>("#addrScanCancel")
      ?.addEventListener("click", stopAddrScan);
    root.querySelector<HTMLButtonElement>("#sendNext")
      ?.addEventListener("click", () => void onSendNext());
    root.querySelector<HTMLButtonElement>("#sendMax")
      ?.addEventListener("click", onSendMax);
    root.querySelector<HTMLSelectElement>("#sendUnit")
      ?.addEventListener("change", (e) => {
        if ((e.target as HTMLSelectElement).value === "usd") void fetchBsvPrice();
      });
    root.querySelector<HTMLButtonElement>("#feeBack")
      ?.addEventListener("click", () => showSendStep("form"));
    root.querySelector<HTMLButtonElement>("#feeNext")
      ?.addEventListener("click", () => void onFeeNext());
    root.querySelector<HTMLButtonElement>("#reviewBack")
      ?.addEventListener("click", () => showSendStep("fee"));
    root.querySelector<HTMLButtonElement>("#reviewConfirm")
      ?.addEventListener("click", () => void onBuildProposal());
    root.querySelector<HTMLButtonElement>("#proposalToggle")
      ?.addEventListener("click", toggleAnimation);
    root.querySelector<HTMLButtonElement>("#proposalDone")
      ?.addEventListener("click", resetSendCard);
    root.querySelector<HTMLButtonElement>("#proposalDone2")
      ?.addEventListener("click", resetSendCard);
    root.querySelector<HTMLButtonElement>("#copyProposalHex")
      ?.addEventListener("click", () => void onCopyProposalHex());
    root.querySelector<HTMLButtonElement>("#pw1ScanStart")
      ?.addEventListener("click", () => void onStartPw1Scan());
    root.querySelector<HTMLButtonElement>("#pw1ScanCancel")
      ?.addEventListener("click", stopPw1Scan);
    root.querySelector<HTMLButtonElement>("#broadcastBtn")
      ?.addEventListener("click", () => void onBroadcast());

    // Fee tier radio — highlight selected
    root.querySelectorAll<HTMLInputElement>('input[name="feeTier"]').forEach((r) => {
      r.addEventListener("change", () => highlightSelectedTier());
    });

    // Custom fee input — update estimated sats live
    root.querySelector<HTMLInputElement>("#feeCustom")
      ?.addEventListener("input", () => {
        const $customInput = root.querySelector<HTMLInputElement>("#feeCustom");
        const $est = root.querySelector<HTMLElement>("#feeCustomEst");
        if (!$customInput || !$est || sendStep.step !== "fee" || !wallet?.lastScan) return;
        const rate = parseInt($customInput.value, 10);
        if (!Number.isInteger(rate) || rate <= 0) { $est.textContent = "—"; return; }
        try {
          const fee = selectUtxosGreedy(wallet.lastScan.utxos, sendStep.sats, rate).feeSats;
          $est.textContent = `~${fee.toLocaleString("en-US")} sats`;
        } catch {
          const bytes = wallet.lastScan.utxos.length * 148 + 2 * 34 + 10;
          $est.textContent = `~${Math.ceil(bytes * rate / 1000).toLocaleString("en-US")} sats`;
        }
      });

    // Receive tab
    root.querySelector<HTMLButtonElement>("#copyAddress")
      ?.addEventListener("click", () => void onCopy());
    root.querySelector<HTMLButtonElement>("#prevIdx")
      ?.addEventListener("click", () => void shiftIndex(-1));
    root.querySelector<HTMLButtonElement>("#nextIdx")
      ?.addEventListener("click", () => void shiftIndex(1));

    // History tab
    root.querySelector<HTMLButtonElement>("#refreshHistory")
      ?.addEventListener("click", () => void onRefreshHistory());

    // Advanced tab
    root.querySelector<HTMLButtonElement>("#exportShow")
      ?.addEventListener("click", () => void onShowExport());
    root.querySelector<HTMLButtonElement>("#exportToggle")
      ?.addEventListener("click", toggleExportAnimation);
    root.querySelector<HTMLButtonElement>("#exportHide")
      ?.addEventListener("click", hideExport);
    root.querySelector<HTMLButtonElement>("#copyXpub")
      ?.addEventListener("click", () => void onCopyXpub());
    root.querySelector<HTMLButtonElement>("#renameSaveBtn")
      ?.addEventListener("click", () => void onRenameSave());
    root.querySelector<HTMLButtonElement>("#removeWalletBtn")
      ?.addEventListener("click", onRemoveWalletOpen);
    root.querySelector<HTMLButtonElement>("#removeWalletConfirmNo")
      ?.addEventListener("click", onRemoveWalletCancel);
    root.querySelector<HTMLButtonElement>("#removeWalletConfirmYes")
      ?.addEventListener("click", () => void onRemoveWalletConfirm());
  }

  async function onCopyXpub(): Promise<void> {
    const $btn = root.querySelector<HTMLButtonElement>("#copyXpub");
    const $status = root.querySelector<HTMLElement>("#copyXpubStatus");
    if (!$btn || !$status || !wallet) return;
    try {
      await navigator.clipboard.writeText(wallet.xpub);
      const orig = $btn.textContent;
      $btn.textContent = "copied!";
      $status.textContent = "";
      setTimeout(() => { $btn.textContent = orig; }, 1200);
    } catch (e) {
      $status.textContent = `clipboard error: ${(e as Error).message}`;
    }
  }

  async function onRenameSave(): Promise<void> {
    if (!wallet) return;
    const $input = root.querySelector<HTMLInputElement>("#renameInput");
    const $status = root.querySelector<HTMLElement>("#renameStatus");
    if (!$input || !$status) return;
    const trimmed = $input.value.trim();
    if (!trimmed) {
      $status.textContent = "Label cannot be empty.";
      return;
    }
    if (trimmed === wallet.label) {
      $status.textContent = "No change.";
      return;
    }
    try {
      await updateLabel(wallet.id, trimmed);
      wallet = { ...wallet, label: trimmed };
      // Refresh the page header label
      const $headerLabel = root.querySelector<HTMLElement>(".page-header h1");
      if ($headerLabel) $headerLabel.firstChild!.textContent = escapeHtml(trimmed);
      $status.textContent = `Renamed to "${trimmed}".`;
      setTimeout(() => { if ($status) $status.textContent = ""; }, 2000);
    } catch (e) {
      $status.textContent = `rename failed: ${(e as Error).message}`;
    }
  }

  function onRemoveWalletOpen(): void {
    root.querySelector<HTMLElement>("#removeWalletActions")!.hidden = true;
    root.querySelector<HTMLElement>("#removeWalletConfirm")!.hidden = false;
  }

  function onRemoveWalletCancel(): void {
    root.querySelector<HTMLElement>("#removeWalletConfirm")!.hidden = true;
    root.querySelector<HTMLElement>("#removeWalletActions")!.hidden = false;
  }

  async function onRemoveWalletConfirm(): Promise<void> {
    if (!wallet) return;
    const $status = root.querySelector<HTMLElement>("#removeWalletStatus");
    try {
      await removeWallet(wallet.id);
      window.location.hash = "#/wallets";
    } catch (e) {
      if ($status) $status.textContent = `remove failed: ${(e as Error).message}`;
      onRemoveWalletCancel();
    }
  }

  function switchTab(tab: Tab): void {
    activeTab = tab;
    root.querySelectorAll<HTMLElement>(".tab-panel").forEach((p) => {
      p.classList.toggle("active", p.id === `tab-${tab}`);
    });
    root.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    // Lazy-load history when tab first opened
    if (tab === "history" && wallet?.lastHistory == null && !historyRunning) {
      void onRefreshHistory();
    }
    // Silently verify receive index is still unused when tab opens
    if (tab === "receive") {
      void refreshReceiveIndex();
    }
  }

  async function refreshReceiveIndex(): Promise<void> {
    if (!wallet || receiveIndexScanRunning) return;
    receiveIndexScanRunning = true;
    try {
      if (!woc) woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });
      const fresh = await scanNextReceiveIndex(
        wallet.xpub, woc, wallet.nextReceiveIndex, wallet.network,
      );
      if (cancelled) return;
      if (fresh !== wallet.nextReceiveIndex) {
        await setNextReceiveIndex(wallet.id, fresh);
        wallet.nextReceiveIndex = fresh;
        void renderReceive();
      }
    } catch {
      // silently ignore — stale index is better than a broken UI
    } finally {
      receiveIndexScanRunning = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Balance
  // ---------------------------------------------------------------------------

  async function onUnitSelectChange(unit: DisplayUnit): Promise<void> {
    if (!wallet) return;
    displayUnit = unit;
    localStorage.setItem("piwallet.listUnit", unit);
    if (unit === "fiat" && bsvUsdPrice === null) await fetchBsvPrice();
    renderBalance();
    // Keep the balance toggle button in sync
    const $toggle = root.querySelector<HTMLButtonElement>("#balanceToggle");
    if ($toggle) $toggle.title = `Showing ${unit}`;
  }

  async function onToggleDisplayUnit(): Promise<void> {
    // Cycle: sats → bsv → fiat → sats
    const cycle: DisplayUnit[] = ["sats", "bsv", "fiat"];
    const next = cycle[(cycle.indexOf(displayUnit) + 1) % cycle.length];
    const $select = root.querySelector<HTMLSelectElement>("#unitSelect");
    if ($select) $select.value = next;
    await onUnitSelectChange(next);
  }

  async function fetchBsvPrice(): Promise<void> {
    if (!wallet) return;
    const now = Date.now();
    if (bsvUsdPrice !== null && now - priceFetchedAt < PRICE_CACHE_TTL_MS) return;
    try {
      if (!woc) woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });
      const url = `${woc.baseUrl}/exchangerate`;
      const resp = await fetch(url, { headers: { Accept: "application/json" } });
      if (!resp.ok) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = (await resp.json()) as any;
      const rate = data?.rate ?? data?.price ?? data?.USD ?? null;
      if (typeof rate === "number" && rate > 0) {
        bsvUsdPrice = rate;
        priceFetchedAt = now;
      }
    } catch {
      // silently ignore — fiat toggle will show "—"
    }
  }

  function formatBalance(sats: number): string {
    if (displayUnit === "bsv") {
      return `${(sats / SATS_PER_BSV).toFixed(8)} BSV`;
    }
    if (displayUnit === "fiat") {
      if (bsvUsdPrice === null) return `— ${getFiatCurrency()}`;
      const val = (sats / SATS_PER_BSV) * bsvUsdPrice;
      return `${getFiatCurrency()} ${val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return formatSats(sats);
  }

  function renderBalance(): void {
    if (!wallet) return;
    const $hero = root.querySelector<HTMLElement>("#balanceHero");
    const $bsv = root.querySelector<HTMLElement>("#balanceBsv");
    const $meta = root.querySelector<HTMLElement>("#balanceMeta");
    const $pending = root.querySelector<HTMLElement>("#balancePending");
    const $details = root.querySelector<HTMLDetailsElement>("#utxoDetails");
    const $count = root.querySelector<HTMLElement>("#utxoCount");
    const $list = root.querySelector<HTMLUListElement>("#utxoList");
    if (!$hero || !$bsv || !$meta || !$pending || !$details || !$count || !$list)
      return;

    const $sendBal = root.querySelector<HTMLElement>("#sendBalanceHero");

    const scan = wallet.lastScan;
    if (!scan) {
      $hero.textContent = "—";
      $bsv.textContent = "";
      $meta.textContent = "Not scanned yet — click Refresh to query WhatsOnChain.";
      $pending.hidden = true;
      $details.hidden = true;
      if ($sendBal) $sendBal.textContent = "—";
      return;
    }

    if ($sendBal) $sendBal.textContent = formatBalance(scan.totalSats);
    $hero.textContent = formatBalance(scan.totalSats);
    $bsv.textContent =
      displayUnit === "sats" ? formatBsv(scan.totalSats) :
      displayUnit === "bsv"  ? formatSats(scan.totalSats) :
      formatSats(scan.totalSats);
    $meta.textContent =
      `${scan.utxos.length} UTXO${scan.utxos.length === 1 ? "" : "s"} · ` +
      `last refreshed ${relativeTimeFrom(scan.at)}`;

    const split = splitConfirmedPending(scan.utxos);
    if (split.hasPending) {
      $pending.hidden = false;
      $pending.textContent = split.allPending
        ? "unconfirmed"
        : `+${formatSats(split.pendingSats)} unconfirmed`;
    } else {
      $pending.hidden = true;
    }

    $details.hidden = scan.utxos.length === 0;
    $count.textContent = String(scan.utxos.length);

    $list.innerHTML = "";
    for (const u of scan.utxos) {
      const li = document.createElement("li");
      const isPending = u.height === 0;
      li.className = isPending ? "utxo-row pending" : "utxo-row";
      const branchLabel = u.derivation[0] === 0 ? "recv" : "change";
      li.innerHTML = `
        <div class="utxo-top">
          <code title="${escapeHtml(u.txid)}">${escapeHtml(shortTxid(u.txid))}:${u.vout}</code>
          <span class="utxo-sats">${formatSats(u.sats)}</span>
        </div>
        <div class="muted-line">
          ${branchLabel} m/${u.derivation[0]}/${u.derivation[1]} ·
          ${escapeHtml(u.address)} ·
          ${isPending ? '<span class="utxo-pending-tag">mempool</span>' : `block ${u.height}`}
        </div>
      `;
      $list.appendChild(li);
    }
  }

  async function onRefreshBalance(): Promise<void> {
    if (!wallet || scanRunning) return;
    scanRunning = true;
    const $refresh = root.querySelector<HTMLButtonElement>("#refreshBalance");
    const $status = root.querySelector<HTMLElement>("#balanceStatus");
    if ($refresh) {
      $refresh.disabled = true;
      $refresh.textContent = "Scanning…";
    }
    if ($status) {
      $status.classList.remove("error");
      $status.textContent = "Starting gap-limit scan…";
    }
    if (!woc) {
      woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });
    }

    try {
      const result = await scanWalletUtxos(wallet.xpub, woc, {
        network: wallet.network,
        onProgress: ({ branch, index, address, found }) => {
          if (cancelled || !$status) return;
          const branchLabel = branch === RECEIVE_BRANCH ? "recv" : "change";
          $status.textContent =
            `Probing ${branchLabel} m/${branch}/${index} ` +
            `(${address.slice(0, 6)}…${address.slice(-4)}) — ` +
            `${found} UTXO${found === 1 ? "" : "s"}`;
        },
      });
      if (cancelled) return;
      const snapshot = {
        at: new Date().toISOString(),
        totalSats: result.totalSats,
        utxos: result.utxos,
        lastReceiveUsed: result.lastReceiveUsed,
        lastChangeUsed: result.lastChangeUsed,
        addressesScanned: result.addressesScanned,
      };
      await setLastScan(wallet.id, snapshot);
      wallet.lastScan = snapshot;

      const autoNext = result.lastReceiveUsed + 1;
      const didAdvance = autoNext > wallet.nextReceiveIndex;
      if (didAdvance) {
        await setNextReceiveIndex(wallet.id, autoNext);
        wallet.nextReceiveIndex = autoNext;
      }

      renderBalance();
      void renderReceive();
      renderRecentList();
      if ($status) {
        $status.textContent =
          `Scan complete — ${result.utxos.length} UTXO(s), ` +
          `${result.addressesScanned} addresses probed.` +
          (didAdvance ? ` · receive index → ${wallet.nextReceiveIndex}` : "");
      }
    } catch (e) {
      if (cancelled) return;
      const msg = e instanceof WocError ? e.message : (e as Error).message;
      if ($status) {
        $status.classList.add("error");
        $status.textContent = `scan failed: ${msg}`;
      }
    } finally {
      scanRunning = false;
      if ($refresh) {
        $refresh.disabled = false;
        $refresh.textContent = "Refresh";
      }
    }
  }

  // ---------------------------------------------------------------------------
  // History
  // ---------------------------------------------------------------------------

  function renderHistory(): void {
    if (!wallet) return;
    const $list = root.querySelector<HTMLUListElement>("#historyList");
    const $empty = root.querySelector<HTMLElement>("#historyEmpty");
    const $status = root.querySelector<HTMLElement>("#historyStatus");
    if (!$list || !$empty) return;

    const snap = wallet.lastHistory;
    if (!snap) {
      $empty.hidden = false;
      $list.innerHTML = "";
      if ($status) $status.textContent = "";
      return;
    }
    $empty.hidden = snap.entries.length > 0;
    if ($status) {
      $status.textContent =
        `${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"} · ` +
        `last fetched ${relativeTimeFrom(snap.at)}`;
    }
    $list.innerHTML = "";
    for (const tx of snap.entries) {
      const li = document.createElement("li");
      const isReceive = tx.deltaSats >= 0;
      const isPending = tx.blockHeight === 0;
      li.className = `history-row ${isReceive ? "receive" : "send"}${isPending ? " pending" : ""}`;
      const network = wallet.network ?? "main";
      const explorerBase = network === "test"
        ? "https://test.whatsonchain.com/tx/"
        : "https://whatsonchain.com/tx/";
      li.innerHTML = `
        <div class="history-top">
          <span class="history-delta ${isReceive ? "positive" : "negative"}">
            ${isReceive ? "+" : ""}${formatSats(tx.deltaSats)}
          </span>
          <span class="history-time muted-line">${escapeHtml(formatTxTimestamp(tx.timestamp))}</span>
        </div>
        <div class="history-meta muted-line">
          <a href="${explorerBase}${escapeHtml(tx.txid)}" target="_blank"
             rel="noopener noreferrer">${escapeHtml(shortTxid(tx.txid))}</a>
          ${isPending
            ? '<span class="utxo-pending-tag">unconfirmed</span>'
            : `· block ${tx.blockHeight}`}
        </div>
      `;
      $list.appendChild(li);
    }
  }

  async function onRefreshHistory(): Promise<void> {
    if (!wallet || historyRunning) return;
    historyRunning = true;
    const $btn = root.querySelector<HTMLButtonElement>("#refreshHistory");
    const $status = root.querySelector<HTMLElement>("#historyStatus");
    if ($btn) { $btn.disabled = true; $btn.textContent = "Fetching…"; }
    if ($status) { $status.classList.remove("error"); $status.textContent = "Fetching history from Bitails…"; }

    if (!bitails) {
      bitails = new BitailsClient({ baseUrl: effectiveBitailsBase(wallet.network) });
    }

    try {
      const snap = await fetchWalletHistory(wallet.xpub, bitails, {
        network: wallet.network,
        lastReceiveUsed: wallet.lastScan?.lastReceiveUsed,
        lastChangeUsed: wallet.lastScan?.lastChangeUsed,
        onProgress: (done, total) => {
          if (cancelled || !$status) return;
          $status.textContent = `Fetching history (${done}/${total} addresses)…`;
        },
      });
      if (cancelled) return;
      await setLastHistory(wallet.id, snap);
      wallet.lastHistory = snap;
      renderHistory();
      if ($status) {
        $status.textContent =
          `${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"} · ` +
          `last fetched just now`;
      }
    } catch (e) {
      if (cancelled) return;
      if ($status) {
        $status.classList.add("error");
        $status.textContent = `history fetch failed: ${(e as Error).message}`;
      }
    } finally {
      historyRunning = false;
      if ($btn) { $btn.disabled = false; $btn.textContent = "Refresh"; }
    }
  }

  // ---------------------------------------------------------------------------
  // Send flow
  // ---------------------------------------------------------------------------

  function stopAddrScan(): void {
    addrScanHandle?.stop();
    addrScanHandle = null;
    const $widget = root.querySelector<HTMLElement>("#addrScanWidget");
    if ($widget) $widget.hidden = true;
  }

  async function onStartAddrScan(): Promise<void> {
    const $widget = root.querySelector<HTMLElement>("#addrScanWidget");
    const $video = root.querySelector<HTMLVideoElement>("#addrScanVideo");
    const $status = root.querySelector<HTMLElement>("#addrScanStatus");
    const $addr = root.querySelector<HTMLInputElement>("#sendAddress");
    if (!$widget || !$video || !$status || !$addr) return;

    stopAddrScan(); // release any previous handle
    $status.textContent = "Scanning for address QR…";
    $widget.hidden = false;

    addrScanHandle = await startCameraScan(
      $video,
      (raw) => {
        // Strip bitcoin: URI scheme if present (e.g. "bitcoin:1abc…?amount=…")
        const addr = raw.replace(/^bitcoin:/i, "").split("?")[0].trim();
        $addr.value = addr;
        stopAddrScan();
      },
      (err) => {
        if ($status) $status.textContent = err;
      },
    );
  }

  function showSendStep(step: "form" | "fee" | "review" | "qr"): void {
    const steps = ["form", "fee", "review", "qr"];
    for (const s of steps) {
      const el = root.querySelector<HTMLElement>(`#sendStep-${s}`);
      if (el) el.hidden = s !== step;
    }
  }

  function onSendMax(): void {
    if (!wallet?.lastScan) return;
    const $amount = root.querySelector<HTMLInputElement>("#sendAmount");
    const $unit = root.querySelector<HTMLSelectElement>("#sendUnit");
    if (!$amount || !$unit) return;
    const feeRate = selectedFeeRate;
    const totalIn = wallet.lastScan.utxos.reduce((a, u) => a + u.sats, 0);
    const estimatedFee = Math.ceil((wallet.lastScan.utxos.length * 148 + 2 * 34 + 10) * feeRate / 1000);
    const maxSats = Math.max(0, totalIn - estimatedFee);
    const unit = $unit.value as "sats" | "bsv" | "usd";
    if (unit === "sats") {
      $amount.value = String(maxSats);
    } else if (unit === "bsv") {
      $amount.value = (maxSats / SATS_PER_BSV).toFixed(8);
    } else {
      $amount.value = bsvUsdPrice !== null
        ? ((maxSats / SATS_PER_BSV) * bsvUsdPrice).toFixed(2)
        : String(maxSats / SATS_PER_BSV);
    }
  }

  async function onSendNext(): Promise<void> {
    if (!wallet) return;
    const $addr = root.querySelector<HTMLInputElement>("#sendAddress")!;
    const $amountInput = root.querySelector<HTMLInputElement>("#sendAmount")!;
    const $unitSelect = root.querySelector<HTMLSelectElement>("#sendUnit")!;
    const $status = root.querySelector<HTMLElement>("#sendFormStatus")!;
    $status.classList.remove("error");

    const recipient = $addr.value.trim();
    const amountRaw = $amountInput.value.trim();
    const amountNum = parseFloat(amountRaw);
    const unit = $unitSelect.value as "sats" | "bsv" | "usd";

    if (!recipient) {
      $status.classList.add("error");
      $status.textContent = "enter a recipient address";
      return;
    }
    if (amountRaw === "" || isNaN(amountNum) || amountNum <= 0) {
      $status.classList.add("error");
      $status.textContent = amountRaw === "" ? "enter an amount" : `invalid amount "${amountRaw}"`;
      $amountInput.focus();
      return;
    }

    let sats: number;
    if (unit === "sats") {
      sats = Math.round(amountNum);
    } else if (unit === "bsv") {
      sats = Math.round(amountNum * SATS_PER_BSV);
    } else {
      if (bsvUsdPrice === null || bsvUsdPrice === 0) {
        $status.classList.add("error");
        $status.textContent = "USD price unavailable — switch to sats or BSV";
        return;
      }
      sats = Math.round((amountNum / bsvUsdPrice) * SATS_PER_BSV);
    }

    if (!Number.isInteger(sats) || sats <= 0) {
      $status.classList.add("error");
      $status.textContent = `amount too small (rounds to ${sats} sats)`;
      $amountInput.focus();
      return;
    }
    if (!wallet.lastScan || wallet.lastScan.utxos.length === 0) {
      $status.classList.add("error");
      $status.textContent = "no UTXOs known — switch to the Balance tab and click Refresh first";
      return;
    }

    sendStep = { step: "fee", recipient, sats };
    showSendStep("fee");
    void loadFeeRates();
  }

  async function loadFeeRates(): Promise<void> {
    if (!wallet) return;
    const $loading = root.querySelector<HTMLElement>("#feeLoading");
    const $tiers = root.querySelector<HTMLElement>("#feeTiers");
    if (!woc) woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });

    try {
      feeRec = await fetchFeeRecommendation(woc);
    } catch {
      feeRec = null;
    }

    const economy = feeRec?.economy ?? DEFAULT_FEE_RATE_SATSKB;
    const standard = feeRec?.standard ?? DEFAULT_FEE_RATE_SATSKB;
    const priority = feeRec?.priority ?? DEFAULT_FEE_RATE_SATSKB * 5;

    const feeStep = sendStep.step === "fee" ? sendStep : null;
    const estSats = feeStep && wallet?.lastScan
      ? (rate: number) => {
          try {
            return selectUtxosGreedy(wallet!.lastScan!.utxos, feeStep.sats, rate).feeSats;
          } catch {
            const bytes = (wallet!.lastScan!.utxos.length) * 148 + 2 * 34 + 10;
            return Math.ceil(bytes * rate / 1000);
          }
        }
      : (_rate: number) => null;

    function fmtTierRate(rate: number): string {
      const fee = estSats(rate);
      return fee !== null
        ? `~${fee.toLocaleString("en-US")} sats  (${formatFeeRate(rate)})`
        : formatFeeRate(rate);
    }

    const $eco = root.querySelector<HTMLElement>("#feeEconomy");
    const $std = root.querySelector<HTMLElement>("#feeStandard");
    const $pri = root.querySelector<HTMLElement>("#feePriority");
    if ($eco) $eco.textContent = fmtTierRate(economy);
    if ($std) $std.textContent = fmtTierRate(standard);
    if ($pri) $pri.textContent = fmtTierRate(priority);

    selectedFeeRate = standard;
    if ($loading) $loading.hidden = true;
    if ($tiers) $tiers.hidden = false;
  }

  function highlightSelectedTier(): void {
    root.querySelectorAll<HTMLElement>(".fee-tier").forEach((el) => {
      const radio = el.querySelector<HTMLInputElement>("input[type=radio]");
      el.classList.toggle("selected", !!radio?.checked);
    });
  }

  async function onFeeNext(): Promise<void> {
    if (sendStep.step !== "fee") return;
    if (!wallet?.lastScan) return;

    const selected = root.querySelector<HTMLInputElement>('input[name="feeTier"]:checked')?.value;
    let rate: number;
    if (selected === "economy") rate = feeRec?.economy ?? DEFAULT_FEE_RATE_SATSKB;
    else if (selected === "standard") rate = feeRec?.standard ?? DEFAULT_FEE_RATE_SATSKB;
    else if (selected === "priority") rate = feeRec?.priority ?? DEFAULT_FEE_RATE_SATSKB * 5;
    else {
      // custom
      const $custom = root.querySelector<HTMLInputElement>("#feeCustom");
      rate = parseInt($custom?.value ?? "", 10);
      if (!Number.isInteger(rate) || rate <= 0) rate = getDefaultCustomFeeRate();
    }
    selectedFeeRate = rate;

    // Estimate fee and change for the review screen
    let feeSats = 0;
    let changeSats = 0;
    try {
      const sel = selectUtxosGreedy(wallet.lastScan.utxos, sendStep.sats, rate);
      feeSats = sel.feeSats;
      changeSats = sel.changeSats;
    } catch {
      // Use rough estimate if coin select fails (will re-run on confirm)
      const estimatedBytes = wallet.lastScan.utxos.length * 148 + 2 * 34 + 10;
      feeSats = Math.ceil(estimatedBytes * rate / 1000);
      changeSats = 0;
    }

    sendStep = { step: "review", recipient: sendStep.recipient, sats: sendStep.sats, feeRate: rate, feeSats, changeSats };
    showSendStep("review");
    renderReview();
  }

  function renderReview(): void {
    if (sendStep.step !== "review") return;
    const $recipient = root.querySelector<HTMLElement>("#reviewRecipient");
    const $amount = root.querySelector<HTMLElement>("#reviewAmount");
    const $fee = root.querySelector<HTMLElement>("#reviewFee");
    const $total = root.querySelector<HTMLElement>("#reviewTotal");
    const $change = root.querySelector<HTMLElement>("#reviewChange");
    const $rate = root.querySelector<HTMLElement>("#reviewFeeRate");
    if ($recipient) $recipient.textContent = sendStep.recipient;
    if ($amount) $amount.textContent = formatSats(sendStep.sats);
    if ($fee) $fee.textContent = formatSats(sendStep.feeSats);
    if ($total) $total.textContent = formatSats(sendStep.sats + sendStep.feeSats);
    if ($change) $change.textContent = sendStep.changeSats > 0
      ? `${formatSats(sendStep.changeSats)} (to your change address)`
      : "none (send max)";
    if ($rate) $rate.textContent = formatFeeRate(sendStep.feeRate);
  }

  async function onBuildProposal(): Promise<void> {
    if (!wallet || sendBusy || sendStep.step !== "review") return;
    const $status = root.querySelector<HTMLElement>("#reviewStatus")!;
    const $confirm = root.querySelector<HTMLButtonElement>("#reviewConfirm")!;
    $status.classList.remove("error");

    sendBusy = true;
    $confirm.disabled = true;
    $confirm.textContent = "Building…";
    $status.textContent = "Selecting UTXOs…";

    try {
      const selection = selectUtxosGreedy(
        wallet.lastScan!.utxos,
        sendStep.sats,
        sendStep.feeRate,
      );
      $status.textContent =
        `Selected ${selection.inputs.length} UTXO(s). Fetching SPV proofs…`;

      if (!woc) woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });
      const proofs = [];
      for (let i = 0; i < selection.inputs.length; i++) {
        const u = selection.inputs[i];
        $status.textContent =
          `Fetching proof ${i + 1}/${selection.inputs.length} for ${u.txid.slice(0, 8)}…`;
        const proof = await fetchInputProof(woc, u.txid);
        proofs.push({ utxo: u, proof });
      }

      const nextChangeIdx = (wallet.lastScan!.lastChangeUsed ?? -1) + 1;
      const changeDerived = deriveAddress(wallet.xpub, CHANGE_BRANCH, nextChangeIdx, wallet.network);
      const envelope = buildUnsignedProposal({
        walletFingerprintHex: wallet.fingerprint,
        inputs: proofs.map(({ utxo, proof }) => ({
          txid: utxo.txid,
          vout: utxo.vout,
          sats: utxo.sats,
          derivation: utxo.derivation,
          proof,
        })),
        recipientAddress: sendStep.recipient,
        recipientSats: sendStep.sats,
        changeAddress: changeDerived.address,
        changeSats: selection.changeSats,
        changeDerivation: [CHANGE_BRANCH, nextChangeIdx],
        feeRateSatskb: sendStep.feeRate,
        locktime: 0,
      });

      const blob = await encodeEnvelope(envelope);
      const frames = encodeMultipartLines(blob);

      proposalFrames = frames;
      proposalFrameIdx = 0;
      proposalLastFrameAt = 0;
      const $frameCount = root.querySelector<HTMLElement>("#proposalFrameCount");
      const $byteCount = root.querySelector<HTMLElement>("#proposalByteCount");
      if ($frameCount) $frameCount.textContent = String(frames.length);
      if ($byteCount) $byteCount.textContent = String(blob.length);

      const $proposalHex = root.querySelector<HTMLTextAreaElement>("#proposalHex");
      if ($proposalHex) $proposalHex.value = wrapHex(bytesToHex(blob), 64);

      showSendStep("qr");
      sendStep = { step: "qr" };
      startProposalAnimation();
    } catch (e) {
      $status.classList.add("error");
      const msg =
        e instanceof CoinSelectError ||
        e instanceof ProofFetchError ||
        e instanceof ProposalBuilderError ||
        e instanceof WocError
          ? e.message
          : (e as Error).message;
      $status.textContent = `build failed: ${msg}`;
    } finally {
      sendBusy = false;
      $confirm.disabled = false;
      $confirm.textContent = "Build QR →";
    }
  }

  // QR animation helpers (proposal)
  function startProposalAnimation(): void {
    stopProposalAnimation();
    if (!proposalFrames?.length) return;
    const $toggle = root.querySelector<HTMLButtonElement>("#proposalToggle");
    if ($toggle) $toggle.textContent = "Pause";
    proposalRaf = requestAnimationFrame(tickProposal);
  }

  function stopProposalAnimation(): void {
    if (proposalRaf !== null) cancelAnimationFrame(proposalRaf);
    proposalRaf = null;
    const $toggle = root.querySelector<HTMLButtonElement>("#proposalToggle");
    if ($toggle) $toggle.textContent = "Resume";
  }

  function toggleAnimation(): void {
    if (proposalRaf !== null) stopProposalAnimation();
    else startProposalAnimation();
  }

  function tickProposal(now: number): void {
    if (!proposalFrames || cancelled) { proposalRaf = null; return; }
    const interval = 1000 / 6;
    if (now - proposalLastFrameAt >= interval) {
      proposalLastFrameAt = now;
      const $canvas = root.querySelector<HTMLCanvasElement>("#proposalQr");
      const $idx = root.querySelector<HTMLElement>("#proposalFrameIdx");
      if ($canvas && $idx) {
        $idx.textContent = String(proposalFrameIdx + 1);
        void QRCode.toCanvas($canvas, proposalFrames[proposalFrameIdx], {
          width: 320, margin: 1, errorCorrectionLevel: "M",
        });
      }
      proposalFrameIdx = (proposalFrameIdx + 1) % proposalFrames.length;
    }
    proposalRaf = requestAnimationFrame(tickProposal);
  }

  async function onCopyProposalHex(): Promise<void> {
    const $hex = root.querySelector<HTMLTextAreaElement>("#proposalHex");
    const $status = root.querySelector<HTMLElement>("#proposalHexStatus");
    if (!$hex || !$status) return;
    const flat = $hex.value.replace(/\s+/g, "");
    try {
      await navigator.clipboard.writeText(flat);
      $status.classList.remove("error");
      $status.textContent = `copied ${flat.length / 2} bytes to clipboard`;
    } catch (e) {
      $hex.focus();
      $hex.select();
      $status.classList.add("error");
      $status.textContent = `clipboard denied — selected for manual copy (${(e as Error).message})`;
    }
  }

  // ---------------------------------------------------------------------------
  // Inline PW1 signed-TX scanner
  // ---------------------------------------------------------------------------

  function stopPw1Scan(): void {
    pw1ScanHandle?.stop();
    pw1ScanHandle = null;
    const $widget = root.querySelector<HTMLElement>("#pw1ScanWidget");
    const $actions = root.querySelector<HTMLElement>("#pw1ScanActions");
    if ($widget) $widget.hidden = true;
    if ($actions) $actions.hidden = false;
  }

  async function onStartPw1Scan(): Promise<void> {
    const $widget = root.querySelector<HTMLElement>("#pw1ScanWidget");
    const $actions = root.querySelector<HTMLElement>("#pw1ScanActions");
    const $video = root.querySelector<HTMLVideoElement>("#pw1ScanVideo");
    const $status = root.querySelector<HTMLElement>("#pw1ScanStatus");
    const $progress = root.querySelector<HTMLElement>("#pw1ScanProgress");
    if (!$widget || !$video || !$status || !$actions) return;

    stopPw1Scan();
    $status.textContent = "Scanning for signed TX…";
    if ($progress) $progress.textContent = "";
    $widget.hidden = false;
    $actions.hidden = true;

    pw1ScanHandle = await startPw1Scan(
      $video,
      (received, total) => {
        if ($progress) {
          $progress.textContent = total
            ? `Frame ${received} / ${total}`
            : received > 0 ? `${received} frame${received > 1 ? "s" : ""} received…` : "";
        }
      },
      (bytes) => {
        stopPw1Scan();
        void onSignedTxReceived(bytes);
      },
      (err) => {
        if ($status) $status.textContent = err;
      },
    );
  }

  async function onSignedTxReceived(bytes: Uint8Array): Promise<void> {
    const $broadcast = root.querySelector<HTMLElement>("#broadcastWidget");
    const $info = root.querySelector<HTMLElement>("#broadcastInfo");
    const $broadcastStatus = root.querySelector<HTMLElement>("#broadcastStatus");
    if (!$broadcast || !$info) return;

    let env: Awaited<ReturnType<typeof decodeEnvelope>>;
    try {
      env = await decodeEnvelope(bytes);
    } catch (e) {
      if ($info) $info.textContent = `decode error: ${(e as Error).message}`;
      $broadcast.hidden = false;
      return;
    }

    if (env.kind !== KIND_SIGNED) {
      if ($info) $info.textContent = `unexpected envelope type: ${env.kind}`;
      $broadcast.hidden = false;
      return;
    }

    const signed = env as SignedTxT;
    let txid = "";
    let rawHex = "";
    let sizeBytes = 0;
    try {
      const tx = Transaction.fromAtomicBEEF(Array.from(signed.atomicBeef));
      txid = tx.id("hex") as string;
      rawHex = tx.toHex();
      sizeBytes = rawHex.length / 2;
    } catch (e) {
      if ($info) {
        $info.textContent =
          `signed_tx Atomic BEEF parse failed: ${(e as Error).message}`;
      }
      $broadcast.hidden = false;
      return;
    }

    if ($info) {
      $info.innerHTML = `Ready to broadcast<br><code class="mono" style="font-size:0.75rem;word-break:break-all">${txid}</code>${sizeBytes ? `<br><span class="muted-line">${sizeBytes} bytes</span>` : ""}`;
    }
    if ($broadcastStatus) $broadcastStatus.textContent = "";
    $broadcast.hidden = false;

    const $btn = root.querySelector<HTMLButtonElement>("#broadcastBtn");
    if ($btn) {
      $btn.dataset.signedHex = rawHex;
      $btn.dataset.txid = txid;
      $btn.disabled = false;
      $btn.textContent = "Broadcast";
    }
  }

  async function onBroadcast(): Promise<void> {
    if (!wallet) return;
    const $btn = root.querySelector<HTMLButtonElement>("#broadcastBtn");
    const $status = root.querySelector<HTMLElement>("#broadcastStatus");
    if (!$btn || !$status) return;

    const rawHex = $btn.dataset.signedHex;
    if (!rawHex) { $status.textContent = "no signed TX — scan the Pi's response first"; return; }

    $btn.disabled = true;
    $btn.textContent = "Broadcasting…";
    $status.classList.remove("error");
    $status.textContent = "";

    try {
      if (!woc) woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });
      await woc.broadcastRaw(rawHex);
      const txid = $btn.dataset.txid ?? "";
      const explorer = wallet.network === "test"
        ? `https://test.whatsonchain.com/tx/${txid}`
        : `https://whatsonchain.com/tx/${txid}`;
      $status.classList.remove("error");
      $status.innerHTML = `✓ Broadcast! <a href="${explorer}" target="_blank" rel="noopener noreferrer">View on explorer ↗</a>`;
      $btn.textContent = "Broadcasted";
    } catch (e) {
      $status.classList.add("error");
      let msg: string;
      if (e instanceof WocError) {
        msg = e.message;
        if (e.bodySnippet) msg += `\nWoC said: ${e.bodySnippet}`;
      } else {
        msg = (e as Error).message;
      }
      $status.textContent = `broadcast failed: ${msg}`;
      $btn.disabled = false;
      $btn.textContent = "Retry broadcast";
    }
  }

  function resetSendCard(): void {
    stopProposalAnimation();
    stopPw1Scan();
    proposalFrames = null;
    proposalFrameIdx = 0;
    sendStep = { step: "form" };
    showSendStep("form");
    // Reset broadcast widget
    const $broadcast = root.querySelector<HTMLElement>("#broadcastWidget");
    const $pw1Actions = root.querySelector<HTMLElement>("#pw1ScanActions");
    if ($broadcast) $broadcast.hidden = true;
    if ($pw1Actions) $pw1Actions.hidden = false;
    const $status = root.querySelector<HTMLElement>("#sendFormStatus");
    if ($status) { $status.classList.remove("error"); $status.textContent = ""; }
  }

  // ---------------------------------------------------------------------------
  // Receive
  // ---------------------------------------------------------------------------

  async function renderReceive(): Promise<void> {
    if (!wallet || cancelled) return;
    const idx = wallet.nextReceiveIndex;
    let derived: ReturnType<typeof deriveAddress>;
    try {
      derived = deriveAddress(wallet.xpub, RECEIVE_BRANCH, idx, wallet.network);
    } catch (e) {
      renderError(`derivation error: ${(e as Error).message}`);
      return;
    }
    const $path = root.querySelector<HTMLElement>("#receivePath")!;
    const $addr = root.querySelector<HTMLElement>("#receiveAddress")!;
    const $canvas = root.querySelector<HTMLCanvasElement>("#receiveQr")!;
    const $status = root.querySelector<HTMLElement>("#receiveStatus")!;
    const $prev = root.querySelector<HTMLButtonElement>("#prevIdx")!;
    const $tip = root.querySelector<HTMLElement>("#verifyTip");

    $path.textContent = `${wallet.path} / ${derived.subPath}`;
    $addr.textContent = derived.address;
    $prev.disabled = idx === 0;
    const $windowDesc = root.querySelector<HTMLElement>("#receiveWindowDesc");
    if ($windowDesc) $windowDesc.textContent = `m/0/${idx}`;
    $status.textContent =
      idx === 0 ? "first address (index 0)" : `address #${idx} on receive branch`;

    if ($tip) {
      const steps = idx === 0
        ? "open <strong>Show deposit address</strong> — it starts at address #0"
        : `open <strong>Show deposit address</strong> and press RIGHT <strong>${idx} time${idx === 1 ? "" : "s"}</strong> to reach address #${idx}`;
      $tip.innerHTML =
        `To verify on your Pi: ${steps}, then confirm it matches. ` +
        `<a href="${DOCS_BASE_URL}/security/#address-verification" target="_blank" ` +
        `rel="noopener noreferrer">Why?</a>`;
    }

    try {
      await QRCode.toCanvas($canvas, derived.address, {
        margin: 1, width: 240, errorCorrectionLevel: "M",
      });
    } catch (e) {
      $status.textContent = `qr render error: ${(e as Error).message}`;
    }
    renderRecentList();
  }

  function renderRecentList(): void {
    if (!wallet || cancelled) return;
    const center = wallet.nextReceiveIndex;
    const start = Math.max(0, center - Math.floor(RECENT_WINDOW / 2));
    const batch = deriveAddressBatch(
      wallet.xpub, RECEIVE_BRANCH, start, RECENT_WINDOW, wallet.network,
    );
    const $list = root.querySelector<HTMLUListElement>("#receiveList")!;
    $list.innerHTML = "";
    for (const a of batch) {
      const li = document.createElement("li");
      li.className = a.index === center ? "addr-row current" : "addr-row";
      li.innerHTML = `
        <span class="addr-index">m/0/${a.index}</span>
        <code class="addr-addr">${escapeHtml(a.address)}</code>
        <button class="copy" data-address="${escapeHtml(a.address)}" type="button">Copy</button>
      `;
      $list.appendChild(li);
    }
    $list.querySelectorAll<HTMLButtonElement>("button.copy").forEach((b) => {
      b.addEventListener("click", () => {
        const v = b.dataset.address ?? "";
        void navigator.clipboard.writeText(v).then(() => {
          const orig = b.textContent;
          b.textContent = "copied!";
          setTimeout(() => { b.textContent = orig; }, 1200);
        }).catch(() => {});
      });
    });
  }

  async function shiftIndex(delta: number): Promise<void> {
    if (!wallet) return;
    const next = wallet.nextReceiveIndex + delta;
    if (next < 0) return;
    try {
      await setNextReceiveIndex(wallet.id, next);
      wallet.nextReceiveIndex = next;
    } catch (e) {
      const $s = root.querySelector<HTMLElement>("#receiveStatus");
      if ($s) {
        $s.classList.add("error");
        $s.textContent = `cannot advance index: ${(e as Error).message}`;
      }
      return;
    }
    void renderReceive();
  }

  async function onCopy(): Promise<void> {
    const $addr = root.querySelector<HTMLElement>("#receiveAddress");
    if (!$addr) return;
    try {
      await navigator.clipboard.writeText($addr.textContent ?? "");
      const $btn = root.querySelector<HTMLButtonElement>("#copyAddress");
      if ($btn) {
        const orig = $btn.textContent;
        $btn.textContent = "copied!";
        setTimeout(() => { if ($btn) $btn.textContent = orig; }, 1200);
      }
    } catch (e) {
      const $s = root.querySelector<HTMLElement>("#receiveStatus");
      if ($s) $s.textContent = `clipboard error: ${(e as Error).message}`;
    }
  }

  // ---------------------------------------------------------------------------
  // Share / export QR
  // ---------------------------------------------------------------------------

  async function onShowExport(): Promise<void> {
    if (!wallet) return;
    const envelope = {
      kind: KIND_XPUB,
      xpub: wallet.xpub,
      path: wallet.path,
      label: wallet.label,
      fingerprint: hexToBytes(wallet.fingerprint),
      network: wallet.network,
    } as const;
    const blob = await encodeEnvelope(envelope);
    exportFrames = encodeMultipartLines(blob);
    exportFrameIdx = 0;
    exportLastFrameAt = 0;
    const $result = root.querySelector<HTMLElement>("#exportResult")!;
    const $count = root.querySelector<HTMLElement>("#exportFrameCount")!;
    const $showBtn = root.querySelector<HTMLButtonElement>("#exportShow");
    $result.hidden = false;
    if ($showBtn) $showBtn.hidden = true;
    $count.textContent = String(exportFrames.length);
    startExportAnimation();
  }

  function startExportAnimation(): void {
    stopExportAnimation();
    if (!exportFrames?.length) return;
    const $toggle = root.querySelector<HTMLButtonElement>("#exportToggle");
    if ($toggle) $toggle.textContent = "Pause";
    exportRaf = requestAnimationFrame(tickExport);
  }

  function stopExportAnimation(): void {
    if (exportRaf !== null) cancelAnimationFrame(exportRaf);
    exportRaf = null;
    const $toggle = root.querySelector<HTMLButtonElement>("#exportToggle");
    if ($toggle) $toggle.textContent = "Resume";
  }

  function toggleExportAnimation(): void {
    if (exportRaf !== null) stopExportAnimation();
    else startExportAnimation();
  }

  function hideExport(): void {
    stopExportAnimation();
    exportFrames = null;
    const $result = root.querySelector<HTMLElement>("#exportResult");
    if ($result) $result.hidden = true;
    const $showBtn = root.querySelector<HTMLButtonElement>("#exportShow");
    if ($showBtn) $showBtn.hidden = false;
  }

  function tickExport(now: number): void {
    if (!exportFrames || cancelled) { exportRaf = null; return; }
    const interval = 1000 / 6;
    if (now - exportLastFrameAt >= interval) {
      exportLastFrameAt = now;
      const $canvas = root.querySelector<HTMLCanvasElement>("#exportQr");
      const $idx = root.querySelector<HTMLElement>("#exportFrameIdx");
      if ($canvas && $idx) {
        $idx.textContent = String(exportFrameIdx + 1);
        void QRCode.toCanvas($canvas, exportFrames[exportFrameIdx], {
          width: 320, margin: 1, errorCorrectionLevel: "M",
        });
      }
      exportFrameIdx = (exportFrameIdx + 1) % exportFrames.length;
    }
    exportRaf = requestAnimationFrame(tickExport);
  }

  // ---------------------------------------------------------------------------
  // Teardown
  // ---------------------------------------------------------------------------

  return () => {
    cancelled = true;
    stopProposalAnimation();
    stopExportAnimation();
    stopAddrScan();
    stopPw1Scan();
  };
}
