import {
  KIND_XPUB,
  encodeEnvelope,
  hexToBytes,
} from "../../lib/envelope.js";
import { encodeMultipartLines } from "../../pw1.js";
import {
  clearPw1QrCanvas,
  startPw1QrPlayback,
  wirePw1QrControls,
} from "../../lib/pw1-qr-playback.js";
import { removeWallet, updateLabel } from "../../lib/wallets.js";
import { escapeHtml } from "./shared.js";
import type { WalletDetailRuntime, WalletDetailTab } from "./types.js";

export interface AdvancedTab extends WalletDetailTab {
  stopExportPlayback(): void;
}

export function createAdvancedTab(rt: WalletDetailRuntime): AdvancedTab {
  function stopExportPlayback(): void {
    rt.exportQrUnwire?.();
    rt.exportQrUnwire = null;
    rt.exportPlayback?.stop();
    rt.exportPlayback = null;
  }

  async function startExportPlayback(frames: string[]): Promise<void> {
    stopExportPlayback();
    const $canvas = rt.root.querySelector<HTMLCanvasElement>("#exportQr");
    const $frameIdx = rt.root.querySelector<HTMLElement>("#exportFrameIdx");
    const $frameCount = rt.root.querySelector<HTMLElement>("#exportFrameCount");
    const $toggle = rt.root.querySelector<HTMLButtonElement>("#exportToggle");
    const $prev = rt.root.querySelector<HTMLButtonElement>("#exportPrev");
    const $next = rt.root.querySelector<HTMLButtonElement>("#exportNext");
    const $hint = rt.root.querySelector<HTMLElement>("#exportQrHint");
    if (!$canvas || !$toggle || !$prev || !$next) return;

    rt.exportPlayback = await startPw1QrPlayback($canvas, frames, {
      onFrame: (idx, total) => {
        if ($frameIdx) $frameIdx.textContent = String(idx);
        if ($frameCount) $frameCount.textContent = String(total);
      },
    });
    rt.exportQrUnwire = wirePw1QrControls(rt.exportPlayback, {
      autoToggle: $toggle,
      prev: $prev,
      next: $next,
      hint: $hint,
    });
  }

  async function onShowExport(): Promise<void> {
    if (!rt.wallet) return;
    const envelope = {
      kind: KIND_XPUB,
      xpub: rt.wallet.xpub,
      path: rt.wallet.path,
      label: rt.wallet.label,
      fingerprint: hexToBytes(rt.wallet.fingerprint),
      network: rt.wallet.network,
    } as const;
    const blob = await encodeEnvelope(envelope);
    const frames = encodeMultipartLines(blob);
    const $result = rt.root.querySelector<HTMLElement>("#exportResult")!;
    const $count = rt.root.querySelector<HTMLElement>("#exportFrameCount")!;
    const $showBtn = rt.root.querySelector<HTMLButtonElement>("#exportShow");
    $result.hidden = false;
    if ($showBtn) $showBtn.hidden = true;
    $count.textContent = String(frames.length);
    await startExportPlayback(frames);
  }

  function hideExport(): void {
    stopExportPlayback();
    clearPw1QrCanvas(rt.root.querySelector<HTMLCanvasElement>("#exportQr")!);
    const $result = rt.root.querySelector<HTMLElement>("#exportResult");
    if ($result) $result.hidden = true;
    const $showBtn = rt.root.querySelector<HTMLButtonElement>("#exportShow");
    if ($showBtn) $showBtn.hidden = false;
  }

  async function onCopyXpub(): Promise<void> {
    const $btn = rt.root.querySelector<HTMLButtonElement>("#copyXpub");
    const $status = rt.root.querySelector<HTMLElement>("#copyXpubStatus");
    if (!$btn || !$status || !rt.wallet) return;
    try {
      await navigator.clipboard.writeText(rt.wallet.xpub);
      const orig = $btn.textContent;
      $btn.textContent = "copied!";
      $status.textContent = "";
      setTimeout(() => {
        $btn.textContent = orig;
      }, 1200);
    } catch (e) {
      $status.textContent = `clipboard error: ${(e as Error).message}`;
    }
  }

  function syncRenameSaveBtn(): void {
    if (!rt.wallet) return;
    const $input = rt.root.querySelector<HTMLInputElement>("#renameInput");
    const $btn = rt.root.querySelector<HTMLButtonElement>("#renameSaveBtn");
    if (!$input || !$btn) return;
    const trimmed = $input.value.trim();
    $btn.disabled = !trimmed || trimmed === rt.wallet.label;
  }

  async function onRenameSave(): Promise<void> {
    if (!rt.wallet) return;
    const $input = rt.root.querySelector<HTMLInputElement>("#renameInput");
    const $status = rt.root.querySelector<HTMLElement>("#renameStatus");
    if (!$input || !$status) return;
    const trimmed = $input.value.trim();
    if (!trimmed) {
      $status.textContent = "Label cannot be empty.";
      return;
    }
    if (trimmed === rt.wallet.label) {
      $status.textContent = "No change.";
      return;
    }
    try {
      await updateLabel(rt.wallet.id, trimmed);
      rt.wallet = { ...rt.wallet, label: trimmed };
      const $headerLabel = rt.root.querySelector<HTMLElement>(".page-header h1");
      if ($headerLabel) $headerLabel.firstChild!.textContent = escapeHtml(trimmed);
      $status.textContent = `Renamed to "${trimmed}".`;
      syncRenameSaveBtn();
      setTimeout(() => {
        if ($status) $status.textContent = "";
      }, 2000);
    } catch (e) {
      $status.textContent = `rename failed: ${(e as Error).message}`;
    }
  }

  function onRemoveWalletOpen(): void {
    rt.root.querySelector<HTMLElement>("#removeWalletActions")!.hidden = true;
    rt.root.querySelector<HTMLElement>("#removeWalletConfirm")!.hidden = false;
  }

  function onRemoveWalletCancel(): void {
    rt.root.querySelector<HTMLElement>("#removeWalletConfirm")!.hidden = true;
    rt.root.querySelector<HTMLElement>("#removeWalletActions")!.hidden = false;
  }

  async function onRemoveWalletConfirm(): Promise<void> {
    if (!rt.wallet) return;
    const $status = rt.root.querySelector<HTMLElement>("#removeWalletStatus");
    try {
      await removeWallet(rt.wallet.id);
      window.location.hash = "#/wallets";
    } catch (e) {
      if ($status) $status.textContent = `remove failed: ${(e as Error).message}`;
      onRemoveWalletCancel();
    }
  }

  function bind(): void {
    rt.root
      .querySelector<HTMLButtonElement>("#exportShow")
      ?.addEventListener("click", () => void onShowExport());
    rt.root.querySelector<HTMLButtonElement>("#exportHide")?.addEventListener("click", hideExport);
    rt.root
      .querySelector<HTMLButtonElement>("#copyXpub")
      ?.addEventListener("click", () => void onCopyXpub());
    rt.root
      .querySelector<HTMLButtonElement>("#renameSaveBtn")
      ?.addEventListener("click", () => void onRenameSave());
    rt.root.querySelector<HTMLInputElement>("#renameInput")?.addEventListener("input", syncRenameSaveBtn);
    syncRenameSaveBtn();
    rt.root
      .querySelector<HTMLButtonElement>("#removeWalletBtn")
      ?.addEventListener("click", onRemoveWalletOpen);
    rt.root
      .querySelector<HTMLButtonElement>("#removeWalletConfirmNo")
      ?.addEventListener("click", onRemoveWalletCancel);
    rt.root
      .querySelector<HTMLButtonElement>("#removeWalletConfirmYes")
      ?.addEventListener("click", () => void onRemoveWalletConfirm());
  }

  function dispose(): void {
    stopExportPlayback();
  }

  return {
    bind,
    dispose,
    stopExportPlayback,
  };
}
