#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_desktop.py — 桌面集成资产一致性与回归测试
#
# 断言对象是资产内容本身，而不是某个 lint 工具的规则：同一事实（默认壁纸
# 路径）在注册表、schema override 与配方之间必须一致；lightdm 只声明合法
# seat；xinitrc.d 脚本保持 POSIX 兼容；策略脚本不得回退到已证伪的旧机制。
# 标准库 unittest 编写，可被 pytest 直接收集。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import configparser
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
SPEC = BASE / "specs" / "airymaxos-release.spec"
WALLPAPER = "/usr/share/backgrounds/airymaxos/airymaxos-default.jpg"

MACROS = {
    "%{_sysconfdir}": "/etc",
    "%{_datadir}": "/usr/share",
    "%{_unitdir}": "/usr/lib/systemd/system",
}

ASSETS = (
    ("desktop/airymax-desktop.slice",
     "%{_unitdir}/airymax-desktop.slice"),
    ("desktop/airymax-desktop-ready.service",
     "%{_unitdir}/airymax-desktop-ready.service"),
    ("desktop/desktop_ready.sh",
     "/usr/lib/airymaxos/desktop/desktop_ready.sh"),
    ("desktop/70-airymax-ukui-policy.sh",
     "%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh"),
    ("desktop/lightdm/50-airymax.conf",
     "%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf"),
    ("desktop/xinitrc.d/70-airymax-im.sh",
     "%{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh"),
    ("desktop/autostart/airymax-input-method.desktop",
     "%{_sysconfdir}/xdg/autostart/airymax-input-method.desktop"),
    ("desktop/user@.service.d/50-airymax-desktop.conf",
     "%{_sysconfdir}/systemd/system/user@.service.d/"
     "50-airymax-desktop.conf"),
    ("desktop/wallpaper/airymaxos-default.xml",
     "%{_datadir}/ukui-background-properties/airymaxos-default.xml"),
    ("desktop/glib-2.0/schemas/99-airymaxos-default.gschema.override",
     "%{_datadir}/glib-2.0/schemas/"
     "99-airymaxos-default.gschema.override"),
    ("desktop/wallpaper/airymaxos-default.jpg",
     "%{_datadir}/backgrounds/airymaxos/airymaxos-default.jpg"),
)


def expand(text):
    for macro, value in MACROS.items():
        text = text.replace(macro, value)
    return text


