"""Pins ``tests/fixtures/proposal_01_decoded.json`` to the live decoded form.

The decoded JSON is part of the public protocol-v1 conformance suite
(see ``docs/protocol/conformance.md``). Anyone implementing a v1
decoder is encouraged to diff their structural dump against this
file, so the committed JSON MUST always reflect the current bytes of
``proposal_01.cbor``.

The test regenerates the dump via ``scripts/dump_decoded_envelope``
and refuses to pass if it differs from what's checked in. To
regenerate after an intentional change, run::

    python scripts/dump_decoded_envelope.py \
        tests/fixtures/proposal_01.cbor \
        tests/fixtures/proposal_01_decoded.json

and commit the result.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.dump_decoded_envelope import dump

FIXTURE_DIR = Path(__file__).parent / "fixtures"
ENVELOPE_PATH = FIXTURE_DIR / "proposal_01.cbor"
DECODED_PATH = FIXTURE_DIR / "proposal_01_decoded.json"


def test_decoded_envelope_matches_committed_json() -> None:
    expected = json.loads(DECODED_PATH.read_text())
    actual = dump(ENVELOPE_PATH)
    assert actual == expected, (
        "proposal_01_decoded.json is stale; regenerate with "
        "`python scripts/dump_decoded_envelope.py "
        "tests/fixtures/proposal_01.cbor tests/fixtures/proposal_01_decoded.json`"
    )
