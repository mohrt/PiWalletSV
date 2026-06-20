"""Picamera2 session for entropy: TFT preview + JPEG capture on A.

Uses preview-mode ``capture_array`` + PIL JPEG encoding — the same path
as :func:`piwallet.bonnet.camera_still.capture_still_jpeg_bytes` and
``scripts/camera_qr_test.py`` (factory smoke). Avoids still-mode
``capture_file`` / ``switch_mode_and_capture_file``, which fail on some
OV5647 + systemd-hardened bonnet setups.
"""

from __future__ import annotations

import io
import logging
import time
from contextlib import suppress

from PIL import Image

from piwallet.bonnet.camera_sizes import capture_sizes_for_machine
from piwallet.bonnet.camera_still import _camera_unavailable
from piwallet.camera_lcd import PIWALLET_CAMERA_ROTATION_DEG, rotate_rgb888

log = logging.getLogger(__name__)


def _preview_sizes_for_machine() -> list[tuple[int, int]]:
    return capture_sizes_for_machine()


class EntropyDualStreamCamera:
    """Single preview stream for bonnet photo entropy (OV5647 / Pi Zero W)."""

    def __init__(
        self,
        *,
        preview_settle_s: float = 0.5,
        jpeg_quality: int = 85,
    ) -> None:
        self._preview_settle_s = preview_settle_s
        self._jpeg_quality = jpeg_quality
        self._cam = None
        self._preview_size: tuple[int, int] | None = None

    def open(self) -> None:
        if self._cam is not None:
            return

        from piwallet.runtime_logging import prepare_runtime_for_cli_camera_scan

        prepare_runtime_for_cli_camera_scan()

        try:
            from picamera2 import Picamera2  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "picamera2/libcamera missing. On Raspberry Pi OS: "
                "`sudo apt install -y python3-picamera2` and use a venv with "
                "`--system-site-packages`.",
            ) from exc

        last_err: BaseException | None = None
        for prev_sz in _preview_sizes_for_machine():
            picam = None
            try:
                info = Picamera2.global_camera_info()
                if not info:
                    raise RuntimeError(
                        "libcamera sees 0 cameras — check ribbon, reboot, "
                        "and config.txt (sealed default: camera_auto_detect=1)."
                    )
                try:
                    picam = Picamera2()
                except IndexError as exc:
                    raise _camera_unavailable(exc) from exc
                picam.configure(
                    picam.create_preview_configuration(
                        main={"format": "RGB888", "size": prev_sz},
                    ),
                )
                picam.start()
                time.sleep(max(0.0, float(self._preview_settle_s)))
                self._cam = picam
                self._preview_size = prev_sz
                log.info("entropy camera: preview RGB888 size=%s", prev_sz)
                return
            except Exception as exc:
                last_err = exc
                log.debug("entropy camera preview=%s failed: %s", prev_sz, exc)
                if picam is not None:
                    with suppress(Exception):
                        picam.stop()
                    with suppress(Exception):
                        picam.close()

        msg = (
            "could not configure Pi camera for entropy preview."
            if last_err is None
            else f"{last_err!s}"
        )
        raise RuntimeError(msg) from last_err

    def read_preview_rgb(self):
        """Return an RGB ndarray for TFT thumbnailing."""
        if self._cam is None:
            raise RuntimeError("camera not opened")
        try:
            raw = self._cam.capture_array("main")
        except IndexError as exc:
            raise _camera_unavailable(exc) from exc
        return rotate_rgb888(raw, PIWALLET_CAMERA_ROTATION_DEG)

    def read_lores_rgb(self):
        """Backward-compatible alias (:func:`read_preview_rgb`)."""
        return self.read_preview_rgb()

    def capture_entropy_jpeg(self) -> bytes:
        """JPEG bytes hashed for mnemonic entropy (fresh frame on A)."""
        if self._cam is None:
            raise RuntimeError("camera not opened")
        frame = self.read_preview_rgb()
        buf = io.BytesIO()
        try:
            Image.fromarray(frame).save(buf, format="JPEG", quality=self._jpeg_quality)
            blob = buf.getvalue()
        finally:
            del frame
        if not blob:
            raise RuntimeError("empty JPEG after capture_array encode")
        return blob

    def close(self) -> None:
        if self._cam is None:
            return
        picam = self._cam
        self._cam = None
        self._preview_size = None
        with suppress(Exception):
            picam.stop()
        with suppress(Exception):
            picam.close()
