import { describe, expect, it } from "vitest";

import {
  BACKUP_FORMAT,
  serializeWalletBackup,
} from "../src/lib/wallet-backup.js";
import { BACKUP_VERSION, APP_VERSION } from "../src/lib/version.js";
import {
  KIND_SIGNED,
  KIND_XPUB,
  encodeEnvelope,
  hexToBytes,
  type SignedTxT,
  type XpubExportT,
} from "../src/lib/envelope.js";
import {
  validateAddressQr,
  validatePw1Bytes,
} from "../src/lib/scan-validate.js";

function makeXpub(): XpubExportT {
  return {
    kind: KIND_XPUB,
    xpub:
      "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQv" +
      "VykQsKLARZdbqKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
    path: "m/44'/236'/0'",
    label: "test wallet",
    fingerprint: hexToBytes("cf987d8c"),
    network: "main",
  };
}

function makeSigned(): SignedTxT {
  const txidBytes = hexToBytes("cd".repeat(32)).reverse();
  const beefBody = new Uint8Array(60).fill(0xee);
  const atomicBeef = new Uint8Array(4 + 32 + beefBody.length);
  atomicBeef.set([0x01, 0x01, 0x01, 0x01], 0);
  atomicBeef.set(txidBytes, 4);
  atomicBeef.set(beefBody, 4 + 32);
  return {
    kind: KIND_SIGNED,
    walletFp: hexToBytes("cf987d8c"),
    atomicBeef,
  };
}

function makeBackupJson(): string {
  return serializeWalletBackup({
    format: BACKUP_FORMAT,
    version: BACKUP_VERSION,
    exportedAt: new Date().toISOString(),
    companionVersion: APP_VERSION,
    wallets: [],
  });
}

describe("scan-validate", () => {
  it("accepts xpub only on pair-xpub workflow", async () => {
    const xpubBytes = await encodeEnvelope(makeXpub());
    const signedBytes = await encodeEnvelope(makeSigned());

    const ok = await validatePw1Bytes("pair-xpub", xpubBytes);
    expect(ok.ok).toBe(true);
    if (ok.ok) expect(ok.result.workflow).toBe("pair-xpub");

    const bad = await validatePw1Bytes("pair-xpub", signedBytes);
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.message).toContain("signed transaction");
  });

  it("accepts signed tx only on send-signed-tx workflow", async () => {
    const xpubBytes = await encodeEnvelope(makeXpub());
    const signedBytes = await encodeEnvelope(makeSigned());

    const ok = await validatePw1Bytes("send-signed-tx", signedBytes);
    expect(ok.ok).toBe(true);

    const bad = await validatePw1Bytes("send-signed-tx", xpubBytes);
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.message).toContain("pairing xpub");
  });

  it("accepts wallet backup JSON on settings-backup workflow", async () => {
    const json = makeBackupJson();
    const bytes = new TextEncoder().encode(json);

    const ok = await validatePw1Bytes("settings-backup", bytes);
    expect(ok.ok).toBe(true);
    if (ok.ok) expect(ok.result.workflow).toBe("settings-backup");

    const bad = await validatePw1Bytes("settings-backup", await encodeEnvelope(makeXpub()));
    expect(bad.ok).toBe(false);
  });

  it("validates address QR strings", () => {
    expect(validateAddressQr("bitcoin:1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa").ok).toBe(true);
    expect(validateAddressQr("PW1|3|0|abc").ok).toBe(false);
    expect(validateAddressQr("not-an-address").ok).toBe(false);
  });
});
