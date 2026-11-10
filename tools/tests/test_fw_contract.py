#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_fw_contract.py — 固件闭包与内核 ABI 的同源断言（FW-02）
#
# 固件闭包这件事有四个各自独立的落点：内核按 ABI 点名固件包、固件包按清单
# 点名固件提供包、配方把固件包装进镜像、闭包求解把清单里的包留在事务里。
# 任何一处单独看都「已完成」，四处一起看才发现名字对不上——0.0.3 的固件
# 就是这样：包在、清单在，内核与固件的对应关系没人声明。
#
# 这里按集合对账，不按「写到就算」：清单第一列必须与固件包的 Requires 相等
# 且不多不少，内核点名的 ABI 必须与固件包提供的 ABI 逐字相同。新增一类
# 器件时只改清单就会红，促使两处一起改。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import re
import subprocess
import unittest
from pathlib import Path

DISTRO = Path(__file__).resolve().parents[2]
FW_SPEC = DISTRO / "specs" / "airymaxos-firmware.spec"
KERNEL_SPEC = DISTRO / "specs" / "kernel" / "airymaxos-kernel.spec"
MANIFEST = DISTRO / "firmware" / "fw-manifest.txt"
FLAT = DISTRO / "firmware" / "fw-flat.sh"
CLOSURE = DISTRO / "scripts" / "lib" / "closure.sh"
KS_DIR = DISTRO / "kickstart"
PACKAGE = "airymaxos-firmware"
# 非固件提供包的功能依赖：对账时剔除，避免清单被迫写进工具包名。
INFRA = {"kmod"}

GLOBAL = re.compile(r"^%global\s+([A-Za-z_][\w]*)\s+(.+?)\s*$", re.M)
REQUIRES = re.compile(r"^Requires:\s*(.+?)\s*$", re.M)
# %posttrans 到下一个段落之间的正文。扁平入口的全部安装期逻辑都在这里，
# 装机首启能否连上 Wi-Fi 取决于它，因此按可执行代码测，不按「写了注释」测。
POSTTRANS = re.compile(r"^%posttrans\s*$(.*?)(?=^%[a-z]+)", re.M | re.S)


def globals_of(text):
    return {name: value for name, value in GLOBAL.findall(text)}


def requires_of(text):
    return set(REQUIRES.findall(text))


def read(path):
    return path.read_text(encoding="utf-8")


def posttrans_body():
    found = POSTTRANS.search(read(FW_SPEC))
    if not found:
        raise AssertionError("固件包没有 %posttrans，扁平入口无从生成")
    return found.group(1)


def manifest_pkgs():
    pkgs = set()
    for line in read(MANIFEST).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) == 3:
            pkgs.add(fields[0])
    return pkgs


def ks_pkgs():
    got = set()
    for path in sorted(KS_DIR.glob("*.ks")):
        for line in read(path).splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "%", "-")):
                got.add(line)
    return got


