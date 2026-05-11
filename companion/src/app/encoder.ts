/**
 * Multipart-QR encoder page.
 *
 * Takes a payload (text / hex / base64 / base64url), splits it via the
 * shared `encodeMultipartLines` (the same implementation `piwallet.qr`
 * uses on the Pi), then animates the resulting `PW1|…` lines as QR
 * codes on a canvas at a user-chosen frame rate.
 */
import QRCode from "qrcode";

import {
  DEFAULT_ENCODED_CHUNK_CHARS,
  MIN_ENCODED_CHUNK_CHARS,
  encodeMultipartLines,
} from "../pw1.js";

type InputMode = "text" | "hex" | "base64" | "base64url";

const SAMPLE =
  "Hello PiWallet — this is a multipart QR demo payload. " +
  "Type or paste anything (text, hex, base64) and watch it animate as PW1 frames.";

export function mountEncoderPage(root: HTMLElement): () => void {
  root.innerHTML = `
    <main class="page">
      <header class="page-header">
        <h1>Encode multipart QR<span class="brand"> · PiWallet companion</span></h1>
        <nav>
          <a href="#/encode" class="active">Encode</a>
          <a href="#/scan">Scan</a>
          <a href="#/loop">Loop</a>
        </nav>
      </header>

      <section class="card">
        <label for="payload">Payload</label>
        <textarea id="payload" rows="6"
          placeholder="Paste text, hex, or base64…"></textarea>

        <div class="row">
          <fieldset>
            <legend>Format</legend>
            <label><input type="radio" name="mode" value="text" checked /> text</label>
            <label><input type="radio" name="mode" value="hex" /> hex</label>
            <label><input type="radio" name="mode" value="base64" /> base64</label>
            <label><input type="radio" name="mode" value="base64url" /> base64url</label>
          </fieldset>

          <div class="slider">
            <span>Chunk chars: <strong id="chunkLabel">${DEFAULT_ENCODED_CHUNK_CHARS}</strong></span>
            <input id="chunk" type="range"
              min="${MIN_ENCODED_CHUNK_CHARS}" max="1000" step="16"
              value="${DEFAULT_ENCODED_CHUNK_CHARS}" />
          </div>

          <div class="slider">
            <span>Frames/sec: <strong id="fpsLabel">5</strong></span>
            <input id="fps" type="range" min="1" max="15" step="1" value="5" />
          </div>
        </div>
      </section>

      <section class="card qr-card">
        <canvas id="qr" width="320" height="320" aria-label="multipart QR frame"></canvas>
        <div class="qr-status">
          <p id="status">Frame —/— · 0 chars · 0 bytes</p>
          <div class="actions">
            <button id="start" class="primary" type="button">Start</button>
            <button id="stop" type="button">Stop</button>
          </div>
        </div>
      </section>
    </main>
  `;

  const $payload = root.querySelector<HTMLTextAreaElement>("#payload")!;
  const $chunk = root.querySelector<HTMLInputElement>("#chunk")!;
  const $fps = root.querySelector<HTMLInputElement>("#fps")!;
  const $chunkLabel = root.querySelector<HTMLElement>("#chunkLabel")!;
  const $fpsLabel = root.querySelector<HTMLElement>("#fpsLabel")!;
  const $canvas = root.querySelector<HTMLCanvasElement>("#qr")!;
  const $status = root.querySelector<HTMLElement>("#status")!;
  const $start = root.querySelector<HTMLButtonElement>("#start")!;
  const $stop = root.querySelector<HTMLButtonElement>("#stop")!;

  let lines: string[] = [];
  let frameIndex = 0;
  let lastFrameAt = 0;
  let rafHandle: number | null = null;
  let totalBytes = 0;

  function getMode(): InputMode {
    const checked = root.querySelector<HTMLInputElement>(
      'input[name="mode"]:checked',
    );
    return (checked?.value as InputMode) ?? "text";
  }

  function decodeInput(raw: string, mode: InputMode): Uint8Array {
    if (mode === "text") {
      return new TextEncoder().encode(raw);
    }
    if (mode === "hex") {
      const clean = raw.replace(/\s+/g, "").toLowerCase();
      if (clean.length === 0) return new Uint8Array();
      if (clean.length % 2 !== 0 || /[^0-9a-f]/.test(clean)) {
        throw new Error("invalid hex (need even number of [0-9a-f] chars)");
      }
      const out = new Uint8Array(clean.length / 2);
      for (let i = 0; i < out.length; i++) {
        out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
      }
      return out;
    }
    const cleanRaw = raw.replace(/\s+/g, "");
    if (cleanRaw.length === 0) return new Uint8Array();
    let b64 = cleanRaw;
    if (mode === "base64url") {
      b64 = cleanRaw.replace(/-/g, "+").replace(/_/g, "/");
    }
    const padLen = (4 - (b64.length % 4)) % 4;
    const padded = b64 + "=".repeat(padLen);
    let bin: string;
    try {
      bin = atob(padded);
    } catch (e) {
      throw new Error(`invalid ${mode}: ${(e as Error).message}`);
    }
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  async function paintFrame(i: number): Promise<void> {
    if (lines.length === 0) {
      const ctx = $canvas.getContext("2d");
      if (ctx) {
        ctx.fillStyle = "#0b0f15";
        ctx.fillRect(0, 0, $canvas.width, $canvas.height);
      }
      return;
    }
    const line = lines[i];
    await QRCode.toCanvas($canvas, line, {
      errorCorrectionLevel: "M",
      width: 320,
      margin: 1,
      color: { dark: "#000000", light: "#ffffff" },
    });
    $status.textContent =
      `Frame ${i + 1}/${lines.length} · ${line.length} chars · ${totalBytes} bytes`;
  }

  function rebuild(): void {
    const mode = getMode();
    const raw = $payload.value;
    const chunkSize = parseInt($chunk.value, 10);
    let bytes: Uint8Array;
    try {
      bytes = decodeInput(raw, mode);
    } catch (e) {
      lines = [];
      totalBytes = 0;
      $status.classList.add("error");
      $status.textContent = `error: ${(e as Error).message}`;
      void paintFrame(0);
      return;
    }
    $status.classList.remove("error");
    totalBytes = bytes.length;

    try {
      lines = encodeMultipartLines(bytes, chunkSize);
    } catch (e) {
      lines = [];
      $status.classList.add("error");
      $status.textContent = `error: ${(e as Error).message}`;
      void paintFrame(0);
      return;
    }

    frameIndex = 0;
    lastFrameAt = 0;
    void paintFrame(0);
  }

  function tick(now: number): void {
    if (lines.length === 0) {
      rafHandle = null;
      return;
    }
    const fps = Math.max(1, parseInt($fps.value, 10));
    const interval = 1000 / fps;
    if (now - lastFrameAt >= interval) {
      lastFrameAt = now;
      void paintFrame(frameIndex);
      frameIndex = (frameIndex + 1) % lines.length;
    }
    rafHandle = requestAnimationFrame(tick);
  }

  function start(): void {
    if (rafHandle !== null) return;
    if (lines.length === 0) rebuild();
    if (lines.length === 0) return;
    lastFrameAt = 0;
    rafHandle = requestAnimationFrame(tick);
    $start.disabled = true;
    $stop.disabled = false;
  }

  function stop(): void {
    if (rafHandle !== null) cancelAnimationFrame(rafHandle);
    rafHandle = null;
    $start.disabled = false;
    $stop.disabled = true;
  }

  $payload.addEventListener("input", rebuild);
  for (const r of root.querySelectorAll<HTMLInputElement>('input[name="mode"]')) {
    r.addEventListener("change", rebuild);
  }
  $chunk.addEventListener("input", () => {
    $chunkLabel.textContent = $chunk.value;
    rebuild();
  });
  $fps.addEventListener("input", () => {
    $fpsLabel.textContent = $fps.value;
  });
  $start.addEventListener("click", start);
  $stop.addEventListener("click", stop);
  $stop.disabled = true;

  $payload.value = SAMPLE;
  rebuild();

  return () => {
    stop();
  };
}
