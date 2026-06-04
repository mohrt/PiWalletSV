/**
 * Saved send recipients (address book) stored in localStorage.
 *
 * Entries are scoped by network so mainnet and testnet addresses never
 * collide. Included in companion settings backup for device migration.
 */
import type { DefaultNetwork } from "./companion-settings.js";

export interface AddressBookEntry {
  address: string;
  label: string;
  network: DefaultNetwork;
  /** ISO 8601 — updated when the address is used or re-saved. */
  lastUsedAt: string;
}

export const KEY_ADDRESS_BOOK = "piwallet.addressBook";
export const MAX_ADDRESS_BOOK = 50;

function storage(): Storage | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null;
  }
}

function readRaw(): AddressBookEntry[] {
  const store = storage();
  if (!store) return [];
  try {
    const parsed = JSON.parse(store.getItem(KEY_ADDRESS_BOOK) ?? "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidEntry);
  } catch {
    return [];
  }
}

function writeRaw(entries: AddressBookEntry[]): void {
  storage()?.setItem(KEY_ADDRESS_BOOK, JSON.stringify(entries));
}

function isValidEntry(raw: unknown): raw is AddressBookEntry {
  if (typeof raw !== "object" || raw === null) return false;
  const e = raw as Record<string, unknown>;
  return (
    typeof e.address === "string" &&
    e.address.length > 0 &&
    typeof e.label === "string" &&
    (e.network === "main" || e.network === "test") &&
    typeof e.lastUsedAt === "string"
  );
}

export function getAddressBook(): AddressBookEntry[] {
  return readRaw();
}

export function getAddressBookForNetwork(network: DefaultNetwork): AddressBookEntry[] {
  return readRaw().filter((e) => e.network === network);
}

/** Insert or bump an entry; trims to {@link MAX_ADDRESS_BOOK}. */
export function upsertAddressBookEntry(
  address: string,
  network: DefaultNetwork,
  label = "",
): AddressBookEntry {
  const trimmed = address.trim();
  const now = new Date().toISOString();
  const rest = readRaw().filter(
    (e) => !(e.address === trimmed && e.network === network),
  );
  const existing = readRaw().find(
    (e) => e.address === trimmed && e.network === network,
  );
  const entry: AddressBookEntry = {
    address: trimmed,
    network,
    label: label.trim() || existing?.label || "",
    lastUsedAt: now,
  };
  writeRaw([entry, ...rest].slice(0, MAX_ADDRESS_BOOK));
  return entry;
}

export function removeAddressBookEntry(
  address: string,
  network: DefaultNetwork,
): void {
  const trimmed = address.trim();
  writeRaw(
    readRaw().filter((e) => !(e.address === trimmed && e.network === network)),
  );
}

export function updateAddressBookLabel(
  address: string,
  network: DefaultNetwork,
  label: string,
): void {
  const trimmed = address.trim();
  writeRaw(
    readRaw().map((e) =>
      e.address === trimmed && e.network === network
        ? { ...e, label: label.trim() }
        : e,
    ),
  );
}

export function validateAddressBookBackup(raw: unknown): AddressBookEntry[] | undefined {
  if (raw === undefined || raw === null) return undefined;
  if (!Array.isArray(raw)) throw new Error("addressBook must be an array");
  const out: AddressBookEntry[] = [];
  for (const item of raw) {
    if (!isValidEntry(item)) throw new Error("addressBook entry invalid");
    out.push(item);
  }
  return out.slice(0, MAX_ADDRESS_BOOK);
}

export function applyAddressBookBackup(entries: AddressBookEntry[] | undefined): void {
  if (!entries) return;
  writeRaw(entries);
}

export function exportAddressBookBackup(): AddressBookEntry[] {
  const book = readRaw();
  return book.length > 0 ? book : [];
}
