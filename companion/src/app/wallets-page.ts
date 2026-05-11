/**
 * Paired-wallets list page (`#/wallets`).
 *
 * Shows every wallet the companion has stored locally (IndexedDB). Each
 * row exposes the public metadata only — `label`, `fingerprint`, `path`,
 * `addedAt` plus the full `xpub` (truncated for readability) — and lets
 * the user rename or remove an entry. The Pi side is unaffected; this
 * only manages the companion's local registry.
 */
import {
  type WalletRecord,
  listWallets,
  removeWallet,
  updateLabel,
} from "../lib/wallets.js";

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function shortenXpub(xpub: string): string {
  if (xpub.length <= 32) return xpub;
  return `${xpub.slice(0, 16)}…${xpub.slice(-12)}`;
}

export function mountWalletsPage(root: HTMLElement): () => void {
  root.innerHTML = `
    <main class="page">
      <header class="page-header">
        <h1>Paired wallets<span class="brand"> · PiWalletSV companion</span></h1>
        <nav>
          <a href="#/encode">Encode</a>
          <a href="#/scan">Scan</a>
          <a href="#/loop">Loop</a>
          <a href="#/wallets" class="active">Wallets</a>
        </nav>
      </header>

      <section class="card">
        <p class="muted-line" id="walletStatus"></p>
        <p class="muted-line" id="emptyState" hidden>
          No wallets paired yet. Scan an <code>xpub_export</code> on the
          <a href="#/scan">Scan</a> page to pair one.
        </p>
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
    $status.textContent = wallets.length === 0
      ? ""
      : `${wallets.length} paired wallet${wallets.length === 1 ? "" : "s"}.`;

    $list.innerHTML = "";
    if (wallets.length === 0) {
      $empty.hidden = false;
      return;
    }
    $empty.hidden = true;

    for (const w of wallets) {
      const li = document.createElement("li");
      li.className = "wallet-row";
      li.innerHTML = `
        <div class="wallet-meta">
          <strong class="wallet-label">${escapeHtml(w.label)}</strong>
          <code class="wallet-fp" title="fingerprint">${w.fingerprint}</code>
          <span class="muted-line">${escapeHtml(w.path)}</span>
        </div>
        <div class="wallet-xpub muted-line"
             title="${escapeHtml(w.xpub)}">${escapeHtml(shortenXpub(w.xpub))}</div>
        <div class="wallet-meta-2 muted-line">
          paired ${new Date(w.addedAt).toLocaleString()}
        </div>
        <div class="actions">
          <a class="primary-link" href="#/wallets/${w.id}">Open</a>
          <button class="rename" data-id="${w.id}" type="button">Rename</button>
          <button class="copy" data-id="${w.id}" type="button">Copy xpub</button>
          <button class="remove" data-id="${w.id}" type="button">Remove</button>
        </div>
      `;
      $list.appendChild(li);
    }

    $list.querySelectorAll<HTMLButtonElement>("button.rename").forEach((b) => {
      b.addEventListener("click", () => void onRename(b.dataset.id!, wallets));
    });
    $list.querySelectorAll<HTMLButtonElement>("button.copy").forEach((b) => {
      b.addEventListener("click", () => void onCopy(b, b.dataset.id!, wallets));
    });
    $list.querySelectorAll<HTMLButtonElement>("button.remove").forEach((b) => {
      b.addEventListener("click", () => void onRemove(b.dataset.id!, wallets));
    });
  }

  async function onRename(id: string, wallets: WalletRecord[]): Promise<void> {
    const w = wallets.find((x) => x.id === id);
    if (!w) return;
    const next = window.prompt("New label:", w.label);
    if (next === null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === w.label) return;
    try {
      await updateLabel(id, trimmed);
    } catch (e) {
      $status.classList.add("error");
      $status.textContent = `rename failed: ${(e as Error).message}`;
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
      setTimeout(() => {
        btn.textContent = orig;
      }, 1200);
    } catch (e) {
      $status.classList.add("error");
      $status.textContent = `clipboard error: ${(e as Error).message}`;
    }
  }

  async function onRemove(id: string, wallets: WalletRecord[]): Promise<void> {
    const w = wallets.find((x) => x.id === id);
    if (!w) return;
    const ok = window.confirm(
      `Remove "${w.label}" (${w.fingerprint})?\nThe Pi side is unaffected.`,
    );
    if (!ok) return;
    try {
      await removeWallet(id);
    } catch (e) {
      $status.classList.add("error");
      $status.textContent = `remove failed: ${(e as Error).message}`;
      return;
    }
    await render();
  }

  void render();

  return () => {
    cancelled = true;
  };
}
