import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("qrcode", () => ({
  default: {
    toCanvas: vi.fn().mockResolvedValue(undefined),
  },
}));

import QRCode from "qrcode";

import { prefersReducedMotion } from "../src/lib/motion-prefs.js";
import { startPw1QrPlayback } from "../src/lib/pw1-qr-playback.js";

function fakeCanvas(): HTMLCanvasElement {
  return {
    width: 320,
    height: 320,
    getContext: () => null,
  } as unknown as HTMLCanvasElement;
}

describe("pw1-qr-playback reduced motion", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("manual mode does not auto-run and step() advances frames", async () => {
    const onFrame = vi.fn();
    const playback = await startPw1QrPlayback(
      fakeCanvas(),
      ["PW1|1|2|aa", "PW1|2|2|bb"],
      { manual: true, onFrame },
    );

    expect(playback.isManual()).toBe(true);
    expect(playback.isRunning()).toBe(false);
    expect(playback.frameIndex()).toBe(0);
    expect(onFrame).toHaveBeenCalledWith(1, 2);
    expect(QRCode.toCanvas).toHaveBeenCalledTimes(1);

    await playback.step(1);
    expect(playback.frameIndex()).toBe(1);
    expect(onFrame).toHaveBeenLastCalledWith(2, 2);
    expect(QRCode.toCanvas).toHaveBeenCalledTimes(2);

    await playback.step(-1);
    expect(playback.frameIndex()).toBe(0);
  });

  it("auto mode starts the animation loop", async () => {
    vi.stubGlobal(
      "requestAnimationFrame",
      (cb: FrameRequestCallback) => {
        setTimeout(() => cb(performance.now()), 0);
        return 1;
      },
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());

    const playback = await startPw1QrPlayback(
      fakeCanvas(),
      ["PW1|1|1|aa"],
      { manual: false },
    );

    expect(playback.isManual()).toBe(false);
    expect(playback.isRunning()).toBe(true);
    playback.stop();
    expect(playback.isRunning()).toBe(false);
  });

  it("uses prefers-reduced-motion when manual is omitted", async () => {
    vi.stubGlobal("window", {
      matchMedia: (query: string) => ({
        matches: query === "(prefers-reduced-motion: reduce)",
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    });

    expect(prefersReducedMotion()).toBe(true);

    const playback = await startPw1QrPlayback(fakeCanvas(), ["PW1|1|1|aa"]);
    expect(playback.isManual()).toBe(true);
    expect(playback.isRunning()).toBe(false);
  });
});
