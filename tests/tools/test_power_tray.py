#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# test_power_tray.py — 电量托盘硬件门控的契约回归
#
# 上游托盘只在有电池时有显示对象。没有 power_supply 设备时它起手即退，
# 退出路径上的工作线程与已析构的对象竞争，偶发空指针崩溃——验收轮里
# 三条无电池的腿只有一条复现，正是竞态的形态。门控由 75-airymax-power-tray.sh
# 在会话拉起前表达：没有电池就落一条用户级 Hidden 条目，有电池就保持
# 发行默认且不留残留。
#
# 这里把判据指向伪 sysfs 与伪 XDG 目录，逐条驱动三条分支，并把 spec 的
# 接线一并断言：漏接安装行与漏接判据的症状完全一样，都只在装机后才可见。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.5
# ===========================================================================

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
HOOK = BASE / "desktop" / "xinitrc.d" / "75-airymax-power-tray.sh"
SPEC = BASE / "specs" / "airymaxos-release.spec"
SH = shutil.which("sh") or "/bin/sh"

TRAY = "ukui-power-manager-tray.desktop"


class PowerTrayGateTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="airymax-tray-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.supply = self.tmp / "power_supply"
        self.supply.mkdir()
        self.vendor = self.tmp / "vendor"
        self.vendor.mkdir()
        self.write_vendor()
        self.drop = self.home / ".config" / "autostart" / TRAY

    def write_vendor(self, present=True):
        path = self.vendor / TRAY
        if present:
            path.write_text("[Desktop Entry]\nType=Application\n"
                            "Exec=/usr/bin/ukui-power-manager-tray\n",
                            encoding="utf-8")
        elif path.exists():
            path.unlink()
        return path

    def write_power(self, kind="Battery", name="BAT0"):
        node = self.supply / name
        node.mkdir(parents=True, exist_ok=True)
        (node / "type").write_text(f"{kind}\n", encoding="utf-8")
        return node

    def write_drop(self, marker=True):
        self.drop.parent.mkdir(parents=True, exist_ok=True)
        text = "[Desktop Entry]\nType=Application\nHidden=true\n"
        if marker:
            text += "X-AirymaxOS-Gate=power-tray\n"
        self.drop.write_text(text, encoding="utf-8")
        return self.drop

    def invoke(self):
        env = dict(os.environ)
        env.pop("XDG_CONFIG_HOME", None)
        env.update({
            "HOME": str(self.home),
            "AIRY_POWER_SUPPLY": str(self.supply),
            "AIRY_AUTOSTART_DIR": str(self.vendor),
        })
        return subprocess.run([SH, "-c", '. "$0"', str(HOOK)], env=env,
                              capture_output=True, text=True)

    def test_no_battery_writes_gate(self):
        got = self.invoke()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertTrue(self.drop.is_file(), "无电池时必须落抑制条目")
        text = self.drop.read_text(encoding="utf-8")
        self.assertIn("Hidden=true", text)
        self.assertIn("X-AirymaxOS-Gate=power-tray", text)
        self.assertIn("no battery, tray gated", got.stderr)

    def test_mains_only_counts_as_no_battery(self):
        self.write_power(kind="Mains", name="AC")
        got = self.invoke()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertTrue(self.drop.is_file(), "只有市电时托盘仍无对象可显示")

    def test_battery_keeps_distribution_default(self):
        self.write_power()
        got = self.invoke()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertFalse(self.drop.exists(), "有电池时不得留下抑制条目")
        self.assertEqual(got.stderr, "", "健康路径不打印任何一行")

    def test_battery_removes_own_gate(self):
        self.write_drop()
        self.write_power()
        got = self.invoke()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertFalse(self.drop.exists())

    def test_battery_keeps_foreign_entry(self):
        self.write_drop(marker=False)
        self.write_power()
        self.invoke()
        self.assertTrue(self.drop.exists(), "没有本脚本标记的条目不得删除")
        self.assertNotIn("X-AirymaxOS-Gate", self.drop.read_text(encoding="utf-8"))

    def test_vendor_entry_absent_writes_nothing(self):
        self.write_vendor(present=False)
        got = self.invoke()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertFalse(self.drop.exists(), "发行条目不在时不该凭空造条目")

    def test_second_run_is_idempotent(self):
        self.invoke()
        first = self.drop.read_text(encoding="utf-8")
        got = self.invoke()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(self.drop.read_text(encoding="utf-8"), first)

    def test_spec_ships_hook(self):
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn("Source57:       75-airymax-power-tray.sh", spec)
        self.assertIn(
            "install -m 0755 %{SOURCE57} \\\n"
            "    %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/"
            "75-airymax-power-tray.sh", spec)
        self.assertIn(
            "sh -n %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/"
            "75-airymax-power-tray.sh", spec)
        self.assertIn(
            "%config(noreplace) %{_sysconfdir}/X11/xinit/xinitrc.d/"
            "75-airymax-power-tray.sh\n", spec)

    def test_hook_stays_posix_quiet(self):
        text = HOOK.read_text(encoding="utf-8")
        code = [line for line in text.splitlines()
                if not line.lstrip().startswith("#")]
        for line in code:
            self.assertNotIn("set -e", line,
                             "被 source 的钩子不得改调用方的 shell 选项")
            for word in ("[[", "local "):
                self.assertNotIn(word, line, "POSIX sh 之外无此语法")
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith("printf '"):
                try:
                    line.encode("ascii")
                except UnicodeEncodeError:
                    self.fail(f"第 {number} 行标记含非 ASCII：VT 字体无字形")


if __name__ == "__main__":
    unittest.main()
