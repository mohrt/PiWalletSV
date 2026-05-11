"""Multipart QR framing for payloads larger than a single barcode.

Splits the gzip+cbor envelope blob into sequentially scanned frames.
The companion PWA (Phase 4) emits the same `PW1|` line format documented
in `multipart.py`.
"""

from piwallet.qr.multipart import (
    MultipartAssembler,
    MultipartQrError,
    encode_multipart_lines,
    join_multipart_lines,
    split_envelope_to_lines,
)

__all__ = [
    "MultipartAssembler",
    "MultipartQrError",
    "encode_multipart_lines",
    "join_multipart_lines",
    "split_envelope_to_lines",
]
