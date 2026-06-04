"""Tests for the root USB mount socket protocol."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from piwallet.backup import usb_mount_socket as sock


def test_handle_mount_success() -> None:
    proc = MagicMock()
    proc.stdout = "/mnt/piwallet-usb\n"
    with patch.object(sock, "_mount_helper", return_value=Path("/opt/bin/usb-mount")):
        with patch("subprocess.run", return_value=proc) as run:
            response = sock._handle_line("mount /dev/sda1")
    assert response == "OK /mnt/piwallet-usb"
    run.assert_called_once()


def test_handle_mount_failure_returns_err() -> None:
    with patch.object(sock, "_mount_helper", return_value=Path("/opt/bin/usb-mount")):
        with patch(
            "subprocess.run",
            side_effect=__import__("subprocess").CalledProcessError(
                1, "mount", stderr="unsupported filesystem: ntfs"
            ),
        ):
            response = sock._handle_line("mount /dev/sda1")
    assert response.startswith("ERR ")
    assert "ntfs" in response


def test_mount_device_uses_socket_response(tmp_path: Path) -> None:
    with patch.object(sock, "SOCKET_PATH") as mock_sock_path:
        mock_sock_path.exists.return_value = True
        with patch.object(sock, "_socket_request", return_value="OK /mnt/piwallet-usb"):
            with patch.object(sock, "_is_mounted", return_value=True):
                path = sock.mount_device("/dev/sda1")
    assert path == sock.DEFAULT_MOUNT_POINT


def test_mount_device_socket_missing() -> None:
    with patch.object(sock, "SOCKET_PATH") as mock_sock_path:
        mock_sock_path.exists.return_value = False
        with pytest.raises(sock.UsbMountError, match="not running"):
            sock.mount_device("/dev/sda1")
