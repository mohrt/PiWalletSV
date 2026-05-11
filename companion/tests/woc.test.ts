import { describe, expect, it } from "vitest";

import { type FetchFn, WOC_DEFAULT_BASE, WocClient, WocError } from "../src/lib/woc.js";

interface StubCall {
  url: string;
  init?: RequestInit;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function textResponse(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "content-type": "text/plain" },
  });
}

function stubFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
): { fetch: FetchFn; calls: StubCall[] } {
  const calls: StubCall[] = [];
  const fn: FetchFn = (input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });
    return Promise.resolve(handler(url, init));
  };
  return { fetch: fn, calls };
}

describe("WocClient", () => {
  it("uses the default base url and Accept header", async () => {
    const { fetch, calls } = stubFetch((url) => {
      expect(url).toBe(`${WOC_DEFAULT_BASE}/chain/info`);
      return jsonResponse({ blocks: 800000, bestblockhash: "ff".repeat(32) });
    });
    const w = new WocClient({ fetch });
    const info = await w.getChainInfo();
    expect(info.blocks).toBe(800000);
    expect(info.bestblockhash).toBe("ff".repeat(32));
    expect(calls[0].init?.headers).toMatchObject({ Accept: "application/json" });
  });

  it("sends woc-api-key header when configured", async () => {
    const { fetch, calls } = stubFetch(() =>
      jsonResponse({ blocks: 1, bestblockhash: "a" }),
    );
    await new WocClient({ fetch, apiKey: "secret" }).getChainInfo();
    expect(calls[0].init?.headers).toMatchObject({ "woc-api-key": "secret" });
  });

  it("getUnspent maps tx_hash/tx_pos/value to txid/vout/sats", async () => {
    const { fetch } = stubFetch(() =>
      jsonResponse([
        { tx_hash: "aa".repeat(32), tx_pos: 1, value: 5000, height: 812345 },
        { tx_hash: "bb".repeat(32), tx_pos: 0, value: 1234, height: 0 },
      ]),
    );
    const w = new WocClient({ fetch });
    const utxos = await w.getUnspent("1K6LZdwpKT5XkEZo2T2kW197aMXYbYMc4f");
    expect(utxos).toEqual([
      { txid: "aa".repeat(32), vout: 1, sats: 5000, height: 812345 },
      { txid: "bb".repeat(32), vout: 0, sats: 1234, height: 0 },
    ]);
  });

  it("getUnspent surfaces non-array payloads as WocError", async () => {
    const { fetch } = stubFetch(() => jsonResponse({ error: "rate-limited" }));
    const w = new WocClient({ fetch });
    await expect(w.getUnspent("x")).rejects.toBeInstanceOf(WocError);
  });

  it("getTxHex returns hex text", async () => {
    const { fetch } = stubFetch(() => textResponse("0100000001abcdef\n"));
    const w = new WocClient({ fetch });
    const hex = await w.getTxHex("ee".repeat(32));
    expect(hex).toBe("0100000001abcdef");
  });

  it("getTxHex rejects non-hex payloads", async () => {
    const { fetch } = stubFetch(() => textResponse("oh no", 200));
    const w = new WocClient({ fetch });
    await expect(w.getTxHex("ee".repeat(32))).rejects.toBeInstanceOf(WocError);
  });

  it("getTxProof normalizes branches and returns structured proof", async () => {
    const { fetch } = stubFetch(() =>
      jsonResponse([
        {
          blockHash: "00".repeat(32),
          merkleRoot: "11".repeat(32),
          branches: [
            { hash: "22".repeat(32), pos: "L" },
            { hash: "33".repeat(32), pos: "R" },
            { hash: "44".repeat(32), pos: "bogus" },
          ],
          index: 42,
        },
      ]),
    );
    const w = new WocClient({ fetch });
    const proof = await w.getTxProof("aa".repeat(32));
    expect(proof).not.toBeNull();
    expect(proof!.blockHash).toBe("00".repeat(32));
    expect(proof!.merkleRoot).toBe("11".repeat(32));
    expect(proof!.branches).toEqual([
      { hash: "22".repeat(32), pos: "L" },
      { hash: "33".repeat(32), pos: "R" },
      { hash: "44".repeat(32), pos: "R" }, // unknown pos -> default R
    ]);
    expect(proof!.txIndex).toBe(42);
  });

  it("getTxProof returns null on 404 (unconfirmed tx)", async () => {
    const { fetch } = stubFetch(() => new Response("not found", { status: 404 }));
    const w = new WocClient({ fetch });
    const proof = await w.getTxProof("ee".repeat(32));
    expect(proof).toBeNull();
  });

  it("getHeaderByHash returns the parsed header", async () => {
    const { fetch } = stubFetch(() =>
      jsonResponse({
        hash: "aa".repeat(32),
        height: 812345,
        merkleroot: "11".repeat(32),
        time: 1700000000,
        previousblockhash: "bb".repeat(32),
      }),
    );
    const w = new WocClient({ fetch });
    const h = await w.getHeaderByHash("aa".repeat(32));
    expect(h.height).toBe(812345);
    expect(h.merkleroot).toBe("11".repeat(32));
    expect(h.previousblockhash).toBe("bb".repeat(32));
  });

  it("broadcastRaw posts JSON {txhex} and returns the de-quoted txid", async () => {
    const { fetch, calls } = stubFetch((url) => {
      expect(url).toBe(`${WOC_DEFAULT_BASE}/tx/raw`);
      return jsonResponse('"deadbeef"');
    });
    const w = new WocClient({ fetch });
    const txid = await w.broadcastRaw("0100abcd");
    expect(txid).toBe("deadbeef");
    expect(calls[0].init?.method).toBe("POST");
    const body = JSON.parse(String(calls[0].init?.body));
    expect(body).toEqual({ txhex: "0100abcd" });
  });

  it("broadcastRaw rejects non-hex input", async () => {
    const { fetch } = stubFetch(() => jsonResponse('"ok"'));
    const w = new WocClient({ fetch });
    await expect(w.broadcastRaw("not-hex")).rejects.toBeInstanceOf(WocError);
    await expect(w.broadcastRaw("abc")).rejects.toBeInstanceOf(WocError); // odd length
  });

  it("non-2xx http errors become WocError with status", async () => {
    const { fetch } = stubFetch(() =>
      new Response("Too Many Requests", {
        status: 429,
        statusText: "Too Many Requests",
      }),
    );
    const w = new WocClient({ fetch });
    try {
      await w.getChainInfo();
      throw new Error("expected throw");
    } catch (e) {
      expect(e).toBeInstanceOf(WocError);
      expect((e as WocError).status).toBe(429);
    }
  });

  it("network errors surface as WocError with status 0", async () => {
    const fetch: FetchFn = () => Promise.reject(new TypeError("offline"));
    const w = new WocClient({ fetch });
    try {
      await w.getChainInfo();
      throw new Error("expected throw");
    } catch (e) {
      expect(e).toBeInstanceOf(WocError);
      expect((e as WocError).status).toBe(0);
      expect((e as WocError).message).toMatch(/offline/);
    }
  });
});
