import { TAB_ORDER } from "./shared.js";
import type { Tab, WalletDetailActions, WalletDetailRuntime } from "./types.js";

export interface TabNav {
  switchTab(tab: Tab): void;
  syncTabAria(tab: Tab): void;
  bindTabNav(): void;
}

export function createTabNav(
  rt: WalletDetailRuntime,
  actions: WalletDetailActions,
): TabNav {
  function syncTabAria(tab: Tab): void {
    rt.root.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((btn) => {
      const selected = btn.dataset.tab === tab;
      btn.setAttribute("aria-selected", selected ? "true" : "false");
      btn.tabIndex = selected ? 0 : -1;
    });
    rt.root.querySelectorAll<HTMLElement>(".tab-panel[role=tabpanel]").forEach((p) => {
      p.tabIndex = p.id === `tab-${tab}` ? 0 : -1;
    });
  }

  function switchTab(tab: Tab): void {
    rt.activeTab = tab;
    rt.root.querySelectorAll<HTMLElement>(".tab-panel").forEach((p) => {
      p.classList.toggle("active", p.id === `tab-${tab}`);
    });
    rt.root.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    syncTabAria(tab);

    if (
      tab === "history" &&
      rt.wallet?.lastScan &&
      rt.wallet.lastHistory == null &&
      !rt.historyRunning
    ) {
      void actions.refreshHistory();
    }
    if (tab === "receive") {
      void actions.refreshReceiveIndex();
    }
    if (tab === "send" && rt.sendStep.step === "form") {
      void actions.loadFeeRates();
    }
  }

  function bindTabNav(): void {
    rt.root.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab as Tab;
        switchTab(tab);
      });
    });
    rt.root.querySelector<HTMLElement>(".tab-nav-tabs")?.addEventListener("keydown", (e) => {
      const ke = e as KeyboardEvent;
      if (ke.key !== "ArrowLeft" && ke.key !== "ArrowRight") return;
      ke.preventDefault();
      const idx = TAB_ORDER.indexOf(rt.activeTab);
      if (idx < 0) return;
      const next =
        ke.key === "ArrowRight"
          ? TAB_ORDER[(idx + 1) % TAB_ORDER.length]
          : TAB_ORDER[(idx - 1 + TAB_ORDER.length) % TAB_ORDER.length];
      switchTab(next);
      rt.root.querySelector<HTMLButtonElement>(`#tab-btn-${next}`)?.focus();
    });
  }

  return { switchTab, syncTabAria, bindTabNav };
}
