/**
 * PiWallet Pass screen (`#/pass?rq=<request URL>`): show what an app is
 * asking for, pick the wallet that answers, and approve with the phone's
 * passkey. Spec: piwalletsv-pay/notes/pass-protocol.md.
 */
import { renderHeader } from "./nav.js";
import { escapeHtml } from "./wallet-detail/shared.js";
import {
  PassError,
  type PassRequest,
  fetchRequest,
  postResponse,
  purposeLabel,
  walletProof,
} from "../lib/pass-protocol.js";
import {
  type WalletChoice,
  createPasskey,
  defaultPasskeyName,
  matchWallets,
  usePasskey,
} from "../lib/passkeys.js";
import { addPasskey, listWallets, touchPasskey } from "../lib/wallets.js";

/** Shown instead of the first-run screen when a PiWallet Pass link opens in a browser with no wallets. */
export function mountNoWalletsHere(root: HTMLElement, onPairHere: () => void): void {
  root.innerHTML = `
    <main class="page">
      <header class="page-header"><h1>PiWallet Pass</h1></header>
      <section class="card pass-card">
        <h2>No wallets in this browser</h2>
        <p>This PiWallet Pass request opened in a browser that has no paired wallets.</p>
        <p>Open the PiWallet companion where your wallets are, such as the one on your Home Screen, tap <strong>Scan</strong>, and scan the code again.</p>
        <p class="muted-line">The Camera app opens links in your browser, which keeps its own storage, separate from the Home Screen companion.</p>
        <div class="actions"><button id="passPairHere" type="button">Pair a wallet in this browser instead</button></div>
      </section>
    </main>
  `;
  root.querySelector("#passPairHere")!.addEventListener("click", onPairHere);
}

