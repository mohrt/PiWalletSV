import { PRICE_CACHE_TTL_MS } from "../../lib/config.js";
import { splitConfirmedPending } from "../../lib/balance-split.js";
import { relativeTimeFrom } from "../../lib/relative-time.js";
import { scanWalletUtxos } from "../../lib/utxo.js";
import { RECEIVE_BRANCH } from "../../lib/derive.js";
import { WocClient, WocError, effectiveWocBase } from "../../lib/woc.js";
import { setLastScan, setNextReceiveIndex } from "../../lib/wallets.js";
import { getFiatCurrency } from "../settings-page.js";
import {
  SATS_PER_BSV,
  escapeHtml,
  formatBsv,
  formatSats,
  shortTxid,
} from "./shared.js";
import type { DisplayUnit, WalletDetailActions, WalletDetailRuntime, WalletDetailTab } from "./types.js";

export interface BalanceTab extends WalletDetailTab {
  renderBalance(): void;
  refreshBalance(options?: { thenHistory?: boolean }): Promise<void>;
  formatBalance(sats: number): string;
  fetchBsvPrice(): Promise<void>;
  onUnitSelectChange(unit: DisplayUnit): Promise<void>;
  onToggleDisplayUnit(): Promise<void>;
}

export function createBalanceTab(
  rt: WalletDetailRuntime,
  actions: WalletDetailActions,
): BalanceTab {
  function formatBalance(sats: number): string {
    if (rt.displayUnit === "bsv") {
      return `${(sats / SATS_PER_BSV).toFixed(8)} BSV`;
    }
    if (rt.displayUnit === "fiat") {
      if (rt.bsvUsdPrice === null) return `— ${getFiatCurrency()}`;
      const val = (sats / SATS_PER_BSV) * rt.bsvUsdPrice;
      return `${getFiatCurrency()} ${val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return formatSats(sats);
  }

  async function fetchBsvPrice(): Promise<void> {
    if (!rt.wallet) return;
    const now = Date.now();
    if (rt.bsvUsdPrice !== null && now - rt.priceFetchedAt < PRICE_CACHE_TTL_MS) return;
    try {
      if (!rt.woc) {
        rt.woc = new WocClient({ baseUrl: effectiveWocBase(rt.wallet.network) });
      }
      const url = `${rt.woc.baseUrl}/exchangerate`;
      const resp = await fetch(url, { headers: { Accept: "application/json" } });
      if (!resp.ok) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data = (await resp.json()) as any;
      const rate = data?.rate ?? data?.price ?? data?.USD ?? null;
      if (typeof rate === "number" && rate > 0) {
        rt.bsvUsdPrice = rate;
        rt.priceFetchedAt = now;
      }
    } catch {
      // silently ignore — fiat toggle will show "—"
    }
  }

  function renderBalance(): void {
    if (!rt.wallet) return;
    const { root } = rt;
    const $hero = root.querySelector<HTMLElement>("#balanceHero");
    const $bsv = root.querySelector<HTMLElement>("#balanceBsv");
    const $meta = root.querySelector<HTMLElement>("#balanceMeta");
    const $pending = root.querySelector<HTMLElement>("#balancePending");
    const $spvNote = root.querySelector<HTMLElement>("#balanceSpvNote");
    const $details = root.querySelector<HTMLDetailsElement>("#utxoDetails");
    const $count = root.querySelector<HTMLElement>("#utxoCount");
    const $list = root.querySelector<HTMLUListElement>("#utxoList");
    if (!$hero || !$bsv || !$meta || !$pending || !$spvNote || !$details || !$count || !$list)
      return;

    const $sendBal = root.querySelector<HTMLElement>("#sendBalanceHero");
    const $sendPending = root.querySelector<HTMLElement>("#sendBalancePending");

    const scan = rt.wallet.lastScan;
    if (!scan) {
      $hero.textContent = "—";
      $bsv.textContent = "";
      $meta.textContent = "Not scanned yet — click Refresh to query WhatsOnChain.";
      $pending.hidden = true;
      $details.hidden = true;
      if ($spvNote) $spvNote.hidden = true;
      if ($sendBal) $sendBal.textContent = "—";
      if ($sendPending) $sendPending.hidden = true;
      actions.renderSendPendingBanner();
      return;
    }

    const split = splitConfirmedPending(scan.utxos);
    if ($sendBal) {
      $sendBal.textContent = formatBalance(split.confirmedSats);
    }
    if ($sendPending) {
      if (split.hasPending) {
        $sendPending.hidden = false;
        $sendPending.textContent =
          ` · ${formatBalance(split.pendingSats)} pending (not spendable yet)`;
      } else {
        $sendPending.hidden = true;
        $sendPending.textContent = "";
      }
    }
    actions.renderSendPendingBanner();
    $hero.textContent = formatBalance(scan.totalSats);
    $bsv.textContent =
      rt.displayUnit === "sats"
        ? formatBsv(scan.totalSats)
        : rt.displayUnit === "bsv"
          ? formatSats(scan.totalSats)
          : formatSats(scan.totalSats);
    $meta.textContent =
      `${scan.utxos.length} UTXO${scan.utxos.length === 1 ? "" : "s"} · ` +
      `last refreshed ${relativeTimeFrom(scan.at)}`;

    if (split.hasPending) {
      $pending.hidden = false;
      $pending.textContent = split.allPending
        ? "pending"
        : `+${formatSats(split.pendingSats)} pending`;
      $spvNote.hidden = false;
      $spvNote.textContent =
        "Pending coins are included in your total but cannot be spent until " +
        "they confirm — SPV requires an on-chain Merkle proof for each input.";
    } else {
      $pending.hidden = true;
      $spvNote.hidden = true;
    }

    $details.hidden = scan.utxos.length === 0;
    $count.textContent = String(scan.utxos.length);

    $list.innerHTML = "";
    for (const u of scan.utxos) {
      const li = document.createElement("li");
      const isPending = u.height === 0;
      li.className = isPending ? "utxo-row pending" : "utxo-row";
      const branchLabel = u.derivation[0] === 0 ? "recv" : "change";
      li.innerHTML = `
        <div class="utxo-top">
          <code title="${escapeHtml(u.txid)}">${escapeHtml(shortTxid(u.txid))}:${u.vout}</code>
          <span class="utxo-sats">${formatSats(u.sats)}</span>
        </div>
        <div class="muted-line">
          ${branchLabel} m/${u.derivation[0]}/${u.derivation[1]} ·
          ${escapeHtml(u.address)} ·
          ${isPending ? '<span class="utxo-pending-tag">pending</span>' : `block ${u.height}`}
        </div>
      `;
      $list.appendChild(li);
    }
  }

  async function refreshBalance(options: { thenHistory?: boolean } = {}): Promise<void> {
    if (!rt.wallet || rt.scanRunning) return;
    rt.scanRunning = true;
    const $refresh = rt.root.querySelector<HTMLButtonElement>("#refreshBalance");
    const $status = rt.root.querySelector<HTMLElement>("#balanceStatus");
    if ($refresh) {
      $refresh.disabled = true;
      $refresh.textContent = "Scanning…";
    }
    if ($status) {
      $status.classList.remove("error");
      $status.textContent = "Starting gap-limit scan…";
    }
    if (!rt.woc) {
      rt.woc = new WocClient({ baseUrl: effectiveWocBase(rt.wallet.network) });
    }

    try {
      const result = await scanWalletUtxos(rt.wallet.xpub, rt.woc, {
        network: rt.wallet.network,
        onProgress: ({ branch, index, address, found }) => {
          if (rt.cancelled || !$status) return;
          const branchLabel = branch === RECEIVE_BRANCH ? "recv" : "change";
          $status.textContent =
            `Probing ${branchLabel} m/${branch}/${index} ` +
            `(${address.slice(0, 6)}…${address.slice(-4)}) — ` +
            `${found} UTXO${found === 1 ? "" : "s"}`;
        },
      });
      if (rt.cancelled) return;
      const snapshot = {
        at: new Date().toISOString(),
        totalSats: result.totalSats,
        utxos: result.utxos,
        lastReceiveUsed: result.lastReceiveUsed,
        lastChangeUsed: result.lastChangeUsed,
        addressesScanned: result.addressesScanned,
        stoppedAt: result.stoppedAt,
      };
      await setLastScan(rt.wallet.id, snapshot);
      rt.wallet.lastScan = snapshot;

      const autoNext = result.lastReceiveUsed + 1;
      const didAdvance = autoNext > rt.wallet.nextReceiveIndex;
      if (didAdvance) {
        await setNextReceiveIndex(rt.wallet.id, autoNext);
        rt.wallet.nextReceiveIndex = autoNext;
      }

      renderBalance();
      void actions.renderReceive();
      actions.renderRecentList();
      if ($status) {
        $status.textContent =
          `Scan complete — ${result.utxos.length} UTXO(s), ` +
          `${result.addressesScanned} addresses probed.` +
          (didAdvance ? ` · receive index → ${rt.wallet.nextReceiveIndex}` : "");
      }
      if (options.thenHistory) {
        await actions.refreshHistory();
      }
    } catch (e) {
      if (rt.cancelled) return;
      const msg = e instanceof WocError ? e.message : (e as Error).message;
      if ($status) {
        $status.classList.add("error");
        $status.textContent = `scan failed: ${msg}`;
      }
    } finally {
      rt.scanRunning = false;
      if ($refresh) {
        $refresh.disabled = false;
        $refresh.textContent = "Refresh";
      }
    }
  }

  async function onUnitSelectChange(unit: DisplayUnit): Promise<void> {
    if (!rt.wallet) return;
    rt.displayUnit = unit;
    localStorage.setItem("piwallet.listUnit", unit);
    if (unit === "fiat" && rt.bsvUsdPrice === null) await fetchBsvPrice();
    renderBalance();
    const $toggle = rt.root.querySelector<HTMLButtonElement>("#balanceToggle");
    if ($toggle) {
      const label =
        unit === "fiat" ? getFiatCurrency() : unit === "bsv" ? "BSV" : "sats";
      $toggle.title = `Tap to cycle (showing ${label})`;
    }
  }

  async function onToggleDisplayUnit(): Promise<void> {
    const cycle: DisplayUnit[] = ["sats", "bsv", "fiat"];
    const next = cycle[(cycle.indexOf(rt.displayUnit) + 1) % cycle.length];
    const $select = rt.root.querySelector<HTMLSelectElement>("#unitSelect");
    if ($select) $select.value = next;
    await onUnitSelectChange(next);
  }

  function bind(): void {
    rt.root
      .querySelector<HTMLButtonElement>("#refreshBalance")
      ?.addEventListener("click", () => void refreshBalance());
    rt.root
      .querySelector<HTMLButtonElement>("#balanceToggle")
      ?.addEventListener("click", () => void onToggleDisplayUnit());
    rt.root.querySelector<HTMLSelectElement>("#unitSelect")?.addEventListener("change", (e) =>
      void onUnitSelectChange((e.target as HTMLSelectElement).value as DisplayUnit),
    );
  }

  return {
    bind,
    renderBalance,
    refreshBalance,
    formatBalance,
    fetchBsvPrice,
    onUnitSelectChange,
    onToggleDisplayUnit,
  };
}
