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
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import fakes

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
    ("desktop/airymax-rt-budget.service",
     "%{_unitdir}/airymax-rt-budget.service"),
    ("desktop/desktop_ready.sh",
     "/usr/lib/airymaxos/desktop/desktop_ready.sh"),
    ("desktop/boot_state.sh",
     "/usr/lib/airymaxos/desktop/boot_state.sh"),
    ("desktop/display_mode.sh",
     "/usr/lib/airymaxos/desktop/display_mode.sh"),
    ("desktop/rt_budget.sh",
     "/usr/lib/airymaxos/desktop/rt_budget.sh"),
    ("desktop/session_env.sh",
     "/usr/lib/airymaxos/desktop/session_env.sh"),
    ("desktop/airy_record.sh",
     "/usr/lib/airymaxos/desktop/airy_record.sh"),
    ("desktop/airy_observe.sh",
     "/usr/lib/airymaxos/desktop/airy_observe.sh"),
    ("desktop/airy_bench.py",
     "/usr/lib/airymaxos/desktop/airy_bench.py"),
    ("desktop/airy_demo.py",
     "/usr/lib/airymaxos/desktop/airy_demo.py"),
    ("desktop/xserver.sh",
     "/usr/lib/airymaxos/desktop/xserver"),
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


# 运行段字段集是活体独有的部分；身份段与静态报告逐键相同，因此两模式的
# 差集必须恰好等于这一组（D-35 的契约）。
RUN_KEYS = {
    "kernel.release", "kernel.owner", "session.type", "session.display",
    "display.outputs", "desktop.ready", "boot.health", "rt.budget",
    "mem.total_kb", "mem.avail_kb", "cpu.count", "root.used", "net.ipv4",
}


def identity_root(root):
    """铺一份最小的身份文件树，供两份报告共用。"""
    files = {
        "usr/lib/os-release":
            'ID=airymaxos\nVERSION_ID="0.0.3"\n'
            'PRETTY_NAME="AirymaxOS 0.0.3 (OpenAirymax)"\n',
        "etc/default/grub": 'GRUB_DISTRIBUTOR="AirymaxOS"\n',
        "etc/hostname": "airymaxos\n",
        "usr/share/backgrounds/airymaxos/airymaxos-default.jpg": "",
        "usr/share/glib-2.0/schemas/"
        "99-airymaxos-default.gschema.override": "",
    }
    for name in ("desktop_ready.sh", "airy_record.sh", "airy_observe.sh",
                 "airy_bench.py", "airy_demo.py"):
        files[f"usr/lib/airymaxos/desktop/{name}"] = ""
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def keys_of(stdout):
    found = set()
    for line in stdout.splitlines():
        head, _, rest = line.partition(" ")
        if head != "AIRYMAX-OBSERVE":
            continue
        key, sep, _val = rest.partition("=")
        if sep and key not in ("mode", "status"):
            found.add(key)
    return found


# 观察点与测量的替身只用于验证 demo 的判据，不冒充真实实现：身份正确、
# 展示项故意缺一项（net.ipv4），用来证明缺字段不会把结论拉成 degraded。
OBSERVE_STUB = """\
#!/bin/sh
M=AIRYMAX-OBSERVE
printf '%s os.id=airymaxos\\n' "$M"
printf '%s os.pretty="AirymaxOS 0.0.3 (OpenAirymax)"\\n' "$M"
printf '%s host.name=airymaxos\\n' "$M"
printf '%s kernel.release=6.6.157-alk\\n' "$M"
printf '%s kernel.owner=airymaxos-kernel\\n' "$M"
printf '%s cpu.count=8\\n' "$M"
printf '%s mem.total_kb=16000000\\n' "$M"
printf '%s display.outputs=eDP-1\\n' "$M"
printf '%s desktop.ready=active\\n' "$M"
printf '%s boot.health=0\\n' "$M"
printf '%s rt.budget=ok\\n' "$M"
printf '%s mode=live fields=11\\n' "$M"
printf '%s status=ok\\n' "$M"
"""

