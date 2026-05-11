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

import { MultipartAssembler, MultipartQrError } from "../pw1.js";

const SCAN_INTERVAL_MS = 80; // ~12.5 fps; plenty for animated QR
const HEX_PREVIEW_BYTES = 64;

export function mountScannerPage(root: HTMLElement): () => void {
  root.innerHTML = `
    <main class="page">
      <header class="page-header">
        <h1>Scan multipart QR<span class="brand"> · PiWallet companion</span></h1>
        <nav>
          <a href="#/encode">Encode</a>
          <a href="#/scan" class="active">Scan</a>
        </nav>
      </header>

      <section class="card scan-card">
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

      <section id="resultCard" class="card" hidden>
        <label for="resultHex">Reassembled payload</label>
        <textarea id="resultHex" rows="6" readonly
          spellcheck="false" autocorrect="off"></textarea>
        <p id="resultMeta" class="muted-line"></p>
        <div class="actions">
          <button id="download" class="primary" type="button">Download .bin</button>
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
  const $resultHex = root.querySelector<HTMLTextAreaElement>("#resultHex")!;
  const $resultMeta = root.querySelector<HTMLElement>("#resultMeta")!;
  const $download = root.querySelector<HTMLButtonElement>("#download")!;
  const $copyB64 = root.querySelector<HTMLButtonElement>("#copyB64")!;

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
  let lastDownloadUrl: string | null = null;

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

  function bytesToHexPreview(bytes: Uint8Array): string {
    const slice = bytes.subarray(0, HEX_PREVIEW_BYTES);
    let hex = "";
    for (const b of slice) hex += b.toString(16).padStart(2, "0");
    return bytes.length > HEX_PREVIEW_BYTES ? `${hex}…` : hex;
  }

  function bytesToBase64Url(bytes: Uint8Array): string {
    let s = "";
    const block = 0x8000;
    for (let i = 0; i < bytes.length; i += block) {
      s += String.fromCharCode(...bytes.subarray(i, i + block));
    }
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function showResult(bytes: Uint8Array): void {
    result = bytes;
    $resultHex.value = bytesToHexPreview(bytes);
    $resultMeta.textContent = `${bytes.length} bytes · sha-like preview shown above`;
    $resultCard.hidden = false;
    $reset.disabled = false;
    setStatus(`complete — reassembled ${bytes.length} bytes`);
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
      showResult(out);
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
    $resultCard.hidden = true;
    $resultHex.value = "";
    $resultMeta.textContent = "";
    $missing.textContent = "";
    $reset.disabled = true;
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

  async function copyBase64(): Promise<void> {
    if (!result) return;
    const b64 = bytesToBase64Url(result);
    try {
      await navigator.clipboard.writeText(b64);
      $copyB64.textContent = "copied!";
      setTimeout(() => {
        $copyB64.textContent = "Copy base64url";
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
    void copyBase64();
  });

  return () => {
    releaseCamera();
    if (lastDownloadUrl) {
      URL.revokeObjectURL(lastDownloadUrl);
      lastDownloadUrl = null;
    }
  };
}
