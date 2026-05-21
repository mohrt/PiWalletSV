/**
 * Multipart-QR scanner page.
 *
 * Mirrors `piwallet.qr.camera_scan` (Pi-side): getUserMedia stream →
 * per-frame ImageData snapshot → jsqr decode → `MultipartAssembler.feed`.
 * Lets the user reassemble a PW1 stream produced by the Pi (or by the
 * companion's own encoder page) and download the resulting bytes.
 *
 * Privacy: getUserMedia is only invoked when the user clicks "Start
 * camera". Tracks are released on Stop and on page teardown.
 */
import { Transaction } from "@bsv/sdk";
import jsQR from "jsqr";

import {
  type Envelope,
  KIND_PROPOSAL,
  KIND_SIGNED,
  KIND_XPUB,
  type SignedTxT,
  type XpubExportT,
  atomicBeefTxid,
  bytesToHex,
  decodeEnvelope,
} from "../lib/envelope.js";
import { xpubFingerprint, DerivationError } from "../lib/derive.js";
import { extractHexFromPaste } from "../lib/hex-paste.js";
import { renderHeader } from "./nav.js";
import { MultipartAssembler, MultipartQrError } from "../pw1.js";
import {
  type WalletRecord,
  WalletStoreError,
  addWallet,
  findByFingerprintAndPath,
  listWallets,
} from "../lib/wallets.js";
import { ENVELOPE_VERSION } from "../lib/envelope.js";
import type { NetworkT } from "../lib/envelope.js";
import { WocClient, WocError, effectiveWocBase } from "../lib/woc.js";

const SCAN_INTERVAL_MS = 80; // ~12.5 fps; plenty for animated QR
const TEXT_DISPLAY_CAP = 64 * 1024; // truncate displayed body for huge payloads

type ViewMode = "text" | "hex" | "base64url";

