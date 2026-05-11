import "./app/styles.css";
import { mountEncoderPage } from "./app/encoder.js";
import { mountScannerPage } from "./app/scanner.js";

const app = document.getElementById("app");
if (!app) {
  throw new Error("missing #app root element");
}

type Teardown = (() => void) | void;

let pageTeardown: (() => void) | null = null;

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

  const route = (window.location.hash || "#/encode").toLowerCase();
  let mounted: Teardown;

  if (route === "" || route === "#" || route === "#/" || route === "#/encode") {
    mounted = mountEncoderPage(app);
  } else if (route === "#/scan") {
    mounted = mountScannerPage(app);
  } else {
    app.innerHTML = `
      <main class="page">
        <header class="page-header"><h1>404</h1></header>
        <section class="placeholder">
          <p>Unknown route: <code>${route}</code></p>
          <p><a href="#/encode">Back to encoder</a></p>
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
render();
