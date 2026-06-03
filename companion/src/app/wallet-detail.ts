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
import { DOCS_BASE_URL, PRICE_CACHE_TTL_MS, PW1_QR_FRAME_MS } from "../lib/config.js";
import { relativeTimeFrom } from "../lib/relative-time.js";
import {
  KIND_XPUB,
  KIND_SIGNED,
  type SignedTxT,
  bytesToHex,
  encodeEnvelope,
  hexToBytes,
  decodeEnvelope,
} from "../lib/envelope.js";
import { CoinSelectError, computeMaxSendSats, selectUtxosGreedy } from "../lib/coin-select.js";
import { decodeHexPasteToBytes } from "../lib/hex-paste.js";
import { encodeMultipartLines } from "../pw1.js";
import { Transaction } from "@bsv/sdk";
import { ProofFetchError, fetchInputProof } from "../lib/proof-fetcher.js";
import { renderHeader } from "./nav.js";
import {
  ProposalBuilderError,
  buildUnsignedProposal,
} from "../lib/proposal.js";
import { noSpendableUtxosMessage, splitConfirmedPending } from "../lib/balance-split.js";
import { confirmedUtxos, scanWalletUtxos, scanNextReceiveIndex } from "../lib/utxo.js";
import { WocClient, WocError, effectiveWocBase, wocExplorerTxUrl } from "../lib/woc.js";
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
const RECEIVE_QR_SIZE_DEFAULT = 240;
const RECEIVE_QR_SIZE_LARGE = 320;

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
  | { step: "review"; recipient: string; sats: number; feeRate: number; feeSats: number; changeSats: number }
  | { step: "qr" };

// ---------------------------------------------------------------------------
// Main mount function
// ---------------------------------------------------------------------------

const VALID_TABS = new Set(["balance", "send", "receive", "history", "advanced"]);

