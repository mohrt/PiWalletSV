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
import jsQR from "jsqr";

import {
  type Envelope,
  KIND_PROPOSAL,
  KIND_SIGNED,
  KIND_XPUB,
  type XpubExportT,
  atomicBeefTxid,
  bytesToHex,
  decodeEnvelope,
} from "../lib/envelope.js";
import { xpubFingerprint, DerivationError } from "../lib/derive.js";
import { renderHeader } from "./nav.js";
import { getDefaultNetwork } from "./settings-page.js";
import { MultipartAssembler, MultipartQrError } from "../pw1.js";
import {
  type WalletRecord,
  WalletStoreError,
  addWallet,
  findByFingerprintAndPath,
} from "../lib/wallets.js";
import { ENVELOPE_VERSION } from "../lib/envelope.js";
import type { NetworkT } from "../lib/envelope.js";

const SCAN_INTERVAL_MS = 80; // ~12.5 fps; plenty for animated QR
const TEXT_DISPLAY_CAP = 64 * 1024; // truncate displayed body for huge payloads

type ViewMode = "text" | "hex" | "base64url";

export function mountScannerPage(root: HTMLElement): () => void {
  root.innerHTML = `
    <main class="page">
      ${renderHeader("Add wallet", "wallets")}

      <section class="card scan-card">
        <p class="muted-line scan-card-desc">Scan xpub from the Pi or another companion wallet.</p>
        <video id="video" playsinline muted autoplay></video>
        <div class="scan-status">
          <p id="status" aria-live="polite">camera idle — click Start to grant access</p>
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
          <summary>Or paste xpub</summary>
          <p class="muted-line">
            Paste the xpub below, and select the network.
            <span class="info-tip-wrap">
              <button class="info-tip" type="button" aria-label="What is an xpub?">ⓘ</button>
              <span class="info-tip-text" hidden>
                An xpub (extended public key) lets the companion derive your wallet
                addresses without exposing your private keys or seed phrase.
              </span>
            </span>
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

    <div id="pairOverlay" class="pair-overlay" hidden role="dialog"
      aria-modal="true" aria-labelledby="pairDialogTitle">
      <div class="pair-modal card pair-card">
        <h2 id="pairDialogTitle">Save as paired wallet</h2>
        <p id="pairStatus" class="muted-line" aria-live="polite"></p>
        <label class="field-label" for="pairLabel">Wallet label</label>
        <input id="pairLabel" type="text" maxlength="64"
          autocomplete="off" autocorrect="off" spellcheck="false" />
        <p id="pairFp" class="muted-line"></p>
        <div class="actions">
          <button id="pairSave" class="primary" type="button">Save wallet</button>
          <button id="pairDismiss" type="button">Cancel</button>
          <a id="pairOpenList" href="#/wallets" hidden>Open wallets list</a>
        </div>
      </div>
    </div>
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
  $pasteXpubNetwork.value = getDefaultNetwork();
  const $pasteXpubImport = root.querySelector<HTMLButtonElement>("#pasteXpubImport")!;
  const $pasteXpubClear = root.querySelector<HTMLButtonElement>("#pasteXpubClear")!;
  const $pasteXpubStatus = root.querySelector<HTMLElement>("#pasteXpubStatus")!;
  const $pairOverlay = root.querySelector<HTMLElement>("#pairOverlay")!;
  const $pairStatus = root.querySelector<HTMLElement>("#pairStatus")!;
  const $pairLabel = root.querySelector<HTMLInputElement>("#pairLabel")!;
  const $pairFp = root.querySelector<HTMLElement>("#pairFp")!;
  const $pairSave = root.querySelector<HTMLButtonElement>("#pairSave")!;
  const $pairDismiss = root.querySelector<HTMLButtonElement>("#pairDismiss")!;
  const $pairOpenList = root.querySelector<HTMLAnchorElement>("#pairOpenList")!;

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
  let pairFocusBefore: HTMLElement | null = null;

  function focusableIn(container: HTMLElement): HTMLElement[] {
    return Array.from(
      container.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), textarea, select, [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => !el.hidden && (el.offsetParent !== null || el === document.activeElement));
  }

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
    $pairOverlay.hidden = true;
    document.body.classList.remove("pair-locked");
    pairFocusBefore?.focus();
    pairFocusBefore = null;
    $pairStatus.classList.remove("error");
    $pairStatus.textContent = "";
    $pairFp.textContent = "";
    $pairLabel.value = "";
    $pairLabel.disabled = false;
    $pairSave.disabled = false;
    $pairSave.textContent = "Save wallet";
    $pairOpenList.hidden = true;
  }

  async function showPairCard(env: XpubExportT): Promise<void> {
    pairXpub = env;
    const fpHex = bytesToHex(env.fingerprint);
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
      $pairOverlay.hidden = false;
      document.body.classList.add("pair-locked");
      pairFocusBefore = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      $pairDismiss.focus();
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

    $pairOverlay.hidden = false;
    document.body.classList.add("pair-locked");
    pairFocusBefore = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    if (existing && sameNetworkDup) {
      $pairDismiss.focus();
    } else {
      $pairLabel.focus();
      $pairLabel.select();
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
      $resultCard.hidden = true;
    } else {
      hidePairCard();
    }

    if (envelope?.kind === KIND_SIGNED) {
      setStatus(
        "Signed tx detected — open Wallets → your wallet → Send → Step 2 to scan or paste the Pi response.",
        false,
      );
    }

    const defaultView: ViewMode = looksLikeText(bytes) ? "text" : "hex";
    for (const r of root.querySelectorAll<HTMLInputElement>(
      'input[name="view"]',
    )) {
      r.checked = r.value === defaultView;
    }
    renderResultView();
    $resultCard.hidden = envelope?.kind === KIND_XPUB;
    $reset.disabled = false;
    let tag: string;
    if (!envelope) {
      tag = `complete — reassembled ${bytes.length} bytes`;
    } else if (envelope.kind === KIND_SIGNED) {
      tag = `signed_tx (${bytes.length} bytes) — use Send → Step 2 in your wallet`;
    } else if (envelope.kind === KIND_XPUB) {
      tag = `complete — xpub_export (${bytes.length} bytes)`;
    } else if (envelope.kind === KIND_PROPOSAL) {
      tag = `complete — unsigned_proposal (${bytes.length} bytes)`;
    } else {
      tag = `complete — envelope (${bytes.length} bytes)`;
    }
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
  $pairDismiss.addEventListener("click", hidePairCard);
  $pairOverlay.addEventListener("click", (e) => {
    if (e.target === $pairOverlay) hidePairCard();
  });
  $pairOverlay.addEventListener("keydown", (e) => {
    const ke = e as KeyboardEvent;
    if (ke.key === "Escape") {
      ke.preventDefault();
      hidePairCard();
      return;
    }
    if (ke.key !== "Tab") return;
    const modal = $pairOverlay.querySelector<HTMLElement>(".pair-modal");
    if (!modal) return;
    const items = focusableIn(modal);
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (ke.shiftKey && document.activeElement === first) {
      ke.preventDefault();
      last.focus();
    } else if (!ke.shiftKey && document.activeElement === last) {
      ke.preventDefault();
      first.focus();
    }
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

    setXpubStatus("xpub valid — fill in a label in the dialog.");

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

  // xpub info tip toggle
  root.querySelector<HTMLButtonElement>(".info-tip")
    ?.addEventListener("click", (e) => {
      e.preventDefault();
      const tip = root.querySelector<HTMLElement>(".info-tip-text");
      if (tip) tip.hidden = !tip.hidden;
    });

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
    hidePairCard();
    if (lastDownloadUrl) {
      URL.revokeObjectURL(lastDownloadUrl);
      lastDownloadUrl = null;
    }
  };
}
