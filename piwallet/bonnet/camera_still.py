"""Grab a single still frame from Picamera2 for entropy mixing.

Separate from QR scanning: no pyzbar, just raw sensor bytes hashed by
:mod:`piwallet.core.mnemonic`.

The bonnet preview flow (:class:`~piwallet.bonnet.entropy_camera.EntropyDualStreamCamera`)
keeps ``main`` full-res for hashing while ``lores`` feeds the TFT thumbnail
— this module captures one **main-stream** JPEG in a disposable session.
"""

from __future__ import annotations

import io
import logging
import time
from typing import BinaryIO

log = logging.getLogger(__name__)


def capture_still_jpeg_bytes(
    *,
    width: int = 1280,
    height: int = 960,
    settle_s: float = 0.75,
    quality: int = 85,
) -> bytes:
    """Capture one JPEG still; return bytes fed to mnemonic entropy mixing.

    Raises ``RuntimeError`` if picamera2 is unavailable or capture fails.

    Blocking call — runs on-device only.
    """
    try:
        from picamera2 import Picamera2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "picamera2/libcamera missing. Install: "
            "`sudo apt install python3-picamera2` and use "
            "`pip install --system-site-packages -e '.[camera]'`.",
        ) from exc

    cam = Picamera2()
    try:
        cam.configure(
            cam.create_still_configuration(main={"size": (width, height)}),
        )
        cam.start()
        try:
            time.sleep(settle_s)
        except Exception as exc:  # pragma: no cover (interrupted sleep is rare)
            log.debug("capture_still: settle sleep interrupted: %s", exc)
        try:
            cam.options["quality"] = quality  # type: ignore[index]
        except Exception as exc:  # some picamera2 versions lack writable options
            log.debug("capture_still: cannot set jpeg quality option: %s", exc)
        buf: BinaryIO = io.BytesIO()
        cam.capture_file(buf, format="jpeg")
        return buf.getvalue()
    finally:
        try:
            cam.stop()
            cam.close()
        except Exception as exc:  # pragma: no cover (best-effort cleanup)
            log.warning("capture_still: cleanup failed: %s", exc)
