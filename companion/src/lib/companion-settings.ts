/**
 * Global companion preferences stored in localStorage.
 *
 * These are included in wallet backup/migration exports so a restore on
 * another browser feels identical. Terms acceptance is per-device and is
 * not migrated. Nothing secret belongs here — the Pi PIN and seed never
 * touch the companion and are not exportable.
 */
import type { WalletListSort } from "./wallets.js";

export type FeeTier = "economy" | "standard" | "priority" | "custom";
export type FiatCurrency = "USD" | "EUR" | "AUD" | "GBP";
export type DefaultNetwork = "main" | "test";
export type ListUnit = "sats" | "bsv" | "fiat";

export const KEY_DEFAULT_FEE_TIER = "piwallet.settings.defaultFeeTier";
export const KEY_CUSTOM_FEE_RATE = "piwallet.settings.customFeeRate";
export const KEY_FIAT_CURRENCY = "piwallet.settings.fiatCurrency";
export const KEY_DEFAULT_NETWORK = "piwallet.settings.defaultNetwork";
export const KEY_LIST_UNIT = "piwallet.listUnit";
export const KEY_LIST_SORT = "piwallet.listSort";

/** Snapshot of companion UI preferences for backup v2+. */
export interface CompanionSettingsBackup {
  defaultFeeTier?: FeeTier;
  customFeeRate?: number;
  fiatCurrency?: FiatCurrency;
  defaultNetwork?: DefaultNetwork;
  listUnit?: ListUnit;
  listSort?: WalletListSort;
}

const FEE_TIERS: FeeTier[] = ["economy", "standard", "priority", "custom"];
const FIAT: FiatCurrency[] = ["USD", "EUR", "AUD", "GBP"];
const NETWORKS: DefaultNetwork[] = ["main", "test"];
const LIST_UNITS: ListUnit[] = ["sats", "bsv", "fiat"];
const LIST_SORTS: WalletListSort[] = [
  "date",
  "date-asc",
  "label",
  "label-desc",
  "balance",
  "balance-asc",
];

function storage(): Storage | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null;
  }
}

export function parseListSort(raw: string | null): WalletListSort {
  return LIST_SORTS.includes(raw as WalletListSort)
    ? (raw as WalletListSort)
    : "date";
}

export function getDefaultFeeTier(): FeeTier {
  const v = storage()?.getItem(KEY_DEFAULT_FEE_TIER) as FeeTier | null;
  return FEE_TIERS.includes(v as FeeTier) ? (v as FeeTier) : "standard";
}

export function getDefaultCustomFeeRate(fallback: number): number {
  const stored = parseInt(storage()?.getItem(KEY_CUSTOM_FEE_RATE) ?? "", 10);
  return Number.isInteger(stored) && stored >= 0 ? stored : fallback;
}

export function getFiatCurrency(): FiatCurrency {
  const v = storage()?.getItem(KEY_FIAT_CURRENCY) as FiatCurrency | null;
  return FIAT.includes(v as FiatCurrency) ? (v as FiatCurrency) : "USD";
}

export function getDefaultNetwork(): DefaultNetwork {
  const v = storage()?.getItem(KEY_DEFAULT_NETWORK) as DefaultNetwork | null;
  return NETWORKS.includes(v as DefaultNetwork) ? (v as DefaultNetwork) : "main";
}

export function getListUnit(): ListUnit {
  const v = storage()?.getItem(KEY_LIST_UNIT) as ListUnit | null;
  return LIST_UNITS.includes(v as ListUnit) ? (v as ListUnit) : "sats";
}

export function getListSort(): WalletListSort {
  return parseListSort(storage()?.getItem(KEY_LIST_SORT) ?? null);
}