def parse_kv(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


class DesktopAssetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = SPEC.read_text(encoding="utf-8")

    def asset(self, rel):
        path = BASE / rel
        self.assertTrue(path.is_file(), f"missing asset: {rel}")
        return path

    def test_assets_are_sources(self):
        for rel, _dst in ASSETS:
            name = Path(rel).name
            self.assertRegex(self.spec, rf"(?m)^Source\d+:\s+{name}$",
                             f"{name} is not a Source")

    def test_assets_are_installed(self):
        for rel, dst in ASSETS:
            self.assertIn(dst, self.spec, f"{rel} has no install target")
            self.assertIn(dst, self.spec.split("%files", 1)[1],
                          f"{dst} missing from %files")

    def test_wallpaper_path_is_single_source(self):
        xml = ET.parse(self.asset(
            "desktop/wallpaper/airymaxos-default.xml")).getroot()
        entry = xml.find("wallpaper")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.findtext("filename"), WALLPAPER)

        override = parse_kv(self.asset(
            "desktop/glib-2.0/schemas/99-airymaxos-default.gschema.override"))
        self.assertEqual(
            override["org.mate.background"]["picture-filename"].strip("'\""),
            WALLPAPER)

        targets = {rel: expand(dst) for rel, dst in ASSETS}
        self.assertEqual(
            targets["desktop/wallpaper/airymaxos-default.jpg"], WALLPAPER)

    def test_wallpaper_registry(self):
        path = self.asset("desktop/wallpaper/airymaxos-default.xml")
        text = path.read_text(encoding="utf-8")
        self.assertIn('<!DOCTYPE wallpapers SYSTEM "gnome-wp-list.dtd">', text)
        entry = ET.parse(path).getroot().find("wallpaper")
        self.assertEqual(entry.get("deleted"), "false")
        self.assertEqual(entry.findtext("name"), "AirymaxOS")
        self.assertEqual(entry.findtext("options"), "zoom")
        self.assertTrue((BASE / "desktop" / "wallpaper" /
                         "airymaxos-default.jpg").is_file())

    def test_schema_override_minimal(self):
        override = parse_kv(self.asset(
            "desktop/glib-2.0/schemas/99-airymaxos-default.gschema.override"))
        self.assertEqual(list(override.sections()), ["org.mate.background"])
        self.assertEqual(list(override["org.mate.background"]),
                         ["picture-filename"])

    def test_input_env(self):
        path = self.asset("desktop/xinitrc.d/70-airymax-im.sh")
        text = path.read_text(encoding="utf-8")
        exports = dict(
            line.removeprefix("export ").split("=", 1)
            for line in text.splitlines() if line.startswith("export "))
        self.assertEqual(exports, {
            "GTK_IM_MODULE": "fcitx",
            "QT_IM_MODULE": "fcitx",
            "XMODIFIERS": "@im=fcitx",
        })
        self.assertIn("[ -x /usr/bin/fcitx ]", text)
        self.assertEqual(run(["sh", "-n", str(path)]).returncode, 0)

    def test_input_autostart(self):
        entry = parse_kv(
            self.asset("desktop/autostart/airymax-input-method.desktop"))
        self.assertEqual(entry["Desktop Entry"]["Type"], "Application")
        self.assertEqual(entry["Desktop Entry"]["Exec"], "/usr/bin/fcitx")
        self.assertEqual(entry["Desktop Entry"]["NoDisplay"], "true")
        self.assertNotIn("OnlyShowIn", entry["Desktop Entry"])

    def test_lightdm_seat(self):
        conf = parse_kv(self.asset("desktop/lightdm/50-airymax.conf"))
        self.assertEqual(list(conf.sections()), ["Seat:*"])
        self.assertEqual(conf["Seat:*"]["user-session"], "ukui")
        self.assertNotIn("type", conf["Seat:*"])

    def test_user_session_slice(self):
        conf = parse_kv(
            self.asset("desktop/user@.service.d/50-airymax-desktop.conf"))
        self.assertEqual(conf["Service"]["Slice"],
                         "airymax-desktop.slice")

    def test_slice_weights(self):
        conf = parse_kv(self.asset("desktop/airymax-desktop.slice"))
        self.assertEqual(conf["Slice"]["CPUWeight"], "50")
        self.assertEqual(conf["Slice"]["IOWeight"], "50")
        self.assertNotIn("MemoryMax", conf["Slice"])
        self.assertNotIn("MemoryHigh", conf["Slice"])

    def test_policy_has_no_legacy(self):
        text = self.asset(
            "desktop/70-airymax-ukui-policy.sh").read_text(encoding="utf-8")
        for legacy in ("/etc/profile.d", "gnome-background-properties",
                       "org.ukui.background", "|| true", "--now"):
            self.assertNotIn(legacy, text, f"legacy mechanism: {legacy}")
        # 默认 target 的唯一事实源是各剖面 kickstart 的 %post，策略脚本不介入
        self.assertNotIn("set-default", text)
        # 安装器 chroot 无 systemd 总线：单元文件动词必须走 --root 离线语义
        self.assertNotIn("systemctl disable", text)
        self.assertNotIn("systemctl mask", text)
        self.assertIn("systemctl --root=/ mask", text)
        self.assertEqual(run(["bash", "-n", str(
            BASE / "desktop" / "70-airymax-ukui-policy.sh")]).returncode, 0)


if __name__ == "__main__":
    unittest.main()
