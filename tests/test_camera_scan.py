"""Unit tests for piwallet/qr/camera_scan.py.

All camera hardware (``picamera2``, ``libcamera``, ``pyzbar``) and
``time.sleep`` are replaced with lightweight stubs so the tests run on
any platform without Pi-specific packages.
"""

from __future__ import annotations

import types
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from piwallet.qr.camera_scan import (
    ScanCancelled,
    _parse_size,
    configure_autofocus,
    scan_multipart_from_camera,
)
from piwallet.qr.multipart import MultipartAssembler, split_envelope_to_lines


# ---------------------------------------------------------------------------
# Helpers to build fake QR data
# ---------------------------------------------------------------------------


def _make_lines(payload: bytes, max_chars: int = 200) -> list[str]:
    # min allowed by split_envelope_to_lines is 64
    return split_envelope_to_lines(payload, max_encoded_chunk_chars=max(64, max_chars))


def _fake_decoded(text: str) -> MagicMock:
    """Mimic a single pyzbar ``Decoded`` object."""
    d = MagicMock()
    d.data = text.encode("utf-8")
    return d


def _blank_frame() -> np.ndarray:
    return np.zeros((64, 64, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_cam() -> MagicMock:
    cam = MagicMock()
    cam.capture_array.return_value = _blank_frame()
    return cam


@pytest.fixture()
def fake_picamera_cls(fake_cam: MagicMock) -> MagicMock:
    cls = MagicMock(return_value=fake_cam)
    return cls


@pytest.fixture()
def fake_controls() -> types.SimpleNamespace:
    controls = types.SimpleNamespace()
    af = types.SimpleNamespace(
        Continuous="continuous",
        Auto="auto",
        Manual="manual",
    )
    controls.AfModeEnum = af
    return controls


# ---------------------------------------------------------------------------
# _parse_size
# ---------------------------------------------------------------------------


def test_parse_size_valid() -> None:
    assert _parse_size("1280x960") == (1280, 960)
    assert _parse_size("640X480") == (640, 480)


def test_parse_size_invalid() -> None:
    with pytest.raises(ValueError, match="bad --size"):
        _parse_size("1280")
    with pytest.raises(ValueError, match="bad --size"):
        _parse_size("abc x def")


# ---------------------------------------------------------------------------
# configure_autofocus
# ---------------------------------------------------------------------------


def test_configure_autofocus_sets_control(
    fake_cam: MagicMock,
    fake_controls: types.SimpleNamespace,
) -> None:
    configure_autofocus(fake_cam, fake_controls, mode="continuous")
    fake_cam.set_controls.assert_called_once_with({"AfMode": "continuous"})


def test_configure_autofocus_swallows_unsupported(
    fake_cam: MagicMock,
    fake_controls: types.SimpleNamespace,
) -> None:
    fake_cam.set_controls.side_effect = RuntimeError("not supported")
    # Should not raise.
    configure_autofocus(fake_cam, fake_controls, mode="continuous")


# ---------------------------------------------------------------------------
# scan_multipart_from_camera — success paths
# ---------------------------------------------------------------------------


def _make_scan_patches(
    fake_picamera_cls: MagicMock,
    fake_controls: types.SimpleNamespace,
    decode_side_effect: Any,
) -> list[Any]:
    """Return context manager list suitable for multi-patch tests."""
    return [
        patch(
            "piwallet.qr.camera_scan._import_camera_stack",
            return_value=(fake_picamera_cls, fake_controls),
        ),
        patch(
            "piwallet.qr.camera_scan._import_pyzbar_decode",
            return_value=decode_side_effect,
        ),
        patch("piwallet.qr.camera_scan.time.sleep"),
        patch(
            "piwallet.runtime_logging.prepare_runtime_for_cli_camera_scan",
            return_value=None,
        ),
    ]


def _run_with_patches(
    fake_picamera_cls: MagicMock,
    fake_controls: types.SimpleNamespace,
    decode_fn: Any,
    **kwargs: Any,
) -> bytes:
    """Convenience wrapper that applies all patches and calls the function."""
    patches = _make_scan_patches(fake_picamera_cls, fake_controls, decode_fn)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
    ):
        return scan_multipart_from_camera(**kwargs)


def test_scan_single_fragment(
    fake_cam: MagicMock,
    fake_picamera_cls: MagicMock,
    fake_controls: types.SimpleNamespace,
) -> None:
    """A single-fragment payload is assembled and returned."""
    payload = b"hello world test payload"
    lines = _make_lines(payload)
    assert len(lines) == 1

    calls_iter: Iterator[list[MagicMock]] = iter([[_fake_decoded(lines[0])]])

    def decode(frame: Any) -> list[MagicMock]:
        try:
            return next(calls_iter)
        except StopIteration:
            return []

    asm = MultipartAssembler()
    result = _run_with_patches(
        fake_picamera_cls, fake_controls, decode, assembler=asm
    )
    assert result == payload


def test_scan_multi_fragment(
    fake_cam: MagicMock,
    fake_picamera_cls: MagicMock,
    fake_controls: types.SimpleNamespace,
) -> None:
    """All fragments must arrive before the function returns."""
    # Force small chunks so we get multiple parts (min allowed is 64 chars).
    payload = b"x" * 500
    lines = _make_lines(payload, max_chars=80)
    assert len(lines) >= 2

    frame_iter: Iterator[list[MagicMock]] = iter(
        [[_fake_decoded(ln)] for ln in lines]
    )

    def decode(frame: Any) -> list[MagicMock]:
        try:
            return next(frame_iter)
        except StopIteration:
            return []

    asm = MultipartAssembler()
    result = _run_with_patches(
        fake_picamera_cls, fake_controls, decode, assembler=asm
    )
    assert result == payload


def test_scan_skips_non_pw1_qr(
    fake_cam: MagicMock,
    fake_picamera_cls: MagicMock,
    fake_controls: types.SimpleNamespace,
) -> None:
    """QR codes without the PW1| prefix are silently skipped."""
    payload = b"test skip non pw1"
    lines = _make_lines(payload)

    noise = _fake_decoded("https://example.com/irrelevant-qr")
    real = _fake_decoded(lines[0])

    frame_iter: Iterator[list[MagicMock]] = iter([[noise], [real]])

    def decode(frame: Any) -> list[MagicMock]:
        try:
            return next(frame_iter)
        except StopIteration:
            return []

    asm = MultipartAssembler()
    result = _run_with_patches(
        fake_picamera_cls, fake_controls, decode, assembler=asm
    )
    assert result == payload


def test_scan_empty_frames_do_not_crash(
    fake_cam: MagicMock,
    fake_picamera_cls: MagicMock,
    fake_controls: types.SimpleNamespace,
) -> None:
    """Empty decode results just increment the frame counter and continue."""
    payload = b"after blank frames"
    lines = _make_lines(payload)

    frame_iter: Iterator[list[MagicMock]] = iter(
        [[], [], [_fake_decoded(lines[0])]]
    )

    def decode(frame: Any) -> list[MagicMock]:
        try:
            return next(frame_iter)
        except StopIteration:
            return []

    asm = MultipartAssembler()
    result = _run_with_patches(
        fake_picamera_cls, fake_controls, decode, assembler=asm
    )
    assert result == payload


def test_scan_cancel_check_raises_scan_cancelled(
    fake_cam: MagicMock,
    fake_picamera_cls: MagicMock,
    fake_controls: types.SimpleNamespace,
) -> None:
    """When cancel_check() returns True the loop raises ScanCancelled."""
    cancel_after = 2
    frame_count = 0

    def decode(frame: Any) -> list[MagicMock]:
        return []

    def cancel_check() -> bool:
        nonlocal frame_count
        frame_count += 1
        return frame_count > cancel_after

    patches = _make_scan_patches(fake_picamera_cls, fake_controls, decode)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        pytest.raises(ScanCancelled),
    ):
        scan_multipart_from_camera(cancel_check=cancel_check)

    # Camera must still be closed even when we cancel.
    fake_cam.close.assert_called()


