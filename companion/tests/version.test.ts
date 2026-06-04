import { describe, expect, it } from "vitest";

import {
  APP_VERSION,
  BACKUP_FORMAT_VERSION,
  backupFormatVersion,
  formatAppVersion,
} from "../src/lib/version.js";

describe("companion version", () => {
  it("reads semver from package.json via Vite define", () => {
    expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("derives backup format v2 from 0.1.x companion releases", () => {
    expect(backupFormatVersion("0.1.0-a0")).toBe(2);
    expect(backupFormatVersion("0.1.99")).toBe(2);
    expect(BACKUP_FORMAT_VERSION).toBe(2);
  });

  it("derives backup format v1 from 0.0.x companion releases", () => {
    expect(backupFormatVersion("0.0.9")).toBe(1);
  });

  it("formats display label with v prefix", () => {
    expect(formatAppVersion("0.1.0-a0")).toBe("v0.1.0-a0");
    expect(formatAppVersion("v1.2.3")).toBe("v1.2.3");
  });
});
