import { Transaction } from "@bsv/sdk";

import { CHANGE_BRANCH, deriveAddress } from "../../lib/derive.js";
import {
  KIND_SIGNED,
  type SignedTxT,
  bytesToHex,
  decodeEnvelope,
  encodeEnvelope,
} from "../../lib/envelope.js";
import { CoinSelectError, computeMaxSendSats, selectUtxosGreedy } from "../../lib/coin-select.js";
import { decodeHexPasteToBytes } from "../../lib/hex-paste.js";
import { encodeMultipartLines } from "../../pw1.js";
import {
  startPw1QrPlayback,
  wirePw1QrControls,
} from "../../lib/pw1-qr-playback.js";
import { ProofFetchError, fetchInputProof } from "../../lib/proof-fetcher.js";
import { ProposalBuilderError, buildUnsignedProposal } from "../../lib/proposal.js";
import { noSpendableUtxosMessage, splitConfirmedPending } from "../../lib/balance-split.js";
import { confirmedUtxos } from "../../lib/utxo.js";
import { WocClient, WocError, effectiveWocBase, wocExplorerTxUrl } from "../../lib/woc.js";
import {
  DEFAULT_FEE_RATE_SATSKB,
  fetchFeeRecommendation,
  formatFeeRate,
} from "../../lib/fee.js";
import { startCameraScan } from "../../lib/camera-scan.js";
import { startPw1Scan } from "../../lib/camera-scan-pw1.js";
import {
  getDefaultCustomFeeRate,
  getFiatCurrency,
} from "../settings-page.js";
import {
  SATS_PER_BSV,
  escapeHtml,
  formatSats,
  shortAddress,
  shortTxid,
  wrapHex,
} from "./shared.js";
import type {
  SpvBuildStep,
  WalletDetailActions,
  WalletDetailRuntime,
  WalletDetailTab,
} from "./types.js";

export interface SendTab extends WalletDetailTab {
  renderSendPendingBanner(): void;
  loadFeeRates(): Promise<void>;
  resetSendCard(): void;
  stopAddrScan(): void;
  stopPw1Scan(): void;
  stopProposalPlayback(): void;
}

