"""Warm libcamera/Picamera2 imports on the bonnet main thread before capture."""

from __future__ import annotations


def preflight_camera_imports() -> str | None:
    """Import picamera2 + libcamera on the main thread.

    Returns ``None`` on success or a short operator-facing error string.
    """
    try:
        import libcamera  # type: ignore[import-not-found]  # noqa: F401
        import picamera2  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return (
            "Camera stack missing.\n"
            "sudo apt install python3-picamera2\n"
            "venv needs --system-site-packages"
        )
    return None
