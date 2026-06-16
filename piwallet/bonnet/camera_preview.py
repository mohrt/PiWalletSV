"""Live camera preview for bonnet hardware tests (no QR decode)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from PIL import Image

from piwallet.camera_lcd import rgb888_thumbnail, rotate_rgb888
from piwallet.qr.camera_scan import _import_camera_stack, _parse_size


@dataclass
class CameraPreviewState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    latest_thumb: Image.Image | None = None
    error: str | None = None
    finished: bool = False
    cancel_requested: bool = False


def start_camera_preview_worker(
    state: CameraPreviewState,
    *,
    size: str = "640x480",
    interval_s: float = 0.15,
) -> None:
    """Spawn a daemon thread that feeds ``state.latest_thumb`` until cancelled."""

    def run() -> None:
        cam = None
        try:
            picamera_cls = _import_camera_stack()
            w, h = _parse_size(size)
            cam = picamera_cls()
            cam.configure(
                cam.create_preview_configuration(
                    main={"format": "RGB888", "size": (w, h)},
                )
            )
            cam.start()
            time.sleep(0.5)
            while True:
                with state.lock:
                    if state.cancel_requested:
                        break
                frame = rotate_rgb888(cam.capture_array("main"))
                thumb = rgb888_thumbnail(frame, max_edge=208)
                with state.lock:
                    state.latest_thumb = thumb
                time.sleep(interval_s)
        except Exception as exc:
            with state.lock:
                state.error = str(exc)
        finally:
            if cam is not None:
                try:
                    cam.close()
                except Exception:
                    pass
            with state.lock:
                state.finished = True

    threading.Thread(target=run, name="piwallet-cam-preview", daemon=True).start()
