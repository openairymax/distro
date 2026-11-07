#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_fw_flat.py — 扁平入口生成器的行为用例
#
# 这一层的行为只能在夹具树上验：真实的固件树要几十 GB，而它的全部判据
# 只有三条——「缺入口的补上」「已有的不动」「补完能复核」。三条都是安装
# 事务里发生的事，装机后再发现写错，代价是一台没有无线的机器。
#
# 用 --requests 而不是 modinfo 喂输入：用例要能在没有内核模块的构建机上
# 跑，且输入可读。modinfo 那条路径由 ci/gates/fw-closure.sh 的 ③ 在镜像
# 上验，两者分工不同。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import subprocess
import tempfile
import unittest
from pathlib import Path

FLAT = Path(__file__).resolve().parents[2] / "firmware" / "fw-flat.sh"


class FlatTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fw = self.root / "firmware"
        self.fw.mkdir()
        self.list = self.root / "flat.list"
        self.reqs = self.root / "reqs.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, rel, data=b"\0"):
        path = self.fw / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def want(self, *names):
        self.reqs.write_text("".join(f"{n}\n" for n in names), encoding="utf-8")

    def run_flat(self, verb, *extra):
        return subprocess.run(
            ["sh", str(FLAT), verb, str(self.fw), "--list", str(self.list),
             "--requests", str(self.reqs), *extra],
            capture_output=True, text=True)

    def rows(self):
        if not self.list.exists():
            return []
        return [line.split() for line in self.list.read_text().splitlines() if line]

    def test_apply_links_vendor_layout(self):
        """厂商子目录里的文件补成扁平入口：0.0.3 的 BE200 就是缺这一步。"""
        self.make("intel/iwlwifi/iwlwifi-gl-c0-fm-c0-83.ucode")
        self.make("intel/iwlwifi/iwlwifi-gl-c0-fm-c0.pnvm")
        self.want("iwlwifi-gl-c0-fm-c0-83.ucode",
                  "iwlwifi-gl-c0-fm-c0.pnvm")
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("flat=2 miss=0", res.stdout)
        for name in ("iwlwifi-gl-c0-fm-c0-83.ucode",
                     "iwlwifi-gl-c0-fm-c0.pnvm"):
            link = self.fw / name
            self.assertTrue(link.is_symlink(), name)
            self.assertEqual(link.readlink().as_posix(),
                             f"intel/iwlwifi/{name}")
        self.assertEqual(sorted(self.rows()), [
            ["iwlwifi-gl-c0-fm-c0-83.ucode", "intel/iwlwifi/iwlwifi-gl-c0-fm-c0-83.ucode"],
            ["iwlwifi-gl-c0-fm-c0.pnvm", "intel/iwlwifi/iwlwifi-gl-c0-fm-c0.pnvm"],
        ])

    def test_apply_prefers_shortest(self):
        """树内多处同名时取字符最短的候选，结论不随 find 顺序漂移。"""
        self.make("intel/x.ucode")
        self.make("a/b/c/d/x.ucode")
        self.want("x.ucode")
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.fw / "x.ucode").readlink().as_posix(),
                         "intel/x.ucode")

    def test_apply_keeps_existing_entry(self):
        """基底已提供扁平文件时原样保留：补的是入口，不是内容。"""
        self.make("intel/iwlwifi/x.ucode")
        flat = self.make("x.ucode", b"base")
        self.want("x.ucode")
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("flat=0 miss=0", res.stdout)
        self.assertFalse(flat.is_symlink())
        self.assertEqual(flat.read_bytes(), b"base")
        self.assertEqual(self.rows(), [])

    def test_apply_reports_missing_file(self):
        """树内也没有该文件时不静默：安装日志留一行，现场才知道是缺件。"""
        self.want("y.ucode")
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 0)
        self.assertIn("flat=0 miss=1", res.stdout)
        self.assertIn("miss name=y.ucode", res.stderr)
        self.assertFalse((self.fw / "y.ucode").exists())

    def test_apply_skips_path_requests(self):
        """带目录的请求名由驱动自己走子路径，不需要入口。"""
        self.make("intel/iwlwifi/x.ucode")
        self.want("intel/iwlwifi/x.ucode")
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("flat=0 miss=0", res.stdout)
        self.assertEqual(self.rows(), [])

    def test_apply_is_idempotent(self):
        """重复 apply 不重复计数，清单按本轮实际补的条目重写。"""
        self.make("intel/iwlwifi/x.ucode")
        self.want("x.ucode")
        self.assertEqual(self.run_flat("apply").returncode, 0)
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("flat=0 miss=0", res.stdout)
        self.assertEqual(self.rows(), [])

    def test_apply_fails_without_requests(self):
        """请求名读不到时如实失败：空输入会让清单变空，判定随之假绿。"""
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail=no-requests", res.stderr)
        self.assertFalse(self.list.exists())

    def test_check_passes_after_apply(self):
        """补完立刻能复核：门禁回读的是同一套判据。"""
        self.make("brcm/x.bin")
        self.want("x.bin")
        self.assertEqual(self.run_flat("apply").returncode, 0)
        res = self.run_flat("check")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("rows=1 bad=0", res.stdout)

    def test_check_accepts_baseline_file(self):
        """基线后来自己提供了同名文件时，不再需要软链，复核仍应通过。"""
        self.make("brcm/x.bin")
        self.want("x.bin")
        self.assertEqual(self.run_flat("apply").returncode, 0)
        link = self.fw / "x.bin"
        link.unlink()
        link.write_bytes(b"base")
        res = self.run_flat("check")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_check_fails_on_wrong_link(self):
        """软链被指到别处必须判负：内核按名取到错文件比取不到更难查。"""
        self.make("brcm/x.bin")
        self.make("brcm/y.bin")
        self.want("x.bin")
        self.assertEqual(self.run_flat("apply").returncode, 0)
        link = self.fw / "x.bin"
        link.unlink()
        link.symlink_to("brcm/y.bin")
        res = self.run_flat("check")
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail=wrong-link name=x.bin", res.stderr)

    def test_check_fails_on_missing_entry(self):
        """入口被删必须判负：这是「文件在但取不到」的复发形态。"""
        self.make("brcm/x.bin")
        self.want("x.bin")
        self.assertEqual(self.run_flat("apply").returncode, 0)
        (self.fw / "x.bin").unlink()
        res = self.run_flat("check")
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail=no-entry name=x.bin", res.stderr)

    def test_apply_links_compressed_variant(self):
        """树内只留 .zst 时入口名带后缀：内核按 <name>.zst 再取一次。

        SP3 的 intel/iwlwifi/ 全是 .ucode.zst（未压缩 0 个）。补成无后缀
        的链会让内核把压缩流当裸文件解析，因此链接名必须保留真实后缀。
        """
        self.make("intel/iwlwifi/x.ucode.zst")
        self.want("x.ucode")
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("flat=1 miss=0", res.stdout)
        link = self.fw / "x.ucode.zst"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.readlink().as_posix(),
                         "intel/iwlwifi/x.ucode.zst")
        self.assertEqual(self.rows(),
                         [["x.ucode.zst", "intel/iwlwifi/x.ucode.zst"]])

    def test_apply_prefers_uncompressed(self):
        """未压缩候选优先于 .zst/.xz：少一次解压，且与内核探测顺序一致。"""
        self.make("a/x.ucode")
        self.make("intel/iwlwifi/x.ucode.zst")
        self.want("x.ucode")
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.fw / "x.ucode").readlink().as_posix(),
                         "a/x.ucode")

    def test_apply_compressed_is_idempotent(self):
        """压缩入口同样幂等：第二轮不该把已有链判成 miss。"""
        self.make("intel/iwlwifi/x.ucode.zst")
        self.want("x.ucode")
        self.assertEqual(self.run_flat("apply").returncode, 0)
        res = self.run_flat("apply")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("flat=0 miss=0", res.stdout)

    def test_check_passes_compressed(self):
        """压缩入口的复核与未压缩同判据。"""
        self.make("intel/iwlwifi/x.ucode.zst")
        self.want("x.ucode")
        self.assertEqual(self.run_flat("apply").returncode, 0)
        res = self.run_flat("check")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("rows=1 bad=0", res.stdout)

    def test_source_leaves_script_inert(self):
        """被 kickstart 段展开时正文只定义函数：不解析位置参数、不早退。

        %pre 把正文原样贴在脚本段里，$0 是安装器临时脚本。这里用 $0=sh
        复现同一形态，正文若在末尾无条件执行就会把整段安装脚本带偏。
        """
        res = subprocess.run(
            ["sh", "-c", '. "$1"; printf "sourced\\n"', "sh", str(FLAT)],
            capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("sourced", res.stdout)

    def test_usage_needs_list(self):
        """缺清单路径是用法错误，与判定失败分开报。"""
        res = subprocess.run(["sh", str(FLAT), "apply", str(self.fw)],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
