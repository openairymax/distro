#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_build_desktop.py — scripts/build-desktop.sh 契约回归测试
#
# 桌面镜像的离线仓库是安装闭包的唯一来源：缺少发行版标识、内核或其
# core/modules 子包时，kickstart 的包组与 %post 校验必然失败。这里以
# PATH 沙箱替代镜像与仓库工具，逐项破坏前提，验证退出码、载荷布局、
# group 元数据与 ISO 回读一致性。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import gzip
import hashlib
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import fakes

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build-desktop.sh"
DISTRO = SCRIPT.parent.parent
BASH = shutil.which("bash") or "/bin/bash"
KS = DISTRO / "kickstart" / "airymaxos-workstation.ks"
COMPS = DISTRO / "comps" / "airymaxos-comps.xml"
APP_OFF = 16 * 2048 + 883

CLOSURE = (
    "airymaxos-release-0.0.3-1.noarch.rpm",
    "airymaxos-system-0.0.3-1.noarch.rpm",
    "airymaxos-kernel-6.6.0-1.x86_64.rpm",
    "airymaxos-kernel-core-6.6.0-1.x86_64.rpm",
    "airymaxos-kernel-modules-6.6.0-1.x86_64.rpm",
)


def comps_pkgs():
    root = ET.parse(COMPS).getroot()
    return {node.text.strip() for node in root.iter("packagereq")
            if node.text and node.text.strip()}


def rpm_name(name):
    bits = name[:-4].rsplit(".", 1)[0].split("-")
    return "-".join(bits[:-2]) if len(bits) >= 3 else name[:-4]


# 伪 dnf 的事务是「comps 全量成员 + 一个非组成员」；本地仓库已有的包
# 复用同一文件名，收割端按文件名去重，所以新增数就是组内尚未在载荷里的包。
STOCK = {rpm_name(name) for name in CLOSURE}
HARVEST = len(comps_pkgs() - STOCK)
TOTAL = len(CLOSURE) + HARVEST


class BuildDesktopTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "out"
        self.out.mkdir()
        self.base = self.root / "base.iso"
        self.base.write_text("fake base iso\n", encoding="utf-8")
        self.rpms = self.root / "rpms"
        self.rpms.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "mkksiso.log"

    def tearDown(self):
        self._tmp.cleanup()

    def write_rpm(self, directory, name, body=None):
        path = Path(directory) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body or f"rpm {name}\n", encoding="utf-8")
        return path

    def stock(self, directory=None):
        directory = directory or self.rpms
        for name in CLOSURE:
            self.write_rpm(directory, name)

    def tools(self, *extra):
        fakes.link_tools(self.bin)
        fakes.desk_tools(self.bin)
        for name, body in extra:
            fakes.write(self.bin, name, body)

    def run_script(self, *args, **extra):
        env = {"PATH": str(self.bin), "HOME": str(self.root),
               "FAKE_MKKSISO_LOG": str(self.log)}
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def build(self, *args, **extra):
        return self.run_script("--iso", str(self.base), "--ks", str(KS),
                               "--out", str(self.out),
                               "--rpms", str(self.rpms), *args, **extra)

    def iso(self):
        return self.out / "iso" / "airymaxos-0.0.3-x86_64.iso"

    def test_help(self):
        self.tools()
        res = self.run_script("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("用法", res.stdout)

    def test_missing_iso(self):
        self.tools()
        self.stock()
        res = self.run_script("--ks", str(KS), "--out", str(self.out),
                              "--rpms", str(self.rpms))
        self.assertEqual(res.returncode, 5)

    def test_missing_rpms(self):
        self.tools()
        res = self.run_script("--iso", str(self.base), "--ks", str(KS),
                              "--out", str(self.out))
        self.assertEqual(res.returncode, 5)

    def test_rpms_absent(self):
        self.tools()
        res = self.build("--rpms", str(self.root / "gone"))
        self.assertEqual(res.returncode, 5)

    def test_bad_arch(self):
        self.tools()
        self.stock()
        self.assertEqual(self.build("--arch", "sparc").returncode, 5)

    def test_wrong_rpm_arch(self):
        self.tools()
        self.stock()
        self.write_rpm(self.rpms, "airymaxos-extra-0.0.3-1.aarch64.rpm")
        self.assertEqual(self.build("--arch", "x86_64").returncode, 5)

    def test_source_rpm_skipped(self):
        self.tools()
        self.stock()
        self.write_rpm(self.rpms, "airymaxos-kernel-6.6.0-1.src.rpm")
        res = self.build("--arch", "x86_64")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("src.rpm",
                         (self.out / "payload" / "airymax" /
                          "payload-manifest.txt").read_text(encoding="utf-8"))

    def test_missing_kernel(self):
        self.tools()
        for name in CLOSURE[:1] + CLOSURE[2:]:
            self.write_rpm(self.rpms, name)
        self.assertEqual(self.build().returncode, 5)

    def test_missing_release(self):
        self.tools()
        for name in CLOSURE[1:]:
            self.write_rpm(self.rpms, name)
        self.assertEqual(self.build().returncode, 5)

    def test_require_narrow(self):
        self.tools()
        for name in CLOSURE[2:]:
            self.write_rpm(self.rpms, name)
        res = self.build("--require", "airymaxos-kernel",
                         "--require", "airymaxos-kernel-core",
                         "--require", "airymaxos-kernel-modules")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("count=3", (self.out / "payload" / "airymax" /
                                  "payload-manifest.txt").read_text(
                                      encoding="utf-8"))

    def test_require_missing(self):
        self.tools()
        self.stock()
        self.assertEqual(
            self.build("--require", "airymaxos-agent").returncode, 5)

    def test_duplicate_rpm(self):
        self.tools()
        self.stock()
        other = self.root / "other"
        self.stock(other)
        res = self.build("--rpms", str(other))
        self.assertEqual(res.returncode, 2)

    def test_createrepo_fail(self):
        self.tools()
        self.stock()
        res = self.build(FAKE_CREATEREPO_MODE="fail")
        self.assertEqual(res.returncode, 6)

    def test_comps_env_missing(self):
        self.tools()
        self.stock()
        res = self.build(FAKE_CREATEREPO_MODE="noenv")
        self.assertEqual(res.returncode, 6)
        self.assertIn("comps 缺环境", res.stderr)

    def test_closure_harvests_payload(self):
        self.tools()
        self.stock()
        log = self.root / "dnf.log"
        res = self.build("--arch", "x86_64", "--closure",
                         FAKE_DNF_LOG=str(log))
        self.assertEqual(res.returncode, 0, res.stderr)
        pkgdir = self.out / "payload" / "airymax" / "Packages"
        for name in ("ukui-1.0-1.noarch.rpm", "grub2-tools-1.0-1.noarch.rpm"):
            self.assertTrue((pkgdir / name).is_file())
        self.assertIn(f"闭包收割: 新增 {HARVEST}", res.stdout)
        manifest = (self.out / "payload" / "airymax" /
                    "payload-manifest.txt").read_text(encoding="utf-8")
        self.assertIn(f"count={TOTAL}", manifest)
        self.assertIn("grub2-tools", manifest)
        specs = log.read_text(encoding="utf-8")
        self.assertIn("@airymax-core", specs)
        self.assertIn("@airymax-desktop-core", specs)
        self.assertIn("@airymax-desktop ", specs)
        self.assertNotIn("@^", specs)

    def test_closure_off_by_default(self):
        self.tools()
        self.stock()
        log = self.root / "dnf.log"
        res = self.build("--arch", "x86_64", FAKE_DNF_LOG=str(log))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(log.exists())

    def test_closure_needs_dnf(self):
        self.tools()
        (self.bin / "dnf").unlink()
        self.stock()
        self.assertEqual(self.build("--closure").returncode, 11)

    def test_closure_solver_fail(self):
        self.tools()
        self.stock()
        res = self.build("--arch", "x86_64", "--closure",
                         FAKE_DNF_MODE="fail", CLOSURE_WAIT="0")
        self.assertEqual(res.returncode, 6)

    def test_closure_retries_link(self):
        self.tools()
        self.stock()
        state = self.root / "dnf.state"
        res = self.build("--arch", "x86_64", "--closure",
                         FAKE_DNF_MODE="flaky", FAKE_DNF_FAILS="1",
                         FAKE_DNF_STATE=str(state), CLOSURE_WAIT="0")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"闭包收割: 新增 {HARVEST}", res.stdout)
        self.assertEqual(state.read_text(encoding="utf-8").strip(), "2")

    def test_closure_retry_gives_up(self):
        self.tools()
        self.stock()
        res = self.build("--arch", "x86_64", "--closure",
                         FAKE_DNF_MODE="flaky", FAKE_DNF_FAILS="9",
                         FAKE_DNF_STATE=str(self.root / "dnf.state"),
                         CLOSURE_TRY="2", CLOSURE_WAIT="0")
        self.assertEqual(res.returncode, 6)
        self.assertIn("安装闭包收割失败", res.stderr)

    def test_closure_downloads_nothing(self):
        self.tools()
        self.stock()
        res = self.build("--arch", "x86_64", "--closure",
                         FAKE_DNF_MODE="empty")
        self.assertEqual(res.returncode, 6)

    def test_mkksiso_fail(self):
        self.tools()
        self.stock()
        res = self.build(FAKE_MKKSISO_MODE="fail")
        self.assertEqual(res.returncode, 6)

    def test_dest_exists(self):
        self.tools()
        self.stock()
        self.assertEqual(self.build("--arch", "x86_64").returncode, 0)
        self.assertEqual(self.build("--arch", "x86_64").returncode, 2)

    def test_build_success(self):
        self.tools()
        self.stock()
        self.write_rpm(self.rpms / "nested", "airymaxos-agent-0.0.3-1.x86_64.rpm")
        res = self.build("--arch", "x86_64")
        self.assertEqual(res.returncode, 0, res.stderr)
        pkgdir = self.out / "payload" / "airymax" / "Packages"
        self.assertTrue((pkgdir / "airymaxos-agent-0.0.3-1.x86_64.rpm").is_file())
        self.assertTrue((pkgdir / "repodata" / "repomd.xml").is_file())
        self.assertEqual(
            gzip.decompress((pkgdir / "repodata" / "comps.xml.gz").read_bytes()),
            COMPS.read_bytes())
        manifest = (self.out / "payload" / "airymax" /
                    "payload-manifest.txt").read_text(encoding="utf-8")
        self.assertIn("arch=x86_64", manifest)
        self.assertIn("count=6", manifest)
        self.assertRegex(manifest, r"comps [0-9a-f]{64} comps/airymaxos-comps\.xml")
        self.assertIn("kernel-core", manifest)
        iso = self.iso()
        self.assertTrue(iso.is_file())
        digest = hashlib.sha256(iso.read_bytes()).hexdigest()
        self.assertEqual((iso.parent / f"{iso.name}.sha256").read_text(
            encoding="utf-8"), f"{digest}  {iso.name}\n")
        body = iso.read_text(encoding="utf-8")
        self.assertIn("=== /airymax/payload-manifest.txt", body)
        self.assertIn("=== /airymax/Packages/repodata/repomd.xml", body)
        app = iso.read_bytes()[APP_OFF:APP_OFF + 512].decode("latin-1")
        self.assertRegex(app, r"ISO MD5SUM = [0-9a-f]{32}")

    def test_extra_add(self):
        self.tools()
        self.stock()
        extra = self.root / "extra.txt"
        extra.write_text("extra payload\n", encoding="utf-8")
        res = self.build("--arch", "x86_64", "--add", str(extra))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("=== /extra.txt",
                      self.iso().read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
