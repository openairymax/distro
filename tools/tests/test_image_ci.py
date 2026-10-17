#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_image_ci.py — ci/run-image-ci.sh 契约回归测试
#
# 编排器的价值在于把五个阶段串成单一门禁：任何一段失败都必须让整体
# 退出码非零，跳过必须显式可见。这里用 PATH 沙箱替代 QEMU 与镜像工具，
# 以预构建 ISO 和真实 build-iso 两条路径分别验证编排与产物定位。
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

SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "run-image-ci.sh"
DISTRO = SCRIPT.parent.parent
BASH = shutil.which("bash") or "/bin/bash"
BASE_ISO = DISTRO / "kickstart" / "airymaxos-minimal.ks"


class ImageCiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "out"
        self.iso = self.root / "airymaxos.iso"
        self.iso.write_text("fake iso\n", encoding="utf-8")
        self.digest = hashlib.sha256(self.iso.read_bytes()).hexdigest()
        self.sums = self.root / "airymaxos.iso.sha256"
        self.write_sum()
        self.base = self.root / "base.iso"
        self.base.write_text("fake base\n", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fakes.link_tools(self.bin)
        self.qlog = self.root / "qemu.log"

    def tearDown(self):
        self._tmp.cleanup()

    def write_sum(self, digest=None, name="airymaxos.iso"):
        self.sums.write_text(f"{digest or self.digest}  {name}\n",
                             encoding="utf-8")

    def tools(self, arch="x86_64", qemu=True, iso=False, desk=False):
        fakes.qemu_tools(self.bin, arch, qemu)
        if desk:
            fakes.desk_tools(self.bin)
        elif iso:
            fakes.iso_tools(self.bin)

    def desk_rpms(self):
        directory = self.root / "desk-rpms"
        directory.mkdir()
        for name in ("airymaxos-release-0.0.3-1.noarch.rpm",
                     "airymaxos-kernel-6.6.0-1.x86_64.rpm",
                     "airymaxos-kernel-core-6.6.0-1.x86_64.rpm",
                     "airymaxos-kernel-modules-6.6.0-1.x86_64.rpm"):
            (directory / name).write_text(f"rpm {name}\n",
                                          encoding="utf-8")
        return directory

    def run_script(self, *args, **extra):
        env = {"PATH": str(self.bin), "HOME": str(self.root),
               "FAKE_QEMU_LOG": str(self.qlog)}
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def ci(self, *args, **extra):
        return self.run_script("--out", str(self.out), *args, **extra)

    def pre(self, *args, **extra):
        return self.ci("--iso", str(self.iso), "--skip-rpms",
                       "--skip-kernel", "--skip-iso", *args, **extra)

    def manifest(self):
        return (self.out / "image-ci-manifest.txt").read_text(
            encoding="utf-8")

    def test_help(self):
        res = self.run_script("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("用法", res.stdout)

    def test_missing_out(self):
        self.assertEqual(self.run_script().returncode, 5)

    def test_bad_arch(self):
        self.assertEqual(
            self.ci("--iso", str(self.iso), "--arch", "sparc").returncode, 5)

    def test_bad_firmware(self):
        self.assertEqual(
            self.ci("--iso", str(self.iso), "--firmware", "coreboot",
                    "--skip-install").returncode, 5)

    def test_bad_profile(self):
        self.assertEqual(
            self.ci("--iso", str(self.iso), "--profile", "live",
                    "--skip-install").returncode, 5)

    def test_desktop_needs_rpms(self):
        self.assertEqual(
            self.ci("--iso-base", str(self.base), "--profile", "desktop",
                    "--skip-rpms", "--skip-kernel",
                    "--skip-install").returncode, 5)

    def test_runs_zero(self):
        self.assertEqual(
            self.ci("--iso", str(self.iso), "--runs", "0",
                    "--skip-install").returncode, 5)

    def test_no_iso(self):
        self.assertEqual(self.ci("--skip-rpms", "--skip-kernel").returncode, 5)

    def test_skip_iso_without_iso(self):
        self.assertEqual(self.ci("--skip-iso", "--skip-rpms").returncode, 5)

    def test_iso_absent(self):
        res = self.ci("--iso", str(self.root / "gone.iso"), "--skip-install")
        self.assertEqual(res.returncode, 5)

    def test_iso_base_absent(self):
        res = self.ci("--iso-base", str(self.root / "gone.iso"),
                      "--skip-install")
        self.assertEqual(res.returncode, 5)

    def test_aarch64_bios(self):
        self.assertEqual(
            self.ci("--iso", str(self.iso), "--arch", "aarch64",
                    "--skip-install").returncode, 5)

    def test_out_in_source(self):
        target = DISTRO / ".image-ci-tmp"
        res = self.run_script("--out", str(target), "--iso", str(self.iso),
                              "--skip-install")
        self.assertEqual(res.returncode, 5)
        self.assertFalse(target.exists())

    def test_all_skip(self):
        res = self.pre("--skip-install")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("1..5", res.stdout)
        self.assertEqual(res.stdout.count("# SKIP"), 5)
        manifest = self.manifest()
        for stage in ("rpm=skip", "kernel=skip", "iso=skip",
                      "checksum=skip", "install=skip"):
            self.assertIn(f"stage {stage}", manifest)
        self.assertRegex(manifest, r"iso [0-9a-f]{64} airymaxos\.iso")
        self.assertIn("result=pass", manifest)

    def test_prebuilt_success(self):
        self.tools()
        res = self.pre("--runs", "1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ok 4 - iso checksum", res.stdout)
        self.assertIn("ok 5 - install test", res.stdout)
        manifest = self.manifest()
        self.assertIn("stage checksum=pass", manifest)
        self.assertIn("stage install=pass", manifest)
        self.assertIn("firmware=bios", manifest)
        self.assertIn("runs=1", manifest)
        self.assertIn("result=pass", manifest)

    def test_checksum_missing(self):
        self.tools()
        self.sums.unlink()
        res = self.pre("--runs", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 4", res.stdout)
        self.assertIn("stage checksum=fail", self.manifest())
        self.assertIn("result=fail", self.manifest())

    def test_checksum_mismatch(self):
        self.tools()
        self.write_sum(digest="0" * 64)
        res = self.pre("--runs", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 4", res.stdout)

    def test_checksum_name_mismatch(self):
        self.tools()
        self.write_sum(name="other.iso")
        res = self.pre("--runs", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 4", res.stdout)

    def test_install_fail(self):
        self.tools()
        res = self.pre("--runs", "1", FAKE_QEMU_INSTALL_MODE="fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 5", res.stdout)
        self.assertIn("stage install=fail", self.manifest())

    def test_missing_qemu(self):
        self.tools(qemu=False)
        res = self.pre("--runs", "1")
        self.assertEqual(res.returncode, 77)
        self.assertIn("# SKIP QEMU", res.stdout)
        manifest = self.manifest()
        self.assertIn("stage install=skip", manifest)
        self.assertIn("result=pass", manifest)

    def test_full_chain(self):
        self.tools(iso=True)
        res = self.ci("--iso-base", str(self.base),
                      "--ks", str(BASE_ISO), "--arch", "x86_64",
                      "--runs", "1", "--skip-rpms", "--skip-kernel")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ok 3 - iso assembly", res.stdout)
        self.assertIn("ok 4 - iso checksum", res.stdout)
        self.assertIn("ok 5 - install test", res.stdout)
        manifest = self.manifest()
        self.assertIn("stage iso=pass", manifest)
        self.assertRegex(manifest, r"iso [0-9a-f]{64} airymaxos-")
        self.assertIn("result=pass", manifest)

    def test_desktop_chain(self):
        self.tools(desk=True)
        rpms = self.desk_rpms()
        res = self.ci("--iso-base", str(self.base), "--profile", "desktop",
                      "--arch", "x86_64", "--rpms", str(rpms), "--runs", "1",
                      "--skip-rpms", "--skip-kernel")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ok 3 - iso assembly", res.stdout)
        self.assertIn("ok 4 - iso checksum", res.stdout)
        self.assertIn("ok 5 - install test", res.stdout)
        manifest = self.manifest()
        self.assertIn("profile=desktop", manifest)
        self.assertIn("stage iso=pass", manifest)
        iso = self.out / "desktop" / "iso" / "airymaxos-0.0.3-x86_64.iso"
        self.assertTrue(iso.is_file())
        self.assertIn("airymaxos-offline", iso.read_text(encoding="utf-8"))
        self.assertIn("=== /airymax/payload-manifest.txt",
                      iso.read_text(encoding="utf-8"))

    def test_source_date_epoch(self):
        self.tools()
        res = self.pre("--runs", "1", SOURCE_DATE_EPOCH="1700000000")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("source_date_epoch=1700000000", self.manifest())

    def test_install_skipped_checksum(self):
        self.tools()
        res = self.pre("--skip-install")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("stage checksum=skip", self.manifest())


if __name__ == "__main__":
    unittest.main()
