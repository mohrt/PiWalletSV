"""USB volume discovery: exFAT partitions on a stick whose disk is removable."""

from __future__ import annotations

import json
import stat

from piwallet.backup.usb import list_usb_volumes


def _lsblk(tmp_path, payload: dict) -> str:
    script = tmp_path / "lsblk"
    script.write_text("#!/bin/sh\nprintf '%s\\n' " + json.dumps(json.dumps(payload)) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_sysfs_lists_a_fat32_microsd_reader_and_skips_the_pi_card(tmp_path) -> None:
    block = tmp_path / "class"
    for name, sectors in (
        ("mmcblk0", 1000),
        ("mmcblk0p1", 800),
        ("sda", 100),
        ("sda1", 61071360),
        ("sdb", 0),
    ):
        node = block / name
        node.mkdir(parents=True)
        (node / "size").write_text(str(sectors))
    volumes = list_usb_volumes(sys_class=block)
    assert [item.device for item in volumes] == ["/dev/sda1"]
    assert "29.1G" in volumes[0].display_name


def test_sysfs_lists_every_usb_partition_and_skips_the_pi_card(tmp_path) -> None:
    block = tmp_path / "class"
    for name, sectors in (
        ("mmcblk0", 1000),
        ("mmcblk0p1", 800),
        ("mmcblk0p2", 15000000),
        ("sdb", 100),
        ("sdb1", 409600),
        ("sdb2", 30_000_000),
    ):
        node = block / name
        node.mkdir(parents=True)
        (node / "size").write_text(str(sectors))
    volumes = list_usb_volumes(sys_class=block)
    assert [item.device for item in volumes] == ["/dev/sdb1", "/dev/sdb2"]


def test_sysfs_reads_the_usb_device_name(tmp_path) -> None:
    block = tmp_path / "class"
    for name, sectors in (("sdb", 100), ("sdb1", 409600), ("sdb2", 30_000_000)):
        node = block / name
        node.mkdir(parents=True)
        (node / "size").write_text(str(sectors))
    device = block / "sdb" / "device"
    device.mkdir()
    (device / "vendor").write_text("SanDisk ")
    (device / "model").write_text("Ultra Fit       ")
    volumes = list_usb_volumes(sys_class=block)
    assert [item.device for item in volumes] == ["/dev/sdb1", "/dev/sdb2"]
    assert volumes[0].model == "SanDisk Ultra Fit"
    assert volumes[1].model == volumes[0].model


def test_sysfs_ignores_the_pi_usb_controller_name(tmp_path) -> None:
    scsi = (
        tmp_path
        / "devices"
        / "usb1"
        / "1-1"
        / "1-1.2"
        / "1-1.2:1.0"
        / "host0"
        / "target0:0:0"
        / "0:0:0:0"
    )
    scsi.mkdir(parents=True)
    (scsi / "vendor").write_text("Generic ")
    (scsi / "model").write_text("Mass-Storage    ")
    hub = tmp_path / "devices" / "usb1"
    (hub / "manufacturer").write_text("Linux 6.18.50+rpt-rpi-v8 dwc2_hsotg")
    (hub / "product").write_text("DWC OTG Controller")
    block = tmp_path / "class"
    disk = block / "sda"
    disk.mkdir(parents=True)
    (disk / "size").write_text("100")
    (disk / "device").symlink_to(scsi)
    part = block / "sda1"
    part.mkdir()
    (part / "size").write_text("409600")
    volumes = list_usb_volumes(sys_class=block)
    assert volumes[0].model == "Generic Mass-Storage"
    assert "Linux" not in volumes[0].model


def test_lsblk_adds_each_partitions_filesystem(tmp_path) -> None:
    from piwallet.backup.usb import UsbVolume, _with_formats

    script = _lsblk(
        tmp_path,
        {
            "blockdevices": [
                {
                    "name": "sdb",
                    "fstype": None,
                    "children": [
                        {"name": "sdb1", "fstype": "vfat"},
                        {"name": "sdb2", "fstype": "exfat"},
                    ],
                }
            ]
        },
    )
    volumes = [
        UsbVolume("/dev/sdb1", "200M", "", "", None, model="Reader"),
        UsbVolume("/dev/sdb2", "14.3G", "", "", None, model="Reader"),
    ]
    filled = _with_formats(volumes, script)
    assert [item.fstype for item in filled] == ["vfat", "exfat"]


def test_sysfs_lists_a_whole_disk_fat_stick(tmp_path) -> None:
    block = tmp_path / "class"
    node = block / "sda"
    node.mkdir(parents=True)
    (node / "size").write_text("204800")
    volumes = list_usb_volumes(sys_class=block)
    assert [item.device for item in volumes] == ["/dev/sda"]


def test_exfat_partition_is_listed_when_only_the_disk_is_removable(tmp_path) -> None:
    path = _lsblk(
        tmp_path,
        {
            "blockdevices": [
                {
                    "name": "mmcblk0",
                    "rm": False,
                    "type": "disk",
                    "tran": None,
                    "fstype": None,
                    "children": [
                        {"name": "mmcblk0p1", "rm": False, "type": "part", "fstype": "vfat"},
                    ],
                },
                {
                    "name": "sda",
                    "rm": True,
                    "type": "disk",
                    "tran": "usb",
                    "fstype": None,
                    "size": "32G",
                    "children": [
                        {
                            "name": "sda1",
                            "rm": False,
                            "type": "part",
                            "tran": None,
                            "fstype": "exfat",
                            "label": "STICK",
                            "size": "32G",
                        }
                    ],
                },
            ]
        },
    )
    volumes = list_usb_volumes(lsblk_path=path)
    assert [item.device for item in volumes] == ["/dev/sda1"]
    assert volumes[0].fstype == "exfat"
    assert volumes[0].label == "STICK"


def test_usb_partition_is_listed_when_exfat_type_is_blank(tmp_path) -> None:
    path = _lsblk(
        tmp_path,
        {
            "blockdevices": [
                {
                    "name": "sda",
                    "rm": False,
                    "tran": "usb",
                    "type": "disk",
                    "fstype": None,
                    "children": [
                        {
                            "name": "sda1",
                            "rm": False,
                            "type": "part",
                            "fstype": None,
                            "size": "8G",
                        }
                    ],
                }
            ]
        },
    )
    volumes = list_usb_volumes(lsblk_path=path)
    assert [item.device for item in volumes] == ["/dev/sda1"]
    assert volumes[0].fstype == ""


def test_unmarked_sd_partition_is_still_listed(tmp_path) -> None:
    path = _lsblk(
        tmp_path,
        {
            "blockdevices": [
                {
                    "name": "sda",
                    "rm": False,
                    "tran": None,
                    "type": "disk",
                    "fstype": None,
                    "children": [
                        {
                            "name": "sda1",
                            "rm": False,
                            "tran": None,
                            "type": "part",
                            "fstype": None,
                            "size": "16G",
                            "label": "BACKUP",
                        }
                    ],
                }
            ]
        },
    )
    volumes = list_usb_volumes(lsblk_path=path)
    assert [item.device for item in volumes] == ["/dev/sda1"]
    assert volumes[0].label == "BACKUP"


def test_exfat_signature_overrides_an_ntfs_label(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "piwallet.backup.usb._probe_signature",
        lambda device: "exfat" if device.endswith("sda1") else None,
    )
    path = _lsblk(
        tmp_path,
        {
            "blockdevices": [
                {
                    "name": "sda",
                    "rm": False,
                    "type": "disk",
                    "children": [
                        {"name": "sda1", "rm": False, "type": "part", "fstype": "ntfs", "size": "8G"},
                    ],
                }
            ]
        },
    )
    volumes = list_usb_volumes(lsblk_path=path)
    assert [item.device for item in volumes] == ["/dev/sda1"]
    assert volumes[0].fstype == "exfat"


def test_probe_reads_exfat_boot_sector(tmp_path) -> None:
    from piwallet.backup.usb import _classify_filesystem, _probe_signature

    blob = bytearray(512)
    blob[3:11] = b"EXFAT   "
    path = tmp_path / "stick"
    path.write_bytes(bytes(blob))
    assert _probe_signature(str(path)) == "exfat"
    assert _classify_filesystem(str(path), "ntfs") == "exfat"


def test_ntfs_usb_partition_is_ignored(tmp_path) -> None:
    path = _lsblk(
        tmp_path,
        {
            "blockdevices": [
                {
                    "name": "sda",
                    "rm": True,
                    "tran": "usb",
                    "type": "disk",
                    "children": [
                        {"name": "sda1", "rm": False, "type": "part", "fstype": "ntfs"},
                    ],
                }
            ]
        },
    )
    assert list_usb_volumes(lsblk_path=path) == []
