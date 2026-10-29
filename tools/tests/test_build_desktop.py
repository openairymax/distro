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
import sys
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
MIRROR_LIST = DISTRO / "repo" / "mirrors.list"
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


def ks_pkgs():
    """配方 %packages 段的显式包名（不含组/环境，也不含 - 排除项）。

    dnf 的事务同时包含组内成员与配方显式安装的包，收割器按文件名去重，
    所以载荷新增数必须把这类非组成员算进来（airymaxos-kernel-devel 即
    一例，它是 D-09 补进来的显式包）。
    """
    names, inside = set(), False
    for raw in KS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("%packages"):
            inside = True
            continue
        if inside and line.startswith("%end"):
            break
        if not inside or not line or line[0] in "#@-":
            continue
        names.add(line)
    return names


def rpm_name(name):
    bits = name[:-4].rsplit(".", 1)[0].split("-")
    return "-".join(bits[:-2]) if len(bits) >= 3 else name[:-4]


def mirrors():
    """repo/mirrors.list 的镜像根，行序即优先级（与 bash 侧解析一致）。"""
    out = []
    for raw in MIRROR_LIST.read_text(encoding="utf-8").splitlines():
        root = raw.split("#")[0].strip()
        if root:
            out.append(root)
    return out


def ks_repos():
    """配方里的安装期仓库三元组 (name, baseurl, cost)，与收割端同源。"""
    res = subprocess.run(
        [sys.executable, str(DISTRO / "tools" / "ks_spec.py"), "repos",
         "--skip-file", str(KS)],
        capture_output=True, text=True, check=True)
    return [line.split("\t") for line in res.stdout.splitlines() if line.strip()]


def expected_urls(base, roots):
    """baseurl 展开：命中首项镜像根才补备用地址，否则原样保留。"""
    if not base.startswith(roots[0] + "/"):
        return [base]
    rel = base[len(roots[0]) + 1:]
    return [base] + [f"{root}/{rel}" for root in roots[1:]]


def repo_baseurls(path):
    return [line.split("=", 1)[1].split() for line in
            path.read_text(encoding="utf-8").splitlines()
            if line.startswith("baseurl=")]


# 伪 dnf 的事务是「comps 全量成员 + 配方显式包 + 架构引导包」；本地仓库
# 已有的包复用同一文件名，收割端按文件名去重，因此新增数就是三者合集中
# 尚未在载荷里的包。引导包清单与 closure.sh 的 cl_boot() x86_64 分支一致。
BOOT = {"grub2-pc", "grub2-efi-x64", "shim-x64", "efibootmgr"}
STOCK = {rpm_name(name) for name in CLOSURE}
HARVEST = len((comps_pkgs() | ks_pkgs() | BOOT) - STOCK)
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

    def test_closure_repo_expands_mirrors(self):
        # 2.5 GB 的载荷不得挂在单一主机上：配方每段仓库都要带上镜像根表
        # 里的等价备用地址，主源停滞时 dnf 才能自动换址。
        self.tools()
        self.stock()
        cfg = self.root / "closure.repo"
        res = self.build("--arch", "x86_64", "--closure",
                         FAKE_DNF_CFG=str(cfg))
        self.assertEqual(res.returncode, 0, res.stderr)
        roots = mirrors()
        self.assertGreater(len(roots), 1)
        want = [expected_urls(base, roots) for _, base, _ in ks_repos()]
        self.assertEqual(repo_baseurls(cfg), want)

    def test_closure_repo_no_guess(self):
        # 镜像根首项与配方源不同根时前缀不命中，地址必须原样保留：猜出来的
        # 相对路径会让 dnf 取到 404，比慢更糟。
        self.tools()
        self.stock()
        cfg = self.root / "closure.repo"
        res = self.build("--arch", "x86_64", "--closure",
                         CLOSURE_MIRRORS="https://mirror.invalid/a "
                         "https://mirror.invalid/b", FAKE_DNF_CFG=str(cfg))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(repo_baseurls(cfg),
                         [[base] for _, base, _ in ks_repos()])

    def test_closure_reports_progress(self):
        # 静默的长传输与挂死在 CI 控制台完全同形（run 40839355885 沉默 80
        # 分钟后被人工取消）：收割期间必须按节拍报落盘量。
        self.tools()
        self.stock()
        res = self.build("--arch", "x86_64", "--closure",
                         FAKE_DNF_MODE="slow", FAKE_DNF_SLEEP="2",
                         CLOSURE_BEAT="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("closure: 拉取中 files=", res.stdout)

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
