import { describe, expect, it } from "vitest";

import {
  SECURITY_SECTIONS,
  renderSecurityHtml,
} from "../src/app/security-page.js";

/**
 * The security briefing is a contract with the operator:
 *
 *   1. The companion is static — nothing about the wallet is sent off-device.
 *   2. The Pi's PIN encrypts a vault file; long PINs matter, short ones don't.
 *   3. The device should be treated like the seed phrase itself —
 *      cold storage, not daily transactions.
 *
 * These tests pin those three sections in place so a future refactor
 * can't silently drop one of them.
 */

describe("security briefing data", () => {
  it("exposes exactly three sections in a stable order", () => {
    expect(SECURITY_SECTIONS).toHaveLength(3);
    expect(SECURITY_SECTIONS.map((s) => s.id)).toEqual([
      "static-companion",
      "pin-strength",
      "physical-security",
    ]);
  });

  it("each section has a non-empty heading and at least three bullets", () => {
    for (const s of SECURITY_SECTIONS) {
      expect(s.heading.trim().length).toBeGreaterThan(0);
      expect(s.bullets.length).toBeGreaterThanOrEqual(3);
      for (const b of s.bullets) {
        expect(b.trim().length).toBeGreaterThan(0);
      }
    }
  });

  it("section ids are unique", () => {
    const ids = SECURITY_SECTIONS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("static-companion section names IndexedDB and rules out telemetry", () => {
    const s = SECURITY_SECTIONS.find((x) => x.id === "static-companion")!;
    const blob = s.bullets.join(" ").toLowerCase();
    expect(blob).toContain("indexeddb");
    expect(blob).toMatch(/no\s+(server|telemetry|analytics)/);
  });

  it("pin-strength section explains scrypt + the wipe + that brute force is possible", () => {
    const s = SECURITY_SECTIONS.find((x) => x.id === "pin-strength")!;
    const blob = s.bullets.join(" ").toLowerCase();
    expect(blob).toContain("scrypt");
    expect(blob).toMatch(/wipe|wipes/);
    expect(blob).toMatch(/not\s+impossible/);
  });

  it("physical-security section pushes the cold-storage framing", () => {
    const s = SECURITY_SECTIONS.find((x) => x.id === "physical-security")!;
    const blob = s.bullets.join(" ").toLowerCase();
    expect(blob).toContain("cold storage");
    expect(blob).toMatch(/seed\s+phrase/);
    expect(blob).toMatch(/vault.*not.*desk\s+drawer|drawer/);
  });
});

describe("renderSecurityHtml()", () => {
  it("renders one anchored card per section", () => {
    const html = renderSecurityHtml();
    for (const s of SECURITY_SECTIONS) {
      expect(html).toContain(`id="${s.id}"`);
      expect(html).toContain(s.heading);
    }
  });

  it("emits valid-looking <ul> bullets, one <li> per bullet", () => {
    const html = renderSecurityHtml();
    const liCount = (html.match(/<li>/g) ?? []).length;
    const expected = SECURITY_SECTIONS.reduce(
      (n, s) => n + s.bullets.length,
      0,
    );
    expect(liCount).toBe(expected);
  });

  it("does not accidentally include unsubstituted template placeholders", () => {
    const html = renderSecurityHtml();
    expect(html).not.toMatch(/\$\{[^}]+\}/);
  });
});
