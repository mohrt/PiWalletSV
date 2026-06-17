"""Unit tests for the airgap diagnostic.

Every check accepts an explicit data source so tests don't have to
mock the real sysfs / subprocess machinery. The handful of tests that
exercise the live ``_read_*`` helpers redirect their default paths via
monkeypatch instead of running on the host directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.diag import airgap as ag

# ---------------------------------------------------------------------------
# CheckResult / AirgapReport
# ---------------------------------------------------------------------------


def test_check_result_status_glyphs() -> None:
    assert ag.CheckResult("x", True, "").status == "OK"
    assert ag.CheckResult("x", False, "").status == "!!"
    assert ag.CheckResult("x", None, "").status == "--"


def test_report_ok_only_when_no_conclusive_failures() -> None:
    pass_check = ag.CheckResult("a", True, "")
    inconclusive = ag.CheckResult("b", None, "")
    fail_check = ag.CheckResult("c", False, "")

    assert ag.AirgapReport(checks=(pass_check, inconclusive)).ok is True
    assert ag.AirgapReport(checks=(pass_check, fail_check)).ok is False
    assert ag.AirgapReport(checks=(inconclusive,)).ok is True


def test_report_partitions_failures_and_inconclusive() -> None:
    p = ag.CheckResult("a", True, "")
    i = ag.CheckResult("b", None, "")
    f = ag.CheckResult("c", False, "")
    rep = ag.AirgapReport(checks=(p, i, f))

    assert rep.failures == (f,)
    assert rep.inconclusive == (i,)


def test_report_to_dict_round_trips_check_fields() -> None:
    rep = ag.AirgapReport(
        checks=(ag.CheckResult("modules", True, "no radio modules loaded"),)
    )
    d = rep.to_dict()
    assert d["ok"] is True
    assert d["checks"] == [
        {"name": "modules", "ok": True, "detail": "no radio modules loaded"}
    ]


# ---------------------------------------------------------------------------
# check_no_radio_modules
# ---------------------------------------------------------------------------


def test_wifi_modules_pass_when_none_loaded() -> None:
    res = ag.check_no_wifi_modules(loaded=["snd_bcm2835", "bluetooth"])
    assert res.ok is True
    assert res.name == "wifi"


def test_bluetooth_modules_fail_lists_loaded() -> None:
    res = ag.check_no_bluetooth_modules(loaded=["btusb", "spi_bcm2835"])
    assert res.ok is False
    assert res.name == "bluetooth"
    assert "btusb" in res.detail


def test_modules_pass_when_no_radio_modules_loaded() -> None:
    res = ag.check_no_radio_modules(loaded=["snd_bcm2835", "spi_bcm2835"])
    assert res.ok is True
    assert "no radio modules" in res.detail


def test_modules_fail_lists_loaded_radio_modules() -> None:
    res = ag.check_no_radio_modules(loaded=["brcmfmac", "btusb", "spi_bcm2835"])
    assert res.ok is False
    # Sorted, so the order is deterministic across runs.
    assert "brcmfmac" in res.detail
    assert "btusb" in res.detail
    assert res.detail.index("brcmfmac") < res.detail.index("btusb")


def test_modules_inconclusive_when_proc_modules_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ag, "DEFAULT_PROC_MODULES", tmp_path / "no-such-file")
    res = ag.check_no_radio_modules()
    assert res.ok is None


# ---------------------------------------------------------------------------
# check_rfkill_all_blocked
# ---------------------------------------------------------------------------


def test_rfkill_pass_when_every_radio_is_blocked() -> None:
    res = ag.check_rfkill_all_blocked(
        states=[("phy0", True, False), ("hci0", False, True)]
    )
    assert res.ok is True
    assert "2 radio" in res.detail


def test_rfkill_fail_when_any_radio_is_unblocked() -> None:
    res = ag.check_rfkill_all_blocked(
        states=[("phy0", True, False), ("hci0", False, False)]
    )
    assert res.ok is False
    assert "hci0" in res.detail
    assert "phy0" not in res.detail


def test_rfkill_pass_when_no_radios_registered() -> None:
    # Disabled at device-tree level → kernel never registers an
    # rfkill entry. That's the strongest possible "no radio" state.
    res = ag.check_rfkill_all_blocked(states=[])
    assert res.ok is True
    assert "no rfkill devices" in res.detail


def test_rfkill_inconclusive_when_sysfs_dir_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ag, "DEFAULT_RFKILL_DIR", tmp_path / "no-rfkill")
    res = ag.check_rfkill_all_blocked()
    assert res.ok is None


# ---------------------------------------------------------------------------
# check_no_network_interfaces
# ---------------------------------------------------------------------------


def test_interfaces_pass_only_loopback() -> None:
    res = ag.check_no_network_interfaces(interfaces=["lo"])
    assert res.ok is True


def test_interfaces_fail_when_any_non_loopback_present() -> None:
    res = ag.check_no_network_interfaces(interfaces=["lo", "wlan0"])
    assert res.ok is False
    assert "wlan0" in res.detail


def test_interfaces_fail_on_eth_too() -> None:
    # Even wired ethernet is a network surface on a sealed signing device.
    res = ag.check_no_network_interfaces(interfaces=["lo", "eth0"])
    assert res.ok is False
    assert "eth0" in res.detail


def test_interfaces_inconclusive_when_sysfs_dir_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ag, "DEFAULT_NET_DIR", tmp_path / "no-net")
    res = ag.check_no_network_interfaces()
    assert res.ok is None


# ---------------------------------------------------------------------------
# check_no_radio_services
# ---------------------------------------------------------------------------


def test_services_pass_when_all_inactive() -> None:
    answers = {
        "wpa_supplicant.service": "inactive",
        "NetworkManager.service": "inactive",
        "hciuart.service": "masked",
        "bluetooth.service": "not-found",
    }
    res = ag.check_no_radio_services(probe=lambda u: answers.get(u))
    assert res.ok is True


def test_services_fail_when_any_active() -> None:
    answers = {
        "wpa_supplicant.service": "active",
        "NetworkManager.service": "inactive",
        "hciuart.service": "masked",
        "bluetooth.service": "inactive",
    }
    res = ag.check_no_radio_services(probe=lambda u: answers.get(u))
    assert res.ok is False
    assert "wpa_supplicant.service" in res.detail


def test_services_inconclusive_when_systemctl_returns_none_for_all() -> None:
    # systemctl missing entirely (probe returns None for every unit).
    res = ag.check_no_radio_services(probe=lambda _u: None)
    assert res.ok is None


# ---------------------------------------------------------------------------
# check_boot_config_disables_radios
# ---------------------------------------------------------------------------


def test_boot_config_pass_when_both_overlays_present() -> None:
    text = """\
