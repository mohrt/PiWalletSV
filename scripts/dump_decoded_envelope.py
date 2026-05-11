"""Dump a field-by-field decoded view of a PiWalletSV envelope as JSON.

The output is intended as a structural reference for third-party
implementers writing a v1-conformant decoder. It is NOT a wire
format — it is a human-readable trace of the CBOR shape inside the
gzip-compressed envelope blob.

Schema of each node in the output:

    { "type": <cbor type tag>,
      "value": <scalar value if short>,
      "length": <int, for arrays/maps/bytes>,
      "sample": "<first/last bytes as hex>",
      "items": [ <node>, ... ],            # for arrays
      "entries": [ { "key": <node>, "value": <node> }, ... ]  # for maps
    }

`type` is one of: "uint", "int", "bytes", "text", "array", "map",
"bool", "null", "float".

Run from the repo root::

    python scripts/dump_decoded_envelope.py \\
        tests/fixtures/proposal_01.cbor \\
        tests/fixtures/proposal_01_decoded.json

If only the input path is given, JSON is printed to stdout.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any

import cbor2

MAX_SCALAR_LEN = 128
"""Max characters / bytes of a scalar to dump inline before summarizing."""


def _hex(b: bytes) -> str:
    return b.hex()


def _summarize_bytes(b: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "bytes",
        "length": len(b),
    }
    if len(b) <= MAX_SCALAR_LEN:
        out["value_hex"] = _hex(b)
    else:
        out["head_hex"] = _hex(b[:32])
        out["tail_hex"] = _hex(b[-32:])
    return out


def _summarize_text(s: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "text",
        "length": len(s),
    }
    if len(s) <= MAX_SCALAR_LEN:
        out["value"] = s
    else:
        out["head"] = s[:32]
        out["tail"] = s[-32:]
    return out


def describe(node: Any) -> dict[str, Any]:
    if node is None:
        return {"type": "null"}
    if isinstance(node, bool):
        return {"type": "bool", "value": node}
    if isinstance(node, int):
        return {
            "type": "uint" if node >= 0 else "int",
            "value": node,
        }
    if isinstance(node, float):
        return {"type": "float", "value": node}
    if isinstance(node, (bytes, bytearray)):
        return _summarize_bytes(bytes(node))
    if isinstance(node, str):
        return _summarize_text(node)
    if isinstance(node, (list, tuple)):
        return {
            "type": "array",
            "length": len(node),
            "items": [describe(v) for v in node],
        }
    if isinstance(node, dict):
        entries = []
        for k, v in node.items():
            entries.append({"key": describe(k), "value": describe(v)})
        return {
            "type": "map",
            "length": len(node),
            "entries": entries,
        }
    return {"type": type(node).__name__, "repr": repr(node)}


def dump(envelope_path: Path) -> dict[str, Any]:
    """Return a path-independent structural dump of the envelope.

    The output is deliberately cwd-agnostic (no source path is
    included) so committing it as a fixture produces stable bytes
    regardless of where the script was invoked from.
    """
    blob = envelope_path.read_bytes()
    cbor_bytes = gzip.decompress(blob)
    body = cbor2.loads(cbor_bytes)
    return {
        "envelope_size_bytes": len(blob),
        "cbor_size_bytes": len(cbor_bytes),
        "compression_ratio": round(len(blob) / max(len(cbor_bytes), 1), 4),
        "body": describe(body),
    }


def main() -> int:
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(__doc__, file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"error: {src} does not exist", file=sys.stderr)
        return 2

    decoded = dump(src)
    payload = json.dumps(decoded, indent=2) + "\n"

    if len(sys.argv) == 3:
        dest = Path(sys.argv[2])
        dest.write_text(payload)
        print(f"wrote {dest} ({dest.stat().st_size} bytes)")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
