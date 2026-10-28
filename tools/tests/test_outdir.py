#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_outdir.py — 产物目录边界守卫（lib/outdir.sh）回归测试
#
# 现场装机时工具树是解包出来的普通目录，不在任何 git 检出里。此前的兜底
# 把源码区认成工具树上两级的父目录，于是 /var/tmp 下的产物目录被判成源码
# 区，站点派生在实体机上第一步就被拒。用例把工具树放进临时目录，令守卫
# 必须恰好以工具树为源码区。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "outdir.sh"
BASH = shutil.which("bash") or "/bin/bash"


class OutGuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tool = self.root / "tool"
        lib = self.tool / "scripts" / "lib"
        lib.mkdir(parents=True)
        shutil.copy2(LIB, lib / "outdir.sh")

    def tearDown(self):
        self._tmp.cleanup()

    def guard(self, out):
        script = '. "$1/scripts/lib/outdir.sh"; out_guard t "$2"'
        return subprocess.run([BASH, "-c", script, "bash", str(self.tool), out],
                              capture_output=True, text=True, check=False)

    def test_unpacked_tree_accepts_sibling_out(self):
        out = self.root / "out"
        res = self.guard(str(out))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), str(out))
        self.assertTrue(out.is_dir())

    def test_rejects_out_inside_tree(self):
        res = self.guard(str(self.tool / "out"))
        self.assertEqual(res.returncode, 5, res.stderr)
        self.assertIn("源码区", res.stderr)

    def test_rejects_dot_name(self):
        res = self.guard(str(self.tool / ".."))
        self.assertEqual(res.returncode, 5, res.stderr)


if __name__ == "__main__":
    sys.exit(unittest.main())
