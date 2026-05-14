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
- **Stdout encoding:** the rule is *hex when a human is in the loop,
  raw bytes when a program is in the loop*. `piwallet sign` (the
  human-touchable copy-paste-over-SSH endpoint) emits hex on stdout
  by default; on a TTY the line is additionally prefixed
  `signed_tx: ` so it lines up visually with the `verified:` /
  `txid:` summary on stderr. Pipelines (non-TTY stdout) get bare hex
  with no prefix. The plumbing endpoints — `xpub-export`, `qr join`,
  `qr scan-camera` — emit raw bytes on stdout by default because
  their natural consumer is another `piwallet` command (`decode`,
  `qr show`) that expects the canonical envelope format.
- All commands that produce a binary blob accept `-o <file>` to
  write the **raw envelope bytes** to disk (canonical wire format,
  for tool-to-tool plumbing). Stderr carries human-readable
  progress and errors regardless.
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

Manage the encrypted vault. The group itself takes one option that
applies to every subcommand:

| Group option | Type | Default | Required | Notes |
|---|---|---|---|---|
| `--vault-path` | path | `~/.piwallet-dev/vault.bin` | no | Path to the encrypted vault file. **Specified on the *group*, not the subcommand**: `piwallet vault --vault-path X <sub>`. Parent directory is created if missing. |

Every wallet subcommand inherits this `--vault-path`; the examples
below show it explicitly so they're copy-paste safe.

---

### `vault init`

Create a new empty vault file. PIN-protected from the moment it
exists.

```bash
piwallet vault --vault-path ~/v.bin init
```

| Option | Type | Default | Required | Notes |
|---|---|---|---|---|
| *(none)* | — | — | — | Inherits `--vault-path` from the `vault` group. |

**Interactive prompts:** PIN entered **twice** (the second is a
confirmation). Minimum length is 6 digits — shorter PINs are rejected
before the vault is created.

**Effects:**
- Generates a fresh 16-byte scrypt salt + AES-GCM key wrap structure.
- Writes `<vault-path>` (creates parent dir if missing).

