#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_ks_spec.py — 安装配方规格提取契约
#
# 构建期闭包收割依赖本工具把 kickstart 翻译为仓库表与包规格。若解析
# 与实际配方漂移，收割出的离线仓库就会缺包，安装期退回网络下载。
# 因此测试同时锁定真实配方的仓库成本序、环境组与排除项。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import gzip
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import ks_spec  # noqa: E402

SCRIPT = TOOLS / "ks_spec.py"
DISTRO = TOOLS.parent
KS = DISTRO / "kickstart" / "airymaxos-workstation.ks"
COMPS = DISTRO / "comps" / "airymaxos-comps.xml"
PYTHON = sys.executable
ENV = "airymax-workstation"


def stage_repo(root, raw, gz=True):
    """按 createrepo_c 的产物布局写一个最小仓库索引。"""
    repodata = Path(root) / "repodata"
    repodata.mkdir(parents=True, exist_ok=True)
    name = "comps.xml.gz" if gz else "comps.xml"
    data = raw.encode("utf-8")
    (repodata / name).write_bytes(gzip.compress(data) if gz else data)
    (repodata / "repomd.xml").write_text(
        '<repomd><data type="group">'
        f'<location href="repodata/{name}"/></data></repomd>',
        encoding="utf-8")


class KsSpecTest(unittest.TestCase):
    def setUp(self):
        self.text = KS.read_text(encoding="utf-8")

    def test_repos_real(self):
        rows = ks_spec.repos(self.text)
        names = [row[0] for row in rows]
        self.assertEqual(names, ["baseos", "update", "epol", "epol-update",
                                 "everything", "airymaxos-offline"])
        costs = {row[0]: row[2] for row in rows}
        self.assertEqual(costs["baseos"], "1000")
        self.assertEqual(costs["update"], "100")
        self.assertEqual(costs["everything"], "2000")
        self.assertEqual(costs["airymaxos-offline"], "1")

    def test_repos_baseurl(self):
        rows = dict((row[0], row[1]) for row in ks_spec.repos(self.text))
        self.assertTrue(rows["baseos"].endswith("/OS/$basearch/"))
        self.assertTrue(rows["airymaxos-offline"].startswith("file://"))

    def test_skip_file(self):
        rows = ks_spec.repos(self.text)
        kept = [row for row in rows if not row[1].startswith("file:")]
        self.assertNotIn("airymaxos-offline", [row[0] for row in kept])
        self.assertEqual(len(kept), 5)

    def test_pkgs_real(self):
        rows = ks_spec.pkgs(self.text)
        install = [spec for kind, spec in rows if kind == "install"]
        exclude = [spec for kind, spec in rows if kind == "exclude"]
        self.assertIn("@^airymax-workstation", install)
        self.assertIn("airymaxos-kernel", install)
        self.assertIn("airymaxos-system", install)
        for spec in ("kernel", "kernel-tools", "openEuler-release",
                     "openEuler-latest-release", "kylin-ai*"):
            self.assertIn(spec, exclude)

    def test_pkgs_ignores_scripts(self):
        text = ("%packages\nfoo\n%end\n"
                "%post\n-bar\n%end\n")
        self.assertEqual(ks_spec.pkgs(text), [("install", "foo")])

    def test_pkgs_requires_end(self):
        with self.assertRaises(ValueError):
            ks_spec.pkgs("%packages\nfoo\n")

    def test_repo_requires_baseurl(self):
        with self.assertRaises(ValueError):
            ks_spec.repos("repo --name=epol --cost=100\n")

    def test_url_requires_url(self):
        with self.assertRaises(ValueError):
            ks_spec.repos("url\n")

    def test_cli_repos(self):
        res = subprocess.run([PYTHON, str(SCRIPT), "repos", "--skip-file",
                              str(KS)], text=True, capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = [line.split("\t") for line in res.stdout.splitlines()]
        self.assertEqual(rows[0], ["baseos",
                                   "https://repo.openeuler.org/openEuler-24.03-"
                                   "LTS-SP2/OS/$basearch/", "1000"])
        self.assertEqual(len(rows), 5)

    def test_cli_pkgs(self):
        res = subprocess.run([PYTHON, str(SCRIPT), "pkgs",
                              "--comps", str(COMPS), str(KS)],
                             text=True, capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        lines = res.stdout.splitlines()
        self.assertIn("install\t@airymax-desktop-core", lines)
        self.assertIn("install\t@airymax-desktop", lines)
        self.assertIn("exclude\tkylin-ai*", lines)
        self.assertFalse([row for row in lines if row.startswith("install\t@^")])
        self.assertEqual(lines.count("install\t@airymax-desktop-core"), 1)

    def test_cli_pkgs_needs_comps(self):
        res = subprocess.run([PYTHON, str(SCRIPT), "pkgs", str(KS)],
                             text=True, capture_output=True)
        self.assertEqual(res.returncode, 5)
        self.assertIn("需 --comps 展开", res.stderr)

    def test_cli_envs(self):
        res = subprocess.run([PYTHON, str(SCRIPT), "envs", str(KS)],
                             text=True, capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.splitlines(), [ENV])

    def test_expand_dedup(self):
        rows = [("install", "@^" + ENV),
                ("install", "@airymax-desktop"),
                ("exclude", "kernel")]
        out = ks_spec.expand_envs(rows, COMPS)
        self.assertEqual(out, [("install", "@airymax-desktop-core"),
                               ("install", "@airymax-desktop"),
                               ("exclude", "kernel")])

    def test_expand_unknown_env(self):
        with self.assertRaises(ValueError):
            ks_spec.expand_envs([("install", "@^no-such-env")], COMPS)

    def test_cli_verify_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage_repo(tmp, COMPS.read_text(encoding="utf-8"))
            res = subprocess.run([PYTHON, str(SCRIPT), "verify", "--env",
                                  ENV, tmp], text=True, capture_output=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            lines = res.stdout.splitlines()
            self.assertIn("env\t" + ENV, lines)
            self.assertIn("group\tairymax-desktop-core", lines)
            res = subprocess.run([PYTHON, str(SCRIPT), "verify", "--env",
                                  "no-such-env", tmp],
                                 text=True, capture_output=True)
            self.assertEqual(res.returncode, 5)

    def test_verify_plain_comps(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage_repo(tmp, COMPS.read_text(encoding="utf-8"), gz=False)
            res = subprocess.run([PYTHON, str(SCRIPT), "verify", "--env",
                                  ENV, tmp], text=True, capture_output=True)
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_verify_env_dropped(self):
        raw = re.sub(r"(?s)<environment\b.*?</environment>", "",
                     COMPS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            stage_repo(tmp, raw)
            res = subprocess.run([PYTHON, str(SCRIPT), "verify", "--env",
                                  ENV, tmp], text=True, capture_output=True)
            self.assertEqual(res.returncode, 5)
            self.assertIn("缺少环境", res.stderr)

    def test_cli_rejects_bad_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.ks"
            bad.write_text("%packages\nfoo\n", encoding="utf-8")
            res = subprocess.run([PYTHON, str(SCRIPT), "pkgs", str(bad)],
                                 text=True, capture_output=True)
            self.assertEqual(res.returncode, 5)
            self.assertIn("%packages 缺少 %end", res.stderr)


if __name__ == "__main__":
    unittest.main()
