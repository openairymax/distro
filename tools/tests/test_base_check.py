#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_base_check.py — 基底选型校验器（base_check）的判据回归
#
# 校验器把「取哪个 SP」与七个消费面绑在一起，真实树常年为绿，所以逐条
# 破坏单一判据，断言错误码而不是文案。main() 走一遍端到端夹具，保证 CLI
# 参数解析、退出码与聚合输出也在这条回归里。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent
                       / "lockfile"))

import base_check
import lineyaml

BASE = "openEuler-24.03-LTS-SP3"
BASE_YAML = """\
deadline: 2027-09-17
selected: openEuler-24.03-LTS-SP3
arch: x86_64
kernel_line: 6.6

policy:
  kind: large-sp-only
  eol-covers: 2027-09-17

candidates:
  - name: openEuler-24.03-LTS-SP1
    ga: 2024-12-30
    kind: large
    eol: 2026-12-30
    kernel: 6.6
  - name: openEuler-24.03-LTS-SP2
    ga: 2025-06-30
    kind: small
    eol: 2026-03-30
    kernel: 6.6
  - name: openEuler-24.03-LTS-SP3
    ga: 2025-12-30
    kind: large
    eol: 2027-12-30
    kernel: 6.6
  - name: openEuler-24.03-LTS-SP4
    ga: 2026-06-30
    kind: small
    eol: 2027-03-30
    kernel: 6.6
"""

SEGS = ("base", "updates", "epol", "epol-updates", "everything")
ROOTS = ("https://repo.openeuler.org",
         "https://mirrors.tuna.tsinghua.edu.cn/openeuler",
         "https://mirrors.huaweicloud.com/openeuler")
SUBS = ("OS", "update", "EPOL/main", "EPOL/update/main", "everything")
REPO = "".join(
    "".join([
        "[airymaxos-%s]\n" % seg,
        "name=AiryMaxOS 24.03 - %s\n" % seg,
        "baseurl=%s\n" % " ".join("%s/%s/%s/$basearch/" % (root, BASE, sub)
                                  for root in ROOTS),
        "enabled=1\n",
        "gpgcheck=0\n\n",
    ]) for seg, sub in zip(SEGS, SUBS))
MIRRORS = "\n".join("%s/%s" % (root, BASE) for root in ROOTS) + "\n"
SEEDS = """\
contentOrigin:
  repos:
""" + "".join("    - repoid: %s\n      baseurl: %s/%s/%s/\n"
              % (seg, ROOTS[0], BASE, sub)
              for seg, sub in zip(SEGS, SUBS))
SPEC = ("%global oe_base " + BASE + "\n"
        "# 0.0.4 取基底 openEuler 24.03 LTS SP3\n"
        "Name: airymaxos-release\n\n"
        "%changelog\n"
        "* Mon Sep 15 2026 AiryMax <dev@spharx.cn> - 0.0.3-15\n"
        "- 早期版本取 openEuler-24.03-LTS-SP2\n")
KS = """\
url --url=https://repo.openeuler.org/%s/OS/$basearch/
repo --name=update --baseurl=https://repo.openeuler.org/%s/update/$basearch/
""" % (BASE, BASE)
COMPS = ("<?xml version=\"1.0\"?>\n<!-- 基底 %s -->\n<comps/>\n" % BASE)
TREE = ("ref: %s/OS/x86_64\n" % BASE
        + "repos:\n  - %s-EPOL\n" % BASE)
README = "# 桌面\n\n0.0.4 基底 %s。\n" % BASE
POLICY = "#!/bin/sh\n# 基底 %s 的默认策略\n" % BASE
BRAND = "# 品牌配置\nBASE = \"%s\"\n" % BASE


class SchemaTest(unittest.TestCase):

    def codes(self, func, *args):
        out = []
        func(*args, out)
        return [line.split(":")[0] for line in out]

    def load(self, text):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "base.yaml"
        path.write_text(text, encoding="utf-8")
        return lineyaml.load(path)

    def test_schema_complete(self):
        self.assertEqual(self.codes(base_check.check_schema,
                                    self.load(BASE_YAML)), [])

    def test_schema_rejects_bad_day(self):
        self.assertEqual(self.codes(base_check.check_schema, self.load(
            BASE_YAML.replace("deadline: 2027-09-17",
                              "deadline: 2027-13-40"))),
            ["schema/deadline", "schema/policy"])

    def test_schema_rejects_arch_and_kernel(self):
        bad = BASE_YAML.replace("arch: x86_64", "arch: aarch64").replace(
            "kernel_line: 6.6", "kernel_line: 6.12")
        self.assertEqual(self.codes(base_check.check_schema, self.load(bad)),
                         ["schema/arch", "schema/kernel"])

    def test_schema_rejects_policy(self):
        bad = BASE_YAML.replace("kind: large-sp-only", "kind: any-sp")
        self.assertEqual(self.codes(base_check.check_schema, self.load(bad)),
                         ["schema/policy"])

    def test_schema_rejects_name(self):
        bad = BASE_YAML.replace("selected: openEuler-24.03-LTS-SP3",
                                "selected: 24.03")
        self.assertEqual(self.codes(base_check.check_schema, self.load(bad)),
                         ["schema/selected"])


