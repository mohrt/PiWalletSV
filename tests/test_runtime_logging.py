"""Runtime logging defaults."""

from __future__ import annotations

import logging
import os

import pytest

import piwallet.runtime_logging as rl


@pytest.fixture(autouse=True)
def restore_root_log_level() -> None:
    root = logging.getLogger()
    before = root.level
    yield
    root.setLevel(before)


@pytest.fixture(autouse=True)
def clear_log_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "LIBCAMERA_LOG_LEVELS",
        "PICAMERA2_LOG_LEVEL",
        "PIWALLET_LOG_LEVEL",
    ):
        monkeypatch.delenv(k, raising=False)


def test_sets_libcamera_when_unset() -> None:
    rl.prepare_runtime_for_cli_camera_scan()
    assert "*:WARN" in os.environ.get("LIBCAMERA_LOG_LEVELS", "")


def test_respects_preset_libcamera(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBCAMERA_LOG_LEVELS", "*:DEBUG")
    rl.prepare_runtime_for_bonnet()
    assert os.environ.get("LIBCAMERA_LOG_LEVELS") == "*:DEBUG"


def test_pi_wallet_log_level_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIWALLET_LOG_LEVEL", "DEBUG")
    rl.prepare_runtime_for_bonnet()
    assert logging.getLogger().level == logging.DEBUG
