# Develop

This chapter is for contributors and people building compatible
implementations. If you only want to use the device, the
[User manual](user-manual.md) is the right starting point.

## 1. Repo layout

See the [Architecture](architecture.md#5-module-layout) chapter for
the full tree. The short version:

- **`piwallet/`** — Python offline core that runs on the Pi.
  Imports cleanly on Linux + macOS for development; the Pi-only
  bits (display, camera) live behind optional extras. USB vault
  backup/restore lives in `piwallet/backup/` (bundle format, mount
  socket daemon, bonnet flows in `piwallet/bonnet/usb_backup.py`).
- **`companion/`** — TypeScript + Vite PWA. Imports cleanly on
  Node 20+; runs in any modern browser. Uses
  [`vitest`](https://vitest.dev/) for tests.
- **`tests/`** — Python pytest suite and canonical fixtures.
  Cross-language fixtures live in `tests/fixtures/`.
- **`scripts/`** — utility scripts: bonnet bring-up demos, camera
  smoke test, envelope decoder dump.
- **`docs/`** — this site (mkdocs-material).
- **Root files** — `README.md`, `LICENSE`, `DISCLAIMER.md`,
  `SECURITY.md`, `GETTING_STARTED.md` (canonical sources, mirrored
  into the docs site via `pymdownx.snippets`).

## 2. Dev setup

```bash
git clone https://github.com/mohrt/PiWalletSV.git
cd PiWalletSV

# --- Python core ---------------------------------------------------------
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# --- Companion -----------------------------------------------------------
cd companion
npm install
cd ..

# --- Docs (optional) -----------------------------------------------------
pip install -r requirements-docs.txt
```

Python **3.11+** is required; 3.13 is the actively-tested target.
3.14 is not yet supported because a couple of transitive wheels
haven't shipped 3.14 builds at the time of writing.

The companion needs **Node 20+** for `CompressionStream` and
top-level `await`.

## 3. Running the test suites

```bash
# Python:
pytest                              # 150+ tests
pytest --cov=piwallet --cov-report=term-missing

# TypeScript:
cd companion
npm test                            # vitest (80+ tests)
npm run build                       # tsc --noEmit + vite build
```

Both suites should pass on a fresh checkout. If they don't, that's
a bug — file it.

Notable cross-language tests:

- `tests/test_address_fixture.py` pins
  `tests/fixtures/addresses_canonical.json` against the Python
  derivation chain.
- `companion/tests/derive.test.ts` does the same against the TS
  derivation chain. If both pass, the two halves agree on every
  P2PKH receive / change address for the canonical mnemonic.
- `tests/test_decoded_envelope_fixture.py` pins
  `tests/fixtures/proposal_01_decoded.json` against the live
  CBOR bytes via `scripts/dump_decoded_envelope.py`.
- `companion/tests/envelope.test.ts` decodes the
  Python-produced `proposal_01.cbor` and asserts every field
  matches the metadata file.

A change that alters the wire format will fail at least one of
these tests before it reaches review.

## 4. Regenerating fixtures

If you intentionally change a wire format (CBOR keys, PW1 framing,
derivation logic), regenerate the fixtures and commit the result:

```bash
# 1. Rebuild the canonical proposal envelope (also rewrites the
#    JSON metadata).
python -m tests.fixtures.generate_fixtures

# 2. Rebuild the structural dump that third-party decoders diff
#    against.
python scripts/dump_decoded_envelope.py \
    tests/fixtures/proposal_01.cbor \
    tests/fixtures/proposal_01_decoded.json

# 3. Re-run the full test matrix to make sure nothing else moved.
pytest && (cd companion && npm test)
```

If you've changed `addresses_canonical.json` (almost never — that
would mean changing the derivation chain), keep the canonical
mnemonic the same so external implementers continue to validate
against a fixed vector.

## 5. Decoding an envelope by hand

When debugging a wire-format question, the structural dump is the
quickest way to see what's inside a CBOR blob:

```bash
python scripts/dump_decoded_envelope.py /path/to/blob.cbor > /tmp/dump.json
less /tmp/dump.json
```

The output is the same shape used as the conformance reference in
`tests/fixtures/proposal_01_decoded.json` — each map entry, each
array index, each typed leaf, with byte lengths and small hex
samples. See [`docs/protocol/conformance.md`](protocol/conformance.md)
for the schema.

For a human-readable summary (addresses, amounts, fee, anchors):

```bash
piwallet decode /path/to/blob.cbor
```

The CLI prints a multi-line description based on the envelope kind.

## 6. Coding conventions

- **Python**: enforced by `ruff` with rules `E F W I N UP B S RUF`.
  Tests get `S` (the security warnings about asserts and hard-coded
  passwords in fixtures) ignored. Run `ruff check .` before pushing.
- **TypeScript**: the `companion/` package uses standard
  Vite + tsc strict mode. Lint with `npm run lint` if you've added
  the script; otherwise `tsc --noEmit` is the minimum CI gate.
- **Comments**: explain "why," not "what." Don't narrate code line
  by line. (See `.cursor/rules` for the project rule.)
- **Tests**: every new behavioural change needs a test that would
  have failed before the change.
- **Wire-format changes** require an updated fixture (§4) and a
  matching change in `docs/protocol/`.

## 7. Branch and PR conventions

- **`main`** is the integration branch. CI must pass before merge.
- **Feature branches** are `feat/<short-name>`. Bugfixes are
  `fix/<short-name>`. Documentation-only changes are `docs/...`.
- **Commits** use plain English in the subject line; details go in
  the body if useful. The reference commits in `git log` are good
  templates.
- **Pull requests** include:
    - A summary of the change in user-visible terms.
    - A "test plan" — the commands you ran to validate.
    - Any wire-format implications, called out explicitly.
- Sign-offs are not required; reviewers may request them for
  security-sensitive changes.

## 8. Release checklist (v0.x)

For each release tag:

1. Bump the version in `pyproject.toml` and
   `companion/package.json` to the same value.
2. Update [`docs/index.md`](index.md) "Project status" table if a
   phase has changed state.
3. Run both test suites on a clean checkout:
    ```bash
    pytest && (cd companion && npm test)
    ```
4. Build the companion bundle:
    ```bash
    cd companion && npm run build
    ```
    Confirm the bundle size hasn't regressed by more than ~10%
    without a good reason (current target: app chunk ≤ 110 KB
    gzipped; `@bsv/sdk` chunk ≤ 75 KB gzipped).
5. Build the docs site locally and skim for broken links:
    ```bash
    mkdocs build --strict
    ```
6. Tag the release: `git tag -s vX.Y.Z -m "vX.Y.Z"` and push.
7. Generate a release notes draft from the commit log since the
   previous tag.
8. **For v0.1 and later**: build the sealed SD image with
   [`deploy/provision-pi.sh`](https://github.com/mohrt/PiWalletSV/blob/main/deploy/provision-pi.sh),
   capture and sign
   per [`docs/includes/image-release-operator.md`](includes/image-release-operator.md),
   and attach artifacts to the GitHub Release. (Full `pi-gen` automation
   is tracked under `phase8-hardening`.)

## 9. Filing security issues

Don't open a public issue. See [Security](security.md) for the
preferred channel (GitHub private vulnerability reporting) and the
disclosure timeline. The summary: report → 90-day fix window →
coordinated disclosure.

## 10. Building docs locally

```bash
pip install -r requirements-docs.txt
mkdocs serve            # http://localhost:8000/
mkdocs build --strict   # builds into ./site/
```

`--strict` makes broken nav links and missing snippet targets fatal,
which is what CI does. The docs site uses
[mkdocs-material](https://squidfunk.github.io/mkdocs-material/) with
dark-mode toggle, search, and `pymdownx.snippets` to mirror the
root `DISCLAIMER.md` and `SECURITY.md` files without duplicating
content.

The deploy is driven by `.github/workflows/docs.yml`, which builds
on every push to `main` and publishes to GitHub Pages via the
`gh-pages` branch. Pull-request docs builds run the same workflow
in dry-run (no deploy) so reviewers can catch broken nav early.
