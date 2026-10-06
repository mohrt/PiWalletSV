/**
 * PiWallet Pass v1 client side: parse and check an app's request, derive
 * the WebAuthn challenge, and post the response back to the app.
 *
 * Spec: piwalletsv-pay/notes/pass-protocol.md. Nothing here is specific to
 * any one app; the phone talks only to the app that made the request.
 */
import { hmac } from "@noble/hashes/hmac.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { base58check } from "@scure/base";

export const REQUEST_TYPE = "piwallet-pass-request";
export const MAX_REQUEST_BYTES = 4096;
export const MAX_LIFETIME_MS = 10 * 60_000;
export const CLOCK_SKEW_MS = 60_000;

export const PURPOSES: Record<string, string> = {
  "create-account": "Create an account",
  "add-passkey": "Add this wallet as a way to sign in",
  "sign-in": "Sign in",
  "set-up-device": "Set up a device",
  recover: "Recover an account",
  confirm: "Confirm an action",
};

export interface PassRequest {
  v: 1;
  type: typeof REQUEST_TYPE;
  id: string;
  app: { origin: string; name: string };
  purpose: string;
  mode: "create" | "get";
  nonce: string;
  expires: string;
  account?: string;
  wallet?: { fingerprint: string };
  allowCredentials?: string[];
  callback: string;
  device?: string;
}

export class PassError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PassError";
  }
}

const ID = /^[A-Za-z0-9_-]{8,64}$/;
const NONCE = /^[A-Za-z0-9_-]{43}$/;
const FINGERPRINT = /^[0-9a-f]{8}$/;
const CREDENTIAL_ID = /^[A-Za-z0-9_-]{16,1400}$/;
const PURPOSE = /^[a-z0-9-]{1,32}$/;
const EXPIRES = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** The request URL inside a PiWallet Pass link for this companion, or null. */
export function requestUrlFromLink(text: string, companionOrigin: string): string | null {
  let link: URL;
  try {
    link = new URL(text.trim());
  } catch {
    return null;
  }
  if (link.origin !== companionOrigin || link.pathname !== "/") return null;
  return requestUrlFromHash(link.hash);
}

/** The request URL from a `#/pass?rq=…` hash, or null. */
export function requestUrlFromHash(hash: string): string | null {
  if (!hash.startsWith("#/pass?")) return null;
  const rq = new URLSearchParams(hash.slice("#/pass?".length)).get("rq");
  return rq || null;
}

function isHttpsOrigin(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.origin === value;
  } catch {
    return false;
  }
}

function sameOriginHttps(url: string, origin: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.origin === origin;
  } catch {
    return false;
  }
}

function text(value: unknown, max: number): string | null {
  return typeof value === "string" && value.length >= 1 && value.length <= max ? value : null;
}

/** Check a parsed request against spec §4–§5. Throws PassError with a plain message. */
export function validateRequest(raw: unknown, requestUrl: string, now = new Date()): PassRequest {
  if (typeof raw !== "object" || raw === null) throw new PassError("The site sent something that is not a PiWallet Pass request.");
  const r = raw as Record<string, unknown>;
  if (r.v !== 1) throw new PassError("This request uses a PiWallet Pass version this companion does not support.");
  if (r.type !== REQUEST_TYPE) throw new PassError("The site sent something that is not a PiWallet Pass request.");
  const app = (typeof r.app === "object" && r.app !== null ? r.app : {}) as Record<string, unknown>;
  const origin = typeof app.origin === "string" ? app.origin : "";
  const name = text(app.name, 60);
  if (!isHttpsOrigin(origin) || !name) throw new PassError("The request does not name its site correctly.");
  if (!sameOriginHttps(requestUrl, origin)) throw new PassError(`The request did not come from ${origin}.`);
  const callback = typeof r.callback === "string" ? r.callback : "";
  if (!sameOriginHttps(callback, origin)) throw new PassError(`The request would send the answer somewhere other than ${origin}.`);
  if (typeof r.id !== "string" || !ID.test(r.id)) throw new PassError("The request id is not valid.");
  if (typeof r.nonce !== "string" || !NONCE.test(r.nonce)) throw new PassError("The request is missing its random value.");
  if (r.mode !== "create" && r.mode !== "get") throw new PassError("The request does not say what to do.");
  if (typeof r.purpose !== "string" || !PURPOSE.test(r.purpose)) throw new PassError("The request does not say what it is for.");
  const expires = typeof r.expires === "string" && EXPIRES.test(r.expires) ? Date.parse(r.expires) : NaN;
  if (!Number.isFinite(expires) || expires <= now.getTime()) throw new PassError("This request has expired. Start again on the other screen.");
  if (expires > now.getTime() + MAX_LIFETIME_MS + CLOCK_SKEW_MS) throw new PassError("This request lasts longer than PiWallet Pass allows.");

  const request: PassRequest = {
    v: 1,
    type: REQUEST_TYPE,
    id: r.id,
    app: { origin, name },
    purpose: r.purpose,
    mode: r.mode,
    nonce: r.nonce,
    expires: r.expires as string,
    callback,
  };
  if (r.account !== undefined) {
    const account = text(r.account, 100);
    if (!account) throw new PassError("The request names its account incorrectly.");
    request.account = account;
  }
  if (r.device !== undefined) {
    const device = text(r.device, 100);
    if (!device) throw new PassError("The request names its device incorrectly.");
    request.device = device;
  }
  if (r.wallet !== undefined) {
    const fp = (r.wallet as Record<string, unknown> | null)?.fingerprint;
    if (typeof fp !== "string" || !FINGERPRINT.test(fp)) throw new PassError("The request names a wallet incorrectly.");
    request.wallet = { fingerprint: fp };
  }
  if (r.allowCredentials !== undefined) {
    const list = r.allowCredentials;
    if (request.mode !== "get" || !Array.isArray(list) || list.length > 20 || !list.every((id) => typeof id === "string" && CREDENTIAL_ID.test(id))) {
      throw new PassError("The request lists its passkeys incorrectly.");
    }
    request.allowCredentials = list as string[];
  }
  return request;
}