export function createSendTab(
  rt: WalletDetailRuntime,
  actions: WalletDetailActions,
): SendTab {
  type SendFlowPhase =
    | "form"
    | "review"
    | "build"
    | "showQr"
    | "scan"
    | "broadcast"
    | "done";

  const SEND_FLOW: Record<
    SendFlowPhase,
    { step: number; label: string; pct: number; checklist: string }
  > = {
    form: { step: 1, label: "Amount & fee", pct: 20, checklist: "form" },
    review: { step: 2, label: "Review", pct: 40, checklist: "review" },
    build: { step: 2, label: "Building proposal (SPV)…", pct: 45, checklist: "review" },
    showQr: { step: 3, label: "Show QR to Pi", pct: 60, checklist: "showQr" },
    scan: { step: 4, label: "Scan signed TX", pct: 80, checklist: "scan" },
    broadcast: { step: 5, label: "Broadcast", pct: 90, checklist: "scan" },
    done: { step: 5, label: "Complete", pct: 100, checklist: "done" },
  };

  const CHECKLIST_IDS = [
    "form",
    "review",
    "showQr",
    "scan",
    "done",
  ] as const;

  let lastSendSummary: {
    recipient: string;
    sats: number;
    feeSats: number;
  } | null = null;

  let feeRatesLoading = false;

  function stopAddrScan(): void {
    rt.addrScanHandle?.stop();
    rt.addrScanHandle = null;
    const $widget = rt.root.querySelector<HTMLElement>("#addrScanWidget");
    if ($widget) $widget.hidden = true;
  }

  async function onStartAddrScan(): Promise<void> {
    const $widget = rt.root.querySelector<HTMLElement>("#addrScanWidget");
    const $video = rt.root.querySelector<HTMLVideoElement>("#addrScanVideo");
    const $status = rt.root.querySelector<HTMLElement>("#addrScanStatus");
    const $addr = rt.root.querySelector<HTMLInputElement>("#sendAddress");
    if (!$widget || !$video || !$status || !$addr) return;

    stopAddrScan();
    $status.textContent = "Scanning for address QR…";
    $widget.hidden = false;

    rt.addrScanHandle = await startCameraScan(
      $video,
      (raw) => {
        const addr = raw.replace(/^bitcoin:/i, "").split("?")[0].trim();
        $addr.value = addr;
        stopAddrScan();
      },
      (err) => {
        if ($status) $status.textContent = err;
      },
    );
  }

  function updateSendFlowProgress(phase: SendFlowPhase): void {
    const meta = SEND_FLOW[phase];
    const $label = rt.root.querySelector<HTMLElement>("#sendProgressLabel");
    const $fill = rt.root.querySelector<HTMLElement>("#sendProgressFill");
    if ($label) {
      $label.textContent = `Step ${meta.step} of 5 — ${meta.label}`;
    }
    if ($fill) $fill.style.width = `${meta.pct}%`;

    const activeIdx = CHECKLIST_IDS.indexOf(
      meta.checklist as (typeof CHECKLIST_IDS)[number],
    );
    for (let i = 0; i < CHECKLIST_IDS.length; i++) {
      const id = CHECKLIST_IDS[i];
      const el = rt.root.querySelector<HTMLElement>(`#sendFlowStep-${id}`);
      if (!el) continue;
      el.classList.remove("active", "done");
      if (phase === "done") {
        el.classList.add("done");
      } else if (i < activeIdx) {
        el.classList.add("done");
      } else if (i === activeIdx) {
        el.classList.add("active");
      }
    }
  }

  function syncSendMaxButton(): void {
    const $max = rt.root.querySelector<HTMLButtonElement>("#sendMax");
    const $select = rt.root.querySelector<HTMLSelectElement>("#feeTierSelect");
    if (!$max) return;
    const disabled = feeRatesLoading || ($select?.disabled ?? false);
    $max.disabled = disabled;
    $max.title = disabled ? "Wait for fee rates to load" : "Send maximum confirmed balance minus fee";
  }

  function renderSendPendingBanner(): void {
    const $banner = rt.root.querySelector<HTMLElement>("#sendPendingBanner");
    if (!$banner) return;
    if (!rt.wallet?.lastScan) {
      $banner.hidden = true;
      return;
    }
    const split = splitConfirmedPending(rt.wallet.lastScan.utxos);
    if (split.allPending) {
      $banner.hidden = false;
      $banner.innerHTML =
        `<strong>Nothing spendable yet.</strong> ` +
        `${actions.formatBalance(split.pendingSats)} is pending and cannot be sent until it confirms. ` +
        `Refresh Balance after confirmation.`;
      return;
    }
    if (split.hasPending && split.confirmedSats > 0) {
      $banner.hidden = false;
      $banner.innerHTML =
        `<strong>Only confirmed coins are spendable.</strong> ` +
        `${actions.formatBalance(split.confirmedSats)} available now; ` +
        `${actions.formatBalance(split.pendingSats)} still pending. Max uses confirmed balance only.`;
      return;
    }
    $banner.hidden = true;
  }

  function getSelectedFeeRate(): number {
    const selected = rt.root.querySelector<HTMLSelectElement>("#feeTierSelect")?.value;
    if (selected === "economy") return rt.feeRec?.economy ?? DEFAULT_FEE_RATE_SATSKB;
    if (selected === "standard") return rt.feeRec?.standard ?? DEFAULT_FEE_RATE_SATSKB;
    if (selected === "priority") return rt.feeRec?.priority ?? DEFAULT_FEE_RATE_SATSKB * 5;
    const $custom = rt.root.querySelector<HTMLInputElement>("#feeCustom");
    const rate = parseInt($custom?.value ?? "", 10);
    return Number.isInteger(rate) && rate >= 0 ? rate : getDefaultCustomFeeRate();
  }

  function getSelectedFeeTier(): string {
    return rt.root.querySelector<HTMLSelectElement>("#feeTierSelect")?.value ?? "standard";
  }

  function readFormAmountSats(): number | null {
    const $amountInput = rt.root.querySelector<HTMLInputElement>("#sendAmount");
    const $unitSelect = rt.root.querySelector<HTMLSelectElement>("#sendUnit");
    if (!$amountInput || !$unitSelect) return null;
    const amountRaw = $amountInput.value.trim();
    if (amountRaw === "") return null;
    const amountNum = parseFloat(amountRaw);
    if (isNaN(amountNum) || amountNum <= 0) return null;
    const unit = $unitSelect.value as "sats" | "bsv" | "fiat";
    let sats: number;
    if (unit === "sats") {
      sats = Math.round(amountNum);
    } else if (unit === "bsv") {
      sats = Math.round(amountNum * SATS_PER_BSV);
    } else {
      if (rt.bsvUsdPrice === null || rt.bsvUsdPrice === 0) return null;
      sats = Math.round((amountNum / rt.bsvUsdPrice) * SATS_PER_BSV);
    }
    return Number.isInteger(sats) && sats > 0 ? sats : null;
  }

  function amountSatsForFeeEstimate(): number | null {
    if (rt.sendStep.step === "review") return rt.sendStep.sats;
    return readFormAmountSats();
  }

  function syncSendFormFromStep(): void {
    if (rt.sendStep.step !== "review") return;
    const $amount = rt.root.querySelector<HTMLInputElement>("#sendAmount");
    const $unit = rt.root.querySelector<HTMLSelectElement>("#sendUnit");
    if (!$amount || !$unit) return;
    const sats = rt.sendStep.sats;
    const unit = $unit.value as "sats" | "bsv" | "fiat";
    if (unit === "sats") {
      $amount.value = String(sats);
    } else if (unit === "bsv") {
      $amount.value = (sats / SATS_PER_BSV).toFixed(8);
    } else if (rt.bsvUsdPrice !== null && rt.bsvUsdPrice > 0) {
      $amount.value = ((sats / SATS_PER_BSV) * rt.bsvUsdPrice).toFixed(2);
    } else {
      $amount.value = String(sats);
    }
  }

  function showSendStep(step: "form" | "review" | "qr"): void {
    const steps = ["form", "review", "qr"];
    for (const s of steps) {
      const el = rt.root.querySelector<HTMLElement>(`#sendStep-${s}`);
      if (el) el.hidden = s !== step;
    }
    updateSendFlowProgress(step === "form" ? "form" : step === "review" ? "review" : "showQr");
    if (step === "form") {
      syncSendFormFromStep();
      void loadFeeRates();
    }
    if (step === "qr") switchSendQrTab("proposal");
  }

  function resetSpvUi(): void {
    const $steps = rt.root.querySelector<HTMLElement>("#spvSteps");
    const $detail = rt.root.querySelector<HTMLElement>("#spvDetail");
    const $banner = rt.root.querySelector<HTMLElement>("#spvCompleteBanner");
    if ($steps) $steps.hidden = true;
    if ($detail) {
      $detail.hidden = true;
      $detail.textContent = "";
      $detail.classList.remove("error");
    }
    if ($banner) {
      $banner.hidden = true;
      $banner.textContent = "";
    }
    for (const id of ["spvStep-select", "spvStep-proofs", "spvStep-build"]) {
      const el = rt.root.querySelector<HTMLElement>(`#${id}`);
      if (el) el.className = "sign-step";
    }
  }

  function setSpvBuildStep(
    step: SpvBuildStep,
    detail?: string,
    failedAt?: "select" | "proofs" | "build",
  ): void {
    const $steps = rt.root.querySelector<HTMLElement>("#spvSteps");
    const $detail = rt.root.querySelector<HTMLElement>("#spvDetail");
    const $select = rt.root.querySelector<HTMLElement>("#spvStep-select");
    const $proofs = rt.root.querySelector<HTMLElement>("#spvStep-proofs");
    const $build = rt.root.querySelector<HTMLElement>("#spvStep-build");
    if (!$steps || !$select || !$proofs || !$build) return;

    if (step === "idle") {
      resetSpvUi();
      return;
    }

    $steps.hidden = false;
    for (const el of [$select, $proofs, $build]) {
      el.className = "sign-step";
    }

    if ($detail) {
      if (detail) {
        $detail.hidden = false;
        $detail.textContent = detail;
        $detail.classList.toggle("error", step === "error");
      } else {
        $detail.hidden = true;
        $detail.textContent = "";
        $detail.classList.remove("error");
      }
    }

    if (step === "select") {
      $select.classList.add("active");
    } else if (step === "proofs") {
      $select.classList.add("done");
      $proofs.classList.add("active");
    } else if (step === "build") {
      $select.classList.add("done");
      $proofs.classList.add("done");
      $build.classList.add("active");
    } else if (step === "done") {
      for (const el of [$select, $proofs, $build]) {
        el.classList.add("done");
      }
    } else if (step === "error" && failedAt) {
      if (failedAt === "select") {
        $select.classList.add("error");
      } else if (failedAt === "proofs") {
        $select.classList.add("done");
        $proofs.classList.add("error");
      } else {
        $select.classList.add("done");
        $proofs.classList.add("done");
        $build.classList.add("error");
      }
    }
  }

  function showSpvCompleteBanner(inputCount: number, heights: number[]): void {
    const $banner = rt.root.querySelector<HTMLElement>("#spvCompleteBanner");
    if (!$banner) return;
    const uniqueHeights = [...new Set(heights)].sort((a, b) => a - b);
    const heightText = uniqueHeights.length === 1
      ? `block ${uniqueHeights[0]}`
      : `blocks ${uniqueHeights[0]}–${uniqueHeights[uniqueHeights.length - 1]}`;
    $banner.hidden = false;
    $banner.textContent =
      `✓ SPV verified — ${inputCount} confirmed input${inputCount === 1 ? "" : "s"} ` +
      `anchored at ${heightText}. The Pi re-verifies each Merkle proof before signing.`;
  }

  function switchSendQrTab(tab: "proposal" | "scan"): void {
    if (tab !== "scan" && rt.sendQrTab === "scan") stopPw1Scan();
    rt.sendQrTab = tab;
    const $proposal = rt.root.querySelector<HTMLElement>("#sendQrTab-proposal");
    const $scan = rt.root.querySelector<HTMLElement>("#sendQrTab-scan");
    if ($proposal) $proposal.hidden = tab !== "proposal";
    if ($scan) $scan.hidden = tab !== "scan";
    rt.root.querySelectorAll<HTMLButtonElement>("[data-send-qr-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.sendQrTab === tab);
    });
    if (rt.sendStep.step === "qr") {
      updateSendFlowProgress(tab === "proposal" ? "showQr" : "scan");
    }
  }

  /** Confirmed UTXOs only — mempool coins can't carry SPV proofs yet. */
  function spendableUtxos() {
    if (!rt.wallet?.lastScan) return [];
    return confirmedUtxos(rt.wallet.lastScan.utxos);
  }

  function applySendAmountSats(sats: number): void {
    const $amount = rt.root.querySelector<HTMLInputElement>("#sendAmount");
    const $unit = rt.root.querySelector<HTMLSelectElement>("#sendUnit");
    if (!$amount || !$unit) return;
    const unit = $unit.value as "sats" | "bsv" | "fiat";
    rt.suppressSendAmountInput = true;
    if (unit === "sats") {
      $amount.value = String(sats);
    } else if (unit === "bsv") {
      $amount.value = (sats / SATS_PER_BSV).toFixed(8);
    } else if (rt.bsvUsdPrice !== null && rt.bsvUsdPrice > 0) {
      $amount.value = ((sats / SATS_PER_BSV) * rt.bsvUsdPrice).toFixed(2);
    } else {
      $amount.value = String(sats);
    }
    rt.suppressSendAmountInput = false;
    refreshFeeTierEstimates();
  }

  function onFeeTierChanged(): void {
    const tier = getSelectedFeeTier();
    const $customRow = rt.root.querySelector<HTMLElement>("#feeCustomRow");
    if ($customRow) $customRow.hidden = tier !== "custom";
    if (rt.sendAmountIsMax) onSendMax();
    else refreshFeeTierEstimates();
  }

  function onSendMax(): void {
    if (!rt.wallet?.lastScan) return;
    const utxos = spendableUtxos();
    if (utxos.length === 0) return;
    const rate = getSelectedFeeRate();
    const maxSats = computeMaxSendSats(utxos, rate);
    if (maxSats <= 0) return;
    rt.sendAmountIsMax = true;
    applySendAmountSats(maxSats);
  }

  async function onSendNext(): Promise<void> {
    if (!rt.wallet) return;
    const $addr = rt.root.querySelector<HTMLInputElement>("#sendAddress")!;
    const $amountInput = rt.root.querySelector<HTMLInputElement>("#sendAmount")!;
    const $unitSelect = rt.root.querySelector<HTMLSelectElement>("#sendUnit")!;
    const $status = rt.root.querySelector<HTMLElement>("#sendFormStatus")!;
    $status.classList.remove("error");

    const recipient = $addr.value.trim();
    const amountRaw = $amountInput.value.trim();
    const amountNum = parseFloat(amountRaw);
    const unit = $unitSelect.value as "sats" | "bsv" | "fiat";

    if (!recipient) {
      $status.classList.add("error");
      $status.textContent = "enter a recipient address";
      return;
    }
    if (amountRaw === "" || isNaN(amountNum) || amountNum <= 0) {
      $status.classList.add("error");
      $status.textContent = amountRaw === "" ? "enter an amount" : `invalid amount "${amountRaw}"`;
      $amountInput.focus();
      return;
    }

    let sats: number;
    if (unit === "sats") {
      sats = Math.round(amountNum);
    } else if (unit === "bsv") {
      sats = Math.round(amountNum * SATS_PER_BSV);
    } else {
      if (rt.bsvUsdPrice === null || rt.bsvUsdPrice === 0) {
        $status.classList.add("error");
        $status.textContent = `${getFiatCurrency()} price unavailable — switch to sats or BSV`;
        return;
      }
      sats = Math.round((amountNum / rt.bsvUsdPrice) * SATS_PER_BSV);
    }

    if (!Number.isInteger(sats) || sats <= 0) {
      $status.classList.add("error");
      $status.textContent = `amount too small (rounds to ${sats} sats)`;
      $amountInput.focus();
      return;
    }
    if (!rt.wallet.lastScan || rt.wallet.lastScan.utxos.length === 0) {
      $status.classList.add("error");
      $status.textContent = "no UTXOs known — switch to the Balance tab and click Refresh first";
      return;
    }
    const utxos = spendableUtxos();
    if (utxos.length === 0) {
      $status.classList.add("error");
      $status.textContent = noSpendableUtxosMessage(
        rt.wallet.lastScan.utxos,
        formatSats,
      );
      return;
    }

    const rate = getSelectedFeeRate();
    let feeSats = 0;
    let changeSats = 0;
    try {
      const sel = selectUtxosGreedy(utxos, sats, rate);
      feeSats = sel.feeSats;
      changeSats = sel.changeSats;
    } catch (e) {
      if (e instanceof CoinSelectError) {
        $status.classList.add("error");
        $status.textContent = e.message;
        return;
      }
      const estimatedBytes = utxos.length * 148 + 2 * 34 + 10;
      feeSats = Math.ceil(estimatedBytes * rate / 1000);
      changeSats = 0;
    }

    rt.sendStep = { step: "review", recipient, sats, feeRate: rate, feeSats, changeSats };
    showSendStep("review");
    renderReview();
  }

  async function loadFeeRates(): Promise<void> {
    if (!rt.wallet) return;
    const $loading = rt.root.querySelector<HTMLElement>("#feeLoading");
    const $select = rt.root.querySelector<HTMLSelectElement>("#feeTierSelect");
    if (!rt.woc) rt.woc = new WocClient({ baseUrl: effectiveWocBase(rt.wallet.network) });

    if ($loading) {
      $loading.hidden = false;
      $loading.textContent = "Loading fee rates…";
    }
    if ($select) $select.disabled = true;
    feeRatesLoading = true;
    syncSendMaxButton();

    try {
      rt.feeRec = await fetchFeeRecommendation(rt.woc);
    } catch {
      rt.feeRec = null;
    }

    refreshFeeTierEstimates();
    onFeeTierChanged();
    if ($loading) $loading.hidden = true;
    if ($select) $select.disabled = false;
    feeRatesLoading = false;
    syncSendMaxButton();
  }

  function refreshFeeTierEstimates(): void {
    if (!rt.wallet) return;
    const economy = rt.feeRec?.economy ?? DEFAULT_FEE_RATE_SATSKB;
    const standard = rt.feeRec?.standard ?? DEFAULT_FEE_RATE_SATSKB;
    const priority = rt.feeRec?.priority ?? DEFAULT_FEE_RATE_SATSKB * 5;

    const targetSats = amountSatsForFeeEstimate();
    const estSats = targetSats !== null && rt.wallet.lastScan
      ? (rate: number) => {
          const utxos = spendableUtxos();
          if (utxos.length === 0) return null;
          try {
            return selectUtxosGreedy(utxos, targetSats, rate).feeSats;
          } catch {
            const bytes = utxos.length * 148 + 2 * 34 + 10;
            return Math.ceil(bytes * rate / 1000);
          }
        }
      : (_rate: number) => null;

    function fmtOptionLabel(name: string, rate: number): string {
      const fee = estSats(rate);
      const rateText = formatFeeRate(rate);
      if (fee !== null) {
        return `${name} — ~${fee.toLocaleString("en-US")} sats (${rateText})`;
      }
      return `${name} — ${rateText}`;
    }

    const $select = rt.root.querySelector<HTMLSelectElement>("#feeTierSelect");
    if ($select) {
      const tier = $select.value;
      for (const [value, name, rate] of [
        ["economy", "Economy", economy],
        ["standard", "Standard", standard],
        ["priority", "Priority", priority],
      ] as const) {
        const opt = $select.querySelector<HTMLOptionElement>(`option[value="${value}"]`);
        if (opt) opt.textContent = fmtOptionLabel(name, rate);
      }
      const customOpt = $select.querySelector<HTMLOptionElement>('option[value="custom"]');
      if (customOpt) {
        const customRate = getSelectedFeeTier() === "custom"
          ? getSelectedFeeRate()
          : getDefaultCustomFeeRate();
        customOpt.textContent = tier === "custom"
          ? fmtOptionLabel("Custom", customRate)
          : "Custom…";
      }
      $select.value = tier;
    }
  }

  function renderReview(): void {
    if (rt.sendStep.step !== "review") return;
    const $recipient = rt.root.querySelector<HTMLElement>("#reviewRecipient");
    const $amount = rt.root.querySelector<HTMLElement>("#reviewAmount");
    const $fee = rt.root.querySelector<HTMLElement>("#reviewFee");
    const $total = rt.root.querySelector<HTMLElement>("#reviewTotal");
    const $change = rt.root.querySelector<HTMLElement>("#reviewChange");
    const $rate = rt.root.querySelector<HTMLElement>("#reviewFeeRate");
    if ($recipient) $recipient.textContent = rt.sendStep.recipient;
    if ($amount) $amount.textContent = formatSats(rt.sendStep.sats);
    if ($fee) $fee.textContent = formatSats(rt.sendStep.feeSats);
    if ($total) $total.textContent = formatSats(rt.sendStep.sats + rt.sendStep.feeSats);
    if ($change) $change.textContent = rt.sendStep.changeSats > 0
      ? `${formatSats(rt.sendStep.changeSats)} (to your change address)`
      : "none (send max)";
    if ($rate) $rate.textContent = formatFeeRate(rt.sendStep.feeRate);
  }

  async function onBuildProposal(): Promise<void> {
    if (!rt.wallet || rt.sendBusy || rt.sendStep.step !== "review") return;
    const $status = rt.root.querySelector<HTMLElement>("#reviewStatus")!;
    const $confirm = rt.root.querySelector<HTMLButtonElement>("#reviewConfirm")!;
    $status.classList.remove("error");
    resetSpvUi();

    rt.sendBusy = true;
    $confirm.disabled = true;
    $confirm.textContent = "Building…";
    updateSendFlowProgress("build");
    setSpvBuildStep("select", "Selecting confirmed UTXOs for SPV…");
    $status.textContent = "";

    let spvPhase: SpvBuildStep = "select";
    try {
      const utxos = spendableUtxos();
      if (utxos.length === 0) {
        throw new CoinSelectError(
          noSpendableUtxosMessage(rt.wallet.lastScan!.utxos, formatSats),
        );
      }
      const selection = selectUtxosGreedy(
        utxos,
        rt.sendStep.sats,
        rt.sendStep.feeRate,
      );
      spvPhase = "proofs";
      setSpvBuildStep(
        "proofs",
        `Fetching and verifying SPV proofs for ${selection.inputs.length} input` +
          `${selection.inputs.length === 1 ? "" : "s"}…`,
      );

      if (!rt.woc) rt.woc = new WocClient({ baseUrl: effectiveWocBase(rt.wallet.network) });
      const proofs = [];
      const proofHeights: number[] = [];
      for (let i = 0; i < selection.inputs.length; i++) {
        const u = selection.inputs[i];
        setSpvBuildStep(
          "proofs",
          `SPV ${i + 1}/${selection.inputs.length}: ${u.txid.slice(0, 8)}… — ` +
            "fetching Merkle proof and block header…",
        );
        const proof = await fetchInputProof(rt.woc, u.txid);
        proofHeights.push(proof.height);
        proofs.push({ utxo: u, proof });
        setSpvBuildStep(
          "proofs",
          `SPV ${i + 1}/${selection.inputs.length}: verified at block ${proof.height} ` +
            `(Merkle rt.root matches header)`,
        );
      }

      spvPhase = "build";
      setSpvBuildStep("build", "Assembling unsigned proposal with BEEF proofs…");

      const nextChangeIdx = (rt.wallet.lastScan!.lastChangeUsed ?? -1) + 1;
      const changeDerived = deriveAddress(rt.wallet.xpub, CHANGE_BRANCH, nextChangeIdx, rt.wallet.network);
      const envelope = buildUnsignedProposal({
        walletFingerprintHex: rt.wallet.fingerprint,
        inputs: proofs.map(({ utxo, proof }) => ({
          txid: utxo.txid,
          vout: utxo.vout,
          sats: utxo.sats,
          derivation: utxo.derivation,
          proof,
        })),
        recipientAddress: rt.sendStep.recipient,
        recipientSats: rt.sendStep.sats,
        changeAddress: changeDerived.address,
        changeSats: selection.changeSats,
        changeDerivation: [CHANGE_BRANCH, nextChangeIdx],
        feeRateSatskb: rt.sendStep.feeRate,
        locktime: 0,
      });

      const blob = await encodeEnvelope(envelope);
      const frames = encodeMultipartLines(blob);

      const $frameCount = rt.root.querySelector<HTMLElement>("#proposalFrameCount");
      const $byteCount = rt.root.querySelector<HTMLElement>("#proposalByteCount");
      if ($frameCount) $frameCount.textContent = String(frames.length);
      if ($byteCount) $byteCount.textContent = String(blob.length);

      const $proposalHex = rt.root.querySelector<HTMLTextAreaElement>("#proposalHex");
      if ($proposalHex) $proposalHex.value = wrapHex(bytesToHex(blob), 64);

      setSpvBuildStep("done", "All SPV checks passed — proposal ready for the Pi.");
      showSpvCompleteBanner(selection.inputs.length, proofHeights);
      $status.textContent = "";

      lastSendSummary = {
        recipient: rt.sendStep.recipient,
        sats: rt.sendStep.sats,
        feeSats: rt.sendStep.feeSats,
      };
      showSendStep("qr");
      rt.sendStep = { step: "qr" };
      resetBroadcastWidget();
      await startProposalPlayback(frames);
    } catch (e) {
      $status.classList.add("error");
      const msg =
        e instanceof CoinSelectError ||
        e instanceof ProofFetchError ||
        e instanceof ProposalBuilderError ||
        e instanceof WocError
          ? e.message
          : (e as Error).message;
      $status.textContent = `build failed: ${msg}`;
      setSpvBuildStep("error", msg, spvPhase === "build" ? "build" : spvPhase);
    } finally {
      rt.sendBusy = false;
      $confirm.disabled = false;
      $confirm.textContent = "Build QR →";
    }
  }

  // PW1 QR playback (proposal + export)
  function stopProposalPlayback(): void {
    rt.proposalQrUnwire?.();
    rt.proposalQrUnwire = null;
    rt.proposalPlayback?.stop();
    rt.proposalPlayback = null;
  }

  async function startProposalPlayback(frames: string[]): Promise<void> {
    stopProposalPlayback();
    const $canvas = rt.root.querySelector<HTMLCanvasElement>("#proposalQr");
    const $frameIdx = rt.root.querySelector<HTMLElement>("#proposalFrameIdx");
    const $frameCount = rt.root.querySelector<HTMLElement>("#proposalFrameCount");
    const $toggle = rt.root.querySelector<HTMLButtonElement>("#proposalToggle");
    const $prev = rt.root.querySelector<HTMLButtonElement>("#proposalPrev");
    const $next = rt.root.querySelector<HTMLButtonElement>("#proposalNext");
    const $hint = rt.root.querySelector<HTMLElement>("#proposalQrHint");
    if (!$canvas || !$toggle || !$prev || !$next) return;

    rt.proposalPlayback = await startPw1QrPlayback($canvas, frames, {
      onFrame: (idx, total) => {
        if ($frameIdx) $frameIdx.textContent = String(idx);
        if ($frameCount) $frameCount.textContent = String(total);
      },
    });
    rt.proposalQrUnwire = wirePw1QrControls(rt.proposalPlayback, {
      autoToggle: $toggle,
      prev: $prev,
      next: $next,
      hint: $hint,
    });
  }

  async function onCopyProposalHex(): Promise<void> {
    const $hex = rt.root.querySelector<HTMLTextAreaElement>("#proposalHex");
    const $status = rt.root.querySelector<HTMLElement>("#proposalHexStatus");
    if (!$hex || !$status) return;
    const flat = $hex.value.replace(/\s+/g, "");
    try {
      await navigator.clipboard.writeText(flat);
      $status.classList.remove("error");
      $status.textContent = `copied ${flat.length / 2} bytes to clipboard`;
    } catch (e) {
      $hex.focus();
      $hex.select();
      $status.classList.add("error");
      $status.textContent = `clipboard denied — selected for manual copy (${(e as Error).message})`;
    }
  }

  // ---------------------------------------------------------------------------
  // Inline PW1 signed-TX scanner
  // ---------------------------------------------------------------------------

  function stopPw1Scan(): void {
    rt.pw1ScanHandle?.stop();
    rt.pw1ScanHandle = null;
    const $widget = rt.root.querySelector<HTMLElement>("#pw1ScanWidget");
    const $actions = rt.root.querySelector<HTMLElement>("#pw1ScanActions");
    if ($widget) $widget.hidden = true;
    if ($actions) $actions.hidden = false;
  }

  function setPasteSignedTxStatus(msg: string, isError = false): void {
    const $status = rt.root.querySelector<HTMLElement>("#pasteSignedTxStatus");
    if (!$status) return;
    $status.textContent = msg;
    $status.classList.toggle("error", isError);
  }

  function onPasteSignedTxClear(): void {
    const $paste = rt.root.querySelector<HTMLTextAreaElement>("#pasteSignedTx");
    if ($paste) {
      $paste.value = "";
      $paste.focus();
    }
    setPasteSignedTxStatus("");
  }

  async function onPasteSignedTxDecode(): Promise<void> {
    const $paste = rt.root.querySelector<HTMLTextAreaElement>("#pasteSignedTx");
    if (!$paste) return;
    const decoded = decodeHexPasteToBytes($paste.value);
    if (!decoded.ok) {
      setPasteSignedTxStatus(decoded.error, true);
      return;
    }
    setPasteSignedTxStatus(`decoding ${decoded.bytes.length} bytes…`);
    stopPw1Scan();
    await onSignedTxReceived(decoded.bytes);
    const dropped =
      decoded.parsed.droppedLabeled.length + decoded.parsed.droppedOther.length;
    const noteParts = [`decoded ${decoded.bytes.length} bytes`];
    if (dropped > 0) noteParts.push(`ignored ${dropped} non-hex line(s)`);
    setPasteSignedTxStatus(noteParts.join(" — "));
  }

  async function onStartPw1Scan(): Promise<void> {
    const $widget = rt.root.querySelector<HTMLElement>("#pw1ScanWidget");
    const $actions = rt.root.querySelector<HTMLElement>("#pw1ScanActions");
    const $video = rt.root.querySelector<HTMLVideoElement>("#pw1ScanVideo");
    const $status = rt.root.querySelector<HTMLElement>("#pw1ScanStatus");
    const $progress = rt.root.querySelector<HTMLElement>("#pw1ScanProgress");
    if (!$widget || !$video || !$status || !$actions) return;

    stopPw1Scan();
    $status.textContent = "Scanning for signed TX…";
    if ($progress) $progress.textContent = "";
    $widget.hidden = false;
    $actions.hidden = true;

    rt.pw1ScanHandle = await startPw1Scan(
      $video,
      (received, total) => {
        if ($progress) {
          $progress.textContent = total
            ? `Frame ${received} / ${total}`
            : received > 0 ? `${received} frame${received > 1 ? "s" : ""} received…` : "";
        }
      },
      (bytes) => {
        stopPw1Scan();
        void onSignedTxReceived(bytes);
      },
      (err) => {
        if ($status) $status.textContent = err;
      },
    );
  }

  function showBroadcastWidget(): void {
    updateSendFlowProgress("broadcast");
    const $broadcast = rt.root.querySelector<HTMLElement>("#broadcastWidget");
    const $pw1Actions = rt.root.querySelector<HTMLElement>("#pw1ScanActions");
    if ($broadcast) $broadcast.hidden = false;
    if ($pw1Actions) $pw1Actions.hidden = true;
  }

  async function onSignedTxReceived(bytes: Uint8Array): Promise<void> {
    const $broadcast = rt.root.querySelector<HTMLElement>("#broadcastWidget");
    const $info = rt.root.querySelector<HTMLElement>("#broadcastInfo");
    const $broadcastStatus = rt.root.querySelector<HTMLElement>("#broadcastStatus");
    if (!$broadcast || !$info) return;

    let env: Awaited<ReturnType<typeof decodeEnvelope>>;
    try {
      env = await decodeEnvelope(bytes);
    } catch (e) {
      if ($info) $info.textContent = `decode error: ${(e as Error).message}`;
      showBroadcastWidget();
      switchSendQrTab("scan");
      return;
    }

    if (env.kind !== KIND_SIGNED) {
      if ($info) $info.textContent = `unexpected envelope type: ${env.kind}`;
      showBroadcastWidget();
      switchSendQrTab("scan");
      return;
    }

    const signed = env as SignedTxT;
    let txid = "";
    let rawHex = "";
    let sizeBytes = 0;
    try {
      const tx = Transaction.fromAtomicBEEF(Array.from(signed.atomicBeef));
      txid = tx.id("hex") as string;
      rawHex = tx.toHex();
      sizeBytes = rawHex.length / 2;
    } catch (e) {
      if ($info) {
        $info.textContent =
          `signed_tx Atomic BEEF parse failed: ${(e as Error).message}`;
      }
      showBroadcastWidget();
      switchSendQrTab("scan");
      return;
    }

    if ($info) {
      $info.innerHTML = `Ready to broadcast<br><code class="mono" style="font-size:0.75rem;word-break:break-all">${txid}</code>${sizeBytes ? `<br><span class="muted-line">${sizeBytes} bytes</span>` : ""}`;
    }
    if ($broadcastStatus) $broadcastStatus.textContent = "";
    showBroadcastWidget();
    switchSendQrTab("scan");
    hideBroadcastDone();

    const $btn = rt.root.querySelector<HTMLButtonElement>("#broadcastBtn");
    if ($btn) {
      $btn.dataset.signedHex = rawHex;
      $btn.dataset.txid = txid;
      $btn.disabled = false;
      $btn.textContent = "Broadcast";
    }
  }

  function hideBroadcastDone(): void {
    const $done = rt.root.querySelector<HTMLButtonElement>("#broadcastDone");
    if ($done) $done.hidden = true;
    const $explorer = rt.root.querySelector<HTMLAnchorElement>("#broadcastExplorer");
    if ($explorer) $explorer.hidden = true;
  }

  function showBroadcastDone(explorerUrl?: string): void {
    const $done = rt.root.querySelector<HTMLButtonElement>("#broadcastDone");
    if ($done) $done.hidden = false;
    const $explorer = rt.root.querySelector<HTMLAnchorElement>("#broadcastExplorer");
    if ($explorer) {
      if (explorerUrl) {
        $explorer.href = explorerUrl;
        $explorer.hidden = false;
      } else {
        $explorer.hidden = true;
      }
    }
  }

  async function onBroadcast(): Promise<void> {
    if (!rt.wallet) return;
    const $btn = rt.root.querySelector<HTMLButtonElement>("#broadcastBtn");
    const $status = rt.root.querySelector<HTMLElement>("#broadcastStatus");
    if (!$btn || !$status) return;

    const rawHex = $btn.dataset.signedHex;
    if (!rawHex) { $status.textContent = "no signed TX — scan the Pi's response first"; return; }

    $btn.disabled = true;
    $btn.textContent = "Broadcasting…";
    hideBroadcastDone();
    $status.classList.remove("error", "success");
    $status.textContent = "";

    try {
      if (!rt.woc) rt.woc = new WocClient({ baseUrl: effectiveWocBase(rt.wallet.network) });
      const txid = $btn.dataset.txid ?? "";
      await rt.woc.broadcastRaw(rawHex, txid || undefined);
      const explorer = wocExplorerTxUrl(txid, rt.wallet.network);
      const $panel = rt.root.querySelector<HTMLElement>("#broadcastWidget");
      const $info = rt.root.querySelector<HTMLElement>("#broadcastInfo");
      if ($panel) $panel.classList.add("success");
      const $summary = rt.root.querySelector<HTMLElement>("#broadcastSuccessSummary");
      if ($summary && lastSendSummary) {
        $summary.hidden = false;
        $summary.innerHTML =
          `<strong class="broadcast-success-head">Transaction sent</strong>` +
          `<dl class="broadcast-success-details">` +
          `<dt>To</dt><dd>${escapeHtml(shortAddress(lastSendSummary.recipient))}</dd>` +
          `<dt>Amount</dt><dd>${escapeHtml(formatSats(lastSendSummary.sats))}</dd>` +
          `<dt>Fee</dt><dd>${escapeHtml(formatSats(lastSendSummary.feeSats))}</dd>` +
          `</dl>`;
      } else if ($summary) {
        $summary.hidden = true;
      }
      if ($info) {
        $info.innerHTML =
          `<span class="muted-line">Txid</span><br>` +
          `<code class="mono broadcast-txid">${escapeHtml(shortTxid(txid))}</code>`;
      }
      $status.classList.remove("error");
      $status.classList.add("success");
      $status.textContent =
        "Accepted by the network. It may take a few minutes to confirm on-chain.";
      delete $btn.dataset.signedHex;
      $btn.hidden = true;
      const $pw1Actions = rt.root.querySelector<HTMLElement>("#pw1ScanActions");
      const $pw1Widget = rt.root.querySelector<HTMLElement>("#pw1ScanWidget");
      if ($pw1Actions) $pw1Actions.hidden = true;
      if ($pw1Widget) $pw1Widget.hidden = true;
      stopPw1Scan();
      updateSendFlowProgress("done");
      showBroadcastDone(explorer);
    } catch (e) {
      const $panel = rt.root.querySelector<HTMLElement>("#broadcastWidget");
      if ($panel) $panel.classList.remove("success");
      $status.classList.add("error");
      $status.classList.remove("success");
      let msg: string;
      if (e instanceof WocError) {
        msg = e.message;
        if (e.bodySnippet) msg += `\nWoC said: ${e.bodySnippet}`;
      } else {
        msg = (e as Error).message;
      }
      $status.textContent = `broadcast failed: ${msg}`;
      $btn.disabled = false;
      $btn.hidden = false;
      $btn.textContent = "Retry broadcast";
      hideBroadcastDone();
    }
  }

  async function onBroadcastDone(): Promise<void> {
    resetSendCard();
    actions.switchTab("balance");
    await actions.refreshBalance();
  }

  function resetBroadcastWidget(): void {
    const $broadcast = rt.root.querySelector<HTMLElement>("#broadcastWidget");
    const $pw1Actions = rt.root.querySelector<HTMLElement>("#pw1ScanActions");
    if ($broadcast) {
      $broadcast.hidden = true;
      $broadcast.classList.remove("success");
    }
    if ($pw1Actions) $pw1Actions.hidden = false;
    const $broadcastBtn = rt.root.querySelector<HTMLButtonElement>("#broadcastBtn");
    if ($broadcastBtn) {
      $broadcastBtn.hidden = false;
      $broadcastBtn.disabled = false;
      $broadcastBtn.textContent = "Broadcast";
      delete $broadcastBtn.dataset.signedHex;
      delete $broadcastBtn.dataset.txid;
    }
    hideBroadcastDone();
    const $broadcastStatus = rt.root.querySelector<HTMLElement>("#broadcastStatus");
    if ($broadcastStatus) {
      $broadcastStatus.classList.remove("error", "success");
      $broadcastStatus.textContent = "";
    }
    const $broadcastInfo = rt.root.querySelector<HTMLElement>("#broadcastInfo");
    if ($broadcastInfo) $broadcastInfo.textContent = "";
    const $summary = rt.root.querySelector<HTMLElement>("#broadcastSuccessSummary");
    if ($summary) {
      $summary.hidden = true;
      $summary.innerHTML = "";
    }
    const $explorer = rt.root.querySelector<HTMLAnchorElement>("#broadcastExplorer");
    if ($explorer) $explorer.hidden = true;
  }

  function resetSendCard(): void {
    stopProposalPlayback();
    stopPw1Scan();
    rt.sendStep = { step: "form" };
    rt.sendAmountIsMax = false;
    showSendStep("form");
    updateSendFlowProgress("form");
    resetBroadcastWidget();
    resetSpvUi();
    const $status = rt.root.querySelector<HTMLElement>("#sendFormStatus");
    if ($status) {
      $status.classList.remove("error");
      $status.textContent = "";
    }
  }


  function bind(): void {
    rt.root.querySelector<HTMLButtonElement>("#sendSpvInfoTip")
      ?.addEventListener("click", (e) => {
        e.preventDefault();
        const tip = rt.root.querySelector<HTMLElement>("#sendSpvInfoText");
        if (tip) tip.hidden = !tip.hidden;
      });
    rt.root.querySelector<HTMLButtonElement>("#scanAddress")
      ?.addEventListener("click", () => void onStartAddrScan());
    rt.root.querySelector<HTMLButtonElement>("#addrScanCancel")
      ?.addEventListener("click", stopAddrScan);
    rt.root.querySelector<HTMLButtonElement>("#sendNext")
      ?.addEventListener("click", () => void onSendNext());
    rt.root.querySelector<HTMLButtonElement>("#sendMax")
      ?.addEventListener("click", onSendMax);
    rt.root.querySelector<HTMLSelectElement>("#sendUnit")
      ?.addEventListener("change", (e) => {
        const unit = (e.target as HTMLSelectElement).value;
        if (unit === "fiat") void actions.fetchBsvPrice();
        if (rt.sendAmountIsMax) onSendMax();
      });
    rt.root.querySelector<HTMLInputElement>("#sendAmount")
      ?.addEventListener("input", () => {
        if (rt.suppressSendAmountInput) return;
        rt.sendAmountIsMax = false;
        refreshFeeTierEstimates();
      });
    rt.root.querySelector<HTMLButtonElement>("#reviewBack")
      ?.addEventListener("click", () => {
        syncSendFormFromStep();
        rt.sendStep = { step: "form" };
        showSendStep("form");
      });
    rt.root.querySelector<HTMLButtonElement>("#reviewConfirm")
      ?.addEventListener("click", () => void onBuildProposal());
    rt.root.querySelector<HTMLButtonElement>("#sendQrGoScan")
      ?.addEventListener("click", () => switchSendQrTab("scan"));
    rt.root.querySelector<HTMLButtonElement>("#proposalDone")
      ?.addEventListener("click", resetSendCard);
    rt.root.querySelector<HTMLButtonElement>("#proposalDone2")
      ?.addEventListener("click", resetSendCard);
    rt.root.querySelector<HTMLButtonElement>("#copyProposalHex")
      ?.addEventListener("click", () => void onCopyProposalHex());
    rt.root.querySelector<HTMLButtonElement>("#pw1ScanStart")
      ?.addEventListener("click", () => void onStartPw1Scan());
    rt.root.querySelector<HTMLButtonElement>("#pw1ScanCancel")
      ?.addEventListener("click", stopPw1Scan);
    rt.root.querySelector<HTMLButtonElement>("#pasteSignedTxDecode")
      ?.addEventListener("click", () => void onPasteSignedTxDecode());
    rt.root.querySelector<HTMLButtonElement>("#pasteSignedTxClear")
      ?.addEventListener("click", onPasteSignedTxClear);
    rt.root.querySelector<HTMLButtonElement>("#broadcastBtn")
      ?.addEventListener("click", () => void onBroadcast());
    rt.root.querySelector<HTMLButtonElement>("#broadcastDone")
      ?.addEventListener("click", () => void onBroadcastDone());
    rt.root.querySelectorAll<HTMLButtonElement>("[data-send-qr-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.sendQrTab as "proposal" | "scan";
        switchSendQrTab(tab);
      });
    });
    rt.root.querySelector<HTMLSelectElement>("#feeTierSelect")
      ?.addEventListener("change", () => onFeeTierChanged());
    rt.root.querySelector<HTMLInputElement>("#feeCustom")
      ?.addEventListener("input", () => onFeeTierChanged());
    syncSendMaxButton();
  }

  function onActivate(): void {
    syncSendMaxButton();
    if (rt.sendStep.step === "form") void loadFeeRates();
    else if (rt.sendStep.step === "review") updateSendFlowProgress("review");
    else if (rt.sendStep.step === "qr") {
      updateSendFlowProgress(rt.sendQrTab === "proposal" ? "showQr" : "scan");
    }
  }

  function dispose(): void {
    stopProposalPlayback();
    stopAddrScan();
    stopPw1Scan();
  }

  return {
    bind,
    onActivate,
    dispose,
    renderSendPendingBanner,
    loadFeeRates,
    resetSendCard,
    stopAddrScan,
    stopPw1Scan,
    stopProposalPlayback,
  };
}
