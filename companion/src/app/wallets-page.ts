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
import { DOCS_BASE_URL, PRICE_CACHE_TTL_MS } from "../lib/config.js";
import {
  type WalletRecord,
  listWallets,
  setLastScan,
  withDefaults,
} from "../lib/wallets.js";
import { renderHeader } from "./nav.js";
import { WocClient, effectiveWocBase } from "../lib/woc.js";
import { getFiatCurrency } from "./settings-page.js";
import { scanWalletUtxos } from "../lib/utxo.js";

const SATS_PER_BSV = 100_000_000;
const LIST_UNIT_KEY = "piwallet.listUnit";

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function mountWalletsPage(root: HTMLElement): () => void {
  type ListUnit = "sats" | "bsv" | "fiat";
  let listUnit: ListUnit =
    (localStorage.getItem(LIST_UNIT_KEY) as ListUnit) ?? "sats";
  let bsvUsdPrice: number | null = null;
  let priceFetchedAt = 0;
  let cachedWallets: WalletRecord[] = [];
  let cancelled = false;

  root.innerHTML = `
    <main class="page">
      ${renderHeader("Wallets", "wallets")}

      <div class="wallets-toolbar">
        <p class="muted-line" id="walletStatus"></p>
        <div class="wallets-toolbar-right">
          <select id="listUnitSelect" class="list-unit-select">
            <option value="sats"${listUnit === "sats" ? " selected" : ""}>sats</option>
            <option value="bsv"${listUnit === "bsv" ? " selected" : ""}>BSV</option>
            <option value="fiat"${listUnit === "fiat" ? " selected" : ""}>${getFiatCurrency()}</option>
          </select>
          <a class="primary-link" href="#/scan">+ Add wallet</a>
        </div>
      </div>

      <section class="card">
        <div id="emptyState" class="empty-state" hidden>
          <h2>No wallets yet</h2>
          <p>
            On the Pi, navigate to a wallet and choose
            <strong>Pair with companion</strong> — the bonnet shows an
            animated QR with your wallet's public key.
          </p>
          <p class="muted-line">
            Your seed phrase never leaves the Pi.
            <a href="${DOCS_BASE_URL}/security/" target="_blank"
               rel="noopener noreferrer">Why is this safe?</a>
          </p>
        </div>
        <ul id="walletsList" class="wallets-list"></ul>
      </section>
    </main>
  `;

  const $list   = root.querySelector<HTMLUListElement>("#walletsList")!;
  const $empty  = root.querySelector<HTMLElement>("#emptyState")!;
  const $status = root.querySelector<HTMLElement>("#walletStatus")!;
  const $unit   = root.querySelector<HTMLSelectElement>("#listUnitSelect")!;

  // ── price fetch ────────────────────────────────────────────────────────────
  async function fetchPrice(): Promise<void> {
    const now = Date.now();
    if (bsvUsdPrice !== null && now - priceFetchedAt < PRICE_CACHE_TTL_MS) return;
    try {
      const woc = new WocClient({ baseUrl: effectiveWocBase("main") });
      const resp = await fetch(`${woc.baseUrl}/exchangerate`, {
        headers: { Accept: "application/json" },
      });
      if (!resp.ok) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = (await resp.json()) as any;
      const rate = data?.rate ?? data?.price ?? data?.USD ?? null;
      if (typeof rate === "number" && rate > 0) {
        bsvUsdPrice = rate;
        priceFetchedAt = now;
      }
    } catch { /* silently ignore */ }
  }

  // ── balance formatting ─────────────────────────────────────────────────────
  function formatBalance(totalSats: number): string {
    if (listUnit === "bsv") {
      return `${(totalSats / SATS_PER_BSV).toFixed(8)} BSV`;
    }
    if (listUnit === "fiat") {
      if (bsvUsdPrice === null) return "—";
      const val = (totalSats / SATS_PER_BSV) * bsvUsdPrice;
      return `${getFiatCurrency()} ${val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `${totalSats.toLocaleString("en-US")} sats`;
  }

  // ── render list ────────────────────────────────────────────────────────────
  function renderList(wallets: WalletRecord[]): void {
    $list.innerHTML = "";
    if (wallets.length === 0) { $empty.hidden = false; return; }
    $empty.hidden = true;

    for (const w of wallets) {
      const wd = withDefaults(w);
      const li = document.createElement("li");
      li.className = "wallet-row";
      li.dataset.id = w.id;

      const netBadge = wd.network === "test"
        ? `<span class="testnet-badge" title="BSV testnet">TESTNET</span>`
        : `<span class="mainnet-badge" title="BSV mainnet">MAINNET</span>`;

      const balanceHtml = w.lastScan
        ? `<span class="wallet-balance">Balance: ${escapeHtml(formatBalance(w.lastScan.totalSats))}</span>`
        : `<span class="wallet-balance muted-line">Balance: —</span>`;
      const refreshBtn = `<button class="wallet-refresh-btn" data-refresh="${w.id}" title="Refresh balance" aria-label="Refresh balance">↻</button>`;

      li.innerHTML = `
        <div class="wallet-card-top">
          <div class="wallet-card-top-row">
            <div class="wallet-card-identity">
              <strong class="wallet-label">${escapeHtml(w.label)}</strong>
              ${netBadge}
            </div>
            <div class="wallet-card-balance">
              ${balanceHtml}
              ${refreshBtn}
            </div>
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
          <a class="wallet-more-link" href="#/wallets/${w.id}">More…</a>
        </div>
      `;
      $list.appendChild(li);
    }
  }

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
    cachedWallets = wallets;
    $status.classList.remove("error");
    $status.textContent = wallets.length === 0
      ? ""
      : `${wallets.length} wallet${wallets.length === 1 ? "" : "s"}`;
    renderList(wallets);
  }

  // ── per-wallet balance refresh ─────────────────────────────────────────────
  $list.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>("[data-refresh]");
    if (!btn) return;
    const id = btn.dataset.refresh!;
    const wallet = cachedWallets.find(w => w.id === id);
    if (!wallet) return;
    void refreshWalletBalance(withDefaults(wallet), btn);
  });

  async function refreshWalletBalance(wallet: ReturnType<typeof withDefaults>, btn: HTMLButtonElement): Promise<void> {
    btn.disabled = true;
    btn.textContent = "…";
    try {
      const woc = new WocClient({ baseUrl: effectiveWocBase(wallet.network) });
      const result = await scanWalletUtxos(wallet.xpub, woc, { network: wallet.network });
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
      if (cancelled) return;
      if (listUnit === "fiat" && bsvUsdPrice === null) await fetchPrice();
      const idx = cachedWallets.findIndex(w => w.id === wallet.id);
      if (idx >= 0) cachedWallets[idx] = { ...cachedWallets[idx], lastScan: snapshot };
      renderList(cachedWallets);
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "↻";
      if (!cancelled) {
        $status.classList.add("error");
        $status.textContent = `balance refresh failed: ${(e as Error).message}`;
      }
    }
  }

  // ── unit selector ──────────────────────────────────────────────────────────
  $unit.addEventListener("change", async () => {
    listUnit = $unit.value as ListUnit;
    localStorage.setItem(LIST_UNIT_KEY, listUnit);
    if (listUnit === "fiat" && bsvUsdPrice === null) {
      await fetchPrice();
    }
    if (!cancelled) renderList(cachedWallets);
  });

  void render();
  // Pre-fetch price if fiat is the stored unit
  if (listUnit === "fiat") void fetchPrice().then(() => { if (!cancelled) renderList(cachedWallets); });

  return () => { cancelled = true; };
}
