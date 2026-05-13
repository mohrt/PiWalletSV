"""Picamera2 session for entropy: TFT preview (low rate) + full-res JPEG from A.

Process defaults for libcamera/picamera2 stderr are applied in :mod:`piwallet.runtime_logging`
(bonnet + CLI camera scan entry points). systemd journal sizing: ``deploy/systemd/``.
"""

from __future__ import annotations

import io
import logging
import tempfile
import time
from contextlib import suppress
from pathlib import Path

log = logging.getLogger(__name__)

# Full-res still used for mnemonic hashing when still-capture succeeds.
_ENTROPY_STILL_DEFAULT: tuple[int, int] = (1280, 960)

# --- Size attempts (order matters) ------------------------------------------
# IMX708 / Pi Camera Module 3 on vc4 usually rejects main+lores for our presets; that
# wasted three Picamera2 cycles and libcamera spammed startup. Try preview+still first.
_PREVIEW_STILL_FALLBACK_SIZES: list[tuple[int, int]] = [
    (640, 480),
    (480, 360),
    (416, 312),
]

# Dual stream: small lores pulls for TFT when the pipeline allows it.
_DUAL_PRESETS: list[tuple[tuple[int, int], tuple[int, int]]] = [
    ((1280, 960), (320, 240)),
    ((640, 480), (320, 240)),
    ((960, 720), (480, 360)),
]


class EntropyDualStreamCamera:
    """Bonnet entropy camera (Picamera2).

    **Preview+still** mode is tried first: a low-res ``main`` RGB888 stream for the TFT,
    then ``switch_mode_and_capture_file`` for a full **still** JPEG when the user presses **A**.

    If that fails on odd hardware, **dual** ``main``+``lores`` is attempted (smaller lores
    reads for preview when supported).
    """

    def __init__(
        self,
        *,
        still_size: tuple[int, int] = _ENTROPY_STILL_DEFAULT,
        autofocus_continuous: bool = True,
        preview_settle_s: float = 0.5,
        jpeg_quality: int = 85,
    ) -> None:
        self._still_size = still_size
        self._autofocus_continuous = autofocus_continuous
        self._preview_settle_s = preview_settle_s
        self._jpeg_quality = jpeg_quality
        self._cam = None
        self._mode: str | None = None  # "dual" | "preview_still"

    def open(self) -> None:
        if self._cam is not None:
            return
        try:
            # Local import validates availability with a single error surface.
            from libcamera import controls  # type: ignore[import-not-found]
            from picamera2 import Picamera2  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "picamera2/libcamera missing. On Raspberry Pi OS: "
                "`sudo apt install -y python3-picamera2` and use a venv with "
                "`--system-site-packages`.",
            ) from exc

        last_err: BaseException | None = None

        # --- 1) Preview + still (typical rpi/vc4 + IMX708 path) ---------------
        for prev_sz in _PREVIEW_STILL_FALLBACK_SIZES:
            picam = None
            try:
                picam = Picamera2()
                picam.configure(
                    picam.create_preview_configuration(
                        main={"format": "RGB888", "size": prev_sz},
                    ),
                )
                picam.start()
                self._apply_af(picam, controls)
                time.sleep(max(0.0, float(self._preview_settle_s)))
                self._cam = picam
                self._mode = "preview_still"
                log.info(
                    "entropy camera: preview+still preview=%s still=%s",
                    prev_sz,
                    self._still_size,
                )
                return
            except Exception as exc:
                last_err = exc
                log.debug("preview-still entropy cam preview=%s failed: %s", prev_sz, exc)
                if picam is not None:
                    with suppress(Exception):
                        picam.stop()
                    with suppress(Exception):
                        picam.close()

        # --- 2) Dual-stream (lores preview when supported) -------------------
        for main_sz, lores_sz in _DUAL_PRESETS:
            picam = None
            try:
                picam = Picamera2()
                picam.configure(
                    picam.create_preview_configuration(
                        main={"format": "RGB888", "size": main_sz},
                        lores={"format": "RGB888", "size": lores_sz},
                    )
                )
                picam.start()
                self._apply_af(picam, controls)
                time.sleep(max(0.0, float(self._preview_settle_s)))
                self._cam = picam
                self._mode = "dual"
                log.info(
                    "entropy camera: dual stream main=%s lores=%s",
                    main_sz,
                    lores_sz,
                )
                return
            except Exception as exc:
                last_err = exc
                log.debug("dual entropy cam main=%s lores=%s failed: %s", main_sz, lores_sz, exc)
                if picam is not None:
                    with suppress(Exception):
                        picam.stop()
                    with suppress(Exception):
                        picam.close()

        msg = (
            "could not configure Pi camera for entropy (preview+still or dual)."
            if last_err is None
            else f"{last_err!s}"
        )
        raise RuntimeError(msg) from last_err

    def _apply_af(self, picam: object, controls_mod: object) -> None:
        if not self._autofocus_continuous:
            return
        try:
            picam.set_controls({"AfMode": controls_mod.AfModeEnum.Continuous})  # type: ignore[attr-defined]
        except Exception as exc:
            log.debug("continuous AF not applied: %s", exc)

    def read_preview_rgb(self):
        """Return an RGB ndarray for TFT thumbnailing (~lores size or preview main size)."""
        if self._cam is None:
            raise RuntimeError("camera not opened")
        if self._mode == "dual":
            return self._cam.capture_array("lores")
        if self._mode == "preview_still":
            return self._cam.capture_array("main")
        raise RuntimeError("camera mode unset")

    def read_lores_rgb(self):
        """Backward-compatible alias (:func:`read_preview_rgb`)."""
        return self.read_preview_rgb()

    def capture_entropy_jpeg(self) -> bytes:
        """Full-resolution JPEG hashed for mnemonic entropy."""
        if self._cam is None:
            raise RuntimeError("camera not opened")
        with suppress(KeyError, TypeError, AttributeError):
            self._cam.options["quality"] = int(self._jpeg_quality)  # type: ignore[index]

        if self._mode == "dual":
            buf = io.BytesIO()
            self._cam.capture_file(buf, format="jpeg")
            blob = buf.getvalue()
            if not blob:
                raise RuntimeError("empty JPEG from camera main stream")
            return blob

        if self._mode == "preview_still":
            still_cfg = self._cam.create_still_configuration(main={"size": self._still_size})
            suffix = ".jpg"
            tmp = tempfile.NamedTemporaryFile(
                prefix="piwallet-entropy-", suffix=suffix, delete=False
            )
            path_str = tmp.name
            tmp.close()
            path = Path(path_str)
            try:
                self._cam.switch_mode_and_capture_file(still_cfg, path_str, format="jpeg")
                blob = path.read_bytes()
            finally:
                with suppress(Exception):
                    path.unlink(missing_ok=True)
            if not blob:
                raise RuntimeError("empty JPEG from still capture")
            return blob

        raise RuntimeError("camera mode unset")

    def close(self) -> None:
        if self._cam is None:
            return
        picam = self._cam
        self._cam = None
        self._mode = None
        with suppress(Exception):
            picam.stop()
        with suppress(Exception):
            picam.close()
