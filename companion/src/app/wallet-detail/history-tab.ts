import { relativeTimeFrom } from "../../lib/relative-time.js";
import {
  enrichWalletHistorySlice,
  fetchWalletHistory,
  formatTxTimestamp,
  historyAddressesForWallet,
} from "../../lib/history.js";
import { HISTORY_PAGE_SIZE } from "../../lib/config.js";
import { BitailsClient, effectiveBitailsBase } from "../../lib/bitails.js";
import { WocClient, effectiveWocBase, wocExplorerTxUrl } from "../../lib/woc.js";
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
      `${snap.addressesQueried} address${snap.addressesQueried === 1 ? "" : "es"} checked · ` +
      `last fetched ${relativeTimeFrom(snap.at)}`
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

    const needsScan = !rt.wallet.lastScan;
    if ($scanBtn) $scanBtn.hidden = !needsScan;
    if ($refreshBtn) {
      $refreshBtn.textContent = needsScan ? "Scan balance first" : "Refresh";
    }

    const snap = rt.wallet.lastHistory;
    if (!snap) {
      $empty.hidden = false;
      $list.innerHTML = "";
      if ($emptyTitle) {
        $emptyTitle.textContent = needsScan
          ? "Balance scan required"
          : "No transaction history yet.";
      }
      if ($emptyHint) {
        $emptyHint.textContent = needsScan
          ? "Refresh balance first so we know which addresses to check."
          : rt.wallet.network === "test"
            ? "Click Refresh to fetch history from WhatsOnChain."
            : "Click Refresh to fetch history from Bitails.";
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
        `Checked ${snap.addressesQueried} address${snap.addressesQueried === 1 ? "" : "es"} — none had history.`;
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
    if (!rt.wallet.lastScan) {
      await actions.refreshBalance({ thenHistory: true });
      return;
    }
    rt.historyRunning = true;
    const $btn = rt.root.querySelector<HTMLButtonElement>("#refreshHistory");
    const $status = rt.root.querySelector<HTMLElement>("#historyStatus");
    if ($btn) {
      $btn.disabled = true;
      $btn.textContent = "Fetching…";
    }
    if ($status) {
      $status.classList.remove("error");
      $status.textContent =
        rt.wallet.network === "test"
          ? "Fetching history from WhatsOnChain…"
          : "Fetching history from Bitails…";
    }

    if (!rt.bitails) {
      rt.bitails = new BitailsClient({
        baseUrl: effectiveBitailsBase(rt.wallet.network),
      });
    }
    if (!rt.woc) {
      rt.woc = new WocClient({ baseUrl: effectiveWocBase(rt.wallet.network) });
    }

    try {
      const snap = await fetchWalletHistory(rt.wallet.xpub, rt.bitails, {
        network: rt.wallet.network,
        woc: rt.wallet.network === "test" ? rt.woc : undefined,
        stoppedAtReceive: rt.wallet.lastScan.stoppedAt?.receive,
        stoppedAtChange: rt.wallet.lastScan.stoppedAt?.change,
        lastReceiveUsed: rt.wallet.lastScan.lastReceiveUsed,
        lastChangeUsed: rt.wallet.lastScan.lastChangeUsed,
        onProgress: (done, total, phase) => {
          if (rt.cancelled || !$status) return;
          $status.textContent =
            phase === "transactions"
              ? `Loading transaction details (${done}/${total})…`
              : `Fetching history (${done}/${total} addresses)…`;
        },
      });
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
          `${countPart} · ` +
          `${snap.addressesQueried} address${snap.addressesQueried === 1 ? "" : "es"} checked · ` +
          `last fetched just now`;
      }
    } catch (e) {
      if (rt.cancelled) return;
      if ($status) {
        $status.classList.add("error");
        $status.textContent = `history fetch failed: ${(e as Error).message}`;
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

    const prevVisible = historyVisibleCount;
    historyVisibleCount = Math.min(
      historyVisibleCount + HISTORY_PAGE_SIZE,
      snap.entries.length,
    );

    const needsEnrich =
      rt.wallet.network === "test" &&
      snap.entries
        .slice(prevVisible, historyVisibleCount)
        .some((e) => e.deltaKnown === false);

    if (!needsEnrich) {
      renderHistory();
      return;
    }

    rt.historyRunning = true;
    const $loadMore = rt.root.querySelector<HTMLButtonElement>("#historyLoadMore");
    const $status = rt.root.querySelector<HTMLElement>("#historyStatus");
    if ($loadMore) {
      $loadMore.disabled = true;
      $loadMore.textContent = "Loading…";
    }
    if ($status) {
      $status.classList.remove("error");
      $status.textContent = "Loading transaction details…";
    }
    if (!rt.woc) {
      rt.woc = new WocClient({ baseUrl: effectiveWocBase(rt.wallet.network) });
    }

    try {
      const addresses = historyAddressesForWallet(rt.wallet.xpub, {
        network: rt.wallet.network,
        stoppedAtReceive: rt.wallet.lastScan?.stoppedAt?.receive,
        stoppedAtChange: rt.wallet.lastScan?.stoppedAt?.change,
        lastReceiveUsed: rt.wallet.lastScan?.lastReceiveUsed,
        lastChangeUsed: rt.wallet.lastScan?.lastChangeUsed,
      });
      await enrichWalletHistorySlice(
        snap.entries,
        addresses,
        rt.woc,
        prevVisible,
        historyVisibleCount,
        (done, total) => {
          if (rt.cancelled || !$status) return;
          $status.textContent = `Loading transaction details (${done}/${total})…`;
        },
      );
      if (rt.cancelled) return;
      await setLastHistory(rt.wallet.id, snap);
      renderHistory();
    } catch (e) {
      if (rt.cancelled) return;
      historyVisibleCount = prevVisible;
      if ($status) {
        $status.classList.add("error");
        $status.textContent = `history load failed: ${(e as Error).message}`;
      }
      updateLoadMoreButton(snap);
    } finally {
      rt.historyRunning = false;
      if ($loadMore && historyVisibleCount < snap.entries.length) {
        $loadMore.disabled = false;
        const remaining = snap.entries.length - historyVisibleCount;
        $loadMore.textContent = `Load ${Math.min(HISTORY_PAGE_SIZE, remaining)} more`;
      }
    }
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
