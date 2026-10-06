import "fake-indexeddb/auto";

import { readFileSync } from "node:fs";

import { beforeEach, describe, expect, it } from "vitest";

import {
  PassError,
  type PassRequest,
  b64url,
  challengeBytes,
  challengeText,
  fetchRequest,
  fromB64url,
  postResponse,
  purposeLabel,
  requestUrlFromHash,
  requestUrlFromLink,
  validateRequest,
  walletProof,
} from "../src/lib/pass-protocol.js";
import { matchWallets } from "../src/lib/passkeys.js";
import {
  type WalletPasskey,
  type WalletRecord,
  _clearAllWallets,
  addPasskey,
  addWallet,
  getWallet,
  removePasskey,
  renamePasskey,
  touchPasskey,
} from "../src/lib/wallets.js";

const vectors = JSON.parse(readFileSync(new URL("./fixtures/pass-vectors.json", import.meta.url), "utf8")) as {
  vectors: { name: string; request: Record<string, string>; text: string; sha256_hex: string; challenge_b64url: string }[];
  wallet_proof: { xpub: string; proofs: Record<string, string> };
};

function vectorRequest(r: Record<string, string>) {
  return {
    app: { origin: r.origin, name: "x" },
    id: r.id,
    purpose: r.purpose,
    mode: r.mode as "get" | "create",
    nonce: r.nonce,
    ...(r.wallet ? { wallet: { fingerprint: r.wallet } } : {}),
  };
}

const NOW = new Date("2026-10-06T16:00:00Z");
const REQUEST_URL = "https://shop.example/pass/requests/q7ZtR2vXkY0aB9cD";

function rawRequest(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    v: 1,
    type: "piwallet-pass-request",
    id: "q7ZtR2vXkY0aB9cD",
    app: { origin: "https://shop.example", name: "Example Shop" },
    purpose: "sign-in",
    mode: "get",
    nonce: "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
    expires: "2026-10-06T16:02:00Z",
    callback: "https://shop.example/pass/requests/q7ZtR2vXkY0aB9cD/finish",
    ...overrides,
  };
}

function refusal(raw: Record<string, unknown>, url = REQUEST_URL): string {
  try {
    validateRequest(raw, url, NOW);
  } catch (e) {
    expect(e).toBeInstanceOf(PassError);
    return (e as Error).message;
  }
  throw new Error("expected a refusal");
}

describe("challenge", () => {
  it("matches the published vectors", () => {
    for (const v of vectors.vectors) {
      const request = vectorRequest(v.request);
      expect(challengeText(request)).toBe(v.text);
      expect(b64url(challengeBytes(request))).toBe(v.challenge_b64url);
    }
  });

  it("makes the wallet proofs in the vectors", () => {
    const { xpub, proofs } = vectors.wallet_proof;
    const checked = vectors.vectors.filter((v) => proofs[v.name]);
    expect(checked).toHaveLength(2);
    for (const v of checked) expect(walletProof(vectorRequest(v.request), xpub)).toBe(proofs[v.name]);
  });

  it("round-trips base64url", () => {
    const bytes = new Uint8Array([0, 255, 62, 63, 1, 2, 3]);
    expect(fromB64url(b64url(bytes))).toEqual(bytes);
  });
});