# PiWalletSV provisioning prepended these:
dtoverlay=disable-wifi
dtoverlay=disable-bt
dtparam=spi=on
"""
    res = ag.check_boot_config_disables_radios(config_text=text)
    assert res.ok is True


def test_boot_config_fail_when_only_one_overlay_present() -> None:
    text = "dtoverlay=disable-wifi\n"
    res = ag.check_boot_config_disables_radios(config_text=text)
    assert res.ok is False
    assert "disable-bt" in res.detail


def test_boot_config_ignores_commented_overlays() -> None:
    # A commented-out disable line must not satisfy the check.
    text = """\
#dtoverlay=disable-wifi
#dtoverlay=disable-bt
"""
    res = ag.check_boot_config_disables_radios(config_text=text)
    assert res.ok is False
    # Both still missing — both should be named.
    assert "disable-wifi" in res.detail
    assert "disable-bt" in res.detail


def test_boot_config_inconclusive_when_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        ag, "DEFAULT_BOOT_CONFIG", tmp_path / "no-config.txt"
    )
    res = ag.check_boot_config_disables_radios()
    assert res.ok is None


# ---------------------------------------------------------------------------
# check_modules_blacklisted
# ---------------------------------------------------------------------------


def test_blacklist_pass_when_required_modules_blacklisted() -> None:
    res = ag.check_modules_blacklisted(
        blacklist_lines=[
            "# autogenerated",
            "blacklist brcmfmac",
            "blacklist btusb",
            "blacklist bluetooth",
            "blacklist cfg80211",
        ]
    )
    assert res.ok is True
    # Detail counts how many radio modules are covered, not just the required.
    assert "4 radio module" in res.detail


def test_blacklist_fail_when_required_module_missing() -> None:
    res = ag.check_modules_blacklisted(
        blacklist_lines=["blacklist brcmfmac", "blacklist btusb"]
    )
    assert res.ok is False
    assert "bluetooth" in res.detail


def test_blacklist_ignores_commented_blacklist_lines() -> None:
    res = ag.check_modules_blacklisted(
        blacklist_lines=[
            "#blacklist brcmfmac",
            "blacklist btusb",
            "blacklist bluetooth",
        ]
    )
    assert res.ok is False
    assert "brcmfmac" in res.detail


def test_blacklist_inconclusive_when_modprobe_dir_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ag, "DEFAULT_MODPROBE_DIR", tmp_path / "no-modprobe.d")
    res = ag.check_modules_blacklisted()
    assert res.ok is None


# ---------------------------------------------------------------------------
# Live readers
# ---------------------------------------------------------------------------


def test_read_loaded_modules_parses_proc_modules_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "modules"
    fake.write_text(
        "snd_bcm2835 49152 0 - Live 0x0000000000000000\n"
        "spi_bcm2835 16384 0 - Live 0x0000000000000000\n"
        "\n"  # blank lines tolerated
    )
    monkeypatch.setattr(ag, "DEFAULT_PROC_MODULES", fake)
    assert ag._read_loaded_modules() == {"snd_bcm2835", "spi_bcm2835"}


def test_read_rfkill_parses_sysfs_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = tmp_path / "rfkill"
    base.mkdir()
    for slot, name, soft, hard in [
        ("rfkill0", "phy0", "1", "0"),
        ("rfkill1", "hci0", "0", "1"),
    ]:
        d = base / slot
        d.mkdir()
        (d / "name").write_text(name + "\n")
        (d / "soft").write_text(soft + "\n")
        (d / "hard").write_text(hard + "\n")
    monkeypatch.setattr(ag, "DEFAULT_RFKILL_DIR", base)
    assert ag._read_rfkill() == [("phy0", True, False), ("hci0", False, True)]


def test_list_interfaces_reads_sysfs_class_net(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = tmp_path / "net"
    base.mkdir()
    (base / "lo").mkdir()
    (base / "eth0").mkdir()
    monkeypatch.setattr(ag, "DEFAULT_NET_DIR", base)
    assert ag._list_interfaces() == {"lo", "eth0"}


def test_systemctl_is_active_returns_none_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ag.shutil, "which", lambda _name: None)
    assert ag._systemctl_is_active("foo.service") is None


def test_read_modprobe_blacklists_concatenates_all_conf_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = tmp_path / "modprobe.d"
    base.mkdir()
    (base / "a.conf").write_text("blacklist brcmfmac\n")
    (base / "b.conf").write_text("blacklist btusb\n")
    # A non-.conf file should be ignored by the glob.
    (base / "c.txt").write_text("blacklist eth_should_be_ignored\n")
    monkeypatch.setattr(ag, "DEFAULT_MODPROBE_DIR", base)
    lines = ag._read_modprobe_blacklists()
    assert lines is not None
    joined = "\n".join(lines)
    assert "brcmfmac" in joined
    assert "btusb" in joined
    assert "eth_should_be_ignored" not in joined


# ---------------------------------------------------------------------------
# check_airgap (smoke; just ensure it returns six conclusive-or-not rows)
# ---------------------------------------------------------------------------


def test_check_airgap_returns_six_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Point every data source at empty directories / non-existent files
    # so all checks are inconclusive (typical CI on macOS/Linux without
    # /proc/modules-style sysfs). The point is the *shape* of the report.
    monkeypatch.setattr(ag, "DEFAULT_PROC_MODULES", tmp_path / "no-modules")
    monkeypatch.setattr(ag, "DEFAULT_RFKILL_DIR", tmp_path / "no-rfkill")
    monkeypatch.setattr(ag, "DEFAULT_NET_DIR", tmp_path / "no-net")
    monkeypatch.setattr(ag, "DEFAULT_BOOT_CONFIG", tmp_path / "no-config.txt")
    monkeypatch.setattr(ag, "DEFAULT_MODPROBE_DIR", tmp_path / "no-modprobe.d")
    monkeypatch.setattr(ag.shutil, "which", lambda _name: None)

    rep = ag.check_airgap()
    assert len(rep.checks) == 6
    names = [c.name for c in rep.checks]
    assert names == [
        "modules",
        "rfkill",
        "interfaces",
        "services",
        "boot_config",
        "blacklist",
    ]


def test_checks_for_bonnet_display_returns_three_user_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ag,
        "check_no_wifi_modules",
        lambda: ag.CheckResult("wifi", True, "none loaded"),
    )
    monkeypatch.setattr(
        ag,
        "check_no_bluetooth_modules",
        lambda: ag.CheckResult("bluetooth", True, "none loaded"),
    )
    monkeypatch.setattr(
        ag,
        "_split_rfkill_checks",
        lambda: (
            ag.CheckResult("rfkill", True, "blocked"),
            ag.CheckResult("rfkill", True, "blocked"),
        ),
    )
    monkeypatch.setattr(
        ag,
        "check_no_network_interfaces",
        lambda: ag.CheckResult("interfaces", True, "only loopback present"),
    )
    monkeypatch.setattr(
        ag,
        "_split_service_checks",
        lambda: (
            ag.CheckResult("services", True, "no apps running"),
            ag.CheckResult("services", True, "no apps running"),
        ),
    )
    monkeypatch.setattr(
        ag,
        "_split_boot_config_checks",
        lambda: (
            ag.CheckResult("boot_config", True, "disable-wifi set"),
            ag.CheckResult("boot_config", True, "disable-bt set"),
        ),
    )
    monkeypatch.setattr(
        ag,
        "_split_blacklist_checks",
        lambda: (
            ag.CheckResult("blacklist", True, "blocked from reloading"),
            ag.CheckResult("blacklist", True, "blocked from reloading"),
        ),
    )

    rows = ag.checks_for_bonnet_display()
    assert [c.name for c in rows] == ["wifi", "bluetooth", "network"]
    assert [c.display_name for c in rows] == ["Wi-Fi", "Bluetooth", "Network"]


def test_aggregate_radio_check_fails_when_any_part_fails() -> None:
    wifi = ag._aggregate_radio_check(
        "wifi",
        ag.CheckResult("wifi", True, "ok"),
        ag.CheckResult("rfkill", False, "unblocked: phy0"),
    )
    assert wifi.ok is False
    assert "phy0" in wifi.detail


def test_bonnet_status_uses_plain_labels() -> None:
    assert ag.CheckResult("wifi", True, "").bonnet_status == "Disabled"
    assert ag.CheckResult("wifi", False, "").bonnet_status == "Active"
    assert ag.CheckResult("wifi", None, "").bonnet_status == "Unknown"
    assert ag.CheckResult("wifi", True, "").status == "OK"


def test_aggregate_radio_check_ok_when_rfkill_inconclusive_but_rest_pass() -> None:
    wifi = ag._aggregate_radio_check(
        "wifi",
        ag.CheckResult("modules", True, "none loaded"),
        ag.CheckResult("rfkill", None, "/sys/class/rfkill unavailable"),
        ag.CheckResult("services", True, "no apps running"),
        ag.CheckResult("boot_config", True, "disable-wifi set"),
        ag.CheckResult("blacklist", True, "blocked from reloading"),
    )
    assert wifi.ok is True
    assert wifi.bonnet_status == "Disabled"


def test_check_display_names_use_plain_vocabulary() -> None:
    assert ag.CheckResult("wifi", True, "x").display_name == "Wi-Fi"
    assert ag.CheckResult("bluetooth", True, "x").display_name == "Bluetooth"
    assert ag.CheckResult("network", True, "x").display_name == "Network"
    assert ag.CheckResult("interfaces", True, "x").display_name == "Network"
