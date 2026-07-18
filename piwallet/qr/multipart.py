"""ASCII multipart framing for animated QR payloads.

Problem: a typical `encode(envelope)` blob is hundreds to thousands of bytes.
A QR code comfortably fits only a fragment. The companion rotates through
many codes; the Pi assembles fragments in any order until all parts arrive.

Wire format (`PW1`, version 1) — one barcode string per frame::

    PW1|<total>|<index>|<base64url_no_pad_fragment>

Where:

- `<total>` is an integer segment count (`>= 1`).
- `<index>` is zero-based (`0 .. total-1`).
- `<base64url_no_pad_fragment>` is a slice of URL-safe Base64 encoding
  (RFC 4648 alphabet `A-Za-z0-9-_`, padding omitted).

The barcode payload is the concatenation of all fragments in index order.

Encoding note: Python's ``urlsafe_b64encode`` uses `-` and `_`; we strip `=`.

Stream reset: seeing a barcode with a *different* `total` than the one
currently being collected clears partial state and starts a fresh stream.

This framing is deliberately minimal so the companion PWA can replicate it
without pulling in heavyweight UR/BC libraries.
"""

from __future__ import annotations

import base64
import math
import re
from collections.abc import Iterable

MAGIC = "PW1"
SEP = "|"
_PREFIX_RE = re.compile(
    rf"^{re.escape(MAGIC)}{re.escape(SEP)}"
    rf"(?P<t>\d+){re.escape(SEP)}(?P<i>\d+){re.escape(SEP)}(?P<rest>.*)$"
)


class MultipartQrError(ValueError):
    """Malformed multipart line or incompatible stream state."""


def split_envelope_to_lines(data: bytes, *, max_encoded_chunk_chars: int = 100) -> list[str]:
    """Split arbitrary bytes into `PW1` barcode lines.

    Default of 100 characters per fragment keeps each frame around QR
    version 7 (byte mode, ECC L) so modules stay large enough for the
    OV5647 kit camera to decode from a phone screen. Callers that need
    denser packing (e.g. phone scanning a bonnet TFT) may pass a
    different size; pairing / signed-tx already use 100 explicitly.

    Chunks are *balanced*: when the payload doesn't divide evenly we
    pick ``n_chunks = ceil(len / max)`` and then size each chunk at
    ``ceil(len / n_chunks)`` so the trailing fragment can't shrink to
    a tiny QR. An unbalanced split (e.g. ``[240, 26]``) renders one
    dense frame and one near-empty one, which is hard to scan reliably
    on a phone — both frames look very different to the autofocus.

    :param data: usually `envelope.encode(...)` gzip+cbor bytes.
    :param max_encoded_chunk_chars: max characters per Base64 slice.
    """
    if max_encoded_chunk_chars < 64:
        raise ValueError("max_encoded_chunk_chars too small")

    blob_b64 = base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
    if not blob_b64:
        return [f"{MAGIC}{SEP}1{SEP}0{SEP}"]

    n_chunks = math.ceil(len(blob_b64) / max_encoded_chunk_chars)
    chunk_size = math.ceil(len(blob_b64) / n_chunks)
    lines: list[str] = []
    for i in range(n_chunks):
        start = i * chunk_size
        frag = blob_b64[start : start + chunk_size]
        lines.append(f"{MAGIC}{SEP}{n_chunks}{SEP}{i}{SEP}{frag}")
    return lines


def join_multipart_lines(lines: Iterable[str]) -> bytes:
    """Join a full set of PW1 lines (any order) into raw bytes."""
    asm = MultipartAssembler()
    out: bytes | None = None
    for raw in lines:
        part = asm.feed(raw.strip())
        if part is not None:
            if out is not None:
                raise MultipartQrError("multiple complete payloads in one join call")
            out = part
    if out is None:
        raise MultipartQrError("incomplete multipart set")
    return out


def encode_multipart_lines(data: bytes, **kwargs: int) -> list[str]:
    """Alias for :func:`split_envelope_to_lines` (symmetry with join)."""
    return split_envelope_to_lines(data, **kwargs)


def pw1_line_meta(line: str) -> tuple[int, int] | None:
    """Return ``(total, index)`` for a PW1 barcode line, or ``None`` if not PW1."""

    m = _PREFIX_RE.match(line.strip())
    if not m:
        return None
    return int(m.group("t")), int(m.group("i"))


class MultipartAssembler:
    """Stateful decoder fed one scanned barcode string at a time."""

    def __init__(self) -> None:
        self._total: int | None = None
        self._parts: dict[int, str] = {}

    @property
    def expected_total(self) -> int | None:
        """Declared segment count after at least one PW1 frame, else ``None``."""

        return self._total

    @property
    def parts_received(self) -> int:
        """Number of distinct fragment indices collected for the current stream."""

        return len(self._parts)

    def reset(self) -> None:
        self._total = None
        self._parts.clear()

    def feed(self, line: str) -> bytes | None:
        """Ingest one barcode payload. Returns assembled bytes when complete."""
        s = line.strip()
        if not s.startswith(f"{MAGIC}{SEP}"):
            return None

        m = _PREFIX_RE.match(s)
        if not m:
            raise MultipartQrError(f"bad PW1 line structure: {s[:60]!r}…")

        total = int(m.group("t"))
        index = int(m.group("i"))
        frag = m.group("rest")

        if total < 1 or index < 0 or index >= total:
            raise MultipartQrError(f"bad total/index: total={total} index={index}")

        if self._total is not None and total != self._total:
            self.reset()
        self._total = total

        if index in self._parts and self._parts[index] != frag:
            raise MultipartQrError(f"conflicting fragment at index {index}")
        self._parts[index] = frag

        if len(self._parts) < total:
            return None

        blob_b64 = "".join(self._parts[i] for i in range(total))
        padded = blob_b64 + "=" * (-len(blob_b64) % 4)
        try:
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        except Exception as exc:
            raise MultipartQrError(f"invalid base64 payload: {exc}") from exc

        self.reset()
        return raw
