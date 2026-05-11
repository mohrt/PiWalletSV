"""Camera capture loop that feeds decoded QR strings into a :class:`MultipartAssembler`.

Requires optional dependencies: **system** ``python3-picamera2`` / libcamera on
the Pi, plus **venv** ``pyzbar`` and **system** ``libzbar0t64`` (or
``libzbar0``). On a Mac during development this module is unavailable unless
you install compatible camera bindings; unit tests use ``MultipartAssembler``
only.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING

from piwallet.qr.multipart import MultipartAssembler, MultipartQrError

if TYPE_CHECKING:
    from pyzbar.pyzbar import Decoded  # noqa: F401

ProgressCallback = Callable[[int, str], None]
"""(parts_received, status_message) — for CLI/progress display."""


def _import_camera_stack() -> tuple[type, object]:
    try:
        from libcamera import controls
        from picamera2 import Picamera2
    except ImportError as exc:
        raise RuntimeError(
            "picamera2/libcamera not installed. On Raspberry Pi OS: "
            "`sudo apt install -y python3-picamera2` and use a venv with "
            "`--system-site-packages`, or run this command on the Pi only."
        ) from exc
    return Picamera2, controls


def _import_pyzbar_decode():
    try:
        from pyzbar.pyzbar import decode
    except ImportError as exc:
        raise RuntimeError(
            "pyzbar missing. Install in the active venv: `pip install pyzbar` "
            "and system lib: `sudo apt install -y libzbar0t64`"
        ) from exc
    return decode


def configure_autofocus(cam, controls_mod, mode: str = "continuous") -> None:
    af_map = {
        "continuous": controls_mod.AfModeEnum.Continuous,
        "auto": controls_mod.AfModeEnum.Auto,
        "manual": controls_mod.AfModeEnum.Manual,
    }
    try:
        cam.set_controls({"AfMode": af_map[mode]})
    except Exception as exc:
        print(f"  (AfMode={mode} not supported: {exc})", file=sys.stderr)


def scan_multipart_from_camera(
    assembler: MultipartAssembler | None = None,
    *,
    size: str = "1280x960",
    interval_s: float = 0.35,
    autofocus: str = "continuous",
    settle_s: float = 1.0,
    on_progress: ProgressCallback | None = None,
) -> bytes:
    """Block until all PW1 QR fragments are seen, then return assembled bytes.

    Press Ctrl+C to abort. Raises :class:`MultipartQrError` on conflicting
    fragments. Propagates ``RuntimeError`` when camera or pyzbar is missing.
    """
    picamera_cls, controls_mod = _import_camera_stack()
    decode = _import_pyzbar_decode()

    asm = assembler if assembler is not None else MultipartAssembler()
    w, h = _parse_size(size)

    cam = picamera_cls()
    cam.configure(cam.create_still_configuration(main={"size": (w, h)}))
    cam.start()
    configure_autofocus(cam, controls_mod, autofocus)
    time.sleep(settle_s)

    frame_no = 0
    try:
        while True:
            frame_no += 1
            frame = cam.capture_array("main")
            results = decode(frame)
            if not results:
                if on_progress:
                    on_progress(asm.parts_received, f"frame {frame_no}: no QR")
                time.sleep(interval_s)
                continue

            for r in results:
                text = r.data.decode("utf-8", errors="strict")
                if not text.startswith("PW1|"):
                    continue
                try:
                    done = asm.feed(text)
                except MultipartQrError:
                    cam.close()
                    raise
                total = asm.expected_total or 0
                have = asm.parts_received if asm.expected_total else 0
                msg = f"fragment {have}/{total}" if total else "fragment"
                if on_progress:
                    on_progress(have, msg)
                if done is not None:
                    return done

            time.sleep(interval_s)
    finally:
        with suppress(Exception):
            cam.close()


def _parse_size(spec: str) -> tuple[int, int]:
    try:
        w_s, h_s = spec.lower().split("x")
        return int(w_s), int(h_s)
    except ValueError as exc:
        raise ValueError(f"bad --size '{spec}', expected WxH") from exc
