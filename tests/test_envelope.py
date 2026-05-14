"""Tests for piwallet.core.envelope."""

from __future__ import annotations

import gzip

import cbor2
import pytest

from piwallet.core import envelope as e

# Reusable test fixtures.
DUMMY_FP = b"\xab\xcd\xef\x01"
DUMMY_TXID = "a" * 64
DUMMY_BEEF = b"\xde\xad\xbe\xef" * 32
# The Pi takes ``header_anchors`` on faith from the companion at the
# codec layer, so the round-trip suite just uses a sentinel 32-byte
# value. ``verify_proposal`` is what compares this against the BUMP-
# computed root.
DUMMY_ANCHOR_ROOT = b"\x42" * 32


def make_xpub_export() -> e.XpubExport:
    return e.XpubExport(
        xpub="xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQvVykQsKLARZdb"
        "qKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
        path="m/44'/236'/0'",
        label="daily",
        fingerprint=DUMMY_FP,
    )


def make_unsigned_proposal(*, change_index: int = 1) -> e.UnsignedProposal:
    inp = e.ProposalInput(
        txid=DUMMY_TXID,
        vout=0,
        sats=10_000,
        beef=DUMMY_BEEF,
        derivation=(0, 0),
    )
    out_recv = e.ProposalOutput(script_hex="76a914" + "00" * 20 + "88ac", sats=4_000)
    out_change = e.ProposalOutput(script_hex="76a914" + "11" * 20 + "88ac", sats=5_500)
    return e.UnsignedProposal(
        wallet_fp=DUMMY_FP,
        inputs=(inp,),
        outputs=(out_recv, out_change),
        change_index=change_index,
        change_derivation=(1, 0),
        fee_rate_satskb=500,
        locktime=0,
        header_anchors={812_340: DUMMY_ANCHOR_ROOT},
    )


def make_atomic_beef(*, txid_hex: str = "b" * 64, body_bytes: int = 64) -> bytes:
    """Hand-built BRC-95 Atomic BEEF envelope for codec round-trip
    tests. Real BRC-95 production happens via
    ``piwallet.core.atomic_beef.encode``; this helper just produces a
    well-formed byte string the envelope codec can ferry intact."""
    txid_bytes = bytes.fromhex(txid_hex)[::-1]
    return b"\x01\x01\x01\x01" + txid_bytes + (b"\xee" * body_bytes)


def make_signed_tx() -> e.SignedTx:
    return e.SignedTx(
        wallet_fp=DUMMY_FP,
        atomic_beef=make_atomic_beef(),
    )


# ---- xpub_export ---------------------------------------------------------


def test_xpub_export_roundtrip() -> None:
    original = make_xpub_export()
    blob = e.encode(original)
    assert isinstance(blob, bytes)
    decoded = e.decode(blob)
    assert isinstance(decoded, e.XpubExport)
    assert decoded == original


def test_xpub_export_kind_constant() -> None:
    assert e.XpubExport.KIND == "xpub"


def test_xpub_export_rejects_bad_fingerprint_length() -> None:
    with pytest.raises(e.EnvelopeError, match="4 bytes"):
        e.XpubExport.from_cbor(
            {
                "v": e.ENVELOPE_VERSION,
                "kind": "xpub",
                "xpub": "x",
                "path": "m/44'/236'/0'",
                "label": "x",
                "fp": b"\xab\xcd\xef",  # only 3 bytes
            }
        )


def test_xpub_export_rejects_missing_keys() -> None:
    with pytest.raises(e.EnvelopeError, match="missing required key"):
        e.XpubExport.from_cbor(
            {"v": e.ENVELOPE_VERSION, "kind": "xpub", "xpub": "x"}
        )


def test_xpub_export_defaults_to_main_network() -> None:
    """Default kwarg keeps existing call sites byte-identical apart from
    a new ``net`` field appearing in the encoded payload."""
    original = make_xpub_export()
    assert original.network == "main"
    blob = e.encode(original)
    decoded = e.decode(blob)
    assert isinstance(decoded, e.XpubExport)
    assert decoded.network == "main"


def test_xpub_export_carries_testnet_marker() -> None:
    original = e.XpubExport(
        xpub="xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQvVykQsKLARZdb"
        "qKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
        path="m/44'/236'/0'",
        label="testnet wallet",
        fingerprint=DUMMY_FP,
        network="test",
    )
    blob = e.encode(original)
    decoded = e.decode(blob)
    assert isinstance(decoded, e.XpubExport)
    assert decoded.network == "test"
    assert decoded == original