function normalizeTab(tab: string | undefined): string | undefined {
  if (tab === "share") return "advanced";
  return tab;
}

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
  let sendQrTab: "proposal" | "scan" = "proposal";
  /** True when amount was set via Max — re-applied when fee tier changes. */
  let sendAmountIsMax = false;
  let suppressSendAmountInput = false;

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
  let receiveQrLarge = false;
  let receiveAdvancePending: number | null = null;

  // Active tab
  type Tab = "balance" | "send" | "receive" | "history" | "advanced";
  const tabFromRoute = normalizeTab(initialTab);
  let activeTab: Tab =
    tabFromRoute && VALID_TABS.has(tabFromRoute) ? (tabFromRoute as Tab) : "balance";

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
          <div class="tab-nav-tabs">
            <button role="tab" data-tab="balance" class="${activeTab === "balance" ? "active" : ""}">Balance</button>
            <button role="tab" data-tab="send" class="${activeTab === "send" ? "active" : ""}">Send</button>
            <button role="tab" data-tab="receive" class="${activeTab === "receive" ? "active" : ""}">Receive</button>
            <button role="tab" data-tab="history" class="${activeTab === "history" ? "active" : ""}">History</button>
            <button role="tab" data-tab="advanced" class="${activeTab === "advanced" ? "active" : ""}">Advanced</button>
          </div>
          <select id="unitSelect" class="tab-unit-select" aria-label="Display unit">
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
                title="Tap to cycle sats, BSV, or ${getFiatCurrency()}">
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
          <p class="muted-line balance-spv-note" id="balanceSpvNote" hidden></p>
          <p class="muted-line balance-status" id="balanceStatus"></p>
          <details id="utxoDetails" class="panel-details" hidden>
            <summary><span class="panel-details-label">UTXOs (<span id="utxoCount">0</span>)</span></summary>
            <div class="panel-details-body">
              <ul id="utxoList" class="utxo-list"></ul>
            </div>
          </details>
        </section>

        <!-- Send tab -->
        <section id="tab-send" class="card tab-panel${activeTab === "send" ? " active" : ""}" role="tabpanel">
          <div id="sendProgress" class="send-progress" aria-live="polite">
            <p id="sendProgressLabel" class="send-progress-label muted-line">Step 1 of 3 — Amount & fee</p>
            <div class="send-progress-track" aria-hidden="true">
              <div id="sendProgressFill" class="send-progress-fill" style="width:33%"></div>
            </div>
          </div>
          <div id="sendPendingBanner" class="send-pending-banner" hidden></div>
          <p class="send-balance-line muted-line">
            Spendable: <span id="sendBalanceHero">—</span>
            <span id="sendBalancePending" hidden></span>
            <span class="info-tip-wrap">
              <button id="sendSpvInfoTip" class="info-tip" type="button"
                aria-label="Why only confirmed coins are spendable">ⓘ</button>
              <span id="sendSpvInfoText" class="info-tip-text" hidden>
                Sending uses SPV verification — only confirmed on-chain coins are
                spendable. Pending UTXOs must confirm first.
              </span>
            </span>
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
              <span>Network fee</span>
              <select id="feeTierSelect" class="fee-tier-select" disabled>
                ${((): string => {
                  const defTier = getDefaultFeeTier();
                  const sel = (v: string) => v === defTier ? " selected" : "";
                  return `
                <option value="economy"${sel("economy")}>Economy</option>
                <option value="standard"${sel("standard")}>Standard</option>
                <option value="priority"${sel("priority")}>Priority</option>
                <option value="custom"${sel("custom")}>Custom…</option>`;
                })()}
              </select>
              <p class="muted-line send-fee-loading" id="feeLoading">Loading fee rates…</p>
            </label>
            <div id="feeCustomRow" class="fee-custom-row"${getDefaultFeeTier() === "custom" ? "" : " hidden"}>
              <label class="field">
                <span>Custom rate (sat/kB)</span>
                <input id="feeCustom" type="number" min="0" step="1"
                  value="${getDefaultCustomFeeRate()}"
                  placeholder="${DEFAULT_FEE_RATE_SATSKB}" />
              </label>
            </div>
            <label class="field">
              <span>Amount</span>
              <div class="amount-row">
                <input id="sendAmount" type="number" min="0" step="any"
                  placeholder="0" />
                <select id="sendUnit" class="send-unit-select">
                  <option value="sats">sats</option>
                  <option value="bsv">BSV</option>
                  <option value="fiat">${getFiatCurrency()}</option>
                </select>
                <button id="sendMax" type="button" class="send-max-btn">Max</button>
              </div>
            </label>
            <p class="muted-line" id="sendFormStatus"></p>
            <div class="actions">
              <button id="sendNext" type="button" class="primary">Review →</button>
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
            <ol class="sign-steps spv-steps" id="spvSteps" hidden aria-label="SPV build progress">
              <li class="sign-step" id="spvStep-select">Select inputs</li>
              <li class="sign-step" id="spvStep-proofs">Verify SPV proofs</li>
              <li class="sign-step" id="spvStep-build">Build proposal</li>
            </ol>
            <p class="muted-line" id="spvDetail" hidden></p>
            <p class="muted-line" id="reviewStatus"></p>
            <div class="actions">
              <button id="reviewBack" type="button">← Back</button>
              <button id="reviewConfirm" type="button" class="primary">Build QR →</button>
            </div>
          </div>

          <div id="sendStep-qr" hidden>
            <div class="scanner-tabs send-qr-tabs" role="tablist">
              <button role="tab" data-send-qr-tab="proposal"
                class="scanner-tab active" type="button">
                Step 1 — Show QR
              </button>
              <button role="tab" data-send-qr-tab="scan"
                class="scanner-tab" type="button">
                Step 2 — Scan
              </button>
            </div>

            <div id="sendQrTab-proposal" role="tabpanel">
              <p id="spvCompleteBanner" class="spv-complete-banner" hidden></p>
              <p class="muted-line">Point the Pi camera at this animated QR.</p>
              <canvas id="proposalQr" width="320" height="320"></canvas>
              <p class="muted-line">
                Frame <span id="proposalFrameIdx">0</span> /
                <span id="proposalFrameCount">0</span> ·
                <span id="proposalByteCount">0</span> bytes
              </p>
              <div class="actions">
                <button id="proposalToggle" type="button" class="primary">Pause</button>
                <button id="sendQrGoScan" type="button">Step 2 →</button>
                <button id="proposalDone" type="button">New send</button>
              </div>

              <details class="advanced send-advanced-details">
                <summary>Advanced</summary>
                <p class="muted-line">
                  Copy the unsigned proposal hex to sign on the Pi terminal:<br>
                  <code>piwallet sign --hex &lt;paste&gt; --wallet-id &lt;id&gt;</code><br>
                  Then paste the signed output under Advanced on Step 2.
                </p>
                <textarea id="proposalHex" class="hex-blob" rows="6"
                  readonly spellcheck="false" autocorrect="off"></textarea>
                <div class="actions">
                  <button id="copyProposalHex" type="button" class="primary">Copy proposal hex</button>
                </div>
                <p class="muted-line" id="proposalHexStatus"></p>
              </details>
            </div>

            <div id="sendQrTab-scan" role="tabpanel" hidden>
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
              <div id="pw1ScanActions" class="actions send-scan-actions">
                <button id="pw1ScanStart" type="button" class="primary">Scan Pi's response</button>
              </div>

              <details class="advanced send-advanced-details">
                <summary>Advanced</summary>
                <p class="muted-line">
                  Paste a signed transaction from the Pi or another source.
                  Full terminal output (<code>signed_tx:</code>, etc.) is fine.
                </p>
                <textarea id="pasteSignedTx" class="hex-blob" rows="6"
                  placeholder="signed_tx: …"
                  spellcheck="false" autocorrect="off"></textarea>
                <div class="actions">
                  <button id="pasteSignedTxDecode" type="button" class="primary">
                    Decode &amp; broadcast
                  </button>
                  <button id="pasteSignedTxClear" type="button">Clear</button>
                </div>
                <p id="pasteSignedTxStatus" class="muted-line"></p>
              </details>

              <div id="broadcastWidget" class="send-broadcast-panel" hidden>
                <p id="broadcastInfo" class="send-broadcast-message muted-line"></p>
                <p id="broadcastStatus" class="send-broadcast-message muted-line"></p>
                <div class="actions send-broadcast-actions">
                  <button id="broadcastBtn" type="button" class="primary">Broadcast</button>
                  <a id="broadcastExplorer" target="_blank" rel="noopener noreferrer"
                    class="primary-link" hidden>View on explorer ↗</a>
                  <button id="broadcastDone" type="button" class="primary" hidden>
                    View balance
                  </button>
                  <button id="proposalDone2" type="button">Send again</button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Receive tab -->
        <section id="tab-receive" class="card tab-panel${activeTab === "receive" ? " active" : ""}" role="tabpanel">
          <h2 class="receive-heading">Receive</h2>
          <p class="receive-verify-line muted-line">
            Confirm this address on the Pi before sharing it.
            <span class="info-tip-wrap">
              <button id="receiveVerifyTip" class="info-tip" type="button"
                aria-label="Why verify on the Pi">ⓘ</button>
              <span id="receiveVerifyText" class="info-tip-text" hidden>
                The companion derives addresses from your public key only — if the
                browser were tampered with, it could show someone else's address.
                <span id="receiveVerifySteps" class="receive-verify-steps"></span>
                <a href="${DOCS_BASE_URL}/security/#address-verification" target="_blank"
                  rel="noopener noreferrer">Address verification guide ↗</a>
              </span>
            </span>
          </p>
          <p class="muted-line" id="receivePath"></p>
          <div class="receive-row">
            <div class="receive-qr-wrap">
              <canvas id="receiveQr" width="240" height="240"></canvas>
              <button id="receiveQrSizeToggle" type="button" class="receive-qr-size-btn">
                Larger QR
              </button>
            </div>
            <div class="receive-detail">
              <code id="receiveAddress" class="big-address"></code>
              <div id="receiveAdvanceConfirm" class="receive-advance-confirm" hidden>
                <p class="remove-confirm-msg warning-text" id="receiveAdvanceConfirmMsg"></p>
                <div class="actions">
                  <button id="receiveAdvanceConfirmYes" type="button" class="primary">
                    Continue
                  </button>
                  <button id="receiveAdvanceConfirmNo" type="button">Cancel</button>
                </div>
              </div>
              <div class="actions receive-actions">
                <button id="copyAddress" type="button">Copy address</button>
                <button id="prevIdx" type="button">← Previous</button>
                <button id="nextIdx" class="primary" type="button">Next address</button>
              </div>
              <p class="muted-line" id="receiveStatus"></p>
            </div>
          </div>
          <details class="panel-details">
            <summary><span class="panel-details-label">Recent receive addresses</span></summary>
            <div class="panel-details-body">
              <p class="muted-line receive-list-hint">
                A window of 8 addresses around the current pointer
                (<span id="receiveWindowDesc">m/0/0</span>).
              </p>
              <ul id="receiveList" class="addr-list"></ul>
            </div>
          </details>
        </section>

        <!-- History tab -->
        <section id="tab-history" class="card tab-panel${activeTab === "history" ? " active" : ""}" role="tabpanel">
          <div class="history-header">
            <h2>Transaction history</h2>
            <button id="refreshHistory" class="primary" type="button">Refresh</button>
          </div>
          <p class="muted-line" id="historyStatus"></p>
          <div id="historyEmpty" class="empty-state" hidden>
            <p id="historyEmptyTitle">No transaction history yet.</p>
            <p class="muted-line" id="historyEmptyHint">Click Refresh to fetch history from Bitails.</p>
            <button id="scanBalanceForHistory" class="primary" type="button" hidden>
              Scan balance first
            </button>
          </div>
          <ul id="historyList" class="history-list"></ul>
        </section>

        <!-- Share tab -->
        <section id="tab-advanced" class="card tab-panel${activeTab === "advanced" ? " active" : ""}" role="tabpanel">
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
            <input id="renameInput" type="text" maxlength="64" required
              autocorrect="off" spellcheck="false"
              value="${escapeHtml(wallet.label)}" />
          </label>
          <div class="actions">
            <button id="renameSaveBtn" type="button" class="primary" disabled>Save label</button>
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
    if (activeTab === "send") void loadFeeRates();
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
    root.querySelector<HTMLButtonElement>("#sendSpvInfoTip")
      ?.addEventListener("click", (e) => {
        e.preventDefault();
        const tip = root.querySelector<HTMLElement>("#sendSpvInfoText");
        if (tip) tip.hidden = !tip.hidden;
      });
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
        const unit = (e.target as HTMLSelectElement).value;
        if (unit === "fiat") void fetchBsvPrice();
        if (sendAmountIsMax) onSendMax();
      });
    root.querySelector<HTMLInputElement>("#sendAmount")
      ?.addEventListener("input", () => {
        if (suppressSendAmountInput) return;
        sendAmountIsMax = false;
        refreshFeeTierEstimates();
      });
    root.querySelector<HTMLButtonElement>("#reviewBack")
      ?.addEventListener("click", () => {
        syncSendFormFromStep();
        sendStep = { step: "form" };
        showSendStep("form");
      });
    root.querySelector<HTMLButtonElement>("#reviewConfirm")
      ?.addEventListener("click", () => void onBuildProposal());
    root.querySelector<HTMLButtonElement>("#proposalToggle")
      ?.addEventListener("click", toggleAnimation);
    root.querySelector<HTMLButtonElement>("#sendQrGoScan")
      ?.addEventListener("click", () => switchSendQrTab("scan"));
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
    root.querySelector<HTMLButtonElement>("#pasteSignedTxDecode")
      ?.addEventListener("click", () => void onPasteSignedTxDecode());
    root.querySelector<HTMLButtonElement>("#pasteSignedTxClear")
      ?.addEventListener("click", onPasteSignedTxClear);
    root.querySelector<HTMLButtonElement>("#broadcastBtn")
      ?.addEventListener("click", () => void onBroadcast());
    root.querySelector<HTMLButtonElement>("#broadcastDone")
      ?.addEventListener("click", () => void onBroadcastDone());
    root.querySelectorAll<HTMLButtonElement>("[data-send-qr-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.sendQrTab as "proposal" | "scan";
        switchSendQrTab(tab);
      });
    });

    // Fee tier dropdown + custom rate
    root.querySelector<HTMLSelectElement>("#feeTierSelect")
      ?.addEventListener("change", () => onFeeTierChanged());
    root.querySelector<HTMLInputElement>("#feeCustom")
      ?.addEventListener("input", () => onFeeTierChanged());

    // Receive tab
    root.querySelector<HTMLButtonElement>("#receiveVerifyTip")
      ?.addEventListener("click", (e) => {
        e.preventDefault();
        const tip = root.querySelector<HTMLElement>("#receiveVerifyText");
        if (tip) tip.hidden = !tip.hidden;
      });
    root.querySelector<HTMLButtonElement>("#copyAddress")
      ?.addEventListener("click", () => void onCopy());
    root.querySelector<HTMLButtonElement>("#prevIdx")
      ?.addEventListener("click", () => void shiftIndex(-1));
    root.querySelector<HTMLButtonElement>("#nextIdx")
      ?.addEventListener("click", () => void shiftIndex(1));
    root.querySelector<HTMLButtonElement>("#receiveQrSizeToggle")
      ?.addEventListener("click", () => {
        receiveQrLarge = !receiveQrLarge;
        void renderReceive();
      });
    root.querySelector<HTMLButtonElement>("#receiveAdvanceConfirmYes")
      ?.addEventListener("click", () => {
        if (receiveAdvancePending === null) return;
        const target = receiveAdvancePending;
        hideReceiveAdvanceConfirm();
        void applyReceiveIndex(target);
      });
    root.querySelector<HTMLButtonElement>("#receiveAdvanceConfirmNo")
      ?.addEventListener("click", hideReceiveAdvanceConfirm);

    // History tab
    root.querySelector<HTMLButtonElement>("#refreshHistory")
      ?.addEventListener("click", () => void onRefreshHistory());
    root.querySelector<HTMLButtonElement>("#scanBalanceForHistory")
      ?.addEventListener("click", () => void onScanBalanceForHistory());

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
    root.querySelector<HTMLInputElement>("#renameInput")
      ?.addEventListener("input", syncRenameSaveBtn);
    syncRenameSaveBtn();
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

  function syncRenameSaveBtn(): void {
    if (!wallet) return;
    const $input = root.querySelector<HTMLInputElement>("#renameInput");
    const $btn = root.querySelector<HTMLButtonElement>("#renameSaveBtn");
    if (!$input || !$btn) return;
    const trimmed = $input.value.trim();
    $btn.disabled = !trimmed || trimmed === wallet.label;
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
      syncRenameSaveBtn();
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
    // Lazy-load history when tab first opened (requires balance scan first)
    if (
      tab === "history" &&
      wallet?.lastScan &&
      wallet.lastHistory == null &&
      !historyRunning
    ) {
      void onRefreshHistory();
    }
    // Silently verify receive index is still unused when tab opens
    if (tab === "receive") {
      void refreshReceiveIndex();
    }
    if (tab === "send" && sendStep.step === "form") {
      void loadFeeRates();
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
    if ($toggle) {
      const label =
        unit === "fiat" ? getFiatCurrency() : unit === "bsv" ? "BSV" : "sats";
      $toggle.title = `Tap to cycle (showing ${label})`;
    }
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
    const $spvNote = root.querySelector<HTMLElement>("#balanceSpvNote");
    const $details = root.querySelector<HTMLDetailsElement>("#utxoDetails");
    const $count = root.querySelector<HTMLElement>("#utxoCount");
    const $list = root.querySelector<HTMLUListElement>("#utxoList");
    if (!$hero || !$bsv || !$meta || !$pending || !$spvNote || !$details || !$count || !$list)
      return;

    const $sendBal = root.querySelector<HTMLElement>("#sendBalanceHero");
    const $sendPending = root.querySelector<HTMLElement>("#sendBalancePending");

    const scan = wallet.lastScan;
    if (!scan) {
      $hero.textContent = "—";
      $bsv.textContent = "";
      $meta.textContent = "Not scanned yet — click Refresh to query WhatsOnChain.";
      $pending.hidden = true;
      $details.hidden = true;
      if ($spvNote) $spvNote.hidden = true;
      if ($sendBal) $sendBal.textContent = "—";
      if ($sendPending) $sendPending.hidden = true;
      renderSendPendingBanner();
      return;
    }

    const split = splitConfirmedPending(scan.utxos);
    if ($sendBal) {
      $sendBal.textContent = formatBalance(split.confirmedSats);
    }
    if ($sendPending) {
      if (split.hasPending) {
        $sendPending.hidden = false;
        $sendPending.textContent =
          ` · ${formatBalance(split.pendingSats)} pending (not spendable yet)`;
      } else {
        $sendPending.hidden = true;
        $sendPending.textContent = "";
      }
    }
    renderSendPendingBanner();
    $hero.textContent = formatBalance(scan.totalSats);
    $bsv.textContent =
      displayUnit === "sats" ? formatBsv(scan.totalSats) :
      displayUnit === "bsv"  ? formatSats(scan.totalSats) :
      formatSats(scan.totalSats);
    $meta.textContent =
      `${scan.utxos.length} UTXO${scan.utxos.length === 1 ? "" : "s"} · ` +
      `last refreshed ${relativeTimeFrom(scan.at)}`;

    if (split.hasPending) {
      $pending.hidden = false;
      $pending.textContent = split.allPending
        ? "pending"
        : `+${formatSats(split.pendingSats)} pending`;
      $spvNote.hidden = false;
      $spvNote.textContent =
        "Pending coins are included in your total but cannot be spent until " +
        "they confirm — SPV requires an on-chain Merkle proof for each input.";
    } else {
      $pending.hidden = true;
      $spvNote.hidden = true;
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
          ${isPending ? '<span class="utxo-pending-tag">pending</span>' : `block ${u.height}`}
        </div>
      `;
      $list.appendChild(li);
    }
  }

  async function onRefreshBalance(options: { thenHistory?: boolean } = {}): Promise<void> {
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
        stoppedAt: result.stoppedAt,
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
      if (options.thenHistory) {
        await onRefreshHistory();
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
    const $emptyTitle = root.querySelector<HTMLElement>("#historyEmptyTitle");
    const $emptyHint = root.querySelector<HTMLElement>("#historyEmptyHint");
    const $scanBtn = root.querySelector<HTMLButtonElement>("#scanBalanceForHistory");
    const $refreshBtn = root.querySelector<HTMLButtonElement>("#refreshHistory");
    const $status = root.querySelector<HTMLElement>("#historyStatus");
    if (!$list || !$empty) return;

    const needsScan = !wallet.lastScan;
    if ($scanBtn) $scanBtn.hidden = !needsScan;
    if ($refreshBtn) {
      $refreshBtn.textContent = needsScan ? "Scan balance first" : "Refresh";
    }

    const snap = wallet.lastHistory;
    if (!snap) {
      $empty.hidden = false;
      $list.innerHTML = "";
      if ($emptyTitle) {
        $emptyTitle.textContent = needsScan
          ? "Balance scan required"
          : "No transaction history yet.";
      }
      if ($emptyHint) {
        $emptyHint.textContent = needsScan
          ? "Refresh balance first so we know which addresses to check."
          : wallet.network === "test"
            ? "Click Refresh to fetch history from WhatsOnChain."
            : "Click Refresh to fetch history from Bitails.";
      }
      if ($status) $status.textContent = "";
      return;
    }
    $empty.hidden = snap.entries.length > 0;
    if ($emptyTitle && snap.entries.length === 0) {
      $emptyTitle.textContent = "No transactions found";
    }
    if ($emptyHint && snap.entries.length === 0) {
      $emptyHint.textContent =
        `Checked ${snap.addressesQueried} address${snap.addressesQueried === 1 ? "" : "es"} — none had history.`;
    }
    if ($status) {
      $status.textContent =
        `${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"} · ` +
        `${snap.addressesQueried} address${snap.addressesQueried === 1 ? "" : "es"} checked · ` +
        `last fetched ${relativeTimeFrom(snap.at)}`;
    }
    $list.innerHTML = "";
    for (const tx of snap.entries) {
      const li = document.createElement("li");
      const deltaKnown = tx.deltaKnown !== false;
      const isReceive = tx.deltaSats >= 0;
      const isPending = tx.blockHeight === 0;
      li.className = `history-row ${deltaKnown ? (isReceive ? "receive" : "send") : "unknown"}${isPending ? " pending" : ""}`;
      const network = wallet.network ?? "main";
      const deltaHtml = deltaKnown
        ? `<span class="history-delta ${isReceive ? "positive" : "negative"}">${isReceive ? "+" : ""}${formatSats(tx.deltaSats)}</span>`
        : `<span class="history-delta muted-line">—</span>`;
      const timeLabel = formatTxTimestamp(tx.timestamp);
      li.innerHTML = `
        <div class="history-top">
          ${deltaHtml}
          <span class="history-time muted-line">${escapeHtml(timeLabel)}</span>
        </div>
        <div class="history-meta muted-line">
          <a href="${escapeHtml(wocExplorerTxUrl(tx.txid, network))}" target="_blank"
             rel="noopener noreferrer">${escapeHtml(shortTxid(tx.txid))}</a>
          ${isPending
            ? '<span class="utxo-pending-tag">pending</span>'
            : `· block ${tx.blockHeight}`}
        </div>
      `;
      $list.appendChild(li);
    }
  }

  async function onScanBalanceForHistory(): Promise<void> {
    await onRefreshBalance({ thenHistory: true });
  }

  async function onRefreshHistory(): Promise<void> {
    if (!wallet || historyRunning) return;
    if (!wallet.lastScan) {
      await onRefreshBalance({ thenHistory: true });
      return;
    }
    historyRunning = true;
    const $btn = root.querySelector<HTMLButtonElement>("#refreshHistory");
    const $status = root.querySelector<HTMLElement>("#historyStatus");
    if ($btn) { $btn.disabled = true; $btn.textContent = "Fetching…"; }
    if ($status) { $status.classList.remove("error"); $status.textContent = wallet.network === "test"
      ? "Fetching history from WhatsOnChain…"
      : "Fetching history from Bitails…"; }

    if (!bitails) {
      bitails = new BitailsClient({ baseUrl: effectiveBitailsBase(wallet.network) });
    }
    if (!woc) {
      woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });
    }

    try {
      const snap = await fetchWalletHistory(wallet.xpub, bitails, {
        network: wallet.network,
        woc: wallet.network === "test" ? woc : undefined,
        stoppedAtReceive: wallet.lastScan.stoppedAt?.receive,
        stoppedAtChange: wallet.lastScan.stoppedAt?.change,
        lastReceiveUsed: wallet.lastScan.lastReceiveUsed,
        lastChangeUsed: wallet.lastScan.lastChangeUsed,
        onProgress: (done, total, phase) => {
          if (cancelled || !$status) return;
          $status.textContent =
            phase === "transactions"
              ? `Loading transaction details (${done}/${total})…`
              : `Fetching history (${done}/${total} addresses)…`;
        },
      });
      if (cancelled) return;
      await setLastHistory(wallet.id, snap);
      wallet.lastHistory = snap;
      renderHistory();
      if ($status) {
        $status.textContent =
          `${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"} · ` +
          `${snap.addressesQueried} address${snap.addressesQueried === 1 ? "" : "es"} checked · ` +
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

  const SEND_PROGRESS: Record<"form" | "review" | "qr", { label: string; pct: number }> = {
    form: { label: "Step 1 of 3 — Amount & fee", pct: 33 },
    review: { label: "Step 2 of 3 — Review", pct: 66 },
    qr: { label: "Step 3 of 3 — Sign on Pi & broadcast", pct: 100 },
  };

  function updateSendProgress(step: "form" | "review" | "qr"): void {
    const meta = SEND_PROGRESS[step];
    const $label = root.querySelector<HTMLElement>("#sendProgressLabel");
    const $fill = root.querySelector<HTMLElement>("#sendProgressFill");
    if ($label) $label.textContent = meta.label;
    if ($fill) $fill.style.width = `${meta.pct}%`;
  }

  function renderSendPendingBanner(): void {
    const $banner = root.querySelector<HTMLElement>("#sendPendingBanner");
    if (!$banner) return;
    if (!wallet?.lastScan) {
      $banner.hidden = true;
      return;
    }
    const split = splitConfirmedPending(wallet.lastScan.utxos);
    if (!split.allPending) {
      $banner.hidden = true;
      return;
    }
    $banner.hidden = false;
    $banner.innerHTML =
      `<strong>Nothing spendable yet.</strong> ` +
      `${formatBalance(split.pendingSats)} is pending and cannot be sent until it confirms. ` +
      `Refresh Balance after confirmation.`;
  }

  function getSelectedFeeRate(): number {
    const selected = root.querySelector<HTMLSelectElement>("#feeTierSelect")?.value;
    if (selected === "economy") return feeRec?.economy ?? DEFAULT_FEE_RATE_SATSKB;
    if (selected === "standard") return feeRec?.standard ?? DEFAULT_FEE_RATE_SATSKB;
    if (selected === "priority") return feeRec?.priority ?? DEFAULT_FEE_RATE_SATSKB * 5;
    const $custom = root.querySelector<HTMLInputElement>("#feeCustom");
    const rate = parseInt($custom?.value ?? "", 10);
    return Number.isInteger(rate) && rate >= 0 ? rate : getDefaultCustomFeeRate();
  }

  function getSelectedFeeTier(): string {
    return root.querySelector<HTMLSelectElement>("#feeTierSelect")?.value ?? "standard";
  }

  function readFormAmountSats(): number | null {
    const $amountInput = root.querySelector<HTMLInputElement>("#sendAmount");
    const $unitSelect = root.querySelector<HTMLSelectElement>("#sendUnit");
    if (!$amountInput || !$unitSelect) return null;
    const amountRaw = $amountInput.value.trim();
    if (amountRaw === "") return null;
    const amountNum = parseFloat(amountRaw);
    if (isNaN(amountNum) || amountNum <= 0) return null;
    const unit = $unitSelect.value as "sats" | "bsv" | "fiat";
    let sats: number;
    if (unit === "sats") {
      sats = Math.round(amountNum);
    } else if (unit === "bsv") {
      sats = Math.round(amountNum * SATS_PER_BSV);
    } else {
      if (bsvUsdPrice === null || bsvUsdPrice === 0) return null;
      sats = Math.round((amountNum / bsvUsdPrice) * SATS_PER_BSV);
    }
    return Number.isInteger(sats) && sats > 0 ? sats : null;
  }

  function amountSatsForFeeEstimate(): number | null {
    if (sendStep.step === "review") return sendStep.sats;
    return readFormAmountSats();
  }

  function syncSendFormFromStep(): void {
    if (sendStep.step !== "review") return;
    const $amount = root.querySelector<HTMLInputElement>("#sendAmount");
    const $unit = root.querySelector<HTMLSelectElement>("#sendUnit");
    if (!$amount || !$unit) return;
    const sats = sendStep.sats;
    const unit = $unit.value as "sats" | "bsv" | "fiat";
    if (unit === "sats") {
      $amount.value = String(sats);
    } else if (unit === "bsv") {
      $amount.value = (sats / SATS_PER_BSV).toFixed(8);
    } else if (bsvUsdPrice !== null && bsvUsdPrice > 0) {
      $amount.value = ((sats / SATS_PER_BSV) * bsvUsdPrice).toFixed(2);
    } else {
      $amount.value = String(sats);
    }
  }

  function showSendStep(step: "form" | "review" | "qr"): void {
    const steps = ["form", "review", "qr"];
    for (const s of steps) {
      const el = root.querySelector<HTMLElement>(`#sendStep-${s}`);
      if (el) el.hidden = s !== step;
    }
    updateSendProgress(step);
    if (step === "form") {
      syncSendFormFromStep();
      void loadFeeRates();
    }
    if (step === "qr") switchSendQrTab("proposal");
  }

  type SpvBuildStep = "idle" | "select" | "proofs" | "build" | "done" | "error";

  function resetSpvUi(): void {
    const $steps = root.querySelector<HTMLElement>("#spvSteps");
    const $detail = root.querySelector<HTMLElement>("#spvDetail");
    const $banner = root.querySelector<HTMLElement>("#spvCompleteBanner");
    if ($steps) $steps.hidden = true;
    if ($detail) {
      $detail.hidden = true;
      $detail.textContent = "";
      $detail.classList.remove("error");
    }
    if ($banner) {
      $banner.hidden = true;
      $banner.textContent = "";
    }
    for (const id of ["spvStep-select", "spvStep-proofs", "spvStep-build"]) {
      const el = root.querySelector<HTMLElement>(`#${id}`);
      if (el) el.className = "sign-step";
    }
  }

  function setSpvBuildStep(
    step: SpvBuildStep,
    detail?: string,
    failedAt?: "select" | "proofs" | "build",
  ): void {
    const $steps = root.querySelector<HTMLElement>("#spvSteps");
    const $detail = root.querySelector<HTMLElement>("#spvDetail");
    const $select = root.querySelector<HTMLElement>("#spvStep-select");
    const $proofs = root.querySelector<HTMLElement>("#spvStep-proofs");
    const $build = root.querySelector<HTMLElement>("#spvStep-build");
    if (!$steps || !$select || !$proofs || !$build) return;

    if (step === "idle") {
      resetSpvUi();
      return;
    }

    $steps.hidden = false;
    for (const el of [$select, $proofs, $build]) {
      el.className = "sign-step";
    }

    if ($detail) {
      if (detail) {
        $detail.hidden = false;
        $detail.textContent = detail;
        $detail.classList.toggle("error", step === "error");
      } else {
        $detail.hidden = true;
        $detail.textContent = "";
        $detail.classList.remove("error");
      }
    }

    if (step === "select") {
      $select.classList.add("active");
    } else if (step === "proofs") {
      $select.classList.add("done");
      $proofs.classList.add("active");
    } else if (step === "build") {
      $select.classList.add("done");
      $proofs.classList.add("done");
      $build.classList.add("active");
    } else if (step === "done") {
      for (const el of [$select, $proofs, $build]) {
        el.classList.add("done");
      }
    } else if (step === "error" && failedAt) {
      if (failedAt === "select") {
        $select.classList.add("error");
      } else if (failedAt === "proofs") {
        $select.classList.add("done");
        $proofs.classList.add("error");
      } else {
        $select.classList.add("done");
        $proofs.classList.add("done");
        $build.classList.add("error");
      }
    }
  }

  function showSpvCompleteBanner(inputCount: number, heights: number[]): void {
    const $banner = root.querySelector<HTMLElement>("#spvCompleteBanner");
    if (!$banner) return;
    const uniqueHeights = [...new Set(heights)].sort((a, b) => a - b);
    const heightText = uniqueHeights.length === 1
      ? `block ${uniqueHeights[0]}`
      : `blocks ${uniqueHeights[0]}–${uniqueHeights[uniqueHeights.length - 1]}`;
    $banner.hidden = false;
    $banner.textContent =
      `✓ SPV verified — ${inputCount} confirmed input${inputCount === 1 ? "" : "s"} ` +
      `anchored at ${heightText}. The Pi re-verifies each Merkle proof before signing.`;
  }

  function switchSendQrTab(tab: "proposal" | "scan"): void {
    if (tab !== "scan" && sendQrTab === "scan") stopPw1Scan();
    sendQrTab = tab;
    const $proposal = root.querySelector<HTMLElement>("#sendQrTab-proposal");
    const $scan = root.querySelector<HTMLElement>("#sendQrTab-scan");
    if ($proposal) $proposal.hidden = tab !== "proposal";
    if ($scan) $scan.hidden = tab !== "scan";
    root.querySelectorAll<HTMLButtonElement>("[data-send-qr-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.sendQrTab === tab);
    });
  }

  /** Confirmed UTXOs only — mempool coins can't carry SPV proofs yet. */
  function spendableUtxos() {
    if (!wallet?.lastScan) return [];
    return confirmedUtxos(wallet.lastScan.utxos);
  }

  function applySendAmountSats(sats: number): void {
    const $amount = root.querySelector<HTMLInputElement>("#sendAmount");
    const $unit = root.querySelector<HTMLSelectElement>("#sendUnit");
    if (!$amount || !$unit) return;
    const unit = $unit.value as "sats" | "bsv" | "fiat";
    suppressSendAmountInput = true;
    if (unit === "sats") {
      $amount.value = String(sats);
    } else if (unit === "bsv") {
      $amount.value = (sats / SATS_PER_BSV).toFixed(8);
    } else if (bsvUsdPrice !== null && bsvUsdPrice > 0) {
      $amount.value = ((sats / SATS_PER_BSV) * bsvUsdPrice).toFixed(2);
    } else {
      $amount.value = String(sats);
    }
    suppressSendAmountInput = false;
    refreshFeeTierEstimates();
  }

  function onFeeTierChanged(): void {
    const tier = getSelectedFeeTier();
    const $customRow = root.querySelector<HTMLElement>("#feeCustomRow");
    if ($customRow) $customRow.hidden = tier !== "custom";
    if (sendAmountIsMax) onSendMax();
    else refreshFeeTierEstimates();
  }

  function onSendMax(): void {
    if (!wallet?.lastScan) return;
    const utxos = spendableUtxos();
    if (utxos.length === 0) return;
    const rate = getSelectedFeeRate();
    const maxSats = computeMaxSendSats(utxos, rate);
    if (maxSats <= 0) return;
    sendAmountIsMax = true;
    applySendAmountSats(maxSats);
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
    const unit = $unitSelect.value as "sats" | "bsv" | "fiat";

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
        $status.textContent = `${getFiatCurrency()} price unavailable — switch to sats or BSV`;
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
    const utxos = spendableUtxos();
    if (utxos.length === 0) {
      $status.classList.add("error");
      $status.textContent = noSpendableUtxosMessage(
        wallet.lastScan.utxos,
        formatSats,
      );
      return;
    }

    const rate = getSelectedFeeRate();
    let feeSats = 0;
    let changeSats = 0;
    try {
      const sel = selectUtxosGreedy(utxos, sats, rate);
      feeSats = sel.feeSats;
      changeSats = sel.changeSats;
    } catch (e) {
      if (e instanceof CoinSelectError) {
        $status.classList.add("error");
        $status.textContent = e.message;
        return;
      }
      const estimatedBytes = utxos.length * 148 + 2 * 34 + 10;
      feeSats = Math.ceil(estimatedBytes * rate / 1000);
      changeSats = 0;
    }

    sendStep = { step: "review", recipient, sats, feeRate: rate, feeSats, changeSats };
    showSendStep("review");
    renderReview();
  }

  async function loadFeeRates(): Promise<void> {
    if (!wallet) return;
    const $loading = root.querySelector<HTMLElement>("#feeLoading");
    const $select = root.querySelector<HTMLSelectElement>("#feeTierSelect");
    if (!woc) woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });

    if ($loading) {
      $loading.hidden = false;
      $loading.textContent = "Loading fee rates…";
    }
    if ($select) $select.disabled = true;

    try {
      feeRec = await fetchFeeRecommendation(woc);
    } catch {
      feeRec = null;
    }

    refreshFeeTierEstimates();
    onFeeTierChanged();
    if ($loading) $loading.hidden = true;
    if ($select) $select.disabled = false;
  }

  function refreshFeeTierEstimates(): void {
    if (!wallet) return;
    const economy = feeRec?.economy ?? DEFAULT_FEE_RATE_SATSKB;
    const standard = feeRec?.standard ?? DEFAULT_FEE_RATE_SATSKB;
    const priority = feeRec?.priority ?? DEFAULT_FEE_RATE_SATSKB * 5;

    const targetSats = amountSatsForFeeEstimate();
    const estSats = targetSats !== null && wallet.lastScan
      ? (rate: number) => {
          const utxos = spendableUtxos();
          if (utxos.length === 0) return null;
          try {
            return selectUtxosGreedy(utxos, targetSats, rate).feeSats;
          } catch {
            const bytes = utxos.length * 148 + 2 * 34 + 10;
            return Math.ceil(bytes * rate / 1000);
          }
        }
      : (_rate: number) => null;

    function fmtOptionLabel(name: string, rate: number): string {
      const fee = estSats(rate);
      const rateText = formatFeeRate(rate);
      if (fee !== null) {
        return `${name} — ~${fee.toLocaleString("en-US")} sats (${rateText})`;
      }
      return `${name} — ${rateText}`;
    }

    const $select = root.querySelector<HTMLSelectElement>("#feeTierSelect");
    if ($select) {
      const tier = $select.value;
      for (const [value, name, rate] of [
        ["economy", "Economy", economy],
        ["standard", "Standard", standard],
        ["priority", "Priority", priority],
      ] as const) {
        const opt = $select.querySelector<HTMLOptionElement>(`option[value="${value}"]`);
        if (opt) opt.textContent = fmtOptionLabel(name, rate);
      }
      const customOpt = $select.querySelector<HTMLOptionElement>('option[value="custom"]');
      if (customOpt) {
        const customRate = getSelectedFeeTier() === "custom"
          ? getSelectedFeeRate()
          : getDefaultCustomFeeRate();
        customOpt.textContent = tier === "custom"
          ? fmtOptionLabel("Custom", customRate)
          : "Custom…";
      }
      $select.value = tier;
    }
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
    resetSpvUi();

    sendBusy = true;
    $confirm.disabled = true;
    $confirm.textContent = "Building…";
    setSpvBuildStep("select", "Selecting confirmed UTXOs for SPV…");
    $status.textContent = "";

    let spvPhase: SpvBuildStep = "select";
    try {
      const utxos = spendableUtxos();
      if (utxos.length === 0) {
        throw new CoinSelectError(
          noSpendableUtxosMessage(wallet.lastScan!.utxos, formatSats),
        );
      }
      const selection = selectUtxosGreedy(
        utxos,
        sendStep.sats,
        sendStep.feeRate,
      );
      spvPhase = "proofs";
      setSpvBuildStep(
        "proofs",
        `Fetching and verifying SPV proofs for ${selection.inputs.length} input` +
          `${selection.inputs.length === 1 ? "" : "s"}…`,
      );

      if (!woc) woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });
      const proofs = [];
      const proofHeights: number[] = [];
      for (let i = 0; i < selection.inputs.length; i++) {
        const u = selection.inputs[i];
        setSpvBuildStep(
          "proofs",
          `SPV ${i + 1}/${selection.inputs.length}: ${u.txid.slice(0, 8)}… — ` +
            "fetching Merkle proof and block header…",
        );
        const proof = await fetchInputProof(woc, u.txid);
        proofHeights.push(proof.height);
        proofs.push({ utxo: u, proof });
        setSpvBuildStep(
          "proofs",
          `SPV ${i + 1}/${selection.inputs.length}: verified at block ${proof.height} ` +
            `(Merkle root matches header)`,
        );
      }

      spvPhase = "build";
      setSpvBuildStep("build", "Assembling unsigned proposal with BEEF proofs…");

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

      setSpvBuildStep("done", "All SPV checks passed — proposal ready for the Pi.");
      showSpvCompleteBanner(selection.inputs.length, proofHeights);
      $status.textContent = "";

      showSendStep("qr");
      sendStep = { step: "qr" };
      resetBroadcastWidget();
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
      setSpvBuildStep("error", msg, spvPhase === "build" ? "build" : spvPhase);
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
    const interval = PW1_QR_FRAME_MS;
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

  function setPasteSignedTxStatus(msg: string, isError = false): void {
    const $status = root.querySelector<HTMLElement>("#pasteSignedTxStatus");
    if (!$status) return;
    $status.textContent = msg;
    $status.classList.toggle("error", isError);
  }

  function onPasteSignedTxClear(): void {
    const $paste = root.querySelector<HTMLTextAreaElement>("#pasteSignedTx");
    if ($paste) {
      $paste.value = "";
      $paste.focus();
    }
    setPasteSignedTxStatus("");
  }

  async function onPasteSignedTxDecode(): Promise<void> {
    const $paste = root.querySelector<HTMLTextAreaElement>("#pasteSignedTx");
    if (!$paste) return;
    const decoded = decodeHexPasteToBytes($paste.value);
    if (!decoded.ok) {
      setPasteSignedTxStatus(decoded.error, true);
      return;
    }
    setPasteSignedTxStatus(`decoding ${decoded.bytes.length} bytes…`);
    stopPw1Scan();
    await onSignedTxReceived(decoded.bytes);
    const dropped =
      decoded.parsed.droppedLabeled.length + decoded.parsed.droppedOther.length;
    const noteParts = [`decoded ${decoded.bytes.length} bytes`];
    if (dropped > 0) noteParts.push(`ignored ${dropped} non-hex line(s)`);
    setPasteSignedTxStatus(noteParts.join(" — "));
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

  function showBroadcastWidget(): void {
    const $broadcast = root.querySelector<HTMLElement>("#broadcastWidget");
    const $pw1Actions = root.querySelector<HTMLElement>("#pw1ScanActions");
    if ($broadcast) $broadcast.hidden = false;
    if ($pw1Actions) $pw1Actions.hidden = true;
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
      showBroadcastWidget();
      switchSendQrTab("scan");
      return;
    }

    if (env.kind !== KIND_SIGNED) {
      if ($info) $info.textContent = `unexpected envelope type: ${env.kind}`;
      showBroadcastWidget();
      switchSendQrTab("scan");
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
      showBroadcastWidget();
      switchSendQrTab("scan");
      return;
    }

    if ($info) {
      $info.innerHTML = `Ready to broadcast<br><code class="mono" style="font-size:0.75rem;word-break:break-all">${txid}</code>${sizeBytes ? `<br><span class="muted-line">${sizeBytes} bytes</span>` : ""}`;
    }
    if ($broadcastStatus) $broadcastStatus.textContent = "";
    showBroadcastWidget();
    switchSendQrTab("scan");
    hideBroadcastDone();

    const $btn = root.querySelector<HTMLButtonElement>("#broadcastBtn");
    if ($btn) {
      $btn.dataset.signedHex = rawHex;
      $btn.dataset.txid = txid;
      $btn.disabled = false;
      $btn.textContent = "Broadcast";
    }
  }

  function hideBroadcastDone(): void {
    const $done = root.querySelector<HTMLButtonElement>("#broadcastDone");
    if ($done) $done.hidden = true;
    const $explorer = root.querySelector<HTMLAnchorElement>("#broadcastExplorer");
    if ($explorer) $explorer.hidden = true;
  }

  function showBroadcastDone(explorerUrl?: string): void {
    const $done = root.querySelector<HTMLButtonElement>("#broadcastDone");
    if ($done) $done.hidden = false;
    const $explorer = root.querySelector<HTMLAnchorElement>("#broadcastExplorer");
    if ($explorer) {
      if (explorerUrl) {
        $explorer.href = explorerUrl;
        $explorer.hidden = false;
      } else {
        $explorer.hidden = true;
      }
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
    hideBroadcastDone();
    $status.classList.remove("error", "success");
    $status.textContent = "";

    try {
      if (!woc) woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });
      const txid = $btn.dataset.txid ?? "";
      await woc.broadcastRaw(rawHex, txid || undefined);
      const explorer = wocExplorerTxUrl(txid, wallet.network);
      const $panel = root.querySelector<HTMLElement>("#broadcastWidget");
      const $info = root.querySelector<HTMLElement>("#broadcastInfo");
      if ($panel) $panel.classList.add("success");
      if ($info) {
        $info.innerHTML =
          `<strong class="broadcast-success-head">Transaction sent</strong><br>` +
          `<code class="mono" style="font-size:0.75rem;word-break:break-all">${escapeHtml(txid)}</code>`;
      }
      $status.classList.remove("error");
      $status.classList.add("success");
      $status.textContent =
        "Accepted by the network. It may take a few minutes to confirm on-chain.";
      delete $btn.dataset.signedHex;
      $btn.hidden = true;
      showBroadcastDone(explorer);
    } catch (e) {
      const $panel = root.querySelector<HTMLElement>("#broadcastWidget");
      if ($panel) $panel.classList.remove("success");
      $status.classList.add("error");
      $status.classList.remove("success");
      let msg: string;
      if (e instanceof WocError) {
        msg = e.message;
        if (e.bodySnippet) msg += `\nWoC said: ${e.bodySnippet}`;
      } else {
        msg = (e as Error).message;
      }
      $status.textContent = `broadcast failed: ${msg}`;
      $btn.disabled = false;
      $btn.hidden = false;
      $btn.textContent = "Retry broadcast";
      hideBroadcastDone();
    }
  }

  async function onBroadcastDone(): Promise<void> {
    resetSendCard();
    switchTab("balance");
    await onRefreshBalance();
  }

  function resetBroadcastWidget(): void {
    const $broadcast = root.querySelector<HTMLElement>("#broadcastWidget");
    const $pw1Actions = root.querySelector<HTMLElement>("#pw1ScanActions");
    if ($broadcast) {
      $broadcast.hidden = true;
      $broadcast.classList.remove("success");
    }
    if ($pw1Actions) $pw1Actions.hidden = false;
    const $broadcastBtn = root.querySelector<HTMLButtonElement>("#broadcastBtn");
    if ($broadcastBtn) {
      $broadcastBtn.hidden = false;
      $broadcastBtn.disabled = false;
      $broadcastBtn.textContent = "Broadcast";
      delete $broadcastBtn.dataset.signedHex;
      delete $broadcastBtn.dataset.txid;
    }
    hideBroadcastDone();
    const $broadcastStatus = root.querySelector<HTMLElement>("#broadcastStatus");
    if ($broadcastStatus) {
      $broadcastStatus.classList.remove("error", "success");
      $broadcastStatus.textContent = "";
    }
    const $broadcastInfo = root.querySelector<HTMLElement>("#broadcastInfo");
    if ($broadcastInfo) $broadcastInfo.textContent = "";
    const $explorer = root.querySelector<HTMLAnchorElement>("#broadcastExplorer");
    if ($explorer) $explorer.hidden = true;
  }

  function resetSendCard(): void {
    stopProposalAnimation();
    stopPw1Scan();
    proposalFrames = null;
    proposalFrameIdx = 0;
    sendStep = { step: "form" };
    sendAmountIsMax = false;
    showSendStep("form");
    resetBroadcastWidget();
    resetSpvUi();
    const $status = root.querySelector<HTMLElement>("#sendFormStatus");
    if ($status) {
      $status.classList.remove("error");
      $status.textContent = "";
    }
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
    const $steps = root.querySelector<HTMLElement>("#receiveVerifySteps");

    $path.textContent = `${wallet.path} / ${derived.subPath}`;
    $addr.textContent = derived.address;
    $prev.disabled = idx === 0;
    const $windowDesc = root.querySelector<HTMLElement>("#receiveWindowDesc");
    if ($windowDesc) $windowDesc.textContent = `m/0/${idx}`;
    $status.textContent =
      idx === 0 ? "first address (index 0)" : `address #${idx} on receive branch`;

    if ($steps) {
      $steps.innerHTML = idx === 0
        ? "On the Pi: open <strong>Show deposit address</strong> — it starts at address #0."
        : `On the Pi: open <strong>Show deposit address</strong> and press RIGHT ` +
          `<strong>${idx} time${idx === 1 ? "" : "s"}</strong> to reach address #${idx}.`;
    }

    try {
      const qrSize = receiveQrLarge ? RECEIVE_QR_SIZE_LARGE : RECEIVE_QR_SIZE_DEFAULT;
      $canvas.width = qrSize;
      $canvas.height = qrSize;
      await QRCode.toCanvas($canvas, derived.address, {
        margin: 1, width: qrSize, errorCorrectionLevel: "M",
      });
      const $toggle = root.querySelector<HTMLButtonElement>("#receiveQrSizeToggle");
      if ($toggle) {
        $toggle.textContent = receiveQrLarge ? "Standard QR" : "Larger QR";
      }
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

  function receiveAdvanceWarning(nextIndex: number): string | null {
    if (!wallet || nextIndex <= wallet.nextReceiveIndex) return null;
    if (!wallet.lastScan) {
      return "Refresh Balance first so the companion knows which receive addresses are in use.";
    }
    const recommended = wallet.lastScan.lastReceiveUsed + 1;
    if (nextIndex <= recommended) return null;
    const lastUsed = wallet.lastScan.lastReceiveUsed;
    if (lastUsed < 0) {
      return (
        `Address #${nextIndex} is ahead of the scanned range. ` +
        `Refresh Balance if you are not sure this address is unused.`
      );
    }
    return (
      `Address #${nextIndex} is beyond the last used receive index (#${lastUsed}). ` +
      `Only advance if you have already shared address #${nextIndex - 1} ` +
      `or no longer expect payments there.`
    );
  }

  function showReceiveAdvanceConfirm(message: string, targetIndex: number): void {
    receiveAdvancePending = targetIndex;
    const $strip = root.querySelector<HTMLElement>("#receiveAdvanceConfirm");
    const $msg = root.querySelector<HTMLElement>("#receiveAdvanceConfirmMsg");
    if ($msg) $msg.textContent = message;
    if ($strip) $strip.hidden = false;
  }

  function hideReceiveAdvanceConfirm(): void {
    receiveAdvancePending = null;
    const $strip = root.querySelector<HTMLElement>("#receiveAdvanceConfirm");
    if ($strip) $strip.hidden = true;
  }

  async function applyReceiveIndex(next: number): Promise<void> {
    if (!wallet) return;
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

  async function shiftIndex(delta: number): Promise<void> {
    if (!wallet) return;
    const next = wallet.nextReceiveIndex + delta;
    if (next < 0) return;
    hideReceiveAdvanceConfirm();
    if (delta > 0) {
      const warning = receiveAdvanceWarning(next);
      if (warning) {
        showReceiveAdvanceConfirm(warning, next);
        return;
      }
    }
    await applyReceiveIndex(next);
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
    const interval = PW1_QR_FRAME_MS;
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