describe("validateRequest", () => {
  it("accepts a well-formed request", () => {
    const request = validateRequest(rawRequest({ device: "Chrome on macOS", wallet: { fingerprint: "cf987d8c" } }), REQUEST_URL, NOW);
    expect(request.app.origin).toBe("https://shop.example");
    expect(request.wallet).toEqual({ fingerprint: "cf987d8c" });
    expect(request.device).toBe("Chrome on macOS");
  });

  it("refuses a request served from another origin", () => {
    expect(refusal(rawRequest(), "https://evil.example/pass/requests/q7ZtR2vXkY0aB9cD")).toMatch(/did not come from/);
  });

  it("refuses a callback on another origin", () => {
    expect(refusal(rawRequest({ callback: "https://evil.example/finish" }))).toMatch(/somewhere other/);
  });

  it("refuses http", () => {
    expect(refusal(rawRequest({ app: { origin: "http://shop.example", name: "x" } }), "http://shop.example/r")).toMatch(/name its site/);
  });

  it("refuses expired and too-long requests", () => {
    expect(refusal(rawRequest({ expires: "2026-10-06T15:59:59Z" }))).toMatch(/expired/);
    expect(refusal(rawRequest({ expires: "2026-10-06T16:20:00Z" }))).toMatch(/longer/);
  });

  it("refuses other versions and malformed fields", () => {
    expect(refusal(rawRequest({ v: 2 }))).toMatch(/version/);
    expect(refusal(rawRequest({ nonce: "short" }))).toMatch(/random value/);
    expect(refusal(rawRequest({ wallet: { fingerprint: "CF987D8C" } }))).toMatch(/wallet/);
    expect(refusal(rawRequest({ mode: "create", allowCredentials: ["c29tZS1wYXNza2V5LWlkLTE"] }))).toMatch(/passkeys/);
  });

  it("names unknown purposes as a confirmation", () => {
    expect(purposeLabel("sign-in")).toBe("Sign in");
    expect(purposeLabel("approve-refund")).toBe("Confirm an action");
  });
});

describe("links", () => {
  const origin = "https://app.dev.piwalletsv.com";
  const rq = "https://dev.piwalletpay.com/v1/pass/requests/AbCdEfGh12345678";

  it("reads this companion's PiWallet Pass links", () => {
    expect(requestUrlFromLink(`${origin}/#/pass?rq=${encodeURIComponent(rq)}`, origin)).toBe(rq);
    expect(requestUrlFromHash(`#/pass?rq=${encodeURIComponent(rq)}`)).toBe(rq);
  });

  it("ignores links for another companion and other QR text", () => {
    expect(requestUrlFromLink(`https://app.piwalletsv.com/#/pass?rq=${encodeURIComponent(rq)}`, origin)).toBeNull();
    expect(requestUrlFromLink(`${origin}/other#/pass?rq=x`, origin)).toBeNull();
    expect(requestUrlFromLink("bitcoin:1abc", origin)).toBeNull();
    expect(requestUrlFromLink("PW1|1|0|abc", origin)).toBeNull();
  });
});

describe("fetchRequest and postResponse", () => {
  it("fetches without cookies and checks the request", async () => {
    let seen: RequestInit | undefined;
    const fake = (async (_url: string, init?: RequestInit) => {
      seen = init;
      return new Response(JSON.stringify(rawRequest({ expires: new Date(Date.now() + 60_000).toISOString().replace(/\.\d{3}Z$/, "Z") })));
    }) as typeof fetch;
    const request = await fetchRequest(REQUEST_URL, fake);
    expect(request.id).toBe("q7ZtR2vXkY0aB9cD");
    expect(seen?.credentials).toBe("omit");
  });

  it("shows the app's message when the request is gone", async () => {
    const fake = (async () => new Response(JSON.stringify({ error: "expired", message: "This request has expired." }), { status: 404 })) as typeof fetch;
    await expect(fetchRequest(REQUEST_URL, fake)).rejects.toThrow("This request has expired.");
  });

  it("refuses oversized requests", async () => {
    const fake = (async () => new Response(JSON.stringify(rawRequest({ device: "x".repeat(5000) })))) as typeof fetch;
    await expect(fetchRequest(REQUEST_URL, fake)).rejects.toThrow(/too large/);
  });

  it("sends the wallet only when the request named one, and the proof only when given", async () => {
    const bodies: Record<string, unknown>[] = [];
    const fake = (async (_url: string, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ ok: true, message: "Signed in." }));
    }) as typeof fetch;
    const unnamed = validateRequest(rawRequest(), REQUEST_URL, NOW);
    const named = validateRequest(rawRequest({ wallet: { fingerprint: "cf987d8c" } }), REQUEST_URL, NOW);
    expect(await postResponse(unnamed, { id: "c" }, undefined, fake)).toBe("Signed in.");
    await postResponse(named, { id: "c" }, "proof", fake);
    expect(bodies[0]).toEqual({ v: 1, id: "q7ZtR2vXkY0aB9cD", credential: { id: "c" } });
    expect(bodies[1].wallet).toEqual({ fingerprint: "cf987d8c" });
    expect(bodies[1].walletProof).toBe("proof");
  });
});