class CandsTest(unittest.TestCase):

    def codes(self, func, *args):
        out = []
        func(*args, out)
        return [line.split(":")[0] for line in out]

    def load(self, text):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "base.yaml"
        path.write_text(text, encoding="utf-8")
        return lineyaml.load(path)

    def test_pick_complete(self):
        dat = self.load(BASE_YAML)
        cands = base_check.check_cands(dat, [])
        out = []
        base_check.check_pick(BASE, cands, dat["deadline"], out)
        self.assertEqual(out, [])

    def test_cands_reject_bad_rows(self):
        bad = BASE_YAML.replace("kind: large\n    eol: 2027-12-30",
                                "kind: huge\n    eol: 2027-12-30").replace(
            "ga: 2024-12-30", "ga: soon").replace(
            "kernel: 6.6\n  - name: openEuler-24.03-LTS-SP2",
            "kernel: 6.12\n  - name: openEuler-24.03-LTS-SP2")
        got = self.codes(base_check.check_cands, self.load(bad))
        self.assertIn("cands/kind", got)
        self.assertIn("cands/date", got)
        self.assertIn("cands/kernel", got)

    def test_cands_reject_dup(self):
        bad = BASE_YAML.replace("  - name: openEuler-24.03-LTS-SP4",
                                "  - name: openEuler-24.03-LTS-SP3")
        self.assertEqual(self.codes(base_check.check_cands, self.load(bad)),
                         ["cands/name"])

    def test_pick_unknown(self):
        dat = self.load(BASE_YAML)
        self.assertEqual(self.codes(base_check.check_pick, "openEuler-24.03"
                                    "-LTS-SP9", base_check.check_cands(
                                        dat, []), dat["deadline"]),
                         ["base/unknown"])

    def test_pick_rejects_small(self):
        dat = self.load(BASE_YAML.replace(
            "selected: openEuler-24.03-LTS-SP3",
            "selected: openEuler-24.03-LTS-SP4"))
        out = []
        base_check.check_pick("openEuler-24.03-LTS-SP4",
                              base_check.check_cands(dat, []),
                              dat["deadline"], out)
        self.assertEqual([line.split(":")[0] for line in out],
                         ["base/small-sp", "base/eol", "base/not-newest"])

    def test_pick_rejects_stale(self):
        dat = self.load(BASE_YAML.replace(
            "selected: openEuler-24.03-LTS-SP3",
            "selected: openEuler-24.03-LTS-SP1"))
        out = []
        base_check.check_pick("openEuler-24.03-LTS-SP1",
                              base_check.check_cands(dat, []),
                              dat["deadline"], out)
        self.assertEqual([line.split(":")[0] for line in out],
                         ["base/eol", "base/not-newest"])


class SurfaceTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def put(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def codes(self, func, *args):
        out = []
        func(*args, out)
        return [line.split(":")[0] for line in out]

    def test_repo_complete(self):
        self.assertEqual(self.codes(base_check.check_repo,
                                    self.put("a.repo", REPO), BASE), [])

    def test_repo_rejects_drift(self):
        bad = REPO.replace(BASE, "openEuler-24.03-LTS-SP2").replace(
            "$basearch/", "$basearch/ $releasever/")
        got = self.codes(base_check.check_repo,
                         self.put("a.repo", bad), BASE)
        self.assertIn("repo/baseurl", got)
        self.assertIn("repo/releasever", got)

    def test_repo_rejects_section_and_host(self):
        bad = REPO.replace("[airymaxos-updates]", "[airymaxos-update]").replace(
            "mirrors.huaweicloud.com", "mirror.example.net")
        got = self.codes(base_check.check_repo,
                         self.put("a.repo", bad), BASE)
        self.assertIn("repo/section", got)
        self.assertIn("repo/host", got)

    def test_repo_rejects_count(self):
        bad = "\n".join(line for line in REPO.splitlines()
                        if not line.startswith("baseurl=")) + "\n"
        self.assertEqual(self.codes(
            base_check.check_repo, self.put("a.repo", bad), BASE),
            ["repo/count"])

    def test_mirrors_complete(self):
        self.assertEqual(self.codes(base_check.check_mirrors,
                                    self.put("m.list", MIRRORS), BASE), [])

    def test_mirrors_rejects_drift(self):
        bad = MIRRORS.replace(ROOTS[0] + "/" + BASE, ROOTS[1] + "/" + BASE)
        got = self.codes(base_check.check_mirrors,
                         self.put("m.list", bad), BASE)
        self.assertEqual(got, ["mirrors/first"])

    def test_mirrors_rejects_root(self):
        bad = MIRRORS.replace("/" + BASE, "")
        got = self.codes(base_check.check_mirrors,
                         self.put("m.list", bad), BASE)
        self.assertIn("mirrors/root", got)

    def test_seeds_complete(self):
        self.assertEqual(self.codes(base_check.check_seeds,
                                    self.put("s.yaml", SEEDS), BASE), [])

    def test_seeds_rejects_drift(self):
        bad = SEEDS.replace(BASE, "openEuler-24.03-LTS-SP2")
        got = self.codes(base_check.check_seeds,
                         self.put("s.yaml", bad), BASE)
        self.assertEqual(got, ["seeds/baseurl"] * 5)

    def test_seeds_rejects_count(self):
        bad = SEEDS.rsplit("    - repoid:", 1)[0]
        got = self.codes(base_check.check_seeds,
                         self.put("s.yaml", bad), BASE)
        self.assertEqual(got, ["seeds/count"])

    def test_spec_complete(self):
        self.assertEqual(self.codes(base_check.check_spec,
                                    self.put("a.spec", SPEC), BASE), [])

    def test_spec_rejects_macro(self):
        bad = SPEC.replace("%global oe_base " + BASE,
                           "%global oe_base openEuler-24.03-LTS-SP2")
        got = self.codes(base_check.check_spec,
                         self.put("a.spec", bad), BASE)
        self.assertEqual(got, ["spec/base", "spec/token"])

    def test_ukui_complete(self):
        self.assertEqual(self.codes(base_check.check_ukui,
                                    self.put("u.yaml", "base: %s\n" % BASE),
                                    BASE), [])

    def test_ukui_rejects_drift(self):
        got = self.codes(base_check.check_ukui,
                         self.put("u.yaml", "base: openEuler-24.03-LTS-SP2\n"),
                         BASE)
        self.assertEqual(got, ["ukui/base"])

    def test_ks_complete(self):
        self.assertEqual(self.codes(base_check.check_ks,
                                    [self.put("a.ks", KS)], BASE), [])

    def test_ks_rejects_drift(self):
        bad = KS.replace(BASE, "openEuler-24.03-LTS-SP2")
        got = self.codes(base_check.check_ks,
                         [self.put("a.ks", bad)], BASE)
        self.assertEqual(got, ["ks/base", "ks/base"])

    def test_tokens_complete(self):
        paths = [self.put(n, t) for n, t in
                 (("c.xml", COMPS), ("t.treefile", TREE), ("r.md", README),
                  ("p.sh", POLICY), ("b.py", BRAND))]
        self.assertEqual(self.codes(base_check.check_tokens, paths, BASE), [])

    def test_tokens_reject_drift(self):
        got = self.codes(base_check.check_tokens,
                         [self.put("r.md", README.replace(BASE,
                                                          "openEuler-24.03"
                                                          "-LTS-SP2"))],
                         BASE)
        self.assertEqual(got, ["token/drift"])

    def test_missing_file(self):
        got = self.codes(base_check.check_mirrors,
                         self.dir / "nope.list", BASE)
        self.assertEqual(got, ["file/missing"])


class MainTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        sub = self.root / "distro"
        for name in ("lockfile", "repo", "specs", "kickstart", "comps",
                     "ostree", "desktop", "tools"):
            (sub / name).mkdir(parents=True)
        files = {
            "lockfile/base.yaml": BASE_YAML,
            "lockfile/rpms.in.yaml": SEEDS,
            "lockfile/ukui-components.yaml": "base: %s\n" % BASE,
            "repo/airymax-os.repo": REPO,
            "repo/mirrors.list": MIRRORS,
            "specs/airymaxos-release.spec": SPEC,
            "kickstart/airymaxos-workstation.ks": KS,
            "kickstart/airymaxos-minimal.ks": KS,
            "comps/airymaxos-comps.xml": COMPS,
            "ostree/airymaxos-workstation.treefile": TREE,
            "desktop/README.md": README,
            "desktop/70-airymax-ukui-policy.sh": POLICY,
            "tools/cfg_brand.py": BRAND,
        }
        for name, text in files.items():
            (sub / name).write_text(text, encoding="utf-8")

    def run_main(self):
        args = ["base_check", "verify", "--root", str(self.root)]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", args), \
                redirect_stdout(out), redirect_stderr(err):
            code = base_check.main()
        return code, out.getvalue(), err.getvalue()

    def test_verify_passes(self):
        code, out, err = self.run_main()
        self.assertEqual(code, 0, err)
        self.assertIn("基底 %s 覆盖收口日到 2027-09-17" % BASE, out)

    def test_verify_reports_drift(self):
        (self.root / "distro/repo/mirrors.list").write_text(
            MIRRORS.replace(ROOTS[0] + "/" + BASE,
                            ROOTS[0] + "/openEuler-24.03-LTS-SP2", 1),
            encoding="utf-8")
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("mirrors/root", err)
        self.assertIn("mirrors/first", err)
        self.assertIn("2 项失败", err)

    def test_missing_base(self):
        (self.root / "distro/lockfile/base.yaml").unlink()
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("schema/base-missing", err)


if __name__ == "__main__":
    unittest.main()