/** Collect every migratable companion preference from localStorage. */
export function exportCompanionSettings(): CompanionSettingsBackup {
  const store = storage();
  if (!store) return {};

  const out: CompanionSettingsBackup = {};
  const feeTier = store.getItem(KEY_DEFAULT_FEE_TIER) as FeeTier | null;
  if (feeTier && FEE_TIERS.includes(feeTier)) out.defaultFeeTier = feeTier;

  const customRaw = store.getItem(KEY_CUSTOM_FEE_RATE);
  if (customRaw !== null) {
    const n = parseInt(customRaw, 10);
    if (Number.isInteger(n) && n >= 0) out.customFeeRate = n;
  }

  const fiat = store.getItem(KEY_FIAT_CURRENCY) as FiatCurrency | null;
  if (fiat && FIAT.includes(fiat)) out.fiatCurrency = fiat;

  const network = store.getItem(KEY_DEFAULT_NETWORK) as DefaultNetwork | null;
  if (network && NETWORKS.includes(network)) out.defaultNetwork = network;

  const listUnit = store.getItem(KEY_LIST_UNIT) as ListUnit | null;
  if (listUnit && LIST_UNITS.includes(listUnit)) out.listUnit = listUnit;

  const listSort = store.getItem(KEY_LIST_SORT) as WalletListSort | null;
  if (listSort && LIST_SORTS.includes(listSort)) out.listSort = listSort;

  return out;
}

/** Restore companion preferences after a backup import. */
export function applyCompanionSettings(settings: CompanionSettingsBackup): void {
  const store = storage();
  if (!store) return;

  if (settings.defaultFeeTier && FEE_TIERS.includes(settings.defaultFeeTier)) {
    store.setItem(KEY_DEFAULT_FEE_TIER, settings.defaultFeeTier);
  }
  if (
    settings.customFeeRate !== undefined &&
    Number.isInteger(settings.customFeeRate) &&
    settings.customFeeRate >= 0
  ) {
    store.setItem(KEY_CUSTOM_FEE_RATE, String(settings.customFeeRate));
  }
  if (settings.fiatCurrency && FIAT.includes(settings.fiatCurrency)) {
    store.setItem(KEY_FIAT_CURRENCY, settings.fiatCurrency);
  }
  if (settings.defaultNetwork && NETWORKS.includes(settings.defaultNetwork)) {
    store.setItem(KEY_DEFAULT_NETWORK, settings.defaultNetwork);
  }
  if (settings.listUnit && LIST_UNITS.includes(settings.listUnit)) {
    store.setItem(KEY_LIST_UNIT, settings.listUnit);
  }
  if (settings.listSort && LIST_SORTS.includes(settings.listSort)) {
    store.setItem(KEY_LIST_SORT, settings.listSort);
  }
}

function validateSettings(raw: unknown): CompanionSettingsBackup | undefined {
  if (raw === undefined || raw === null) return undefined;
  if (typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("settings must be an object");
  }
  const s = raw as Record<string, unknown>;
  const out: CompanionSettingsBackup = {};

  if (s.defaultFeeTier !== undefined) {
    if (!FEE_TIERS.includes(s.defaultFeeTier as FeeTier)) {
      throw new Error("settings.defaultFeeTier invalid");
    }
    out.defaultFeeTier = s.defaultFeeTier as FeeTier;
  }
  if (s.customFeeRate !== undefined) {
    if (!Number.isInteger(s.customFeeRate) || (s.customFeeRate as number) < 0) {
      throw new Error("settings.customFeeRate invalid");
    }
    out.customFeeRate = s.customFeeRate as number;
  }
  if (s.fiatCurrency !== undefined) {
    if (!FIAT.includes(s.fiatCurrency as FiatCurrency)) {
      throw new Error("settings.fiatCurrency invalid");
    }
    out.fiatCurrency = s.fiatCurrency as FiatCurrency;
  }
  if (s.defaultNetwork !== undefined) {
    if (!NETWORKS.includes(s.defaultNetwork as DefaultNetwork)) {
      throw new Error("settings.defaultNetwork invalid");
    }
    out.defaultNetwork = s.defaultNetwork as DefaultNetwork;
  }
  if (s.listUnit !== undefined) {
    if (!LIST_UNITS.includes(s.listUnit as ListUnit)) {
      throw new Error("settings.listUnit invalid");
    }
    out.listUnit = s.listUnit as ListUnit;
  }
  if (s.listSort !== undefined) {
    if (!LIST_SORTS.includes(s.listSort as WalletListSort)) {
      throw new Error("settings.listSort invalid");
    }
    out.listSort = s.listSort as WalletListSort;
  }

  return Object.keys(out).length > 0 ? out : undefined;
}

export { validateSettings as validateCompanionSettingsBackup };
