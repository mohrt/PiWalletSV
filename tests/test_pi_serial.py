"""Pi board serial reader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.platform import pi_serial


def test_serial_from_cpuinfo_text_parses_serial_line() -> None:
    text = """
Hardware        : BCM2835
Serial          : 10000000a1b2c3d4
"""
    assert pi_serial.serial_from_cpuinfo_text(text) == "10000000a1b2c3d4"


def test_serial_from_cpuinfo_text_ignores_zero_serial() -> None:
    text = "Serial          : 0000000000000000\n"
    assert pi_serial.serial_from_cpuinfo_text(text) is None


def test_read_pi_serial_from_device_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    serial_file = tmp_path / "serial-number"
    serial_file.write_bytes(b"10000000deadbeef\0")
    monkeypatch.setattr(pi_serial, "_DEVICE_TREE_SERIAL", serial_file)
    monkeypatch.setattr(
        pi_serial, "_serial_from_cpuinfo", lambda: None
    )
    assert pi_serial.read_pi_serial() == "10000000DEADBEEF"


def test_read_pi_serial_falls_back_to_cpuinfo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pi_serial, "_serial_from_device_tree", lambda: None)
    monkeypatch.setattr(
        pi_serial,
        "_serial_from_cpuinfo",
        lambda: "10000000a1b2c3d4",
    )
    assert pi_serial.read_pi_serial() == "10000000A1B2C3D4"
