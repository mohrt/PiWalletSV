import { PRICE_CACHE_TTL_MS } from "../../lib/config.js";
import { splitConfirmedPending } from "../../lib/balance-split.js";
import { relativeTimeFrom } from "../../lib/relative-time.js";
import { deriveAddress } from "../../lib/derive.js";
import { encodeEnvelope } from "../../lib/envelope.js";
import {
  applyStateReceipt,
  buildStateSyncEnvelope,
  stateBalanceSats,
  stateUtxos,
} from "../../lib/wallet-state.js";
import { encodeMultipartLines } from "../../pw1.js";
import {
  startPw1QrPlayback,
  wirePw1QrControls,
  type Pw1QrPlayback,
} from "../../lib/pw1-qr-playback.js";
import {
  WocClient,
  effectiveWocBase,
} from "../../lib/woc.js";
import { getFiatCurrency } from "../settings-page.js";
import { mountCameraScanner, type CameraScannerHandle } from "../camera-scanner.js";
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
  let syncPlayback: Pw1QrPlayback | null = null;
  let syncQrUnwire: (() => void) | null = null;
  let receiptScanner: CameraScannerHandle | null = null;

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

    const secured = rt.wallet.walletState;
    const legacy = secured ? undefined : rt.wallet.lastScan;
    const utxos = secured ? stateUtxos(secured) : (legacy?.utxos ?? []);
    const totalSats = secured ? stateBalanceSats(secured) : (legacy?.totalSats ?? 0);
    if (!secured && !legacy) {
      $hero.textContent = "—";
      $bsv.textContent = "";
      $meta.textContent =
        "No secured wallet state yet — import a sender's Atomic BEEF or use Advanced disaster recovery once to migrate.";
      $pending.hidden = true;
      $details.hidden = true;
      if ($spvNote) $spvNote.hidden = true;
      if ($sendBal) $sendBal.textContent = "—";
      if ($sendPending) $sendPending.hidden = true;
      actions.renderSendPendingBanner();
      renderStateSyncPanel();
      return;
    }

    const split = splitConfirmedPending(utxos);
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
    $hero.textContent = formatBalance(totalSats);
    $bsv.textContent =
      rt.displayUnit === "sats"
        ? formatBsv(totalSats)
        : rt.displayUnit === "bsv"
          ? formatSats(totalSats)
          : formatSats(totalSats);
    $meta.textContent = secured
      ? `${utxos.length} secured UTXO${utxos.length === 1 ? "" : "s"} · ` +
        `state revision ${secured.revision} · updated ${relativeTimeFrom(secured.updatedAt)}`
      : `${utxos.length} legacy cached UTXO${utxos.length === 1 ? "" : "s"} · ` +
        "not secured on the Pi; use Advanced disaster recovery to migrate";

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

    $details.hidden = utxos.length === 0;
    $count.textContent = String(utxos.length);

    $list.innerHTML = "";
    for (const u of utxos) {
      const li = document.createElement("li");
      const isPending = u.height === 0;
      li.className = isPending ? "utxo-row pending" : "utxo-row";
      const branchLabel = u.derivation[0] === 0 ? "recv" : "change";
      let address = u.address;
      if (!address) {
        try {
          address = deriveAddress(
            rt.wallet.xpub,
            u.derivation[0],
            u.derivation[1],
            rt.wallet.network,
          ).address;
        } catch {
          address = "address unavailable";
        }
      }
      li.innerHTML = `
        <div class="utxo-top">
          <code title="${escapeHtml(u.txid)}">${escapeHtml(shortTxid(u.txid))}:${u.vout}</code>
          <span class="utxo-sats">${formatSats(u.sats)}</span>
        </div>
        <div class="muted-line">
          ${branchLabel} m/${u.derivation[0]}/${u.derivation[1]} ·
          ${escapeHtml(address)} ·
          ${isPending ? '<span class="utxo-pending-tag">pending</span>' : `block ${u.height}`}
        </div>
      `;
      $list.appendChild(li);
    }
    renderStateSyncPanel();
  }

  function renderStateSyncPanel(): void {
    const panel = rt.root.querySelector<HTMLElement>("#stateSyncPanel");
    const count = rt.root.querySelector<HTMLElement>("#stateSyncCount");
    if (!panel || !count || !rt.wallet) return;
    const pending = rt.wallet.pendingStateSync;
    panel.hidden = !pending || pending.coins.length === 0;
    count.textContent = String(pending?.coins.length ?? 0);
  }

  async function refreshBalance(options: { thenHistory?: boolean } = {}): Promise<void> {
    if (!rt.wallet || rt.scanRunning) return;
    rt.scanRunning = true;
    const $refresh = rt.root.querySelector<HTMLButtonElement>("#refreshBalance");
    const $status = rt.root.querySelector<HTMLElement>("#balanceStatus");
    if ($refresh) {
      $refresh.disabled = true;
      $refresh.textContent = "Refreshing…";
    }
    if ($status) {
      $status.classList.remove("error");
      $status.textContent = "Loading the Pi-authoritative local state…";
    }

    try {
      // No address or UTXO lookup belongs on this path. New payments arrive
      // as Atomic BEEF, and legacy discovery lives behind Advanced recovery.
      renderBalance();
      if ($status) {
        const state = rt.wallet.walletState;
        $status.textContent = state
          ? `Up to date from local state revision ${state.revision}; no addresses scanned.`
          : "No secured local state. Import Atomic BEEF or run Advanced disaster recovery.";
      }
      if (options.thenHistory) {
        await actions.refreshHistory();
      }
    } catch (e) {
      if (rt.cancelled) return;
      if ($status) {
        $status.classList.add("error");
        $status.textContent = `local state refresh failed: ${(e as Error).message}`;
      }
    } finally {
      rt.scanRunning = false;
      if ($refresh) {
        $refresh.disabled = false;
        $refresh.textContent = "Refresh";
      }
    }
  }

  async function showStateSyncQr(): Promise<void> {
    if (!rt.wallet) return;
    const status = rt.root.querySelector<HTMLElement>("#stateSyncStatus");
    try {
      const envelope = buildStateSyncEnvelope(rt.wallet);
      const blob = await encodeEnvelope(envelope);
      const frames = encodeMultipartLines(blob);
      const panel = rt.root.querySelector<HTMLElement>("#stateSyncQrPanel");
      const canvas = rt.root.querySelector<HTMLCanvasElement>("#stateSyncQr");
      const total = rt.root.querySelector<HTMLElement>("#stateSyncFrames");
      const current = rt.root.querySelector<HTMLElement>("#stateSyncFrame");
      const toggle = rt.root.querySelector<HTMLButtonElement>("#stateSyncToggle");
      const prev = rt.root.querySelector<HTMLButtonElement>("#stateSyncPrev");
      const next = rt.root.querySelector<HTMLButtonElement>("#stateSyncNext");
      const hint = rt.root.querySelector<HTMLElement>("#stateSyncQrHint");
      if (!panel || !canvas || !total || !current || !toggle || !prev || !next) return;
      syncQrUnwire?.();
      syncPlayback?.stop();
      panel.hidden = false;
      total.textContent = String(frames.length);
      syncPlayback = await startPw1QrPlayback(canvas, frames, {
        width: 320,
        onFrame: (index) => { current.textContent = String(index); },
      });
      syncQrUnwire = wirePw1QrControls(syncPlayback, {
        autoToggle: toggle,
        prev,
        next,
        hint,
      });
      if (status) status.textContent = "After the Pi commits, scan its state receipt.";
    } catch (e) {
      if (status) {
        status.classList.add("error");
        status.textContent = (e as Error).message;
      }
    }
  }

  function scanStateReceipt(): void {
    if (!rt.wallet) return;
    receiptScanner?.destroy();
    const panel = rt.root.querySelector<HTMLElement>("#stateReceiptScanner");
    const host = rt.root.querySelector<HTMLElement>("#stateReceiptScannerHost");
    const status = rt.root.querySelector<HTMLElement>("#stateSyncStatus");
    if (!panel || !host) return;
    panel.hidden = false;
    receiptScanner = mountCameraScanner(host, {
      workflow: "state-receipt",
      variant: "compact",
      autoStart: true,
      onAccept: (validation) => {
        if (validation.result.workflow !== "state-receipt" || !rt.wallet) return;
        void applyStateReceipt(rt.wallet, validation.result.envelope)
          .then(() => {
            renderBalance();
            if (status) {
              status.classList.remove("error");
              status.textContent = "Payment state secured and mirrored from the Pi.";
            }
            panel.hidden = true;
            syncQrUnwire?.();
            syncPlayback?.stop();
          })
          .catch((e: Error) => {
            if (status) {
              status.classList.add("error");
              status.textContent = `receipt rejected: ${e.message}`;
            }
          });
      },
      onStopped: () => {
        panel.hidden = true;
      },
    });
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
    rt.root.querySelector<HTMLButtonElement>("#stateSyncShow")
      ?.addEventListener("click", () => void showStateSyncQr());
    rt.root.querySelector<HTMLButtonElement>("#stateReceiptScan")
      ?.addEventListener("click", scanStateReceipt);
  }

  function dispose(): void {
    syncQrUnwire?.();
    syncPlayback?.stop();
    receiptScanner?.destroy();
  }

  return {
    bind,
    renderBalance,
    refreshBalance,
    formatBalance,
    fetchBsvPrice,
    onUnitSelectChange,
    onToggleDisplayUnit,
    dispose,
  };
}
