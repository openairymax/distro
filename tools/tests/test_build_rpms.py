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

TOOLS = ("basename", "cat", "cmp", "cp", "cut", "date", "dirname", "find",
         "gzip", "mkdir", "nproc", "rm", "sed", "sha256sum", "sort", "tar",
         "uname")

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

BUNDLE = SPEC.replace("Source0:        demo.conf",
                      "# spec-lint: source-bundle demo-pkg\n"
                      "Source0:        demo-pkg-0.0.3.tar.gz")

RPMSPEC = """\
#!/bin/sh
for a in "$@"; do last=$a; done
exec cat "$last"
"""

RPMBUILD = """\
#!/bin/sh
orig=$*
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
[ -f "$sourcedir/demo.conf" ] || [ -f "$sourcedir/demo-pkg-0.0.3.tar.gz" ] ||
    exit 8
mkdir -p "$rpmdir/$target"
printf '%s\\n' "$orig" > "$rpmdir/$target/argv.txt"
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

    def run_script(self, *args, **extra):
        env = {"PATH": str(self.bin), "HOME": str(self.root)}
        env.update(extra)
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
        # 台账三元组：门禁按它推导预算，缺一项就无从判断这一轮到底跑了多久。
        self.assertIn("stage=rpm", manifest)
        for key in ("started_at", "finished_at"):
            self.assertRegex(
                manifest, rf"(?m)^{key}=\d{{4}}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertRegex(manifest, r"(?m)^elapsed_s=\d+$")
        self.assertRegex(manifest, r"spec [0-9a-f]{64} demo\.spec")
        self.assertRegex(
            manifest,
            r"rpm [0-9a-f]{64} RPMS/x86_64/demo-0\.0\.3-1\.x86_64\.rpm")

    def test_define_without_value(self):
        self.tools()
        res = self.run_script("--out", str(self.out), "--spec",
                              str(self.spec), "--define", "cross_prefix")
        self.assertEqual(res.returncode, 5)
        self.assertFalse(self.out.exists())

    def test_define_and_nodeps(self):
        self.full()
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec),
                              "--arch", "loongarch64", "--nodeps",
                              "--define", "cross_prefix loongarch64-linux-gnu-")
        self.assertEqual(res.returncode, 0, res.stderr)
        argv = (self.out / "work" / "rpmbuild" / "RPMS" / "loongarch64"
                / "argv.txt").read_text(encoding="utf-8")
        self.assertIn("--define cross_prefix loongarch64-linux-gnu-", argv)
        self.assertIn("--nodeps", argv)
        manifest = (self.out / "build-manifest.txt").read_text(
            encoding="utf-8")
        self.assertIn("define=cross_prefix loongarch64-linux-gnu-", manifest)

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

    def test_stale_outputs_reset(self):
        self.full()
        rpm_dir = self.out / "RPMS" / "x86_64"
        repo = self.out / "repo" / "AppStream" / "x86_64"
        rpm_dir.mkdir(parents=True)
        repo.mkdir(parents=True)
        stale = "demo-0.0.2-1.x86_64.rpm"
        (rpm_dir / stale).write_bytes(b"old")
        (repo / stale).write_bytes(b"old")
        (self.out / "build-manifest.txt").write_text(
            "rpm deadbeef %s\n" % stale, encoding="utf-8")
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec),
                              "--arch", "x86_64", "--repo",
                              "--gpg-key", "test", "--stream", "AppStream")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((rpm_dir / stale).exists())
        self.assertFalse((repo / stale).exists())
        self.assertTrue((rpm_dir / "demo-0.0.3-1.x86_64.rpm").is_file())
        manifest = (self.out / "build-manifest.txt").read_text(encoding="utf-8")
        self.assertNotIn("0.0.2", manifest)

    def bundle_tree(self):
        pkg = self.specs / "demo-pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("x\n", encoding="utf-8")
        (pkg / "__pycache__").mkdir()
        (pkg / "__pycache__" / "x.pyc").write_bytes(b"x")
        self.spec.write_text(BUNDLE, encoding="utf-8")

    def bundle_tar(self):
        return (self.out / "work" / "rpmbuild" / "SOURCES"
                / "demo-pkg-0.0.3.tar.gz")

    def names_of(self, tar):
        res = subprocess.run(["tar", "-tzf", str(tar)], text=True,
                             capture_output=True, check=True)
        return res.stdout.split()

    def test_bundle_source(self):
        self.full()
        self.bundle_tree()
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec),
                              "--arch", "x86_64")
        self.assertEqual(res.returncode, 0, res.stderr)
        names = self.names_of(self.bundle_tar())
        self.assertIn("demo-pkg/__init__.py", names)
        self.assertFalse(any("__pycache__" in name for name in names))

    def test_bundle_reproducible(self):
        self.full()
        self.bundle_tree()
        args = ("--out", str(self.out), "--spec", str(self.spec),
                "--arch", "x86_64")
        self.assertEqual(self.run_script(*args).returncode, 0)
        first = self.bundle_tar().read_bytes()
        self.assertEqual(self.run_script(*args).returncode, 0)
        self.assertEqual(self.bundle_tar().read_bytes(), first)

    def test_bundle_missing_dir(self):
        self.full()
        self.spec.write_text(BUNDLE, encoding="utf-8")
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec))
        self.assertEqual(res.returncode, 5)

    def manifest(self):
        return (self.out / "build-manifest.txt").read_text(encoding="utf-8")

    def test_build_id_digest(self):
        # 沙箱里没有 git，也没有流水线变量：指纹退化为配方摘要，仍可复算。
        self.full()
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec),
                              "--arch", "x86_64")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertRegex(self.manifest(),
                         r"(?m)^build_id=src-[0-9a-f]{12}$")
        argv = (self.out / "work" / "rpmbuild" / "RPMS" / "x86_64" /
                "argv.txt").read_text(encoding="utf-8")
        self.assertRegex(argv, r"--define airy_build_id src-[0-9a-f]{12}")

    def test_build_id_pipeline(self):
        # 流水线原生量：run id 加提交短 sha，同一提交可回查到具体那一轮。
        self.full()
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec),
                              "--arch", "x86_64",
                              AIRYMAX_RUN_ID="12345678",
                              AIRYMAX_COMMIT="0a1b2c3d4e5f60718293")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("build_id=r12345678-g0a1b2c3d4e5f\n", self.manifest())

    def test_build_id_explicit(self):
        # 显式值优先于流水线原生量：离线重放与回溯构建用它钉住发布号。
        self.full()
        res = self.run_script("--out", str(self.out), "--spec", str(self.spec),
                              "--arch", "x86_64",
                              AIRYMAX_BUILD_ID="offline-0.0.4",
                              AIRYMAX_RUN_ID="12345678",
                              AIRYMAX_COMMIT="0a1b2c3d4e5f60718293")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("build_id=offline-0.0.4\n", self.manifest())

    def test_build_id_invalid(self):
        # 空值、含分隔符或超长的值会破坏 os-release 与一行式文件，必须拒绝。
        self.tools()
        for value in ("bad id", "x/y", "a" * 65):
            with self.subTest(value=value):
                res = self.run_script("--out", str(self.out),
                                      "--spec", str(self.spec),
                                      AIRYMAX_BUILD_ID=value)
                self.assertEqual(res.returncode, 5, res.stderr)
                self.assertIn("构建来源指纹非法", res.stderr)


if __name__ == "__main__":
    unittest.main()
