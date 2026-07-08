# Kit insert (print)

Ship **one printed copy** of this two-page insert inside every full kit.
Customers should keep it with their seed backup paperwork.

[Open printable insert (full page)](kit-insert.html){ .md-button .md-button--primary target=_blank }
[Print from this page](#print){ .md-button }

!!! tip "Print settings"
    - **Paper:** US Letter (8.5 × 11 in)
    - **Sides:** Double-sided (flip on long edge)
    - **Margins:** None or Minimum
    - **Background graphics:** On (optional gold/green accent bar on page 1)

    Before a production batch, update **Firmware** and **Image ID** on page 1
    in [`kit-insert.html`](https://github.com/mohrt/PiWalletSV/blob/main/docs/print/kit-insert.html).

Extended checklist (verify SD, upgrade path): [kit-insert.md](kit-insert.md).

<div class="kit-insert-preview" id="print">
  <iframe
    src="kit-insert.html"
    title="PiWalletSV kit insert — 2 pages"
    loading="lazy"
  ></iframe>
</div>

<script>
(function () {
  const frame = document.querySelector(".kit-insert-preview iframe");
  if (!frame) return;
  document.querySelectorAll('a[href="#print"]').forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      if (frame.contentWindow) {
        frame.contentWindow.focus();
        frame.contentWindow.print();
      }
    });
  });
})();
</script>