function wallet(id: string, fingerprint: string, passkeys: WalletPasskey[] = []): WalletRecord {
  return { id, label: `wallet ${id}`, xpub: "xpub", fingerprint, path: "m/44'/236'/0'", addedAt: NOW.toISOString(), schemaVersion: 2, passkeys };
}

function passkey(appOrigin: string, credentialId: string): WalletPasskey {
  return { name: "Shop", appOrigin, appName: "Shop", credentialId, userHandle: "dXNlcg", createdAt: NOW.toISOString() };
}

describe("matchWallets", () => {
  const signIn = validateRequest(rawRequest(), REQUEST_URL, NOW) as PassRequest;
  const shopKey = passkey("https://shop.example", "c2hvcC1wYXNza2V5LWlkLTE");
  const otherKey = passkey("https://other.example", "b3RoZXItcGFzc2tleS1pZC0x");

  it("picks the wallet connected to the app", () => {
    const match = matchWallets(signIn, [wallet("a", "11111111", [otherKey]), wallet("b", "22222222", [shopKey])]);
    expect(match.choices.map((c) => c.wallet.id)).toEqual(["b"]);
    expect(match.choices[0].passkey?.credentialId).toBe(shopKey.credentialId);
    expect(match.discoverable).toBe(false);
  });

  it("falls back to the phone's picker when no wallet is connected", () => {
    const match = matchWallets(signIn, [wallet("a", "11111111", [otherKey])]);
    expect(match.choices).toEqual([]);
    expect(match.discoverable).toBe(true);
  });

  it("uses only the wallet a request names", () => {
    const named = validateRequest(rawRequest({ mode: "create", purpose: "add-passkey", wallet: { fingerprint: "22222222" } }), REQUEST_URL, NOW);
    expect(matchWallets(named, [wallet("a", "11111111"), wallet("b", "22222222")]).choices.map((c) => c.wallet.id)).toEqual(["b"]);
    expect(matchWallets(named, [wallet("a", "11111111")]).problem).toMatch(/not paired/);
  });

  it("offers every wallet for a new passkey and marks connected ones", () => {
    const create = validateRequest(rawRequest({ mode: "create", purpose: "create-account" }), REQUEST_URL, NOW);
    const match = matchWallets(create, [wallet("a", "11111111"), wallet("b", "22222222", [shopKey])]);
    expect(match.choices.map((c) => [c.wallet.id, Boolean(c.passkey)])).toEqual([["a", false], ["b", true]]);
    expect(matchWallets(create, []).problem).toMatch(/Pair a wallet/);
  });
});

describe("wallet passkey records", () => {
  beforeEach(async () => {
    await _clearAllWallets();
  });

  it("adds, uses, renames, and removes", async () => {
    const rec = await addWallet({ label: "store", xpub: "xpub", fingerprint: "cf987d8c", path: "m/44'/236'/0'" });
    const key = passkey("https://shop.example", "c2hvcC1wYXNza2V5LWlkLTE");
    await addPasskey(rec.id, key);
    await touchPasskey(rec.id, key.credentialId, "2026-10-07T00:00:00.000Z");
    await renamePasskey(rec.id, key.credentialId, "  Shop on my phone ");
    let stored = await getWallet(rec.id);
    expect(stored?.passkeys).toEqual([{ ...key, name: "Shop on my phone", lastUsedAt: "2026-10-07T00:00:00.000Z" }]);
    await removePasskey(rec.id, key.credentialId);
    stored = await getWallet(rec.id);
    expect(stored?.passkeys).toEqual([]);
  });
});
