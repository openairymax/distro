#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_ukui_compat.py — ukui 兼容链接的回归测试
#
# 2026-11 现场发现：ukui-interface 的 D-Bus 服务文件把 Exec 写成
# /usr/libexec/ukui-*server，同一批 RPM 却把二进制装在 /usr/bin，激活时按
# 绝对路径 execve 失败，285H 上控制中心的触控板、鼠标、键盘、电源模块打开
# 即空。修复是让声明路径存在，而不是去改上游文件。
#
# 本用例守三件事：脚本对「该建、已存在、不是 ukui 入口」三种输入的行为与
# 幂等性；配方确实在 %posttrans 调用它并把它装进脚本目录；脚本不维护第二份
# 文件名清单（否则上游增删模块时要改两处）。脚本行为在临时树上验证，不碰
# 构建机的 /usr。
#
# Author: Decheng Li <lidecheng@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DISTRO = Path(__file__).resolve().parents[2]
ROOT = DISTRO.parent
TOOL = ROOT / "system" / "scripts" / "ukui_compat.sh"
SPEC = DISTRO / "specs" / "airymaxos-system.spec"


def run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(TOOL), str(root)],
                          capture_output=True, text=True)


class SpecTest(unittest.TestCase):
    def test_installed(self):
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("Source72:       ukui_compat.sh", text)
        self.assertIn("%{SOURCE72} %{buildroot}/usr/lib/airymaxos/scripts/",
                      text)

    def test_called_on_upgrade(self):
        text = SPEC.read_text(encoding="utf-8")
        post = text.split("\n%posttrans\n")[1].split("%files")[0]
        self.assertIn("/usr/lib/airymaxos/scripts/ukui_compat.sh || :", post)

    def test_shipped_by_glob(self):
        files = SPEC.read_text(encoding="utf-8").split("%files")[1]
        self.assertIn("/usr/lib/airymaxos/scripts/*.sh", files)


class ToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "usr" / "bin"
        self.bin.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, name: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    def test_links_declared_servers(self):
        self.add("ukui-touchpadserver")
        self.add("ukui-mouseserver")
        done = run(self.root)
        self.assertEqual(0, done.returncode, done.stderr)
        for name in ("ukui-touchpadserver", "ukui-mouseserver"):
            link = self.root / "usr" / "libexec" / name
            self.assertTrue(link.is_symlink(), name)
            self.assertEqual(f"/usr/bin/{name}", os.readlink(link))

    def test_leaves_other_entries(self):
        self.add("ukui-desktoppluginserver")
        self.add("ukui-panel")
        done = run(self.root)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertTrue((self.root / "usr" / "libexec"
                         / "ukui-desktoppluginserver").is_symlink())
        self.assertFalse((self.root / "usr" / "libexec" / "ukui-panel").exists())

    def test_idempotent(self):
        self.add("ukui-powerserver")
        first = run(self.root)
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertIn("linked 1", first.stdout)
        second = run(self.root)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual("", second.stdout)

    def test_keeps_existing_file(self):
        self.add("ukui-keyboardserver")
        mine = self.root / "usr" / "libexec"
        mine.mkdir()
        own = mine / "ukui-keyboardserver"
        own.write_text("packaged\n", encoding="utf-8")
        done = run(self.root)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertFalse(own.is_symlink())
        self.assertEqual("packaged\n", own.read_text(encoding="utf-8"))

    def test_empty_tree_is_quiet(self):
        done = run(self.root)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("", done.stdout)
        self.assertFalse((self.root / "usr" / "libexec").exists())


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
