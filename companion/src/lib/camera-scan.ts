/**
 * Lightweight single-QR camera scanner.
 */
import jsQR from "jsqr";

const SCAN_INTERVAL_MS = 150;

export interface CameraScanHandle {
  stop(): void;
}

export type CameraScanResultHandler = (
  raw: string,
) => boolean | void | Promise<boolean | void>;

export async function startCameraScan(
  videoEl: HTMLVideoElement,
  onResult: CameraScanResultHandler,
  onError: (msg: string) => void,
): Promise<CameraScanHandle> {
  if (!navigator.mediaDevices?.getUserMedia) {
    onError("camera unavailable: needs HTTPS or localhost");
    return { stop: () => {} };
  }

  let stream: MediaStream | null = null;
  let rafHandle: number | null = null;
  let done = false;
  let lastScanAt = 0;
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

  async function handleDecode(raw: string) {
    if (resolving) return;
    resolving = true;
    try {
      const accepted = await onResult(raw);
      if (accepted === false) {
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
        void handleDecode(code.data);
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
  try {
    await videoEl.play();
  } catch {
    // AbortError on rapid teardown is benign
  }

  rafHandle = requestAnimationFrame(tick);
  return { stop: release };
}
