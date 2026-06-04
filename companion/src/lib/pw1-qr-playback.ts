/**
 * Animate a PW1 multipart QR sequence on a canvas.
 *
 * Shared by Send proposal QR, Advanced xpub export, and Settings backup
 * transfer. Respects `prefers-reduced-motion` with manual frame stepping.
 */
import QRCode from "qrcode";

import { PW1_QR_FRAME_MS } from "./config.js";
import { prefersReducedMotion } from "./motion-prefs.js";

export interface Pw1QrPlayback {
  pause(): void;
  resume(): void;
  stop(): void;
  isRunning(): boolean;
  /** Manual stepping mode (no auto-cycle). */
  isManual(): boolean;
  step(delta: -1 | 1): Promise<void>;
  frameIndex(): number;
  frameCount(): number;
}

export interface Pw1QrControlElements {
  autoToggle: HTMLButtonElement;
  prev: HTMLButtonElement;
  next: HTMLButtonElement;
  hint?: HTMLElement | null;
  /** Shown when auto-animate is active. */
  autoHint?: string;
  /** Shown when manual stepping is active. */
  manualHint?: string;
}

const DEFAULT_AUTO_HINT = "Point the Pi camera at this animated QR.";
const DEFAULT_MANUAL_HINT =
  "Use Previous / Next to step through frames for the Pi camera.";

export function clearPw1QrCanvas(canvas: HTMLCanvasElement): void {
  const ctx = canvas.getContext("2d");
  if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
}

/** Show Pause vs Prev/Next based on playback mode. */
export function syncPw1QrControlVisibility(
  playback: Pw1QrPlayback,
  els: Pw1QrControlElements,
): void {
  const manual = playback.isManual();
  els.autoToggle.hidden = manual;
  els.prev.hidden = !manual;
  els.next.hidden = !manual;
  if (els.hint) {
    els.hint.textContent = manual
      ? (els.manualHint ?? DEFAULT_MANUAL_HINT)
      : (els.autoHint ?? DEFAULT_AUTO_HINT);
  }
}

/** Wire Pause/Resume or Prev/Next for a PW1 QR playback instance. */
export function wirePw1QrControls(
  playback: Pw1QrPlayback,
  els: Pw1QrControlElements,
): () => void {
  syncPw1QrControlVisibility(playback, els);

  const onAutoToggle = (): void => {
    if (playback.isManual()) return;
    if (playback.isRunning()) {
      playback.pause();
      els.autoToggle.textContent = "Resume";
    } else {
      playback.resume();
      els.autoToggle.textContent = "Pause";
    }
  };

  const onPrev = (): void => {
    void playback.step(-1);
  };

  const onNext = (): void => {
    void playback.step(1);
  };

  els.autoToggle.addEventListener("click", onAutoToggle);
  els.prev.addEventListener("click", onPrev);
  els.next.addEventListener("click", onNext);

  return () => {
    els.autoToggle.removeEventListener("click", onAutoToggle);
    els.prev.removeEventListener("click", onPrev);
    els.next.removeEventListener("click", onNext);
  };
}

export async function startPw1QrPlayback(
  canvas: HTMLCanvasElement,
  frames: string[],
  opts: {
    width?: number;
    manual?: boolean;
    onFrame?: (index: number, total: number) => void;
  } = {},
): Promise<Pw1QrPlayback> {
  const width = opts.width ?? 320;
  const manual = opts.manual ?? prefersReducedMotion();
  let frameIdx = 0;
  let lastFrameAt = 0;
  let raf: number | null = null;
  let stopped = false;

  async function renderCurrent(): Promise<void> {
    if (frames.length === 0) return;
    const payload = frames[frameIdx]!;
    opts.onFrame?.(frameIdx + 1, frames.length);
    await QRCode.toCanvas(canvas, payload, {
      width,
      margin: 1,
      errorCorrectionLevel: "M",
    });
  }

  async function advanceAuto(): Promise<void> {
    await renderCurrent();
    frameIdx = (frameIdx + 1) % frames.length;
  }

  function tick(now: number): void {
    if (raf === null || stopped) return;
    if (now - lastFrameAt >= PW1_QR_FRAME_MS) {
      lastFrameAt = now;
      void advanceAuto();
    }
    raf = requestAnimationFrame(tick);
  }

  function stop(): void {
    stopped = true;
    if (raf !== null) {
      cancelAnimationFrame(raf);
      raf = null;
    }
  }

  async function resume(): Promise<void> {
    if (manual || frames.length === 0 || raf !== null || stopped) return;
    lastFrameAt = 0;
    await advanceAuto();
    raf = requestAnimationFrame(tick);
  }

  function pause(): void {
    if (raf !== null) {
      cancelAnimationFrame(raf);
      raf = null;
    }
  }

  async function step(delta: -1 | 1): Promise<void> {
    if (frames.length === 0) return;
    frameIdx = (frameIdx + delta + frames.length) % frames.length;
    await renderCurrent();
  }

  stopped = false;
  if (manual) {
    await renderCurrent();
  } else {
    await resume();
  }

  return {
    pause,
    resume: () => { void resume(); },
    stop,
    isRunning: () => raf !== null,
    isManual: () => manual,
    step,
    frameIndex: () => frameIdx,
    frameCount: () => frames.length,
  };
}
