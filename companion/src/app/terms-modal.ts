/**
 * First-load disclaimer modal.
 *
 * `ensureTermsAccepted(parent)` renders a blocking overlay (parented to
 * `document.body`) when the user hasn't yet accepted the current
 * `termsVersion`. The promise resolves once they tick "I have read and
 * accept" and click Continue. The overlay removes itself; the rest of
 * the app then mounts as normal.
 *
 * When acceptance is already on record (matching version), the function
 * resolves immediately without rendering anything.
 */
import { DOCS_BASE_URL } from "../lib/config.js";
import {
  CURRENT_TERMS_VERSION,
  isTermsAccepted,
  recordAcceptance,
} from "../lib/terms.js";

const MODAL_ID = "piwallet-terms-modal";

function focusableIn(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), textarea, select, [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => el.offsetParent !== null || el === document.activeElement);
}

export async function ensureTermsAccepted(): Promise<void> {
  if (isTermsAccepted()) return;
  return new Promise<void>((resolve) => {
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;

    const overlay = document.createElement("div");
    overlay.id = MODAL_ID;
    overlay.className = "terms-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "termsTitle");
    overlay.innerHTML = `
      <div class="terms-modal">
        <h1 id="termsTitle">PiWalletSV — please read before continuing</h1>
        <p class="terms-version">
          Disclaimer version <code>${CURRENT_TERMS_VERSION}</code>. The
          short bullets below are a pointer; the full, canonical text
          lives at
          <a href="${DOCS_BASE_URL}/disclaimer/" target="_blank" rel="noopener noreferrer">
            ${DOCS_BASE_URL.replace(/^https?:\/\//, "")}/disclaimer
          </a>.
        </p>
        <ul class="terms-bullets">
          <li>
            <strong>Beta software.</strong> Pre-release, unaudited
            personal project — expect bugs. Keys and seed phrase stay on
            the Pi. Restore from any BIP44-compatible wallet with your
            seed phrase; PiWalletSV is not required.
          </li>
          <li>
            <strong>Non-custodial.</strong> You — and only you — are
            responsible for your seed phrase, your PIN, and your
            physical signer. The author cannot recover lost funds.
          </li>
          <li>
            <strong>No warranty.</strong> The Software is provided
            "AS IS". No liability for losses, taxes, regulatory issues,
            or third-party (WhatsOnChain) outages.
          </li>
          <li>
            <strong>Air-gap discipline.</strong> Never enter your seed
            phrase into anything online — including this companion app,
            cloud editors, password managers, or AI assistants.
          </li>
          <li>
            <strong>Kits and case goods.</strong> Software stays MIT;
            commercial resale of PiWalletSV kits or printed case goods
            requires prior permission — contact
            <a href="https://x.com/PiWalletSV" target="_blank"
               rel="noopener noreferrer">@PiWalletSV on X</a>.
          </li>
          <li>
            <strong>Not financial / legal / tax advice.</strong>
            Consult qualified professionals before relying on this
            wallet for material amounts.
          </li>
        </ul>
        <p class="terms-version" style="margin-top: 0.25rem;">
          Want the plain-English trust model first? See
          <a href="${DOCS_BASE_URL}/security/" target="_blank" rel="noopener noreferrer">
            ${DOCS_BASE_URL.replace(/^https?:\/\//, "")}/security ↗
          </a>.
        </p>
        <label class="terms-accept">
          <input type="checkbox" id="termsAccept" />
          <span>
            I have read and accept the full
            <a href="${DOCS_BASE_URL}/disclaimer/"
               target="_blank" rel="noopener noreferrer">disclaimer</a>
            on my own responsibility.
          </span>
        </label>
        <div class="actions">
          <button id="termsContinue" class="primary" type="button" disabled>
            Continue
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    document.body.classList.add("terms-locked");

    const $check = overlay.querySelector<HTMLInputElement>("#termsAccept")!;
    const $btn = overlay.querySelector<HTMLButtonElement>("#termsContinue")!;

    function dismiss(): void {
      recordAcceptance();
      overlay.remove();
      document.body.classList.remove("terms-locked");
      previousFocus?.focus();
      resolve();
    }

    overlay.addEventListener("keydown", (e) => {
      const ke = e as KeyboardEvent;
      if (ke.key === "Escape") {
        ke.preventDefault();
        $check.focus();
        return;
      }
      if (ke.key !== "Tab") return;
      const items = focusableIn(overlay);
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

    $check.addEventListener("change", () => {
      $btn.disabled = !$check.checked;
    });
    $btn.addEventListener("click", () => {
      if (!$check.checked) return;
      dismiss();
    });

    $check.focus();
  });
}