BENCH_STUB = """\
import sys
M = "AIRYMAX-BENCH"
print(f"{M} host kernel=6.6.157-alk cpu=8 ops=2000")
print(f"{M} pipe rtt_p50_us=2.8 rtt_p99_us=5.3 rate=338000")
print(f"{M} stream rtt_p50_us=4.7 rtt_p99_us=8.1 rate=210000")
print(f"{M} dgram rtt_p50_us=4.5 rtt_p99_us=7.9 rate=220000")
print(f"{M} msgs kind=pipe count=400000 size=64 rate=470000")
print(f"{M} bulk bytes=67108864 mib_s=6280")
print(f"{M} fork procs=8 ops_per_proc=2000 rate=1130000 scale=3.36")
print(f"{M} status=ok")
sys.exit(0)
"""


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
        # 0.0.3 口径：本地座位以 Airymax 自动登录，与 shadow 空口令一致
        conf = parse_kv(self.asset("desktop/lightdm/50-airymax.conf"))
        self.assertEqual(conf["Seat:*"]["autologin-user"], "Airymax")
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
        self.assertEqual(rules, ["Airymax ALL=(ALL) NOPASSWD: ALL"])
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn(
            "install -m 0440 %{SOURCE21} \\\n"
            "    %{buildroot}%{_sysconfdir}/sudoers.d/90-airymax", spec)
        self.assertIn(
            "%config(noreplace) %attr(0440, root, root) "
            "%{_sysconfdir}/sudoers.d/90-airymax", spec)

    def test_hostname_runtime_source(self):
        # /etc/hostname 的产品名含下划线，systemd 读取时按 RFC 1123 删除它，
        # 运行时名只能由 sysctl.d 在内核层写回；有效行必须唯一且逐字一致
        text = self.asset("boot/99-airymax-hostname.conf").read_text(
            encoding="utf-8")
        rules = [line for line in text.splitlines()
                 if line.strip() and not line.startswith("#")]
        self.assertEqual(rules, ["kernel.hostname = AIRYMAX_PC"])
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn("Source34:       99-airymax-hostname.conf", spec)
        self.assertIn(
            "%config(noreplace) %{_sysconfdir}/sysctl.d/"
            "99-airymax-hostname.conf", spec)

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

    def test_rt_budget_reports_what_it_applied(self):
        # 新装机实测：systemd 按控制器按需建立单元 cgroup，cpu 层级里还没有
        # slice 目录时，只写「已存在且可写」的组会一个都写不进，旧脚本却仍
        # 打印 status=ok。这里用假层级固定三条语义：缺目录先建、写入后回读、
        # 未生效的组必须让 status 降级。
        script = self.asset("desktop/rt_budget.sh")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cpu = base / "cgroup" / "cpu,cpuacct"
            cpu.mkdir(parents=True)
            (cpu / "cpu.rt_runtime_us").write_text("950000\n")
            (base / "proc").write_text("950000\n")
            (cpu / "system.slice").mkdir()
            (cpu / "system.slice" / "cpu.rt_runtime_us").write_text("0\n")
            env = dict(os.environ,
                       AIRYMAX_RT_PROC=str(base / "proc"),
                       AIRYMAX_RT_CGROOT=str(base / "cgroup"))
            out = subprocess.run(["sh", str(script)], capture_output=True,
                                 text=True, env=env, check=False)
            self.assertEqual(out.returncode, 0)
            self.assertIn("status=partial", out.stdout)
            self.assertIn("applied=1 wanted=4", out.stdout)
            self.assertIn("missing=[user.slice", out.stdout)
            self.assertEqual(
                (cpu / "system.slice" /
                 "cpu.rt_runtime_us").read_text().strip(), "190000")
            self.assertTrue((cpu / "user.slice").is_dir())

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
        # 两个收尾脚本都必须在目标根内执行：安装器环境没有 efibootmgr，直接调用
        # 只会走 skip，而配方仍会报 OK（验收 run 40587295652）。状态文件非空是
        # 「确实落地」的唯一判据，退出码 0 不够；品牌副本是 grub.cfg 的拷贝，
        # 必须拿到启动参数重建后的版本，故排在它之后。
        text = (BASE / "kickstart" / "airymaxos-workstation.ks").read_text(
            encoding="utf-8")
        for want in ('chroot "${root}" "${script}"',
                     '--state "/var/lib/airymaxos/${name}"',
                     '[ -s "${root}/var/lib/airymaxos/${name}" ]',
                     "mount --rbind",
                     "step /usr/lib/airymaxos/boot/grub_args.sh grub-args GRUB",
                     "step /usr/lib/airymaxos/boot/efi_brand.sh efi-brand EFI"):
            self.assertIn(want, text)
        self.assertLess(
            text.index("step /usr/lib/airymaxos/boot/grub_args.sh"),
            text.index("step /usr/lib/airymaxos/boot/efi_brand.sh"))

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

    def test_session_lib_is_passive(self):
        # 库被 source 时不得探测会话，也不得设置 set -u：调用方来自 sshd、
        # systemd 或桌面终端，加载期任何一次探测失败都会把「没有会话」变成
        # 「调用方脚本意外退出」。
        path = self.asset("desktop/session_env.sh")
        self.assertEqual(run(["sh", "-n", str(path)]).returncode, 0)
        self.assertNotIn("set -u",
                         path.read_text(encoding="utf-8").splitlines())
        out = run(["sh", "-c", f'. "{path}"; printf ok'])
        self.assertEqual((out.returncode, out.stdout), (0, "ok"))

    def test_observe_static_report(self):
        # 静态报告是打包自检的另一半：%check 只断言 os.id 一行，这里钉住
        # 完整字段集，避免资产改名后「少一行」被读成「没有这一项」。
        script = self.asset("desktop/airy_observe.sh")
        with tempfile.TemporaryDirectory() as tmp:
            root = identity_root(Path(tmp))
            out = run(["sh", str(script), "--root", str(root), "--static"])
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            lines = out.stdout.splitlines()
            for want in (
                    "AIRYMAX-OBSERVE os.id=airymaxos",
                    "AIRYMAX-OBSERVE os.version=0.0.3",
                    'AIRYMAX-OBSERVE os.pretty='
                    '"AirymaxOS 0.0.3 (OpenAirymax)"',
                    "AIRYMAX-OBSERVE brand.grub=AirymaxOS",
                    "AIRYMAX-OBSERVE brand.wallpaper=present",
                    "AIRYMAX-OBSERVE brand.schema=present",
                    "AIRYMAX-OBSERVE asset.desktop=present",
                    "AIRYMAX-OBSERVE asset.record=present",
                    "AIRYMAX-OBSERVE asset.observe=present",
                    "AIRYMAX-OBSERVE asset.bench=present",
                    "AIRYMAX-OBSERVE asset.demo=present",
                    "AIRYMAX-OBSERVE host.name=airymaxos",
                    "AIRYMAX-OBSERVE mode=static fields=12"):
                self.assertIn(want, lines)
            self.assertEqual(lines[-1], "AIRYMAX-OBSERVE status=ok")

    def test_observe_missing_root_stays_readable(self):
        # 空根下每个字段都要显式写 absent；省略行会让「没采到」与「没有这
        # 一项」长得一样，结论只能由末行 status 与非零退出码给出。
        script = self.asset("desktop/airy_observe.sh")
        with tempfile.TemporaryDirectory() as tmp:
            out = run(["sh", str(script), "--root", tmp, "--static"])
            self.assertNotEqual(out.returncode, 0)
            lines = out.stdout.splitlines()
            for key in ("os.id", "os.version", "os.pretty", "brand.grub",
                        "brand.wallpaper", "brand.schema", "asset.desktop",
                        "asset.record", "asset.observe", "asset.bench",
                        "asset.demo", "host.name"):
                self.assertIn(f"AIRYMAX-OBSERVE {key}=absent", lines)
            self.assertIn("AIRYMAX-OBSERVE mode=static fields=12", lines)
            self.assertEqual(lines[-1], "AIRYMAX-OBSERVE status=partial")

    def test_observe_live_carries_identity(self):
        # 身份段是两种模式共用的：装机后再也没有人跑 --static，而「这台机器
        # 是谁」恰恰是活体现场最常被问的一项。活体必须先用同一份实现读身份
        # 文件，再补运行段（D-35）。
        script = self.asset("desktop/airy_observe.sh")
        with tempfile.TemporaryDirectory() as tmp:
            root = identity_root(Path(tmp))
            out = run(["sh", str(script), "--root", str(root)])
            lines = out.stdout.splitlines()
            for want in ("os.id=airymaxos", "os.version=0.0.3",
                         "host.name=airymaxos",
                         'os.pretty="AirymaxOS 0.0.3 (OpenAirymax)"',
                         "brand.grub=AirymaxOS"):
                self.assertIn(f"AIRYMAX-OBSERVE {want}", lines)
            self.assertIn("AIRYMAX-OBSERVE mode=live fields=25", lines)
            self.assertTrue(
                any(line.startswith("AIRYMAX-OBSERVE kernel.release=")
                    for line in lines))

    def test_observe_modes_share_identity_keys(self):
        # 两种模式的差集只能是运行段：身份键少一个就说明活体又退回了「身份
        # 只在构建期可查」，多一个则说明同一事实被两个来源各写了一遍。
        script = self.asset("desktop/airy_observe.sh")
        with tempfile.TemporaryDirectory() as tmp:
            root = identity_root(Path(tmp))
            static = keys_of(run(["sh", str(script), "--root", str(root),
                                  "--static"]).stdout)
            live = keys_of(run(["sh", str(script), "--root", str(root)]).stdout)
        self.assertEqual(static - live, set())
        self.assertEqual(live - static, RUN_KEYS)

    def test_observe_sections_reuse_identity(self):
        # 主题视图是一次采集的切片，不是第二份实现：os.id 必须与静态报告
        # 逐字相同，否则「展示里叫 AirymaxOS、验收里叫别的」只差一个参数。
        script = self.asset("desktop/airy_observe.sh")
        with tempfile.TemporaryDirectory() as tmp:
            root = identity_root(Path(tmp))
            static = run(["sh", str(script), "--root", str(root),
                          "--static"]).stdout
            out = run(["sh", str(script), "--root", str(root),
                       "--section", "os"])
            self.assertIn("AIRYMAX-OBSERVE os.id=airymaxos", out.stdout)
            keys = keys_of(static)
            self.assertIn("os.id", keys)
            lines = out.stdout.splitlines()
            self.assertIn("AIRYMAX-OBSERVE section=os fields=7", lines)
            self.assertIn("AIRYMAX-OBSERVE mode=section fields=7", lines)

    def test_observe_sections_cover_topics(self):
        # 每个主题的字段数是契约：少一行要么是采集退化，要么是版本漂移，
        # 两种都必须在 CI 里看出来，而不是到展示现场才发现屏幕缺一截。
        script = self.asset("desktop/airy_observe.sh")
        for topic, count in (("kernel", 8), ("boot", 5), ("net", 4),
                             ("sched", 4)):
            out = run(["sh", str(script), "--section", topic])
            self.assertIn(f"AIRYMAX-OBSERVE section={topic} fields={count}",
                          out.stdout.splitlines(), topic)

    def test_observe_rejects_unknown_section(self):
        # 打错主题名必须立刻失败：静默输出空报告会被当成「这台机器没有
        # 这些项」。
        script = self.asset("desktop/airy_observe.sh")
        out = run(["sh", str(script), "--section", "nope"])
        self.assertEqual(out.returncode, 2)
        self.assertIn("reason=bad-section=nope", out.stderr)

    def test_observe_resolves_delayed_grub_brand(self):
        # anaconda 写入的 GRUB_DISTRIBUTOR 是延迟展开的管道表达式。报告不
        # eval 别人的配置，而是按同一条规则从 /etc/system-release 推菜单
        # 名；否则名字那一行显示的是「一条命令」，看的人无从判断品牌。
        script = self.asset("desktop/airy_observe.sh")
        with tempfile.TemporaryDirectory() as tmp:
            root = identity_root(Path(tmp))
            (root / "etc/default/grub").write_text(
                'GRUB_DISTRIBUTOR="$(sed \'s, release .*$,,g\' '
                '/etc/system-release)"\n', encoding="utf-8")
            (root / "etc/system-release").write_text(
                "AirymaxOS release 0.0.3 (OpenAirymax)\n", encoding="utf-8")
            out = run(["sh", str(script), "--root", str(root), "--static"])
            self.assertIn("AIRYMAX-OBSERVE brand.grub=AirymaxOS",
                          out.stdout.splitlines())

            (root / "etc/system-release").unlink()
            out = run(["sh", str(script), "--root", str(root), "--static"])
            self.assertIn("AIRYMAX-OBSERVE brand.grub=absent",
                          out.stdout.splitlines())

    def test_observe_reads_oneshot_ready(self):
        # 就绪探针是 Type=oneshot：成功后单元回到 inactive，is-active 恒答
        # inactive。只看 is-active 会把已经起了桌面的机器判成 partial，所以
        # 判据改成 Result=success 且 InvocationID 非空。
        script = self.asset("desktop/airy_observe.sh")
        with tempfile.TemporaryDirectory() as tmp:
            root = identity_root(Path(tmp))
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fakes.write(bin_dir, "systemctl", fakes.SYSTEMCTL)
            cases = (
                ({"FAKE_ACTIVE_STATE": "inactive", "FAKE_RESULT": "success",
                  "FAKE_INVOCATION": "d6e35bd7169f4c30a14c4f80de233976"},
                 "ready", "ok"),
                ({"FAKE_ACTIVE_STATE": "inactive", "FAKE_RESULT": "success",
                  "FAKE_INVOCATION": ""}, "absent", "partial"),
                ({"FAKE_ACTIVE_STATE": "failed", "FAKE_RESULT": "exit-code"},
                 "failed", "partial"),
            )
            for extra, want, verdict in cases:
                env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
                           **extra)
                out = subprocess.run(
                    ["sh", str(script), "--root", str(root)],
                    capture_output=True, text=True, check=False, env=env)
                lines = out.stdout.splitlines()
                self.assertIn(f"AIRYMAX-OBSERVE desktop.ready={want}", lines)
                self.assertIn(f"AIRYMAX-OBSERVE status={verdict}", lines)

    def test_demo_judges_identity_by_value(self):
        # 判据收紧（D-35）：展示项缺一两个只影响那一行，不能把品牌正确的
        # 机器判成 degraded；真正的缺口是观察点跑不起来或测量失败。
        demo = self.asset("desktop/airy_demo.py")
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            shutil.copy2(demo, stage / "airy_demo.py")
            (stage / "airy_observe.sh").write_text(
                OBSERVE_STUB, encoding="utf-8")
            (stage / "airy_bench.py").write_text(BENCH_STUB, encoding="utf-8")
            ok = run([sys.executable, str(stage / "airy_demo.py"),
                      "--no-sweep", "--plain"])
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("AIRYMAX-DEMO status=ok", ok.stdout)
            self.assertIn("absent", ok.stdout)

            (stage / "airy_bench.py").write_text(
                "import sys\nsys.exit(1)\n", encoding="utf-8")
            bad = run([sys.executable, str(stage / "airy_demo.py"),
                       "--no-sweep", "--plain"])
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("AIRYMAX-DEMO status=degraded", bad.stdout)

    def test_demo_prints_replay_entries(self):
        # 展示必须自带复算入口：看到数字的人第一件事是复跑命令，入口随
        # 输出走，就不依赖文档是否同步；末尾仍是唯一一行结论。
        demo = self.asset("desktop/airy_demo.py")
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            shutil.copy2(demo, stage / "airy_demo.py")
            (stage / "airy_observe.sh").write_text(
                OBSERVE_STUB, encoding="utf-8")
            (stage / "airy_bench.py").write_text(BENCH_STUB, encoding="utf-8")
            out = run([sys.executable, str(stage / "airy_demo.py"),
                       "--no-sweep", "--plain"])
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            for topic in ("kernel", "os", "boot", "net", "sched"):
                self.assertIn(f"--section {topic}", out.stdout)
            self.assertIn("rpm -qf /boot/vmlinuz-$(uname -r)", out.stdout)
            self.assertEqual(out.stdout.splitlines()[-1],
                             "AIRYMAX-DEMO status=ok")

    def test_record_check_reports_degraded(self):
        # 自检必须先给出证据再下结论：缺 ffmpeg 时提前退出，自动化只会
        # 拿到一个没有行的失败。这里用去掉 ffmpeg 的 PATH 固定这三条语义。
        script = self.asset("desktop/airy_record.sh")
        shell = shutil.which("sh")
        self.assertIsNotNone(shell)
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            for tool in ("readlink", "sed", "tail", "head", "tr", "awk",
                         "cat", "cut", "wc", "sleep"):
                src = shutil.which(tool)
                if src:
                    (bin_dir / tool).symlink_to(src)
            env = dict(os.environ, PATH=str(bin_dir), HOME=str(Path(tmp)))
            env.pop("DISPLAY", None)
            env.pop("XAUTHORITY", None)
            out = subprocess.run([shell, str(script), "--check"],
                                 capture_output=True, text=True, env=env,
                                 check=False)
            self.assertNotEqual(out.returncode, 0)
            lines = out.stdout.splitlines()
            self.assertIn("AIRYMAX-RECORD check ffmpeg=absent", lines)
            self.assertIn("AIRYMAX-RECORD check x11grab=absent", lines)
            self.assertIn("AIRYMAX-RECORD check status=degraded", lines)
            self.assertGreaterEqual(
                len([line for line in lines if " check " in line]), 5)

    def test_tool_packaging_is_weak_dependency(self):
        # ffmpeg 在 EPOL 而非基线仓库：硬 Require 会让一次元数据缺口中止
        # 装机；入口必须是相对符号链接，升级时不会出现两份实现。
        self.assertIn("Recommends:     ffmpeg", self.spec)
        self.assertNotRegex(self.spec, r"(?m)^Requires:.*\bffmpeg\b")
        for entry, impl in (("airy-record", "airy_record.sh"),
                            ("airy-observe", "airy_observe.sh"),
                            ("airy-bench", "airy_bench.py"),
                            ("airy-demo", "airy_demo.py")):
            self.assertIn(
                f"ln -s ../lib/airymaxos/desktop/{impl} "
                f"%{{buildroot}}%{{_bindir}}/{entry}", self.spec)
            self.assertIn(f"%{{_bindir}}/{entry}",
                          self.spec.split("%files", 1)[1])

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
