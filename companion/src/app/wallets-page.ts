/**
 * Paired-wallets list page (`#/wallets`).
 *
 * Shows every wallet the companion has stored locally (IndexedDB).
 * Each card shows: label, network badge, last-known balance, fingerprint,
 * derivation path, and paired date.
 *
 * Primary actions are Send and Receive (deep-link into wallet detail tabs).
 * Rename and Remove live in the wallet's Advanced tab.
 */
import { DOCS_BASE_URL } from "../lib/config.js";
import {
  type WalletRecord,
  listWallets,
  withDefaults,
} from "../lib/wallets.js";
import { renderHeader } from "./nav.js";

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

export function mountWalletsPage(root: HTMLElement): () => void {
  root.innerHTML = `
    <main class="page">
      ${renderHeader("Wallets", "wallets")}

      <section class="card">
        <p class="muted-line" id="walletStatus"></p>
        <div id="emptyState" class="empty-state" hidden>
          <h2>No wallets paired yet</h2>
          <p>
            On the Pi, navigate to a wallet and choose
            <strong>Pair with companion</strong> — the bonnet animates
            a multipart QR with your wallet's public xpub.
          </p>
          <p>
            Then click <a class="primary-link" href="#/scan">Scan QR</a>
            and point your camera at the Pi to complete the pairing.
          </p>
          <p class="muted-line">
            Pairing only ever transmits public material. Your seed phrase
            never leaves the Pi.
            <a href="${DOCS_BASE_URL}/security/" target="_blank"
               rel="noopener noreferrer">Why is this safe?</a>
          </p>
          <div class="actions">
            <a class="primary-link" href="#/scan">Scan a wallet xpub</a>
          </div>
        </div>
        <ul id="walletsList" class="wallets-list"></ul>
      </section>
    </main>
  `;

  const $list = root.querySelector<HTMLUListElement>("#walletsList")!;
  const $empty = root.querySelector<HTMLParagraphElement>("#emptyState")!;
  const $status = root.querySelector<HTMLParagraphElement>("#walletStatus")!;

  let cancelled = false;

  async function render(): Promise<void> {
    let wallets: WalletRecord[];
    try {
      wallets = await listWallets();
    } catch (e) {
      if (cancelled) return;
      $status.classList.add("error");
      $status.textContent = `wallet store error: ${(e as Error).message}`;
      return;
    }
    if (cancelled) return;
    $status.classList.remove("error");
    $status.textContent =
      wallets.length === 0
        ? ""
        : `${wallets.length} paired wallet${wallets.length === 1 ? "" : "s"}`;

    $list.innerHTML = "";
    if (wallets.length === 0) {
      $empty.hidden = false;
      return;
    }
    $empty.hidden = true;

    for (const w of wallets) {
      const wd = withDefaults(w);
      const li = document.createElement("li");
      li.className = "wallet-row";
      li.dataset.id = w.id;

      const netBadge =
        wd.network === "test"
          ? `<span class="testnet-badge" title="BSV testnet">TESTNET</span>`
          : `<span class="mainnet-badge" title="BSV mainnet">MAINNET</span>`;

      const balanceHtml = w.lastScan
        ? `<span class="wallet-balance">${formatSats(w.lastScan.totalSats)}</span>`
        : `<span class="wallet-balance muted-line">—</span>`;

      li.innerHTML = `
        <div class="wallet-card-top">
          <div class="wallet-card-identity">
            <strong class="wallet-label">${escapeHtml(w.label)}</strong>
            ${netBadge}
            ${balanceHtml}
          </div>
          <div class="wallet-card-meta muted-line">
            <code title="fingerprint">${w.fingerprint}</code> ·
            ${escapeHtml(w.path)} ·
            paired ${new Date(w.addedAt).toLocaleDateString()}
          </div>
        </div>

        <div class="wallet-card-actions actions">
          <a class="primary-link" href="#/wallets/${w.id}/send">Send</a>
          <a class="primary-link" href="#/wallets/${w.id}/receive">Receive</a>
          <a class="primary-link" href="#/wallets/${w.id}">More…</a>
        </div>
      `;
      $list.appendChild(li);
    }

  }

  void render();

  return () => { cancelled = true; };
}
