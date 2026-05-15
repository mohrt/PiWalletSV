/**
 * Shared top-of-page header for every operational route.
 *
 * The companion only has two real surfaces in the post-split layout:
 *
 *   - `#/wallets`               (also used for `#/wallets/<id>` detail)
 *   - `#/scan`                  (multipart-QR scanner)
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

export type ActivePage = "wallets" | "scan";

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
  const cls = (page: ActivePage): string => (page === active ? ' class="active"' : "");
  return `
    <header class="page-header">
      <h1>${title}${titleSuffix}<span class="brand"> · PiWalletSV</span></h1>
      <nav>
        <a href="#/wallets"${cls("wallets")}>Wallets</a>
        <a href="#/scan"${cls("scan")}>Scan QR</a>
        <a href="${DOCS_BASE_URL}/" class="ext"
           target="_blank" rel="noopener noreferrer">Docs ↗</a>
      </nav>
    </header>
  `;
}
