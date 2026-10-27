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
import re
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
    ("desktop/boot_state.sh",
     "/usr/lib/airymaxos/desktop/boot_state.sh"),
    ("desktop/display_mode.sh",
     "/usr/lib/airymaxos/desktop/display_mode.sh"),
    ("desktop/70-airymax-ukui-policy.sh",
     "%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh"),
    ("desktop/lightdm/50-airymax.conf",
     "%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf"),
    ("desktop/xinitrc.d/70-airymax-im.sh",
     "%{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh"),
    ("desktop/xinitrc.d/60-airymax-display.sh",
     "%{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh"),
    ("desktop/01_airymax_display",
     "%{_sysconfdir}/grub.d/01_airymax_display"),
    ("desktop/autostart/airymax-input-method.desktop",
     "%{_sysconfdir}/xdg/autostart/airymax-input-method.desktop"),
    ("desktop/autostart/airymax-display.desktop",
     "%{_sysconfdir}/xdg/autostart/airymax-display.desktop"),
    ("desktop/user@.service.d/50-airymax-desktop.conf",
     "%{_sysconfdir}/systemd/system/user@.service.d/"
     "50-airymax-desktop.conf"),
    ("desktop/journald.conf.d/50-airymax-journald.conf",
     "%{_sysconfdir}/systemd/journald.conf.d/50-airymax-journald.conf"),
    ("desktop/wallpaper/airymaxos-default.xml",
     "%{_datadir}/ukui-background-properties/airymaxos-default.xml"),
    ("desktop/glib-2.0/schemas/99-airymaxos-default.gschema.override",
     "%{_datadir}/glib-2.0/schemas/"
     "99-airymaxos-default.gschema.override"),
    ("desktop/wallpaper/airymaxos-default.jpg",
     "%{_datadir}/backgrounds/airymaxos/airymaxos-default.jpg"),
    ("login/50-airymax-sshd.conf",
     "%{_sysconfdir}/ssh/sshd_config.d/50-airymax-sshd.conf"),
    ("login/90-airymax-sudoers",
     "%{_sysconfdir}/sudoers.d/90-airymax"),
    ("login/00-airymax-screensaver",
     "%{_sysconfdir}/dconf/db/local.d/00-airymax-screensaver"),
    ("boot/efi_brand.sh",
     "/usr/lib/airymaxos/boot/efi_brand.sh"),
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

    def test_lightdm_autologin(self):
        # 0.0.3 口径：本地座位以 airymax 自动登录，与 shadow 空口令一致
        conf = parse_kv(self.asset("desktop/lightdm/50-airymax.conf"))
        self.assertEqual(conf["Seat:*"]["autologin-user"], "airymax")
        self.assertEqual(conf["Seat:*"]["autologin-session"], "ukui")
        self.assertEqual(conf["Seat:*"]["autologin-user-timeout"], "0")

    def test_sshd_empty_password(self):
        # 空口令账户要能过 sshd，必须显式放开 PermitEmptyPasswords；
        # 只放开这一项，认证方式集合保持发行版默认
        text = self.asset("login/50-airymax-sshd.conf").read_text(
            encoding="utf-8")
        directives = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition(" ")
            directives[key] = value.strip()
        self.assertEqual(directives, {
            "PermitEmptyPasswords": "yes",
            "KbdInteractiveAuthentication": "no",
        })

    def test_sudoers_policy_is_single_grant(self):
        # sudo 静默忽略非 0440 的 include 文件，权限与内容同样是契约；
        # 有效规则必须只有一条，且只放开交付账户
        text = self.asset("login/90-airymax-sudoers").read_text(
            encoding="utf-8")
        rules = [line for line in text.splitlines()
                 if line.strip() and not line.startswith("#")]
        self.assertEqual(rules, ["airymax ALL=(ALL) NOPASSWD: ALL"])
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn(
            "install -m 0440 %{SOURCE21} \\\n"
            "    %{buildroot}%{_sysconfdir}/sudoers.d/90-airymax", spec)
        self.assertIn(
            "%config(noreplace) %attr(0440, root, root) "
            "%{_sysconfdir}/sudoers.d/90-airymax", spec)

    def test_screensaver_policy_disables_idle_lock(self):
        # 锁屏策略与 sudo 策略是免密口径的两半：键名拼错或取值回退到 true
        # 都不会让构建失败，只会在装机后以“每五分钟一次口令框”出现；dconf
        # 不编译键文件也不生效，因此内容与 %post 的 dconf update 都要断言。
        text = self.asset("login/00-airymax-screensaver").read_text(
            encoding="utf-8")
        keys = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "[")):
                continue
            key, _, value = line.partition("=")
            keys[key] = value
        self.assertEqual(keys, {"idle-lock-enabled": "false",
                                "lock-enabled": "false"})
        self.assertIn("[org/ukui/screensaver]", text)
        self.assertIn("Requires:       dconf", self.spec)
        self.assertIn("dconf update", self.spec)

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

    def test_grub_display_unconditional(self):
        # 00_header 把 gfxmode 与 gfxterm 塞进 loadfont 成功的分支，字体缺失
        # 时整段消失，控制台停在固件默认（B50 实测 800x600）。本片段的输出
        # 必须无条件包含三条设置，且候选不带位深。
        out = run(["sh", str(self.asset("desktop/01_airymax_display"))])
        self.assertEqual(out.returncode, 0)
        lines = out.stdout.splitlines()
        for want in ("  set gfxmode=1920x1080,1680x1050,1600x900,"
                     "1280x1024,1024x768,auto",
                     "  insmod gfxterm",
                     "  terminal_output gfxterm"):
            self.assertIn(want, lines)
        self.assertNotIn("loadfont", out.stdout)
        self.assertNotIn("x32", out.stdout)
        self.assertIn("grub_platform", out.stdout)

    def test_efi_brand_contract(self):
        # 品牌化只由安装配方调用：脚本必须接受目标根重定向，且把「不在可改写
        # 范围」与「范围内失败」分成两个退出码，否则 BIOS 装机被误判为失败。
        text = self.asset("boot/efi_brand.sh").read_text(encoding="utf-8")
        for want in ("--esp)", "--state)",
                     '[ -d /sys/firmware/efi ] || skip "no efivarfs (BIOS boot)"'):
            self.assertIn(want, text)
        self.assertIn("exit 0", text.split("skip()", 1)[1].split("}", 1)[0])
        self.assertIn("exit 1", text.split("fail()", 1)[1].split("}", 1)[0])
        # 首启路径必须不存在：init_t 在 dosfs_t 上建文件被 SELinux 拒绝
        self.assertFalse(
            (BASE / "boot" / "airymaxos-efi-brand.service").exists())

    def test_ks_brands_inside_root(self):
        # 品牌脚本必须在目标根内执行：安装器环境没有 efibootmgr，直接调用只会
        # 走 skip，而配方仍会报 OK（验收 run 40587295652）。状态文件非空是
        # 「品牌确实落地」的唯一判据，退出码 0 不够。
        text = (BASE / "kickstart" / "airymaxos-workstation.ks").read_text(
            encoding="utf-8")
        for want in ('chroot "${root}" "${brand}"',
                     "--state /var/lib/airymaxos/efi-brand",
                     '[ ! -s "${root}/var/lib/airymaxos/efi-brand" ]',
                     "mount --rbind"):
            self.assertIn(want, text)

    def test_check_literals_match_assets(self):
        # %check 的 grep 字面量若与出厂资产漂移（缩进、拼写），要到构建期才
        # 失败，一轮 CI 几十分钟；这里把同一条断言提前到 lint 阶段。
        target = {expand(dst): self.asset(rel) for rel, dst in ASSETS}
        check = self.spec.split("%check", 1)[1].split("\n%files", 1)[0]
        seen = 0
        for lit, path in re.findall(
                r"grep -qxF '([^']*)'[ \t]*\\?\n?[ \t]*(%\{buildroot\}\S+)",
                check):
            asset = target.get(expand(path.replace("%{buildroot}", "")))
            if asset is None:
                continue
            lines = asset.read_text(encoding="utf-8").splitlines()
            self.assertIn(lit, lines,
                          f"{asset.name} lacks %check literal: {lit}")
            seen += 1
        self.assertGreater(seen, 0)

    def test_efi_brand_script(self):
        script = self.asset("boot/efi_brand.sh")
        self.assertEqual(run(["sh", "-n", str(script)]).returncode, 0)
        # 成功路径必须先回读 BootOrder 再落状态文件，否则失败会被固化
        text = script.read_text(encoding="utf-8")
        self.assertLess(text.index("efibootmgr -o"),
                        text.index(">\"${state}\""))

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
