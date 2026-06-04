import { readFileSync } from "node:fs";
import { defineConfig } from "vitest/config";

const appVersion = (
  JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
    version: string;
  }
).version;

export default defineConfig({
  define: {
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(appVersion),
  },
  test: {
    include: ["tests/**/*.test.ts"],
  },
});
