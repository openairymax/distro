#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_build_kernel.py — scripts/build-kernel.sh 契约回归测试
#
# 归档确定性与版本对齐是内核配方的两个前提，一旦漂移要到数小时构建后
# 才会暴露。用例以微型 git 内核树为夹具，用 PATH 沙箱替换 rpm 工具链，
# 每个用例只破坏一个前提，断言对应退出码或归档属性。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import hashlib
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build-kernel.sh"
DISTRO = SCRIPT.parent.parent
BASH = shutil.which("bash") or "/bin/bash"
GIT = shutil.which("git") or "/usr/bin/git"

KVER = "6.6.157"
PREFIX = "airymaxos-kernel-{}/".format(KVER)

TOOLS = ("bash", "basename", "cat", "cmp", "cp", "dirname", "find", "git",
         "gzip", "mkdir", "mv", "nproc", "rm", "sed", "sha256sum", "sort",
         "uname")

RPMSPEC = """\
#!/bin/sh
for a in "$@"; do last=$a; done
kv=$(sed -n 's/^%global[[:space:]]*kernel_version[[:space:]]*//p' "$last")
sed "s/%{kernel_version}/$kv/g" "$last"
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
[ -f "$sourcedir/airymaxos-kernel-@KVER@.tar.gz" ] || exit 8
mkdir -p "$rpmdir/$target"
printf 'payload\n' > "$rpmdir/$target/airymaxos-kernel-0.0.3-1.$target.rpm"
""".replace("@KVER@", KVER)


class BuildKernelTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "out"
        self.kdir = self.root / "kernel"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.repo("157")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        res = subprocess.run(
            [GIT, "-C", str(self.kdir), "-c", "commit.gpgsign=false",
             "-c", "user.name=test", "-c", "user.email=test@example.com",
             *args], text=True, capture_output=True)
        if res.returncode != 0:
            raise AssertionError(res.stderr)

    def repo(self, sublevel):
        self.kdir.mkdir()
        (self.kdir / "Makefile").write_text(
            "VERSION = 6\nPATCHLEVEL = 6\nSUBLEVEL = {}\n"
            "EXTRAVERSION =\n".format(sublevel), encoding="utf-8")
        (self.kdir / "Kconfig").write_text("mainmenu \"Airy\"\n",
                                           encoding="utf-8")
        (self.kdir / "arch").mkdir()
        (self.kdir / "arch" / "airy_defconfig").write_text(
            "CONFIG_SECURITY=y\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "init")

    def tools(self, *fakes):
        for name in TOOLS:
            src = shutil.which(name)
            if src:
                (self.bin / name).symlink_to(src)
        for name, body in fakes:
            path = self.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

    def run_script(self, *args):
        env = {"PATH": str(self.bin), "HOME": str(self.root)}
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def base(self, *extra):
        return self.run_script("--out", str(self.out),
                               "--kernel", str(self.kdir), *extra)

    def tarball(self):
        return self.out / "src" / "airymaxos-kernel-{}.tar.gz".format(KVER)

    def test_help(self):
        self.tools()
        res = self.run_script("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("用法", res.stdout)

    def test_missing_out(self):
        self.tools()
        res = self.run_script("--kernel", str(self.kdir))
        self.assertEqual(res.returncode, 5)

    def test_out_in_source(self):
        self.tools()
        target = DISTRO / ".kernel-out-test"
        res = self.run_script("--out", str(target),
                              "--kernel", str(self.kdir))
        self.assertEqual(res.returncode, 5)
        self.assertFalse(target.exists())

    def test_bad_arch(self):
        self.tools()
        res = self.base("--arch", "ppc64le")
        self.assertEqual(res.returncode, 5)

    def test_missing_kernel(self):
        self.tools()
        res = self.run_script("--out", str(self.out),
                              "--kernel", str(self.root / "gone"))
        self.assertEqual(res.returncode, 5)

    def test_dirty_tree(self):
        self.tools()
        (self.kdir / "Kconfig").write_text("mainmenu \"Dirty\"\n",
                                           encoding="utf-8")
        res = self.base()
        self.assertEqual(res.returncode, 5)
        self.assertFalse(self.out.exists())

    def test_config_present(self):
        self.tools()
        (self.kdir / ".config").write_text("CONFIG_X=y\n", encoding="utf-8")
        res = self.base()
        self.assertEqual(res.returncode, 5)
        self.assertFalse(self.out.exists())

    def test_version_drift(self):
        self.tools()
        self.kdir.joinpath("Makefile").write_text(
            "VERSION = 6\nPATCHLEVEL = 6\nSUBLEVEL = 156\n"
            "EXTRAVERSION =\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "drift")
        res = self.base()
        self.assertEqual(res.returncode, 5)

    def test_extraversion(self):
        self.tools()
        self.kdir.joinpath("Makefile").write_text(
            "VERSION = 6\nPATCHLEVEL = 6\nSUBLEVEL = 157\n"
            "EXTRAVERSION = -local\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "local")
        res = self.base()
        self.assertEqual(res.returncode, 5)

    def test_archive_layout(self):
        self.tools(("rpmspec", RPMSPEC), ("rpmbuild", RPMBUILD))
        res = self.base("--arch", "x86_64", "--dist", ".airy03")
        self.assertEqual(res.returncode, 0, res.stderr)
        tar = self.tarball()
        self.assertTrue(tar.is_file())
        with tarfile.open(tar) as handle:
            names = handle.getnames()
        self.assertTrue(names)
        top = PREFIX.rstrip("/")
        self.assertTrue(all(n == top or n.startswith(PREFIX) for n in names),
                        names)
        self.assertIn(PREFIX + "Makefile", names)

    def test_archive_sum(self):
        self.tools(("rpmspec", RPMSPEC), ("rpmbuild", RPMBUILD))
        res = self.base("--arch", "x86_64")
        self.assertEqual(res.returncode, 0, res.stderr)
        tar = self.tarball()
        want = hashlib.sha256(tar.read_bytes()).hexdigest()
        line = Path(str(tar) + ".sha256").read_text(encoding="utf-8")
        self.assertEqual(line.split()[0], want)
        self.assertEqual(line.split()[1],
                         "airymaxos-kernel-{}.tar.gz".format(KVER))

    def test_archive_deterministic(self):
        self.tools(("rpmspec", RPMSPEC), ("rpmbuild", RPMBUILD))
        self.assertEqual(self.base("--arch", "x86_64").returncode, 0)
        first = hashlib.sha256(self.tarball().read_bytes()).hexdigest()
        self.assertEqual(self.base("--arch", "x86_64").returncode, 0)
        second = hashlib.sha256(self.tarball().read_bytes()).hexdigest()
        self.assertEqual(first, second)

    def test_delegation(self):
        self.tools(("rpmspec", RPMSPEC), ("rpmbuild", RPMBUILD))
        res = self.base("--arch", "x86_64", "--dist", ".airy03")
        self.assertEqual(res.returncode, 0, res.stderr)
        rpm = (self.out / "RPMS" / "x86_64"
               / "airymaxos-kernel-0.0.3-1.x86_64.rpm")
        self.assertTrue(rpm.is_file())
        manifest = (self.out / "build-manifest.txt").read_text(
            encoding="utf-8")
        self.assertIn("arch=x86_64", manifest)
        self.assertIn("dist=.airy03", manifest)
        self.assertEqual(manifest.count("spec "), 1)
        self.assertIn("airymaxos-kernel.spec", manifest)
        self.assertIn("rpm ", manifest)


if __name__ == "__main__":
    unittest.main()
