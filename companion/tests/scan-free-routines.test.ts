import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const ROUTINE_SURFACES = [
  "src/app/wallets-page.ts",
  "src/app/wallet-detail/balance-tab.ts",
  "src/app/wallet-detail/history-tab.ts",
  "src/app/wallet-detail/receive-tab.ts",
  "src/app/wallet-detail/send-tab.ts",
  "src/lib/balance-split.ts",
];

describe("scan-free routine wallet surfaces", () => {
  it.each(ROUTINE_SURFACES)("keeps %s off discovery and proof-fetch APIs", (path) => {
    const source = readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
    expect(source).not.toContain("scanWalletUtxos");
    expect(source).not.toContain("fetchInputProof");
    expect(source).not.toContain("fetchWalletHistory");
  });

  it("keeps address discovery available only as explicit advanced recovery", () => {
    const source = readFileSync(
      new URL("../src/app/wallet-detail/advanced-tab.ts", import.meta.url),
      "utf8",
    );
    expect(source).toContain("scanWalletUtxos");
    expect(source).toContain("fetchInputProof");
    expect(source).toContain("disaster recovery discovery");
  });
});
