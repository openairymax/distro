#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_kernel_spec.py — 内核配方结构回归测试
#
# 内核构建周期长，配方中的三步法顺序、生成式源码声明、initramfs 安装期
# 契约与包矩阵一旦漂移，只有在真实装机时才会暴露。这里以纯文本断言把
# 这些不变量前移到秒级门禁，避免把问题留到镜像阶段。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import spec_lint

SPEC = ROOT / "specs" / "kernel" / "airymaxos-kernel.spec"

REQUIRED = (
    "CONFIG_SECURITY=y",
    "CONFIG_SECURITY_AIRY=y",
    "CONFIG_AIRY_SYSCALL=y",
    "CONFIG_AIRY_COREKERN=y",
    "CONFIG_AIRY_LOG=y",
    "CONFIG_AIRY_IPC=y",
    "CONFIG_AIRY_AGENT_TRACING=y",
    "CONFIG_AIRY_CAP_TABLE_SIZE=1024",
    "CONFIG_IO_URING=y",
)


def sections(text):
    out = {}
    for name, arg, num in spec_lint.parse_secs(text.splitlines()):
        out.setdefault((name, arg), num)
    return out


def body(text, sec, arg=""):
    lines = text.splitlines()
    start = None
    for name, found, num in spec_lint.parse_secs(lines):
        if start is not None:
            return "\n".join(lines[start:num - 1])
        if (name, found) == (sec, arg):
            start = num
    return "\n".join(lines[start:]) if start is not None else ""


def norm(text):
    return "\n".join(" ".join(line.split()) for line in text.splitlines())


class KernelSpecTest(unittest.TestCase):
    def setUp(self):
        self.text = SPEC.read_text(encoding="utf-8")
        self.macros = spec_lint.collect_macros(self.text.splitlines())
        self.tags = spec_lint.parse_tags(self.text.splitlines())

    def test_lint_clean(self):
        self.assertEqual(spec_lint.lint_spec(SPEC, ROOT), [])

    def test_package_matrix(self):
        names = [arg for sec, arg in sections(self.text) if sec == "package"]
        self.assertEqual(names, ["core", "modules", "headers", "devel",
                                 "tools"])

    def test_version_matches_os_release(self):
        raw = self.tags["Version"][1]
        self.assertEqual(spec_lint.expand(raw, self.macros), "0.0.3")

    def test_generated_source_declared(self):
        source = spec_lint.expand(self.tags["Source0"][1], self.macros)
        self.assertIn("spec-lint: generated-source " + source,
                      self.text)

    def test_three_step_config(self):
        build = body(self.text, "build")
        order = [build.find("make ARCH=%{karch} defconfig"),
                 build.find("merge_config.sh -m .config"),
                 build.find("make ARCH=%{karch} olddefconfig")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn(-1, order)

    def test_localversion(self):
        self.assertIn('CONFIG_LOCALVERSION="%{kernel_local}"', self.text)
        self.assertIn("%global kernel_local -agentrt", self.text)
        self.assertIn("%global kernel_release %{kernel_version}"
                      "%{kernel_local}", self.text)

    def test_initramfs_contract(self):
        post = body(self.text, "post", "core")
        self.assertIn("dracut --force "
                      "/boot/initramfs-%{kernel_release}.img", post)
        self.assertIn("exit 1", post)
        self.assertIn("rm -f /boot/initramfs-%{kernel_release}.img",
                      body(self.text, "preun", "core"))

    def test_initramfs_unowned(self):
        lines = self.text.splitlines()
        secs = spec_lint.parse_secs(lines)
        for pos, (name, _arg, num) in enumerate(secs):
            if name != "files":
                continue
            end = secs[pos + 1][2] - 1 if pos + 1 < len(secs) else len(lines)
            self.assertNotIn("initramfs", "\n".join(lines[num:end]))

    def test_check_required_configs(self):
        check = body(self.text, "check")
        for item in REQUIRED:
            self.assertIn("grep -qx '%s'" % item, check)

    def test_check_reads_vmlinux(self):
        check = body(self.text, "check")
        self.assertIn("readelf -h %{ksrc}/vmlinux", check)
        self.assertNotIn("readelf -h %{buildroot}", check)

    def test_headers_layout(self):
        self.assertNotIn("/usr/include/uapi", self.text)
        self.assertIn("%{_includedir}/*", body(self.text, "files", "headers"))

    def test_kernel_identity(self):
        main = norm(self.text.split("%package core")[0])
        core = norm(body(self.text, "package", "core"))
        modules = norm(body(self.text, "package", "modules"))
        self.assertIn("Provides: kernel = %{kernel_version}", main)
        self.assertIn("Provides: installonlypkg(kernel)", main)
        self.assertIn("Obsoletes: kernel", main)
        self.assertIn("Provides: kernel-core = %{kernel_version}", core)
        self.assertIn("Provides: kernel-uname-r = %{kernel_release}", core)
        self.assertIn("Obsoletes: kernel-core", core)
        self.assertIn("Provides: kernel-modules = %{kernel_version}", modules)
        self.assertIn("Obsoletes: kernel-modules", modules)

    def test_no_debuginfo(self):
        self.assertIn("%global debug_package %{nil}", self.text)


if __name__ == "__main__":
    unittest.main()
