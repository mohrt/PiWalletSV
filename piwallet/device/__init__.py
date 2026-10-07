"""Named device configs.

A config picks the display, the input, and which shell to run. The
Zero image keeps ``zero``. ``pi3-ws35`` is the Waveshare 3.5 inch LCD (A).
``pi3-ws35f`` is the Waveshare 3.5 inch LCD (F).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """One supported board + panel + input combination."""

    id: str
    width: int
    height: int
    display: str
    fb_device: str
    input: str
    shell: str
    #: Display HAT for the About screen. It has no ID EEPROM to read.
    hat: str = ""
    #: Panel rotation once the HAT is seated on the 40-pin header.
    #: The Waveshare 3.5 inch LCD (A) plugs in only one way. Its
    #: native framebuffer is 480×320 at rotation 0. Pin 1 of the
    #: header is the panel origin. With KMS left on, that panel is
    #: ``/dev/fb0`` (``fb_ili9486``). ``/dev/fb1`` is the HDMI console.
    display_rotation_deg: int = 0
    #: ArduCam OV5647 on both devices. The Pi 3 uses a 15-pin ribbon;
    #: the Zero uses the 15-to-22-pin cable. Same camera board.
    camera: str = "ov5647"
    camera_name: str = "ArduCam OV5647 5MP"
    #: Clockwise rotation applied to preview frames. The Zero case is
    #: 90 degrees. The Pi 3 with the 3.5 inch LCD (F) is 180 degrees.
    camera_rotation_deg: int | None = 90
    #: The 3.5 inch LCD (A) touch is rotated 90 degrees from the glass.
    #: Swap the axes, then flip X, so a tap lands on the tile under the finger.
    swap_axes: bool = False
    invert_x: bool = False
    invert_y: bool = False


_PROFILES: dict[str, DeviceProfile] = {
    "zero": DeviceProfile(
        id="zero",
        width=240,
        height=240,
        display="st7789",
        fb_device="",
        input="bonnet",
        shell="joystick",
        hat="Adafruit 1.3in TFT Bonnet",
        display_rotation_deg=180,
    ),
    "pi3-ws35": DeviceProfile(
        id="pi3-ws35",
        width=480,
        height=320,
        display="framebuffer",
        fb_device="/dev/fb0",
        input="touch",
        shell="touch",
        hat="Waveshare 3.5in LCD (A)",
        camera="ov5647",
        camera_rotation_deg=None,
        swap_axes=True,
        invert_x=True,
    ),
    # Native 320×480 portrait. The extra height is for the wallet list.
    "pi3-ws35f": DeviceProfile(
        id="pi3-ws35f",
        width=320,
        height=480,
        display="framebuffer",
        fb_device="/dev/fb1",
        input="touch",
        shell="touch",
        hat="Waveshare 3.5in LCD (F)",
        camera="ov5647",
        camera_rotation_deg=180,
    ),
}


def get_device(device_id: str) -> DeviceProfile:
    """Return a known device config. Unknown ids fail closed."""
    try:
        return _PROFILES[device_id]
    except KeyError as exc:
        known = ", ".join(sorted(_PROFILES))
        raise ValueError(f"unknown device {device_id!r} (known: {known})") from exc


def known_devices() -> tuple[str, ...]:
    return tuple(sorted(_PROFILES))


def framebuffer_for_panel(
    fallback: str,
    *,
    graphics_root: Path | None = None,
    name_prefix: str = "panel-mipi-dbi",
) -> str:
    """Return the framebuffer whose sysfs name is the SPI panel.

    HDMI and the panel swap ``/dev/fb0`` and ``/dev/fb1`` depending on
    which one probes first. The kernel names the panel ``panel-mipi-dbid``.
    """
    root = graphics_root if graphics_root is not None else Path("/sys/class/graphics")
    try:
        nodes = sorted(
            p for p in root.iterdir() if p.name.startswith("fb") and p.name[2:].isdigit()
        )
    except OSError:
        return fallback
    for node in nodes:
        try:
            name = (node / "name").read_text(encoding="ascii").strip()
        except OSError:
            continue
        if name.startswith(name_prefix):
            return f"/dev/{node.name}"
    return fallback


def hardware_rows(profile: DeviceProfile, pi_model: str | None) -> tuple[tuple[str, str], ...]:
    """About-screen rows for the board, display HAT, and camera."""
    return (
        ("Pi", pi_model or "—"),
        ("HAT", profile.hat or "—"),
        ("Camera", profile.camera_name or "—"),
    )
