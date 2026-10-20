#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_iso_pad.py — tools/iso_pad.py 契约回归测试
#
# 目标镜像的最小结构：扇区 16 为主卷描述符，卷空间大小按双端字节序写入。
# 用例覆盖余量缺失、余量不足、余量充足、镜像截断与无 PVD 五种前提，
# 每个用例只破坏一个前提。
#
# Author: Decheng Li <lidecheng@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "iso_pad.py"
SECTOR = 2048
FRAGMENT = 32 * 1024


class IsoPadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.iso = self.root / "test.iso"

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, sectors, slack=0, pvd=True):
        img = bytearray(sectors * SECTOR + slack)
        if pvd:
            off = 16 * SECTOR
            img[off] = 1
            img[off + 1:off + 6] = b"CD001"
            img[off + 6] = 1
            img[off + 80:off + 84] = struct.pack("<I", sectors)
            img[off + 84:off + 88] = struct.pack(">I", sectors)
        self.iso.write_bytes(img)

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args],
                              text=True, capture_output=True)

    def test_pads_when_slack_missing(self):
        self.make(40)
        res = self.run_tool(str(self.iso))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.iso.stat().st_size, 40 * SECTOR + FRAGMENT)

    def test_pads_when_slack_short(self):
        self.make(40, slack=4096)
        self.assertEqual(self.run_tool(str(self.iso)).returncode, 0)
        self.assertEqual(self.iso.stat().st_size, 40 * SECTOR + FRAGMENT)

    def test_keeps_existing_slack(self):
        self.make(40, slack=2 * FRAGMENT)
        self.assertEqual(self.run_tool(str(self.iso)).returncode, 0)
        self.assertEqual(self.iso.stat().st_size, 40 * SECTOR + 2 * FRAGMENT)

    def test_truncated(self):
        self.make(40)
        self.iso.write_bytes(self.iso.read_bytes()[:-1])
        res = self.run_tool(str(self.iso))
        self.assertEqual(res.returncode, 1)
        self.assertIn("截断", res.stderr)

    def test_missing_pvd(self):
        self.make(40, pvd=False)
        res = self.run_tool(str(self.iso))
        self.assertEqual(res.returncode, 1)
        self.assertIn("主卷描述符", res.stderr)

    def test_usage(self):
        self.assertEqual(self.run_tool().returncode, 2)


if __name__ == "__main__":
    unittest.main()
