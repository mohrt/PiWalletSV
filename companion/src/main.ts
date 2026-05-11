import "./app/styles.css";
import { mountEncoderPage } from "./app/encoder.js";
import { mountScanPlaceholder } from "./app/scan-placeholder.js";

const app = document.getElementById("app");
if (!app) {
  throw new Error("missing #app root element");
}

function render(): void {
  if (!app) return;
  const route = (window.location.hash || "#/encode").toLowerCase();
  app.innerHTML = "";
  if (route === "" || route === "#" || route === "#/" || route === "#/encode") {
    mountEncoderPage(app);
    return;
  }
  if (route === "#/scan") {
    mountScanPlaceholder(app);
    return;
  }
  app.innerHTML = `
    <main class="page">
      <header class="page-header"><h1>404</h1></header>
      <section class="placeholder">
        <p>Unknown route: <code>${route}</code></p>
        <p><a href="#/encode">Back to encoder</a></p>
      </section>
    </main>
  `;
}

window.addEventListener("hashchange", render);
render();
