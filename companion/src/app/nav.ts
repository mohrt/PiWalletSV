/**
 * Shared top-of-page header for every operational route.
 *
 * The companion only has two real surfaces in the post-split layout:
 *
 *   - `#/wallets`               (also used for `#/wallets/<id>` detail)
 *   - `#/scan`                  (pair wallet — camera or paste xpub; reached from Wallets CTA)
 *
 * Marketing-flavoured pages (front-page explainer, security briefing,
 * disclaimer, encoder playground) live on the docs site (URL fixed at
 * build time via VITE_DOCS_BASE_URL — see `lib/config.ts`). The `Docs`
 * link in the header is an external pointer; the rest of the header
 * stays inside the app's hash router.
 *
 * Centralising the header markup here keeps every page in lockstep:
 * one place to flip "active" state, one place to add or rename a route.
 */
import { DOCS_BASE_URL } from "../lib/config.js";

export type ActivePage = "wallets" | "settings";

/**
 * Render the header `<header class="page-header">…</header>` block.
 *
 * @param title       page title shown next to the brand suffix
 * @param active      which top-nav item to mark as `class="active"`
 * @param titleSuffix optional inline-HTML extra (e.g. a TESTNET badge);
 *                    rendered inside the `<h1>` after the title
 */
export function renderHeader(
  title: string,
  active: ActivePage,
  titleSuffix = "",
): string {
  const navLink = (page: ActivePage, href: string, label: string): string => {
    const isActive = page === active;
    const cls = isActive ? ' class="active"' : "";
    const current = isActive ? ' aria-current="page"' : "";
    return `<a href="${href}"${cls}${current}>${label}</a>`;
  };
  return `
    <header class="page-header">
      <div class="page-header-brand">
        <img src="/logo.png" alt="" class="header-logo" aria-hidden="true" />
        <h1>${title}${titleSuffix}<span class="brand"> · PiWalletSV</span></h1>
      </div>
      <nav aria-label="Main">
        ${navLink("wallets", "#/wallets", "Wallets")}
        ${navLink("settings", "#/settings", "Settings")}
        <a href="${DOCS_BASE_URL}/" class="ext"
           target="_blank" rel="noopener noreferrer"
           aria-label="Documentation (opens in new tab)">Docs ↗</a>
      </nav>
    </header>
  `;
}
