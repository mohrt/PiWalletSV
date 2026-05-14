/**
 * Security briefing page (`#/security`).
 *
 * Plain-language operator-facing explanation of the trust model. Rendered
 * as a static, link-rich page so a user can land here from the main nav
 * or from the first-load disclaimer modal and quickly reason about three
 * things:
 *
 *  1. *This website is static.* Nothing about your wallet is sent off
 *     your device when you load this page. The companion stores public
 *     metadata (xpubs, fingerprints, UTXO snapshots) in your browser's
 *     IndexedDB and never reports them anywhere.
 *  2. *The Pi's PIN protects an encrypted vault, not a vault made of
 *     magic.* The vault is AES-GCM encrypted with a scrypt-derived key.
 *     Long PINs matter; short ones do not. Six wrong attempts in a row
 *     wipe the vault as a circuit breaker.
 *  3. *Treat the device like the seed phrase itself.* Keep it in a
 *     vault, not a desk drawer. PiWalletSV is designed for cold
 *     storage — long-term, infrequent signing — not for daily
 *     transactions.
 *
 * The content lives in :data:`SECURITY_SECTIONS` so unit tests can
 * assert the three sections stay present without needing a DOM.
 */

export interface SecuritySection {
  /** Stable HTML id used as a deep-link anchor (and asserted by tests). */
  id: string;
  /** Short, plain-English heading for the section. */
  heading: string;
  /** Bullet body, in HTML (small `<code>` / `<strong>` runs are fine). */
  bullets: string[];
}

export const SECURITY_SECTIONS: readonly SecuritySection[] = [
  {
    id: "static-companion",
    heading: "This website is static",
    bullets: [
      "There is <strong>no server</strong> behind this page. The site is " +
        "a stack of HTML, CSS and JavaScript files. Once your browser has " +
        "downloaded them, everything runs locally.",
      "Nothing about your wallet is sent back to the site. No login, no " +
        "telemetry, no analytics, no \"sync\" anywhere. Paired-wallet " +
        "metadata (xpub, fingerprint, label, derivation path, cached UTXO " +
        "snapshots) lives in your browser's <code>IndexedDB</code> and " +
        "stays there.",
      "The only outbound calls the companion makes are to " +
        "<a href=\"https://whatsonchain.com/\" target=\"_blank\" " +
        "rel=\"noopener noreferrer\">WhatsOnChain</a> for UTXO discovery, " +
        "Merkle proofs, and broadcasting signed transactions. Those are " +
        "public-blockchain reads / writes — they do not leak your seed.",
      "Losing this browser profile is <em>not</em> a loss of funds. The " +
        "companion only holds <strong>public</strong> material; spending " +
        "still requires the Pi (and ultimately your seed phrase).",
    ],
  },
  {
    id: "pin-strength",
    heading: "Your PIN protects an encrypted vault — not magic",
    bullets: [
      "The Pi's vault file (<code>~/.piwallet/vault.bin</code>) is " +
        "AES-GCM encrypted. The key is derived from your PIN with " +
        "<a href=\"https://en.wikipedia.org/wiki/Scrypt\" target=\"_blank\" " +
        "rel=\"noopener noreferrer\">scrypt</a>, which is intentionally " +
        "slow and memory-hard. That makes brute-forcing a long PIN very " +
        "expensive — but it is <strong>not impossible</strong>.",
      "<strong>PIN length matters.</strong> A 6-digit PIN has only a " +
        "million combinations; a determined attacker with the vault file " +
        "and a GPU farm can chew through that. Use a long PIN — ideally " +
        "12+ digits — if you treat your seed as a high-value secret.",
      "Six wrong PIN attempts in a row <strong>wipe the vault</strong> " +
        "from the Pi. This is a circuit breaker, not a guarantee: if " +
        "someone copies <code>vault.bin</code> off the device they can " +
        "retry forever offline. Your seed phrase backup is what protects " +
        "you in that scenario.",
      "The seed itself is <strong>never persisted</strong>. It only " +
        "exists in transient memory long enough to derive the master xprv " +
        "and is then zeroed.",
    ],
  },
  {
    id: "physical-security",
    heading: "Treat the device like the seed phrase itself",
    bullets: [
      "<strong>Keep the Pi in a vault, not a desk drawer.</strong> " +
        "Anyone with extended physical access can copy the encrypted " +
        "vault file and attack it offline at their leisure. There is no " +
        "secure element, no tamper mesh, no anti-rollback fuse. It is a " +
        "Raspberry Pi.",
      "<strong>PiWalletSV is for cold storage, not daily transactions.</strong> " +
        "It is designed for long-term, infrequent signing of larger " +
        "amounts. If you need to move funds every day, use a hot wallet " +
        "on a phone or laptop and keep PiWalletSV for the savings stack.",
      "Your <strong>seed phrase</strong> is the source of truth, not the " +
        "Pi. Back it up on something durable (steel plates, multiple " +
        "geographic locations) and store it the way you would store the " +
        "deed to a house. Losing the Pi is annoying; losing the seed is " +
        "permanent.",
      "Air-gap discipline still applies: don't plug the Pi into the " +
        "internet, don't type the seed into anything online, and don't " +
        "let cameras / screen-recorders see the disclaimer-revealed phrase " +
        "during initial setup or recovery.",
    ],
  },
];

/**
 * Build the inner HTML for the security briefing.
 *
 * Exported so tests can assert the rendered HTML contains the section
 * anchors and key copy without spinning up a DOM.
 */
export function renderSecurityHtml(): string {
  const sections = SECURITY_SECTIONS.map((s) => {
    const items = s.bullets.map((b) => `        <li>${b}</li>`).join("\n");
    return `
      <article class="card security-section" id="${s.id}">
        <h2>${s.heading}</h2>
        <ul class="security-bullets">
${items}
        </ul>
      </article>
    `.trim();
  }).join("\n\n      ");
  return sections;
}

export function mountSecurityPage(root: HTMLElement): () => void {
  root.innerHTML = `
    <main class="page">
      <header class="page-header">
        <h1>Security briefing<span class="brand"> · PiWalletSV companion</span></h1>
        <nav>
          <a href="#/encode">Encode</a>
          <a href="#/scan">Scan</a>
          <a href="#/loop">Loop</a>
          <a href="#/wallets">Wallets</a>
          <a href="#/security" class="active">Security</a>
        </nav>
      </header>

      <section class="card">
        <p class="muted-line" style="margin-bottom: 0;">
          Plain-language summary of the PiWalletSV trust model. The full
          policy lives in
          <a href="https://github.com/" target="_blank" rel="noopener noreferrer">
            <code>SECURITY.md</code>
          </a>
          and the
          <a href="https://github.com/" target="_blank" rel="noopener noreferrer">
            project docs
          </a>.
        </p>
      </section>

      ${renderSecurityHtml()}

      <section class="card">
        <p class="muted-line" style="margin-bottom: 0;">
          Found a security-relevant bug? Please report it privately first —
          see
          <a href="https://github.com/" target="_blank" rel="noopener noreferrer">
            <code>SECURITY.md</code>
          </a>
          for the disclosure process.
        </p>
      </section>
    </main>
  `;
  return () => {
    /* nothing to tear down */
  };
}
