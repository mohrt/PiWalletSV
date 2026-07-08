# Printable kit insert

Ship **one printed copy** inside every PiWalletSV kit (case or bag).
Customers should keep it with their seed backup paperwork.

## Files

| File | Use |
|------|-----|
| **`kit-insert.html`** | **Primary — branded 2-page insert** (welcome + quick start). Open in a browser → Print → PDF or direct to printer. |
| **`kit-insert.md`** | Extended text reference (verify SD, upgrade path, cut-out card). Use when you need the long-form checklist or Pandoc PDF. |

## Print settings (HTML — recommended)

1. Open `kit-insert.html` in Chrome or Safari (double-click, or drag into the browser).
2. **File → Print** (or `Cmd+P`).
3. **Paper:** US Letter (8.5 × 11 in).
4. **Margins:** None or Minimum (the layout includes its own padding).
5. **Background graphics:** Optional — page 1 is white; a thin gold/green accent bar prints at the top.
6. **Sides:** **Two-sided** (flip on long edge) — page 1 is the welcome cover, page 2 is quick reference.
7. **Color or B&W:** Both work; color adds subtle accent tints on pills and callouts.

Before a production batch, edit the **Firmware** and **Image ID** fields at the
bottom of page 1 in `kit-insert.html` (and the matching lines in `kit-insert.md`).

## Generate PDF from Markdown (optional)

With [Pandoc](https://pandoc.org/) installed:

```bash
cd docs/print
pandoc kit-insert.md -o kit-insert-extended.pdf \
  --pdf-engine=xelatex \
  -V geometry:margin=0.75in \
  -V fontsize=10pt
```

## Online

- **[Kit insert (print)](index.md)** — preview and print the 2-page insert in your browser.
- Direct link (no site chrome): [`kit-insert.html`](kit-insert.html)
- Extended checklist: [`kit-insert.md`](kit-insert.md)
- User manual: [Verify your SD card](../user-manual.md#verify-sd-card-on-arrival)

## Customisation

Edit `kit-insert.html` for visual/branding changes and the short insert.
Edit `kit-insert.md` for extended operational text — do not fork long content
into the web manual; link to piwalletsv.com for details that change frequently.
