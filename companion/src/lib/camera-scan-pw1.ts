/**
 * PW1 multipart camera scanner — reusable utility for scanning an animated
 * PW1 QR sequence from a caller-supplied <video> element.
 */
import jsQR from "jsqr";
import { MultipartAssembler, MultipartQrError } from "../pw1.js";

const DEFAULT_SCAN_INTERVAL_MS = 100;

export interface Pw1ScanProgress {
  received: number;
  total: number | null;
  missingIndices: number[];
}

export interface Pw1ScanHandle {
  stop(): void;
  resetAssembler(): void;
}

export type Pw1ScanResultHandler = (
  bytes: Uint8Array,
) => boolean | void | Promise<boolean | void>;

function missingFragmentIndices(asm: MultipartAssembler, cap = 16): number[] {
  const total = asm.expectedTotal;
  if (total === null) return [];
  const have = new Set(asm.receivedIndices);
  const missing: number[] = [];
  for (let i = 0; i < total && missing.length < cap; i++) {
    if (!have.has(i)) missing.push(i);
  }
  return missing;
}

function emitProgress(
  asm: MultipartAssembler,
  onProgress: (progress: Pw1ScanProgress) => void,
): void {
  onProgress({
    received: asm.partsReceived,
    total: asm.expectedTotal,
    missingIndices: missingFragmentIndices(asm),
  });
}

export async function startPw1Scan(
  videoEl: HTMLVideoElement,
  onProgress: (progress: Pw1ScanProgress) => void,
  onResult: Pw1ScanResultHandler,
  onError: (msg: string) => void,
  options?: {
    scanIntervalMs?: number;
    onPw1Error?: (msg: string) => void;
  },
): Promise<Pw1ScanHandle> {
  if (!navigator.mediaDevices?.getUserMedia) {
    onError("camera unavailable: needs HTTPS or localhost");
    return { stop: () => {}, resetAssembler: () => {} };
  }

  const scanIntervalMs = options?.scanIntervalMs ?? DEFAULT_SCAN_INTERVAL_MS;
  let stream: MediaStream | null = null;
  let rafHandle: number | null = null;
  let done = false;
  let lastScanAt = 0;
  let asm = new MultipartAssembler();
  let resolving = false;

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

  function resetAssembler() {
    asm.reset();
    emitProgress(asm, onProgress);
  }

  async function handleComplete(out: Uint8Array) {
    if (resolving) return;
    resolving = true;
    try {
      const accepted = await onResult(out);
      if (accepted === false) {
        resetAssembler();
        resolving = false;
        return;
      }
      release();
    } catch (e) {
      resolving = false;
      onError((e as Error).message);
    }
  }

  function tick(now: number) {
    if (done || resolving) {
      if (!done) rafHandle = requestAnimationFrame(tick);
      return;
    }
    if (
      now - lastScanAt >= scanIntervalMs &&
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
              options?.onPw1Error?.(e.message);
              resetAssembler();
            }
          }
          if (out !== null) {
            // Completing frame: show N/N before validation/import (can take seconds).
            emitProgress(asm, onProgress);
            void handleComplete(out);
          } else {
            emitProgress(asm, onProgress);
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
    return { stop: () => {}, resetAssembler: () => {} };
  }

  videoEl.srcObject = stream;
  await new Promise<void>((resolve) => {
    if (videoEl.readyState >= 1) { resolve(); return; }
    videoEl.addEventListener("loadedmetadata", () => resolve(), { once: true });
  });
  try { await videoEl.play(); } catch { /* AbortError on rapid teardown is benign */ }

  emitProgress(asm, onProgress);
  rafHandle = requestAnimationFrame(tick);
  return { stop: release, resetAssembler };
}
