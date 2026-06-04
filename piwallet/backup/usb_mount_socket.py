"""Root-owned Unix socket for mounting USB sticks from the bonnet.

``piwallet-bonnet.service`` sets ``NoNewPrivileges=yes``, so a setuid
``sudo`` helper cannot work. A small root daemon listens on
``/run/piwallet/usb-mount.sock`` (group ``pwsv``, mode ``0660``) and
runs the ``usb-mount`` shell helper.
"""

from __future__ import annotations

import argparse
import grp
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

SOCKET_PATH = Path("/run/piwallet/usb-mount.sock")
DEFAULT_MOUNT_POINT = Path("/mnt/piwallet-usb")
_USB_MOUNT_HELPER = Path("/opt/piwallet/bin/usb-mount")
_PACKAGE_MOUNT_HELPER = Path(__file__).with_name("usb_mount.sh")
_RUNTIME_USER = "pwsv"


class UsbMountError(Exception):
    """Mount/unmount request failed."""


def _mount_helper() -> Path:
    if _USB_MOUNT_HELPER.is_file():
        return _USB_MOUNT_HELPER
    if _PACKAGE_MOUNT_HELPER.is_file():
        return _PACKAGE_MOUNT_HELPER
    raise UsbMountError("usb-mount helper not installed")


def _is_mounted(device: str, mount_point: Path) -> bool:
    try:
        proc = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", str(mount_point)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    if proc.returncode != 0:
        return False
    source = proc.stdout.strip()
    return source == device or source.endswith(device.removeprefix("/dev/"))


def _socket_request(line: str, *, timeout_s: float = 10.0) -> str:
    if not SOCKET_PATH.exists():
        raise UsbMountError(
            "USB mount service not running. "
            "Enable piwallet-usb-mount on the Pi."
        )
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect(str(SOCKET_PATH))
        sock.sendall(f"{line.strip()}\n".encode())
        data = sock.recv(1024).decode(errors="replace").strip()
    except OSError as exc:
        raise UsbMountError(f"USB mount socket error: {exc}") from exc
    finally:
        sock.close()
    if not data:
        raise UsbMountError("USB mount socket returned no response")
    if data.startswith("ERR "):
        raise UsbMountError(data[4:].strip() or "mount failed")
    if data.startswith("OK"):
        return data
    raise UsbMountError(data)


def mount_device(device: str, *, timeout_s: float = 15.0) -> Path:
    """Ask the root daemon to mount ``device`` at the canonical mount point."""
    mount_point = DEFAULT_MOUNT_POINT
    if _is_mounted(device, mount_point):
        return mount_point
    response = _socket_request(f"mount {device}")
    resolved = mount_point
    if response.startswith("OK "):
        reported = response[3:].strip()
        if reported:
            resolved = Path(reported)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _is_mounted(device, resolved):
            return resolved
        time.sleep(0.2)
    raise UsbMountError("USB mount timed out")


def unmount_stick(*, timeout_s: float = 10.0) -> None:
    if not DEFAULT_MOUNT_POINT.is_dir():
        return
    try:
        proc = subprocess.run(
            ["findmnt", "-n", str(DEFAULT_MOUNT_POINT)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return
    if proc.returncode != 0:
        return
    _socket_request("unmount", timeout_s=timeout_s)


def _handle_line(line: str) -> str:
    parts = line.strip().split()
    if not parts:
        return "ERR empty command"
    helper = _mount_helper()
    cmd = parts[0]
    if cmd == "mount":
        if len(parts) != 2:
            return "ERR usage: mount /dev/sda1"
        device = parts[1]
        try:
            proc = subprocess.run(
                [str(helper), "mount", device],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            detail = detail.replace("\n", " ")[:200]
            return f"ERR {detail or 'mount failed'}"
        mount_path = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else str(
            DEFAULT_MOUNT_POINT
        )
        return f"OK {mount_path}"
    if cmd == "unmount":
        try:
            subprocess.run([str(helper), "unmount"], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            detail = detail.replace("\n", " ")[:200]
            return f"ERR {detail or 'unmount failed'}"
        return "OK"
    return "ERR unknown command"


def run_daemon() -> None:
    if os.geteuid() != 0:
        raise SystemExit("piwallet USB mount daemon must run as root")
    helper = _mount_helper()
    log.info("starting USB mount daemon (helper=%s)", helper)
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        SOCKET_PATH.unlink()
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_PATH))
    try:
        pwsv_gid = grp.getgrnam(_RUNTIME_USER).gr_gid
    except KeyError:
        pwsv_gid = 0
    os.chown(SOCKET_PATH, 0, pwsv_gid)
    os.chmod(SOCKET_PATH, 0o660)
    server.listen(8)
    while True:
        conn, _addr = server.accept()
        with conn:
            try:
                payload = conn.recv(512).decode(errors="replace").strip()
                response = _handle_line(payload)
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("socket handler failed")
                response = f"ERR {exc}"
            conn.sendall(f"{response}\n".encode())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PiWallet USB mount socket daemon")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_daemon()
    return 0


if __name__ == "__main__":
    sys.exit(main())
