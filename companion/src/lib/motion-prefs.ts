/**
 * OS-level motion preferences (accessibility).
 *
 * Used to switch PW1 QR playback from auto-cycle to manual frame stepping
 * without changing behavior for users who leave Reduce Motion off.
 */

const QUERY = "(prefers-reduced-motion: reduce)";

/** True when the user prefers reduced motion at the OS level. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(QUERY).matches;
}

/** Subscribe to Reduce Motion changes (e.g. user toggles in Settings mid-session). */
export function onReducedMotionChange(
  listener: (reduced: boolean) => void,
): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => {};
  }
  const mq = window.matchMedia(QUERY);
  const handler = (): void => listener(mq.matches);
  mq.addEventListener("change", handler);
  return () => mq.removeEventListener("change", handler);
}
