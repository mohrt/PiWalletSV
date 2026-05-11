"""Disclaimer acceptance state tests."""

from __future__ import annotations

import json
from pathlib import Path

from piwallet.firstboot.terms import (
    CURRENT_TERMS_VERSION,
    TermsState,
    load_state,
    mark_accepted,
    requires_acceptance,
    save_state,
)


def _fixed_now() -> str:
    return "2026-05-10T15:20:30+00:00"


def _fixed_random_id() -> str:
    return "0123456789abcdef"


def test_requires_acceptance_when_state_missing(tmp_path: Path) -> None:
    state_file = tmp_path / "terms.json"
    assert requires_acceptance(state_file) is True


def test_requires_acceptance_when_state_stale(tmp_path: Path) -> None:
    state_file = tmp_path / "terms.json"
    save_state(
        TermsState(
            terms_version=0,
            accepted_at="2025-01-01T00:00:00+00:00",
            device_id="cafebabecafebabe",
        ),
        state_file,
    )
    assert requires_acceptance(state_file, current_version=1) is True


def test_requires_acceptance_false_when_current(tmp_path: Path) -> None:
    state_file = tmp_path / "terms.json"
    save_state(
        TermsState(
            terms_version=CURRENT_TERMS_VERSION,
            accepted_at=_fixed_now(),
            device_id=_fixed_random_id(),
        ),
        state_file,
    )
    assert requires_acceptance(state_file) is False


def test_load_returns_none_when_file_corrupt(tmp_path: Path) -> None:
    state_file = tmp_path / "terms.json"
    state_file.write_text("not json at all")
    assert load_state(state_file) is None
    # And requires_acceptance treats corrupt state as "not accepted".
    assert requires_acceptance(state_file) is True


def test_load_returns_none_when_file_missing_keys(tmp_path: Path) -> None:
    state_file = tmp_path / "terms.json"
    state_file.write_text(json.dumps({"terms_version": 1}))
    assert load_state(state_file) is None


def test_mark_accepted_writes_state(tmp_path: Path) -> None:
    state_file = tmp_path / "subdir" / "terms.json"
    state = mark_accepted(
        state_file,
        now=_fixed_now,
        random_id=_fixed_random_id,
    )
    assert state.terms_version == CURRENT_TERMS_VERSION
    assert state.accepted_at == _fixed_now()
    assert state.device_id == _fixed_random_id()
    on_disk = json.loads(state_file.read_text())
    assert on_disk == {
        "terms_version": CURRENT_TERMS_VERSION,
        "accepted_at": _fixed_now(),
        "device_id": _fixed_random_id(),
    }


def test_mark_accepted_preserves_device_id_across_version_bumps(tmp_path: Path) -> None:
    state_file = tmp_path / "terms.json"
    # First acceptance under v0.
    mark_accepted(
        state_file,
        now=lambda: "2026-01-01T00:00:00+00:00",
        random_id=lambda: "deadbeefdeadbeef",
        current_version=0,
    )
    # Bump to v1; device_id must stay the same.
    new_state = mark_accepted(
        state_file,
        now=_fixed_now,
        random_id=lambda: "should-not-be-used",
        current_version=1,
    )
    assert new_state.device_id == "deadbeefdeadbeef"
    assert new_state.terms_version == 1


def test_mark_accepted_regenerates_when_preserve_false(tmp_path: Path) -> None:
    state_file = tmp_path / "terms.json"
    mark_accepted(
        state_file,
        now=lambda: "2026-01-01T00:00:00+00:00",
        random_id=lambda: "deadbeefdeadbeef",
    )
    new_state = mark_accepted(
        state_file,
        now=_fixed_now,
        random_id=lambda: "ffffffffffffffff",
        preserve_device_id=False,
    )
    assert new_state.device_id == "ffffffffffffffff"