class FirmwareContractTest(unittest.TestCase):
    def test_kernel_names_abi(self):
        """内核按 ABI 点名固件包，ABI 由内核版本派生而非另写一个数。"""
        text = read(KERNEL_SPEC)
        abi = globals_of(text)
        self.assertIn("kernel_version", abi)
        self.assertEqual(abi.get("kernel_abi"), "%{kernel_version}")
        self.assertIn(f"{PACKAGE}-%{{kernel_abi}}", requires_of(text))

    def test_abi_matches(self):
        """固件包声明的 ABI 与内核版本逐字相同，抬基线时两边不会各改各的。"""
        want = globals_of(read(KERNEL_SPEC))["kernel_version"]
        got = globals_of(read(FW_SPEC)).get("kernel_abi")
        self.assertEqual(got, want)

    def test_fw_provides_abi(self):
        """元包形态与 ABI 声明：noarch，且 Provides 用内核同一个宏展开。"""
        text = read(FW_SPEC)
        for pat in (rf"^Name:[ \t]+{PACKAGE}[ \t]*$",
                    r"^BuildArch:[ \t]+noarch[ \t]*$",
                    rf"^Provides:[ \t]+{PACKAGE}-%{{kernel_abi}}[ \t]*="):
            self.assertRegex(text, re.compile(pat, re.M), pat)

    def test_fw_requires_manifest(self):
        """固件包的 Requires 与清单第一列相等：清单加一类器件必须同时加依赖。"""
        wanted = manifest_pkgs()
        self.assertTrue(wanted)
        # kmod 是生成器的功能依赖（%posttrans 用 modinfo 读驱动声明），
        # 不是固件提供包，对账时剔除；它本身由下面单独断言。
        declared = requires_of(read(FW_SPEC)) - INFRA
        self.assertEqual(declared, wanted,
                         "固件包 Requires 与 fw-manifest.txt 的包集合不一致")

    def test_fw_installs_generator(self):
        """生成器随包落盘、被 %posttrans 调用，且清单是它声明的产物。

        这三件事必须同时成立：只装脚本不调用则入口永远补不上；只调用不装
        则装机后第一次升级就断；清单不声明为 %ghost 会被 rpm 当成未拥有
        文件，校验和漂移看不见。
        """
        text = read(FW_SPEC)
        self.assertRegex(text, re.compile(r"^Source1:[ \t]+fw-flat\.sh[ \t]*$", re.M))
        self.assertIn("%{_libexecdir}/airymaxos/fw-flat.sh", text)
        self.assertRegex(text, re.compile(
            r"^%ghost[ \t]+%\{_datadir\}/airymaxos/firmware/firmware-flat\.list", re.M))
        self.assertTrue(FLAT.is_file(), "缺少 distro/firmware/fw-flat.sh")

    def test_fw_posttrans_applies_flat(self):
        """%posttrans 调生成器补入口，且不写死任何厂商目录。

        0.0.3 的缺陷形态是「文件在 intel/iwlwifi/ 下，内核按裸名取不到」。
        写死目录只能修 Intel Wi-Fi，brcmfmac/ath11k/mt76/rtw88 与 ARM、
        RISC-V 的主用无线仍会复发，所以判据是「调用生成器」而不是「出现
        某个路径」。
        """
        body = posttrans_body()
        code = "\n".join(line for line in body.splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertIn("fw-flat.sh apply", code)
        self.assertIn("--list %{_datadir}/airymaxos/firmware/firmware-flat.list",
                      code)
        self.assertIn("--modules %{_prefix}/lib/modules", code)
        self.assertNotIn("intel/iwlwifi", code)
        self.assertIn("%{_localstatedir}/log/airymaxos/firmware-flat.log", code,
                      "自证行必须落盘：%posttrans 的 stdout 不进 install.log，"
                      "目标系统跑没跑过本节只能靠它判")
        self.assertIn("kmod", requires_of(read(FW_SPEC)),
                      "生成器依赖 modinfo，缺 kmod 时静默不补入口")

    def test_preflight_shares_flat_rules(self):
        """构建期预演复用同一份补齐实现，且不写死厂商目录。

        预演若自己列一套规则，预演绿了装机照样缺件；写死厂商目录则只能覆盖
        Intel Wi-Fi，ARM 与 RISC-V 的主用无线不在 intel/ 下。
        """
        pre = DISTRO / "ci" / "fw-preflight.sh"
        self.assertTrue(pre.is_file(), "缺少 distro/ci/fw-preflight.sh")
        text = pre.read_text(encoding="utf-8")
        self.assertIn("firmware/fw-flat.sh", text)
        for vendor in ("intel/iwlwifi", "brcm/", "ath11k", "rtw88", "mt76"):
            self.assertNotIn(vendor, text)
        self.assertIn("AIRYMAX-FW-PREFLIGHT arch=", text,
                      "预演必须留一行带架构名的自证行")

    def test_ks_installs_package(self):
        """两个剖面都显式列出固件包，镜像里缺它在事务阶段就失败。"""
        got = ks_pkgs()
        self.assertIn(PACKAGE, got)

    def test_scope_keeps_packages(self):
        """闭包作用域把清单里的包与固件包一起点名，排除项裁不掉它们。"""
        out = subprocess.run(
            ["bash", "-c", f'. "{CLOSURE}" && cl_scope "{MANIFEST}"'],
            capture_output=True, text=True, check=True)
        got = set(out.stdout.split())
        self.assertEqual(got, manifest_pkgs() | {PACKAGE})


if __name__ == "__main__":
    unittest.main()
