# QR transport — `PW1` multipart framing — v1

Envelopes from [`envelopes.md`](envelopes.md) are typically a few hundred
bytes to a few tens of kilobytes after gzip+CBOR. That overflows any
realistic QR code, so we slice them into a sequence of QR codes that
the receiver re-assembles. The transmitter animates between QR
frames; the receiver scans whichever frames it can and stops when
the set is complete.

This document defines version 1 of that framing, called **`PW1`**.
It is deliberately minimal — third-party companions can implement
both halves in well under a hundred lines of code.

## 1. Line grammar

Every QR code on the wire carries exactly one ASCII line of the form:

```
PW1|<total>|<index>|<base64url_fragment>
```

Formally (ABNF-ish):

```
line          = magic "|" total "|" index "|" fragment
magic         = "PW1"
total         = 1*DIGIT       ; decimal, no leading zeros, value >= 1
index         = 1*DIGIT       ; decimal, no leading zeros, 0 <= value < total
fragment      = *(ALPHA / DIGIT / "-" / "_")
```

`fragment` is unpadded base64url per RFC 4648 §5 — the alphabet
`A-Za-z0-9-_`, no `=` padding. The `+` and `/` characters of
standard base64 are **never** present.

Whitespace MUST NOT appear inside a line. Implementations SHOULD
strip leading/trailing whitespace from a scanned QR string before
parsing.

There is no line terminator. One QR code = one line. Multiple lines
glued by newlines is **not** part of the wire format; that's a
debugging convenience some CLI tools use (e.g., `piwallet qr split`
emits one line per row to stdout).

## 2. Encoding (transmitter side)

Given a `data` byte string (typically `gzip(cbor(envelope))`):

1. Base64url-encode `data` with no padding. Call the result `b`.
2. Pick a `chunk_size` ≤ the safe per-QR character count for your
   chosen QR version and error-correction level. The reference
   transmitters default to `720` characters per fragment, which gives
   QR version 16-ish at byte mode (capacity ~1273 chars) with
   comfortable margin and no compaction tricks. Smaller bonnet
   displays SHOULD scale this down; the assembler doesn't care.
3. Let `n = ceil(len(b) / chunk_size)`. For `i` in `0..n-1`, the i-th
   line is:

   ```
   PW1|<n>|<i>|<b[i*chunk_size : (i+1)*chunk_size]>
   ```

If `data` is empty, emit exactly one line: `PW1|1|0|` (empty
fragment, trailing pipe).

Frames SHOULD be displayed in a rotating animation; the assembler
collects whichever it can decode, so missed frames are not fatal as
long as the loop eventually replays them. The Pi bonnet defaults to
**700 ms per frame** (~1.4 fps); the Pi camera captures and decodes
roughly every **350 ms** (~2.9 fps). The companion uses the same
700 ms interval so the Pi camera sees each QR long enough before it
rotates. Faster cycles (6–8 fps) work for phone/laptop webcams but
can slow Pi-side assembly because the camera misses intermediate frames.

## 3. Decoding (assembler side)

The assembler is stateful. Pseudocode:

```python
class Assembler:
    total = None
    parts = {}          # index -> fragment string

    def feed(line):
        line = line.strip()
        if not line.startswith("PW1|"):
            return None                      # silently ignore noise
        magic, total_s, index_s, fragment = line.split("|", 3)
        total = int(total_s)
        index = int(index_s)
        if total < 1 or not (0 <= index < total):
            raise BadLine
        if self.total is not None and total != self.total:
            self.reset()                     # new stream
        self.total = total
        if index in self.parts and self.parts[index] != fragment:
            raise BadLine                    # corruption in flight
        self.parts[index] = fragment
        if len(self.parts) < total:
            return None
        b = "".join(self.parts[i] for i in range(total))
        return base64url_decode_no_pad(b)
```

Key behaviours:

- **Idempotent re-feed.** Receiving the same `(total, index, fragment)`
  multiple times is normal (the transmitter loops). Storing it again
  is a no-op.
- **Conflict = abort.** Receiving a different fragment for an index
  already filled is a hard error — the assembler MUST refuse to
  silently overwrite. The reference Pi assembler raises and the
  receiver discards the in-progress stream.
- **Stream reset.** Seeing a frame whose `total` differs from the
  current stream's `total` clears all collected parts and starts a
  fresh stream. This makes the transmitter free to switch to a new
  envelope without an explicit handoff (e.g., user navigates away).
- **No order requirement.** The assembler does not care which order
  frames arrive in; it just needs every index from `0..total-1`.

A complete stream's bytes are produced exactly once. The reference
assembler clears its state immediately on success.

## 4. Capacity and sizing

The default chunk size of 720 characters per fragment gives:

- A `PW1|<total>|<index>|...` line of typically 720 + ~10 characters.
  At QR version 16 with error-correction level M and byte mode, the
  capacity is 1273 characters — leaving comfortable headroom.
- A typical `unsigned_proposal` of ~2 KB encodes to ~2700 base64url
  characters, which is ~4 frames. The transmitter animates through
  them in ~0.5 s; in practice the receiver gets a full set within
  one or two cycles.

Implementations MAY use smaller chunks for noisy environments
(consumer phone cameras on shaky hands), or larger chunks if they
have a stable mount and a high-density QR generator. The format
imposes no upper bound.

A signer SHOULD have a fail-safe cap on the total payload size it
will assemble (the reference implementation accepts up to ~16 KB of
decoded bytes; larger payloads almost certainly indicate a malformed
or hostile transmitter).

## 5. QR rendering hints

PiWalletSV's reference encoders use these defaults; they are not
required but make scanning easier on Pi-class cameras:

- QR error-correction level **M** (allow ~15% damage). L is too
  fragile in motion; Q and H eat into capacity without much
  practical benefit at the distances involved.
- Byte mode (not alphanumeric). base64url contains `-` and `_`
  which are not in the QR alphanumeric set.
- White margin (quiet zone) of at least 2 modules.
- Render at integer pixel scale on screen so the camera doesn't see
  shimmer.
- Animate at **700 ms per frame** when the Pi camera is the scanner
  (matches bonnet ``PairingMultipartQrScreen``). Up to ~6–8 fps is fine
  for phone/laptop webcams on a static mount; slower on hand-held setups.

The reference companion uses the JavaScript `qrcode-generator` library
configured for byte mode and error-correction level M; the Pi side
uses `PIL.Image` to compose QR codes for the bonnet display and `qrencode`
for terminal demos. Either approach is fine.

## 6. End-of-stream signaling

There is **none**. v1 has no explicit "this is the last frame" or
checksum frame — the assembler knows it's done when it has every
index from `0..total-1`. This keeps the format trivially small.

A v2 could add a CRC frame or a `total` byte length to detect cases
where every fragment arrives correctly but their base64 decode
produces a different gzip body than the transmitter sent. We don't
have evidence this matters in practice; the gzip body has its own
CRC32 (RFC 1952 §2.3.1) and CBOR has a strict grammar, so corrupted
data fails to decode rather than silently producing a different
envelope.
