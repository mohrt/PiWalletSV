/**
 * Theme preference — dark, light, or follow system.
 */
import { KEY_THEME, type ThemePreference, getThemePreference } from "./companion-settings.js";

export { type ThemePreference, getThemePreference } from "./companion-settings.js";

const MEDIA = "(prefers-color-scheme: light)";

function resolvedTheme(pref: ThemePreference): "dark" | "light" {
  if (pref === "light") return "light";
  if (pref === "dark") return "dark";
  try {
    return window.matchMedia(MEDIA).matches ? "light" : "dark";
  } catch {
    return "dark";
  }
}

/** Apply theme to document root (call on boot and when preference changes). */
export function applyTheme(pref?: ThemePreference): void {
  const theme = resolvedTheme(pref ?? getThemePreference());
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;

  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) {
    meta.content = theme === "light" ? "#f4f6f9" : "#0b0f15";
  }
}

let mediaListener: ((e: MediaQueryListEvent) => void) | null = null;

/** Watch system theme when preference is "system". Returns cleanup. */
export function watchSystemTheme(): () => void {
  if (mediaListener) return () => {};
  try {
    const mq = window.matchMedia(MEDIA);
    mediaListener = () => {
      if (getThemePreference() === "system") applyTheme("system");
    };
    mq.addEventListener("change", mediaListener);
    return () => {
      mq.removeEventListener("change", mediaListener!);
      mediaListener = null;
    };
  } catch {
    return () => {};
  }
}

export function setThemePreference(pref: ThemePreference): void {
  try {
    localStorage.setItem(KEY_THEME, pref);
  } catch { /* private mode */ }
  applyTheme(pref);
}
