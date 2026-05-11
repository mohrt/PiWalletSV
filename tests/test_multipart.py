"""Multipart QR framing (`PW1|` lines)."""

from __future__ import annotations

import pytest

from piwallet.core import envelope as env
from piwallet.qr.multipart import (
    MultipartAssembler,
    MultipartQrError,
    join_multipart_lines,
    split_envelope_to_lines,
)
from tests.fixtures.generate_fixtures import build_proposal_01


def test_empty_payload_roundtrip() -> None:
    asm = MultipartAssembler()
    assert asm.feed("PW1|1|0|") == b""


def test_split_join_roundtrip_fixture() -> None:
    blob, _meta = build_proposal_01()
    lines = split_envelope_to_lines(blob, max_encoded_chunk_chars=80)
    assert all(ln.startswith("PW1|") for ln in lines)
    assert len(lines) >= 2
    restored = join_multipart_lines(lines)
    assert restored == blob
    assert env.decode(restored) == env.decode(blob)


def test_assembler_out_of_order() -> None:
    blob = b"x" * 300
    lines = split_envelope_to_lines(blob, max_encoded_chunk_chars=64)
    assert len(lines) >= 3
    asm = MultipartAssembler()
    out: bytes | None = None
    for ln in reversed(lines):
        part = asm.feed(ln)
        if part is not None:
            out = part
    assert out == blob


def test_assembler_duplicate_fragment_ok() -> None:
    blob = b"w" * 400
    lines = split_envelope_to_lines(blob, max_encoded_chunk_chars=64)
    assert len(lines) >= 3
    asm = MultipartAssembler()
    asm.feed(lines[0])
    asm.feed(lines[0])  # duplicate OK
    out: bytes | None = None
    for ln in lines[1:]:
        part = asm.feed(ln)
        if part is not None:
            out = part
    assert out == blob


def test_stream_switch_resets_state() -> None:
    asm = MultipartAssembler()
    asm.feed("PW1|3|0|a")
    assert asm.expected_total == 3
    asm.feed("PW1|2|0|b")
    assert asm.parts_received == 1
    assert asm.expected_total == 2


def test_conflict_same_index_different_payload() -> None:
    asm = MultipartAssembler()
    asm.feed("PW1|2|0|YWJj")
    with pytest.raises(MultipartQrError, match="conflicting"):
        asm.feed("PW1|2|0|AAA")


def test_reject_bad_structure() -> None:
    asm = MultipartAssembler()
    with pytest.raises(MultipartQrError, match="structure"):
        asm.feed("PW1|")


def test_reject_bad_index() -> None:
    asm = MultipartAssembler()
    with pytest.raises(MultipartQrError, match="total/index"):
        asm.feed("PW1|3|99|YWJj")


@pytest.mark.parametrize(
    ("line",),
    [
        ("not a pw1 frame",),
        ("PW99|2|0|whatever",),
    ],
)
def test_non_pw1_does_not_error(line: str) -> None:
    """Unknown strings are skipped by the assembler (camera noise)."""

    asm = MultipartAssembler()
    assert asm.feed(line) is None
