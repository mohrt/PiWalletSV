/**
 * PiWallet Pass passkeys: which wallet answers a request (spec §7.0) and
 * the WebAuthn calls that create or use its passkey (spec §7.1–§7.2).
 *
 * The RP ID is this companion's own hostname, so no other site can use
 * these passkeys.
 */
import { b64url, challengeBytes, fromB64url, type PassRequest } from "./pass-protocol.js";
import type { WalletPasskey, WalletRecord } from "./wallets.js";

export interface WalletChoice {
  wallet: WalletRecord;
  /** The passkey this wallet has for the app, if it has one. */
  passkey?: WalletPasskey;
}

export interface WalletMatch {
  choices: WalletChoice[];
  /** No wallet has a record for the app: let the phone's passkey picker choose (spec §7.2). */
  discoverable: boolean;
  /** Set when the request can't be answered from this companion. */
  problem?: string;
}

function passkeyFor(wallet: WalletRecord, request: PassRequest): WalletPasskey | undefined {
  const allow = request.allowCredentials;
  return wallet.passkeys?.find((p) => p.appOrigin === request.app.origin && (!allow || allow.includes(p.credentialId)));
}

export function matchWallets(request: PassRequest, wallets: WalletRecord[]): WalletMatch {
  const fp = request.wallet?.fingerprint;
  if (fp) {
    const named = wallets.filter((w) => w.fingerprint === fp);
    if (!named.length) {
      return { choices: [], discoverable: false, problem: `${request.app.origin} asked for the wallet ${fp}, which is not paired with this companion.` };
    }
    return { choices: named.map((wallet) => ({ wallet, passkey: passkeyFor(wallet, request) })), discoverable: false };
  }
  if (request.mode === "create") {
    if (!wallets.length) return { choices: [], discoverable: false, problem: "Pair a wallet with this companion first." };
    return { choices: wallets.map((wallet) => ({ wallet, passkey: passkeyFor(wallet, request) })), discoverable: false };
  }
  const connected = wallets
    .map((wallet) => ({ wallet, passkey: passkeyFor(wallet, request) }))
    .filter((choice) => choice.passkey);
  return { choices: connected, discoverable: connected.length === 0 };
}

export function defaultPasskeyName(request: PassRequest): string {
  return request.app.name.slice(0, 64);
}

function buffer(bytes: Uint8Array): ArrayBuffer {
  return bytes.slice().buffer as ArrayBuffer;
}

function rpId(): string {
  return window.location.hostname;
}

export interface CreatedPasskey {
  credential: unknown;
  record: WalletPasskey;
}

export async function createPasskey(request: PassRequest, wallet: WalletRecord, name: string): Promise<CreatedPasskey> {
  const userHandle = crypto.getRandomValues(new Uint8Array(16));
  const host = new URL(request.app.origin).host;
  const exclude = (wallet.passkeys ?? []).filter((p) => p.appOrigin === request.app.origin);
  const created = (await navigator.credentials.create({
    publicKey: {
      rp: { id: rpId(), name: "PiWallet Pass" },
      user: { id: buffer(userHandle), name: `${wallet.label} · ${host}`, displayName: name },
      challenge: buffer(challengeBytes(request)),
      pubKeyCredParams: [
        { type: "public-key", alg: -7 },
        { type: "public-key", alg: -257 },
      ],
      authenticatorSelection: { residentKey: "preferred", userVerification: "required" },
      attestation: "none",
      excludeCredentials: exclude.map((p) => ({ type: "public-key" as const, id: buffer(fromB64url(p.credentialId)) })),
      timeout: 120_000,
    },
  })) as PublicKeyCredential | null;
  if (!created) throw new Error("No passkey was created.");
  const now = new Date().toISOString();
  return {
    credential: credentialJson(created),
    record: {
      name,
      appOrigin: request.app.origin,
      appName: request.app.name,
      credentialId: b64url(created.rawId),
      userHandle: b64url(userHandle),
      createdAt: now,
      lastUsedAt: now,
    },
  };
}

export interface UsedPasskey {
  credential: unknown;
  credentialId: string;
}

export async function usePasskey(request: PassRequest, choice: WalletChoice | null): Promise<UsedPasskey> {
  const allow = choice?.passkey ? [choice.passkey.credentialId] : (request.allowCredentials ?? []);
  const got = (await navigator.credentials.get({
    publicKey: {
      rpId: rpId(),
      challenge: buffer(challengeBytes(request)),
      allowCredentials: allow.map((id) => ({ type: "public-key" as const, id: buffer(fromB64url(id)) })),
      userVerification: "required",
      timeout: 120_000,
    },
  })) as PublicKeyCredential | null;
  if (!got) throw new Error("No passkey was used.");
  return { credential: credentialJson(got), credentialId: b64url(got.rawId) };
}

/** WebAuthn Level 3 JSON, using the browser's toJSON() when it has one. */
export function credentialJson(credential: PublicKeyCredential): unknown {
  const native = (credential as PublicKeyCredential & { toJSON?: () => unknown }).toJSON;
  if (typeof native === "function") return native.call(credential);
  const response = credential.response;
  const common = {
    id: credential.id,
    rawId: b64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
  };
  if ("attestationObject" in response) {
    const attestation = response as AuthenticatorAttestationResponse;
    return {
      ...common,
      response: {
        clientDataJSON: b64url(attestation.clientDataJSON),
        attestationObject: b64url(attestation.attestationObject),
        transports: attestation.getTransports?.() ?? [],
      },
    };
  }
  const assertion = response as AuthenticatorAssertionResponse;
  return {
    ...common,
    response: {
      clientDataJSON: b64url(assertion.clientDataJSON),
      authenticatorData: b64url(assertion.authenticatorData),
      signature: b64url(assertion.signature),
      userHandle: assertion.userHandle ? b64url(assertion.userHandle) : undefined,
    },
  };
}
