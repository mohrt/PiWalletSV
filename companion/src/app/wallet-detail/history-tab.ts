import { relativeTimeFrom } from "../../lib/relative-time.js";
import { formatTxTimestamp } from "../../lib/history.js";
import { HISTORY_PAGE_SIZE } from "../../lib/config.js";
import { wocExplorerTxUrl } from "../../lib/woc.js";
import { historyFromState } from "../../lib/wallet-state.js";
import { setLastHistory } from "../../lib/wallets.js";
import { escapeHtml, formatSats, shortTxid } from "./shared.js";
import type { WalletDetailActions, WalletDetailRuntime, WalletDetailTab } from "./types.js";

export interface HistoryTab extends WalletDetailTab {
  renderHistory(): void;
  refreshHistory(): Promise<void>;
  scanBalanceForHistory(): Promise<void>;
  loadMoreHistory(): Promise<void>;
}

export function createHistoryTab(
  rt: WalletDetailRuntime,
  actions: WalletDetailActions,
): HistoryTab {
  let historyVisibleCount = HISTORY_PAGE_SIZE;

  function historyStatusLine(snap: NonNullable<typeof rt.wallet>["lastHistory"]): string {
    if (!snap) return "";
    const shown = Math.min(historyVisibleCount, snap.entries.length);
    const countPart =
      shown < snap.entries.length
        ? `Showing ${shown} of ${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"}`
        : `${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"}`;
    const truncatedNote = snap.truncated ? " (list capped)" : "";
    return (
      `${countPart}${truncatedNote} · ` +
      (snap.addressesQueried === 0
        ? "local Atomic BEEF · "
        : `${snap.addressesQueried} address${snap.addressesQueried === 1 ? "" : "es"} checked · `) +
      `updated ${relativeTimeFrom(snap.at)}`
    );
  }

  function updateLoadMoreButton(snap: NonNullable<typeof rt.wallet>["lastHistory"]): void {
    const $loadMore = rt.root.querySelector<HTMLButtonElement>("#historyLoadMore");
    if (!$loadMore || !snap) return;
    const hasMore = historyVisibleCount < snap.entries.length;
    $loadMore.hidden = !hasMore;
    if (hasMore) {
      const remaining = snap.entries.length - historyVisibleCount;
      const next = Math.min(HISTORY_PAGE_SIZE, remaining);
      $loadMore.textContent = `Load ${next} more`;
      $loadMore.disabled = rt.historyRunning;
    }
  }
  function renderHistory(): void {
    if (!rt.wallet) return;
    const { root } = rt;
    const $list = root.querySelector<HTMLUListElement>("#historyList");
    const $empty = root.querySelector<HTMLElement>("#historyEmpty");
    const $emptyTitle = root.querySelector<HTMLElement>("#historyEmptyTitle");
    const $emptyHint = root.querySelector<HTMLElement>("#historyEmptyHint");
    const $scanBtn = root.querySelector<HTMLButtonElement>("#scanBalanceForHistory");
    const $refreshBtn = root.querySelector<HTMLButtonElement>("#refreshHistory");
    const $status = root.querySelector<HTMLElement>("#historyStatus");
    if (!$list || !$empty) return;

    const needsScan = !rt.wallet.walletState;
    if ($scanBtn) $scanBtn.hidden = true;
    if ($refreshBtn) {
      $refreshBtn.textContent = needsScan ? "Secure state first" : "Refresh";
    }

    const snap = rt.wallet.lastHistory;
    if (!snap) {
      $empty.hidden = false;
      $list.innerHTML = "";
      if ($emptyTitle) {
        $emptyTitle.textContent = needsScan
          ? "Secured wallet state required"
          : "No transaction history yet.";
      }
      if ($emptyHint) {
        $emptyHint.textContent = needsScan
          ? "Secure a payment on the Pi so history uses persisted derivation counters."
          : "Click Refresh to rebuild history from locally persisted Atomic BEEF.";
      }
      if ($status) $status.textContent = "";
      const $loadMore = root.querySelector<HTMLButtonElement>("#historyLoadMore");
      if ($loadMore) $loadMore.hidden = true;
      return;
    }
    $empty.hidden = snap.entries.length > 0;
    if ($emptyTitle && snap.entries.length === 0) {
      $emptyTitle.textContent = "No transactions found";
    }
    if ($emptyHint && snap.entries.length === 0) {
      $emptyHint.textContent =
        snap.addressesQueried === 0
          ? "No committed Atomic BEEF transactions are available yet."
          : `Checked ${snap.addressesQueried} address${snap.addressesQueried === 1 ? "" : "es"} — none had history.`;
    }
    if ($status) {
      $status.textContent = historyStatusLine(snap);
    }
    updateLoadMoreButton(snap);
    $list.innerHTML = "";
    const visible = snap.entries.slice(0, historyVisibleCount);
    for (const tx of visible) {
      const li = document.createElement("li");
      const deltaKnown = tx.deltaKnown !== false;
      const isReceive = tx.deltaSats >= 0;
      const isPending = tx.blockHeight === 0;
      li.className = `history-row ${deltaKnown ? (isReceive ? "receive" : "send") : "unknown"}${isPending ? " pending" : ""}`;
      const network = rt.wallet.network ?? "main";
      const deltaHtml = deltaKnown
        ? `<span class="history-delta ${isReceive ? "positive" : "negative"}">${isReceive ? "+" : ""}${formatSats(tx.deltaSats)}</span>`
        : `<span class="history-delta muted-line">—</span>`;
      const timeLabel = formatTxTimestamp(tx.timestamp);
      li.innerHTML = `
        <div class="history-top">
          ${deltaHtml}
          <span class="history-time muted-line">${escapeHtml(timeLabel)}</span>
        </div>
        <div class="history-meta muted-line">
          <a href="${escapeHtml(wocExplorerTxUrl(tx.txid, network))}" target="_blank"
             rel="noopener noreferrer">${escapeHtml(shortTxid(tx.txid))}</a>
          ${isPending
            ? '<span class="utxo-pending-tag">pending</span>'
            : `· block ${tx.blockHeight}`}
        </div>
      `;
      $list.appendChild(li);
    }
  }

  async function scanBalanceForHistory(): Promise<void> {
    await actions.refreshBalance({ thenHistory: true });
  }

  async function refreshHistory(): Promise<void> {
    if (!rt.wallet || rt.historyRunning) return;
    if (!rt.wallet.walletState) {
      return;
    }
    rt.historyRunning = true;
    const $btn = rt.root.querySelector<HTMLButtonElement>("#refreshHistory");
    const $status = rt.root.querySelector<HTMLElement>("#historyStatus");
    if ($btn) {
      $btn.disabled = true;
      $btn.textContent = "Rebuilding…";
    }
    if ($status) {
      $status.classList.remove("error");
      $status.textContent = "Rebuilding from locally persisted Atomic BEEF…";
    }

    try {
      const snap = historyFromState(rt.wallet);
      if (rt.cancelled) return;
      historyVisibleCount = HISTORY_PAGE_SIZE;
      await setLastHistory(rt.wallet.id, snap);
      rt.wallet.lastHistory = snap;
      renderHistory();
      if ($status) {
        const shown = Math.min(historyVisibleCount, snap.entries.length);
        const countPart =
          shown < snap.entries.length
            ? `Showing ${shown} of ${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"}`
            : `${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"}`;
        $status.textContent =
          `${countPart} · rebuilt locally · no addresses scanned`;
      }
    } catch (e) {
      if (rt.cancelled) return;
      if ($status) {
        $status.classList.add("error");
        $status.textContent = `local history rebuild failed: ${(e as Error).message}`;
      }
    } finally {
      rt.historyRunning = false;
      if ($btn) {
        $btn.disabled = false;
        $btn.textContent = "Refresh";
      }
    }
  }

  async function loadMoreHistory(): Promise<void> {
    if (!rt.wallet?.lastHistory || rt.historyRunning) return;
    const snap = rt.wallet.lastHistory;
    if (historyVisibleCount >= snap.entries.length) return;

    historyVisibleCount = Math.min(
      historyVisibleCount + HISTORY_PAGE_SIZE,
      snap.entries.length,
    );
    renderHistory();
  }

  function bind(): void {
    rt.root
      .querySelector<HTMLButtonElement>("#refreshHistory")
      ?.addEventListener("click", () => void refreshHistory());
    rt.root
      .querySelector<HTMLButtonElement>("#scanBalanceForHistory")
      ?.addEventListener("click", () => void scanBalanceForHistory());
    rt.root
      .querySelector<HTMLButtonElement>("#historyLoadMore")
      ?.addEventListener("click", () => void loadMoreHistory());
  }

  return {
    bind,
    renderHistory,
    refreshHistory,
    scanBalanceForHistory,
    loadMoreHistory,
  };
}
