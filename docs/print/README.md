# Printable kit insert

Source file: **`kit-insert.md`** — ships with PiWalletSV hardware kits.

## Print settings

- **Paper:** US Letter or A4
- **Color:** Black & white is fine
- **Sides:** Double-sided recommended (fold or staple with device)
- **Margins:** Default or “narrow” if your printer crops footers

Before printing a production batch, fill in at the top of page 1:

- **Firmware version** (e.g. `0.1.0-r3`)
- **Image ID** (e.g. `c05daabb` for the first pi0 beta batch)

## Generate PDF (optional)

With [Pandoc](https://pandoc.org/) installed:

```bash
cd docs/print
pandoc kit-insert.md -o kit-insert.pdf \
  --pdf-engine=xelatex \
  -V geometry:margin=0.75in \
  -V fontsize=10pt
```

Without Pandoc: open `kit-insert.md` in any Markdown viewer, print to PDF
from the browser or VS Code preview.

## What ships

Include **one printed copy** inside the case or bag. Customers should
keep it with their seed backup paperwork.

Online equivalent: [User manual § Verify your SD card](../user-manual.md#verify-sd-card-on-arrival)

## Customisation

Edit `kit-insert.md` only — do not fork content into the web manual;
link to piwalletsv.com for details that change frequently.
