"""Interaction + render tests for the bonnet airgap screen."""

from __future__ import annotations

import pytest

from piwallet.bonnet import airgap_screen as ags
from piwallet.diag.airgap import AirgapReport, CheckResult
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS) -> Event:
    return Event(button=b, kind=k, at_ms=0)


def _make_screen(
    *checks: CheckResult,
) -> ags.AirgapScreen:
    return ags.AirgapScreen(report=AirgapReport(checks=checks))


def _fb() -> FrameBuffer:
    return FrameBuffer(240, 240)


# ---------------------------------------------------------------------------
# Construction + verdict
# ---------------------------------------------------------------------------


def test_screen_starts_undone_and_unresolved() -> None:
    s = _make_screen(CheckResult("modules", True, "ok"))
    assert s.done is False
    assert s.result is None


def test_screen_reports_pass_when_no_failures() -> None:
    s = _make_screen(
        CheckResult("modules", True, "ok"),
        CheckResult("rfkill", None, "n/a"),
    )
    assert s.report.ok is True


def test_screen_reports_breach_when_any_failure() -> None:
    s = _make_screen(
        CheckResult("modules", True, "ok"),
        CheckResult("rfkill", False, "phy0 unblocked"),
    )
    assert s.report.ok is False


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


def test_b_press_exits_back() -> None:
    s = _make_screen(CheckResult("modules", True, "ok"))
    s.on_event(_evt(Button.B))
    assert s.done is True
    assert s.result == "back"


def test_b_long_is_ignored_until_back() -> None:
    s = _make_screen(CheckResult("modules", True, "ok"))
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is False
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.done is True
    assert s.result == "back"


@pytest.mark.parametrize("button", [Button.A, Button.SELECT])
def test_a_or_select_refreshes_report_in_place(
    button: Button, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial_report = AirgapReport(checks=(CheckResult("modules", False, "stale"),))
    refreshed_report = AirgapReport(checks=(CheckResult("modules", True, "fresh"),))

    s = ags.AirgapScreen(report=initial_report)
    refreshed_rows = (CheckResult("wifi", True, "fresh"),)
    monkeypatch.setattr(
        "piwallet.bonnet.airgap_screen.check_airgap", lambda: refreshed_report
    )
    monkeypatch.setattr(
        "piwallet.bonnet.airgap_screen.checks_for_bonnet_display",
        lambda: refreshed_rows,
    )

    s.on_event(_evt(button))

    assert s.done is False
    assert s.result is None
    assert s.report is refreshed_report
    assert s._rows() is refreshed_rows


def test_events_after_done_are_no_op() -> None:
    s = _make_screen(CheckResult("modules", True, "ok"))
    s.on_event(_evt(Button.B))
    assert s.done is True

    # Subsequent events should not flip the result back.
    s.on_event(_evt(Button.A))
    assert s.result == "back"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def test_draw_does_not_raise_on_pass_report() -> None:
    s = _make_screen(
        CheckResult("modules", True, "no radio modules loaded"),
        CheckResult("rfkill", True, "2 radio(s) blocked"),
    )
    fb = _fb()
    s.draw(fb)  # smoke: just ensure all anchors / colours resolve.


def test_draw_does_not_raise_on_fail_report() -> None:
    s = _make_screen(
        CheckResult("modules", False, "radio modules loaded: brcmfmac"),
    )
    fb = _fb()
    s.draw(fb)


def test_draw_does_not_raise_on_inconclusive_report() -> None:
    s = _make_screen(
        CheckResult("modules", None, "/proc/modules unavailable"),
        CheckResult("rfkill", None, "rfkill unavailable"),
    )
    fb = _fb()
    s.draw(fb)


def test_rows_use_wifi_bluetooth_network_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        CheckResult("wifi", True, "ok"),
        CheckResult("bluetooth", True, "ok"),
        CheckResult("network", True, "ok"),
    )
    monkeypatch.setattr(
        "piwallet.bonnet.airgap_screen.checks_for_bonnet_display",
        lambda: rows,
    )
    s = _make_screen(CheckResult("modules", True, "ok"))
    assert [c.display_name for c in s._rows()] == [
        "Wi-Fi",
        "Bluetooth",
        "Network",
    ]
