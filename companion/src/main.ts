import "./app/styles.css";
import { mountScannerPage } from "./app/scanner.js";
import { mountSettingsPage } from "./app/settings-page.js";
import { ensureTermsAccepted } from "./app/terms-modal.js";
import { mountWalletDetailPage } from "./app/wallet-detail.js";
import { mountWalletsPage } from "./app/wallets-page.js";
import { DOCS_BASE_URL } from "./lib/config.js";
import { captureInstallPrompt } from "./lib/pwa-install.js";
import { applyTheme, watchSystemTheme } from "./lib/theme.js";
import { APP_VERSION, formatAppVersion } from "./lib/version.js";

const app = document.getElementById("app");
if (!app) {
  throw new Error("missing #app root element");
}

const footerVersion = document.getElementById("appFooterVersion");
if (footerVersion) {
  footerVersion.textContent = formatAppVersion(APP_VERSION);
}

type Teardown = (() => void) | void;

let pageTeardown: (() => void) | null = null;

// Default landing surface. The companion is now an operational wallet —
// it lands on the wallets list (or its empty state if none are paired
// yet, which then directs the user at #/scan to pair one). The encoder
// playground, security briefing, and codec round-trip live on the
// marketing site / docs site (DOCS_BASE_URL — env-driven, see config.ts).
const DEFAULT_ROUTE = "#/wallets";

applyTheme();
const stopSystemTheme = watchSystemTheme();
const stopInstallCapture = captureInstallPrompt();
window.addEventListener("beforeunload", () => {
  stopSystemTheme();
  stopInstallCapture();
});

function render(): void {
  if (!app) return;
  if (pageTeardown) {
    try {
      pageTeardown();
    } catch (e) {
      console.error("page teardown failed:", e);
    }
    pageTeardown = null;
  }

  app.innerHTML = "";

  const route = (window.location.hash || DEFAULT_ROUTE).toLowerCase();
  let mounted: Teardown;

  if (route === "" || route === "#" || route === "#/" || route === "#/wallets") {
    mounted = mountWalletsPage(app);
  } else if (route === "#/scan/tx") {
    sessionStorage.setItem(
      "piwallet-signed-tx-hint",
      "Signed TX submit lives in Send → Step 2 → Advanced. Open a wallet and continue there.",
    );
    window.location.hash = "#/wallets";
    return;
  } else if (route === "#/scan") {
    mounted = mountScannerPage(app);
  } else if (route === "#/settings") {
    mounted = mountSettingsPage(app);
  } else if (route.startsWith("#/wallets/")) {
    const rest = route.slice("#/wallets/".length);
    const slash = rest.indexOf("/");
    const id = slash >= 0 ? rest.slice(0, slash) : rest;
    const initialTab = slash >= 0 ? rest.slice(slash + 1) : undefined;
    mounted = mountWalletDetailPage(app, id, initialTab);
  } else if (import.meta.env.DEV && route === "#/loop") {
    // Codec round-trip page is dev-only; production builds tree-shake
    // the import below entirely. Operational users have no reason to
    // see it; QA / dev runs can still hit it via `npm run dev`.
    void import("./app/loop.js").then((m) => {
      const td = m.mountLoopPage(app);
      if (typeof td === "function") pageTeardown = td;
    });
    return;
  } else {
    // Unknown route — including #/encode and #/security from older
    // bookmarks, which now live on the marketing site. We send them
    // back to the wallets list rather than redirect off-domain so
    // an operator who mis-types stays inside the app.
    app.innerHTML = `
      <main class="page">
        <header class="page-header"><h1>Not found</h1></header>
        <section class="placeholder">
          <p>Unknown route: <code>${route}</code></p>
          <p>
            <a href="${DEFAULT_ROUTE}">Open wallets</a> ·
            <a href="${DOCS_BASE_URL}/" target="_blank" rel="noopener noreferrer">
              Marketing &amp; docs site
            </a>
          </p>
        </section>
      </main>
    `;
    return;
  }

  if (typeof mounted === "function") {
    pageTeardown = mounted;
  }
}

window.addEventListener("hashchange", render);
window.addEventListener("beforeunload", () => {
  if (pageTeardown) pageTeardown();
});

void ensureTermsAccepted().then(render);
