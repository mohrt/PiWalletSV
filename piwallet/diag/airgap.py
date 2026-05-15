"""Airgap diagnostic — verify the device cannot reach a network.

PiWalletSV's whole security claim is "keys never leave the device".
That claim collapses if the device's radios are accidentally live, so
this module gives the operator (and the bonnet About screen) a way to
verify, on demand, that nothing is listening or broadcasting.

The check is structured as six independent sub-checks:

1. **No radio kernel modules loaded** — ``/proc/modules`` must not list
   any of the well-known Wi-Fi or Bluetooth driver modules. The
   provision script blacklists them, but lsmod is the authoritative
   answer.
2. **rfkill says everything is blocked** — ``/sys/class/rfkill/rfkill*``
   must report ``soft=1`` or ``hard=1`` for every entry. Even if the
   modules are loaded, an rfkill block prevents them from broadcasting.
3. **No radio network interfaces present** — ``/sys/class/net`` should
   contain only ``lo``. Anything else (``wlan0``, ``hci0``, ``bnep0``,
   ``eth0``) is a network attack surface.
4. **Radio services not running** — ``wpa_supplicant``,
   ``NetworkManager``, ``hciuart``, ``bluetooth`` must all be
   ``inactive`` or ``masked``.
5. **Boot config disables the radios at firmware level** —
   ``config.txt`` must declare both ``dtoverlay=disable-wifi`` and
   ``dtoverlay=disable-bt``. Belt-and-suspenders against userspace
   reloading them.
6. **Modules blacklisted in modprobe** — ``/etc/modprobe.d/*.conf`` must
   blacklist at least the core Wi-Fi/BT modules so they don't load on
   next boot even if firmware overlays were reverted.

Each sub-check returns a :class:`CheckResult` with one of three
outcomes:

* ``ok=True``  — conclusive PASS.
* ``ok=False`` — conclusive FAIL (this is the BREACH signal).
* ``ok=None``  — the check could not be performed (running on macOS,
  command missing, sysfs node absent). Inconclusive checks are
  surfaced to the operator but do not flip the report to FAIL — that
  way ``piwallet diag airgap`` is meaningful on a developer laptop
  too, just with most rows reading "n/a".

The full :class:`AirgapReport` is **PASS** iff no sub-check reported
``ok=False``. A report that's all-inconclusive is technically PASS,
which is fine — the CLI surfaces inconclusive rows as a separate
warning so a developer-laptop run isn't mistaken for a real airgap
verification.

Sandboxing caveat
-----------------
When this module is invoked from a process with ``PrivateNetwork=yes``
(i.e. from inside the bonnet systemd unit), ``/sys/class/net`` shows
only ``lo`` regardless of host config. The interface check therefore
verifies the **sandbox**, not the host. Run ``piwallet diag airgap``
from an unprivileged shell to verify the host's actual interface
list. The other five checks see the host through namespaced-but-
unrestricted paths (``/proc/modules``, ``/sys/class/rfkill``,
``/etc/modprobe.d``, ``/boot/firmware/config.txt``, and ``systemctl``
over AF_UNIX), so they're honest from either context.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

# Wi-Fi driver modules and their cfg80211/mac80211 backing stack.
# rfkill is intentionally absent — the rfkill module is the *blocker*,
# its presence is fine.
WIFI_MODULES: frozenset[str] = frozenset(
    {
        "cfg80211",
        "mac80211",
        "brcmfmac",
        "brcmutil",
        "rtl8xxxu",
        "rtl8192cu",
        "rt2x00usb",
    }
)

# Bluetooth stack + common transports.
BLUETOOTH_MODULES: frozenset[str] = frozenset(
    {
        "bluetooth",
        "bluetooth_6lowpan",
        "btusb",
        "btsdio",
        "btbcm",
        "btintel",
        "btrtl",
        "hci_uart",
        "hci_vhci",
        "rfcomm",
        "bnep",
    }
)

RADIO_MODULES: frozenset[str] = WIFI_MODULES | BLUETOOTH_MODULES

# Subset of modules that *must* be in a modprobe blacklist for the
# blacklist check to pass. We don't insist on every module — distros
# split the blacklist file in different ways — but these three are the
# minimum the provision script must have written.
REQUIRED_BLACKLISTED: frozenset[str] = frozenset({"brcmfmac", "btusb", "bluetooth"})

# Anything in /sys/class/net that isn't loopback is a network surface
# we don't want on an air-gapped signing device.
SAFE_INTERFACES: frozenset[str] = frozenset({"lo"})

# Services we want guaranteed-not-running. ``masked`` and ``not-found``
# both count as PASS.
RADIO_SERVICES: tuple[str, ...] = (
    "wpa_supplicant.service",
    "NetworkManager.service",
    "hciuart.service",
    "bluetooth.service",
)

# Default filesystem locations. Overridable via the check_*() data
# arguments for unit tests.
DEFAULT_PROC_MODULES = Path("/proc/modules")
DEFAULT_RFKILL_DIR = Path("/sys/class/rfkill")
DEFAULT_NET_DIR = Path("/sys/class/net")
DEFAULT_BOOT_CONFIG = Path("/boot/firmware/config.txt")
DEFAULT_MODPROBE_DIR = Path("/etc/modprobe.d")


@dataclass(frozen=True)
class CheckResult:
    """One row of the airgap report.

    Attributes:
        name: short slug used by the CLI / About screen ("modules",
            "rfkill", "interfaces", "services", "boot_config",
            "blacklist").
        ok: ``True`` for PASS, ``False`` for FAIL, ``None`` for
            inconclusive (data source unavailable in this environment).
        detail: human-readable one-liner the operator can act on.
    """

    name: str
    ok: bool | None
    detail: str

    @property
    def status(self) -> str:
        """Three-letter glyph for compact rendering on the LCD."""
        if self.ok is True:
            return "OK"
        if self.ok is False:
            return "!!"
        return "--"


@dataclass(frozen=True)
class AirgapReport:
    """Full set of :class:`CheckResult` rows from one airgap pass."""

    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        """True iff no sub-check reported a conclusive FAIL.

        Inconclusive checks (``ok=None``) are *not* failures — see the
        module docstring for the rationale.
        """
        return not any(c.ok is False for c in self.checks)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.ok is False)

    @property
    def inconclusive(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.ok is None)

    def to_dict(self) -> dict[str, object]:
        """Machine-readable form for ``piwallet diag airgap --json``."""
        return {
            "ok": self.ok,
            "checks": [asdict(c) for c in self.checks],
        }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_no_radio_modules(
    loaded: Iterable[str] | None = None,
) -> CheckResult:
    """Fail if any known Wi-Fi or Bluetooth driver module is loaded."""
    if loaded is None:
        observed = _read_loaded_modules()
        if observed is None:
            return CheckResult("modules", None, "/proc/modules unavailable")
    else:
        observed = set(loaded)
    bad = sorted(observed & RADIO_MODULES)
    if bad:
        return CheckResult(
            "modules", False, f"radio modules loaded: {', '.join(bad)}"
        )
    return CheckResult("modules", True, "no radio modules loaded")


def check_rfkill_all_blocked(
    states: Iterable[tuple[str, bool, bool]] | None = None,
) -> CheckResult:
    """Fail if any rfkill device reports neither soft nor hard block.

    ``states`` is an iterable of ``(name, soft_blocked, hard_blocked)``
    triples, mirroring ``/sys/class/rfkill/rfkill*/{name,soft,hard}``.
    Pass ``None`` (the default) to read the live sysfs.
    """
    if states is None:
        observed = _read_rfkill()
        if observed is None:
            return CheckResult("rfkill", None, "/sys/class/rfkill unavailable")
    else:
        observed = list(states)
    if not observed:
        # No rfkill entries at all means there's nothing to block —
        # which is the right answer when radios are disabled at the
        # device-tree level (the kernel never registers an rfkill
        # entry for a radio that doesn't exist).
        return CheckResult("rfkill", True, "no rfkill devices registered")
    unblocked = [name for name, soft, hard in observed if not (soft or hard)]
    if unblocked:
        return CheckResult(
            "rfkill", False, f"unblocked: {', '.join(unblocked)}"
        )
    return CheckResult("rfkill", True, f"{len(observed)} radio(s) blocked")


def check_no_network_interfaces(
    interfaces: Iterable[str] | None = None,
) -> CheckResult:
    """Fail if anything other than ``lo`` is present in /sys/class/net.

    Note: when called from a ``PrivateNetwork=yes`` systemd unit (i.e.
    the bonnet itself), only ``lo`` is visible regardless of host
    config. This check therefore verifies the bonnet's sandbox is
    intact when run from inside it; run from a host shell to verify
    the host.
    """
    if interfaces is None:
        observed = _list_interfaces()
        if observed is None:
            return CheckResult("interfaces", None, "/sys/class/net unavailable")
    else:
        observed = set(interfaces)
    bad = sorted(observed - SAFE_INTERFACES)
    if bad:
        return CheckResult(
            "interfaces", False, f"net ifaces present: {', '.join(bad)}"
        )
    return CheckResult("interfaces", True, "only loopback present")


def check_no_radio_services(
    probe: Callable[[str], str | None] | None = None,
) -> CheckResult:
    """Fail if any of :data:`RADIO_SERVICES` is reported ``active``.

    ``probe(unit)`` should return the systemctl ``is-active`` answer
    (``"active"``, ``"inactive"``, ``"masked"``, ``"failed"``,
    ``"unknown"``, etc.) or ``None`` if the probe could not be run.
    """
    if probe is None:
        probe = _systemctl_is_active
    observations: list[tuple[str, str | None]] = []
    for svc in RADIO_SERVICES:
        observations.append((svc, probe(svc)))
    if all(state is None for _, state in observations):
        return CheckResult("services", None, "systemctl unavailable")
    active = [svc for svc, state in observations if state == "active"]
    if active:
        return CheckResult(
            "services", False, f"active: {', '.join(active)}"
        )
    return CheckResult("services", True, "no radio services active")


def check_boot_config_disables_radios(
    config_text: str | None = None,
) -> CheckResult:
    """Fail unless ``config.txt`` explicitly disables wifi and bluetooth.

    Looks for ``dtoverlay=disable-wifi`` and ``dtoverlay=disable-bt``
    as substrings on any uncommented line. We don't try to parse the
    full ``[filter]`` grammar — the provision script writes both
    overlays to the unconditional top section, so a substring match is
    sufficient and robust to filter-section changes.
    """
    if config_text is None:
        try:
            config_text = DEFAULT_BOOT_CONFIG.read_text()
        except OSError:
            return CheckResult(
                "boot_config", None, f"{DEFAULT_BOOT_CONFIG} not readable"
            )
    needed = ("disable-wifi", "disable-bt")
    present = []
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for name in needed:
            if f"dtoverlay={name}" in stripped:
                present.append(name)
    missing = sorted(set(needed) - set(present))
    if missing:
        return CheckResult(
            "boot_config", False, f"missing overlays: {', '.join(missing)}"
        )
    return CheckResult("boot_config", True, "wifi+bt disabled in config.txt")


def check_modules_blacklisted(
    blacklist_lines: Iterable[str] | None = None,
) -> CheckResult:
    """Fail unless the core radio modules are blacklisted in modprobe."""
    if blacklist_lines is None:
        observed = _read_modprobe_blacklists()
        if observed is None:
            return CheckResult(
                "blacklist", None, f"{DEFAULT_MODPROBE_DIR} unavailable"
            )
    else:
        observed = list(blacklist_lines)
    blacklisted = set()
    for line in observed:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2 and parts[0] == "blacklist":
            blacklisted.add(parts[1].strip())
    missing_core = sorted(REQUIRED_BLACKLISTED - blacklisted)
    if missing_core:
        return CheckResult(
            "blacklist", False, f"not blacklisted: {', '.join(missing_core)}"
        )
    covered = sorted(blacklisted & RADIO_MODULES)
    return CheckResult(
        "blacklist", True, f"{len(covered)} radio module(s) blacklisted"
    )


def check_airgap() -> AirgapReport:
    """Run every sub-check against the live system and return the report."""
    return AirgapReport(
        checks=(
            check_no_radio_modules(),
            check_rfkill_all_blocked(),
            check_no_network_interfaces(),
            check_no_radio_services(),
            check_boot_config_disables_radios(),
            check_modules_blacklisted(),
        )
    )


# ---------------------------------------------------------------------------
# Live data sources
# ---------------------------------------------------------------------------


def _read_loaded_modules() -> set[str] | None:
    try:
        text = DEFAULT_PROC_MODULES.read_text()
    except OSError:
        return None
    return {line.split(maxsplit=1)[0] for line in text.splitlines() if line.strip()}


def _read_rfkill() -> list[tuple[str, bool, bool]] | None:
    if not DEFAULT_RFKILL_DIR.is_dir():
        return None
    out: list[tuple[str, bool, bool]] = []
    for entry in sorted(DEFAULT_RFKILL_DIR.iterdir()):
        try:
            name = (entry / "name").read_text().strip()
            soft = (entry / "soft").read_text().strip() == "1"
            hard = (entry / "hard").read_text().strip() == "1"
        except OSError:
            # Partial read (rfkill device disappearing under us, or a
            # permission glitch) — treat as if the entry weren't there.
            continue
        out.append((name, soft, hard))
    return out


def _list_interfaces() -> set[str] | None:
    if not DEFAULT_NET_DIR.is_dir():
        return None
    return {p.name for p in DEFAULT_NET_DIR.iterdir()}


def _systemctl_is_active(unit: str) -> str | None:
    """Return the ``systemctl is-active`` answer for ``unit``, or None.

    A non-zero exit code is fine: ``inactive`` and ``failed`` both
    return non-zero, but their *stdout* is the value we care about.
    """
    if shutil.which("systemctl") is None:
        return None
    try:
        # S603 / S607: args are constants; resolving systemctl via $PATH
        # is the conventional way to call it, and the unit is read-only
        # so there's no shell-injection surface here.
        result = subprocess.run(  # noqa: S603
            ["systemctl", "is-active", unit],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    state = result.stdout.strip()
    return state or None


def _read_modprobe_blacklists() -> list[str] | None:
    if not DEFAULT_MODPROBE_DIR.is_dir():
        return None
    lines: list[str] = []
    for path in sorted(DEFAULT_MODPROBE_DIR.glob("*.conf")):
        try:
            lines.extend(path.read_text().splitlines())
        except OSError:
            continue
    return lines
