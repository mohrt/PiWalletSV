/**
 * Wallet detail page (`#/wallets/<id>`).
 *
 * Read-only view of a paired wallet plus the BIP32 receive flow:
 *
 * - Current receive address (m/0/<nextReceiveIndex>) shown as text + QR.
 * - "Next address" advances the on-disk pointer; "Previous" walks back.
 * - "Recent receive addresses" panel renders a window for visual context.
 *
 * Pure derivation; no network, no signing key. The Pi side is unaffected
 * by anything done here.
 */
import QRCode from "qrcode";

import {
  RECEIVE_BRANCH,
  deriveAddress,
  deriveAddressBatch,
} from "../lib/derive.js";
import { scanWalletUtxos } from "../lib/utxo.js";
import { WocClient, WocError } from "../lib/woc.js";
import {
  type WalletRecord,
  getWallet,
  setLastScan,
  setNextReceiveIndex,
  withDefaults,
} from "../lib/wallets.js";

const RECENT_WINDOW = 8;
const SATS_PER_BSV = 100_000_000;

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

export function mountWalletDetailPage(
  root: HTMLElement,
  walletId: string,
): () => void {
  let cancelled = false;
  let wallet: (WalletRecord & { nextReceiveIndex: number }) | null = null;
  let scanRunning = false;
  let woc: WocClient | null = null;

  root.innerHTML = `
    <main class="page">
      <header class="page-header">
        <h1>Wallet detail<span class="brand"> · PiWalletSV companion</span></h1>
        <nav>
          <a href="#/encode">Encode</a>
          <a href="#/scan">Scan</a>
          <a href="#/loop">Loop</a>
          <a href="#/wallets" class="active">Wallets</a>
        </nav>
      </header>
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
    renderShell();
    void renderReceive();
  }

  function renderError(html: string): void {
    if (cancelled) return;
    root.querySelector("#loadingCard")!.innerHTML = `
      <p class="error">${html}</p>
      <p><a href="#/wallets">← Back to wallets</a></p>
    `;
  }

  function renderShell(): void {
    if (!wallet) return;
    root.innerHTML = `
      <main class="page">
        <header class="page-header">
          <h1>${escapeHtml(wallet.label)}<span class="brand"> · PiWalletSV companion</span></h1>
          <nav>
            <a href="#/encode">Encode</a>
            <a href="#/scan">Scan</a>
            <a href="#/loop">Loop</a>
            <a href="#/wallets" class="active">Wallets</a>
          </nav>
        </header>

        <section class="card wallet-meta-card">
          <p class="muted-line">
            fingerprint <code>${wallet.fingerprint}</code> · ${escapeHtml(wallet.path)} ·
            paired ${new Date(wallet.addedAt).toLocaleString()}
          </p>
          <p class="muted-line wallet-xpub-full" title="${escapeHtml(wallet.xpub)}">
            xpub: ${escapeHtml(wallet.xpub)}
          </p>
          <p><a href="#/wallets">← Back to wallets</a></p>
        </section>

        <section class="card balance-card">
          <h2>Balance</h2>
          <div class="balance-row">
            <div class="balance-figures">
              <div class="balance-sats" id="balanceSats">—</div>
              <div class="balance-bsv muted-line" id="balanceBsv"></div>
              <div class="muted-line" id="balanceMeta"></div>
            </div>
            <div class="actions">
              <button id="refreshBalance" class="primary" type="button">
                Refresh balance
              </button>
            </div>
          </div>
          <p class="muted-line" id="balanceStatus"></p>
          <details id="utxoDetails" hidden>
            <summary>Show UTXOs (<span id="utxoCount">0</span>)</summary>
            <ul id="utxoList" class="utxo-list"></ul>
          </details>
        </section>

        <section class="card receive-card">
          <h2>Current receive address</h2>
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
        </section>

        <section class="card receive-list-card">
          <h2>Recent receive addresses</h2>
          <p class="muted-line">
            A window of 8 addresses around the current pointer (m/0/i).
            Pure derivation — no network calls.
          </p>
          <ul id="receiveList" class="addr-list"></ul>
        </section>
      </main>
    `;

    const $copy = root.querySelector<HTMLButtonElement>("#copyAddress")!;
    const $prev = root.querySelector<HTMLButtonElement>("#prevIdx")!;
    const $next = root.querySelector<HTMLButtonElement>("#nextIdx")!;
    $copy.addEventListener("click", () => void onCopy());
    $prev.addEventListener("click", () => void shiftIndex(-1));
    $next.addEventListener("click", () => void shiftIndex(1));

    const $refresh = root.querySelector<HTMLButtonElement>("#refreshBalance")!;
    $refresh.addEventListener("click", () => void onRefreshBalance());

    renderBalance();
  }

  function renderBalance(): void {
    if (!wallet) return;
    const $sats = root.querySelector<HTMLElement>("#balanceSats");
    const $bsv = root.querySelector<HTMLElement>("#balanceBsv");
    const $meta = root.querySelector<HTMLElement>("#balanceMeta");
    const $details = root.querySelector<HTMLDetailsElement>("#utxoDetails");
    const $count = root.querySelector<HTMLElement>("#utxoCount");
    const $list = root.querySelector<HTMLUListElement>("#utxoList");
    if (!$sats || !$bsv || !$meta || !$details || !$count || !$list) return;

    const scan = wallet.lastScan;
    if (!scan) {
      $sats.textContent = "—";
      $bsv.textContent = "";
      $meta.textContent =
        "Not scanned yet. Click Refresh to query WhatsOnChain for UTXOs.";
      $details.hidden = true;
      return;
    }
    $sats.textContent = formatSats(scan.totalSats);
    $bsv.textContent = formatBsv(scan.totalSats);
    $meta.textContent =
      `${scan.utxos.length} UTXO${scan.utxos.length === 1 ? "" : "s"} · ` +
      `scanned ${scan.addressesScanned} addresses · ` +
      `last refreshed ${relativeTimeFrom(scan.at)}`;
    $details.hidden = scan.utxos.length === 0;
    $count.textContent = String(scan.utxos.length);

    $list.innerHTML = "";
    for (const u of scan.utxos) {
      const li = document.createElement("li");
      li.className = "utxo-row";
      const branchLabel = u.derivation[0] === 0 ? "recv" : "change";
      li.innerHTML = `
        <div class="utxo-top">
          <code title="${escapeHtml(u.txid)}">${escapeHtml(shortTxid(u.txid))}:${u.vout}</code>
          <span class="utxo-sats">${formatSats(u.sats)}</span>
        </div>
        <div class="muted-line">
          ${branchLabel} m/${u.derivation[0]}/${u.derivation[1]} ·
          ${escapeHtml(u.address)} ·
          ${u.height === 0 ? "mempool" : `block ${u.height}`}
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
      $status.textContent = "Starting gap-limit scan (this can take a few seconds)…";
    }
    if (!woc) woc = new WocClient();

    try {
      const result = await scanWalletUtxos(wallet.xpub, woc, {
        onProgress: ({ branch, index, address, found }) => {
          if (cancelled || !$status) return;
          const branchLabel = branch === RECEIVE_BRANCH ? "recv" : "change";
          $status.textContent =
            `Probed ${branchLabel} m/${branch}/${index} ` +
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
      renderBalance();
      if ($status)
        $status.textContent =
          `Scan complete — ${result.utxos.length} UTXO(s), ` +
          `${result.addressesScanned} addresses probed.`;
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
        $refresh.textContent = "Refresh balance";
      }
    }
  }

  async function renderReceive(): Promise<void> {
    if (!wallet || cancelled) return;
    const idx = wallet.nextReceiveIndex;
    let derived: ReturnType<typeof deriveAddress>;
    try {
      derived = deriveAddress(wallet.xpub, RECEIVE_BRANCH, idx);
    } catch (e) {
      renderError(`derivation error: ${(e as Error).message}`);
      return;
    }
    const $path = root.querySelector<HTMLElement>("#receivePath")!;
    const $addr = root.querySelector<HTMLElement>("#receiveAddress")!;
    const $canvas = root.querySelector<HTMLCanvasElement>("#receiveQr")!;
    const $status = root.querySelector<HTMLElement>("#receiveStatus")!;
    const $prev = root.querySelector<HTMLButtonElement>("#prevIdx")!;

    $path.textContent = `${wallet.path} / ${derived.subPath}`;
    $addr.textContent = derived.address;
    $prev.disabled = idx === 0;
    $status.textContent =
      idx === 0
        ? "this is the first address (index 0)"
        : `address #${idx} on the receive branch`;

    try {
      await QRCode.toCanvas($canvas, derived.address, {
        margin: 1,
        width: 240,
        errorCorrectionLevel: "M",
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
      wallet.xpub,
      RECEIVE_BRANCH,
      start,
      RECENT_WINDOW,
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
        void navigator.clipboard
          .writeText(v)
          .then(() => {
            const orig = b.textContent;
            b.textContent = "copied!";
            setTimeout(() => {
              b.textContent = orig;
            }, 1200);
          })
          .catch(() => {});
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
        setTimeout(() => {
          if ($btn) $btn.textContent = orig;
        }, 1200);
      }
    } catch (e) {
      const $s = root.querySelector<HTMLElement>("#receiveStatus");
      if ($s) $s.textContent = `clipboard error: ${(e as Error).message}`;
    }
  }

  return () => {
    cancelled = true;
  };
}
