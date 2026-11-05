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
# Version: 0.0.4
# ===========================================================================

import hashlib
import re
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

# 包名与镜像名都由 release/os-release 单点派生，写死某次发版的字符串
# 会让每次升版本都要改一批与编排契约无关的断言。
VERSION = fakes.osrel("VERSION_ID")
ISO_NAME = f"airymaxos-{VERSION}-x86_64.iso"

CLOSURE = (
    f"airymaxos-release-{VERSION}-1.noarch.rpm",
    f"airymaxos-system-{VERSION}-1.noarch.rpm",
    "airymaxos-kernel-6.6.0-1.x86_64.rpm",
    "airymaxos-kernel-core-6.6.0-1.x86_64.rpm",
    "airymaxos-kernel-modules-6.6.0-1.x86_64.rpm",
)
KERNEL = CLOSURE[2:]
LIB_SH = ("arch.sh", "iso.sh", "log.sh", "outdir.sh")

# build-rpms/build-kernel 把成品放在 <root>/RPMS，同时把 rpmbuild 的
# 中间产物留在 <root>/work/rpmbuild/RPMS。两者同名，编排层若把 <root>
# 整体交给 build-desktop，汇集时必然冲突而拒绝出镜像。
FAKE_BUILD = f"""\
#!/bin/sh
set -eu
out=""
while [ $# -gt 0 ]; do
    case "$1" in
    --out) shift; out=$1 ;;
    esac
    shift
done
[ -n "$out" ] || exit 5
case "$(basename "$out")" in
rpms)
    if [ "${{FAKE_BUILD_RPMS_MODE:-ok}}" = fail ]; then
        printf 'error: line 12: Unknown tag\\n' >&2
        exit 1
    fi
    pkg=airymaxos-release-{VERSION}-1.noarch.rpm ;;
*) pkg=airymaxos-kernel-6.6.0-1.x86_64.rpm ;;
esac
for d in "$out/RPMS/x86_64" "$out/work/rpmbuild/RPMS/x86_64"; do
    mkdir -p "$d"
    printf 'rpm\\n' > "$d/$pkg"
done
"""

