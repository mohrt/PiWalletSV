import { DOCS_BASE_URL } from "../../lib/config.js";
import { DEFAULT_FEE_RATE_SATSKB } from "../../lib/fee.js";
import { renderHeader } from "../nav.js";
import {
  getDefaultCustomFeeRate,
  getDefaultFeeTier,
  getFiatCurrency,
} from "../settings-page.js";
import { escapeHtml } from "./shared.js";
import type { DisplayUnit, Tab, WalletDetailWallet } from "./types.js";

export function renderWalletDetailShell(
  wallet: WalletDetailWallet,
  activeTab: Tab,
  displayUnit: DisplayUnit,
): string {
  const netBadge =
    wallet.network === "test"
      ? ' <span class="testnet-badge" title="This wallet is on BSV testnet (TBSV).">TESTNET</span>'
      : "";

  const tabBtn = (tab: Tab, label: string): string => {
    const sel = activeTab === tab;
    return (
      `<button role="tab" id="tab-btn-${tab}" data-tab="${tab}" ` +
      `class="${sel ? "active" : ""}" aria-controls="tab-${tab}" ` +
      `aria-selected="${sel ? "true" : "false"}" tabindex="${sel ? "0" : "-1"}">` +
      `${label}</button>`
    );
  };

  return `
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

        <nav class="tab-nav" role="tablist" aria-label="Wallet sections">
          <div class="tab-nav-tabs">
            ${tabBtn("balance", "Balance")}
            ${tabBtn("send", "Send")}
            ${tabBtn("receive", "Receive")}
            ${tabBtn("history", "History")}
            ${tabBtn("advanced", "Advanced")}
          </div>
          <select id="unitSelect" class="tab-unit-select" aria-label="Display unit">
            <option value="sats"${displayUnit === "sats" ? " selected" : ""}>sats</option>
            <option value="bsv"${displayUnit === "bsv" ? " selected" : ""}>BSV</option>
            <option value="fiat"${displayUnit === "fiat" ? " selected" : ""}>${getFiatCurrency()}</option>
          </select>
        </nav>

        <!-- Balance tab -->
        <section id="tab-balance" class="card tab-panel${activeTab === "balance" ? " active" : ""}" role="tabpanel" aria-labelledby="tab-btn-balance" tabindex="${activeTab === "balance" ? "0" : "-1"}">
          <div class="balance-hero-row">
            <div class="balance-hero">
              <button id="balanceToggle" class="balance-hero-value" type="button"
                title="Tap to cycle sats, BSV, or ${getFiatCurrency()}"
                aria-label="Cycle balance display unit">
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
          <p class="muted-line balance-status" id="balanceStatus" aria-live="polite"></p>
          <details id="utxoDetails" class="panel-details" hidden>
            <summary><span class="panel-details-label">UTXOs (<span id="utxoCount">0</span>)</span></summary>
            <div class="panel-details-body">
              <ul id="utxoList" class="utxo-list"></ul>
            </div>
          </details>
        </section>

        <!-- Send tab -->
        <section id="tab-send" class="card tab-panel${activeTab === "send" ? " active" : ""}" role="tabpanel" aria-labelledby="tab-btn-send" tabindex="${activeTab === "send" ? "0" : "-1"}">
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
                <button id="scanAddress" type="button" class="icon-btn"
                  title="Scan address QR" aria-label="Scan address QR">
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
                  const sel = (v: string) => (v === defTier ? " selected" : "");
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
            <p class="muted-line" id="sendFormStatus" aria-live="polite"></p>
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
            <p class="muted-line" id="spvDetail" hidden aria-live="polite"></p>
            <p class="muted-line" id="reviewStatus" aria-live="polite"></p>
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
              <p id="proposalQrHint" class="muted-line">Point the Pi camera at this animated QR.</p>
              <canvas id="proposalQr" width="320" height="320"></canvas>
              <p class="muted-line">
                Frame <span id="proposalFrameIdx">0</span> /
                <span id="proposalFrameCount">0</span> ·
                <span id="proposalByteCount">0</span> bytes
              </p>
              <div class="actions pw1-qr-controls">
                <button id="proposalPrev" type="button" hidden>Previous</button>
                <button id="proposalNext" type="button" hidden>Next</button>
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
                <p id="broadcastStatus" class="send-broadcast-message muted-line" aria-live="polite"></p>
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
        <section id="tab-receive" class="card tab-panel${activeTab === "receive" ? " active" : ""}" role="tabpanel" aria-labelledby="tab-btn-receive" tabindex="${activeTab === "receive" ? "0" : "-1"}">
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
        <section id="tab-history" class="card tab-panel${activeTab === "history" ? " active" : ""}" role="tabpanel" aria-labelledby="tab-btn-history" tabindex="${activeTab === "history" ? "0" : "-1"}">
          <div class="history-header">
            <h2>Transaction history</h2>
            <button id="refreshHistory" class="primary" type="button">Refresh</button>
          </div>
          <p class="muted-line" id="historyStatus" aria-live="polite"></p>
          <div id="historyEmpty" class="empty-state" hidden>
            <p id="historyEmptyTitle">No transaction history yet.</p>
            <p class="muted-line" id="historyEmptyHint">Click Refresh to fetch history from Bitails.</p>
            <button id="scanBalanceForHistory" class="primary" type="button" hidden>
              Scan balance first
            </button>
          </div>
          <ul id="historyList" class="history-list"></ul>
          <div class="history-footer">
            <button id="historyLoadMore" type="button" hidden>Load more</button>
          </div>
        </section>

        <!-- Advanced tab -->
        <section id="tab-advanced" class="card tab-panel${activeTab === "advanced" ? " active" : ""}" role="tabpanel" aria-labelledby="tab-btn-advanced" tabindex="${activeTab === "advanced" ? "0" : "-1"}">
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
            <p id="exportQrHint" class="muted-line">
              Point another companion at this animated QR.
            </p>
            <p class="muted-line">
              Scan from <a href="#/scan">+ Add wallet</a> on the other device.
            </p>
            <p class="muted-line">
              Frame <span id="exportFrameIdx">0</span> /
              <span id="exportFrameCount">0</span>
            </p>
            <div class="actions pw1-qr-controls">
              <button id="exportPrev" type="button" hidden>Previous</button>
              <button id="exportNext" type="button" hidden>Next</button>
              <button id="exportToggle" type="button" class="primary">Pause</button>
              <button id="exportHide" type="button">Hide</button>
            </div>
          </div>
          <p class="muted-line">
            To move all wallets and companion settings to another device, use
            <a href="#/settings">Backup &amp; migration</a> in Settings.
          </p>

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
}
