import type { FeeRecommendation } from "../../lib/fee.js";
import type { NetworkT } from "../../lib/envelope.js";
import type { WalletRecord } from "../../lib/wallets.js";
import type { BitailsClient } from "../../lib/bitails.js";
import type { WocClient } from "../../lib/woc.js";
import type { CameraScannerHandle } from "../camera-scanner.js";
import type { Pw1QrPlayback } from "../../lib/pw1-qr-playback.js";

export type Tab = "balance" | "send" | "receive" | "history" | "advanced";

export type DisplayUnit = "sats" | "bsv" | "fiat";

export type SendStep =
  | { step: "form" }
  | {
      step: "review";
      recipient: string;
      sats: number;
      feeRate: number;
      feeSats: number;
      changeSats: number;
    }
  | { step: "qr" };

export type SpvBuildStep = "idle" | "select" | "proofs" | "build" | "done" | "error";

export type WalletDetailWallet = WalletRecord & {
  nextReceiveIndex: number;
  network: NetworkT;
};

export interface WalletDetailTab {
  bind(): void;
  onActivate?(): void;
  dispose?(): void;
}

export interface WalletDetailRuntime {
  root: HTMLElement;
  walletId: string;
  cancelled: boolean;
  wallet: WalletDetailWallet | null;
  activeTab: Tab;
  displayUnit: DisplayUnit;
  bsvUsdPrice: number | null;
  priceFetchedAt: number;
  woc: WocClient | null;
  bitails: BitailsClient | null;
  scanRunning: boolean;
  historyRunning: boolean;
  receiveIndexScanRunning: boolean;
  receiveQrLarge: boolean;
  receiveAdvancePending: number | null;
  sendBusy: boolean;
  sendStep: SendStep;
  feeRec: FeeRecommendation | null;
  addrScanHandle: CameraScannerHandle | null;
  pw1ScanHandle: CameraScannerHandle | null;
  sendQrTab: "proposal" | "scan";
  sendAmountIsMax: boolean;
  suppressSendAmountInput: boolean;
  proposalPlayback: Pw1QrPlayback | null;
  proposalQrUnwire: (() => void) | null;
  exportPlayback: Pw1QrPlayback | null;
  exportQrUnwire: (() => void) | null;
}

export interface WalletDetailActions {
  switchTab(tab: Tab): void;
  refreshBalance(options?: { thenHistory?: boolean }): Promise<void>;
  refreshHistory(): Promise<void>;
  renderReceive(): Promise<void>;
  renderRecentList(): void;
  formatBalance(sats: number): string;
  fetchBsvPrice(): Promise<void>;
  renderError(html: string): void;
  renderBalance(): void;
  renderHistory(): void;
  renderSendPendingBanner(): void;
  loadFeeRates(): Promise<void>;
  refreshReceiveIndex(): Promise<void>;
}
