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
import tempfile
import unittest
from pathlib import Path

DISTRO = Path(__file__).resolve().parents[2]
FW_SPEC = DISTRO / "specs" / "airymaxos-firmware.spec"
KERNEL_SPEC = DISTRO / "specs" / "kernel" / "airymaxos-kernel.spec"
MANIFEST = DISTRO / "firmware" / "fw-manifest.txt"
CLOSURE = DISTRO / "scripts" / "lib" / "closure.sh"
KS_DIR = DISTRO / "kickstart"
PACKAGE = "airymaxos-firmware"

GLOBAL = re.compile(r"^%global\s+([A-Za-z_][\w]*)\s+(.+?)\s*$", re.M)
REQUIRES = re.compile(r"^Requires:\s*(.+?)\s*$", re.M)
# %post 到下一个段落之间的正文。兼容链接的全部逻辑都在这里，装机首启能否
# 连上 Wi-Fi 取决于它，因此按可执行代码测，不按「写了注释」测。
POST = re.compile(r"^%post\s*$(.*?)(?=^%[a-z]+)", re.M | re.S)
PREFIX = "%{_prefix}"


def globals_of(text):
    return {name: value for name, value in GLOBAL.findall(text)}


def requires_of(text):
    return set(REQUIRES.findall(text))


def read(path):
    return path.read_text(encoding="utf-8")


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


def alias_script(root):
    """把 %post 正文里的 %{_prefix} 换成沙箱前缀后返回可执行脚本。"""
    found = POST.search(read(FW_SPEC))
    if not found:
        raise AssertionError("固件包没有 %post，兼容链接无从生成")
    return found.group(1).replace(PREFIX, str(root / "usr"))


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
        declared = requires_of(read(FW_SPEC))
        self.assertEqual(declared, wanted,
                         "固件包 Requires 与 fw-manifest.txt 的包集合不一致")

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

    def run_alias(self, root):
        return subprocess.run(["sh", "-c", alias_script(root)],
                              capture_output=True, text=True)

    def test_wifi_alias_links_flat_names(self):
        """每个 intel/ 下的固件都要在固件根上有同名条目：内核只认扁平名，
        缺一条就是首启「未发现 Wi-Fi 设备」。.pnvm 与 .ucode 同等对待。"""
        names = ("iwlwifi-gl-c0-fm-c0-83.ucode", "iwlwifi-gl-c0-fm-c0.pnvm")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "usr" / "lib" / "firmware" / "intel" / "iwlwifi"
            src.mkdir(parents=True)
            for name in names:
                (src / name).write_bytes(b"\0")
            res = self.run_alias(root)
            self.assertEqual(res.returncode, 0, res.stderr)
            for name in names:
                link = root / "usr" / "lib" / "firmware" / name
                self.assertTrue(link.is_symlink(), name)
                self.assertEqual(link.readlink(), Path("intel/iwlwifi") / name)

    def test_wifi_alias_keeps_base_files(self):
        """基底自带扁平文件时原样保留：链接是补齐手段，不是覆盖手段。"""
        name = "iwlwifi-1000-5.ucode"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "usr" / "lib" / "firmware" / "intel" / "iwlwifi"
            src.mkdir(parents=True)
            (src / name).write_bytes(b"\0")
            flat = root / "usr" / "lib" / "firmware" / name
            flat.write_bytes(b"base")
            res = self.run_alias(root)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertFalse(flat.is_symlink())
            self.assertEqual(flat.read_bytes(), b"base")

    def test_wifi_alias_noop_on_flat_layout(self):
        """基底回到扁平布局时脚本不产生任何条目，也不会因缺目录而失败。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fw = root / "usr" / "lib" / "firmware"
            fw.mkdir(parents=True)
            res = self.run_alias(root)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(list(fw.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
