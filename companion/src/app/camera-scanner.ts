/**
 * Shared camera scanner UI — video preview, status, progress, and controls.
 * Validates scan results against the declared workflow before calling onAccept.
 */
import { startCameraScan } from "../lib/camera-scan.js";
import {
  startPw1Scan,
  type Pw1ScanHandle,
} from "../lib/camera-scan-pw1.js";
import type { CameraScanHandle } from "../lib/camera-scan.js";
import {
  type ScanValidation,
  type ScanWorkflow,
  validateAddressQr,
  validatePw1Bytes,
} from "../lib/scan-validate.js";

export type { ScanWorkflow };

export interface CameraScannerLabels {
  idle?: string;
  scanning?: string;
  start?: string;
  stop?: string;
  cancel?: string;
  reset?: string;
}

export interface CameraScannerOptions {
  workflow: ScanWorkflow;
  /** full = Start/Stop/Reset (pair page); compact = Start/Cancel (inline flows) */
  variant?: "full" | "compact";
  showMissingFragments?: boolean;
  labels?: CameraScannerLabels;
  /** When true, start() is called automatically on mount (Send inline scans). */
  autoStart?: boolean;
  /** When true (default), hide the scanner UI after a successful scan. */
  hideOnAccept?: boolean;
  onAccept: (validation: Extract<ScanValidation, { ok: true }>) => void;
  onStopped?: () => void;
}

export interface CameraScannerHandle {
  start(): Promise<void>;
  stop(): void;
  reset(): void;
  /** Show the scanner shell again after a successful scan dismissed it. */
  reveal(): void;
  destroy(): void;
}

const DEFAULT_LABELS: Record<"full" | "compact", Required<CameraScannerLabels>> = {
  full: {
    idle: "camera idle — click Start to grant access",
    scanning: "scanning…",
    start: "Start camera",
    stop: "Stop",
    cancel: "Cancel",
    reset: "Reset",
  },
  compact: {
    idle: "click Start to scan",
    scanning: "scanning…",
    start: "Start camera",
    stop: "Stop",
    cancel: "Cancel",
    reset: "Reset",
  },
};

