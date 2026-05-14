"""Photo entropy screen: TFT preview hooks (fake camera; no Picamera2)."""

from __future__ import annotations

from io import BytesIO
from typing import Any, ClassVar

import numpy as np
from PIL import Image

from piwallet.bonnet.entropy_screens import CameraEntropyScreen
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def tiny_jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 12), color=(120, 50, 200)).save(buf, format="JPEG")
    return buf.getvalue()


class FakeEntropyCam:
    def __init__(self) -> None:
        self.closed = False

    def open(self) -> None:
        return

    def read_preview_rgb(self):
        img = np.zeros((24, 32, 3), dtype=np.uint8)
        img[:, :, 1] = 200
        return img

    def read_lores_rgb(self):
        return self.read_preview_rgb()

    def capture_entropy_jpeg(self) -> bytes:
        return tiny_jpeg()

    def close(self) -> None:
        self.closed = True


class TrackCam(FakeEntropyCam):
    constructed: ClassVar[list[Any]] = []

    def __init__(self) -> None:
        super().__init__()
        TrackCam.constructed.append(self)


def test_camera_entropy_thumb_updates_on_draw() -> None:
    screen = CameraEntropyScreen(camera_cls=FakeEntropyCam)
    fb = FrameBuffer()
    screen.draw(fb)
    assert screen._cached_thumb is not None


def test_camera_entropy_capture_closes_camera() -> None:
    TrackCam.constructed.clear()
    screen = CameraEntropyScreen(camera_cls=TrackCam)
    fb = FrameBuffer()
    screen.draw(fb)
    assert len(TrackCam.constructed) == 1
    cam = TrackCam.constructed[0]
    screen.on_event(Event(button=Button.A, kind=EventKind.PRESS, at_ms=0))
    assert screen.done
    assert screen.result == tiny_jpeg()
    assert cam.closed


def test_camera_entropy_short_b_press_cancels_and_closes_camera() -> None:
    """B (short tap) cancels the photo-entropy capture and frees the camera.

    Long-hold-B already cancelled; this guards the parity behavior so
    operators don't have to remember which press length backs out.
    """
    TrackCam.constructed.clear()
    screen = CameraEntropyScreen(camera_cls=TrackCam)
    fb = FrameBuffer()
    screen.draw(fb)
    cam = TrackCam.constructed[0]
    screen.on_event(Event(button=Button.B, kind=EventKind.PRESS, at_ms=0))
    assert screen.done
    assert screen.result is None
    assert cam.closed


def test_camera_entropy_long_b_press_cancels_and_closes_camera() -> None:
    TrackCam.constructed.clear()
    screen = CameraEntropyScreen(camera_cls=TrackCam)
    fb = FrameBuffer()
    screen.draw(fb)
    cam = TrackCam.constructed[0]
    screen.on_event(Event(button=Button.B, kind=EventKind.LONG, at_ms=0))
    assert screen.done
    assert screen.result is None
    assert cam.closed
