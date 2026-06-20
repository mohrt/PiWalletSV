# Firmware release artifacts

Signed SD-card images are published on **GitHub Releases**, not in this
directory. See [`releases.json`](releases.json) for canonical download URLs
and metadata consumed by docs.

**Filename pattern** (board slug + optional maturity):

`piwalletsv-{version}-{board}[-{maturity}].img.xz`

Examples: `piwalletsv-0.1.0-r3-pi0-beta.img.xz` (Zero / Zero W beta),
`piwalletsv-1.0.0-pi0.img.xz` (GA). Board slugs: `pi0`, `pi02w`, `pi2`, `pi4`.

Operator workflow: [`docs/includes/image-release-operator.md`](../docs/includes/image-release-operator.md).