export function mountPassPage(root: HTMLElement, requestUrl: string | null): () => void {
  let timer = 0;
  let destroyed = false;

  root.innerHTML = `
    <main class="page">
      ${renderHeader("PiWallet Pass", "wallets")}
      <section class="card pass-card" id="passCard" aria-live="polite">
        <p class="muted-line">Loading the request…</p>
      </section>
    </main>
  `;
  const $card = root.querySelector<HTMLElement>("#passCard")!;

  function showProblem(message: string): void {
    window.clearInterval(timer);
    $card.innerHTML = `
      <h2>Can't continue</h2>
      <p class="error">${escapeHtml(message)}</p>
      <div class="actions"><a class="primary-link" href="#/wallets">Back to wallets</a></div>`;
  }

  void (async () => {
    if (!requestUrl) return showProblem("That is not a PiWallet Pass link.");
    let request: PassRequest;
    try {
      request = await fetchRequest(requestUrl);
    } catch (e) {
      return showProblem(e instanceof PassError ? e.message : "Could not load the request.");
    }
    if (destroyed) return;
    const match = matchWallets(request, await listWallets());
    if (match.problem) return showProblem(match.problem);
    render(request, match.choices, match.discoverable);
  })();

  function render(request: PassRequest, choices: WalletChoice[], discoverable: boolean): void {
    const creating = request.mode === "create";
    const facts = [
      ["Asking to", purposeLabel(request.purpose)],
      ...(request.account ? [["Account", request.account]] : []),
      ...(request.device ? [["Started on", request.device]] : []),
    ];
    const walletHtml = discoverable
      ? `<p>No wallet in this companion has a passkey for this site. Your phone will show the PiWallet Pass passkeys it holds: pick the one for <strong>${escapeHtml(new URL(request.app.origin).host)}</strong>.</p>`
      : choices.length === 1
        ? `<p><strong>${escapeHtml(choices[0].wallet.label)}</strong> <span class="muted-line">${escapeHtml(choices[0].wallet.fingerprint)}</span>${choices[0].passkey ? ` · passkey “${escapeHtml(choices[0].passkey.name)}”` : ""}</p>`
        : `<fieldset class="pass-wallets"><legend>Answer with</legend>${choices
            .map(
              (choice, i) =>
                `<label><input type="radio" name="passWallet" value="${i}" ${i === 0 ? "checked" : ""}> ${escapeHtml(choice.wallet.label)} <span class="muted-line">${escapeHtml(choice.wallet.fingerprint)}</span>${choice.passkey ? ` · ${creating ? "already connected" : `“${escapeHtml(choice.passkey.name)}”`}` : ""}</label>`,
            )
            .join("")}</fieldset>`;
    $card.innerHTML = `
      <h2>Request from</h2>
      <p class="pass-origin">${escapeHtml(request.app.origin)}</p>
      <p class="muted-line">It calls itself “${escapeHtml(request.app.name)}”. Approve only if you started this on that site just now.</p>
      <dl class="pass-facts">
        ${facts.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join("")}
        <dt>Valid for</dt><dd id="passLeft"></dd>
      </dl>
      <h2>Wallet</h2>
      ${walletHtml}
      ${creating ? `<label class="field"><span>Passkey name</span><input id="passName" type="text" maxlength="64" value="${escapeHtml(defaultPasskeyName(request))}" autocomplete="off"></label>` : ""}
      <p class="error" id="passError" hidden></p>
      <div class="actions">
        <button class="primary" id="passApprove" type="button">Approve</button>
        <button id="passDeny" type="button">Deny</button>
      </div>`;

    const $approve = $card.querySelector<HTMLButtonElement>("#passApprove")!;
    const $error = $card.querySelector<HTMLElement>("#passError")!;
    const $left = $card.querySelector<HTMLElement>("#passLeft")!;
    const tick = (): void => {
      const left = Math.max(0, Math.floor((Date.parse(request.expires) - Date.now()) / 1000));
      $left.textContent = left ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : "expired";
      if (!left) {
        window.clearInterval(timer);
        $approve.disabled = true;
      }
    };
    tick();
    timer = window.setInterval(tick, 1000);

    $card.querySelector("#passDeny")!.addEventListener("click", () => {
      window.location.hash = "#/wallets";
    });
    $approve.addEventListener("click", () => void approve());

    async function approve(): Promise<void> {
      $approve.disabled = true;
      $error.hidden = true;
      const picked = $card.querySelector<HTMLInputElement>("input[name=passWallet]:checked");
      const choice = discoverable ? null : choices[picked ? Number(picked.value) : 0];
      try {
        let message: string;
        const proof = choice ? walletProof(request, choice.wallet.xpub) : undefined;
        if (creating) {
          const name = $card.querySelector<HTMLInputElement>("#passName")!.value.trim() || defaultPasskeyName(request);
          const created = await createPasskey(request, choice!.wallet, name);
          message = await postResponse(request, created.credential, proof);
          await addPasskey(choice!.wallet.id, created.record);
        } else {
          const used = await usePasskey(request, choice);
          message = await postResponse(request, used.credential, proof);
          if (choice?.passkey) await touchPasskey(choice.wallet.id, used.credentialId);
        }
        window.clearInterval(timer);
        const ownTab = window.history.length === 1 && !window.matchMedia("(display-mode: standalone)").matches;
        $card.innerHTML = `
          <h2>Done</h2>
          <p>${escapeHtml(message)}</p>
          <p class="muted-line">Go back to ${escapeHtml(request.app.origin)} to carry on.</p>
          <div class="actions">
            ${ownTab ? `<button id="passClose" class="primary" type="button">Close this tab</button>` : ""}
            <a class="${ownTab ? "" : "primary-link"}" href="#/wallets">Back to wallets</a>
          </div>`;
        $card.querySelector("#passClose")?.addEventListener("click", () => window.close());
      } catch (e) {
        $error.textContent = failureText(e);
        $error.hidden = false;
        $approve.disabled = Date.parse(request.expires) <= Date.now();
      }
    }
  }

  return () => {
    destroyed = true;
    window.clearInterval(timer);
  };
}

function failureText(e: unknown): string {
  if (e instanceof PassError) return e.message;
  const name = (e as { name?: string } | null)?.name;
  if (name === "NotAllowedError") return "Cancelled, or no matching passkey on this phone.";
  if (name === "InvalidStateError") return "This wallet already has a passkey for this site on this phone.";
  if (name === "SecurityError") return "This browser refused to use a passkey here.";
  return e instanceof Error ? e.message : "Something went wrong.";
}
