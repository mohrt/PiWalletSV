# CLI reference

`piwallet` is the single command-line entry point for everything the
signer can do. It's a [Click](https://click.palletsprojects.com)
application with subcommand groups; `piwallet --help` lists them all
and `piwallet <group> --help` drills in.

This page is a focused reference, not a tutorial. For end-to-end
flows see the [User manual](user-manual.md); for installation see
[Build & deploy](build.md).

## Conventions

- The default `--vault-path` everywhere is
  `~/.piwallet-dev/vault.bin`. Set it explicitly in a script.
- Anything that needs the PIN reads it interactively (`--no-input`
  is not supported, by design).
- Binary blobs go to **stdout** by default and to a file with `-o`.
  Stderr carries human-readable progress and errors.
- Exit codes follow the Unix convention: `0` success, `1` user
  error or missing precondition, `2` wrong PIN, `3` vault wiped,
  `130` keyboard interrupt.

## Top-level groups

```text
piwallet
├── mnemonic    create / validate BIP39 phrases
├── vault       open / init / list / add / export-xpub
├── xpub-export build a paired-pubkey envelope (CBOR + gzip)
├── decode      pretty-print any envelope blob
├── qr          multipart-QR transport (join, split, scan-camera)
├── sign        verify + sign an unsigned_proposal
├── firstboot   manage the legal disclaimer state
└── bonnet      launch the full on-device UI
```

## `piwallet mnemonic`

BIP39 phrase creation and validation. Stateless — no vault required.

### `mnemonic new`

Generate a fresh BIP39 mnemonic from `os.urandom`.

```bash
piwallet mnemonic new                  # 12 words (default)
piwallet mnemonic new --words 24       # 24 words
```

Prints the phrase to stdout, one line, space-separated. **Save it
offline immediately** — the CLI does not keep a copy.

### `mnemonic validate`

Read a phrase from stdin and verify it's valid BIP39 (correct words
*and* checksum):

```bash
echo "various crime ... pole" | piwallet mnemonic validate
```

Exits `0` on success, `1` on any failure (unknown word, wrong word
count, bad checksum). Stderr explains why.

## `piwallet vault`

Manage the encrypted vault. Every subcommand accepts `--vault-path`
on the *group*, e.g.:

```bash
piwallet vault --vault-path /path/vault.bin <subcommand>
```

### `vault init`

