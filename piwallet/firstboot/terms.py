"""Disclaimer acceptance state.

Persists a tiny JSON document at ``~/.piwallet/terms.json`` (or a
caller-supplied path) recording which disclaimer version the operator
has accepted, when they accepted it, and a per-device random ID. The
file is *not* sensitive material - it carries no secrets, only a
timestamp and an opaque ID - and so is stored in plain JSON so it can
be read with `cat` for debugging.

The disclaimer version policy is intentionally simple: when the
canonical disclaimer text changes in a way that requires re-consent,
bump :data:`CURRENT_TERMS_VERSION` in this module. On the next boot,
the saved state will compare lower than the new version and the
operator will see the prompt again.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Version of the disclaimer text the running build expects. Bump this
#: whenever the canonical disclaimer changes in a way the user must
#: re-consent to. Old saved states with a strictly lower version trigger
#: a re-prompt on next boot.
CURRENT_TERMS_VERSION: int = 1


@dataclass(frozen=True, slots=True)
class TermsState:
    """The on-disk schema."""

    terms_version: int
    accepted_at: str  # ISO 8601 UTC, e.g. "2026-05-10T15:20:30+00:00"
    device_id: str    # 16 hex chars (8 random bytes)


def default_state_path() -> Path:
    """Return ``~/.piwallet/terms.json`` (the default location).

    Re-exported here as part of the historical firstboot API; the
    actual path lives in :mod:`piwallet.core.paths`.
    """
    from piwallet.core.paths import default_terms_path

    return default_terms_path()


def load_state(path: Path | None = None) -> TermsState | None:
    """Read :class:`TermsState` from ``path`` (default: standard location).

    Returns ``None`` if the file is missing, unreadable, or malformed.
    The caller treats "no state" and "corrupt state" identically: in
    both cases we re-prompt the operator.
    """
    path = path if path is not None else default_state_path()
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return TermsState(
            terms_version=int(data["terms_version"]),
            accepted_at=str(data["accepted_at"]),
            device_id=str(data["device_id"]),
        )
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def save_state(state: TermsState, path: Path | None = None) -> None:
    """Persist ``state`` as pretty-printed JSON, creating parent dirs."""
    path = path if path is not None else default_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(state), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def requires_acceptance(
    path: Path | None = None,
    *,
    current_version: int = CURRENT_TERMS_VERSION,
) -> bool:
    """Return True if the operator must (re-)accept the disclaimer."""
    state = load_state(path)
    if state is None:
        return True
    return state.terms_version < current_version


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _random_device_id() -> str:
    return secrets.token_hex(8)


def mark_accepted(
    path: Path | None = None,
    *,
    now: Callable[[], str] = _utc_now_iso,
    random_id: Callable[[], str] = _random_device_id,
    current_version: int = CURRENT_TERMS_VERSION,
    preserve_device_id: bool = True,
) -> TermsState:
    """Record acceptance of the current disclaimer version.

    If a previous state file exists *and* ``preserve_device_id`` is
    True, the existing ``device_id`` is reused; this avoids generating
    fresh IDs on every disclaimer bump while still allowing the operator
    to wipe state and start over manually.
    """
    prev = load_state(path)
    device_id = (
        prev.device_id
        if (preserve_device_id and prev is not None and prev.device_id)
        else random_id()
    )
    state = TermsState(
        terms_version=current_version,
        accepted_at=now(),
        device_id=device_id,
    )
    save_state(state, path)
    return state
