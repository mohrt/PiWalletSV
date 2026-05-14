import { describe, expect, it } from "vitest";

import {
  type FetchFn,
  WOC_BULK_BATCH_MAX,
  WOC_DEFAULT_BASE,
  WOC_DEV_PROXY_MAINNET_PATH,
  WOC_DEV_PROXY_TESTNET_PATH,
  WOC_MAINNET_BASE,
  WOC_TESTNET_BASE,
  WocClient,
  WocError,
  effectiveWocBase,
  wocBaseForNetwork,
} from "../src/lib/woc.js";

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

  it("getUnspentBatch fans out to confirmed+unconfirmed and merges per-address", async () => {
    // The companion's gap-limit scanner depends on this method
    // returning *both* confirmed and mempool UTXOs in a single call.
    // WoC's older `POST /addresses/unspent` is mempool-blind, which
    // surfaced as "balance is 0" right after a fresh broadcast. The
    // fix is to call both split endpoints in parallel and merge.
    const { fetch, calls } = stubFetch((url, init) => {
      expect(init?.method).toBe("POST");
      const body = JSON.parse(String(init?.body));
      expect(body).toEqual({ addresses: ["addrA", "addrB"] });
      if (url.endsWith("/addresses/confirmed/unspent")) {
        return jsonResponse([
          {
            address: "addrA",
            script: "deadbeef",
            result: [
              {
                tx_hash: "aa".repeat(32),
                tx_pos: 0,
                value: 1000,
                height: 800001,
                isSpentInMempoolTx: false,
              },
            ],
            error: "",
          },
          { address: "addrB", script: "feedface", result: [], error: "" },
        ]);
      }
      if (url.endsWith("/addresses/unconfirmed/unspent")) {
        return jsonResponse([
          { address: "addrA", script: "deadbeef", result: [], error: "" },
          {
            address: "addrB",
            script: "feedface",
            result: [
              {
                tx_hash: "bb".repeat(32),
                tx_pos: 1,
                value: 2500,
                isSpentInMempoolTx: false,
                hex: "76a914...88ac",
              },
            ],
            error: "",
          },
        ]);
      }
      throw new Error(`unexpected url: ${url}`);
    });
    const w = new WocClient({ fetch });
    const rows = await w.getUnspentBatch(["addrA", "addrB"]);
    expect(rows).toEqual([
      {
        address: "addrA",
        utxos: [
          { txid: "aa".repeat(32), vout: 0, sats: 1000, height: 800001 },
        ],
      },
      {
        address: "addrB",
        utxos: [
          // Mempool entry — height: 0 marks it unconfirmed, matching
          // `GET /address/{addr}/unspent` semantics that the rest of
          // the pipeline already speaks.
          { txid: "bb".repeat(32), vout: 1, sats: 2500, height: 0 },
        ],
      },
    ]);
    expect(calls).toHaveLength(2);
    expect(calls[0].init?.headers).toMatchObject({
      "Content-Type": "application/json",
    });
  });

  it("getUnspentBatch filters UTXOs already being spent in mempool", async () => {
    // A confirmed UTXO can be flagged `isSpentInMempoolTx: true`
    // when the wallet has just broadcast a tx that consumes it.
    // Counting it in the balance would inflate the spendable total
    // and any selector that picks it would produce a guaranteed
    // double-spend the moment it's broadcast.
    const { fetch } = stubFetch((url) => {
      if (url.endsWith("/addresses/confirmed/unspent")) {
        return jsonResponse([
          {
            address: "addrA",
            script: "deadbeef",
            result: [
              {
                tx_hash: "aa".repeat(32),
                tx_pos: 0,
                value: 1000,
                height: 800001,
                isSpentInMempoolTx: true,
              },
              {
                tx_hash: "cc".repeat(32),
                tx_pos: 0,
                value: 4242,
                height: 800002,
                isSpentInMempoolTx: false,
              },
            ],
            error: "",
          },
        ]);
      }
      return jsonResponse([
        { address: "addrA", script: "deadbeef", result: [], error: "" },
      ]);
    });
    const w = new WocClient({ fetch });
    const rows = await w.getUnspentBatch(["addrA"]);
    expect(rows).toEqual([
      {
        address: "addrA",
        utxos: [
          { txid: "cc".repeat(32), vout: 0, sats: 4242, height: 800002 },
        ],
      },
    ]);
  });

  it("getUnspentBatch returns [] without calling fetch on empty input", async () => {
    const { fetch, calls } = stubFetch(() => jsonResponse([]));
    const w = new WocClient({ fetch });
    expect(await w.getUnspentBatch([])).toEqual([]);
    expect(calls).toEqual([]);
  });

  it("getUnspentBatch surfaces a per-address WoC error as WocError", async () => {
    // The error can come from either sub-call; failing fast on the
    // first one is enough to signal the operator that the gap-limit
    // counter would be wrong.
    const { fetch } = stubFetch((url) => {
      if (url.endsWith("/addresses/confirmed/unspent")) {
        return jsonResponse([
          {
            address: "addrA",
            result: [],
            error: "Unable to convert address to scripthash",
          },
        ]);
      }
      return jsonResponse([{ address: "addrA", result: [], error: "" }]);
    });
    const w = new WocClient({ fetch });
    await expect(w.getUnspentBatch(["addrA"])).rejects.toBeInstanceOf(WocError);
  });

  it("getUnspentBatch enforces the WOC_BULK_BATCH_MAX cap client-side", async () => {
    const { fetch } = stubFetch(() => jsonResponse([]));
    const w = new WocClient({ fetch });
    const tooMany = Array.from(
      { length: WOC_BULK_BATCH_MAX + 1 },
      (_, i) => `addr${i}`,
    );
    await expect(w.getUnspentBatch(tooMany)).rejects.toBeInstanceOf(WocError);
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

  it("getTxProof returns normalized TSC shape from /proof/tsc", async () => {
    const { fetch, calls } = stubFetch((url) => {
      expect(url).toContain("/proof/tsc");
      return jsonResponse([
        {
          index: 42,
          txOrId: "aa".repeat(32),
          target: "00".repeat(32),
          targetType: "blockHash",
          nodes: ["11".repeat(32), "*", "22".repeat(32)],
        },
      ]);
    });
    const w = new WocClient({ fetch });
    const proof = await w.getTxProof("aa".repeat(32));
    expect(proof).not.toBeNull();
    expect(proof!.txIndex).toBe(42);
    expect(proof!.blockHash).toBe("00".repeat(32));
    expect(proof!.nodes).toEqual(["11".repeat(32), "*", "22".repeat(32)]);
    expect(calls).toHaveLength(1);
  });

  it("getTxProof rejects unsupported targetType", async () => {
    const { fetch } = stubFetch(() =>
      jsonResponse([
        {
          index: 0,
          txOrId: "aa".repeat(32),
          target: "11".repeat(32),
          targetType: "merkleRoot",
          nodes: [],
        },
      ]),
    );
    const w = new WocClient({ fetch });
    await expect(w.getTxProof("aa".repeat(32))).rejects.toBeInstanceOf(WocError);
  });

  it("getTxProof returns null on 404 (unconfirmed tx)", async () => {
    const { fetch } = stubFetch(() => new Response("not found", { status: 404 }));
    const w = new WocClient({ fetch });
    const proof = await w.getTxProof("ee".repeat(32));
    expect(proof).toBeNull();
  });

  it("getHeaderByHash returns the parsed header from /block/<hash>/header", async () => {
    const { fetch, calls } = stubFetch((url) => {
      expect(url).toContain("/block/");
      expect(url).toContain("/header");
      expect(url).not.toContain("/block/hash/"); // legacy path
      return jsonResponse({
        hash: "aa".repeat(32),
        height: 812345,
        merkleroot: "11".repeat(32),
        time: 1700000000,
        previousblockhash: "bb".repeat(32),
      });
    });
    const w = new WocClient({ fetch });
    const h = await w.getHeaderByHash("aa".repeat(32));
    expect(h.height).toBe(812345);
    expect(h.merkleroot).toBe("11".repeat(32));
    expect(h.previousblockhash).toBe("bb".repeat(32));
    expect(calls).toHaveLength(1);
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
    // `maxRetries: 0` short-circuits the 429 retry loop so the call
    // surfaces a WocError immediately instead of sitting on the
    // exponential backoff. Pacing is also disabled to keep the test
    // synchronous-ish.
    const w = new WocClient({ fetch, maxRetries: 0, minIntervalMs: 0 });
    try {
      await w.getChainInfo();
      throw new Error("expected throw");
    } catch (e) {
      expect(e).toBeInstanceOf(WocError);
      expect((e as WocError).status).toBe(429);
    }
  });

  it("retries 429s up to maxRetries with paced backoff, then throws", async () => {
    let calls = 0;
    const fetch: FetchFn = () => {
      calls += 1;
      if (calls <= 3) {
        return Promise.resolve(
          new Response("slow down", {
            status: 429,
            statusText: "Too Many Requests",
            // Force a 1-second Retry-After to confirm the client
            // honours it via the stubbed sleep below.
            headers: { "Retry-After": "1" },
          }),
        );
      }
      return Promise.resolve(new Response('"deadbeef"', {
        status: 200,
        headers: { "content-type": "application/json" },
      }));
    };
    const sleeps: number[] = [];
    const w = new WocClient({
      fetch,
      maxRetries: 3,
      minIntervalMs: 0,
      sleep: async (ms) => {
        sleeps.push(ms);
      },
    });
    const txid = await w.broadcastRaw("0100abcd");
    expect(txid).toBe("deadbeef");
    expect(calls).toBe(4); // 3 x 429 + 1 success
    // Three Retry-After: 1s sleeps were honoured.
    expect(sleeps.filter((n) => n === 1000)).toHaveLength(3);
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

  it("WOC_DEFAULT_BASE remains an alias for WOC_MAINNET_BASE", () => {
    expect(WOC_DEFAULT_BASE).toBe(WOC_MAINNET_BASE);
  });

  it("WOC_TESTNET_BASE points at the v1/bsv/test endpoint", () => {
    expect(WOC_TESTNET_BASE).toBe("https://api.whatsonchain.com/v1/bsv/test");
  });

  it("wocBaseForNetwork picks the right base per network", () => {
    expect(wocBaseForNetwork("main")).toBe(WOC_MAINNET_BASE);
    expect(wocBaseForNetwork("test")).toBe(WOC_TESTNET_BASE);
  });

  // The dev branch of effectiveWocBase shields mobile WebKit clients
  // from the "Load failed" failure mode where a self-signed-cert page
  // can't fetch() to a different HTTPS origin even with CORS open.
  // See companion/vite.config.ts for the matching server.proxy entry.
  it("effectiveWocBase returns same-origin proxy paths in dev", () => {
    expect(effectiveWocBase("main", { dev: true })).toBe(
      WOC_DEV_PROXY_MAINNET_PATH,
    );
    expect(effectiveWocBase("test", { dev: true })).toBe(
      WOC_DEV_PROXY_TESTNET_PATH,
    );
  });

  it("effectiveWocBase returns absolute WoC URLs in production", () => {
    expect(effectiveWocBase("main", { dev: false })).toBe(WOC_MAINNET_BASE);
    expect(effectiveWocBase("test", { dev: false })).toBe(WOC_TESTNET_BASE);
  });

  it("dev-proxy paths are bare prefixes (no leading scheme/host)", () => {
    // The proxy entries in vite.config.ts match exactly these prefixes;
    // if either constant grows a scheme/host the rewrite stops firing
    // and same-origin routing silently breaks.
    expect(WOC_DEV_PROXY_MAINNET_PATH).toBe("/woc-main");
    expect(WOC_DEV_PROXY_TESTNET_PATH).toBe("/woc-test");
  });

  it("a testnet WocClient routes /chain/info to the testnet base", async () => {
    const { fetch, calls } = stubFetch((url) => {
      expect(url).toBe(`${WOC_TESTNET_BASE}/chain/info`);
      return jsonResponse({ blocks: 1, bestblockhash: "ff" });
    });
    const w = new WocClient({ fetch, baseUrl: wocBaseForNetwork("test") });
    await w.getChainInfo();
    expect(calls).toHaveLength(1);
  });
});
