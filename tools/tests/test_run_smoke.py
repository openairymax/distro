#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_run_smoke.py — ci/run-smoke.sh 契约回归测试
#
# 冒烟脚本必须在已登录的 UKUI 桌面会话内运行，CI 宿主机不具备该环境。
# 脚本对外契约是：TAP 14 计划、十一项探测的判定，以及“探测工具缺失即失败”
# 的退出码规则。这里用 PATH 沙箱提供伪 loginctl /
# pgrep / xdpyinfo / fcitx-remote / pactl / systemctl / gsettings /
# sha256sum / uname / xrandr，并给 T6–T11 准备一份只读系统视图
# （AIRYMAX_SMOKE_ROOT），每个用例只破坏一个前提，从而在无桌面环境下判定
# 真实控制流。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import fakes

SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "run-smoke.sh"
DISPLAY_MODE = Path(__file__).resolve().parents[2] / "desktop" / "display_mode.sh"
BASH = shutil.which("bash") or "/bin/bash"

LEGACY = ("tauri", "webkitwebprocess", "fcitx5", "pipewire",
          "kylin-app-cgroupd")

# 用户态可见的发行版内核版本；T6 以 -alk 后缀区分产品内核与上游内核。
KREL = "6.6.157-alk"
LSM_LIST = "airy_lockdown,lockdown,capability,yama,airy,selinux"
HOSTNAME = "airymaxos"
OS_RELEASE = ('NAME="AirymaxOS"\n'
              'VERSION="0.0.3 (OpenAirymax)"\n'
              "ID=airymaxos\n"
              'VERSION_ID="0.0.3"\n'
              'PRETTY_NAME="AirymaxOS 0.0.3 (OpenAirymax)"\n')

# T10 的两份 xrandr --query 拓扑：已在策略模式、以及首选 4K 待下调。
TOPO_OK = ("Screen 0: minimum 8 x 8, current 1920 x 1080,"
           " maximum 32767 x 32767\n"
           "eDP-1 connected primary 1920x1080+0+0 (normal) 344mm x 194mm\n"
           "   1920x1080     60.00*+\n"
           "   1280x720      60.00\n")
TOPO_4K = ("Screen 0: minimum 8 x 8, current 3840 x 2160,"
           " maximum 32767 x 32767\n"
           "eDP-1 connected primary 3840x2160+0+0 (normal) 344mm x 194mm\n"
           "   3840x2160     60.00*+\n"
           "   1920x1080     60.00\n"
           "   1280x720      60.00\n")


class RunSmokeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.sysroot = self.root / "sysroot"
        self.make_sysroot()
        self.install_display()

    def tearDown(self):
        self._tmp.cleanup()

    def make_sysroot(self):
        """构造 T6–T11 读取的只读视图：/boot 三件套、LSM、产品标识、ESP。"""
        boot = self.sysroot / "boot"
        boot.mkdir(parents=True)
        (boot / f"vmlinuz-{KREL}").write_bytes(b"vmlinuz\n")
        self.write_boot("config", 'CONFIG_LOCALVERSION="-alk"\n'
                                  "CONFIG_SECURITY_AIRY=y\n")
        (boot / f"System.map-{KREL}").write_text(
            "ffffffff81000000 T start_kernel\n", encoding="utf-8")
        self.write_lsm(LSM_LIST)
        self.write_product(HOSTNAME, OS_RELEASE)
        self.write_esp()

    def write_esp(self):
        """EFI 品牌的落点：完整签名套件 + 首启可见的 efivars 目录。"""
        esp = self.sysroot / "boot" / "efi" / "EFI" / "airymaxos"
        esp.mkdir(parents=True)
        for name in ("shimx64.efi", "grubx64.efi"):
            (esp / name).write_bytes(b"efi\n")
        (esp / "BOOTX64.CSV").write_text(
            "shimx64.efi,airymaxos,,AirymaxOS\n", encoding="utf-8")
        (self.sysroot / "sys" / "firmware" / "efi").mkdir(
            parents=True, exist_ok=True)
        return esp

    def write_product(self, hostname, os_release):
        etc = self.sysroot / "etc"
        etc.mkdir(parents=True, exist_ok=True)
        (etc / "hostname").write_text(f"{hostname}\n", encoding="utf-8")
        self.write_osrel(os_release)

    def write_osrel(self, body):
        path = self.sysroot / "etc" / "os-release"
        path.write_text(body, encoding="utf-8")
        return path

    def write_boot(self, kind, body):
        path = self.sysroot / "boot" / f"{kind}-{KREL}"
        path.write_text(body, encoding="utf-8")
        return path

    def write_lsm(self, body):
        path = self.sysroot / "sys" / "kernel" / "security" / "lsm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def install_display(self):
        """把策略脚本装进沙箱的 %{_prefix}/lib 路径，并给伪 xrandr 一份拓扑。"""
        dest = (self.sysroot / "usr" / "lib" / "airymaxos" / "desktop" /
                "display_mode.sh")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DISPLAY_MODE, dest)
        dest.chmod(0o755)
        self.topo = self.sysroot / "xrandr.topo"
        self.write_topo(TOPO_OK)
        return dest

    def write_topo(self, body):
        self.topo.write_text(body, encoding="utf-8")

    def tools(self, omit=()):
        fakes.link_tools(self.bin)
        fakes.smoke_tools(self.bin, omit)

    def run_script(self, *args, **extra):
        env = {
            "PATH": str(self.bin),
            "HOME": str(self.root),
            "DISPLAY": ":0",
            "XDG_SESSION_ID": "2",
            "GTK_IM_MODULE": "fcitx",
            "QT_IM_MODULE": "fcitx",
            "XMODIFIERS": "@im=fcitx",
            "FAKE_PROCS": "ukui-session-manager fcitx",
            "FAKE_XRANDR_TOPO": str(self.topo),
            "AIRYMAX_SMOKE_WAIT": "0",
            "AIRYMAX_SMOKE_ROOT": str(self.sysroot),
        }
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def run_smoke(self, **extra):
        return self.run_script("airymaxos-0.0.3", **extra)

    def taps(self, res):
        return [line for line in res.stdout.splitlines()
                if line.startswith(("ok ", "not ok "))]

    def tap(self, res, num):
        for line in self.taps(res):
            parts = line.split()
            if parts[0] == "ok" and parts[1] == str(num):
                return line
            if parts[0] == "not" and parts[2] == str(num):
                return line
        self.fail(f"no TAP line for probe {num}")

    def summary(self, res):
        lines = [line for line in res.stdout.splitlines()
                 if line.startswith("# summary:")]
        self.assertEqual(len(lines), 1, res.stdout)
        fields = lines[0].split(": ", 1)[1].split()
        return {key: int(value) for key, value in
                (field.split("=", 1) for field in fields)}

    def assert_fail(self, res, num):
        line = self.tap(res, num)
        self.assertTrue(line.startswith("not ok"), line)

    def test_all_pass(self):
        self.tools()
        res = self.run_smoke()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.summary(res), {"pass": 11, "fail": 0})
        self.assertNotIn("# SKIP", res.stdout)
        self.assertEqual(len(self.taps(res)), 11)
        for line in self.taps(res):
            self.assertTrue(line.startswith("ok"), line)

    def test_tap_plan(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("TAP version 14", res.stdout)
        self.assertIn("1..11", res.stdout.splitlines())
        self.assertIn(
            "# AirymaxOS distro smoke: target=airymaxos-0.0.3", res.stdout)

    def test_requires_target(self):
        self.tools()
        res = self.run_script()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("usage: run-smoke.sh", res.stderr)

    def test_no_legacy_probes(self):
        text = SCRIPT.read_text(encoding="utf-8").lower()
        for token in LEGACY:
            self.assertNotIn(token, text)

    def test_display_unset(self):
        self.tools()
        res = self.run_smoke(DISPLAY="")
        self.assert_fail(res, 1)
        self.assertIn("DISPLAY unset", res.stdout)

    def test_session_id_unset(self):
        self.tools()
        res = self.run_smoke(XDG_SESSION_ID="")
        self.assert_fail(res, 1)
        self.assertIn("XDG_SESSION_ID unset", res.stdout)

    def test_x11_unreachable(self):
        self.tools()
        res = self.run_smoke(FAKE_XDPYINFO="fail")
        self.assert_fail(res, 1)
        self.assertIn("X11 unreachable: :0", res.stdout)

    def test_session_not_x11(self):
        self.tools()
        self.assert_fail(self.run_smoke(FAKE_TYPE="tty"), 1)

    def test_service_not_lightdm(self):
        self.tools()
        self.assert_fail(self.run_smoke(FAKE_SERVICE="sddm"), 1)

    def test_session_inactive(self):
        self.tools()
        self.assert_fail(self.run_smoke(FAKE_ACTIVE="no"), 1)

    def test_no_ukui_session(self):
        self.tools()
        res = self.run_smoke(FAKE_PROCS="fcitx")
        self.assert_fail(res, 1)
        self.assertIn("ukui-session not running", res.stdout)

    def test_fcitx_down(self):
        self.tools()
        res = self.run_smoke(FAKE_PROCS="ukui-session-manager")
        self.assert_fail(res, 2)
        self.assertIn("fcitx not running", res.stdout)

    def test_fcitx_unreachable(self):
        self.tools()
        res = self.run_smoke(FAKE_FCITX_REMOTE="fail")
        self.assert_fail(res, 2)
        self.assertIn("fcitx-remote cannot reach daemon", res.stdout)

    def test_fcitx_state_invalid(self):
        self.tools()
        res = self.run_smoke(FAKE_FCITX_STATE="9")
        self.assert_fail(res, 2)
        self.assertIn("fcitx-remote state: 9", res.stdout)

    def test_im_variables(self):
        self.tools()
        for name in ("GTK_IM_MODULE", "QT_IM_MODULE", "XMODIFIERS"):
            with self.subTest(name=name):
                res = self.run_smoke(**{name: ""})
                self.assert_fail(res, 2)
                self.assertIn(name, res.stdout)

    def test_fcitx_remote_absent(self):
        self.tools(omit=("fcitx-remote",))
        res = self.run_smoke()
        self.assert_fail(res, 2)
        self.assertIn("fcitx-remote not installed", res.stdout)

    def test_pactl_unreachable(self):
        self.tools()
        res = self.run_smoke(FAKE_PACTL="fail")
        self.assert_fail(res, 3)
        self.assertIn("PulseAudio unreachable", res.stdout)

    def test_pactl_absent(self):
        self.tools(omit=("pactl",))
        res = self.run_smoke()
        self.assert_fail(res, 3)
        self.assertIn("pactl not installed", res.stdout)

    def test_audio_latency(self):
        self.tools()
        ready = self.root / "pactl.ready"
        fakes.write(self.bin, "pactl",
                    "#!/bin/sh\n[ -e '%s' ] || exit 1\n" % ready)
        timer = threading.Timer(1.5, ready.touch)
        timer.start()
        try:
            res = self.run_smoke(AIRYMAX_SMOKE_WAIT="15")
        finally:
            timer.cancel()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.summary(res), {"pass": 11, "fail": 0})

    def test_slice_wrong(self):
        self.tools()
        res = self.run_smoke(FAKE_SLICE="user.slice")
        self.assert_fail(res, 4)
        self.assertIn("user@ service slice: user.slice", res.stdout)

    def test_slice_inactive(self):
        self.tools()
        res = self.run_smoke(FAKE_SLICE_ACTIVE="inactive")
        self.assert_fail(res, 4)
        self.assertIn("slice state: inactive", res.stdout)

    def test_slice_weights(self):
        self.tools()
        for name in ("FAKE_CPU", "FAKE_IO"):
            with self.subTest(name=name):
                self.assert_fail(self.run_smoke(**{name: "100"}), 4)

    def test_slice_tasks_infinity(self):
        self.tools()
        res = self.run_smoke(FAKE_TASKS="infinity")
        self.assert_fail(res, 4)
        self.assertIn("slice TasksMax: infinity", res.stdout)

    def test_wallpaper_tool_absent(self):
        self.tools(omit=("gsettings",))
        res = self.run_smoke()
        self.assert_fail(res, 5)
        self.assertIn("gsettings not installed", res.stdout)

    def test_wallpaper_schema_missing(self):
        self.tools()
        res = self.run_smoke(FAKE_GSETTINGS="fail")
        self.assert_fail(res, 5)
        self.assertIn("No such schema 'org.mate.background'", res.stdout)

    def test_wallpaper_path_wrong(self):
        self.tools()
        res = self.run_smoke(FAKE_PAPER="/usr/share/backgrounds/gnome/adwaita.jpg")
        self.assert_fail(res, 5)
        self.assertIn("picture-filename", res.stdout)

    def test_wallpaper_unreadable(self):
        self.tools()
        res = self.run_smoke(FAKE_SHA256SUM="fail")
        self.assert_fail(res, 5)
        self.assertIn("wallpaper unreadable", res.stdout)

    def test_wallpaper_checksum(self):
        self.tools()
        res = self.run_smoke(FAKE_PAPER_SHA="0" * 64)
        self.assert_fail(res, 5)
        self.assertIn("wallpaper sha256", res.stdout)

    def test_probe_tool_absent_fails(self):
        self.tools(omit=("loginctl",))
        res = self.run_smoke()
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertEqual(self.summary(res), {"pass": 10, "fail": 1})
        self.assert_fail(res, 1)
        self.assertIn("loginctl not installed", res.stdout)
        self.assertNotIn("# SKIP", res.stdout)

    def test_kernel_not_alk(self):
        self.tools()
        res = self.run_smoke(FAKE_KERNEL_RELEASE="6.6.0-1.oe2403")
        self.assert_fail(res, 6)
        self.assertIn("uname -r: 6.6.0-1.oe2403 (want *-alk)", res.stdout)

    def test_kernel_boot_files_missing(self):
        self.tools()
        (self.sysroot / "boot" / f"config-{KREL}").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 6)
        self.assertIn(f"/boot/config-{KREL} missing", res.stdout)

    def test_kernel_config_mismatch(self):
        self.tools()
        self.write_boot("config", 'CONFIG_LOCALVERSION=""\n'
                                  "CONFIG_SECURITY_AIRY=y\n")
        res = self.run_smoke()
        self.assert_fail(res, 6)
        self.assertIn(f"config-{KREL}: LOCALVERSION mismatch", res.stdout)

    def test_lsm_duplicate_airy(self):
        self.tools()
        # 补充钩子在 late_initcall 里以同名二次注册时，注册表会出现两个
        # airy；这不是两个模块，必须判失败。
        self.write_lsm("airy_lockdown,lockdown,capability,yama,airy,selinux,"
                       "airy")
        res = self.run_smoke()
        self.assert_fail(res, 7)
        self.assertIn("airy registered 2 time(s)", res.stdout)

    def test_lsm_lockdown_absent(self):
        self.tools()
        self.write_lsm("lockdown,capability,yama,airy,selinux")
        res = self.run_smoke()
        self.assert_fail(res, 7)
        self.assertIn("airy_lockdown absent", res.stdout)

    def test_lsm_registry_unreadable(self):
        self.tools()
        (self.sysroot / "sys" / "kernel" / "security" / "lsm").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 7)
        self.assertIn("lsm registry unreadable", res.stdout)

    def test_hostname_default(self):
        self.tools()
        # 安装器缺省名（localhost.localdomain）说明配方没写 hostname。
        self.write_product("localhost.localdomain", OS_RELEASE)
        res = self.run_smoke()
        self.assert_fail(res, 8)
        self.assertIn("hostname: localhost.localdomain (want airymaxos)",
                      res.stdout)

    def test_hostname_absent(self):
        self.tools()
        (self.sysroot / "etc" / "hostname").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 8)
        self.assertIn("/etc/hostname unreadable", res.stdout)

    def test_brand_name_wrong(self):
        self.tools()
        self.write_osrel(OS_RELEASE.replace('NAME="AirymaxOS"',
                                            'NAME="openEuler"'))
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("os-release NAME: openEuler", res.stdout)

    def test_brand_version_not_semver(self):
        self.tools()
        self.write_osrel(OS_RELEASE.replace('VERSION_ID="0.0.3"',
                                            'VERSION_ID="rolling"'))
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("os-release VERSION_ID: rolling", res.stdout)

    def test_brand_absent(self):
        self.tools()
        (self.sysroot / "etc" / "os-release").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("/etc/os-release unreadable", res.stdout)


    def test_display_off_policy(self):
        self.tools()
        # 首选 4K 已超过 1920x1200 上限，会话停在 3840x2160 即判失败。
        self.write_topo(TOPO_4K)
        res = self.run_smoke()
        self.assert_fail(res, 10)
        self.assertIn("eDP-1:3840x2160->1920x1080", res.stdout)

    def test_display_tool_absent(self):
        self.tools(omit=("xrandr",))
        res = self.run_smoke()
        self.assert_fail(res, 10)
        self.assertIn("xrandr not installed", res.stdout)

    def test_display_no_output(self):
        self.tools()
        self.write_topo("Screen 0: minimum 8 x 8, current 640 x 480,"
                        " maximum 32767 x 32767\n"
                        "DP-1 disconnected (normal) 0mm x 0mm\n")
        res = self.run_smoke()
        self.assert_fail(res, 10)
        self.assertIn("无 connected 输出", res.stdout)

    def test_display_script_absent(self):
        self.tools()
        (self.sysroot / "usr" / "lib" / "airymaxos" / "desktop" /
         "display_mode.sh").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 10)
        self.assertIn("display_mode.sh not installed", res.stdout)

    def test_efi_brand_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 11 - T11 efi boot brand", res.stdout)

    def test_efi_brand_missing_shim(self):
        self.tools()
        (self.sysroot / "boot" / "efi" / "EFI" / "airymaxos" /
         "shimx64.efi").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 11)
        self.assertIn("shimx64.efi missing", res.stdout)

    def test_efi_brand_missing_csv(self):
        self.tools()
        (self.sysroot / "boot" / "efi" / "EFI" / "airymaxos" /
         "BOOTX64.CSV").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 11)
        self.assertIn("BOOTX64.CSV missing", res.stdout)

    def test_efi_brand_non_efi(self):
        # 纯 BIOS 装机没有 NVRAM 条目可写，本项不适用，但仍要留痕
        self.tools()
        (self.sysroot / "sys" / "firmware" / "efi").rmdir()
        res = self.run_smoke()
        self.assertIn("ok 11 - T11 efi boot brand", res.stdout)
        self.assertIn("non-EFI target", res.stdout)


if __name__ == "__main__":
    unittest.main()