export function mountCameraScanner(
  host: HTMLElement,
  options: CameraScannerOptions,
): CameraScannerHandle {
  const variant = options.variant ?? "compact";
  const labels = { ...DEFAULT_LABELS[variant], ...options.labels };
  const isPw1 = options.workflow !== "send-address";

  host.innerHTML = `
    <div class="camera-scanner camera-scanner--${variant}">
      <video class="camera-scanner-video" playsinline muted autoplay aria-label="Camera preview"></video>
      <div class="camera-scanner-meta">
        <p class="camera-scanner-status muted-line" aria-live="polite"></p>
        <p class="camera-scanner-progress muted-line" hidden></p>
        <p class="camera-scanner-missing muted-line" hidden></p>
        <div class="actions camera-scanner-actions">
          <button type="button" class="primary camera-scanner-start">${labels.start}</button>
          ${
            variant === "full"
              ? `<button type="button" class="camera-scanner-stop" disabled>${labels.stop}</button>
                 <button type="button" class="camera-scanner-reset" disabled>${labels.reset}</button>`
              : `<button type="button" class="camera-scanner-cancel" hidden>${labels.cancel}</button>`
          }
        </div>
      </div>
    </div>
  `;

  const $video = host.querySelector<HTMLVideoElement>(".camera-scanner-video")!;
  const $root = host.querySelector<HTMLElement>(".camera-scanner")!;
  const $status = host.querySelector<HTMLElement>(".camera-scanner-status")!;
  const $progress = host.querySelector<HTMLElement>(".camera-scanner-progress")!;
  const $missing = host.querySelector<HTMLElement>(".camera-scanner-missing")!;
  const $start = host.querySelector<HTMLButtonElement>(".camera-scanner-start")!;
  const $stop = host.querySelector<HTMLButtonElement>(".camera-scanner-stop");
  const $reset = host.querySelector<HTMLButtonElement>(".camera-scanner-reset");
  const $cancel = host.querySelector<HTMLButtonElement>(".camera-scanner-cancel");

  let pw1Handle: Pw1ScanHandle | null = null;
  let singleHandle: CameraScanHandle | null = null;
  let active = false;
  let destroyed = false;

  function setStatus(msg: string, isError = false): void {
    $status.textContent = msg;
    $status.classList.toggle("error", isError);
  }

  function setProgress(text: string): void {
    if (!text) {
      $progress.hidden = true;
      $progress.textContent = "";
      return;
    }
    $progress.hidden = false;
    $progress.textContent = text;
  }

  function setMissing(indices: number[], total: number | null, received: number): void {
    if (!options.showMissingFragments || indices.length === 0 || total === null) {
      $missing.hidden = true;
      $missing.textContent = "";
      return;
    }
    const more = total - received > indices.length ? "…" : "";
    $missing.hidden = false;
    $missing.textContent = `missing: ${indices.join(", ")}${more}`;
  }

  function syncControls(running: boolean): void {
    $start.disabled = running;
    if ($stop) $stop.disabled = !running;
    if ($reset) $reset.disabled = !running;
    if ($cancel) $cancel.hidden = !running;
  }

  function hideScannerUi(): void {
    $video.hidden = true;
    if (options.hideOnAccept !== false) {
      $root.hidden = true;
    }
  }

  function showScannerUi(): void {
    $root.hidden = false;
    $video.hidden = false;
  }

  function stopInternal(notify = true): void {
    pw1Handle?.stop();
    pw1Handle = null;
    singleHandle?.stop();
    singleHandle = null;
    active = false;
    syncControls(false);
    setProgress("");
    setMissing([], null, 0);
    $video.hidden = true;
    if (!destroyed) {
      setStatus(labels.idle);
    }
    if (notify) options.onStopped?.();
  }

  function completeScan(): void {
    pw1Handle?.stop();
    pw1Handle = null;
    singleHandle?.stop();
    singleHandle = null;
    active = false;
    syncControls(false);
    setProgress("");
    setMissing([], null, 0);
    hideScannerUi();
    options.onStopped?.();
  }

  async function validateAndAcceptPw1(bytes: Uint8Array): Promise<boolean> {
    setStatus("Validating…");
    const validation = await validatePw1Bytes(options.workflow, bytes);
    if (!validation.ok) {
      setStatus(validation.message, true);
      return false;
    }
    options.onAccept(validation);
    completeScan();
    return true;
  }

  async function startInternal(): Promise<void> {
    if (destroyed || active) return;
    showScannerUi();
    active = true;
    syncControls(true);
    setStatus(labels.scanning);
    setProgress("");
    setMissing([], null, 0);

    if (isPw1) {
      pw1Handle = await startPw1Scan(
        $video,
        ({ received, total, missingIndices }) => {
          if (total !== null) {
            setStatus(`scanning… received ${received}/${total} fragments`);
            setProgress(`Frame ${received}${total ? ` / ${total}` : ""}`);
          } else if (received > 0) {
            setStatus(labels.scanning);
            setProgress(`${received} frame${received > 1 ? "s" : ""} received…`);
          }
          setMissing(missingIndices, total, received);
        },
        (bytes) => validateAndAcceptPw1(bytes),
        (err) => {
          setStatus(err, true);
          stopInternal(false);
        },
        {
          scanIntervalMs: options.workflow === "pair-xpub" ? 80 : 100,
          onPw1Error: (msg) => {
            setStatus(`pw1 error: ${msg} (assembler reset)`, true);
          },
        },
      );
      return;
    }

    singleHandle = await startCameraScan(
      $video,
      async (raw) => {
        const validation = validateAddressQr(raw);
        if (!validation.ok) {
          setStatus(validation.message, true);
          return false;
        }
        options.onAccept(validation);
        completeScan();
        return true;
      },
      (err) => {
        setStatus(err, true);
        stopInternal(false);
      },
    );
  }

  $start.addEventListener("click", () => {
    void startInternal();
  });
  $stop?.addEventListener("click", () => stopInternal());
  $cancel?.addEventListener("click", () => stopInternal());
  $reset?.addEventListener("click", () => {
    pw1Handle?.resetAssembler();
    setProgress("");
    setMissing([], null, 0);
    setStatus(labels.scanning);
  });

  if (options.autoStart) {
    void startInternal();
  } else {
    setStatus(labels.idle);
  }

  return {
    start: startInternal,
    stop: () => stopInternal(),
    reset: () => {
      pw1Handle?.resetAssembler();
      setProgress("");
      setMissing([], null, 0);
      setStatus(active ? labels.scanning : labels.idle);
    },
    reveal: () => {
      if (destroyed) return;
      showScannerUi();
      if (!active) {
        setStatus(labels.idle);
      }
    },
    destroy: () => {
      destroyed = true;
      stopInternal(false);
      host.innerHTML = "";
    },
  };
}
