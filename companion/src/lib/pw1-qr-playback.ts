/**
 * Animate a PW1 multipart QR sequence on a canvas.
 *
 * Shared by wallet export (Advanced tab) and Settings backup transfer.
 */
import QRCode from "qrcode";

import { PW1_QR_FRAME_MS } from "./config.js";

export interface Pw1QrPlayback {
  pause(): void;
  resume(): void;
  stop(): void;
  isRunning(): boolean;
}

export function clearPw1QrCanvas(canvas: HTMLCanvasElement): void {
  const ctx = canvas.getContext("2d");
  if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
}

export async function startPw1QrPlayback(
  canvas: HTMLCanvasElement,
  frames: string[],
  opts: {
    width?: number;
    onFrame?: (index: number, total: number) => void;
  } = {},
): Promise<Pw1QrPlayback> {
  const width = opts.width ?? 320;
  let frameIdx = 0;
  let lastFrameAt = 0;
  let raf: number | null = null;
  let stopped = false;

  async function drawFrame(): Promise<void> {
    const payload = frames[frameIdx];
    opts.onFrame?.(frameIdx + 1, frames.length);
    await QRCode.toCanvas(canvas, payload, {
      width,
      margin: 1,
      errorCorrectionLevel: "M",
    });
    frameIdx = (frameIdx + 1) % frames.length;
  }

  function tick(now: number): void {
    if (raf === null || stopped) return;
    if (now - lastFrameAt >= PW1_QR_FRAME_MS) {
      lastFrameAt = now;
      void drawFrame();
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
    if (frames.length === 0 || raf !== null || stopped) return;
    lastFrameAt = 0;
    await drawFrame();
    raf = requestAnimationFrame(tick);
  }

  function pause(): void {
    if (raf !== null) {
      cancelAnimationFrame(raf);
      raf = null;
    }
  }

  stopped = false;
  await resume();

  return {
    pause,
    resume: () => { void resume(); },
    stop,
    isRunning: () => raf !== null,
  };
}
