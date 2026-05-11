/**
 * Placeholder for the multipart-QR scan page. The webcam decoder
 * (getUserMedia + jsqr + MultipartAssembler) is wired up in the
 * follow-up step.
 */
export function mountScanPlaceholder(root: HTMLElement): void {
  root.innerHTML = `
    <main class="page">
      <header class="page-header">
        <h1>Scan multipart QR<span class="brand"> · PiWallet companion</span></h1>
        <nav>
          <a href="#/encode">Encode</a>
          <a href="#/scan" class="active">Scan</a>
        </nav>
      </header>

      <section class="placeholder">
        <p>Webcam decoder lands in the next step.</p>
        <p>It will use <code>getUserMedia</code> + <code>jsqr</code> +
        <code>MultipartAssembler</code>, mirroring
        <code>piwallet.qr.camera_scan</code> on the Pi.</p>
      </section>
    </main>
  `;
}
