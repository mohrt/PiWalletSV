"""Pins ``tests/fixtures/addresses_canonical.json`` against current Python output.

The TypeScript side asserts byte-for-byte against this fixture (see
``companion/tests/derive.test.ts``). If the Python derivation chain changes,
this test will fail BEFORE the cross-language test does, so the developer
knows to regenerate the fixture (and verify the TS side still agrees).
"""

from __future__ import annotations

import json
from pathlib import Path

from piwallet.core import derivation as deriv
from piwallet.core import mnemonic as mnem

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "addresses_canonical.json"


def test_address_fixture_matches_python_derivation() -> None:
    fx = json.loads(FIXTURE_PATH.read_text())
    seed = mnem.seed_from_mnemonic(fx["mnemonic"])
    master = deriv.master_xprv_from_seed(seed)
    acct = deriv.derive_account(master)

    assert acct.path == fx["path"], "derivation path drifted"
    assert acct.fingerprint.hex() == fx["fingerprint"], "fingerprint drifted"
    assert str(acct.xpub) == fx["xpub"], "account xpub drifted"

    for entry in fx["addresses"]["receive"]:
        got = deriv.derive_address(acct.xpub, deriv.CHANGE_RECEIVE, entry["index"])
        assert got == entry["address"], (
            f"receive m/0/{entry['index']} drifted: {got} != {entry['address']}"
        )

    for entry in fx["addresses"]["change"]:
        got = deriv.derive_address(acct.xpub, deriv.CHANGE_INTERNAL, entry["index"])
        assert got == entry["address"], (
            f"change m/1/{entry['index']} drifted: {got} != {entry['address']}"
        )
