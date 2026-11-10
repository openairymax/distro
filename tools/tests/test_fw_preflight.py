#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_fw_preflight.py — 构建期固件预演的行为用例
#
# 这一层的判据只有一条：**该架构模块请求的固件名，镜像的固件树里有没有**。
# 它必须在装机之前给出结论，因为 riscv64 没有实机、ARM 的板载无线在 QEMU
# 里不出现，唯一的兜底就是构建期这一次预演。
#
# 用例用 --requests 喂请求名而不是解析真实模块树：构建机上没有目标架构的
# .ko，而这一层要验的是「骨架 + 补齐 + 计数」这条链，不是 modinfo 本身
# （modinfo 那条路径由 image-build 在装了 kernel-modules 的容器里走）。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.5
# ===========================================================================

import subprocess
import tempfile
import unittest
from pathlib import Path

PRE = Path(__file__).resolve().parents[2] / "ci" / "fw-preflight.sh"


class PreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fw = self.root / "names.txt"
        self.mods = self.root / "modules"
        self.mods.mkdir()
        self.reqs = self.root / "reqs.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def have(self, *rels):
        self.fw.write_text("".join(f"{r}\n" for r in rels), encoding="utf-8")

    def want(self, *names):
        self.reqs.write_text("".join(f"{n}\n" for n in names), encoding="utf-8")

    def run_pre(self, *extra):
        return subprocess.run(
            ["sh", str(PRE), "--firmware", str(self.fw),
             "--modules", str(self.mods), "--arch", "aarch64",
             "--requests", str(self.reqs), *extra],
            capture_output=True, text=True)

    def test_all_hits(self):
        """名字集覆盖请求名即通过，自证行带架构与两个计数。"""
        self.have("intel/iwlwifi/x.ucode", "README", "brcm/y.bin")
        self.want("x.ucode", "y.bin")
        res = self.run_pre()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("AIRYMAX-FW-PREFLIGHT arch=aarch64 flat=2 miss=0",
                      res.stdout)

    def test_missing_names_fail(self):
        """缺件必须判负，并逐条报出请求名原文，而不是只给一个计数。"""
        self.have("intel/iwlwifi/x.ucode")
        self.want("x.ucode", "brcmfmac4356-pcie.bin")
        res = self.run_pre()
        self.assertEqual(res.returncode, 1)
        self.assertIn("miss=1", res.stdout)
        self.assertIn("miss name=brcmfmac4356-pcie.bin", res.stderr)

    def test_compressed_suffix_kept(self):
        """树里只有 .zst 时入口名带真实后缀，与安装期同一规则。"""
        self.have("intel/iwlwifi/x.ucode.zst")
        self.want("x.ucode")
        res = self.run_pre()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("flat=1 miss=0", res.stdout)

    def test_empty_module_tree_fails(self):
        """空模块树不是「无需补齐」：没有请求名就无从判定，必须判负。"""
        self.have("intel/iwlwifi/x.ucode")
        self.reqs.unlink(missing_ok=True)
        res = subprocess.run(
            ["sh", str(PRE), "--firmware", str(self.fw),
             "--modules", str(self.root / "absent"), "--arch", "riscv64"],
            capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-FW-PREFLIGHT arch=riscv64 fail=no-requests",
                      res.stdout)

    def test_empty_request_list_fails(self):
        """空请求清单同样判负：这是 modinfo 缺席最容易长成的假绿形态。"""
        self.have("intel/iwlwifi/x.ucode")
        self.reqs.write_text("", encoding="utf-8")
        res = self.run_pre()
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail=no-requests", res.stdout)

    def test_usage_needs_arch(self):
        """三个必填缺一即用法错误，与判定失败分开报。"""
        res = subprocess.run(
            ["sh", str(PRE), "--firmware", str(self.fw),
             "--modules", str(self.mods)],
            capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)

    def test_unreadable_names_fail(self):
        """名字集读不到时如实失败，不退化成「零个固件、全部命中」。"""
        res = subprocess.run(
            ["sh", str(PRE), "--firmware", str(self.root / "absent"),
             "--modules", str(self.mods), "--arch", "x86_64"],
            capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail=no-tree", res.stdout)


if __name__ == "__main__":
    unittest.main()
