import basicSsl from "@vitejs/plugin-basic-ssl";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const companionRoot = path.dirname(fileURLToPath(import.meta.url));

const appVersion = (
  JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
    version: string;
  }
).version;

// HTTPS is on by default in dev because the multipart-QR scan page uses
// `getUserMedia`, which iOS Safari (and most other browsers) only expose
// over a secure origin when the host isn't `localhost`. The cert is a
// throwaway self-signed one — phones will warn on first visit; tap through
// once and the camera prompt appears as expected. For a friction-free
// long-term setup, see the `mkcert` notes in README.md.
//
// Set PIWALLET_HTTP=1 to force plain HTTP (e.g. quick localhost-only work
// where the cert warning is annoying).
const useHttps = process.env.PIWALLET_HTTP !== "1";

export default defineConfig({
  define: {
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(appVersion),
  },
  resolve: {
    alias: {
      // @bsv/sdk optional Node fast-paths; pure-TS fallbacks run in the browser.
      "node:crypto": path.resolve(companionRoot, "src/shims/node-crypto-stub.ts"),
    },
  },
  plugins: useHttps ? [basicSsl()] : [],
  server: {
    port: 5173,
    strictPort: false,
    host: true,
    // ---- WhatsOnChain proxy (dev only) ---------------------------------
    // Mobile WebKit (iOS Safari, and Chrome on iOS, which is also WebKit)
    // refuses cross-origin `fetch()` from a self-signed-cert page even
    // when CORS on the target is wide open — the request fails with
    // status 0 and Safari's generic "Load failed" message. The fix is
    // to make the WoC requests *same-origin* by routing them through
    // the dev server. Production builds (`vite build`) skip this
    // entirely and call api.whatsonchain.com directly.
    //
    // The companion's WoC client picks `/woc-main` / `/woc-test` as its
    // baseUrl in dev (see `effectiveWocBase` in src/lib/woc.ts) so the
    // browser only ever sees same-origin requests, which the proxy
    // then forwards to the right WoC base.
    proxy: {
      "/woc-main": {
        target: "https://api.whatsonchain.com",
        changeOrigin: true,
        secure: true,
        rewrite: (p) => p.replace(/^\/woc-main/, "/v1/bsv/main"),
      },
      "/woc-test": {
        target: "https://api.whatsonchain.com",
        changeOrigin: true,
        secure: true,
        rewrite: (p) => p.replace(/^\/woc-test/, "/v1/bsv/test"),
      },
      // Bitails proxies — same reason as WoC above (self-signed HTTPS +
      // missing CORS on test-api.bitails.io). Production testnet uses the
      // CloudFront `/bitails-test` behavior instead of this Vite proxy.
      "/bitails": {
        target: "https://api.bitails.io",
        changeOrigin: true,
        secure: true,
        rewrite: (p) => p.replace(/^\/bitails/, ""),
      },
      "/bitails-test": {
        target: "https://test-api.bitails.io",
        changeOrigin: true,
        secure: true,
        rewrite: (p) => p.replace(/^\/bitails-test/, ""),
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      output: {
        // @bsv/sdk is large and rarely changes — give it its own chunk
        // so browser cache survives app-code redeploys.
        manualChunks(id) {
          if (id.includes("node_modules/@bsv/sdk")) {
            return "bsv";
          }
        },
      },
    },
  },
});
