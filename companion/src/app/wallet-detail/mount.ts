import { renderHeader } from "../nav.js";
import { getWallet, withDefaults } from "../../lib/wallets.js";
import { createAdvancedTab } from "./advanced-tab.js";
import { createBalanceTab } from "./balance-tab.js";
import { createHistoryTab } from "./history-tab.js";
import { createReceiveTab } from "./receive-tab.js";
import { createSendTab } from "./send-tab.js";
import { renderWalletDetailShell } from "./shell.js";
import { escapeHtml, normalizeTab, VALID_TABS } from "./shared.js";
import { createTabNav } from "./tabs.js";
import type {
  DisplayUnit,
  Tab,
  WalletDetailActions,
  WalletDetailRuntime,
  WalletDetailWallet,
} from "./types.js";

export function mountWalletDetailPage(
  root: HTMLElement,
  walletId: string,
  initialTab?: string,
): () => void {
  const tabFromRoute = normalizeTab(initialTab);
  const initialActiveTab: Tab =
    tabFromRoute && VALID_TABS.has(tabFromRoute) ? (tabFromRoute as Tab) : "balance";

  const rt: WalletDetailRuntime = {
    root,
    walletId,
    cancelled: false,
    wallet: null,
    activeTab: initialActiveTab,
    displayUnit: "sats",
    bsvUsdPrice: null,
    priceFetchedAt: 0,
    woc: null,
    bitails: null,
    scanRunning: false,
    historyRunning: false,
    receiveIndexScanRunning: false,
    receiveQrLarge: false,
    receiveAdvancePending: null,
    sendBusy: false,
    sendStep: { step: "form" },
    feeRec: null,
    addrScanHandle: null,
    pw1ScanHandle: null,
    sendQrTab: "proposal",
    sendAmountIsMax: false,
    suppressSendAmountInput: false,
    proposalPlayback: null,
    proposalQrUnwire: null,
    exportPlayback: null,
    exportQrUnwire: null,
  };

  const actions = {} as WalletDetailActions;

  const historyTab = createHistoryTab(rt, actions);
  const advancedTab = createAdvancedTab(rt);
  const receiveTab = createReceiveTab(rt, actions);
  const balanceTab = createBalanceTab(rt, actions);
  const sendTab = createSendTab(rt, actions);
  const tabNav = createTabNav(rt, actions, {
    onTabSwitch(prev, next) {
      if (prev === "advanced" && next !== "advanced") {
        advancedTab.onLeaveTab();
      }
    },
  });

  Object.assign(actions, {
    switchTab: tabNav.switchTab,
    refreshBalance: balanceTab.refreshBalance.bind(balanceTab),
    refreshHistory: historyTab.refreshHistory.bind(historyTab),
    renderReceive: receiveTab.renderReceive.bind(receiveTab),
    renderRecentList: receiveTab.renderRecentList.bind(receiveTab),
    formatBalance: balanceTab.formatBalance.bind(balanceTab),
    fetchBsvPrice: balanceTab.fetchBsvPrice.bind(balanceTab),
    renderBalance: balanceTab.renderBalance.bind(balanceTab),
    renderHistory: historyTab.renderHistory.bind(historyTab),
    renderSendPendingBanner: sendTab.renderSendPendingBanner.bind(sendTab),
    loadFeeRates: sendTab.loadFeeRates.bind(sendTab),
    refreshReceiveIndex: receiveTab.refreshReceiveIndex.bind(receiveTab),
    renderError(html: string): void {
      if (rt.cancelled) return;
      root.querySelector("#loadingCard")!.innerHTML = `
      <p class="error">${html}</p>
      <p><a href="#/wallets">← Back to wallets</a></p>
    `;
    },
  });

  root.innerHTML = `
    <main class="page">
      ${renderHeader("Wallet detail", "wallets")}
      <section id="loadingCard" class="card">
        <p class="muted-line">Loading wallet…</p>
      </section>
    </main>
  `;

  void load();

  async function load(): Promise<void> {
    let rec;
    try {
      rec = await getWallet(walletId);
    } catch (e) {
      actions.renderError(`store error: ${(e as Error).message}`);
      return;
    }
    if (rt.cancelled) return;
    if (!rec) {
      actions.renderError(`No wallet with id <code>${escapeHtml(walletId)}</code>.`);
      return;
    }
    rt.wallet = withDefaults(rec) as WalletDetailWallet;
    const storedUnit = localStorage.getItem("piwallet.listUnit") as DisplayUnit | null;
    rt.displayUnit = storedUnit ?? rec.displayUnit ?? "sats";
    renderShell();
    void receiveTab.renderReceive();
    void balanceTab.refreshBalance();
    if (rt.activeTab === "receive") void receiveTab.refreshReceiveIndex();
  }

  function renderShell(): void {
    if (!rt.wallet) return;
    root.innerHTML = renderWalletDetailShell(rt.wallet, rt.activeTab, rt.displayUnit);
    tabNav.bindTabNav();
    balanceTab.bind();
    sendTab.bind();
    receiveTab.bind();
    historyTab.bind();
    advancedTab.bind();
    balanceTab.renderBalance();
    historyTab.renderHistory();
    if (rt.activeTab === "send") void sendTab.loadFeeRates();
  }

  return () => {
    rt.cancelled = true;
    sendTab.dispose?.();
    advancedTab.dispose?.();
  };
}
