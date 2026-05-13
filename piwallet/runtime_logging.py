"""Defaults for constrained logging on the Pi (journal + SD longevity).

Bonnet/TV-style apps run under systemd: stderr lands in the journal. libcamera
emits INFO lines to stderr unless ``LIBCAMERA_LOG_LEVELS`` is set.

We do **not** add rotating log files inside the vault tree; bounded journal size is handled
via ``deploy/systemd`` journald drop-ins.
"""

from __future__ import annotations

import logging
import os


def apply_pi_camera_stderr_defaults(*, vendor_max: str = "WARN") -> None:
    """If unset, clamp libcamera (and picamera2 env) chatter on stderr.

    ``vendor_max`` is the libcamera severity token (``WARN``, ``ERROR``, …).
    Export ``LIBCAMERA_LOG_LEVELS`` yourself to override.
    """
    if os.environ.get("LIBCAMERA_LOG_LEVELS") is None:
        os.environ["LIBCAMERA_LOG_LEVELS"] = f"*:{vendor_max}"

    # Picamera2 numeric console verbosity (default 0); higher = more chatter.
    if not os.environ.get("PICAMERA2_LOG_LEVEL", "").strip():
        os.environ["PICAMERA2_LOG_LEVEL"] = "0"


def apply_app_python_logging(level: int = logging.WARNING) -> None:
    """Raise the root threshold so INFO from dependencies does not bloat journald.

    Override with ``PIWALLET_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR``.
    """
    env = os.environ.get("PIWALLET_LOG_LEVEL", "").strip().upper()
    name_to_level = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    if env in name_to_level:
        level = name_to_level[env]

    logging.getLogger().setLevel(level)
    for name in ("picamera2", "libcamera"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))


def prepare_runtime_for_bonnet(*, vendor_log_max: str = "WARN") -> None:
    """Call early in ``run_bonnet()`` before Picamera2 or noisy imports."""
    apply_pi_camera_stderr_defaults(vendor_max=vendor_log_max)
    apply_app_python_logging()


def prepare_runtime_for_cli_camera_scan(*, vendor_log_max: str = "WARN") -> None:
    """Call at start of QR camera-scan paths (CLI or future bonnet scanner)."""
    apply_pi_camera_stderr_defaults(vendor_max=vendor_log_max)
    apply_app_python_logging()