def test_xpub_export_pre_v1_1_envelope_decodes_as_main() -> None:
    """An xpub_export envelope encoded by a pre-testnet build (no
    ``net`` key) decodes as ``network='main'``. Locks the wire-level
    backward compatibility promise."""
    body = {
        "v": e.ENVELOPE_VERSION,
        "kind": "xpub",
        "xpub": "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQvVykQsKLARZdb"
        "qKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
        "path": "m/44'/236'/0'",
        "label": "legacy",
        "fp": DUMMY_FP,
    }
    blob = gzip.compress(cbor2.dumps(body))
    decoded = e.decode(blob)
    assert isinstance(decoded, e.XpubExport)
    assert decoded.network == "main"


def test_xpub_export_rejects_unknown_network() -> None:
    body = {
        "v": e.ENVELOPE_VERSION,
        "kind": "xpub",
        "xpub": "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQvVykQsKLARZdb"
        "qKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R",
        "path": "m/44'/236'/0'",
        "label": "x",
        "fp": DUMMY_FP,
        "net": "regtest",
    }
    with pytest.raises(e.EnvelopeError, match="network"):
        e.XpubExport.from_cbor(body)


# ---- unsigned_proposal ---------------------------------------------------


def test_unsigned_proposal_roundtrip() -> None:
    original = make_unsigned_proposal()
    decoded = e.decode(e.encode(original))
    assert isinstance(decoded, e.UnsignedProposal)
    assert decoded == original


def test_unsigned_proposal_change_index_in_range() -> None:
    """changeIndex must be a valid index into outputs."""
    bad = make_unsigned_proposal(change_index=99)
    blob = e.encode(bad)
    with pytest.raises(e.EnvelopeError, match="changeIndex"):
        e.decode(blob)