**Exit codes:**
- `0` — vault created.
- `1` — vault already exists at `<vault-path>` (refuses to overwrite;
  see [Operate § Wiping](operate.md#wiping-the-vault) to start over).

**Stdout:** `created <path>` confirmation line.

---

### `vault add`

Add a wallet from a BIP39 mnemonic supplied on stdin.

```bash
piwallet mnemonic new \
  | piwallet vault --vault-path ~/v.bin add --label "Daily"

# Or restore from an existing phrase:
echo "various crime ... pole" \
  | piwallet vault --vault-path ~/v.bin add --label "Restored"

# Testnet wallet:
piwallet mnemonic new \
  | piwallet vault --vault-path ~/v.bin add --label "Faucet" --network test
```

| Option | Type | Default | Required | Notes |
|---|---|---|---|---|
| `--label` | text | *(none)* | **yes** | Human-readable wallet label. Stored in the vault and stamped into the `xpub_export` envelope when pairing. |
| `--network` | `main` \| `test` | `main` | no | Picks BSV mainnet vs TBSV testnet. Affects the base58check prefix for receive addresses *and* the WoC base URL the companion uses to fetch balances / broadcast. **Does NOT change the key material** — the same mnemonic restores the same xprv on either network; the network is purely a presentation/routing flag. Case-insensitive on the value (`Main`, `TEST` etc. accepted). |

**Stdin:** the BIP39 mnemonic phrase (whitespace-separated words,
trailing newline tolerated). Word count is auto-detected — 12 / 15 /
18 / 21 / 24 are all accepted. Words must be from the official
BIP39 English wordlist *and* the checksum must verify; bad checksums
are rejected before the vault is touched.

**Interactive prompts:** PIN once (no confirmation here — the vault
is already initialised and any wrong PIN counts toward the 6-strike
wipe).

**Effects:**
- Re-derives the BIP44 account xprv from the phrase.
- Encrypts the xprv under the vault DEK (which itself is wrapped
  under scrypt(PIN, salt)).
- Persists the new wallet record (id, fingerprint, label, network,
  derivation path, word count, creation timestamp).

**Stdout:** one line on success — `added wallet '<label>' id=<uuid>
fp=<8 hex chars>`. No PIN, no key material is ever printed.

**Exit codes:**
- `0` — wallet added.
- `1` — vault not initialised, mnemonic invalid (unknown word /
  bad checksum / wrong word count), `--label` missing, or any
  other vault error. Stderr carries the reason.
- `2` — wrong PIN (attempt counter incremented; remaining attempts
  printed to stderr).
- `3` — vault wiped on this attempt (6th consecutive wrong PIN).

---

### `vault list`

Print one tab-separated line per wallet. **Does NOT require the
PIN** — the metadata is stored unencrypted because it has no
spend-relevant secrets and the bonnet wallet-list screen has to
read it before the user types a PIN.

```bash
piwallet vault --vault-path ~/v.bin list
```

| Option | Type | Default | Required | Notes |
|---|---|---|---|---|
| *(none)* | — | — | — | Inherits `--vault-path`. |

**Output format** — tab-separated, one row per wallet, in the order
they were added:

```text
<id>\t<fp>\t<label>\t<hd_path>\t<network>\t<words>\t<created_at>
```

Where:

- `<id>` — wallet UUID (36 chars).
- `<fp>` — BIP32 fingerprint, 4 bytes hex (8 chars).
- `<label>` — human label as supplied to `vault add` / `rename`.
- `<hd_path>` — derivation path, e.g. `m/44'/236'/0'`.
- `<network>` — rendered as **`mainnet`** or **`TESTNET`** (caps for
  emphasis so a testnet wallet can't be missed in a mixed-network
  listing).
- `<words>` — `12 words`, `24 words`, etc.
- `<created_at>` — ISO 8601 timestamp.

**Exit codes:** `0` always, even when no vault exists (prints
`no vault at <path>` and exits clean — making this safe to use as a
"does it exist?" probe in shell scripts).

**Scripting tip:** parse with `cut -f 1` for ids, `awk '$5=="TESTNET"'`
to filter testnet wallets, etc.

---

### `vault export-xpub`

Print the BIP44 account xpub for a single wallet. Useful for cross-
checking the companion's stored xpub against what the signer holds,
or for piping into another tool that wants the raw xpub string.

```bash
piwallet vault --vault-path ~/v.bin export-xpub <wallet-id>
```

| Argument | Type | Required | Notes |
|---|---|---|---|
| `wallet_id` | text (positional) | **yes** | UUID of the wallet (from `vault list`). Mismatched ids exit `1`. |

| Option | Type | Default | Required | Notes |
|---|---|---|---|---|
| *(none)* | — | — | — | Inherits `--vault-path`. |

**Interactive prompts:** PIN once.

**Stdout:** the xpub string on a single line, no trailing whitespace.
Nothing else is written there — safe to capture into a shell
variable: `xpub=$(echo $PIN | piwallet vault ... export-xpub <id>)`.

**Exit codes:**
- `0` — xpub printed.
- `1` — wallet id not found.
- `2` — wrong PIN.
- `3` — vault wiped.

> **Building a paired-wallet envelope?** Use the top-level
> `piwallet xpub-export` command instead — it wraps the xpub in the
> versioned `xpub_export` CBOR envelope the companion expects (see
> below). `vault export-xpub` is the raw-string variant for ad-hoc
> debugging.

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

## `piwallet sign`

The core offline operation. Verifies an `unsigned_proposal` envelope
end-to-end, signs the transaction, emits a `signed_tx` envelope.
Accepts the proposal as either a file (canonical) or hex (the SSH
copy-paste bridge — see below).

```bash
# File-based:
piwallet sign /tmp/proposal.cbor --wallet-id <id> -o /tmp/signed.cbor

# Hex-on-stdin (paste over SSH from the companion's wallet-detail card):
piwallet sign --hex - --wallet-id <id> <<'EOF'
8a07b3f1...
EOF

# Hex inline:
piwallet sign --hex 8a07b3f1... --wallet-id <id>
```

| Argument | Type | Required | Notes |
|---|---|---|---|
| `proposal_path` | path (positional) | conditional | Read the unsigned proposal from this file. **Mutually exclusive with `--hex`** — provide exactly one of the two. |

| Option | Type | Default | Required | Notes |
|---|---|---|---|---|
| `--hex` | text | *(none)* | conditional | Read the proposal as hex instead of from a file. Use `--hex -` to read hex from stdin (the recommended SSH-paste form — handles arbitrarily long blobs without quoting headaches). Whitespace inside the hex (newlines from a wrapped paste, tabs, spaces) is stripped before decoding. Mutually exclusive with `proposal_path`. |
| `--vault-path` | path | `~/.piwallet-dev/vault.bin` | no | Path to the vault. *(Note: this is a per-command option here, not the group-level option from `piwallet vault`. They have the same default but live at different scopes.)* |
| `--wallet-id` | text | *(none)* | **yes** | UUID of the wallet to sign with. The wallet's xpub fingerprint must match the proposal's `wallet_fp`; mismatches exit `1` with `FINGERPRINT MISMATCH` on stderr. |
| `-o`, `--output` | path | *(none)* | no | Write the **raw signed_tx envelope bytes** to this file. When omitted, the envelope is printed as hex on stdout (terminal-safe; the canonical form for the SSH-paste workflow). |
| `--max-fee-rate-satskb` | integer | `10000` | no | Reject proposals whose `feeRate` exceeds this cap (sats per kB). Defaults to 10 sat/byte — a hard ceiling against rogue companions trying to drain a wallet via an inflated fee. Lower it for paranoid setups; raise only if you've verified the fee in the on-screen summary. |

What it does, in order:

1. Reads the input (file or hex).
2. Decodes the envelope; refuses anything that isn't an
   `unsigned_proposal`.
3. Prompts for the PIN.
4. Confirms `--wallet-id`'s xpub fingerprint matches
   `proposal.wallet_fp`.
5. Verifies BEEF + Merkle paths against header anchors.
6. Re-derives every claimed input address and confirms script match.
7. Re-derives the change address and confirms script match.
8. Asserts value conservation and fee within
   `--max-fee-rate-satskb`.
9. Signs all inputs, emits the `signed_tx` envelope.

**Stdout (no `-o`):** the encoded `signed_tx` envelope as hex. Two
shapes depending on whether stdout is attached to a terminal:

- *Interactive (TTY):* the hex line is prefixed `signed_tx: ` so it
  visually parallels the `verified:` / `txid:` summary lines on
  stderr. This makes it unambiguous which line to copy when scrolling
  back through an SSH session — the previous bare-hex shape made the
  txid line and the hex blob run together visually. The companion's
  "Paste signed_tx hex" textarea on `#/scan` strips this prefix
  automatically and will also tolerate pasting all three summary
  lines at once.
- *Pipeline (non-TTY, e.g. `… | xclip`, `… > tx.hex`):* bare hex with
  no prefix, so machine consumers don't have to strip a label.

Stderr always carries the human-readable summary (`verified: …`,
`txid: …`, plus `wrote signed envelope to <path>` when `-o` is
used).

**Stdout (with `-o`):** nothing on stdout; raw bytes go to the file.
Stderr says `wrote signed envelope to <path>`.

Exit codes:

- `0` — signed.
- `1` — input invalid (bad hex, wrong envelope kind, both/neither
  of file/`--hex` provided), or verification failed; stderr names
  the failing rule.
- `2` — wrong PIN.
- `3` — vault wiped on this attempt.
- `4` — proposal verification failed (BEEF, fee cap, change script,
  etc.).
- `5` — signing failed (key derivation / sighash error).

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

### Sign over SSH with copy-paste only (no scp, no camera)

The companion's wallet-detail Send card surfaces the unsigned
proposal as a hex blob next to the multipart QR. Copy that hex
(the **Copy hex** button puts it on the clipboard as one
contiguous line), paste it into a `piwallet sign` invocation over
SSH, and the resulting hex (signed_tx) goes back to the companion's
`#/scan` "Paste hex" input for broadcast — round-trip without ever
touching the file system or the camera.

**As a parameter (simplest):**

```bash
# On the Pi, over SSH:
piwallet sign --hex 8a07b3f1c8d2... --wallet-id d2c1...
# verified: in=99904 out=99791 fee=113     <- stderr
# txid: f9c9f9229f...                       <- stderr
# signed_tx: 1f8b0800000000...              <- stdout, TTY-prefixed
```

Copy the **last** line — the one starting `signed_tx:` — into the
companion's `#/scan` "Paste hex" textarea. The companion strips the
`signed_tx:` prefix automatically and will also tolerate pasting
all three summary lines together (the `verified:` / `txid:` lines
are dropped on the way to decode). When stdout is *not* a TTY (e.g.
`piwallet sign … | xclip -selection clipboard`), no prefix is
added so the pipeline gets bare hex.

Hex contains only `[0-9a-f]` so it doesn't need shell quoting. A
typical proposal is ~500-2000 bytes ≈ 1-4 KB of hex, well under
`ARG_MAX` on any modern shell.

**Via stdin (better when typing interactively, since the command
line stays short):**

```bash
piwallet sign --hex - --wallet-id d2c1... <<'EOF'
8a07b3f1c8d2...
(paste the unsigned hex from the companion here, line wraps fine)
EOF
```

This bridge is the recommended unblock when the in-bonnet sign
flow is unavailable (e.g. before the camera/UI flow ships, or on
a Pi where the camera is detached for some reason).

### Quick fixture sanity check

```bash
python -m tests.fixtures.generate_fixtures
piwallet decode tests/fixtures/proposal_01.cbor
```
