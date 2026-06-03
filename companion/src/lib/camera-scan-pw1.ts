/**
 * PW1 multipart camera scanner — reusable utility for scanning an animated
 * PW1 QR sequence from a caller-supplied <video> element.
 *
 * Feeds frames through jsQR + MultipartAssembler. Calls onResult with the
 * fully reassembled bytes, then stops automatically. Call handle.stop() to
 * cancel early.
 */
import jsQR from "jsqr";
import { MultipartAssembler, MultipartQrError, pw1LineMeta } from "../pw1.js";

const SCAN_INTERVAL_MS = 100;

export interface Pw1ScanHandle {
  stop(): void;
}

export async function startPw1Scan(
  videoEl: HTMLVideoElement,
  onProgress: (received: number, total: number | null) => void,
  onResult: (bytes: Uint8Array) => void,
  onError: (msg: string) => void,
): Promise<Pw1ScanHandle> {
  if (!navigator.mediaDevices?.getUserMedia) {
    onError("camera unavailable: needs HTTPS or localhost");
    return { stop: () => {} };
  }

  let stream: MediaStream | null = null;
  let rafHandle: number | null = null;
  let done = false;
  let lastScanAt = 0;
  let asm = new MultipartAssembler();

  const offscreen = document.createElement("canvas");
  const offscreenCtx = offscreen.getContext("2d", { willReadFrequently: true });

  function release() {
    done = true;
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle);
      rafHandle = null;
    }
    if (stream) {
      for (const t of stream.getTracks()) t.stop();
      stream = null;
    }
    videoEl.srcObject = null;
  }

  function tick(now: number) {
    if (done) return;
    if (
      now - lastScanAt >= SCAN_INTERVAL_MS &&
      videoEl.readyState >= 2 &&
      videoEl.videoWidth > 0 &&
      offscreenCtx
    ) {
      lastScanAt = now;
      const w = videoEl.videoWidth;
      const h = videoEl.videoHeight;
      offscreen.width = w;
      offscreen.height = h;
      offscreenCtx.drawImage(videoEl, 0, 0, w, h);
      const img = offscreenCtx.getImageData(0, 0, w, h);
      const code = jsQR(img.data, img.width, img.height, {
        inversionAttempts: "dontInvert",
      });
      if (code?.data) {
        const trimmed = code.data.trim();
        if (trimmed.startsWith("PW1|")) {
          let out: Uint8Array | null = null;
          try {
            out = asm.feed(trimmed);
          } catch (e) {
            if (e instanceof MultipartQrError) {
              asm = new MultipartAssembler();
            }
          }
          const meta = pw1LineMeta(trimmed);
          if (out !== null && meta) {
            onProgress(meta[0], meta[0]);
          } else {
            onProgress(asm.partsReceived, asm.expectedTotal);
          }
          if (out !== null) {
            release();
            onResult(out);
            return;
          }
        }
      }
    }
    rafHandle = requestAnimationFrame(tick);
  }

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
  } catch (e) {
    const err = e as DOMException;
    const map: Record<string, string> = {
      NotAllowedError: "camera permission denied",
      NotFoundError: "no camera found on this device",
      NotReadableError: "camera in use by another app",
      OverconstrainedError: "camera constraints failed",
    };
    onError(map[err.name] ?? `camera error: ${err.message ?? err.name}`);
    return { stop: () => {} };
  }

  videoEl.srcObject = stream;
  await new Promise<void>((resolve) => {
    if (videoEl.readyState >= 1) { resolve(); return; }
    videoEl.addEventListener("loadedmetadata", () => resolve(), { once: true });
  });
  try { await videoEl.play(); } catch { /* AbortError on rapid teardown is benign */ }

  rafHandle = requestAnimationFrame(tick);
  return { stop: release };
}