Create a new empty vault. Interactive: prompts for PIN twice. Refuses
if the vault file already exists; see [Operate § Wiping](operate.md#wiping-the-vault)
for how to start over.

### `vault add --label <name>`

Add a wallet from a mnemonic on stdin:

```bash
piwallet mnemonic new \
  | piwallet vault --vault-path ~/.piwallet-dev/vault.bin add --label "Daily"
```

Or restore from an existing phrase:

```bash
echo "various crime ... pole" \
  | piwallet vault --vault-path ~/.piwallet-dev/vault.bin add --label "Restored"
```

Prompts for the PIN, derives the BIP44 account xprv, encrypts it,
and persists the wallet record.

### `vault list`

Print one line per wallet (`<id> <label>`). **Does not require the
PIN** — the public metadata is unencrypted. Safe to script.

### `vault export-xpub <wallet-id>`

Print the BIP44 account xpub string. Prompts for the PIN. Useful
for cross-checking that the companion's xpub matches what the signer
holds.

## `piwallet xpub-export`

Build the canonical `xpub_export` envelope (CBOR + gzip) used during
companion pairing.

```bash
piwallet xpub-export --wallet-id <id> -o /tmp/xpub.bin
```

Prompts for the PIN. Without `-o` the raw bytes go to stdout (binary).
Pipe through `qr split` to drive a terminal QR loop without the
bonnet display:

```bash
piwallet xpub-export --wallet-id <id> | piwallet qr split | qrencode -t UTF8
```

`--label <override>` overrides the stored label in the emitted
envelope without modifying the vault.

## `piwallet decode <blob_path>`

Decode any envelope blob (`xpub_export`, `unsigned_proposal`,
`signed_tx`) and print a human-readable summary — addresses, amounts,
fee, anchors. Useful for debugging fixtures or scanned blobs.

```bash
piwallet decode /tmp/proposal_01.cbor
```

Pairs well with `qr scan-camera --output /tmp/blob.bin && piwallet
decode /tmp/blob.bin`.

## `piwallet qr`

Multipart-QR transport (the PW1 framing format documented in
[Protocol § QR transport](protocol/qr-transport.md)).

### `qr join`

Read PW1 lines from stdin (one per line) and emit the assembled
binary blob. Mirrors the companion's decoder.

```bash
cat /tmp/frames.txt | piwallet qr join -o /tmp/proposal.cbor
```

### `qr split`

Inverse of `qr join`. Read raw bytes and emit PW1 lines:

```bash
piwallet xpub-export --wallet-id <id> | piwallet qr split
```

`--chunk-chars <N>` controls the maximum chars per QR (default tuned
for the bonnet panel). Output is one line per frame, ready to feed a
terminal QR loop.

### `qr scan-camera`

Pi-only. Capture frames from the Camera Module 3 until a full PW1
payload is assembled.

```bash
piwallet qr scan-camera -o /tmp/blob.bin
```

Common options:

- `--size 1280x960` — capture resolution.
- `--interval 0.35` — seconds between frames.
- `--af continuous` — autofocus mode.
- `--show / --no-show` — print envelope summary to stderr on
  completion (default on).

`Ctrl-C` aborts with exit `130`. Without `-o` and `--show`, the raw
blob still goes to stdout.

## `piwallet sign <proposal_path>`

The core offline operation. Verifies an `unsigned_proposal` envelope
end-to-end, signs the transaction, emits a `signed_tx` envelope.

```bash
piwallet sign /tmp/proposal.cbor --wallet-id <id> -o /tmp/signed.cbor
```

What it does, in order:

1. Decodes the envelope.
2. Verifies BEEF + Merkle paths against header anchors.
3. Re-derives every claimed input address and confirms script match.
4. Re-derives the change address and confirms script match.
5. Asserts value conservation and fee within `--max-fee-rate-satskb`
   (default 10 sats/byte; reject anything fatter).
6. Prompts for the PIN, signs, emits `signed_tx`.

Without `-o`, prints the signed envelope as **hex** to stdout (so
you can pipe it through `qr split` for an animated QR display).
Stderr carries a one-line summary.

Exit codes:

- `0` — signed.
- `1` — verification failed; stderr names the failing rule.
- `2` — wrong PIN.
- `3` — vault wiped on this attempt.

## `piwallet firstboot`

Manage the disclaimer-acceptance state file (`terms.json`).

### `firstboot status`

Print the saved acceptance state. Exits `0` if the *current* terms
version is accepted, `1` otherwise.

### `firstboot run`

Run the on-device disclaimer screen (or `--display headless` for a
test/CI path). Hold the bonnet's A button to accept; long-B to bail.

```bash
piwallet firstboot run                           # interactive on bonnet
piwallet firstboot run --display headless        # CI/test acceptance
piwallet firstboot run --force                   # re-run even if accepted
```

## `piwallet bonnet`

Launch the full on-device UI. The systemd unit installs this as
`ExecStart=`; you'll only run it directly during install or
debugging.

```bash
piwallet bonnet                                              # uses defaults
piwallet bonnet --vault-path /home/pi/.piwallet-dev/vault.bin
piwallet bonnet --display headless --input fake              # for screenshots
```

Options worth knowing:

- `--display {auto,st7789,headless}` — pick a display backend.
  `headless` writes nothing; useful with `--input fake` for tests.
- `--input {auto,bonnet,fake}` — pick an input backend. `fake` reads
  from a programmatic queue (used by the test suite).
- `--fps <n>` — bonnet main-loop target. Default 30 fps. Lower this
  to 15 if you want longer SD-card lifetime on a quiet kiosk.

Exit codes are documented under [Operate § Exit codes](operate.md#exit-codes).

## Environment variables

| Variable | Effect |
|----------|--------|
| `PIWALLET_LOG_LEVEL` | Override Python logger level (`DEBUG`/`INFO`/`WARNING`/`ERROR`). |
| `LIBCAMERA_LOG_LEVELS` | libcamera severity (`*:WARN` is the default). |
| `PICAMERA2_LOG_LEVEL` | Picamera2 console verbosity (numeric). |

The bonnet flow tightens these to safe defaults at process entry; set
them explicitly to override.

## Examples

### Pair a fresh wallet (CLI-only)

```bash
piwallet vault --vault-path ~/v.bin init
piwallet mnemonic new \
  | piwallet vault --vault-path ~/v.bin add --label "Daily"
piwallet vault --vault-path ~/v.bin list
# d2c1...    Daily

piwallet xpub-export --vault-path ~/v.bin --wallet-id d2c1... \
  | piwallet qr split \
  | qrencode -t UTF8     # animated QR in your terminal
```

### Sign a proposal end-to-end without the bonnet

```bash
# (Companion built the proposal; you scp'd it across.)
piwallet sign /tmp/proposal.cbor --wallet-id d2c1... -o /tmp/signed.cbor
piwallet decode /tmp/signed.cbor
piwallet qr split < /tmp/signed.cbor | qrencode -t UTF8
```

### Quick fixture sanity check

```bash
python -m tests.fixtures.generate_fixtures
piwallet decode tests/fixtures/proposal_01.cbor
```
