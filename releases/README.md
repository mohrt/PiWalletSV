# Firmware release artifacts

Signed SD-card images are published on
**[GitHub Releases](https://github.com/mohrt/PiWalletSV/releases)**, not in this
directory. [`releases.json`](releases.json) is optional machine-readable history
(docs link to it; the website does **not** republish version numbers or hashes).

**Filename pattern** (board slug + optional maturity):

`piwalletsv-{version}-{board}[-{maturity}].img.xz`

Examples: `piwalletsv-0.1.0-r3-pi0-beta.img.xz` (Zero / Zero W beta),
`piwalletsv-1.0.0-pi0.img.xz` (GA). Board slugs: `pi0`, `pi02w`, `pi2`, `pi4`.

Operator workflow: [`docs/includes/image-release-operator.md`](../docs/includes/image-release-operator.md).