export function purposeLabel(purpose: string): string {
  return PURPOSES[purpose] ?? PURPOSES.confirm;
}

/** Spec §8: the text whose SHA-256 is the WebAuthn challenge. */
export function challengeText(request: Pick<PassRequest, "app" | "id" | "purpose" | "mode" | "nonce" | "wallet">): string {
  return [
    "piwallet-pass:v1",
    `origin:${request.app.origin}`,
    `id:${request.id}`,
    `purpose:${request.purpose}`,
    `mode:${request.mode}`,
    `nonce:${request.nonce}`,
    `wallet:${request.wallet?.fingerprint ?? ""}`,
  ].join("\n");
}

export function challengeBytes(request: Parameters<typeof challengeText>[0]): Uint8Array {
  return sha256(new TextEncoder().encode(challengeText(request)));
}

const WALLET_PROOF_PREFIX = new TextEncoder().encode("piwallet-pass:v1:wallet-proof\n");

/** HMAC of the challenge keyed by the xpub's chain code and public key: shows the app this companion holds the xpub without sending it. */
export function walletProof(request: Parameters<typeof challengeText>[0], xpub: string): string {
  const key = base58check(sha256).decode(xpub).slice(13, 78);
  const challenge = challengeBytes(request);
  const message = new Uint8Array(WALLET_PROOF_PREFIX.length + challenge.length);
  message.set(WALLET_PROOF_PREFIX);
  message.set(challenge, WALLET_PROOF_PREFIX.length);
  return b64url(hmac(sha256, key, message));
}

export function b64url(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = "";
  for (const b of view) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function fromB64url(value: string): Uint8Array {
  const b64 = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (value.length % 4)) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Fetch and check a request from the app (spec §3–§5). */
export async function fetchRequest(requestUrl: string, fetchImpl: typeof fetch = fetch): Promise<PassRequest> {
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(requestUrl);
  } catch {
    throw new PassError("That is not a PiWallet Pass link.");
  }
  if (parsedUrl.protocol !== "https:") throw new PassError("PiWallet Pass requests must use https.");
  let res: Response;
  try {
    res = await fetchImpl(parsedUrl.href, { credentials: "omit", cache: "no-store", headers: { accept: "application/json" } });
  } catch {
    throw new PassError(`Could not reach ${parsedUrl.origin}. Check your connection and try again.`);
  }
  const body = await res.text();
  if (!res.ok) {
    throw new PassError(messageFrom(body) ?? "This request has expired or was already used. Start again on the other screen.");
  }
  if (new TextEncoder().encode(body).length > MAX_REQUEST_BYTES) throw new PassError("The request is too large.");
  let raw: unknown;
  try {
    raw = JSON.parse(body);
  } catch {
    throw new PassError("The site sent something that is not a PiWallet Pass request.");
  }
  return validateRequest(raw, parsedUrl.href);
}

export interface PassResponseBody {
  v: 1;
  id: string;
  credential: unknown;
  wallet?: { fingerprint: string };
  walletProof?: string;
}

/** Post the passkey response to the app's callback (spec §9). Returns the app's message. */
export async function postResponse(
  request: PassRequest,
  credential: unknown,
  proof?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<string> {
  const body: PassResponseBody = { v: 1, id: request.id, credential };
  if (request.wallet) body.wallet = { fingerprint: request.wallet.fingerprint };
  if (proof) body.walletProof = proof;
  let res: Response;
  try {
    res = await fetchImpl(request.callback, {
      method: "POST",
      credentials: "omit",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new PassError(`Could not reach ${request.app.origin} to send the answer.`);
  }
  const reply = await res.text();
  if (!res.ok) throw new PassError(messageFrom(reply) ?? `${request.app.origin} did not accept the passkey.`);
  return messageFrom(reply) ?? "Done.";
}

function messageFrom(body: string): string | null {
  try {
    const parsed = JSON.parse(body) as { message?: unknown };
    return typeof parsed.message === "string" && parsed.message ? parsed.message.slice(0, 200) : null;
  } catch {
    return null;
  }
}

export function isCredentialId(value: string): boolean {
  return CREDENTIAL_ID.test(value);
}