export function mountScannerPage(
  root: HTMLElement,
  initialTab: "wallet" | "tx" = "wallet",
): () => void {
  root.innerHTML = `
    <main class="page">
      ${renderHeader("Scan / Import", "wallets")}

      <div class="scanner-tabs">
        <button role="tab" data-scan-tab="wallet"
          class="scanner-tab${initialTab === "wallet" ? " active" : ""}">
          Add wallet
        </button>
        <button role="tab" data-scan-tab="tx"
          class="scanner-tab${initialTab === "tx" ? " active" : ""}">
          Submit signed TX
        </button>
      </div>

      <!-- ── Add wallet tab ─────────────────────────────────────────── -->
      <div id="scanTab-wallet"${initialTab !== "wallet" ? ' hidden' : ''}>
        <section class="card scan-card">
          <p class="muted-line" style="margin-bottom:0.5rem">
            Point your camera at the Pi's animated QR to pair a wallet.
          </p>
          <video id="video" playsinline muted autoplay></video>
          <div class="scan-status">
            <p id="status">camera idle — click Start to grant access</p>
            <p id="missing" class="muted-line"></p>
            <div class="actions">
              <button id="start" class="primary" type="button">Start camera</button>
              <button id="stop" type="button">Stop</button>
              <button id="reset" type="button">Reset</button>
            </div>
          </div>
        </section>

        <section class="card paste-hex-card">
          <details>
            <summary>Or paste xpub (import from another companion)</summary>
            <p class="muted-line">
              Paste a BIP32 account-level extended public key to import a
              watch-only wallet without scanning the Pi. BSV uses the
              <code>xpub</code> prefix for both networks, so select the
              correct network below.
            </p>
            <textarea id="pasteXpub" class="hex-blob" rows="3"
              placeholder="xpub6…"
              spellcheck="false" autocorrect="off" autocomplete="off"></textarea>
            <label class="field">
              <span>Network</span>
              <select id="pasteXpubNetwork">
                <option value="main">Mainnet (BSV)</option>
                <option value="test">Testnet (TBSV)</option>
              </select>
            </label>
            <div class="actions">
              <button id="pasteXpubImport" class="primary" type="button">
                Import xpub
              </button>
              <button id="pasteXpubClear" type="button">Clear</button>
            </div>
            <p id="pasteXpubStatus" class="muted-line"></p>
          </details>
        </section>
      </div>

      <!-- ── Submit signed TX tab ───────────────────────────────────── -->
      <div id="scanTab-tx"${initialTab !== "tx" ? ' hidden' : ''}>
        <section class="card paste-hex-card">
          <h2>Paste signed transaction hex</h2>
          <p class="muted-line">
            After signing on the Pi via SSH, paste the hex output from
            <code>piwallet sign --hex …</code> here to broadcast it.
            Whitespace, newlines, and a leading <code>signed_tx:</code>
            prefix are all accepted.
          </p>
          <textarea id="pasteHex" class="hex-blob" rows="6"
            placeholder="paste signed_tx hex here…"
            spellcheck="false" autocorrect="off"></textarea>
          <div class="actions">
            <button id="pasteHexDecode" class="primary" type="button">
              Decode &amp; broadcast
            </button>
            <button id="pasteHexClear" type="button">Clear</button>
          </div>
          <p id="pasteHexStatus" class="muted-line"></p>
        </section>
      </div>

      <section id="pairCard" class="card pair-card" hidden>
        <h2>Save as paired wallet</h2>
        <p id="pairStatus" class="muted-line"></p>
        <label class="field-label" for="pairLabel">Wallet label</label>
        <input id="pairLabel" type="text" maxlength="64"
          autocomplete="off" autocorrect="off" spellcheck="false" />
        <p id="pairFp" class="muted-line"></p>
        <div class="actions">
          <button id="pairSave" class="primary" type="button">Save wallet</button>
          <a id="pairOpenList" href="#/wallets" hidden>Open wallets list</a>
        </div>
      </section>

      <section id="broadcastCard" class="card broadcast-card" hidden>
        <h2>Broadcast signed transaction</h2>
        <ol class="sign-steps" id="signSteps">
          <li class="sign-step done" id="step-scan">Scanned</li>
          <li class="sign-step active" id="step-broadcast">Broadcast</li>
          <li class="sign-step" id="step-done">Done</li>
        </ol>
        <p id="broadcastTxid" class="broadcast-txid"></p>
        <p id="broadcastMeta" class="muted-line"></p>
        <div class="actions">
          <button id="broadcastBtn" class="primary" type="button">
            Broadcast to BSV mainnet
          </button>
          <a id="broadcastExplorer" target="_blank" rel="noopener noreferrer"
            class="primary-link" hidden>View on WhatsOnChain</a>
        </div>
        <p id="broadcastStatus" class="muted-line"></p>
        <p id="broadcastSuccess" class="broadcast-success" hidden>
          ✓ Transaction accepted by the BSV network.
        </p>
      </section>

      <section id="resultCard" class="card" hidden>
        <pre id="envelopeView" class="envelope-summary" hidden></pre>
        <div class="row" style="margin-bottom: 0.6rem;">
          <fieldset>
            <legend>View raw bytes as</legend>
            <label><input type="radio" name="view" value="text" /> text</label>
            <label><input type="radio" name="view" value="hex" /> hex</label>
            <label><input type="radio" name="view" value="base64url" /> base64url</label>
          </fieldset>
        </div>
        <textarea id="resultBody" rows="8" readonly
          spellcheck="false" autocorrect="off"></textarea>
        <p id="resultMeta" class="muted-line"></p>
        <div class="actions">
          <button id="download" class="primary" type="button">Download .bin</button>
          <button id="copyView" type="button">Copy current view</button>
          <button id="copyB64" type="button">Copy base64url</button>
        </div>
      </section>
    </main>
  `;

  const $video = root.querySelector<HTMLVideoElement>("#video")!;
  const $status = root.querySelector<HTMLElement>("#status")!;
  const $missing = root.querySelector<HTMLElement>("#missing")!;
  const $start = root.querySelector<HTMLButtonElement>("#start")!;
  const $stop = root.querySelector<HTMLButtonElement>("#stop")!;
  const $reset = root.querySelector<HTMLButtonElement>("#reset")!;
  const $resultCard = root.querySelector<HTMLElement>("#resultCard")!;
  const $envelopeView = root.querySelector<HTMLElement>("#envelopeView")!;
  const $resultBody = root.querySelector<HTMLTextAreaElement>("#resultBody")!;
  const $resultMeta = root.querySelector<HTMLElement>("#resultMeta")!;
  const $download = root.querySelector<HTMLButtonElement>("#download")!;
  const $copyView = root.querySelector<HTMLButtonElement>("#copyView")!;
  const $copyB64 = root.querySelector<HTMLButtonElement>("#copyB64")!;
  const $pasteXpub = root.querySelector<HTMLTextAreaElement>("#pasteXpub")!;
  const $pasteXpubNetwork = root.querySelector<HTMLSelectElement>("#pasteXpubNetwork")!;
  const $pasteXpubImport = root.querySelector<HTMLButtonElement>("#pasteXpubImport")!;
  const $pasteXpubClear = root.querySelector<HTMLButtonElement>("#pasteXpubClear")!;
  const $pasteXpubStatus = root.querySelector<HTMLElement>("#pasteXpubStatus")!;
  const $pairCard = root.querySelector<HTMLElement>("#pairCard")!;
  const $pairStatus = root.querySelector<HTMLElement>("#pairStatus")!;
  const $pairLabel = root.querySelector<HTMLInputElement>("#pairLabel")!;
  const $pairFp = root.querySelector<HTMLElement>("#pairFp")!;
  const $pairSave = root.querySelector<HTMLButtonElement>("#pairSave")!;
  const $pairOpenList = root.querySelector<HTMLAnchorElement>("#pairOpenList")!;
  const $broadcastCard = root.querySelector<HTMLElement>("#broadcastCard")!;
  const $broadcastTxid = root.querySelector<HTMLElement>("#broadcastTxid")!;
  const $broadcastMeta = root.querySelector<HTMLElement>("#broadcastMeta")!;
  const $broadcastBtn = root.querySelector<HTMLButtonElement>("#broadcastBtn")!;
  const $broadcastExplorer = root.querySelector<HTMLAnchorElement>(
    "#broadcastExplorer",
  )!;
  const $broadcastStatus = root.querySelector<HTMLElement>("#broadcastStatus")!;

  // ── Tab switching ──────────────────────────────────────────────────────────
  let activeTab: "wallet" | "tx" = initialTab;

  function switchScannerTab(tab: "wallet" | "tx"): void {
    activeTab = tab;
    root.querySelectorAll<HTMLElement>("[id^='scanTab-']").forEach((el) => {
      el.hidden = el.id !== `scanTab-${tab}`;
    });
    root.querySelectorAll<HTMLButtonElement>("[data-scan-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.scanTab === tab);
    });
    // Release camera when leaving the wallet tab
    if (tab !== "wallet" && scanning) releaseCamera();
  }

  root.querySelectorAll<HTMLButtonElement>("[data-scan-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchScannerTab(btn.dataset.scanTab as "wallet" | "tx");
    });
  });

  // When a signed TX is scanned on the wallet tab, auto-switch to TX tab
  function autoSwitchToTx(): void {
    if (activeTab !== "tx") switchScannerTab("tx");
  }

  const offscreen = document.createElement("canvas");
  const offscreenCtx = offscreen.getContext("2d", { willReadFrequently: true });
  if (!offscreenCtx) {
    $status.textContent = "this browser does not expose a 2D canvas context";
    return () => {};
  }

  let stream: MediaStream | null = null;
  let rafHandle: number | null = null;
  let scanning = false;
  let lastScanAt = 0;
  let asm = new MultipartAssembler();
  let result: Uint8Array | null = null;
  let envelope: Envelope | null = null;
  let lastDownloadUrl: string | null = null;
  let pairXpub: XpubExportT | null = null;
  let signedTx: SignedTxT | null = null;
  let signedTxNetwork: NetworkT = "main";
  // Decoded once when the broadcast card is shown so the broadcast click
  // doesn't re-parse the BEEF (and so a parse failure surfaces in the UI
  // before the user commits to a network round-trip).
  let signedTxRawHex = "";
  let signedTxId = "";
  let woc: WocClient | null = null;
  let broadcasting = false;

  $stop.disabled = true;
  $reset.disabled = true;

  function setStatus(msg: string, isError = false): void {
    $status.textContent = msg;
    $status.classList.toggle("error", isError);
  }

  function refreshProgress(): void {
    const total = asm.expectedTotal;
    const got = asm.partsReceived;
    if (total === null) {
      setStatus(scanning ? "scanning… (no PW1 frames yet)" : "camera idle");
      $missing.textContent = "";
      return;
    }
    setStatus(`scanning… received ${got}/${total} fragments`);
    if (got < total) {
      const haveSet = new Set(asm.receivedIndices);
      const missing: number[] = [];
      for (let i = 0; i < total && missing.length < 16; i++) {
        if (!haveSet.has(i)) missing.push(i);
      }
      const more = total - got > missing.length ? "…" : "";
      $missing.textContent = `missing: ${missing.join(", ")}${more}`;
    } else {
      $missing.textContent = "";
    }
  }

  function looksLikeText(bytes: Uint8Array): boolean {
    if (bytes.length === 0) return true;
    let decoded: string;
    try {
      decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      return false;
    }
    for (const ch of decoded) {
      const c = ch.codePointAt(0)!;
      if (c < 0x20 && c !== 0x09 && c !== 0x0a && c !== 0x0d) return false;
      if (c === 0x7f) return false;
    }
    return true;
  }

  function bytesToBase64Url(bytes: Uint8Array): string {
    let s = "";
    const block = 0x8000;
    for (let i = 0; i < bytes.length; i += block) {
      s += String.fromCharCode(...bytes.subarray(i, i + block));
    }
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function bytesAsView(bytes: Uint8Array, mode: ViewMode): string {
    if (mode === "text") {
      return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    }
    if (mode === "hex") return bytesToHex(bytes);
    return bytesToBase64Url(bytes);
  }

  function currentViewMode(): ViewMode {
    const checked = root.querySelector<HTMLInputElement>(
      'input[name="view"]:checked',
    );
    return (checked?.value as ViewMode) ?? "text";
  }

  function renderResultView(): void {
    if (!result) return;
    const mode = currentViewMode();
    let body = bytesAsView(result, mode);
    let truncated = false;
    if (body.length > TEXT_DISPLAY_CAP) {
      body = `${body.slice(0, TEXT_DISPLAY_CAP)}\n…[display truncated]`;
      truncated = true;
    }
    $resultBody.value = body;
    const textLabel = looksLikeText(result) ? "valid UTF-8" : "binary";
    $resultMeta.textContent = `${result.length} bytes · ${textLabel}` +
      (truncated ? " · display truncated" : "");
  }

  function formatEnvelope(env: Envelope): string {
    const fp = env.kind === KIND_XPUB ? env.fingerprint : env.walletFp;
    const lines: string[] = [
      `${env.kind === KIND_XPUB ? "xpub_export" : env.kind === KIND_PROPOSAL ? "unsigned_proposal" : "signed_tx"} v${ENVELOPE_VERSION}`,
      `walletFp:    ${bytesToHex(fp)}`,
    ];
    if (env.kind === KIND_XPUB) {
      lines.push(
        `xpub:        ${env.xpub}`,
        `path:        ${env.path}`,
        `label:       ${env.label}`,
      );
    } else if (env.kind === KIND_PROPOSAL) {
      lines.push(`feeRate:     ${env.feeRate} sats/kB`);
      lines.push(`locktime:    ${env.locktime}`);
      lines.push(
        `changeIndex: ${env.changeIndex} (derivation [${env.changeDerivation.join(", ")}])`,
      );
      env.inputs.forEach((i, idx) => {
        lines.push(
          `inputs[${idx}]:`,
          `  txid:       ${i.txid}`,
          `  vout:       ${i.vout}`,
          `  sats:       ${i.sats}`,
          `  derivation: [${i.derivation.join(", ")}]`,
          `  beef:       ${i.beef.byteLength} bytes`,
        );
      });
      env.outputs.forEach((o, idx) => {
        lines.push(`outputs[${idx}]: ${o.sats} sats → ${o.scriptHex}`);
      });
      const anchorHeights = [...env.headerAnchors.keys()].sort(
        (a, b) => a - b,
      );
      const anchorRange =
        anchorHeights.length === 0
          ? "(none)"
          : anchorHeights.length === 1
            ? `(height ${anchorHeights[0]})`
            : `(heights ${anchorHeights[0]}..${anchorHeights[anchorHeights.length - 1]})`;
      lines.push(
        `headerAnchors:    ${env.headerAnchors.size} entry${
          env.headerAnchors.size === 1 ? "" : "s"
        } ${anchorRange}`,
      );
    } else {
      // signed_tx envelope. The BRC-95 header carries the subject TXID
      // directly; we surface the inner BEEF body length as a sanity hint.
      try {
        lines.push(`txid:        ${atomicBeefTxid(env.atomicBeef)}`);
      } catch (e) {
        lines.push(`atomicBeef:  parse error: ${(e as Error).message}`);
      }
      lines.push(
        `atomicBeef:  ${env.atomicBeef.byteLength} bytes (BRC-95)`,
      );
    }
    return lines.join("\n");
  }

  function hidePairCard(): void {
    pairXpub = null;
    $pairCard.hidden = true;
    $pairStatus.classList.remove("error");
    $pairStatus.textContent = "";
    $pairFp.textContent = "";
    $pairLabel.value = "";
    $pairSave.disabled = false;
    $pairSave.textContent = "Save wallet";
    $pairOpenList.hidden = true;
  }

  async function showPairCard(env: XpubExportT): Promise<void> {
    pairXpub = env;
    const fpHex = bytesToHex(env.fingerprint);
    $pairCard.hidden = false;
    $pairLabel.value = env.label;
    $pairLabel.disabled = false;
    $pairSave.textContent = "Save wallet";
    $pairOpenList.hidden = true;
    const netLabel = env.network === "test" ? " · TESTNET" : "";
    $pairFp.textContent = `fingerprint ${fpHex} · ${env.path}${netLabel}`;
    $pairStatus.classList.remove("error");

    let existing: WalletRecord | null = null;
    try {
      existing = await findByFingerprintAndPath(fpHex, env.path);
    } catch (e) {
      $pairStatus.classList.add("error");
      $pairStatus.textContent = `wallet store error: ${(e as Error).message}`;
      $pairSave.disabled = true;
      return;
    }

    // A duplicate pair is only blocking if it's on the same network.
    // The same seed can drive a mainnet and a testnet wallet in
    // parallel; the companion treats those as distinct entries.
    const sameNetworkDup =
      existing && (existing.network ?? "main") === (env.network ?? "main");

    if (existing && sameNetworkDup) {
      $pairStatus.textContent =
        `already paired as "${existing.label}" on ${new Date(existing.addedAt).toLocaleString()}.`;
      $pairSave.disabled = true;
      $pairOpenList.hidden = false;
    } else if (existing) {
      // Cross-network re-pair: same fingerprint+path, different network.
      const otherNet = (existing.network ?? "main") === "test" ? "TESTNET" : "mainnet";
      const thisNet = env.network === "test" ? "TESTNET" : "mainnet";
      $pairStatus.textContent =
        `note: this seed is already paired as "${existing.label}" on ${otherNet}; ` +
        `saving will create a new ${thisNet} entry alongside it.`;
      $pairSave.disabled = false;
    } else {
      const isImport = env.label === "Imported wallet";
      $pairStatus.textContent = isImport
        ? "Enter a label for this wallet, then save."
        : `Pi reported label "${env.label}". You can rename it before saving.`;
      $pairSave.disabled = false;
    }
  }

  async function onPairSave(): Promise<void> {
    if (!pairXpub) return;
    const label = $pairLabel.value.trim() || pairXpub.label;
    $pairSave.disabled = true;
    try {
      const rec = await addWallet({
        label,
        xpub: pairXpub.xpub,
        fingerprint: bytesToHex(pairXpub.fingerprint),
        path: pairXpub.path,
        network: pairXpub.network,
      });
      $pairStatus.classList.remove("error");
      const netSuffix = rec.network === "test" ? " (TESTNET)" : "";
      $pairStatus.textContent =
        `saved "${rec.label}"${netSuffix} — opening wallets…`;
      $pairLabel.disabled = true;
      setTimeout(() => {
        window.location.hash = "#/wallets";
      }, 800);
    } catch (e) {
      $pairStatus.classList.add("error");
      const msg = e instanceof WalletStoreError ? e.message : (e as Error).message;
      $pairStatus.textContent = `save failed: ${msg}`;
      // If it's the duplicate-pair case, surface the wallets list link.
      if (msg.includes("duplicate-pair")) $pairOpenList.hidden = false;
    }
  }

  function hideBroadcastCard(): void {
    signedTx = null;
    signedTxNetwork = "main";
    signedTxRawHex = "";
    signedTxId = "";
    broadcasting = false;
    $broadcastCard.hidden = true;
    $broadcastTxid.textContent = "";
    $broadcastMeta.textContent = "";
    $broadcastStatus.classList.remove("error");
    $broadcastStatus.textContent = "";
    $broadcastBtn.disabled = false;
    $broadcastBtn.textContent = "Broadcast to BSV mainnet";
    $broadcastExplorer.hidden = true;
    $broadcastExplorer.removeAttribute("href");
  }

  async function showBroadcastCard(env: SignedTxT): Promise<void> {
    signedTx = env;
    broadcasting = false;
    // Resolve the wallet's network so we route the broadcast (and the
    // explorer link) to the correct WoC base. The signed_tx envelope
    // carries only `walletFp`, so we look it up against the paired
    // wallet store; if the wallet isn't paired here we default to
    // mainnet and surface a notice. Mismatches surface clearly when
    // the broadcast eventually fails on the wrong network.
    const fpHex = bytesToHex(env.walletFp).toLowerCase();
    let net: NetworkT = "main";
    try {
      const all = await listWallets();
      const match = all.find((w) => w.fingerprint === fpHex);
      if (match) net = match.network ?? "main";
    } catch {
      // Treat IndexedDB errors as "no match"; fall through to mainnet.
    }
    signedTxNetwork = net;

    // Decode the Atomic BEEF (BRC-95) once at card-display time so
    // the operator sees the same txid the broadcast will submit, and
    // any malformed payload surfaces a clear error before the user
    // commits to a network round-trip.
    let txid: string;
    let rawHex: string;
    let txByteSize: number;
    try {
      const tx = Transaction.fromAtomicBEEF(Array.from(env.atomicBeef));
      txid = tx.id("hex") as string;
      rawHex = tx.toHex();
      txByteSize = rawHex.length / 2;
    } catch (e) {
      $broadcastCard.hidden = false;
      $broadcastTxid.textContent = "";
      $broadcastMeta.textContent = "";
      $broadcastStatus.classList.add("error");
      $broadcastStatus.textContent =
        `signed_tx Atomic BEEF parse failed: ${(e as Error).message}`;
      $broadcastBtn.disabled = true;
      $broadcastBtn.textContent = "Cannot broadcast";
      $broadcastExplorer.hidden = true;
      return;
    }
    signedTxRawHex = rawHex;
    signedTxId = txid;

    $broadcastCard.hidden = false;
    $broadcastTxid.textContent = `txid: ${txid}`;
    const netLabel = net === "test" ? "TESTNET" : "mainnet";
    $broadcastMeta.textContent =
      `wallet ${fpHex} · raw tx ${txByteSize} bytes · ${netLabel}`;
    $broadcastStatus.classList.remove("error");
    $broadcastStatus.textContent = "";
    $broadcastBtn.disabled = false;
    $broadcastBtn.textContent =
      net === "test" ? "Broadcast to BSV testnet" : "Broadcast to BSV mainnet";
    $broadcastExplorer.hidden = true;
    $broadcastExplorer.removeAttribute("href");
  }

  function setSignStep(step: "scan" | "broadcast" | "done" | "error"): void {
    const $scan = root.querySelector<HTMLElement>("#step-scan");
    const $broadcast = root.querySelector<HTMLElement>("#step-broadcast");
    const $done = root.querySelector<HTMLElement>("#step-done");
    if (!$scan || !$broadcast || !$done) return;
    // Reset all
    for (const el of [$scan, $broadcast, $done]) {
      el.className = "sign-step";
    }
    if (step === "scan") {
      $scan.classList.add("active");
    } else if (step === "broadcast") {
      $scan.classList.add("done");
      $broadcast.classList.add("active");
    } else if (step === "done") {
      $scan.classList.add("done");
      $broadcast.classList.add("done");
      $done.classList.add("done");
    } else if (step === "error") {
      $scan.classList.add("done");
      $broadcast.classList.add("error");
    }
  }

  async function onBroadcast(): Promise<void> {
    if (!signedTx || broadcasting) return;
    broadcasting = true;
    $broadcastBtn.disabled = true;
    $broadcastBtn.textContent = "Broadcasting…";
    $broadcastStatus.classList.remove("error");
    $broadcastStatus.textContent = "Submitting to WhatsOnChain…";
    setSignStep("broadcast");

    const baseUrl = effectiveWocBase(signedTxNetwork);
    if (!woc || woc.baseUrl !== baseUrl.replace(/\/+$/, "")) {
      woc = new WocClient({ baseUrl });
    }
    try {
      const txid = await woc.broadcastRaw(signedTxRawHex);
      setSignStep("done");
      const $success = root.querySelector<HTMLElement>("#broadcastSuccess");
      if ($success) $success.hidden = false;
      $broadcastStatus.textContent = `txid: ${txid}`;
      if (txid.toLowerCase() !== signedTxId.toLowerCase()) {
        $broadcastStatus.classList.add("error");
        $broadcastStatus.textContent =
          `WARNING: WoC returned txid ${txid} but the Pi signed ${signedTxId}.`;
      }
      const explorerBase =
        signedTxNetwork === "test"
          ? "https://test.whatsonchain.com/tx/"
          : "https://whatsonchain.com/tx/";
      $broadcastExplorer.href = `${explorerBase}${txid}`;
      $broadcastExplorer.hidden = false;
      $broadcastBtn.textContent = "Broadcasted";
    } catch (e) {
      setSignStep("error");
      $broadcastStatus.classList.add("error");
      let msg: string;
      if (e instanceof WocError) {
        msg = e.message;
        if (e.bodySnippet) msg += `\nWoC said: ${e.bodySnippet}`;
      } else {
        msg = (e as Error).message;
      }
      $broadcastStatus.textContent = `broadcast failed: ${msg}`;
      $broadcastBtn.disabled = false;
      $broadcastBtn.textContent = "Retry broadcast";
    } finally {
      broadcasting = false;
    }
  }

  async function tryDecodeEnvelope(bytes: Uint8Array): Promise<void> {
    try {
      envelope = await decodeEnvelope(bytes);
    } catch {
      envelope = null;
    }
  }

  async function showResult(bytes: Uint8Array): Promise<void> {
    result = bytes;
    await tryDecodeEnvelope(bytes);

    if (envelope) {
      $envelopeView.textContent = formatEnvelope(envelope);
      $envelopeView.hidden = false;
    } else {
      $envelopeView.textContent = "";
      $envelopeView.hidden = true;
    }

    if (envelope?.kind === KIND_XPUB) {
      await showPairCard(envelope);
    } else {
      hidePairCard();
    }

    if (envelope?.kind === KIND_SIGNED) {
      autoSwitchToTx();
      void showBroadcastCard(envelope);
    } else {
      hideBroadcastCard();
    }

    const defaultView: ViewMode = looksLikeText(bytes) ? "text" : "hex";
    for (const r of root.querySelectorAll<HTMLInputElement>(
      'input[name="view"]',
    )) {
      r.checked = r.value === defaultView;
    }
    renderResultView();
    $resultCard.hidden = false;
    $reset.disabled = false;
    const tag = envelope
      ? `complete — ${envelope.kind === KIND_XPUB ? "xpub_export" : envelope.kind === KIND_PROPOSAL ? "unsigned_proposal" : "signed_tx"} (${bytes.length} bytes)`
      : `complete — reassembled ${bytes.length} bytes`;
    setStatus(tag);
    $missing.textContent = "";
  }

  function handleDecoded(data: string): void {
    const trimmed = data.trim();
    if (!trimmed.startsWith("PW1|")) return;
    let out: Uint8Array | null = null;
    try {
      out = asm.feed(trimmed);
    } catch (e) {
      if (e instanceof MultipartQrError) {
        // mid-stream protocol error: reset and keep scanning
        asm = new MultipartAssembler();
        setStatus(`pw1 error: ${e.message} (assembler reset)`, true);
        return;
      }
      throw e;
    }
    if (out !== null) {
      stopScanning();
      void showResult(out);
    } else {
      refreshProgress();
    }
  }

  function tickScan(now: number): void {
    if (!scanning) {
      rafHandle = null;
      return;
    }
    if (
      now - lastScanAt >= SCAN_INTERVAL_MS &&
      $video.readyState >= 2 &&
      $video.videoWidth > 0
    ) {
      lastScanAt = now;
      const w = $video.videoWidth;
      const h = $video.videoHeight;
      offscreen.width = w;
      offscreen.height = h;
      offscreenCtx!.drawImage($video, 0, 0, w, h);
      const img = offscreenCtx!.getImageData(0, 0, w, h);
      const code = jsQR(img.data, img.width, img.height, {
        inversionAttempts: "dontInvert",
      });
      if (code?.data) handleDecoded(code.data);
    }
    rafHandle = requestAnimationFrame(tickScan);
  }

  async function startCamera(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus(
        "camera unavailable: needs HTTPS or localhost (insecure context)",
        true,
      );
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
    } catch (e) {
      const err = e as DOMException;
      const name = err.name ?? "unknown";
      const map: Record<string, string> = {
        NotAllowedError: "camera permission denied",
        NotFoundError: "no camera available on this device",
        NotReadableError: "camera in use by another application",
        OverconstrainedError: "camera does not match requested constraints",
      };
      setStatus(map[name] ?? `camera error: ${err.message ?? name}`, true);
      return;
    }

    $video.srcObject = stream;
    await new Promise<void>((resolve) => {
      if ($video.readyState >= 1) {
        resolve();
        return;
      }
      $video.addEventListener("loadedmetadata", () => resolve(), {
        once: true,
      });
    });
    try {
      await $video.play();
    } catch {
      // Some browsers throw a benign AbortError when play() races teardown.
    }

    scanning = true;
    lastScanAt = 0;
    rafHandle = requestAnimationFrame(tickScan);
    $start.disabled = true;
    $stop.disabled = false;
    refreshProgress();
  }

  function stopScanning(): void {
    scanning = false;
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle);
      rafHandle = null;
    }
  }

  function releaseCamera(): void {
    stopScanning();
    if (stream) {
      for (const t of stream.getTracks()) t.stop();
      stream = null;
    }
    $video.srcObject = null;
    $start.disabled = false;
    $stop.disabled = true;
  }

  function resetAll(): void {
    asm = new MultipartAssembler();
    result = null;
    envelope = null;
    $resultCard.hidden = true;
    $envelopeView.hidden = true;
    $envelopeView.textContent = "";
    $resultBody.value = "";
    $resultMeta.textContent = "";
    $missing.textContent = "";
    $reset.disabled = true;
    hidePairCard();
    hideBroadcastCard();
    if (lastDownloadUrl) {
      URL.revokeObjectURL(lastDownloadUrl);
      lastDownloadUrl = null;
    }
    if (stream && !scanning) {
      // camera still warm; resume scanning for the next stream
      scanning = true;
      lastScanAt = 0;
      rafHandle = requestAnimationFrame(tickScan);
      $stop.disabled = false;
      refreshProgress();
    } else if (!stream) {
      setStatus("camera idle — click Start to grant access");
    }
  }

  function downloadResult(): void {
    if (!result) return;
    const blob = new Blob([result], { type: "application/octet-stream" });
    if (lastDownloadUrl) URL.revokeObjectURL(lastDownloadUrl);
    lastDownloadUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = lastDownloadUrl;
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    a.download = `pw1-payload-${ts}.bin`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function copyToClipboard(
    text: string,
    btn: HTMLButtonElement,
    restoreLabel: string,
  ): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "copied!";
      setTimeout(() => {
        btn.textContent = restoreLabel;
      }, 1200);
    } catch (e) {
      setStatus(`clipboard error: ${(e as Error).message}`, true);
    }
  }

  $start.addEventListener("click", () => {
    void startCamera();
  });
  $stop.addEventListener("click", releaseCamera);
  $reset.addEventListener("click", resetAll);
  $download.addEventListener("click", downloadResult);
  $copyB64.addEventListener("click", () => {
    if (!result) return;
    void copyToClipboard(
      bytesToBase64Url(result),
      $copyB64,
      "Copy base64url",
    );
  });
  $copyView.addEventListener("click", () => {
    if (!result) return;
    void copyToClipboard(
      bytesAsView(result, currentViewMode()),
      $copyView,
      "Copy current view",
    );
  });
  for (const r of root.querySelectorAll<HTMLInputElement>('input[name="view"]')) {
    r.addEventListener("change", renderResultView);
  }
  $pairSave.addEventListener("click", () => {
    void onPairSave();
  });
  $broadcastBtn.addEventListener("click", () => {
    void onBroadcast();
  });

  // ---- Paste-hex bridge ----------------------------------------------
  // Lets the operator skip the camera entirely when they have the
  // envelope as text — typically a signed_tx blob piped over SSH from
  // `piwallet sign --hex -` on the Pi (the "Sign over SSH" example in
  // docs/cli.md). Reuses showResult() so xpub_export / proposal blobs
  // work too — useful for debugging without ever opening the camera.
  const $pasteHex = root.querySelector<HTMLTextAreaElement>("#pasteHex")!;
  const $pasteHexDecode = root.querySelector<HTMLButtonElement>(
    "#pasteHexDecode",
  )!;
  const $pasteHexClear = root.querySelector<HTMLButtonElement>(
    "#pasteHexClear",
  )!;
  const $pasteHexStatus = root.querySelector<HTMLElement>("#pasteHexStatus")!;

  function setPasteStatus(msg: string, isError = false): void {
    $pasteHexStatus.textContent = msg;
    $pasteHexStatus.classList.toggle("error", isError);
  }

  function onPasteHexDecode(): void {
    // extractHexFromPaste() tolerates the labelled SSH-terminal output
    // shape — lines like `verified: ...` and `txid: ...` are dropped,
    // and a `signed_tx:` (or any `label:`) prefix is stripped from the
    // hex line so the operator can paste the entire CLI summary.
    const parsed = extractHexFromPaste($pasteHex.value);
    const cleaned = parsed.hex;
    if (cleaned.length === 0) {
      setPasteStatus("paste an envelope hex string first", true);
      return;
    }
    if (cleaned.length % 2 !== 0) {
      setPasteStatus(
        `hex has odd length ${cleaned.length}; check the paste was complete`,
        true,
      );
      return;
    }
    if (!/^[0-9a-f]+$/.test(cleaned)) {
      setPasteStatus(
        "hex contains non-[0-9a-f] characters after stripping whitespace",
        true,
      );
      return;
    }
    let bytes: Uint8Array;
    try {
      bytes = new Uint8Array(cleaned.length / 2);
      for (let i = 0; i < bytes.length; i++) {
        bytes[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
      }
    } catch (e) {
      setPasteStatus(`hex decode failed: ${(e as Error).message}`, true);
      return;
    }
    setPasteStatus(`decoding ${bytes.length} bytes…`);
    // Reset the multipart assembler so a previous half-finished camera
    // session doesn't bleed into this paste-driven session.
    asm = new MultipartAssembler();
    void showResult(bytes).then(() => {
      // showResult() already updates the main #status banner; the
      // textarea's own status echoes "decoded" so the operator
      // doesn't have to scan up the page to find feedback. If we
      // dropped any prefix-labelled summary lines (e.g. `verified:`,
      // `txid:`) call that out so the operator knows the parse was
      // generous on purpose, not by accident.
      const droppedCount =
        parsed.droppedLabeled.length + parsed.droppedOther.length;
      const noteParts: string[] = [`decoded ${bytes.length} bytes`];
      if (droppedCount > 0) {
        noteParts.push(`ignored ${droppedCount} non-hex line(s)`);
      }
      noteParts.push("see the result card below");
      setPasteStatus(noteParts.join(" — "));
    });
  }

  $pasteHexDecode.addEventListener("click", onPasteHexDecode);
  $pasteHexClear.addEventListener("click", () => {
    $pasteHex.value = "";
    setPasteStatus("");
    $pasteHex.focus();
  });

  // ── xpub paste import ───────────────────────────────────────────────────
  function setXpubStatus(msg: string, isError = false): void {
    $pasteXpubStatus.textContent = msg;
    $pasteXpubStatus.classList.toggle("error", isError);
  }

  async function onPasteXpubImport(): Promise<void> {
    const raw = $pasteXpub.value.trim();
    if (!raw) {
      setXpubStatus("paste an xpub key first", true);
      return;
    }

    if (!raw.startsWith("xpub") && !raw.startsWith("tpub")) {
      setXpubStatus(
        "unrecognised key — expected a BIP32 extended public key (xpub… or tpub…)",
        true,
      );
      return;
    }

    const network = $pasteXpubNetwork.value as NetworkT;

    let fp: Uint8Array;
    try {
      fp = xpubFingerprint(raw);
    } catch (e) {
      setXpubStatus(
        `invalid xpub: ${e instanceof DerivationError ? e.message : (e as Error).message}`,
        true,
      );
      return;
    }

    setXpubStatus("xpub valid — fill in a label and save below.");

    // Reuse the QR-scan pair card with a synthetic XpubExportT-like object
    await showPairCard({
      kind: KIND_XPUB,
      xpub: raw,
      path: "m/44'/236'/0'",
      label: "Imported wallet",
      fingerprint: fp,
      network,
    });
  }

  $pasteXpubImport.addEventListener("click", () => {
    void onPasteXpubImport();
  });
  $pasteXpubClear.addEventListener("click", () => {
    $pasteXpub.value = "";
    setXpubStatus("");
    hidePairCard();
    $pasteXpub.focus();
  });

  return () => {
    releaseCamera();
    if (lastDownloadUrl) {
      URL.revokeObjectURL(lastDownloadUrl);
      lastDownloadUrl = null;
    }
  };
}
