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
  CHANGE_BRANCH,
  RECEIVE_BRANCH,
  deriveAddress,
  deriveAddressBatch,
} from "../lib/derive.js";
import { encodeEnvelope } from "../lib/envelope.js";
import { CoinSelectError, selectUtxosGreedy } from "../lib/coin-select.js";
import { encodeMultipartLines } from "../pw1.js";
import { ProofFetchError, fetchInputProof } from "../lib/proof-fetcher.js";
import {
  ProposalBuilderError,
  buildUnsignedProposal,
} from "../lib/proposal.js";
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
  let sendBusy = false;
  let proposalFrames: string[] | null = null;
  let proposalFrameIdx = 0;
  let proposalLastFrameAt = 0;
  let proposalRaf: number | null = null;

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

        <section class="card send-card">
          <h2>Send</h2>
          <div id="sendForm">
            <label class="field">
              <span>Recipient address</span>
              <input id="sendAddress" type="text" autocomplete="off"
                placeholder="1..." />
            </label>
            <label class="field">
              <span>Amount (sats)</span>
              <input id="sendSats" type="number" min="1" step="1"
                placeholder="10000" />
            </label>
            <details class="advanced">
              <summary>Advanced</summary>
              <label class="field">
                <span>Fee rate (sats/kB)</span>
                <input id="sendFeeRate" type="number" min="0" step="1" value="500" />
              </label>
            </details>
            <div class="actions">
              <button id="buildProposal" type="button" class="primary">
                Build proposal
              </button>
            </div>
            <p class="muted-line" id="sendStatus"></p>
          </div>
          <div id="sendResult" hidden>
            <p class="muted-line">
              Animated PW1 proposal — point the Pi camera at this canvas.
            </p>
            <canvas id="proposalQr" width="320" height="320"></canvas>
            <p class="muted-line">
              Frame <span id="proposalFrameIdx">0</span> /
              <span id="proposalFrameCount">0</span> ·
              <span id="proposalByteCount">0</span> bytes total
            </p>
            <div class="actions">
              <button id="proposalToggle" type="button" class="primary">Pause</button>
              <button id="proposalDone" type="button">New send</button>
            </div>
          </div>
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

    const $build = root.querySelector<HTMLButtonElement>("#buildProposal")!;
    $build.addEventListener("click", () => void onBuildProposal());
    const $toggle = root.querySelector<HTMLButtonElement>("#proposalToggle")!;
    $toggle.addEventListener("click", toggleAnimation);
    const $done = root.querySelector<HTMLButtonElement>("#proposalDone")!;
    $done.addEventListener("click", resetSendCard);

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

  async function onBuildProposal(): Promise<void> {
    if (!wallet || sendBusy) return;
    const $addr = root.querySelector<HTMLInputElement>("#sendAddress")!;
    const $sats = root.querySelector<HTMLInputElement>("#sendSats")!;
    const $feeRate = root.querySelector<HTMLInputElement>("#sendFeeRate")!;
    const $btn = root.querySelector<HTMLButtonElement>("#buildProposal")!;
    const $status = root.querySelector<HTMLElement>("#sendStatus")!;
    $status.classList.remove("error");

    const recipient = $addr.value.trim();
    const sats = parseInt($sats.value, 10);
    const feeRate = parseInt($feeRate.value, 10);

    if (!recipient) {
      $status.classList.add("error");
      $status.textContent = "enter a recipient address";
      return;
    }
    if (!Number.isInteger(sats) || sats <= 0) {
      $status.classList.add("error");
      $status.textContent = "amount must be a positive integer (sats)";
      return;
    }
    if (!wallet.lastScan || wallet.lastScan.utxos.length === 0) {
      $status.classList.add("error");
      $status.textContent =
        "no UTXOs known. Click Refresh balance first.";
      return;
    }

    sendBusy = true;
    $btn.disabled = true;
    $btn.textContent = "Building…";
    $status.textContent = "Selecting UTXOs…";

    try {
      const selection = selectUtxosGreedy(
        wallet.lastScan.utxos,
        sats,
        feeRate,
      );
      $status.textContent =
        `Selected ${selection.inputs.length} UTXO(s) ` +
        `(${selection.totalInputSats.toLocaleString()} sats). ` +
        `Fetching SPV proofs…`;

      if (!woc) woc = new WocClient();
      const proofs = [];
      for (let i = 0; i < selection.inputs.length; i++) {
        const u = selection.inputs[i];
        $status.textContent =
          `Fetching proof ${i + 1}/${selection.inputs.length} for ${u.txid.slice(0, 8)}…`;
        const proof = await fetchInputProof(woc, u.txid);
        proofs.push({ utxo: u, proof });
      }

      // v1 proposals always carry an explicit above-dust change output.
      // selectUtxosGreedy throws if it cannot satisfy that, so by this
      // point selection.changeSats is guaranteed >= dust.
      const nextChangeIdx = (wallet.lastScan.lastChangeUsed ?? -1) + 1;
      const changeDerived = deriveAddress(
        wallet.xpub,
        CHANGE_BRANCH,
        nextChangeIdx,
      );
      const changeAddress = changeDerived.address;
      const changeDerivation: [number, number] = [CHANGE_BRANCH, nextChangeIdx];
      const changeSats = selection.changeSats;

      const envelope = buildUnsignedProposal({
        walletFingerprintHex: wallet.fingerprint,
        inputs: proofs.map(({ utxo, proof }) => ({
          txid: utxo.txid,
          vout: utxo.vout,
          sats: utxo.sats,
          derivation: utxo.derivation,
          proof,
        })),
        recipientAddress: recipient,
        recipientSats: sats,
        changeAddress,
        changeSats,
        changeDerivation,
        feeRateSatskb: feeRate,
        locktime: 0,
      });

      const blob = await encodeEnvelope(envelope);
      const frames = encodeMultipartLines(blob, 720);

      proposalFrames = frames;
      proposalFrameIdx = 0;
      proposalLastFrameAt = 0;
      const $count = root.querySelector<HTMLElement>("#proposalFrameCount")!;
      const $bytes = root.querySelector<HTMLElement>("#proposalByteCount")!;
      $count.textContent = String(frames.length);
      $bytes.textContent = String(blob.length);

      const $form = root.querySelector<HTMLElement>("#sendForm")!;
      const $result = root.querySelector<HTMLElement>("#sendResult")!;
      $form.hidden = true;
      $result.hidden = false;
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
      $btn.disabled = false;
      $btn.textContent = "Build proposal";
    }
  }

  function startProposalAnimation(): void {
    stopProposalAnimation();
    if (!proposalFrames || proposalFrames.length === 0) return;
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
    if (!proposalFrames || cancelled) {
      proposalRaf = null;
      return;
    }
    const interval = 1000 / 6; // 6 fps — same default as the encoder page.
    if (now - proposalLastFrameAt >= interval) {
      proposalLastFrameAt = now;
      const $canvas = root.querySelector<HTMLCanvasElement>("#proposalQr");
      const $idx = root.querySelector<HTMLElement>("#proposalFrameIdx");
      if ($canvas && $idx) {
        $idx.textContent = String(proposalFrameIdx + 1);
        void QRCode.toCanvas($canvas, proposalFrames[proposalFrameIdx], {
          width: 320,
          margin: 1,
          errorCorrectionLevel: "M",
        });
      }
      proposalFrameIdx = (proposalFrameIdx + 1) % proposalFrames.length;
    }
    proposalRaf = requestAnimationFrame(tickProposal);
  }

  function resetSendCard(): void {
    stopProposalAnimation();
    proposalFrames = null;
    proposalFrameIdx = 0;
    const $form = root.querySelector<HTMLElement>("#sendForm");
    const $result = root.querySelector<HTMLElement>("#sendResult");
    const $status = root.querySelector<HTMLElement>("#sendStatus");
    if ($form) $form.hidden = false;
    if ($result) $result.hidden = true;
    if ($status) {
      $status.classList.remove("error");
      $status.textContent = "";
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
    stopProposalAnimation();
  };
}