def test_scan_on_progress_callback(
    fake_cam: MagicMock,
    fake_picamera_cls: MagicMock,
    fake_controls: types.SimpleNamespace,
) -> None:
    """on_progress is called whenever a PW1 fragment is fed."""
    payload = b"progress test payload"
    lines = _make_lines(payload)

    frame_iter: Iterator[list[MagicMock]] = iter(
        [[_fake_decoded(ln)] for ln in lines]
    )

    def decode(frame: Any) -> list[MagicMock]:
        try:
            return next(frame_iter)
        except StopIteration:
            return []

    progress_calls: list[tuple[int, str]] = []

    def on_progress(count: int, msg: str) -> None:
        progress_calls.append((count, msg))

    asm = MultipartAssembler()
    _run_with_patches(
        fake_picamera_cls, fake_controls, decode,
        assembler=asm, on_progress=on_progress,
    )
    assert len(progress_calls) == len(lines)


def test_scan_camera_closed_on_multipart_error(
    fake_cam: MagicMock,
    fake_picamera_cls: MagicMock,
    fake_controls: types.SimpleNamespace,
) -> None:
    """MultipartQrError from conflicting same-index fragments closes the camera."""
    from piwallet.qr.multipart import MultipartQrError

    # Two PW1 lines that claim to be part 0-of-2 but with different base64 data.
    frag_a = "PW1|2|0|aGVsbG8="    # "hello" encoded
    frag_b = "PW1|2|0|d29ybGQ="    # "world" encoded — same slot, different content

    frame_iter: Iterator[list[MagicMock]] = iter(
        [[_fake_decoded(frag_a)], [_fake_decoded(frag_b)]]
    )

    def decode(frame: Any) -> list[MagicMock]:
        try:
            return next(frame_iter)
        except StopIteration:
            return []

    patches = _make_scan_patches(fake_picamera_cls, fake_controls, decode)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        pytest.raises(MultipartQrError),
    ):
        scan_multipart_from_camera()

    fake_cam.close.assert_called()


# ---------------------------------------------------------------------------
# _import_* error handling
# ---------------------------------------------------------------------------


def test_import_camera_stack_raises_without_picamera2() -> None:
    from piwallet.qr.camera_scan import _import_camera_stack

    with patch.dict("sys.modules", {"picamera2": None, "libcamera": None}):
        with pytest.raises(RuntimeError, match="picamera2"):
            _import_camera_stack()


def test_import_pyzbar_decode_raises_without_pyzbar() -> None:
    from piwallet.qr.camera_scan import _import_pyzbar_decode

    with patch.dict("sys.modules", {"pyzbar": None, "pyzbar.pyzbar": None}):
        with pytest.raises(RuntimeError, match="pyzbar"):
            _import_pyzbar_decode()
