#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_install_test.py — scripts/install-test.sh 契约回归测试
#
# 装机验收依赖 QEMU 与 OVMF/AAVMF，开发机与 CI 未必具备。脚本对外契约
# 是：TAP 计划、退出码、产物布局、启动墙钟上限与固件腿选择。这里用
# PATH 沙箱提供伪 qemu-system-* 与 qemu-img，并以 --fw-dir 指向临时
# 固件目录，从而在无虚拟化环境下判定真实控制流。每个用例只破坏一个
# 前提，避免多重故障互相掩盖。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import fakes

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install-test.sh"
DISTRO = SCRIPT.parent.parent
BASH = shutil.which("bash") or "/bin/bash"


class InstallTestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "out"
        self.out.mkdir()
        self.iso = self.root / "airymaxos.iso"
        self.iso.write_text("fake iso\n", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.qlog = self.root / "qemu.log"
        self.fwdir = self.root / "fw"
        self.fwdir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def tools(self, arch="x86_64", qemu=True):
        fakes.link_tools(self.bin)
        fakes.qemu_tools(self.bin, arch, qemu)

    def firmware(self, prefix="OVMF", vars_=True):
        (self.fwdir / f"{prefix}_CODE_4M.fd").write_text(
            "code\n", encoding="utf-8")
        if vars_:
            (self.fwdir / f"{prefix}_VARS_4M.fd").write_text(
                "vars\n", encoding="utf-8")

    def run_script(self, *args, **extra):
        env = {"PATH": str(self.bin), "HOME": str(self.root),
               "FAKE_QEMU_LOG": str(self.qlog)}
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def install(self, *args, **extra):
        return self.run_script("--iso", str(self.iso), "--out", str(self.out),
                               *args, **extra)

    def taps(self, res):
        return [line for line in res.stdout.splitlines()
                if line.startswith(("ok ", "not ok "))]

    def manifest(self):
        return (self.out / "install-manifest.txt").read_text(encoding="utf-8")

    def test_help(self):
        self.tools()
        res = self.run_script("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("用法", res.stdout)

    def test_missing_iso_arg(self):
        self.tools()
        res = self.run_script("--out", str(self.out))
        self.assertEqual(res.returncode, 5)

    def test_iso_absent(self):
        self.tools()
        res = self.run_script("--iso", str(self.root / "gone.iso"),
                              "--out", str(self.out))
        self.assertEqual(res.returncode, 5)

    def test_bad_arch(self):
        self.tools()
        self.assertEqual(self.install("--arch", "sparc").returncode, 5)

    def test_bad_firmware(self):
        self.tools()
        self.assertEqual(self.install("--firmware", "coreboot").returncode, 5)

    def test_aarch64_bios(self):
        self.tools("aarch64")
        res = self.install("--arch", "aarch64", "--firmware", "bios")
        self.assertEqual(res.returncode, 5)

    def test_runs_not_number(self):
        self.tools()
        self.assertEqual(self.install("--runs", "many").returncode, 5)

    def test_runs_zero(self):
        self.tools()
        self.assertEqual(self.install("--runs", "0").returncode, 5)

    def test_out_in_source(self):
        self.tools()
        target = DISTRO / ".install-test-tmp"
        res = self.run_script("--iso", str(self.iso), "--out", str(target),
                              "--runs", "1")
        self.assertEqual(res.returncode, 5)
        self.assertFalse(target.exists())

    def test_missing_qemu(self):
        self.tools(qemu=False)
        res = self.install("--runs", "1")
        self.assertEqual(res.returncode, 77)
        self.assertIn("1..0 # SKIP", res.stdout)

    def test_success(self):
        self.tools()
        res = self.install("--runs", "1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("1..2", res.stdout)
        self.assertEqual(len(self.taps(res)), 2)
        self.assertTrue(all(line.startswith("ok ") for line in self.taps(res)))
        self.assertIn("boot bios run 1", res.stdout)
        manifest = self.manifest()
        self.assertRegex(manifest, r"iso [0-9a-f]{64} airymaxos\.iso")
        self.assertIn("arch=x86_64", manifest)
        self.assertIn("firmware=bios", manifest)
        self.assertIn("runs=1", manifest)
        self.assertIn("max_boot=30", manifest)
        self.assertIn("run bios run=1 install=pass", manifest)
        self.assertRegex(manifest, r"run bios run=1 boot=pass boot_s=\d+")
        self.assertIn("result=pass", manifest)
        self.assertTrue((self.out / "run-bios-1" / "disk.qcow2").is_file())
        self.assertTrue((self.out / "run-bios-1" / "install.log").is_file())
        self.assertTrue((self.out / "run-bios-1" / "boot.log").is_file())

    def test_cpu_model(self):
        self.tools()
        res = self.install("--runs", "1")
        self.assertEqual(res.returncode, 0, res.stderr)
        args = self.qlog.read_text(encoding="utf-8").splitlines()
        cpu = args[args.index("-cpu") + 1]
        if "-accel" in args:
            self.assertEqual(cpu, "host")
        else:
            self.assertEqual(cpu, "max")

    def test_install_fail(self):
        self.tools()
        res = self.install("--runs", "1", FAKE_QEMU_INSTALL_MODE="fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1", res.stdout)
        self.assertIn("run bios run=1 install=fail", self.manifest())
        self.assertIn("result=fail", self.manifest())

    def test_install_panic_fast(self):
        self.tools()
        start = time.monotonic()
        res = self.install("--runs", "1", "--install-timeout", "60",
                           FAKE_QEMU_INSTALL_MODE="panic")
        elapsed = time.monotonic() - start
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1", res.stdout)
        self.assertIn("install failure pattern", res.stderr)
        self.assertLess(elapsed, 30)

    def test_install_post_fail_fast(self):
        self.tools()
        start = time.monotonic()
        res = self.install("--runs", "1", "--install-timeout", "60",
                           FAKE_QEMU_INSTALL_MODE="postfail")
        elapsed = time.monotonic() - start
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1", res.stdout)
        self.assertIn("install failure pattern", res.stderr)
        self.assertLess(elapsed, 30)

    def test_install_scriptlet_fast(self):
        self.tools()
        start = time.monotonic()
        res = self.install("--runs", "1", "--install-timeout", "60",
                           FAKE_QEMU_INSTALL_MODE="scriptlet")
        elapsed = time.monotonic() - start
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1", res.stdout)
        self.assertIn("install failure pattern", res.stderr)
        self.assertIn("按 ENTER 退出", res.stderr)
        self.assertLess(elapsed, 30)

    def test_install_bootloader_fast(self):
        self.tools()
        start = time.monotonic()
        res = self.install("--runs", "1", "--install-timeout", "60",
                           FAKE_QEMU_INSTALL_MODE="bootloader")
        elapsed = time.monotonic() - start
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1", res.stdout)
        self.assertIn("install failure pattern", res.stderr)
        self.assertIn("请回答 'yes' 或 'no'", res.stderr)
        self.assertLess(elapsed, 30)

    def test_install_payload_fast(self):
        self.tools()
        start = time.monotonic()
        res = self.install("--runs", "1", "--install-timeout", "60",
                           FAKE_QEMU_INSTALL_MODE="payload")
        elapsed = time.monotonic() - start
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1", res.stdout)
        self.assertIn("install failure pattern", res.stderr)
        self.assertIn("安装负载时出现以下错误", res.stderr)
        self.assertLess(elapsed, 30)

    def test_install_timeout(self):
        self.tools()
        start = time.monotonic()
        res = self.install("--runs", "1", "--install-timeout", "2",
                           FAKE_QEMU_INSTALL_MODE="hang")
        elapsed = time.monotonic() - start
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1", res.stdout)
        self.assertIn("install timeout", res.stderr)
        self.assertLess(elapsed, 15)

    def test_install_fail_skips_boot(self):
        self.tools()
        res = self.install("--runs", "1", FAKE_QEMU_INSTALL_MODE="fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)
        self.assertIn("skipped: install failed", res.stdout)
        self.assertIn("run bios run=1 boot=skip", self.manifest())
        self.assertFalse((self.out / "run-bios-1" / "boot.log").exists())
        self.assertEqual(self.qlog.read_text(encoding="utf-8").count("-serial"),
                         1)

    def test_gpu_device(self):
        self.tools()
        res = self.install("--runs", "1")
        self.assertEqual(res.returncode, 0, res.stderr)
        args = self.qlog.read_text(encoding="utf-8").splitlines()
        self.assertEqual(args[args.index("-vga") + 1], "virtio")

    def test_install_marker_missing(self):
        self.tools()
        res = self.install("--runs", "1", FAKE_QEMU_INSTALL_MODE="nomarker")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1", res.stdout)

    def test_boot_panic(self):
        self.tools()
        res = self.install("--runs", "1", FAKE_QEMU_BOOT_MODE="panic")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)
        self.assertIn("run bios run=1 boot=fail", self.manifest())

    def test_boot_unit_text_not_fatal(self):
        # 单元失败的串口文本只做归因：启动腿必须继续等到标记，
        # 否则桌面是否进得去永远没有证据。
        self.tools()
        res = self.install("--runs", "1", FAKE_QEMU_BOOT_MODE="noisy")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("run bios run=1 boot=pass", self.manifest())
        self.assertIn("boot unit failures: sshd.service", res.stderr)

    def test_boot_degraded_fails(self):
        self.tools()
        res = self.install("--runs", "1", FAKE_QEMU_BOOT_MODE="degraded")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)
        self.assertIn("run bios run=1 boot=fail", self.manifest())
        self.assertIn("boot failure pattern", res.stderr)

    def test_boot_marker_missing(self):
        self.tools()
        res = self.install("--runs", "1", FAKE_QEMU_BOOT_MODE="nomarker")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)

    def test_desktop_boot_marker(self):
        self.tools()
        res = self.install("--runs", "1",
                           "--boot-marker", "AIRYMAX-DESKTOP-READY")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ok 2", res.stdout)
        self.assertIn("max_boot=auto", self.manifest())

    def test_desktop_boot_cap(self):
        self.tools()
        res = self.install("--runs", "1", "--max-boot", "0",
                           "--boot-marker", "AIRYMAX-DESKTOP-READY",
                           FAKE_QEMU_BOOT_MODE="desktop-slow")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)
        self.assertIn("took", res.stderr)

    def test_desktop_marker_missing(self):
        self.tools()
        res = self.install("--runs", "1",
                           "--boot-marker", "AIRYMAX-DESKTOP-READY",
                           FAKE_QEMU_BOOT_MODE="login-only")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)

    def test_desktop_probe_fail(self):
        self.tools()
        res = self.install("--runs", "1",
                           "--boot-marker", "AIRYMAX-DESKTOP-READY",
                           FAKE_QEMU_BOOT_MODE="desktop-fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)
        self.assertIn("boot failure pattern", res.stderr)

    def test_smoke_boot_marker(self):
        self.tools()
        res = self.install("--runs", "1",
                           "--boot-marker", "AIRYMAX-SMOKE-PASS",
                           FAKE_QEMU_BOOT_MODE="smoke-pass")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ok 2", res.stdout)
        self.assertIn("max_boot=auto", self.manifest())

    def test_smoke_marker_missing(self):
        self.tools()
        res = self.install("--runs", "1",
                           "--boot-marker", "AIRYMAX-SMOKE-PASS",
                           FAKE_QEMU_BOOT_MODE="login-only")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)

    def test_smoke_fail_pattern(self):
        self.tools()
        res = self.install("--runs", "1",
                           "--boot-marker", "AIRYMAX-SMOKE-PASS",
                           FAKE_QEMU_BOOT_MODE="smoke-fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)
        self.assertIn("boot failure pattern", res.stderr)

    def test_boot_timeout(self):
        self.tools()
        res = self.install("--runs", "1", "--boot-timeout", "2",
                           FAKE_QEMU_BOOT_MODE="hang")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)

    def test_boot_too_slow(self):
        self.tools()
        res = self.install("--runs", "1", "--max-boot", "0",
                           FAKE_QEMU_BOOT_MODE="slow")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 2", res.stdout)
        self.assertIn("took", res.stderr)

    def test_qemu_img_fail(self):
        self.tools()
        res = self.install("--runs", "1", FAKE_QEMU_IMG_MODE="fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1", res.stdout)

    def test_uefi_missing_firmware(self):
        self.tools()
        res = self.install("--runs", "1", "--firmware", "uefi",
                           "--fw-dir", str(self.fwdir))
        self.assertEqual(res.returncode, 5)
        self.assertIn("UEFI", res.stderr)

    def test_uefi_pflash(self):
        self.tools()
        self.firmware()
        res = self.install("--runs", "1", "--firmware", "uefi",
                           "--fw-dir", str(self.fwdir))
        self.assertEqual(res.returncode, 0, res.stderr)
        run = self.out / "run-uefi-1"
        self.assertEqual((run / "vars.fd").read_text(encoding="utf-8"),
                         "vars\nBOOTENTRY\n")
        args = self.qlog.read_text(encoding="utf-8")
        self.assertEqual(args.count("-serial"), 2)
        self.assertIn("if=pflash,format=raw,readonly=on,file=", args)
        self.assertIn(f"if=pflash,format=raw,file={run}/vars.fd", args)

    def test_uefi_without_vars(self):
        self.tools()
        self.firmware(vars_=False)
        res = self.install("--runs", "1", "--firmware", "uefi",
                           "--fw-dir", str(self.fwdir))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("-bios", self.qlog.read_text(encoding="utf-8"))

    def test_firmware_both(self):
        self.tools()
        self.firmware()
        res = self.install("--runs", "1", "--firmware", "both",
                           "--fw-dir", str(self.fwdir))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("1..4", res.stdout)
        self.assertEqual(len(self.taps(res)), 4)
        manifest = self.manifest()
        self.assertIn("run bios run=1 install=pass", manifest)
        self.assertIn("run uefi run=1 install=pass", manifest)

    def test_firmware_both_without_uefi(self):
        """缺 OVMF 时 both 降级为 BIOS 腿，而不是整轮以参数错误退出。"""
        self.tools()
        res = self.install("--runs", "1", "--firmware", "both",
                           "--fw-dir", str(self.fwdir))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("UEFI 腿降级", res.stderr)
        self.assertIn("1..2", res.stdout)
        self.assertEqual(len(self.taps(res)), 2)
        manifest = self.manifest()
        self.assertIn("firmware=bios", manifest)
        self.assertNotIn("uefi", manifest)

    def test_aarch64_scsi(self):
        self.tools("aarch64")
        self.firmware("AAVMF")
        res = self.install("--arch", "aarch64", "--firmware", "uefi",
                           "--runs", "1", "--fw-dir", str(self.fwdir))
        self.assertEqual(res.returncode, 0, res.stderr)
        args = self.qlog.read_text(encoding="utf-8")
        self.assertIn("-machine", args)
        self.assertIn("virt", args)
        self.assertIn("virtio-scsi-pci", args)
        self.assertIn("scsi-cd", args)
        self.assertIn("virtio-gpu-pci", args)
        self.assertIn("AAVMF_CODE_4M.fd", args)


if __name__ == "__main__":
    unittest.main()
