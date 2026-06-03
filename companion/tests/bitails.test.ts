import { describe, expect, it } from "vitest";

import {
  BITAILS_DEV_PROXY_PATH,
  BITAILS_MAINNET_BASE,
  BITAILS_TESTNET_PROXY_PATH,
  BitailsClient,
  BitailsError,
  effectiveBitailsBase,
  type FetchFn,
} from "../src/lib/bitails.js";

interface StubCall {
  url: string;
  init?: RequestInit;
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
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

describe("BitailsClient", () => {
  it("getHistoryBatch maps raw fields to deltaSats and timestamps", async () => {
    const { fetch } = stubFetch(() =>
      jsonResponse([
        {
          txid: "aa".repeat(32),
          inputSatoshis: 1000,
          outputSatoshis: 6000,
          time: 1_700_000_000,
          blockheight: 812345,
        },
      ]),
    );
    const client = new BitailsClient({ fetch, minIntervalMs: 0 });
    const entries = await client.getHistoryBatch(["1Addr"], { limit: 50 });
    expect(entries).toEqual([
      {
        txid: "aa".repeat(32),
        timestamp: 1_700_000_000,
        blockHeight: 812345,
        deltaSats: 5000,
      },
    ]);
  });

  it("getHistoryBatch appends limit and from query params", async () => {
    const { fetch, calls } = stubFetch(() => jsonResponse([]));
    const client = new BitailsClient({ fetch, minIntervalMs: 0 });
    await client.getHistoryBatch(["1Addr"], { limit: 25, from: 10 });
    expect(calls[0].url).toBe(
      `${BITAILS_MAINNET_BASE}/address/history/multi?limit=25&from=10`,
    );
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      addresses: ["1Addr"],
    });
  });

  it("throws BitailsError on non-2xx responses", async () => {
    const { fetch } = stubFetch(() => jsonResponse({ error: "nope" }, 502));
    const client = new BitailsClient({ fetch, minIntervalMs: 0 });
    await expect(client.getHistoryBatch(["1Addr"])).rejects.toBeInstanceOf(
      BitailsError,
    );
  });

  it("retries on 429 with Retry-After header", async () => {
    let attempts = 0;
    const sleeps: number[] = [];
    const { fetch, calls } = stubFetch(() => {
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse({ error: "rate limit" }, 429, {
          "Retry-After": "1",
        });
      }
      return jsonResponse([]);
    });
    const client = new BitailsClient({
      fetch,
      minIntervalMs: 0,
      sleep: (ms) => {
        sleeps.push(ms);
        return Promise.resolve();
      },
    });
    await client.getHistoryBatch(["1Addr"]);
    expect(calls).toHaveLength(2);
    expect(sleeps[0]).toBe(1000);
  });
});

describe("effectiveBitailsBase", () => {
  it("returns same-origin proxy paths in dev", () => {
    expect(effectiveBitailsBase("main", { dev: true })).toBe(
      BITAILS_DEV_PROXY_PATH,
    );
    expect(effectiveBitailsBase("test", { dev: true })).toBe(
      BITAILS_TESTNET_PROXY_PATH,
    );
  });

  it("returns absolute URLs in production", () => {
    expect(effectiveBitailsBase("main", { dev: false })).toBe(
      BITAILS_MAINNET_BASE,
    );
    expect(effectiveBitailsBase("test", { dev: false })).toBe(
      BITAILS_TESTNET_PROXY_PATH,
    );
  });
});
