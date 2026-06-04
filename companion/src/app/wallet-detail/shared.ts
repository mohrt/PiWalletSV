export const RECENT_WINDOW = 8;
export const SATS_PER_BSV = 100_000_000;
export const RECEIVE_QR_SIZE_DEFAULT = 240;
export const RECEIVE_QR_SIZE_LARGE = 320;

export const VALID_TABS = new Set([
  "balance",
  "send",
  "receive",
  "history",
  "advanced",
]);

export const TAB_ORDER = [
  "balance",
  "send",
  "receive",
  "history",
  "advanced",
] as const;

export function normalizeTab(tab: string | undefined): string | undefined {
  if (tab === "share") return "advanced";
  return tab;
}

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function formatSats(n: number): string {
  return `${n.toLocaleString("en-US")} sats`;
}

export function formatBsv(n: number): string {
  return `${(n / SATS_PER_BSV).toFixed(8)} BSV`;
}

export function shortTxid(txid: string): string {
  if (txid.length <= 16) return txid;
  return `${txid.slice(0, 8)}…${txid.slice(-8)}`;
}

export function shortXpub(xpub: string): string {
  if (xpub.length <= 24) return xpub;
  return `${xpub.slice(0, 12)}…${xpub.slice(-8)}`;
}

export function wrapHex(hex: string, width: number): string {
  if (width <= 0) return hex;
  const lines: string[] = [];
  for (let i = 0; i < hex.length; i += width) {
    lines.push(hex.slice(i, i + width));
  }
  return lines.join("\n");
}
