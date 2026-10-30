#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_gen_accept_ks.py — 验收 kickstart 生成器契约
#
# 验收夹具必须与产品配方分离：生成器只在顶层收尾命令前插入 overlay，
# 并拒绝重复叠加、缺失收尾命令与源码区落点。测试同时用 ks_lint 校验
# 组合产物仍是合法配方。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import gen_accept_ks  # noqa: E402
import ks_lint  # noqa: E402

SCRIPT = TOOLS / "gen_accept_ks.py"
DISTRO = TOOLS.parent
BASE = DISTRO / "kickstart" / "airymaxos-workstation.ks"
PART = DISTRO / "ci" / "ks" / "acceptance.part"
PYTHON = sys.executable


class GenAcceptKsTest(unittest.TestCase):
    def setUp(self):
        self.base = BASE.read_text(encoding="utf-8")
        self.part = PART.read_text(encoding="utf-8")

    def test_insert_before_reboot(self):
        text = gen_accept_ks.compose(self.base, self.part)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.assertEqual(lines[-1], "reboot")
        self.assertLess(lines.index(gen_accept_ks.MARK), len(lines) - 1)

    def test_product_untouched(self):
        self.assertNotIn(gen_accept_ks.MARK, self.base)
        lines = self.base.splitlines(keepends=True)
        pos = gen_accept_ks.stop_at(lines)
        text = gen_accept_ks.compose(self.base, self.part).splitlines()
        self.assertEqual(text[:pos], self.base.splitlines()[:pos])

    def test_reject_stacked(self):
        text = gen_accept_ks.compose(self.base, self.part)
        with self.assertRaises(ValueError):
            gen_accept_ks.compose(text, self.part)

    def test_reject_unmarked(self):
        with self.assertRaises(ValueError):
            gen_accept_ks.compose(self.base, "lang zh_CN.UTF-8\n")

    def test_reject_missing_stop(self):
        with self.assertRaises(ValueError):
            gen_accept_ks.compose("lang zh_CN.UTF-8\n", self.part)

    def test_stop_inside_script_ignored(self):
        base = "%post --log=/root/x.log\nset -eu\nreboot\n%end\nreboot\n"
        lines = gen_accept_ks.compose(base, self.part).splitlines()
        self.assertLess(lines.index(gen_accept_ks.MARK), len(lines) - 1)
        self.assertLess(lines.index("reboot"), lines.index("%end"))
        self.assertEqual(lines[-1], "reboot")

    def test_include_is_not_section(self):
        base = ("lang zh_CN.UTF-8\n"
                "%pre --erroronfail --log=/tmp/p.log\n"
                "set -eu\necho disk\n%end\n"
                "%include /tmp/disk.ks\nreboot\n")
        lines = gen_accept_ks.compose(base, self.part).splitlines()
        self.assertEqual(lines[-1], "reboot")
        self.assertLess(lines.index("%include /tmp/disk.ks"),
                        lines.index(gen_accept_ks.MARK))

    def test_cli_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "acceptance.ks"
            res = subprocess.run(
                [PYTHON, str(SCRIPT), "--base", str(BASE),
                 "--overlay", str(PART), "--out", str(out)],
                text=True, capture_output=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            text = out.read_text(encoding="utf-8")
            self.assertIn(gen_accept_ks.MARK, text)
            self.assertEqual(ks_lint.lint_text(text), [])

    def test_cli_rejects_source_out(self):
        out = DISTRO / ".accept-tmp" / "acceptance.ks"
        res = subprocess.run(
            [PYTHON, str(SCRIPT), "--base", str(BASE),
             "--overlay", str(PART), "--out", str(out)],
            text=True, capture_output=True)
        self.assertEqual(res.returncode, 5)
        self.assertFalse(out.parent.exists())


if __name__ == "__main__":
    unittest.main()
