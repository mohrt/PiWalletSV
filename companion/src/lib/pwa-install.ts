/**
 * PWA install detection and optional Chromium install prompt capture.
 */

export const KEY_INSTALL_DISMISSED = "piwallet.installPromptDismissed";

export type InstallPlatform = "ios" | "chromium" | "other";

export type InstallPromptOutcome = "accepted" | "dismissed" | "unavailable";

/** Minimal shape of the non-standard beforeinstallprompt event. */
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferredInstallPrompt: BeforeInstallPromptEvent | null = null;

/** True when the app is already running as an installed PWA. */
export function isStandalonePwa(): boolean {
  if (typeof window === "undefined") return false;
  const nav = navigator as Navigator & { standalone?: boolean };
  if (nav.standalone === true) return true;
  if (typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(display-mode: standalone)").matches;
}

/** Rough platform hint for install copy and controls. */
export function detectInstallPlatform(): InstallPlatform {
  if (typeof navigator === "undefined") return "other";
  const ua = navigator.userAgent;
  const isIos =
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (isIos) return "ios";
  if (deferredInstallPrompt !== null) return "chromium";
  if (/Chrome|Chromium|Edg|OPR|Brave/i.test(ua) && !/iPhone|iPad|iPod/i.test(ua)) {
    return "chromium";
  }
  return "other";
}

export function isInstallPromptDismissed(): boolean {
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(KEY_INSTALL_DISMISSED) === "1";
}

export function dismissInstallPrompt(): void {
  localStorage.setItem(KEY_INSTALL_DISMISSED, "1");
}

/** Whether the wallets-page install banner should render. */
export function shouldShowInstallBanner(): boolean {
  if (isStandalonePwa()) return false;
  if (isInstallPromptDismissed()) return false;
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    if (window.matchMedia("(min-width: 768px)").matches) return false;
  }
  return true;
}

/** Whether Chromium can show the native install sheet right now. */
export function canPromptInstall(): boolean {
  return deferredInstallPrompt !== null;
}

/** Listen for beforeinstallprompt; call from main.ts on boot. */
export function captureInstallPrompt(): () => void {
  if (typeof window === "undefined") return () => {};

  const handler = (ev: Event): void => {
    // Only defer when our in-app banner can use it (mobile/narrow viewport).
    // On desktop, skipping preventDefault avoids Chrome's console warning and
    // leaves install to the browser menu / omnibox affordance.
    if (!shouldShowInstallBanner()) return;
    ev.preventDefault();
    deferredInstallPrompt = ev as BeforeInstallPromptEvent;
  };

  window.addEventListener("beforeinstallprompt", handler);
  return () => {
    window.removeEventListener("beforeinstallprompt", handler);
  };
}

/** Open the native install prompt when available (Chromium). */
export async function promptInstall(): Promise<InstallPromptOutcome> {
  const prompt = deferredInstallPrompt;
  if (!prompt) return "unavailable";
  try {
    await prompt.prompt();
    const { outcome } = await prompt.userChoice;
    if (outcome === "accepted") {
      deferredInstallPrompt = null;
    }
    return outcome;
  } catch {
    return "unavailable";
  }
}

/** Test-only reset of captured prompt. */
export function _resetInstallPromptForTests(): void {
  deferredInstallPrompt = null;
}
