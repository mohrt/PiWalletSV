import { relativeTimeFrom } from "../../lib/relative-time.js";
import { fetchWalletHistory, formatTxTimestamp } from "../../lib/history.js";
import { BitailsClient, effectiveBitailsBase } from "../../lib/bitails.js";
import { WocClient, effectiveWocBase, wocExplorerTxUrl } from "../../lib/woc.js";
import { setLastHistory } from "../../lib/wallets.js";
import { escapeHtml, formatSats, shortTxid } from "./shared.js";
import type { WalletDetailActions, WalletDetailRuntime, WalletDetailTab } from "./types.js";

export interface HistoryTab extends WalletDetailTab {
  renderHistory(): void;
  refreshHistory(): Promise<void>;
  scanBalanceForHistory(): Promise<void>;
}

export function createHistoryTab(
  rt: WalletDetailRuntime,
  actions: WalletDetailActions,
): HistoryTab {
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
      $status.textContent =
        `${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"} · ` +
        `${snap.addressesQueried} address${snap.addressesQueried === 1 ? "" : "es"} checked · ` +
        `last fetched ${relativeTimeFrom(snap.at)}`;
    }
    $list.innerHTML = "";
    for (const tx of snap.entries) {
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
      await setLastHistory(rt.wallet.id, snap);
      rt.wallet.lastHistory = snap;
      renderHistory();
      if ($status) {
        $status.textContent =
          `${snap.entries.length} transaction${snap.entries.length === 1 ? "" : "s"} · ` +
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

  function bind(): void {
    rt.root
      .querySelector<HTMLButtonElement>("#refreshHistory")
      ?.addEventListener("click", () => void refreshHistory());
    rt.root
      .querySelector<HTMLButtonElement>("#scanBalanceForHistory")
      ?.addEventListener("click", () => void scanBalanceForHistory());
  }

  return {
    bind,
    renderHistory,
    refreshHistory,
    scanBalanceForHistory,
  };
}
