#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_build_iso.py — scripts/build-iso.sh 契约回归测试
#
# mkksiso/xorriso/implantisomd5 在开发机与 CI 中未必可用，而退出码、
# 产物布局与三重校验（ks 逐字节、inst.ks、stage2 卷标）属于对外契约。
# 这里用 PATH 沙箱替换镜像工具：伪 mkksiso 按真实语义把 kickstart 放到
# ISO 根目录并写入 inst.ks，伪 xorriso 从同一镜像回读，从而让校验逻辑
# 在无 root、无镜像工具的环境下仍可判定。每个用例只破坏一个前提。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import fakes

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build-iso.sh"
DISTRO = SCRIPT.parent.parent
BASH = shutil.which("bash") or "/bin/bash"
BASELINE = DISTRO / "kickstart" / "airymaxos-minimal.ks"


class BuildIsoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "out"
        self.out.mkdir()
        self.base = self.root / "base.iso"
        self.base.write_text("fake base iso\n", encoding="utf-8")
        self.ks = self.root / "airymaxos.ks"
        self.ks.write_text(BASELINE.read_text(encoding="utf-8"),
                           encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "mkksiso.log"

    def tearDown(self):
        self._tmp.cleanup()

    def tools(self, *extra):
        fakes.link_tools(self.bin)
        for name, body in extra:
            fakes.write(self.bin, name, body)

    def full(self, *extra):
        self.tools(*extra)
        fakes.iso_tools(self.bin)

    def run_script(self, *args, **extra):
        env = {"PATH": str(self.bin), "HOME": str(self.root),
               "FAKE_MKKSISO_LOG": str(self.log)}
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def build(self, *args, **extra):
        return self.run_script("--iso", str(self.base), "--ks", str(self.ks),
                               "--out", str(self.out), *args, **extra)

    def test_help(self):
        self.tools()
        res = self.run_script("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("用法", res.stdout)

    def test_missing_iso(self):
        self.tools()
        res = self.run_script("--ks", str(self.ks), "--out", str(self.out))
        self.assertEqual(res.returncode, 5)

    def test_out_in_source(self):
        self.tools()
        target = DISTRO / ".build-iso-test"
        res = self.run_script("--iso", str(self.base), "--ks", str(self.ks),
                              "--out", str(target))
        self.assertEqual(res.returncode, 5)
        self.assertFalse(target.exists())

    def test_bad_arch(self):
        self.full()
        self.assertEqual(self.build("--arch", "sparc").returncode, 5)

    def test_bad_volid(self):
        self.full()
        self.assertEqual(self.build("--volid", "airymaxos").returncode, 5)

    def test_long_volid(self):
        self.full()
        self.assertEqual(self.build("--volid", "A" * 33).returncode, 5)

    def test_missing_add(self):
        self.full()
        res = self.build("--add", str(self.root / "gone"))
        self.assertEqual(res.returncode, 5)

    def test_missing_mkksiso(self):
        self.tools(("xorriso", fakes.XORRISO), ("implantisomd5", fakes.IMPLANT))
        self.assertEqual(self.build().returncode, 11)

    def test_missing_implant(self):
        self.tools(("mkksiso", fakes.MKKSISO), ("xorriso", fakes.XORRISO))
        self.assertEqual(self.build().returncode, 11)

    def test_ks_lint_fail(self):
        self.full()
        self.ks.write_text("lang zh_CN.UTF-8\n", encoding="utf-8")
        self.assertEqual(self.build().returncode, 5)

    def test_mkksiso_fail(self):
        self.full()
        self.assertEqual(
            self.build(FAKE_MKKSISO_MODE="fail").returncode, 6)

    def test_ks_mismatch(self):
        self.full()
        self.assertEqual(
            self.build(FAKE_MKKSISO_MODE="badks").returncode, 6)

    def test_missing_inst_ks(self):
        self.full()
        self.assertEqual(
            self.build(FAKE_MKKSISO_MODE="nostage").returncode, 6)

    def test_stage2_mismatch(self):
        self.full()
        self.assertEqual(
            self.build(FAKE_MKKSISO_MODE="badlabel").returncode, 6)

    def test_dest_exists(self):
        self.full()
        self.assertEqual(self.build("--arch", "x86_64").returncode, 0)
        self.assertEqual(self.build("--arch", "x86_64").returncode, 2)

    def test_build_success(self):
        self.full()
        res = self.build("--arch", "x86_64")
        self.assertEqual(res.returncode, 0, res.stderr)
        iso = self.out / "airymaxos-0.0.3-x86_64.iso"
        self.assertTrue(iso.is_file())
        digest = hashlib.sha256(iso.read_bytes()).hexdigest()
        self.assertEqual((iso.parent / f"{iso.name}.sha256").read_text(
            encoding="utf-8"), f"{digest}  {iso.name}\n")
        manifest = (self.out / "iso-manifest.txt").read_text(
            encoding="utf-8")
        self.assertIn("name=airymaxos-0.0.3-x86_64.iso", manifest)
        self.assertIn("volid=AIRYMAXOS", manifest)
        self.assertRegex(manifest, r"iso [0-9a-f]{64} airymaxos-0\.0\.3")
        self.assertRegex(manifest, r"base [0-9a-f]{64} base\.iso")
        self.assertIn("cmd=console=ttyS0,115200",
                      self.log.read_text(encoding="utf-8"))
        self.assertIn("IMPLANTED", iso.read_text(encoding="utf-8"))

    def test_version_override(self):
        self.full()
        res = self.build("--arch", "x86_64", "--version", "9.9.9")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("不一致", res.stderr)
        self.assertTrue(
            (self.out / "airymaxos-9.9.9-x86_64.iso").is_file())

    def test_no_md5(self):
        self.tools(("mkksiso", fakes.MKKSISO), ("xorriso", fakes.XORRISO))
        res = self.build("--arch", "x86_64", "--no-md5")
        self.assertEqual(res.returncode, 0, res.stderr)
        iso = self.out / "airymaxos-0.0.3-x86_64.iso"
        self.assertNotIn("IMPLANTED", iso.read_text(encoding="utf-8"))

    def test_gpg_key(self):
        self.full(("gpg", fakes.GPG))
        res = self.build("--arch", "x86_64", "--gpg-key", "test")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(
            (self.out / "airymaxos-0.0.3-x86_64.iso.asc").is_file())


if __name__ == "__main__":
    unittest.main()
