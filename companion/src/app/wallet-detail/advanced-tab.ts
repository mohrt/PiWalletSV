import {
  KIND_XPUB,
  encodeEnvelope,
  hexToBytes,
} from "../../lib/envelope.js";
import { P2PKH } from "@bsv/sdk/script/templates";
import { encodeMultipartLines } from "../../pw1.js";
import {
  clearPw1QrCanvas,
  startPw1QrPlayback,
  wirePw1QrControls,
} from "../../lib/pw1-qr-playback.js";
import { removeWallet, updateLabel } from "../../lib/wallets.js";
import { setNextReceiveIndex } from "../../lib/wallets.js";
import { scanWalletUtxos } from "../../lib/utxo.js";
import { fetchInputProof } from "../../lib/proof-fetcher.js";
import {
  stageStateSyncCoins,
  stageAtomicBeefPayment,
  syncCoinFromProof,
} from "../../lib/wallet-state.js";
import { WocClient, effectiveWocBase } from "../../lib/woc.js";
import { escapeHtml } from "./shared.js";
import type { WalletDetailRuntime, WalletDetailTab } from "./types.js";

export interface AdvancedTab extends WalletDetailTab {
  stopExportPlayback(): void;
  onLeaveTab(): void;
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

  async function onRecoveryScan(): Promise<void> {
    if (!rt.wallet || rt.scanRunning) return;
    if (!window.confirm(
      "Run infrastructure-dependent disaster recovery discovery? Normal operation should restore state.bin instead.",
    )) return;
    const button = rt.root.querySelector<HTMLButtonElement>("#recoveryScanBtn");
    const status = rt.root.querySelector<HTMLElement>("#recoveryScanStatus");
    rt.scanRunning = true;
    if (button) button.disabled = true;
    if (status) {
      status.classList.remove("error");
      status.textContent = "Discovering used addresses with history-aware gap checks…";
    }
    try {
      if (!rt.woc) {
        rt.woc = new WocClient({ baseUrl: effectiveWocBase(rt.wallet.network) });
      }
      const result = await scanWalletUtxos(rt.wallet.xpub, rt.woc, {
        network: rt.wallet.network,
        onProgress: ({ branch, index }) => {
          if (status) status.textContent = `Recovery discovery m/${branch}/${index}…`;
        },
      });
      const known = new Set([
        ...(rt.wallet.walletState?.coins ?? []).map((coin) => `${coin.txid}:${coin.vout}`),
        ...(rt.wallet.pendingStateSync?.coins ?? []).map((coin) => `${coin.txid}:${coin.vout}`),
      ]);
      const staged = [];
      for (const utxo of result.utxos) {
        if (utxo.height <= 0 || known.has(`${utxo.txid}:${utxo.vout}`)) continue;
        if (status) status.textContent = `Saving proof for ${utxo.txid.slice(0, 8)}…`;
        const proof = await fetchInputProof(rt.woc, utxo.txid);
        const script = new P2PKH().lock(utxo.address).toHex();
        staged.push(syncCoinFromProof(utxo, script, proof));
      }
      if (staged.length > 0) await stageStateSyncCoins(rt.wallet, staged);
      const nextReceive = Math.max(rt.wallet.nextReceiveIndex, result.lastReceiveUsed + 1);
      if (nextReceive !== rt.wallet.nextReceiveIndex) {
        await setNextReceiveIndex(rt.wallet.id, nextReceive);
        rt.wallet.nextReceiveIndex = nextReceive;
      }
      if (status) {
        status.textContent = staged.length > 0
          ? `${staged.length} recovered coin(s) ready. Return to Balance to secure them on the Pi.`
          : "Recovery discovery completed; no new confirmed coins found.";
      }
    } catch (e) {
      if (status) {
        status.classList.add("error");
        status.textContent = `recovery discovery failed: ${(e as Error).message}`;
      }
    } finally {
      rt.scanRunning = false;
      if (button) button.disabled = false;
    }
  }

  async function onIncomingBeefImport(): Promise<void> {
    if (!rt.wallet) return;
    const input = rt.root.querySelector<HTMLTextAreaElement>("#incomingBeefHex");
    const status = rt.root.querySelector<HTMLElement>("#incomingBeefStatus");
    if (!input || !status) return;
    status.classList.remove("error");
    try {
      const bytes = hexToBytes(input.value);
      const pending = await stageAtomicBeefPayment(rt.wallet, bytes);
      input.value = "";
      status.textContent =
        `${pending.coins.length} payment output(s) ready. Return to Balance to secure on the Pi.`;
    } catch (e) {
      status.classList.add("error");
      status.textContent = `import failed: ${(e as Error).message}`;
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
    rt.root.querySelector<HTMLInputElement>("#renameInput")?.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "Enter") void onRenameSave();
    });
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
    rt.root.querySelector<HTMLButtonElement>("#recoveryScanBtn")
      ?.addEventListener("click", () => void onRecoveryScan());
    rt.root.querySelector<HTMLButtonElement>("#incomingBeefImport")
      ?.addEventListener("click", () => void onIncomingBeefImport());
  }

  function dispose(): void {
    stopExportPlayback();
  }

  function onLeaveTab(): void {
    hideExport();
  }

  return {
    bind,
    dispose,
    onLeaveTab,
    stopExportPlayback,
  };
}
