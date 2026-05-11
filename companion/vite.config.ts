import basicSsl from "@vitejs/plugin-basic-ssl";
import { defineConfig } from "vite";

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
  plugins: useHttps ? [basicSsl()] : [],
  server: {
    port: 5173,
    strictPort: false,
    host: true,
  },
  build: {
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      output: {
        // @bsv/sdk is large and rarely changes — give it its own chunk
        // so browser cache survives app-code redeploys.
        manualChunks: {
          bsv: ["@bsv/sdk"],
        },
      },
    },
  },
});
