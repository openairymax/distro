#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_site_ks.py — 站点派生（site_ks.py / site-iso.sh）契约回归测试
#
# 站点介质的输入是产品 ISO 里已投影过的安装配方，输出必须满足同一套产物
# 契约：/ks.cfg 与派生配方逐字节一致、卷标与引导配置不自相矛盾、混合镜像
# 三元一致、校验块可在 rd.live.check 下通过。xorriso/implantisomd5 未必
# 可用，这里沿用 PATH 沙箱的伪工具，并从 ks_spec 的投影产物构造底座，使
# 用例跑的就是装机现场真正读到的配方形状。
#
# 每个用例只破坏一个前提，便于定位失败原因。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import fakes

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
DISTRO = SCRIPTS.parent
SITE = SCRIPTS / "site-iso.sh"
UNIT = DISTRO / "tools" / "site_ks.py"
SPEC = DISTRO / "tools" / "ks_spec.py"
PRODUCT = DISTRO / "kickstart" / "airymaxos-workstation.ks"
BASH = shutil.which("bash") or "/bin/bash"
DISK = "nvme0n1"


class SiteIsoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fakes.link_tools(self.bin)
        fakes.iso_tools(self.bin)
        self.out = self.root / "out"
        self.out.mkdir()
        self.key = self.file("site.pub", "ssh-ed25519 AAAATEST airymax\n")
        self.ifcfg = self.file("ifcfg-SiteLab",
                               "TYPE=Wireless\nSSID=SiteLab\n")
        self.psk = self.file("psk", "s3cret\n")
        self.base = self.make_iso(self.project(), "base.iso")
        self.dest = self.out / "base-site.iso"

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, extra=None):
        env = {"PATH": str(self.bin), "HOME": str(self.root)}
        if extra:
            env.update(extra)
        return env

    def file(self, name, text):
        path = self.root / "cfg" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def project(self):
        res = subprocess.run([sys.executable, str(SPEC), "install",
                              str(PRODUCT)],
                             text=True, capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    def make_iso(self, text, name):
        ks = self.file(name + ".ks", text)
        out = self.root / "base" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        res = subprocess.run(
            [str(self.bin / "mkksiso"), "-V", "AIRYMAXOS", "-c",
             "console=tty0", str(ks), str(self.root / "no-such-base"),
             str(out)], env=self.env(), text=True, capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        return out

    def site(self, *args, **extra):
        return subprocess.run([BASH, str(SITE), *args], env=self.env(extra),
                              text=True, capture_output=True)

    def derive(self, *extra, **kwargs):
        args = ["--iso", str(self.base), "--out", str(self.out),
                "--disk", DISK, "--esp", "p1", "--boot", "p2",
                "--swap", "p3", "--root", "p4",
                "--key", str(self.key), "--ifcfg", str(self.ifcfg),
                "--psk", str(self.psk)]
        return self.site(*args, *extra, **kwargs)

    def recipe(self):
        return (self.out / "work" / "site.ks").read_text(encoding="utf-8")

    def extract(self, path):
        got = self.root / "got" / Path(path).name
        got.parent.mkdir(parents=True, exist_ok=True)
        res = subprocess.run([str(self.bin / "xorriso"), "-osirrox", "on",
                              "-indev", str(self.dest), "-extract", path,
                              str(got)], env=self.env(), text=True,
                             capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        return got

    def test_help(self):
        res = self.site("--help")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("用法", res.stdout)

    def test_missing_part(self):
        res = self.site("--iso", str(self.base), "--out", str(self.out),
                        "--disk", DISK, "--esp", "p1", "--boot", "p2",
                        "--swap", "p3", "--key", str(self.key),
                        "--ifcfg", str(self.ifcfg), "--psk", str(self.psk))
        self.assertEqual(res.returncode, 5, res.stderr)
        self.assertIn("--root 必填", res.stderr)

    def test_out_in_source(self):
        res = self.site("--iso", str(self.base),
                        "--out", str(DISTRO / ".site-iso-test"),
                        "--disk", DISK, "--esp", "p1", "--boot", "p2",
                        "--swap", "p3", "--root", "p4",
                        "--key", str(self.key), "--ifcfg", str(self.ifcfg),
                        "--psk", str(self.psk))
        self.assertEqual(res.returncode, 5, res.stderr)
        self.assertFalse((DISTRO / ".site-iso-test").exists())

    def test_recipe_binds_parts(self):
        res = self.derive()
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self.recipe()
        self.assertNotIn("clearpart --all", text)
        self.assertNotIn("autopart", text)
        self.assertIn("ignoredisk --only-use=nvme0n1", text)
        self.assertIn("clearpart --none", text)
        self.assertIn('part / --fstype="ext4" --onpart=nvme0n1p4', text)
        self.assertIn('part /boot/efi --fstype="efi" --onpart=nvme0n1p1',
                      text)
        self.assertIn('part /boot --fstype="ext4" --onpart=nvme0n1p2', text)
        self.assertIn("--boot-drive=nvme0n1", text)
        self.assertIn("url --url=file:///run/install/repo/airymax/Packages",
                      text)
        self.assertEqual(text.strip().splitlines()[-1], "reboot")

    def test_recipe_carries_site_tail(self):
        res = self.derive()
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self.recipe()
        self.assertIn("%post --log=/root/airymax-site.log", text)
        self.assertIn("ssh-ed25519 AAAATEST airymax", text)
        self.assertIn('ifcfg-SiteLab', text)
        self.assertIn("s3cret", text)
        self.assertLess(text.index("%post"), text.index("reboot"))

    def test_iso_matches_recipe(self):
        res = self.derive()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(self.dest.is_file())
        self.assertTrue((self.dest.parent / "site-manifest.txt").is_file())
        got = self.extract("/ks.cfg")
        self.assertEqual(got.read_bytes(),
                         (self.out / "work" / "site.ks").read_bytes())

    def test_short_image_padded(self):
        res = self.derive(FAKE_XORRISO_SHORT="2")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.dest.stat().st_size, self.base.stat().st_size)

    def test_rebuild_failure(self):
        res = self.derive(FAKE_XORRISO_MODE="fail")
        self.assertEqual(res.returncode, 6, res.stderr)
        self.assertFalse(self.dest.exists())

    def test_existing_dest(self):
        res = self.derive()
        self.assertEqual(res.returncode, 0, res.stderr)
        again = self.derive()
        self.assertEqual(again.returncode, 2, again.stderr)
        self.assertIn("产物已存在", again.stderr)

    def test_recipe_without_clearpart(self):
        text = "\n".join(line for line in self.project().splitlines()
                         if not line.startswith("clearpart"))
        iso = self.make_iso(text + "\n", "noclear.iso")
        work = self.root / "unit"
        out = self.root / "unit" / "site.ks"
        res = subprocess.run(
            [sys.executable, str(UNIT), "--iso", str(iso),
             "--out", str(out), "--work", str(work), "--disk", DISK,
             "--esp", "p1", "--boot", "p2", "--swap", "p3", "--root", "p4",
             "--key", str(self.key), "--ifcfg", str(self.ifcfg),
             "--psk", str(self.psk)], env=self.env(), text=True,
            capture_output=True)
        self.assertEqual(res.returncode, 5, res.stderr)
        self.assertIn("clearpart --all", res.stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
