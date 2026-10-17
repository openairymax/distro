#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_build_rpms.py — scripts/build-rpms.sh 契约回归测试
#
# 用 PATH 沙箱替换 rpm 工具链：真实工具在本机可能缺失，而退出码与产物
# 布局属于对外契约，必须可独立验证。每个用例只破坏一个前提，断言对应
# 退出码或产物，避免失败被上层逻辑掩盖。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build-rpms.sh"
DISTRO = SCRIPT.parent.parent
BASH = shutil.which("bash") or "/bin/bash"

TOOLS = ("basename", "cat", "cmp", "cp", "dirname", "find", "mkdir",
         "nproc", "rm", "sed", "sha256sum", "sort", "uname")

SPEC = """\
Name:           airymaxos-demo
Version:        0.0.3
Release:        1%{?dist}
Summary:        Demo
License:        AGPL-3.0-or-later
BuildArch:      noarch

Source0:        demo.conf

%description
Demo.

%files
/etc/demo.conf
"""

RPMSPEC = """\
#!/bin/sh
for a in "$@"; do last=$a; done
exec cat "$last"
"""

RPMBUILD = """\
#!/bin/sh
rpmdir=""; sourcedir=""; target=""
while [ $# -gt 0 ]; do
    case "$1" in
    --define)
        shift
        key=${1%% *}; val=${1#* }
        case "$key" in
        _rpmdir) rpmdir=$val ;;
        _sourcedir) sourcedir=$val ;;
        esac
        ;;
    --target) shift; target=$1 ;;
    esac
    shift
done
[ -n "$rpmdir" ] || exit 9
[ -n "$target" ] || exit 9
[ -f "$sourcedir/demo.conf" ] || exit 8
mkdir -p "$rpmdir/$target"
printf 'payload\\n' > "$rpmdir/$target/demo-0.0.3-1.$target.rpm"
"""

CREATEREPO = """\
#!/bin/sh
for a in "$@"; do last=$a; done
mkdir -p "$last/repodata"
printf '<repomd/>\\n' > "$last/repodata/repomd.xml"
"""

GPG = """\
#!/bin/sh
out=""
while [ $# -gt 0 ]; do
    case "$1" in
    --output) shift; out=$1 ;;
    esac
    shift
done
[ -n "$out" ] || exit 1
printf 'signature\\n' > "$out"
"""


class BuildRpmsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "out"
        self.specs = self.root / "specs"
        self.specs.mkdir()
        self.spec = self.specs / "demo.spec"
        self.spec.write_text(SPEC, encoding="utf-8")
        (self.specs / "demo.conf").write_text("x\n", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def tools(self, *fakes):
        for name in TOOLS:
            src = shutil.which(name)
            if src:
                (self.bin / name).symlink_to(src)
        for name, body in fakes:
            path = self.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

    def full(self):
        self.tools(("rpmspec", RPMSPEC), ("rpmbuild", RPMBUILD),
                   ("createrepo_c", CREATEREPO), ("gpg", GPG))

    def run_script(self, *args):
        env = {"PATH": str(self.bin), "HOME": str(self.root)}
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def test_help(self):
        self.tools()
        res = self.run_script("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("用法", res.stdout)

    def test_missing_out(self):
        self.tools()
        self.assertEqual(
            self.run_script("--spec", str(self.spec)).returncode, 5)

    def test_out_in_source(self):
        self.tools()
        target = DISTRO / ".build-out-test"
        res = self.run_script("--out", str(target), "--spec", str(self.spec))
        self.assertEqual(res.returncode, 5)
        self.assertFalse(target.exists())

    def test_bad_arch(self):
        self.tools()
        res = self.run_script("--out", str(self.out), "--arch", "sparc")
        self.assertEqual(res.returncode, 5)

    def test_missing_rpmbuild(self):
        self.tools()
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec))
        self.assertEqual(res.returncode, 11)

    def test_empty_spec_dir(self):
        self.tools()
        empty = self.root / "empty"
        empty.mkdir()
        res = self.run_script("--out", str(self.out),
                              "--spec-dir", str(empty))
        self.assertEqual(res.returncode, 5)

    def test_duplicate_specs(self):
        self.tools()
        other = self.root / "other"
        other.mkdir()
        dup = other / "demo.spec"
        dup.write_text(SPEC, encoding="utf-8")
        (other / "demo.conf").write_text("x\n", encoding="utf-8")
        res = self.run_script("--out", str(self.out),
                              "--spec", str(self.spec), "--spec", str(dup))
        self.assertEqual(res.returncode, 2)

    def test_missing_source(self):
        self.full()
        self.spec.write_text(SPEC.replace("demo.conf", "gone.conf"),
                             encoding="utf-8")
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec))
        self.assertEqual(res.returncode, 6)

    def test_repo_key_required(self):
        self.full()
        res = self.run_script("--out", str(self.out),
                              "--spec", str(self.spec), "--repo")
        self.assertEqual(res.returncode, 5)

    def test_build_success(self):
        self.full()
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec),
                              "--arch", "x86_64", "--dist", ".airy03")
        self.assertEqual(res.returncode, 0, res.stderr)
        rpm = self.out / "RPMS" / "x86_64" / "demo-0.0.3-1.x86_64.rpm"
        self.assertTrue(rpm.is_file())
        manifest = (self.out / "build-manifest.txt").read_text(
            encoding="utf-8")
        self.assertIn("arch=x86_64", manifest)
        self.assertIn("dist=.airy03", manifest)
        self.assertRegex(manifest, r"spec [0-9a-f]{64} demo\.spec")
        self.assertRegex(
            manifest,
            r"rpm [0-9a-f]{64} RPMS/x86_64/demo-0\.0\.3-1\.x86_64\.rpm")

    def test_repo_build(self):
        self.full()
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec),
                              "--arch", "x86_64", "--repo",
                              "--gpg-key", "test", "--stream", "AppStream")
        self.assertEqual(res.returncode, 0, res.stderr)
        repo = self.out / "repo" / "AppStream" / "x86_64"
        self.assertTrue((repo / "repodata" / "repomd.xml").is_file())
        self.assertTrue((repo / "repodata" / "repomd.xml.asc").is_file())
        self.assertTrue((repo / "demo-0.0.3-1.x86_64.rpm").is_file())


if __name__ == "__main__":
    unittest.main()
