/**
 * Pair wallet page — scan Pi xpub QR or paste xpub manually.
 */
import {
  KIND_XPUB,
  type XpubExportT,
  bytesToHex,
} from "../lib/envelope.js";
import { xpubFingerprint, DerivationError } from "../lib/derive.js";
import { renderHeader } from "./nav.js";
import { getDefaultNetwork } from "./settings-page.js";
import {
  type WalletRecord,
  WalletStoreError,
  addWallet,
  findByFingerprintAndPath,
} from "../lib/wallets.js";
import type { NetworkT } from "../lib/envelope.js";
import {
  mountCameraScanner,
} from "./camera-scanner.js";

export function mountScannerPage(root: HTMLElement): () => void {
  root.innerHTML = `
    <main class="page">
      ${renderHeader("Add wallet", "wallets")}

      <section class="card scan-card">
        <p class="muted-line scan-card-desc">Scan xpub from the Pi or another companion wallet.</p>
        <div id="pairCameraHost" class="camera-scanner-host"></div>
      </section>

      <section class="card paste-hex-card">
        <details>
          <summary>Or paste xpub</summary>
          <p class="muted-line">
            Paste the xpub below, and select the network.
            <span class="info-tip-wrap">
              <button class="info-tip" type="button" aria-label="What is an xpub?">ⓘ</button>
              <span class="info-tip-text" hidden>
                An xpub (extended public key) lets the companion derive your wallet
                addresses without exposing your private keys or seed phrase.
              </span>
            </span>
          </p>
          <textarea id="pasteXpub" class="hex-blob" rows="3"
            placeholder="xpub6…"
            spellcheck="false" autocorrect="off" autocomplete="off"></textarea>
          <label class="field">
            <span>Derivation path</span>
            <input id="pasteXpubPath" type="text"
              value="m/44'/236'/0'"
              spellcheck="false" autocorrect="off" autocomplete="off"
              aria-describedby="pasteXpubPathHint" />
            <p id="pasteXpubPathHint" class="muted-line">
              BIP44 account path from the Pi (default <code>m/44'/236'/0'</code>).
            </p>
          </label>
          <label class="field">
            <span>Network</span>
            <select id="pasteXpubNetwork">
              <option value="main">Mainnet (BSV)</option>
              <option value="test">Testnet (TBSV)</option>
            </select>
          </label>
          <div class="actions">
            <button id="pasteXpubImport" class="primary" type="button">
              Import xpub
            </button>
            <button id="pasteXpubClear" type="button">Clear</button>
          </div>
          <p id="pasteXpubStatus" class="muted-line"></p>
        </details>
      </section>
    </main>

    <div id="pairOverlay" class="pair-overlay" hidden role="dialog"
      aria-modal="true" aria-labelledby="pairDialogTitle">
      <div class="pair-modal card pair-card">
        <h2 id="pairDialogTitle">Save as paired wallet</h2>
        <p id="pairStatus" class="muted-line" aria-live="polite"></p>
        <label class="field-label" for="pairLabel">Wallet label</label>
        <input id="pairLabel" type="text" maxlength="64"
          autocomplete="off" autocorrect="off" spellcheck="false" />
        <p id="pairFp" class="muted-line"></p>
        <div class="actions">
          <button id="pairSave" class="primary" type="button">Save wallet</button>
          <button id="pairDismiss" type="button">Cancel</button>
          <a id="pairOpenList" href="#/wallets" hidden>Open wallets list</a>
        </div>
      </div>
    </div>
  `;

  const $pasteXpub = root.querySelector<HTMLTextAreaElement>("#pasteXpub")!;
  const $pasteXpubPath = root.querySelector<HTMLInputElement>("#pasteXpubPath")!;
  const $pasteXpubNetwork = root.querySelector<HTMLSelectElement>("#pasteXpubNetwork")!;
  $pasteXpubNetwork.value = getDefaultNetwork();
  const $pasteXpubImport = root.querySelector<HTMLButtonElement>("#pasteXpubImport")!;
  const $pasteXpubClear = root.querySelector<HTMLButtonElement>("#pasteXpubClear")!;
  const $pasteXpubStatus = root.querySelector<HTMLElement>("#pasteXpubStatus")!;
  const $pairOverlay = root.querySelector<HTMLElement>("#pairOverlay")!;
  const $pairStatus = root.querySelector<HTMLElement>("#pairStatus")!;
  const $pairLabel = root.querySelector<HTMLInputElement>("#pairLabel")!;
  const $pairFp = root.querySelector<HTMLElement>("#pairFp")!;
  const $pairSave = root.querySelector<HTMLButtonElement>("#pairSave")!;
  const $pairDismiss = root.querySelector<HTMLButtonElement>("#pairDismiss")!;
  const $pairOpenList = root.querySelector<HTMLAnchorElement>("#pairOpenList")!;
  const $pairCameraHost = root.querySelector<HTMLElement>("#pairCameraHost")!;

  let pairXpub: XpubExportT | null = null;
  let pairFocusBefore: HTMLElement | null = null;

  const cameraScanner = mountCameraScanner($pairCameraHost, {
    workflow: "pair-xpub",
    variant: "full",
    showMissingFragments: true,
    onAccept: (validation) => {
      if (validation.result.workflow === "pair-xpub") {
        void showPairCard(validation.result.envelope);
      }
    },
  });

  function focusableIn(container: HTMLElement): HTMLElement[] {
    return Array.from(
      container.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), textarea, select, [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => !el.hidden && (el.offsetParent !== null || el === document.activeElement));
  }

  function hidePairCard(): void {
    pairXpub = null;
    $pairOverlay.hidden = true;
    document.body.classList.remove("pair-locked");
    pairFocusBefore?.focus();
    pairFocusBefore = null;
    $pairStatus.classList.remove("error");
    $pairStatus.textContent = "";
    $pairFp.textContent = "";
    $pairLabel.value = "";
    $pairLabel.disabled = false;
    $pairSave.disabled = false;
    $pairSave.textContent = "Save wallet";
    $pairOpenList.hidden = true;
  }

  async function showPairCard(env: XpubExportT): Promise<void> {
    pairXpub = env;
    const fpHex = bytesToHex(env.fingerprint);
    $pairLabel.value = env.label;
    $pairLabel.disabled = false;
    $pairSave.textContent = "Save wallet";
    $pairOpenList.hidden = true;
    const netLabel = env.network === "test" ? " · TESTNET" : "";
    $pairFp.textContent = `fingerprint ${fpHex} · ${env.path}${netLabel}`;
    $pairStatus.classList.remove("error");

    let existing: WalletRecord | null = null;
    try {
      existing = await findByFingerprintAndPath(fpHex, env.path);
    } catch (e) {
      $pairStatus.classList.add("error");
      $pairStatus.textContent = `wallet store error: ${(e as Error).message}`;
      $pairSave.disabled = true;
      $pairOverlay.hidden = false;
      document.body.classList.add("pair-locked");
      pairFocusBefore = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      $pairDismiss.focus();
      return;
    }

    const sameNetworkDup =
      existing && (existing.network ?? "main") === (env.network ?? "main");

    if (existing && sameNetworkDup) {
      $pairStatus.textContent =
        `already paired as "${existing.label}" on ${new Date(existing.addedAt).toLocaleString()}.`;
      $pairSave.disabled = true;
      $pairOpenList.hidden = false;
    } else if (existing) {
      const otherNet = (existing.network ?? "main") === "test" ? "TESTNET" : "mainnet";
      const thisNet = env.network === "test" ? "TESTNET" : "mainnet";
      $pairStatus.textContent =
        `note: this seed is already paired as "${existing.label}" on ${otherNet}; ` +
        `saving will create a new ${thisNet} entry alongside it.`;
      $pairSave.disabled = false;
    } else {
      const isImport = env.label === "Imported wallet";
      $pairStatus.textContent = isImport
        ? "Enter a label for this wallet, then save."
        : `Pi reported label "${env.label}". You can rename it before saving.`;
      $pairSave.disabled = false;
    }

    $pairOverlay.hidden = false;
    document.body.classList.add("pair-locked");
    pairFocusBefore = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    if (existing && sameNetworkDup) {
      $pairDismiss.focus();
    } else {
      $pairLabel.focus();
      $pairLabel.select();
    }
  }

  async function onPairSave(): Promise<void> {
    if (!pairXpub) return;
    const label = $pairLabel.value.trim() || pairXpub.label;
    $pairSave.disabled = true;
    try {
      const rec = await addWallet({
        label,
        xpub: pairXpub.xpub,
        fingerprint: bytesToHex(pairXpub.fingerprint),
        path: pairXpub.path,
        network: pairXpub.network,
      });
      $pairStatus.classList.remove("error");
      const netSuffix = rec.network === "test" ? " (TESTNET)" : "";
      $pairStatus.textContent =
        `saved "${rec.label}"${netSuffix} — opening wallets…`;
      $pairLabel.disabled = true;
      setTimeout(() => {
        window.location.hash = "#/wallets";
      }, 800);
    } catch (e) {
      $pairStatus.classList.add("error");
      const msg = e instanceof WalletStoreError ? e.message : (e as Error).message;
      $pairStatus.textContent = `save failed: ${msg}`;
      if (msg.includes("duplicate-pair")) $pairOpenList.hidden = false;
    }
  }

  function setXpubStatus(msg: string, isError = false): void {
    $pasteXpubStatus.textContent = msg;
    $pasteXpubStatus.classList.toggle("error", isError);
  }

  async function onPasteXpubImport(): Promise<void> {
    const raw = $pasteXpub.value.trim();
    if (!raw) {
      setXpubStatus("paste an xpub key first", true);
      return;
    }

    if (!raw.startsWith("xpub") && !raw.startsWith("tpub")) {
      setXpubStatus(
        "unrecognised key — expected a BIP32 extended public key (xpub… or tpub…)",
        true,
      );
      return;
    }

    const network = $pasteXpubNetwork.value as NetworkT;

    let fp: Uint8Array;
    try {
      fp = xpubFingerprint(raw);
    } catch (e) {
      setXpubStatus(
        `invalid xpub: ${e instanceof DerivationError ? e.message : (e as Error).message}`,
        true,
      );
      return;
    }

    setXpubStatus("xpub valid — fill in a label in the dialog.");

    const path = $pasteXpubPath.value.trim();
    if (!/^m(\/\d+'?)+$/.test(path)) {
      setXpubStatus(
        "invalid derivation path — expected format like m/44'/236'/0'",
        true,
      );
      return;
    }

    await showPairCard({
      kind: KIND_XPUB,
      xpub: raw,
      path,
      label: "Imported wallet",
      fingerprint: fp,
      network,
    });
  }

  root.querySelector<HTMLButtonElement>(".info-tip")
    ?.addEventListener("click", (e) => {
      e.preventDefault();
      const tip = root.querySelector<HTMLElement>(".info-tip-text");
      if (tip) tip.hidden = !tip.hidden;
    });

  $pasteXpubImport.addEventListener("click", () => {
    void onPasteXpubImport();
  });
  $pasteXpubClear.addEventListener("click", () => {
    $pasteXpub.value = "";
    setXpubStatus("");
    hidePairCard();
    $pasteXpub.focus();
  });
  $pairSave.addEventListener("click", () => {
    void onPairSave();
  });
  $pairDismiss.addEventListener("click", hidePairCard);
  $pairOverlay.addEventListener("click", (e) => {
    if (e.target === $pairOverlay) hidePairCard();
  });
  $pairOverlay.addEventListener("keydown", (e) => {
    const ke = e as KeyboardEvent;
    if (ke.key === "Escape") {
      ke.preventDefault();
      hidePairCard();
      return;
    }
    if (ke.key !== "Tab") return;
    const modal = $pairOverlay.querySelector<HTMLElement>(".pair-modal");
    if (!modal) return;
    const items = focusableIn(modal);
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (ke.shiftKey && document.activeElement === first) {
      ke.preventDefault();
      last.focus();
    } else if (!ke.shiftKey && document.activeElement === last) {
      ke.preventDefault();
      first.focus();
    }
  });

  return () => {
    cameraScanner.destroy();
    hidePairCard();
  };
}
