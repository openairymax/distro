#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_airy_inspect.py — airy-kernel / airy-os 身份报告回归
#
# 两个命令共用一份实现，按 argv[0] 基名分派。分派错、取不到值时省略行、
# 非法入口不以 2 退出，这三种缺陷都不会让构建失败，只会在现场演示时把
# 「没采到」显示成「没有这一项」。这里用一棵冻结的静态根固定契约：静态
# 模式不查 rpm 数据库也不取 uname(2)，每个字段都有取值或显式 absent，
# 用法错误以 2 退出、帮助以 0 退出。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
SCRIPT = BASE / "desktop" / "airy_inspect.py"
REL = "6.6.157-alk"
IMAGE = b"AirymaxOS test kernel image\n"

# 字段集是契约本身：少一行说明采集退化，多一行说明同一事实被两处各写
# 了一遍。顺序也一并钉住，输出被人用 diff 比对时才有意义。
KERNEL_KEYS = (
    "kernel.release", "kernel.version", "kernel.machine", "kernel.build",
    "kernel.cmdline", "image.path", "image.bytes", "image.sha256",
    "image.owner", "map.path", "config.path", "config.security_airy",
    "config.airy_syscall", "config.airy_corekern", "config.airy_log",
    "config.airy_ipc", "config.airy_agent_tracing",
    "config.airy_cap_table_size", "ksym.airy", "module.count",
)
OS_KEYS = (
    "os.id", "os.name", "os.pretty", "os.version", "os.version_id",
    "os.variant", "host.name", "pkg.release", "pkg.system", "pkg.kernel",
    "repo.path", "repo.sections", "cpu.model", "cpu.count", "mem.total_kb",
    "disk.root.source", "disk.root.fstype", "session.autologin",
)

CFG = (
    "CONFIG_SECURITY_AIRY=y",
    "CONFIG_AIRY_SYSCALL=y",
    "CONFIG_AIRY_COREKERN=y",
    "CONFIG_AIRY_LOG=y",
    "CONFIG_AIRY_IPC=y",
    "CONFIG_AIRY_AGENT_TRACING=y",
    "CONFIG_AIRY_CAP_TABLE_SIZE=1024",
    "CONFIG_EXT4_FS=y",
)


def fixture(root):
    """铺一棵内核身份与整机身份都齐备的静态根。"""
    files = {
        "proc/sys/kernel/osrelease": REL + "\n",
        "proc/sys/kernel/version": "#1 SMP PREEMPT_DYNAMIC AirymaxOS\n",
        "proc/version": "Linux version %s (builder@airymax) #1 SMP\n" % REL,
        "proc/cmdline": "BOOT_IMAGE=/vmlinuz-%s rhgb quiet\n" % REL,
        "proc/kallsyms": "0000000000000000 T airy_dispatch\n"
                         "0000000000000000 t airy_ipc_send\n"
                         "0000000000000000 D vfs_read\n",
        "proc/cpuinfo": "processor\t: 0\nmodel name\t: Airymax Test CPU\n\n"
                        "processor\t: 1\nmodel name\t: Airymax Test CPU\n\n",
        "proc/meminfo": "MemTotal:       16000000 kB\nMemFree:   1024 kB\n",
        "proc/mounts": "/dev/nvme0n1p3 / xfs rw,relatime 0 0\n",
        "lib/modules/%s/modules.dep" % REL:
            "kernel/fs/ext4/ext4.ko:\n"
            "kernel/drivers/nvme/nvme.ko:\n",
        "boot/System.map-%s" % REL: "ffffffff81000000 T airy_dispatch\n",
        "boot/config-%s" % REL: "\n".join(CFG) + "\n",
        "usr/lib/os-release": 'ID=airymaxos\nNAME="AirymaxOS"\n'
                              'PRETTY_NAME="AirymaxOS 0.0.3 (OpenAirymax)"\n'
                              'VERSION="0.0.3"\nVERSION_ID="0.0.3"\n'
                              'VARIANT_ID="workstation"\n',
        "etc/hostname": "AIRYMAX_PC\n",
        "etc/yum.repos.d/airymaxos.repo":
            "[airymaxos-baseos]\nname=AirymaxOS BaseOS\n"
            "[airymaxos-appstream]\nname=AirymaxOS AppStream\n",
        "etc/lightdm/lightdm.conf.d/50-airymax.conf":
            "[Seat:*]\nautologin-user=Airymax\n",
    }
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    image = root / "boot" / ("vmlinuz-%s" % REL)
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(IMAGE)
    return root


def invoke(bin_dir, name, *args):
    """按装机后的调用路径执行：先建同名符号链接，再以该路径启动。"""
    link = bin_dir / name
    if not link.exists():
        link.symlink_to(SCRIPT)
    return subprocess.run([sys.executable, str(link)] + list(args),
                          capture_output=True, text=True, check=False)


def pairs(stdout):
    """把 <mark> key=value 还原成有序键值对，值保留引号原样。"""
    out = []
    for line in stdout.splitlines():
        _mark, sep, rest = line.partition(" ")
        if not sep:
            continue
        key, eq, value = rest.partition("=")
        out.append((key, value) if eq else (key, ""))
    return out


class InspectStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.root = fixture(base / "root")
        cls.bin = base / "bin"
        cls.bin.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def report(self, name, root=None):
        out = invoke(self.bin, name, "--root", str(root or self.root))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout.splitlines()

    def test_kernel_key_set(self):
        lines = self.report("airy-kernel")
        self.assertEqual([key for key, _ in pairs("\n".join(lines))],
                         list(KERNEL_KEYS))
        self.assertTrue(all(line.startswith("AIRYMAX-KERNEL ")
                            for line in lines))

    def test_kernel_identity_and_image(self):
        lines = self.report("airy-kernel")
        for want in (
                "kernel.release=%s" % REL,
                "kernel.version=\"#1 SMP PREEMPT_DYNAMIC AirymaxOS\"",
                "kernel.build=\"Linux version %s (builder@airymax) #1 SMP\""
                % REL,
                "kernel.machine=absent",
                "image.path=%s/boot/vmlinuz-%s" % (self.root, REL),
                "image.bytes=%d" % len(IMAGE),
                "image.sha256=%s" % hashlib.sha256(IMAGE).hexdigest(),
                # 静态模式不查 rpm 数据库：归属只能写 absent，不能猜
                "image.owner=absent",
                "map.path=%s/boot/System.map-%s" % (self.root, REL),
                "config.path=%s/boot/config-%s" % (self.root, REL)):
            self.assertIn("AIRYMAX-KERNEL " + want, lines)

    def test_kernel_cmdline_is_quoted(self):
        lines = self.report("airy-kernel")
        self.assertIn('AIRYMAX-KERNEL kernel.cmdline='
                      '"BOOT_IMAGE=/vmlinuz-%s rhgb quiet"' % REL, lines)

    def test_kernel_own_config_and_symbols(self):
        lines = self.report("airy-kernel")
        for want in ("config.security_airy=y", "config.airy_syscall=y",
                     "config.airy_corekern=y", "config.airy_log=y",
                     "config.airy_ipc=y", "config.airy_agent_tracing=y",
                     "config.airy_cap_table_size=1024",
                     # 只数 airy_ 前缀，vfs_read 不计入
                     "ksym.airy=2",
                     "module.count=2"):
            self.assertIn("AIRYMAX-KERNEL " + want, lines)

    def test_os_key_set(self):
        lines = self.report("airy-os")
        self.assertEqual([key for key, _ in pairs("\n".join(lines))],
                         list(OS_KEYS))
        self.assertTrue(all(line.startswith("AIRYMAX-OS ") for line in lines))

    def test_os_identity_and_host(self):
        lines = self.report("airy-os")
        for want in ("os.id=airymaxos",
                     "os.name=AirymaxOS",
                     'os.pretty="AirymaxOS 0.0.3 (OpenAirymax)"',
                     "os.version=0.0.3",
                     "os.version_id=0.0.3",
                     "os.variant=workstation",
                     "host.name=AIRYMAX_PC",
                     "repo.sections=2",
                     "session.autologin=Airymax"):
            self.assertIn("AIRYMAX-OS " + want, lines)

    def test_os_hardware_and_packages(self):
        lines = self.report("airy-os")
        for want in ("cpu.model=\"Airymax Test CPU\"", "cpu.count=2",
                     "mem.total_kb=16000000",
                     "disk.root.source=/dev/nvme0n1p3",
                     "disk.root.fstype=xfs",
                     "pkg.release=absent", "pkg.system=absent",
                     "pkg.kernel=absent"):
            self.assertIn("AIRYMAX-OS " + want, lines)


class InspectMissingTest(unittest.TestCase):
    """取不到就显式 absent：省略行会让「没采到」与「没有这一项」同形。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.root = base / "empty"
        cls.root.mkdir()
        cls.bin = base / "bin"
        cls.bin.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_empty_root_reports_absent(self):
        for name, keys in (("airy-kernel", KERNEL_KEYS),
                           ("airy-os", OS_KEYS)):
            out = invoke(self.bin, name, "--root", str(self.root))
            self.assertEqual(out.returncode, 0, out.stderr)
            got = pairs(out.stdout)
            self.assertEqual([key for key, _ in got], list(keys))
            for key, value in got:
                self.assertEqual(value, "absent", "%s %s" % (name, key))

    def test_missing_root_is_static_too(self):
        # 路径不存在与路径为空是同一种事实，不能靠退出码区分
        out = invoke(self.bin, "airy-kernel",
                     "--root", str(self.root / "nope"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("AIRYMAX-KERNEL kernel.release=absent",
                      out.stdout.splitlines())


class InspectUsageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bin = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_unknown_entry_rejected(self):
        # 直接跑 airy_inspect.py 是未知入口：静默挑一个命令执行会让人
        # 以为另一个也跑过了
        out = invoke(self.bin, "airy_inspect.py")
        self.assertEqual(out.returncode, 2)
        self.assertIn("用法错误", out.stderr)
        self.assertEqual(out.stdout, "")

    def test_bad_args_rejected(self):
        for args in (["--root"], ["--root", "/tmp", "extra"], ["--nope"]):
            out = invoke(self.bin, "airy-os", *args)
            self.assertEqual(out.returncode, 2, args)

    def test_help_succeeds(self):
        for flag in ("-h", "--help"):
            out = invoke(self.bin, "airy-kernel", flag)
            self.assertEqual(out.returncode, 0)
            self.assertIn("airy-kernel", out.stdout)
            self.assertIn("airy-os", out.stdout)

    def test_live_mode_uses_uname(self):
        # 无 --root 即活体：release 必须与 uname(2) 一致，而不是读 procfs
        out = invoke(self.bin, "airy-kernel")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("AIRYMAX-KERNEL kernel.release=%s" % os.uname().release,
                      out.stdout.splitlines())
        self.assertIn("AIRYMAX-KERNEL kernel.machine=%s" % os.uname().machine,
                      out.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
