# Kit insert (print)

Ship **one printed copy** of the kit insert inside every full kit, and
offer the seed backup sheet for offline BIP39 records. Customers should
keep both with their seed backup paperwork.

!!! tip "Print settings"
    - **Paper:** US Letter (8.5 × 11 in)
    - **Sides:** Kit insert — double-sided (flip on long edge). Seed sheet — single-sided is fine.
    - **Margins:** None or Minimum
    - **Background graphics:** On (optional gold/green accent bars)

    Before a production batch, update **Firmware** and **Image ID** on page 1
    in [`kit-insert.html`](https://github.com/mohrt/PiWalletSV/blob/main/docs/print/kit-insert.html).

Extended checklist (verify SD, upgrade path): [kit-insert.md](kit-insert.md).

## Seed phrase backup sheet

One US Letter page with **two cuttable cards**: one **12-word** (default)
and one **24-word**. Print, cut along the guide, store separately from the device.

[Open seed backup sheet](seed-backup.html){ .md-button .md-button--primary target=_blank }

<div class="kit-insert-preview">
  <iframe
    src="/print/seed-backup.html?embed=1"
    title="PiWalletSV seed phrase backup sheet"
    loading="lazy"
  ></iframe>
</div>

## Kit insert

Two-page welcome + quick-start insert for full kits.

[Open kit insert](kit-insert.html){ .md-button .md-button--primary target=_blank }

<div class="kit-insert-preview">
  <iframe
    src="/print/kit-insert.html?embed=1"
    title="PiWalletSV kit insert — 2 pages"
    loading="lazy"
  ></iframe>
</div>

<script>
(function () {
  // Scale each preview so the full US-Letter sheet(s) fit the content
  // column. Embed mode strips chrome/margins; we measure .sheet/.page
  // boxes so the iframe viewport matches the paper, then scale.
  function contentSize(doc) {
    const nodes = doc.querySelectorAll(".sheet, .page");
    if (!nodes.length) {
      return {
        w: Math.max(doc.body.scrollWidth, 816),
        h: Math.max(doc.body.scrollHeight, 1),
      };
    }
    let maxRight = 0;
    let maxBottom = 0;
    nodes.forEach(function (el) {
      maxRight = Math.max(maxRight, el.offsetLeft + el.offsetWidth);
      maxBottom = Math.max(maxBottom, el.offsetTop + el.offsetHeight);
    });
    return {
      w: Math.ceil(maxRight) || 816,
      h: Math.ceil(maxBottom) || 1056,
    };
  }

  function fitFrame(frame) {
    const wrap = frame.parentElement;
    const doc = frame.contentDocument;
    if (!wrap || !doc || !doc.body) return;
    // Ensure embed class is present even if the child script raced.
    doc.documentElement.classList.add("embed");
    // Measure unscaled paper size (clear any prior zoom).
    doc.documentElement.style.zoom = "";
    const size = contentSize(doc);
    const style = getComputedStyle(wrap);
    const padX = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    const avail = Math.max(wrap.clientWidth - padX, 1);
    const scale = Math.min(avail / size.w, 1);
    const scaledW = size.w * scale;
    const scaledH = size.h * scale;

    frame.style.width = size.w + "px";
    frame.style.height = size.h + "px";
    frame.style.maxWidth = "none";
    frame.style.maxHeight = "none";
    frame.style.transform = "scale(" + scale + ")";
    frame.style.transformOrigin = "top left";
    // Center in the available column.
    frame.style.marginLeft = Math.max((avail - scaledW) / 2, 0) + "px";
    // Collapse the layout box to the scaled visual height so the
    // wrapper does not clip the bottom (transform alone does not
    // shrink layout).
    frame.style.marginBottom = (scaledH - size.h) + "px";
    // Same for width: collapse unused horizontal layout after scale.
    frame.style.marginRight = (scaledW - size.w) + "px";
    wrap.style.height = scaledH
      + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + "px";
    wrap.style.overflow = "hidden";
  }

  const frames = document.querySelectorAll(".kit-insert-preview iframe");
  frames.forEach(function (frame) {
    frame.addEventListener("load", function () {
      fitFrame(frame);
      setTimeout(function () { fitFrame(frame); }, 300);
      setTimeout(function () { fitFrame(frame); }, 1000);
    });
    if (frame.contentDocument &&
        frame.contentDocument.readyState === "complete") {
      fitFrame(frame);
    }
  });
  window.addEventListener("resize", function () {
    frames.forEach(fitFrame);
  });
})();
</script>
