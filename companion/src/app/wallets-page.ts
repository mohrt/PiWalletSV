/**
 * Paired-wallets list page (`#/wallets`).
 *
 * Shows every wallet the companion has stored locally (IndexedDB).
 * Each card shows: label, network badge, last-known balance, fingerprint,
 * derivation path, and paired date — plus inline actions (rename, remove).
 *
 * Rename uses an inline edit field instead of window.prompt.
 * Remove uses an inline confirmation strip instead of window.confirm.
 */
import { DOCS_BASE_URL } from "../lib/config.js";
import {
  type WalletRecord,
  listWallets,
  removeWallet,
  updateLabel,
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
  // Track which wallet card is currently in rename/remove mode so we
  // can cancel it if the user opens another action.
  let activeInlineAction: { id: string; type: "rename" | "remove" } | null = null;

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
          <a class="primary-link" href="#/wallets/${w.id}">Open</a>
          <button class="rename" data-id="${w.id}" type="button">Rename</button>
          <button class="copy-xpub" data-id="${w.id}" type="button">Copy xpub</button>
          <button class="remove" data-id="${w.id}" type="button">Remove</button>
        </div>

        <!-- Inline rename strip (hidden by default) -->
        <div class="inline-rename" id="rename-${w.id}" hidden>
          <input type="text" class="rename-input" value="${escapeHtml(w.label)}"
            maxlength="64" autocorrect="off" spellcheck="false" />
          <div class="actions">
            <button class="rename-save primary" data-id="${w.id}" type="button">Save</button>
            <button class="rename-cancel" data-id="${w.id}" type="button">Cancel</button>
          </div>
        </div>

        <!-- Inline remove confirmation strip (hidden by default) -->
        <div class="inline-remove" id="remove-${w.id}" hidden>
          <p class="remove-confirm-msg">
            Remove <strong>${escapeHtml(w.label)}</strong>?
            <span class="muted-line">The Pi side is unaffected.</span>
          </p>
          <div class="actions">
            <button class="remove-confirm primary danger" data-id="${w.id}" type="button">Remove</button>
            <button class="remove-cancel" data-id="${w.id}" type="button">Cancel</button>
          </div>
        </div>
      `;
      $list.appendChild(li);
    }

    // Wire actions
    $list.querySelectorAll<HTMLButtonElement>("button.rename").forEach((b) => {
      b.addEventListener("click", () => onRenameOpen(b.dataset.id!));
    });
    $list.querySelectorAll<HTMLButtonElement>("button.rename-save").forEach((b) => {
      b.addEventListener("click", () => void onRenameSave(b.dataset.id!, wallets));
    });
    $list.querySelectorAll<HTMLButtonElement>("button.rename-cancel").forEach((b) => {
      b.addEventListener("click", () => onRenameCancel(b.dataset.id!));
    });
    $list.querySelectorAll<HTMLButtonElement>("button.copy-xpub").forEach((b) => {
      b.addEventListener("click", () => void onCopy(b, b.dataset.id!, wallets));
    });
    $list.querySelectorAll<HTMLButtonElement>("button.remove").forEach((b) => {
      b.addEventListener("click", () => onRemoveOpen(b.dataset.id!));
    });
    $list.querySelectorAll<HTMLButtonElement>("button.remove-confirm").forEach((b) => {
      b.addEventListener("click", () => void onRemoveConfirm(b.dataset.id!));
    });
    $list.querySelectorAll<HTMLButtonElement>("button.remove-cancel").forEach((b) => {
      b.addEventListener("click", () => onRemoveCancel(b.dataset.id!));
    });
  }

  function closeActiveInline(): void {
    if (!activeInlineAction) return;
    const { id, type } = activeInlineAction;
    const strip = root.querySelector<HTMLElement>(`#${type}-${id}`);
    if (strip) strip.hidden = true;
    activeInlineAction = null;
  }

  function onRenameOpen(id: string): void {
    closeActiveInline();
    const strip = root.querySelector<HTMLElement>(`#rename-${id}`);
    if (!strip) return;
    strip.hidden = false;
    strip.querySelector<HTMLInputElement>(".rename-input")?.focus();
    activeInlineAction = { id, type: "rename" };
  }

  function onRenameCancel(id: string): void {
    const strip = root.querySelector<HTMLElement>(`#rename-${id}`);
    if (strip) strip.hidden = true;
    if (activeInlineAction?.id === id) activeInlineAction = null;
  }

  async function onRenameSave(id: string, wallets: WalletRecord[]): Promise<void> {
    const strip = root.querySelector<HTMLElement>(`#rename-${id}`);
    const input = strip?.querySelector<HTMLInputElement>(".rename-input");
    if (!input) return;
    const trimmed = input.value.trim();
    const w = wallets.find((x) => x.id === id);
    if (!trimmed || trimmed === w?.label) {
      onRenameCancel(id);
      return;
    }
    try {
      await updateLabel(id, trimmed);
    } catch (e) {
      $status.classList.add("error");
      $status.textContent = `rename failed: ${(e as Error).message}`;
      return;
    }
    await render();
  }

  function onRemoveOpen(id: string): void {
    closeActiveInline();
    const strip = root.querySelector<HTMLElement>(`#remove-${id}`);
    if (!strip) return;
    strip.hidden = false;
    activeInlineAction = { id, type: "remove" };
  }

  function onRemoveCancel(id: string): void {
    const strip = root.querySelector<HTMLElement>(`#remove-${id}`);
    if (strip) strip.hidden = true;
    if (activeInlineAction?.id === id) activeInlineAction = null;
  }

  async function onRemoveConfirm(id: string): Promise<void> {
    try {
      await removeWallet(id);
    } catch (e) {
      $status.classList.add("error");
      $status.textContent = `remove failed: ${(e as Error).message}`;
      return;
    }
    await render();
  }

  async function onCopy(
    btn: HTMLButtonElement,
    id: string,
    wallets: WalletRecord[],
  ): Promise<void> {
    const w = wallets.find((x) => x.id === id);
    if (!w) return;
    try {
      await navigator.clipboard.writeText(w.xpub);
      const orig = btn.textContent;
      btn.textContent = "copied!";
      setTimeout(() => { btn.textContent = orig; }, 1200);
    } catch (e) {
      $status.classList.add("error");
      $status.textContent = `clipboard error: ${(e as Error).message}`;
    }
  }

  void render();

  return () => { cancelled = true; };
}