FAKE_DESKTOP = f"""\
#!/bin/sh
set -eu
out=""
: > "$ARGS_LOG"
: > "$ARGS_LOG.all"
while [ $# -gt 0 ]; do
    printf '%s\\n' "$1" >> "$ARGS_LOG.all"
    case "$1" in
    --out) shift; out=$1 ;;
    --rpms) shift; printf '%s\\n' "$1" >> "$ARGS_LOG" ;;
    esac
    shift
done
[ -n "$out" ] || exit 5
names="$ARGS_LOG.names"
: > "$names"
list="$ARGS_LOG.list"
: > "$list"
while IFS= read -r d; do
    find "$d" -type f -name '*.rpm' >> "$list"
done < "$ARGS_LOG"
while IFS= read -r f; do
    b=$(basename "$f")
    if grep -qxF "$b" "$names"; then
        printf 'duplicate %s\\n' "$b" >&2
        exit 2
    fi
    printf '%s\\n' "$b" >> "$names"
done < "$list"
[ -s "$names" ] || exit 5
mkdir -p "$out/iso"
printf 'fake iso\\n' > "$out/iso/{ISO_NAME}"
printf 'name={ISO_NAME}\\n' > "$out/iso/iso-manifest.txt"
(cd "$out/iso" && sha256sum {ISO_NAME} \
    > {ISO_NAME}.sha256)
"""


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

    def rpms(self, names):
        directory = self.root / "rpms"
        directory.mkdir(exist_ok=True)
        for name in names:
            (directory / name).write_text(f"rpm {name}\n", encoding="utf-8")
        return directory

    def desk_rpms(self):
        return self.rpms(CLOSURE)

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
        self.assertIn("--src-dir", res.stdout)
        self.assertIn("system/units", res.stdout)

    def test_src_dir_missing_arg(self):
        self.assertEqual(self.ci("--src-dir").returncode, 5)

    def test_src_dir_accepted(self):
        res = self.pre("--src-dir", str(DISTRO / "specs"),
                       "--skip-install")
        self.assertEqual(res.returncode, 0)

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

    def test_minimal_needs_rpms(self):
        self.assertEqual(
            self.ci("--iso-base", str(self.base), "--skip-rpms",
                    "--skip-kernel", "--skip-install").returncode, 5)

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
        self.assertEqual(res.stdout.count("# SKIP"), 4)
        self.assertIn("ok 4 - iso checksum", res.stdout)
        manifest = self.manifest()
        for stage in ("rpm=skip", "kernel=skip", "iso=skip",
                      "checksum=pass", "install=skip"):
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
        self.assertIn("acceptance=0", manifest)
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

    def test_rpm_fail_blocks_downstream(self):
        """rpm 段失败后必须立即收口，不再空转闭包收割与装机。

        缺载荷的组装不可能产出可用镜像，继续跑只会把秒级编译错误放大成
        小时级空转（run 42039949529）；失败必须只留在根因段。
        """
        self.tools(desk=True)
        res = self.ci("--iso-base", str(self.base), "--rpms",
                      str(self.rpms(KERNEL)), "--runs", "1",
                      "--skip-kernel", FAKE_BUILD_RPMS_MODE="fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 1 - rpm build", res.stdout)
        self.assertIn("not ok 3 - iso assembly", res.stdout)
        self.assertIn("blocked: rpm build failed", res.stdout)
        self.assertIn("# SKIP blocked: rpm build failed", res.stdout)
        manifest = self.manifest()
        self.assertIn("stage iso=blocked", manifest)
        self.assertIn("stage install=skip", manifest)
        self.assertFalse((self.out / "logs" / "build-desktop.log").exists())

    def test_full_chain(self):
        self.tools(desk=True)
        res = self.ci("--iso-base", str(self.base),
                      "--ks", str(BASE_ISO), "--arch", "x86_64",
                      "--rpms", str(self.rpms(KERNEL)),
                      "--runs", "1", "--skip-rpms", "--skip-kernel")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ok 3 - iso assembly", res.stdout)
        self.assertIn("ok 4 - iso checksum", res.stdout)
        self.assertIn("ok 5 - install test", res.stdout)
        manifest = self.manifest()
        self.assertIn("profile=minimal", manifest)
        self.assertIn("stage iso=pass", manifest)
        self.assertRegex(manifest, r"iso [0-9a-f]{64} airymaxos-")
        self.assertIn("result=pass", manifest)
        iso = self.out / "iso" / ISO_NAME
        self.assertTrue(iso.is_file())
        body = iso.read_text(encoding="utf-8")
        self.assertIn("airymaxos-offline", body)
        self.assertIn("=== /airymax/payload-manifest.txt", body)

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
        iso = self.out / "desktop" / "iso" / ISO_NAME
        self.assertTrue(iso.is_file())
        self.assertIn("airymaxos-offline", iso.read_text(encoding="utf-8"))
        self.assertIn("=== /airymax/payload-manifest.txt",
                      iso.read_text(encoding="utf-8"))

    def test_desktop_marker_missing(self):
        self.tools(desk=True)
        rpms = self.desk_rpms()
        res = self.ci("--iso-base", str(self.base), "--profile", "desktop",
                      "--arch", "x86_64", "--rpms", str(rpms), "--runs", "1",
                      "--skip-rpms", "--skip-kernel",
                      FAKE_QEMU_BOOT_MODE="login-only")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 5", res.stdout)
        self.assertIn("stage install=fail", self.manifest())

    def test_acceptance_needs_desktop(self):
        self.assertEqual(self.pre("--acceptance").returncode, 5)

    def test_acceptance_ks_conflict(self):
        res = self.ci("--iso-base", str(self.base), "--profile", "desktop",
                      "--ks", str(BASE_ISO), "--acceptance",
                      "--skip-rpms", "--skip-kernel", "--skip-install")
        self.assertEqual(res.returncode, 5)

    def test_acceptance_prebuilt_iso(self):
        res = self.pre("--acceptance", "--profile", "desktop")
        self.assertEqual(res.returncode, 5)

    def test_acceptance_chain(self):
        self.tools(desk=True)
        rpms = self.desk_rpms()
        res = self.ci("--iso-base", str(self.base), "--profile", "desktop",
                      "--arch", "x86_64", "--rpms", str(rpms), "--runs", "1",
                      "--acceptance", "--skip-rpms", "--skip-kernel",
                      FAKE_QEMU_BOOT_MODE="smoke-pass")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("acceptance=1", self.manifest())
        ks = self.out / "acceptance" / "airymaxos-acceptance.ks"
        self.assertIn("# AIRYMAX-ACCEPTANCE-FIXTURE",
                      ks.read_text(encoding="utf-8"))
        iso = self.out / "desktop" / "iso" / ISO_NAME
        body = iso.read_text(encoding="utf-8")
        self.assertIn("=== /run-smoke.sh", body)
        self.assertIn("=== /fixture/airymax-smoke-run.sh", body)

    def test_acceptance_smoke_fail(self):
        self.tools(desk=True)
        rpms = self.desk_rpms()
        res = self.ci("--iso-base", str(self.base), "--profile", "desktop",
                      "--arch", "x86_64", "--rpms", str(rpms), "--runs", "1",
                      "--acceptance", "--skip-rpms", "--skip-kernel",
                      FAKE_QEMU_BOOT_MODE="smoke-fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not ok 5", res.stdout)
        self.assertIn("stage install=fail", self.manifest())

    def test_source_date_epoch(self):
        self.tools()
        res = self.pre("--runs", "1", SOURCE_DATE_EPOCH="1700000000")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("source_date_epoch=1700000000", self.manifest())

    def test_install_skip_keeps_checksum(self):
        """装机段跳过不影响 ISO 完整性校验：只出镜像也必须核 sha256。"""
        self.tools()
        res = self.pre("--skip-install")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ok 4 - iso checksum", res.stdout)
        self.assertIn("stage checksum=pass", self.manifest())


