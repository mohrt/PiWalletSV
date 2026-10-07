"""Pro image filename and the panel firmware the provisioner installs."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ST7796S_SHA256 = "17204e39cce35fba857ad2dff14243e1d3a958c4dac00283f8df9b7ad5147cc7"


def test_st7796s_firmware_matches_waveshare_init_blob() -> None:
    blob = (REPO_ROOT / "deploy" / "firmware" / "st7796s.bin").read_bytes()
    assert hashlib.sha256(blob).hexdigest() == ST7796S_SHA256
    assert len(blob) == 117


def test_capture_accepts_pro_pi3_board() -> None:
    proc = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "capture-sd-image.sh"),
            "--version",
            "0.1.0-r1",
            "--board",
            "pro-pi3",
            "--maturity",
            "beta",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "device path required" in proc.stderr
    assert "must be" not in proc.stderr


def test_capture_rejects_an_unknown_board() -> None:
    proc = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "capture-sd-image.sh"),
            "--version",
            "0.1.0-r1",
            "--board",
            "pi3",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "pro-pi3" in proc.stderr


def test_pro_provisioner_keeps_the_working_panel_lines() -> None:
    text = (REPO_ROOT / "deploy" / "provision-pi.sh").read_text(encoding="utf-8")
    assert "--product pro" in text or "product == \"pro\"" in text
    assert "dtoverlay=mipi-dbi-spi,speed=48000000" in text
    assert r"dtparam=compatible=st7796s\0panel-mipi-dbi-spi" in text
    assert "dtoverlay=goodix,addr=0x5d" in text
    unit = (REPO_ROOT / "deploy" / "systemd" / "piwallet-touch.service").read_text(
        encoding="utf-8"
    )
    assert "piwallet touch --device pi3-ws35f" in unit
    assert "ExecStartPre=+/usr/local/sbin/piwallet-panel-on" in unit
    rules = (REPO_ROOT / "deploy" / "udev" / "99-piwallet-hardware.rules").read_text(
        encoding="utf-8"
    )
    assert "/usr/local/sbin/piwallet-panel-on" in rules
    panel_on = (REPO_ROOT / "deploy" / "piwallet-panel-on").read_text(encoding="utf-8")
    assert "panel-mipi-dbi" in panel_on
    assert "max_brightness" in panel_on
    assert "Waveshare35f" in text
