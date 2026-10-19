#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_run_smoke.py — ci/run-smoke.sh 契约回归测试
#
# 冒烟脚本必须在已登录的 UKUI 桌面会话内运行，CI 宿主机不具备该环境。
# 脚本对外契约是：TAP 14 计划、五项探测的判定、77 跳过语义，以及
# “跳过不掩盖失败”的退出码规则。这里用 PATH 沙箱提供伪 loginctl /
# pgrep / xdpyinfo / fcitx-remote / pactl / systemctl / gsettings /
# sha256sum，每个用例只破坏一个前提，从而在无桌面环境下判定真实控制流。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import fakes

SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "run-smoke.sh"
BASH = shutil.which("bash") or "/bin/bash"

LEGACY = ("tauri", "webkitwebprocess", "fcitx5", "pipewire",
          "kylin-app-cgroupd")


class RunSmokeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

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
        self.assertEqual(self.summary(res),
                         {"pass": 5, "fail": 0, "skip": 0})
        self.assertEqual(len(self.taps(res)), 5)
        for line in self.taps(res):
            self.assertTrue(line.startswith("ok"), line)

    def test_tap_plan(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("TAP version 14", res.stdout)
        self.assertIn("1..5", res.stdout.splitlines())
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
        self.assertEqual(self.summary(res)["skip"], 0)

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
        self.assertEqual(self.summary(res)["skip"], 0)

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

    def test_loginctl_absent_skips(self):
        self.tools(omit=("loginctl",))
        res = self.run_smoke()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.summary(res),
                         {"pass": 4, "fail": 0, "skip": 1})
        self.assertIn("# SKIP loginctl not installed", self.tap(res, 1))

    def test_skip_does_not_mask_failure(self):
        self.tools(omit=("loginctl",))
        res = self.run_smoke(FAKE_PACTL="fail")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.summary(res),
                         {"pass": 3, "fail": 1, "skip": 1})


if __name__ == "__main__":
    unittest.main()