class MediaArgsTest(unittest.TestCase):
    """构建段的产物根同时含 RPMS/ 与 work/，只有前者可进离线仓库。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.distro = self.root / "src" / "agent-linux" / "distro"
        (self.distro / "ci").mkdir(parents=True)
        libs = self.distro / "scripts" / "lib"
        libs.mkdir(parents=True)
        shutil.copy2(SCRIPT, self.distro / "ci" / "run-image-ci.sh")
        for name in LIB_SH:
            shutil.copy2(DISTRO / "scripts" / "lib" / name, libs / name)
        self.write("build-rpms.sh", FAKE_BUILD)
        self.write("build-kernel.sh", FAKE_BUILD)
        self.write("build-desktop.sh", FAKE_DESKTOP)
        self.out = self.root / "out"
        self.base = self.root / "base.iso"
        self.base.write_text("fake base\n", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fakes.link_tools(self.bin)
        self.args = self.root / "desktop.args"

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, body):
        path = self.distro / "scripts" / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def test_build_dirs_exclude_work_tree(self):
        script = self.distro / "ci" / "run-image-ci.sh"
        env = {"PATH": str(self.bin), "HOME": str(self.root),
               "ARGS_LOG": str(self.args)}
        res = subprocess.run(
            [BASH, str(script), "--out", str(self.out), "--profile", "desktop",
             "--iso-base", str(self.base), "--skip-install"],
            env=env, text=True, capture_output=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.args.read_text(encoding="utf-8").split(),
                         [f"{self.out}/rpms/RPMS",
                          f"{self.out}/kernel/RPMS"])
        manifest = (self.out / "image-ci-manifest.txt").read_text(
            encoding="utf-8")
        for stage in ("rpm=pass", "kernel=pass", "iso=pass"):
            self.assertIn(f"stage {stage}", manifest)

    def reuse_rpms(self, pkgs=KERNEL):
        rpms = self.root / "rel-rpms"
        rpms.mkdir()
        for pkg in pkgs:
            (rpms / pkg).write_text("rpm\n", encoding="utf-8")
        return rpms

    def run_reuse(self, rpms, *args):
        env = {"PATH": str(self.bin), "HOME": str(self.root),
               "ARGS_LOG": str(self.args)}
        return subprocess.run(
            [BASH, str(self.distro / "ci" / "run-image-ci.sh"),
             "--out", str(self.out), "--profile", "desktop",
             "--iso-base", str(self.base), "--skip-install",
             "--kernel-rpms", str(rpms), *args],
            env=env, text=True, capture_output=True)

    def test_kernel_reuse_replaces_build(self):
        rpms = self.reuse_rpms()
        res = self.run_reuse(rpms)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("ok 2 - kernel build # SKIP", res.stdout)
        self.assertEqual(self.args.read_text(encoding="utf-8").split(),
                         [f"{self.out}/rpms/RPMS", str(rpms)])
        manifest = (self.out / "image-ci-manifest.txt").read_text(
            encoding="utf-8")
        self.assertIn("stage kernel=reuse", manifest)
        self.assertIn("result=pass", manifest)

    def test_kernel_reuse_incomplete(self):
        res = self.run_reuse(self.reuse_rpms(KERNEL[:2]))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not ok 2 - kernel payload", res.stdout)
        manifest = (self.out / "image-ci-manifest.txt").read_text(
            encoding="utf-8")
        self.assertIn("stage kernel=fail", manifest)
        self.assertIn("result=fail", manifest)

    def test_kernel_reuse_conflicts(self):
        rpms = self.reuse_rpms()
        cases = (("--skip-kernel",), ("--kernel", str(self.root / "src")))
        for extra in cases:
            self.assertEqual(self.run_reuse(rpms, *extra).returncode, 5)
        self.assertEqual(self.run_reuse(self.root / "gone").returncode, 5)

    def test_closure_follows_profile(self):
        script = self.distro / "ci" / "run-image-ci.sh"
        env = {"PATH": str(self.bin), "HOME": str(self.root)}
        cases = (("desk", ("--profile", "desktop"), True),
                 ("mini", (), False),
                 ("off", ("--profile", "desktop", "--no-closure"), False),
                 ("force", ("--closure",), True))
        for label, args, want in cases:
            log = self.root / f"{label}.args"
            env["ARGS_LOG"] = str(log)
            res = subprocess.run(
                [BASH, str(script), "--out", str(self.root / label),
                 "--iso-base", str(self.base), "--skip-install", *args],
                env=env, text=True, capture_output=True)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            body = (self.root / f"{label}.args.all").read_text(
                encoding="utf-8").split()
            self.assertEqual("--closure" in body, want, label)


# 验收载荷有两处声明：run-image-ci.sh 的 accept_ks 决定哪些文件随 ISO 进
# 介质，acceptance.part 决定哪些文件被装进目标系统。两处只靠人眼对齐时，
# 漏拷一行不会报错，只会把判据悄悄改成另一种语义：run 41989055666 的 T23
# 正是镜像里只有 run-smoke.sh 没有 err-budget，棘轮按「读不到即 0」判负。
# 这里把两处声明直接对账，新增载荷少拷贝一次即失败。
class AcceptFixtureTest(unittest.TestCase):
    """accept_ks 声明的载荷必须全部由验收夹具装进目标系统。"""

    ADD = re.compile(r'ADDS\+=\("\$\{DISTRO_ROOT\}/(ci/[^"]+)"\)')
    COPY = re.compile(r"/run/install/repo/(\S+)")

    def test_payload_installed(self):
        part = DISTRO / "ci" / "ks" / "acceptance.part"
        adds = self.ADD.findall(SCRIPT.read_text(encoding="utf-8"))
        self.assertTrue(adds, "accept_ks 未声明任何载荷")
        copied = set(self.COPY.findall(part.read_text(encoding="utf-8")))
        # mkksiso -a 按 basename 落到 ISO 根：文件即原名，目录保留其名。
        want = set()
        for rel in adds:
            path = DISTRO / rel
            name = path.name
            if path.is_dir():
                want |= {f"{name}/{p.name}" for p in path.iterdir()
                         if p.is_file()}
            else:
                want.add(name)
        self.assertEqual(sorted(want - copied), [])


if __name__ == "__main__":
    unittest.main()
