/**
 * Build-time configuration for the companion.
 *
 * The companion is split across two hosts:
 *   - this app           → app.piwalletsv.com  (or app.dev.piwalletsv.com)
 *   - marketing/docs     →     piwalletsv.com  (or     dev.piwalletsv.com)
 *
 * Cross-domain links from the app into the docs (footer, "Why is
 * this safe?", terms-modal pointers) need to land in the same
 * environment the user is currently in — a visitor on the dev mirror
 * shouldn't get bounced into prod docs and vice versa.
 *
 * `DOCS_BASE_URL` is resolved at **build** time from
 * `VITE_DOCS_BASE_URL` (Vite inlines `import.meta.env.*` at compile
 * time, so there's no runtime config fetch and no need for the dev
 * server to know about deployment).
 *
 * Defaults to the canonical prod host so:
 *   - `npm run build` without env overrides produces a prod-ready bundle
 *   - `npm run dev` (local dev server) sends Docs links to canonical
 *     prod docs (which is the public-facing reference a developer
 *     would expect to see)
 *
 * publish.sh sets `VITE_DOCS_BASE_URL=https://dev.piwalletsv.com` for
 * `--env dev` builds and leaves it unset for `--env prod`.
 */
export const DOCS_BASE_URL: string =
  import.meta.env.VITE_DOCS_BASE_URL ?? "https://piwalletsv.com";

/** `${DOCS_BASE_URL}/<path>` with no double slashes. */
export function docsUrl(path = ""): string {
  const trimmed = path.replace(/^\/+/, "");
  return trimmed ? `${DOCS_BASE_URL}/${trimmed}` : `${DOCS_BASE_URL}/`;
}

/**
 * How many transaction history entries to show in the History tab
 * before offering a "load more" button.
 */
export const HISTORY_PAGE_SIZE = 50;

/**
 * Price cache TTL in milliseconds. The fiat toggle fetches the BSV/USD
 * rate from WoC and caches it this long before re-fetching.
 */
export const PRICE_CACHE_TTL_MS = 60_000;
