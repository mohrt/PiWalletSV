"""Bonnet camera capture size selection per SoC."""

from __future__ import annotations

from piwallet.bonnet.camera_sizes import bonnet_live_preview_enabled, capture_sizes_for_machine


def test_capture_sizes_armv6(monkeypatch) -> None:
    monkeypatch.setattr("piwallet.bonnet.camera_sizes.platform.machine", lambda: "armv6l")
    assert capture_sizes_for_machine() == [(640, 480), (480, 360), (416, 312)]


def test_capture_sizes_default(monkeypatch) -> None:
    monkeypatch.setattr("piwallet.bonnet.camera_sizes.platform.machine", lambda: "aarch64")
    assert capture_sizes_for_machine()[0] == (1280, 960)


def test_live_preview_enabled_on_armv6(monkeypatch) -> None:
    monkeypatch.setattr("piwallet.bonnet.camera_sizes.platform.machine", lambda: "armv6l")
    assert bonnet_live_preview_enabled() is True
