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
import { splitConfirmedPending } from "../lib/balance-split.js";
import { relativeTimeFrom } from "../lib/relative-time.js";
import { DOCS_BASE_URL, PRICE_CACHE_TTL_MS } from "../lib/config.js";
import {
  KEY_LIST_SORT,
  KEY_LIST_UNIT,
  getFiatCurrency,
  getListSort,
  getListUnit,
  parseListSort,
  type ListUnit,
} from "../lib/companion-settings.js";
import {
  type WalletListSort,
  type WalletRecord,
  listWallets,
  setLastScan,
  sortWalletRecords,
  withDefaults,
} from "../lib/wallets.js";
import { renderHeader } from "./nav.js";
import { WocClient, effectiveWocBase } from "../lib/woc.js";
import { scanWalletUtxos } from "../lib/utxo.js";
import {
  canPromptInstall,
  detectInstallPlatform,
  dismissInstallPrompt,
  promptInstall,
  shouldShowInstallBanner,
} from "../lib/pwa-install.js";

const SATS_PER_BSV = 100_000_000;

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function mountWalletsPage(root: HTMLElement): () => void {
  let listUnit: ListUnit = getListUnit();
  let listSort: WalletListSort = getListSort();
  let bsvUsdPrice: number | null = null;
  let priceFetchedAt = 0;
  let cachedWallets: WalletRecord[] = [];
  let cancelled = false;

  root.innerHTML = `
    <main class="page">
      ${renderHeader("Wallets", "wallets")}

      <section id="installBanner" class="card install-banner" hidden>
        <h2 class="install-banner-title">Install PiWalletSV on this device</h2>
        <p id="installBannerBody" class="muted-line install-banner-body"></p>
        <div class="actions install-banner-actions">
          <button id="installBannerPrimary" type="button" class="primary" hidden>
            Install
          </button>
          <button id="installBannerDismiss" type="button">Not now</button>
        </div>
      </section>

      <div class="wallets-toolbar">
        <p class="muted-line" id="walletHint" hidden></p>
        <p class="muted-line" id="walletStatus" aria-live="polite"></p>
        <div class="wallets-toolbar-right">
          <select id="listSortSelect" class="list-unit-select" aria-label="Sort wallets">
            <option value="date"${listSort === "date" ? " selected" : ""}>Newest first</option>
            <option value="date-asc"${listSort === "date-asc" ? " selected" : ""}>Oldest first</option>
            <option value="label"${listSort === "label" ? " selected" : ""}>Label A–Z</option>
            <option value="label-desc"${listSort === "label-desc" ? " selected" : ""}>Label Z–A</option>
            <option value="balance"${listSort === "balance" ? " selected" : ""}>Balance high–low</option>
            <option value="balance-asc"${listSort === "balance-asc" ? " selected" : ""}>Balance low–high</option>
          </select>
          <select id="listUnitSelect" class="list-unit-select" aria-label="Balance unit">
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
  const $hint   = root.querySelector<HTMLElement>("#walletHint")!;
  const $status = root.querySelector<HTMLElement>("#walletStatus")!;

  const signedTxHint = sessionStorage.getItem("piwallet-signed-tx-hint");
  if (signedTxHint) {
    sessionStorage.removeItem("piwallet-signed-tx-hint");
    $hint.hidden = false;
    $hint.textContent = signedTxHint;
  }
  const $unit   = root.querySelector<HTMLSelectElement>("#listUnitSelect")!;
  const $sort   = root.querySelector<HTMLSelectElement>("#listSortSelect")!;
  const $installBanner = root.querySelector<HTMLElement>("#installBanner")!;
  const $installBody = root.querySelector<HTMLElement>("#installBannerBody")!;
  const $installPrimary = root.querySelector<HTMLButtonElement>("#installBannerPrimary")!;
  const $installDismiss = root.querySelector<HTMLButtonElement>("#installBannerDismiss")!;

  function hideInstallBanner(): void {
    $installBanner.hidden = true;
  }

  function setupInstallBanner(): void {
    if (!shouldShowInstallBanner()) {
      hideInstallBanner();
      return;
    }

    const platform = detectInstallPlatform();
    $installBanner.hidden = false;

    if (platform === "ios") {
      $installBody.textContent =
        "Tap Share (↑), then Add to Home Screen. Opens full-screen like an app — " +
        "handy for camera pairing and sends.";
      $installPrimary.hidden = true;
      $installDismiss.textContent = "Got it";
    } else if (platform === "chromium" && canPromptInstall()) {
      $installBody.textContent =
        "Install for full-screen access without the browser chrome.";
      $installPrimary.hidden = false;
      $installPrimary.textContent = "Install";
      $installDismiss.textContent = "Not now";
    } else if (platform === "chromium") {
      $installBody.textContent =
        "Open the browser menu (⋮) and choose Install app or Add to Home screen.";
      $installPrimary.hidden = true;
      $installDismiss.textContent = "Got it";
    } else {
      $installBody.textContent =
        "Add this page to your home screen for full-screen access.";
      $installPrimary.hidden = true;
      $installDismiss.textContent = "Got it";
    }
  }

  $installDismiss.addEventListener("click", () => {
    dismissInstallPrompt();
    hideInstallBanner();
  });

  $installPrimary.addEventListener("click", () => {
    void (async () => {
      $installPrimary.disabled = true;
      const outcome = await promptInstall();
      $installPrimary.disabled = false;
      if (outcome === "accepted") {
        hideInstallBanner();
        $status.classList.remove("error");
        $status.textContent = "Installed — open PiWalletSV from your home screen.";
        return;
      }
      if (outcome === "dismissed") {
        $status.textContent = "Install dismissed — use the browser menu anytime.";
        return;
      }
      $installBody.textContent =
        "Install unavailable here — use the browser menu (⋮) → Install app.";
      $installPrimary.hidden = true;
      $installDismiss.textContent = "Got it";
    })();
  });

  setupInstallBanner();

  function displayWallets(): WalletRecord[] {
    return sortWalletRecords(cachedWallets, listSort);
  }

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
        ? (() => {
            const split = splitConfirmedPending(w.lastScan.utxos);
            let pendingHtml = "";
            if (split.hasPending) {
              if (split.allPending) {
                pendingHtml = `<span class="wallet-pending-hint">pending</span>`;
              } else {
                pendingHtml =
                  `<span class="wallet-pending-hint">+${escapeHtml(formatBalance(split.pendingSats))} pending</span>`;
              }
            }
            return `<span class="wallet-balance">Balance: ${escapeHtml(formatBalance(w.lastScan.totalSats))}</span>${pendingHtml}`;
          })()
        : `<span class="wallet-balance muted-line">Balance: —</span>`;
      const scanMeta = w.lastScan
        ? `scanned ${relativeTimeFrom(w.lastScan.at)} · `
        : "";
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
            ${scanMeta}<code title="fingerprint">${w.fingerprint}</code> ·
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
    renderList(displayWallets());
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
      renderList(displayWallets());
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
    localStorage.setItem(KEY_LIST_UNIT, listUnit);
    if (listUnit === "fiat" && bsvUsdPrice === null) {
      await fetchPrice();
    }
    if (!cancelled) renderList(displayWallets());
  });

  $sort.addEventListener("change", () => {
    listSort = parseListSort($sort.value);
    localStorage.setItem(KEY_LIST_SORT, listSort);
    if (!cancelled) renderList(displayWallets());
  });

  void render();
  // Pre-fetch price if fiat is the stored unit
  if (listUnit === "fiat") void fetchPrice().then(() => { if (!cancelled) renderList(displayWallets()); });

  return () => { cancelled = true; };
}
