"""Grab a single still frame from Picamera2 for entropy mixing.

Separate from QR scanning: no pyzbar, just raw sensor bytes hashed by
:mod:`piwallet.core.mnemonic`.

Uses the same preview-mode + ``capture_array`` path as
``scripts/camera_qr_test.py`` (factory smoke). Still-mode ``capture_file``
is less reliable on OV5647 and can fail inside the hardened bonnet unit.
"""

from __future__ import annotations

import io
import logging
import time

from PIL import Image

log = logging.getLogger(__name__)


def _camera_unavailable(exc: BaseException) -> RuntimeError:
    return RuntimeError(
        "Pi camera not available. Check ribbon cable and that /dev/video0 "
        "is readable by the bonnet user (video group). "
        f"Detail: {exc}"
    )


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
    from piwallet.runtime_logging import prepare_runtime_for_cli_camera_scan

    prepare_runtime_for_cli_camera_scan()

    try:
        from picamera2 import Picamera2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "picamera2/libcamera missing. Install: "
            "`sudo apt install python3-picamera2` and use "
            "`pip install --system-site-packages -e '.[camera]'`.",
        ) from exc

    info = Picamera2.global_camera_info()
    if not info:
        raise RuntimeError(
            "Pi camera not detected (libcamera sees 0 cameras). "
            "On tty2: stop bonnet, run "
            "'sudo -u pwsv rpicam-hello --list-cameras', check ribbon cable, "
            "and verify /boot/firmware/config.txt has "
            "camera_auto_detect=0 and dtoverlay=ov5647."
        )

    try:
        cam = Picamera2()
    except IndexError as exc:
        raise _camera_unavailable(exc) from exc

    try:
        cam.configure(
            cam.create_preview_configuration(
                main={"format": "RGB888", "size": (width, height)},
            ),
        )
        cam.start()
        try:
            time.sleep(settle_s)
        except Exception as exc:  # pragma: no cover (interrupted sleep is rare)
            log.debug("capture_still: settle sleep interrupted: %s", exc)
        try:
            frame = cam.capture_array("main")
        except IndexError as exc:
            raise _camera_unavailable(exc) from exc
        buf = io.BytesIO()
        Image.fromarray(frame).save(buf, format="JPEG", quality=quality)
        blob = buf.getvalue()
        if not blob:
            raise RuntimeError("empty JPEG after capture_array encode")
        return blob
    finally:
        try:
            cam.stop()
            cam.close()
        except Exception as exc:  # pragma: no cover (best-effort cleanup)
            log.warning("capture_still: cleanup failed: %s", exc)
