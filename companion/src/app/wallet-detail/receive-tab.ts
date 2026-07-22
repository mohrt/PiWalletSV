import QRCode from "qrcode";

import { RECEIVE_BRANCH, deriveAddress, deriveAddressBatch } from "../../lib/derive.js";
import { setNextReceiveIndex } from "../../lib/wallets.js";
import {
  RECENT_WINDOW,
  RECEIVE_QR_SIZE_DEFAULT,
  RECEIVE_QR_SIZE_LARGE,
  escapeHtml,
} from "./shared.js";
import type { WalletDetailActions, WalletDetailRuntime, WalletDetailTab } from "./types.js";

export interface ReceiveTab extends WalletDetailTab {
  renderReceive(): Promise<void>;
  renderRecentList(): void;
  refreshReceiveIndex(): Promise<void>;
}

export function createReceiveTab(
  rt: WalletDetailRuntime,
  actions: WalletDetailActions,
): ReceiveTab {
  /** Receive index the user last checked "verified on Pi" for. */
  let verifiedReceiveIndex: number | null = null;

  function isReceiveVerified(): boolean {
    return rt.wallet != null && verifiedReceiveIndex === rt.wallet.nextReceiveIndex;
  }

  function syncReceiveVerifiedUi(): void {
    const verified = isReceiveVerified();
    const $block = rt.root.querySelector<HTMLElement>("#receiveShareBlock");
    const $check = rt.root.querySelector<HTMLInputElement>("#receiveVerifiedCheck");
    const $hint = rt.root.querySelector<HTMLElement>("#receiveVerifyHint");
    const $copy = rt.root.querySelector<HTMLButtonElement>("#copyAddress");
    const $gate = rt.root.querySelector<HTMLElement>("#receiveQrGate");
    const $toggle = rt.root.querySelector<HTMLButtonElement>("#receiveQrSizeToggle");
    if ($block) $block.classList.toggle("receive-gated", !verified);
    if ($check) $check.checked = verified;
    if ($hint) $hint.hidden = verified;
    if ($copy) $copy.disabled = !verified;
    if ($gate) {
      $gate.hidden = verified;
      $gate.setAttribute("aria-hidden", verified ? "true" : "false");
    }
    if ($toggle) $toggle.disabled = !verified;
  }

  function onReceiveVerifiedChange(): void {
    const $check = rt.root.querySelector<HTMLInputElement>("#receiveVerifiedCheck");
    if (!rt.wallet || !$check) return;
    verifiedReceiveIndex = $check.checked ? rt.wallet.nextReceiveIndex : null;
    syncReceiveVerifiedUi();
  }

  function receiveAdvanceWarning(nextIndex: number): string | null {
    if (!rt.wallet || nextIndex <= rt.wallet.nextReceiveIndex) return null;
    if (!rt.wallet.walletState) {
      return "Secure wallet state on the Pi before skipping receive addresses.";
    }
    const recommended = rt.wallet.walletState.nextReceiveIndex;
    if (nextIndex <= recommended) return null;
    const lastUsed = recommended - 1;
    if (lastUsed < 0) {
      return (
        `Address #${nextIndex} is ahead of secured wallet state. ` +
        `Only advance after you no longer expect payment to the current address.`
      );
    }
    return (
      `Address #${nextIndex} is beyond the last used receive index (#${lastUsed}). ` +
      `Only advance if you have already shared address #${nextIndex - 1} ` +
      `or no longer expect payments there.`
    );
  }

  function showReceiveAdvanceConfirm(message: string, targetIndex: number): void {
    rt.receiveAdvancePending = targetIndex;
    const $strip = rt.root.querySelector<HTMLElement>("#receiveAdvanceConfirm");
    const $msg = rt.root.querySelector<HTMLElement>("#receiveAdvanceConfirmMsg");
    if ($msg) $msg.textContent = message;
    if ($strip) $strip.hidden = false;
  }

  function hideReceiveAdvanceConfirm(): void {
    rt.receiveAdvancePending = null;
    const $strip = rt.root.querySelector<HTMLElement>("#receiveAdvanceConfirm");
    if ($strip) $strip.hidden = true;
  }

  async function applyReceiveIndex(next: number): Promise<void> {
    if (!rt.wallet) return;
    try {
      await setNextReceiveIndex(rt.wallet.id, next);
      rt.wallet.nextReceiveIndex = next;
    } catch (e) {
      const $s = rt.root.querySelector<HTMLElement>("#receiveStatus");
      if ($s) {
        $s.classList.add("error");
        $s.textContent = `cannot advance index: ${(e as Error).message}`;
      }
      return;
    }
    void renderReceive();
  }

  async function shiftIndex(delta: number): Promise<void> {
    if (!rt.wallet) return;
    const next = rt.wallet.nextReceiveIndex + delta;
    if (next < 0) return;
    hideReceiveAdvanceConfirm();
    if (delta > 0) {
      const warning = receiveAdvanceWarning(next);
      if (warning) {
        showReceiveAdvanceConfirm(warning, next);
        return;
      }
    }
    await applyReceiveIndex(next);
  }

  async function onCopy(): Promise<void> {
    const $addr = rt.root.querySelector<HTMLElement>("#receiveAddress");
    if (!$addr) return;
    try {
      await navigator.clipboard.writeText($addr.textContent ?? "");
      const $btn = rt.root.querySelector<HTMLButtonElement>("#copyAddress");
      if ($btn) {
        const orig = $btn.textContent;
        $btn.textContent = "copied!";
        setTimeout(() => {
          if ($btn) $btn.textContent = orig;
        }, 1200);
      }
    } catch (e) {
      const $s = rt.root.querySelector<HTMLElement>("#receiveStatus");
      if ($s) $s.textContent = `clipboard error: ${(e as Error).message}`;
    }
  }

  async function renderReceive(): Promise<void> {
    if (!rt.wallet || rt.cancelled) return;
    const idx = rt.wallet.nextReceiveIndex;
    let derived: ReturnType<typeof deriveAddress>;
    try {
      derived = deriveAddress(rt.wallet.xpub, RECEIVE_BRANCH, idx, rt.wallet.network);
    } catch (e) {
      actions.renderError(`derivation error: ${(e as Error).message}`);
      return;
    }
    const $path = rt.root.querySelector<HTMLElement>("#receivePath")!;
    const $addr = rt.root.querySelector<HTMLElement>("#receiveAddress")!;
    const $canvas = rt.root.querySelector<HTMLCanvasElement>("#receiveQr")!;
    const $status = rt.root.querySelector<HTMLElement>("#receiveStatus")!;
    const $prev = rt.root.querySelector<HTMLButtonElement>("#prevIdx")!;
    const $steps = rt.root.querySelector<HTMLElement>("#receiveVerifySteps");

    $path.textContent = `${rt.wallet.path} / ${derived.subPath}`;
    $addr.textContent = derived.address;
    $prev.disabled = idx === 0;
    const $windowDesc = rt.root.querySelector<HTMLElement>("#receiveWindowDesc");
    if ($windowDesc) $windowDesc.textContent = `m/0/${idx}`;
    $status.textContent =
      idx === 0 ? "first address (index 0)" : `address #${idx} on receive branch`;

    if ($steps) {
      $steps.innerHTML =
        idx === 0
          ? "On the Pi: open <strong>Show deposit address</strong> — it starts at address #0."
          : `On the Pi: open <strong>Show deposit address</strong> and press RIGHT ` +
            `<strong>${idx} time${idx === 1 ? "" : "s"}</strong> to reach address #${idx}.`;
    }

    try {
      const qrSize = rt.receiveQrLarge ? RECEIVE_QR_SIZE_LARGE : RECEIVE_QR_SIZE_DEFAULT;
      $canvas.width = qrSize;
      $canvas.height = qrSize;
      await QRCode.toCanvas($canvas, derived.address, {
        margin: 1,
        width: qrSize,
        errorCorrectionLevel: "M",
      });
      const $toggle = rt.root.querySelector<HTMLButtonElement>("#receiveQrSizeToggle");
      if ($toggle) {
        $toggle.textContent = rt.receiveQrLarge ? "Standard QR" : "Larger QR";
      }
    } catch (e) {
      $status.textContent = `qr render error: ${(e as Error).message}`;
    }
    renderRecentList();
    syncReceiveVerifiedUi();
  }

  function renderRecentList(): void {
    if (!rt.wallet || rt.cancelled) return;
    const center = rt.wallet.nextReceiveIndex;
    const start = Math.max(0, center - Math.floor(RECENT_WINDOW / 2));
    const batch = deriveAddressBatch(
      rt.wallet.xpub,
      RECEIVE_BRANCH,
      start,
      RECENT_WINDOW,
      rt.wallet.network,
    );
    const $list = rt.root.querySelector<HTMLUListElement>("#receiveList")!;
    $list.innerHTML = "";
    for (const a of batch) {
      const li = document.createElement("li");
      li.className = a.index === center ? "addr-row current" : "addr-row";
      li.innerHTML = `
        <span class="addr-index">m/0/${a.index}</span>
        <code class="addr-addr">${escapeHtml(a.address)}</code>
        <button class="copy" type="button" aria-label="Copy address" data-address="${escapeHtml(a.address)}" type="button">Copy</button>
      `;
      $list.appendChild(li);
    }
    const verified = isReceiveVerified();
    $list.querySelectorAll<HTMLButtonElement>("button.copy").forEach((b) => {
      b.disabled = !verified;
      b.addEventListener("click", () => {
        const v = b.dataset.address ?? "";
        void navigator.clipboard
          .writeText(v)
          .then(() => {
            const orig = b.textContent;
            b.textContent = "copied!";
            setTimeout(() => {
              b.textContent = orig;
            }, 1200);
          })
          .catch(() => {});
      });
    });
  }

  async function refreshReceiveIndex(): Promise<void> {
    if (!rt.wallet || rt.receiveIndexScanRunning) return;
    rt.receiveIndexScanRunning = true;
    try {
      const fresh = Math.max(
        rt.wallet.nextReceiveIndex,
        rt.wallet.walletState?.nextReceiveIndex ?? 0,
      );
      if (rt.cancelled) return;
      if (fresh !== rt.wallet.nextReceiveIndex) {
        await setNextReceiveIndex(rt.wallet.id, fresh);
        rt.wallet.nextReceiveIndex = fresh;
        void renderReceive();
      }
    } catch {
      // silently ignore — stale index is better than a broken UI
    } finally {
      rt.receiveIndexScanRunning = false;
    }
  }

  function bind(): void {
    rt.root
      .querySelector<HTMLInputElement>("#receiveVerifiedCheck")
      ?.addEventListener("change", onReceiveVerifiedChange);
    rt.root.querySelector<HTMLButtonElement>("#receiveVerifyTip")?.addEventListener("click", (e) => {
      e.preventDefault();
      const btn = e.currentTarget as HTMLButtonElement;
      const tip = rt.root.querySelector<HTMLElement>("#receiveVerifyText");
      if (!tip) return;
      tip.hidden = !tip.hidden;
      btn.setAttribute("aria-expanded", tip.hidden ? "false" : "true");
    });
    rt.root.querySelector<HTMLButtonElement>("#copyAddress")?.addEventListener("click", () => void onCopy());
    rt.root.querySelector<HTMLButtonElement>("#prevIdx")?.addEventListener("click", () => void shiftIndex(-1));
    rt.root.querySelector<HTMLButtonElement>("#nextIdx")?.addEventListener("click", () => void shiftIndex(1));
    rt.root.querySelector<HTMLButtonElement>("#receiveQrSizeToggle")?.addEventListener("click", () => {
      rt.receiveQrLarge = !rt.receiveQrLarge;
      void renderReceive();
    });
    rt.root.querySelector<HTMLButtonElement>("#receiveAdvanceConfirmYes")?.addEventListener("click", () => {
      if (rt.receiveAdvancePending === null) return;
      const target = rt.receiveAdvancePending;
      hideReceiveAdvanceConfirm();
      void applyReceiveIndex(target);
    });
    rt.root
      .querySelector<HTMLButtonElement>("#receiveAdvanceConfirmNo")
      ?.addEventListener("click", hideReceiveAdvanceConfirm);
    syncReceiveVerifiedUi();
  }

  function onActivate(): void {
    syncReceiveVerifiedUi();
    void refreshReceiveIndex();
  }

  return {
    bind,
    onActivate,
    renderReceive,
    renderRecentList,
    refreshReceiveIndex,
  };
}
