"""CLI tests for ``piwallet diag``.

We don't run the live system data sources here — we monkeypatch
``check_airgap`` to return synthetic reports so the test exercises the
CLI's *output formatting* and *exit codes*, not the underlying check
logic (which has its own unit tests in ``tests/test_diag_airgap.py``).
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from piwallet.cli import main
from piwallet.diag import airgap as ag


def _make_report(*checks: ag.CheckResult) -> ag.AirgapReport:
    return ag.AirgapReport(checks=checks)


def test_diag_airgap_pass_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    rep = _make_report(
        ag.CheckResult("modules", True, "no radio modules loaded"),
        ag.CheckResult("rfkill", True, "2 radio(s) blocked"),
    )
    # Patch on the module the CLI imports from.
    monkeypatch.setattr(
        "piwallet.diag.airgap.check_airgap", lambda: rep
    )

    runner = CliRunner()
    res = runner.invoke(main, ["diag", "airgap"])

    assert res.exit_code == 0, res.output
    assert "PASS" in res.output
    assert "air-gapped" in res.output
    assert "modules" in res.output
    assert "rfkill" in res.output


def test_diag_airgap_fail_exits_nonzero_with_breach_headline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rep = _make_report(
        ag.CheckResult("modules", False, "radio modules loaded: brcmfmac"),
    )
    monkeypatch.setattr(
        "piwallet.diag.airgap.check_airgap", lambda: rep
    )

    runner = CliRunner()
    res = runner.invoke(main, ["diag", "airgap"])

    assert res.exit_code == 1, res.output
    assert "FAIL" in res.output
    assert "BREACH" in res.output
    assert "brcmfmac" in res.output


def test_diag_airgap_inconclusive_count_is_called_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rep = _make_report(
        ag.CheckResult("modules", True, "no radio modules loaded"),
        ag.CheckResult("rfkill", None, "/sys/class/rfkill unavailable"),
        ag.CheckResult("services", None, "systemctl unavailable"),
    )
    monkeypatch.setattr(
        "piwallet.diag.airgap.check_airgap", lambda: rep
    )

    runner = CliRunner()
    res = runner.invoke(main, ["diag", "airgap"])

    # An all-pass-or-inconclusive report is still PASS (no conclusive failures).
    assert res.exit_code == 0, res.output
    assert "PASS" in res.output
    assert "2 check(s) inconclusive" in res.output


def test_diag_airgap_json_output_round_trips_with_to_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rep = _make_report(
        ag.CheckResult("modules", True, "no radio modules loaded"),
        ag.CheckResult("rfkill", False, "unblocked: phy0"),
    )
    monkeypatch.setattr(
        "piwallet.diag.airgap.check_airgap", lambda: rep
    )

    runner = CliRunner()
    res = runner.invoke(main, ["diag", "airgap", "--json"])

    # rfkill failed → exit 1 even with --json.
    assert res.exit_code == 1, res.output
    payload = json.loads(res.output)
    assert payload == rep.to_dict()


def test_diag_airgap_help_lists_under_main(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    res = runner.invoke(main, ["--help"])
    assert res.exit_code == 0
    assert "diag" in res.output

    res = runner.invoke(main, ["diag", "--help"])
    assert res.exit_code == 0
    assert "airgap" in res.output
    assert "camera" in res.output


def test_diag_camera_pass_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "piwallet.bonnet.camera_still.capture_still_jpeg_bytes",
        lambda **_: b"\xff\xd8fake",
    )
    runner = CliRunner()
    res = runner.invoke(main, ["diag", "camera"])
    assert res.exit_code == 0, res.output
    assert "PASS" in res.output
    assert "byte JPEG" in res.output


def test_diag_camera_fail_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**_: object) -> bytes:
        raise RuntimeError("no sensor")

    monkeypatch.setattr("piwallet.bonnet.camera_still.capture_still_jpeg_bytes", _boom)
    runner = CliRunner()
    res = runner.invoke(main, ["diag", "camera"])
    assert res.exit_code == 1, res.output
    assert "FAIL" in res.output
    assert "no sensor" in res.output
