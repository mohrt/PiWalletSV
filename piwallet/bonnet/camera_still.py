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

from piwallet.bonnet.camera_sizes import capture_sizes_for_machine
from piwallet.camera_lcd import PIWALLET_CAMERA_ROTATION_DEG, rotate_rgb888

log = logging.getLogger(__name__)


def _camera_unavailable(exc: BaseException) -> RuntimeError:
    return RuntimeError(
        "Pi camera not available. Check ribbon cable and that /dev/video0 "
        "is readable by the bonnet user (video group). "
        f"Detail: {exc}"
    )


def capture_still_jpeg_bytes(
    *,
    width: int | None = None,
    height: int | None = None,
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
            "Stop bonnet, re-seat the ribbon cable, reboot once, then run "
            "'sudo bash deploy/scripts/diag-camera-offline.sh'. "
            "Sealed images use camera_auto_detect=1; for DIY modules without "
            "EEPROM, set camera_auto_detect=0 and dtoverlay=ov5647 in config.txt."
        )

    if width is not None and height is not None:
        sizes = [(width, height)]
    else:
        sizes = capture_sizes_for_machine()

    last_err: BaseException | None = None
    for w, h in sizes:
        picam = None
        try:
            try:
                picam = Picamera2()
            except IndexError as exc:
                raise _camera_unavailable(exc) from exc
            picam.configure(
                picam.create_preview_configuration(
                    main={"format": "RGB888", "size": (w, h)},
                ),
            )
            picam.start()
            try:
                time.sleep(settle_s)
            except Exception as exc:  # pragma: no cover
                log.debug("capture_still: settle sleep interrupted: %s", exc)
            try:
                frame = picam.capture_array("main")
            except IndexError as exc:
                raise _camera_unavailable(exc) from exc
            frame = rotate_rgb888(frame, PIWALLET_CAMERA_ROTATION_DEG)
            buf = io.BytesIO()
            Image.fromarray(frame).save(buf, format="JPEG", quality=quality)
            blob = buf.getvalue()
            if not blob:
                raise RuntimeError("empty JPEG after capture_array encode")
            log.info("capture_still: JPEG %d bytes at %dx%d", len(blob), w, h)
            return blob
        except Exception as exc:
            last_err = exc
            log.debug("capture_still: size=%dx%d failed: %s", w, h, exc)
        finally:
            if picam is not None:
                try:
                    picam.stop()
                    picam.close()
                except Exception as exc:  # pragma: no cover
                    log.warning("capture_still: cleanup failed: %s", exc)

    msg = "could not capture camera still"
    if last_err is not None:
        msg = f"{msg}: {last_err}"
    raise RuntimeError(msg) from last_err