def test_unsigned_proposal_negative_change_index() -> None:
    with pytest.raises(e.EnvelopeError, match="changeIndex"):
        # Force a negative value through manual CBOR.
        body = make_unsigned_proposal().to_cbor()
        body["changeIndex"] = -1
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_unsigned_proposal_empty_inputs() -> None:
    body = make_unsigned_proposal().to_cbor()
    body["inputs"] = []
    with pytest.raises(e.EnvelopeError, match="inputs"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_unsigned_proposal_empty_outputs() -> None:
    body = make_unsigned_proposal().to_cbor()
    body["outputs"] = []
    with pytest.raises(e.EnvelopeError, match="outputs"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_unsigned_proposal_rejects_short_anchor_root() -> None:
    """v2 carries header anchors as a ``height -> 32-byte root`` map.
    A truncated entry must surface a clear, height-tagged error."""
    body = make_unsigned_proposal().to_cbor()
    body["headerAnchors"] = {"100": b"\x00" * 31}  # not 32 bytes
    with pytest.raises(e.EnvelopeError, match=r"headerAnchors\[100\]"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_unsigned_proposal_rejects_non_dict_header_anchors() -> None:
    body = make_unsigned_proposal().to_cbor()
    body["headerAnchors"] = [(100, b"\x00" * 32)]  # list of tuples, not a map
    with pytest.raises(e.EnvelopeError, match="headerAnchors must be a map"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_unsigned_proposal_rejects_negative_anchor_height() -> None:
    body = make_unsigned_proposal().to_cbor()
    body["headerAnchors"] = {"-1": b"\x00" * 32}
    with pytest.raises(e.EnvelopeError, match="headerAnchors height"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_unsigned_proposal_rejects_empty_header_anchors() -> None:
    """An empty anchor map is structurally illegal: a proposal must
    name at least one input, and every input contributes one anchor.
    Pinning this at the codec surface gives the operator a clear
    error before the per-input verification loop starts."""
    body = make_unsigned_proposal().to_cbor()
    body["headerAnchors"] = {}
    with pytest.raises(e.EnvelopeError, match="at least one entry"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_unsigned_proposal_bad_derivation_format() -> None:
    body = make_unsigned_proposal().to_cbor()
    body["inputs"][0]["derivation"] = [0, 1, 2]
    with pytest.raises(e.EnvelopeError, match="derivation"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_unsigned_proposal_does_not_carry_standalone_merkle_path() -> None:
    """v2 schema dropped the redundant per-input ``merklePath`` field
    because the BEEF (BRC-62) payload already carries it. Any caller
    that tries to assemble a v2 envelope by including the old field
    should not appear in the encoded CBOR; a decoded payload should
    not surface it either."""
    proposal = make_unsigned_proposal()
    body = proposal.to_cbor()
    assert "merklePath" not in body["inputs"][0]
    decoded = e.decode(e.encode(proposal))
    assert isinstance(decoded, e.UnsignedProposal)
    assert not hasattr(decoded.inputs[0], "merkle_path")


def test_unsigned_proposal_default_locktime() -> None:
    """If locktime is omitted, decode falls back to 0."""
    body = make_unsigned_proposal().to_cbor()
    del body["locktime"]
    decoded = e.decode(gzip.compress(cbor2.dumps(body)))
    assert isinstance(decoded, e.UnsignedProposal)
    assert decoded.locktime == 0


# ---- signed_tx -----------------------------------------------------------


def test_signed_tx_roundtrip() -> None:
    original = make_signed_tx()
    decoded = e.decode(e.encode(original))
    assert isinstance(decoded, e.SignedTx)
    assert decoded == original


def test_signed_tx_rejects_bad_fingerprint() -> None:
    with pytest.raises(e.EnvelopeError, match="walletFp"):
        e.SignedTx.from_cbor(
            {
                "v": e.ENVELOPE_VERSION,
                "kind": "signed",
                "walletFp": b"\xff\xff",
                "atomicBeef": make_atomic_beef(),
            }
        )


def test_signed_tx_rejects_non_bytes_atomic_beef() -> None:
    with pytest.raises(e.EnvelopeError, match="atomicBeef"):
        e.SignedTx.from_cbor(
            {
                "v": e.ENVELOPE_VERSION,
                "kind": "signed",
                "walletFp": DUMMY_FP,
                "atomicBeef": "not bytes",
            }
        )


def test_signed_tx_txid_is_derived_from_atomic_beef_header() -> None:
    """v2 dropped the standalone ``txid`` field and exposes it as a
    property derived from the BRC-95 header. Decoded envelopes must
    surface the same hex the producer declared."""
    txid_hex = "ab" * 32
    s = e.SignedTx(wallet_fp=DUMMY_FP, atomic_beef=make_atomic_beef(txid_hex=txid_hex))
    assert s.txid == txid_hex
    decoded = e.decode(e.encode(s))
    assert isinstance(decoded, e.SignedTx)
    assert decoded.txid == txid_hex


# ---- top-level decode errors --------------------------------------------


def test_decode_rejects_non_bytes() -> None:
    with pytest.raises(e.EnvelopeError, match="bytes"):
        e.decode("not bytes")  # type: ignore[arg-type]


def test_decode_rejects_corrupted_gzip() -> None:
    with pytest.raises(e.EnvelopeError, match="gzip"):
        e.decode(b"\x00\x00not_gzip\x00\x00")


def test_decode_rejects_corrupted_cbor() -> None:
    junk = gzip.compress(b"\xff\xff\xff\xff\xff")  # invalid CBOR
    with pytest.raises(e.EnvelopeError, match="CBOR"):
        e.decode(junk)


def test_decode_rejects_unknown_version() -> None:
    body = {"v": 99, "kind": "xpub"}
    with pytest.raises(e.EnvelopeError, match="version"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_decode_rejects_unknown_kind() -> None:
    body = {"v": e.ENVELOPE_VERSION, "kind": "weird"}
    with pytest.raises(e.EnvelopeError, match="kind"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_decode_rejects_legacy_v1_envelopes() -> None:
    """v1 envelopes (pre-Atomic-BEEF, pre-merklePath-drop) MUST be
    refused. The schema bump is the documented signal that an
    out-of-sync producer needs an upgrade; silently accepting v1
    would let stale companions ship a wire format the verifier no
    longer understands and fail with a less actionable error
    later."""
    body = {"v": 1, "kind": "xpub"}
    with pytest.raises(e.EnvelopeError, match="version"):
        e.decode(gzip.compress(cbor2.dumps(body)))


def test_decode_rejects_non_map_top_level() -> None:
    blob = gzip.compress(cbor2.dumps([1, 2, 3]))
    with pytest.raises(e.EnvelopeError, match="map"):
        e.decode(blob)


def test_encoded_size_is_smaller_than_raw() -> None:
    """Sanity: gzip helps a real-world proposal payload (lots of repeated bytes in BEEF)."""
    proposal = make_unsigned_proposal()
    raw = cbor2.dumps(proposal.to_cbor())
    gz = e.encode(proposal)
    assert len(gz) < len(raw)


def test_envelope_version_constant_is_2() -> None:
    """v2 was cut for the BRC-95 / merklePath-drop schema cleanup;
    pin the constant so a future bump triggers a deliberate update of
    every version-aware test rather than slipping through silently."""
    assert e.ENVELOPE_VERSION == 2
