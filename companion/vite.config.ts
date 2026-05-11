import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    strictPort: false,
    host: true,
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
