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

import os
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

    def test_name_also_a_directory(self):
        """名字集里 a/b 与 a/b/c 并存时以目录为先，与真树的索引同形。

        固件包用目录符号链接表达布局时，同一路径既是条目又是若干条目的
        前缀。先建文件会让后续建目录 ENOTDIR，整轮预演中止在第一条冲突。
        """
        self.have("a/b", "a/b/c")
        self.want("c")
        res = self.run_pre()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("flat=1 miss=0", res.stdout)

    def test_tree_failure_names_the_entry(self):
        """骨架建不起来时报出条目与 errno，不能只留一个 no-tree。"""
        self.have("a" * 300)
        self.want("x.ucode")
        res = self.run_pre()
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail=no-tree", res.stdout)
        self.assertIn("bad=1", res.stdout)

    def test_unreadable_names_fail(self):
        """名字集读不到时如实失败，不退化成「零个固件、全部命中」。"""
        res = subprocess.run(
            ["sh", str(PRE), "--firmware", str(self.root / "absent"),
             "--modules", str(self.mods), "--arch", "x86_64"],
            capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail=no-tree", res.stdout)


class ExemptTest(unittest.TestCase):
    """豁免表：不支持类器件记账，表外缺件照旧判负。

    豁免不是「把 miss 改写成 0」的口令，它是「这一类器件本版不支持」的账。
    用例要同时钉住两半：命中的不计入、未命中的仍判负。只钉前半边的话，一
    张写错通配的表就能把全部缺件静音，而日志里只剩一个 miss=0。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fw = self.root / "names.txt"
        self.mods = self.root / "modules"
        self.mods.mkdir()
        self.reqs = self.root / "reqs.txt"
        self.exempt = self.root / "exempt.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def have(self, *rels):
        self.fw.write_text("".join(f"{r}\n" for r in rels), encoding="utf-8")

    def want(self, *names):
        self.reqs.write_text("".join(f"{n}\n" for n in names), encoding="utf-8")

    def table(self, *rows):
        self.exempt.write_text("".join(f"{r}\n" for r in rows), encoding="utf-8")

    def run_pre(self, *extra):
        return subprocess.run(
            ["sh", str(PRE), "--firmware", str(self.fw),
             "--modules", str(self.mods), "--arch", "x86_64",
             "--requests", str(self.reqs), "--exempt", str(self.exempt),
             *extra],
            capture_output=True, text=True)

    def test_hit_is_excluded_with_reason(self):
        """命中豁免的缺件不进 miss，且日志留下名字与原因。"""
        self.have("intel/keep.bin")
        self.want("keep.bin", "iwlwifi-6000-6.ucode")
        self.table("# 注释与空行都要跳过", "",
                   "iwlwifi-bz-*    Wi-Fi 7 BZ 族，矩阵内无此类网卡",
                   "iwlwifi-6000-*  Centrino 6000 旧卡")
        res = self.run_pre()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("flat=1 miss=0", res.stdout)
        self.assertIn("exempt name=iwlwifi-6000-6.ucode", res.stderr)
        self.assertIn("Centrino 6000", res.stderr)

    def test_miss_outside_table_still_fails(self):
        """表里没有的缺件照旧判负，逐条报出名字。"""
        self.have("intel/keep.bin")
        self.want("keep.bin", "iwlwifi-bz-a0-gf-a0-83.ucode",
                  "iwlwifi-ma-a0-gf-a0-83.ucode")
        self.table("iwlwifi-bz-*  Wi-Fi 7 BZ 族")
        res = self.run_pre()
        self.assertEqual(res.returncode, 1)
        self.assertIn("miss=1", res.stdout)
        self.assertIn("miss name=iwlwifi-ma-a0-gf-a0-83.ucode", res.stderr)
        self.assertNotIn("exempt name=iwlwifi-ma", res.stderr)

    def test_unreadable_table_is_usage_error(self):
        """豁免表读不到时按用法错误退 2，不把「读不到」当成「没有豁免」。"""
        self.have("intel/keep.bin")
        self.want("keep.bin")
        self.exempt.unlink(missing_ok=True)
        res = self.run_pre()
        self.assertEqual(res.returncode, 2)


class RpmModeTest(unittest.TestCase):
    """构建期的取件形式：名字集与模块树从 RPM 就地生成。

    这一层只能验取件失败时的判定，取件成功的那半边要真 RPM 与真 kmod，
    由 image-build 的四架构作业覆盖。失败侧仍必须验：缺件若退化成「零个
    固件、全部命中」，预演就变成了恒绿的装饰。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fw = self.root / "names.txt"
        self.fw.write_text("intel/iwlwifi/x.ucode\n", encoding="utf-8")
        self.mods = self.root / "modules"
        self.mods.mkdir()
        self.reqs = self.root / "reqs.txt"
        self.reqs.write_text("x.ucode\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def run_pre(self, *args, env=None):
        return subprocess.run(["sh", str(PRE), *args],
                              capture_output=True, text=True, env=env)

    def env(self, **over):
        return {**os.environ, **over}

    def test_firmware_forms_are_exclusive(self):
        """两种固件取件形式同时给出时无法确定读哪一份，按用法错误退 2。"""
        res = self.run_pre("--firmware", str(self.fw),
                           "--firmware-rpm", str(self.root / "a.rpm"),
                           "--modules", str(self.mods), "--arch", "x86_64")
        self.assertEqual(res.returncode, 2)

    def test_modules_forms_are_exclusive(self):
        res = self.run_pre("--firmware", str(self.fw),
                           "--modules", str(self.mods),
                           "--modules-rpm", str(self.root / "a.rpm"),
                           "--arch", "x86_64")
        self.assertEqual(res.returncode, 2)

    def test_firmware_rpm_unreadable(self):
        """固件包读不出名字集时判负，而不是当成空固件树。"""
        res = self.run_pre("--firmware-rpm", str(self.root / "absent.rpm"),
                           "--modules", str(self.mods),
                           "--requests", str(self.reqs), "--arch", "x86_64",
                           env=self.env(AIRY_RPM="/bin/false"))
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-FW-PREFLIGHT arch=x86_64 fail=no-firmware",
                      res.stdout)

    def test_two_firmware_rpms_are_unioned(self):
        """清单里每个提供包都要读：只读一个会把另一个包的条目报成缺件。

        镜像的固件树是几个包的并集（linux-firmware + wireless-regdb），
        run 42797570216 的 regulatory.db 假缺件就是只读了前者。
        """
        rpm = self.root / "fakerpm"
        rpm.write_text(
            "#!/bin/sh\n"
            "case \"$2\" in\n"
            "*one.rpm) printf '/usr/lib/firmware/intel/x.ucode\\n' ;;\n"
            "*two.rpm) printf '/usr/lib/firmware/brcm/y.bin\\n' ;;\n"
            "esac\n", encoding="utf-8")
        rpm.chmod(0o755)
        reqs = self.root / "reqs2.txt"
        reqs.write_text("x.ucode\ny.bin\n", encoding="utf-8")
        res = self.run_pre("--firmware-rpm", str(self.root / "one.rpm"),
                           "--firmware-rpm", str(self.root / "two.rpm"),
                           "--modules", str(self.mods),
                           "--requests", str(reqs), "--arch", "x86_64",
                           env=self.env(AIRY_RPM=str(rpm)))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("flat=2 miss=0", res.stdout)

    def test_firmware_rpm_no_rpm(self):
        """缺 rpm 与包坏是两回事：前者报工具缺席，别让人去查 RPM。"""
        res = self.run_pre("--firmware-rpm", str(self.root / "absent.rpm"),
                           "--modules", str(self.mods), "--arch", "x86_64",
                           env=self.env(AIRY_RPM="/nonexistent/rpm"))
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-FW-PREFLIGHT arch=x86_64 fail=no-rpm",
                      res.stdout)

    def test_modules_rpm_unreadable(self):
        """模块包解不开时判负：没有请求名就没有判据。"""
        res = self.run_pre("--firmware", str(self.fw),
                           "--modules-rpm", str(self.root / "absent.rpm"),
                           "--arch", "aarch64",
                           env=self.env(AIRY_RPM2CPIO="/bin/false",
                                        AIRY_CPIO="/bin/false"))
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-FW-PREFLIGHT arch=aarch64 fail=no-modules",
                      res.stdout)

    def test_modules_rpm_no_rpm2cpio(self):
        """解包工具缺席时单独成案，和模块包坏掉分得开。"""
        res = self.run_pre("--firmware", str(self.fw),
                           "--modules-rpm", str(self.root / "absent.rpm"),
                           "--arch", "riscv64",
                           env=self.env(AIRY_RPM2CPIO="/nonexistent/rpm2cpio"))
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-FW-PREFLIGHT arch=riscv64 fail=no-rpm2cpio",
                      res.stdout)

    def test_modules_rpm_no_cpio(self):
        """解包器缺席时同样单独成案。"""
        res = self.run_pre("--firmware", str(self.fw),
                           "--modules-rpm", str(self.root / "absent.rpm"),
                           "--arch", "loongarch64",
                           env=self.env(AIRY_RPM2CPIO="/bin/true",
                                        AIRY_CPIO="/nonexistent/cpio"))
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-FW-PREFLIGHT arch=loongarch64 fail=no-cpio",
                      res.stdout)


if __name__ == "__main__":
    unittest.main()
