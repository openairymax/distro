#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_ukui_check.py — UKUI 台账校验器（ukui_check）的判据回归
#
# 校验器断言四份文件同源：台账、comps、冻结输入、内部取证册。真实树常年
# 为绿，所以逐条破坏单一判据，断言错误码而不是文案。main() 走一遍端到端
# 夹具，保证 CLI 参数解析、退出码与聚合输出也在这条回归里。
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

import ukui_check

LEDGER = """\
base: openEuler-24.03-LTS-SP2
arch: x86_64
segments:
  - OS
  - update
  - EPOL/main
  - EPOL/update/main
  - everything

policy:
  route: base-highest-stable
  generation: 3.1
  deferred: ukui-4.24

components:
  - name: ukui-kwin
    state: present
    segment: EPOL/main
    nvra: ukui-kwin-0:1.0.5-8.oe2403sp2.x86_64
  - name: ukui-panel
    state: present
    segment: EPOL/main
    nvra: ukui-panel-0:3.1.0-14.oe2403sp2.x86_64
  - name: ukui-session-manager
    state: present
    segment: EPOL/main
    nvra: ukui-session-manager-0:3.1.0-7.oe2403sp2.x86_64
  - name: ukui-control-center
    state: present
    segment: EPOL/main
    nvra: ukui-control-center-0:3.1.2-33.oe2403sp2.x86_64
  - name: ukui-menu
    state: present
    segment: EPOL/main
    nvra: ukui-menu-0:3.1.1-14.oe2403sp2.x86_64
  - name: ukui-biometric-auth
    state: present
    segment: EPOL/main
    nvra: ukui-biometric-auth-0:1.2.4-2.oe2403sp2.x86_64
  - name: ukui-desktop-environment
    state: available
    segment: EPOL/main
    nvra: ukui-desktop-environment-0:2.0.2-20.oe2403sp2.x86_64
  - name: ukui
    state: available
    segment: EPOL/main
    nvra: ukui-0:2.0.2-20.oe2403sp2.x86_64
  - name: ukui-shell
    state: absent
    segment: 五段均无
"""

COMPS = """\
<?xml version="1.0" encoding="UTF-8"?>
<comps>
  <group>
    <id>airymax-core</id>
    <packagelist>
      <packagereq type="mandatory">ukui-kwin</packagereq>
      <packagereq type="mandatory">ukui-panel</packagereq>
      <packagereq type="mandatory">ukui-session-manager</packagereq>
      <packagereq type="mandatory">ukui-control-center</packagereq>
    </packagelist>
  </group>
  <group>
    <id>airymax-desktop</id>
    <packagelist>
      <packagereq type="default">ukui-menu</packagereq>
      <packagereq type="optional">ukui-biometric-auth</packagereq>
    </packagelist>
  </group>
  <environment>
    <id>airymax-workstation</id>
    <grouplist>
      <groupid>airymax-core</groupid>
      <groupid>airymax-desktop</groupid>
    </grouplist>
  </environment>
</comps>
"""

SEEDS = """\
packages:
  - ukui-kwin
  - ukui-panel
  - ukui-session-manager
  - ukui-control-center
  - ukui-menu
repos:
  - name: epol
"""

DELTA = """\
# 差异清单

| 组件 | NVRA |
|---|---|
| kwin | `ukui-kwin-0:1.0.5-8.oe2403sp2.x86_64` |
| panel | `ukui-panel-0:3.1.0-14.oe2403sp2.x86_64` |
| session | `ukui-session-manager-0:3.1.0-7.oe2403sp2.x86_64` |
| ccc | `ukui-control-center-0:3.1.2-33.oe2403sp2.x86_64` |
| menu | `ukui-menu-0:3.1.1-14.oe2403sp2.x86_64` |
| bio | `ukui-biometric-auth-0:1.2.4-2.oe2403sp2.x86_64` |

```sh
dnf -q repoquery --repo=epol "ukui-*"
```
"""

FEAS = """\
# 可行性

路线 A：自建 4.24 闭包。
路线 B：取基底 3.1 组件代。
基底无 ukui-shell；4.24 顺延。
"""


class LedgerTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def codes(self, func, *args):
        out = []
        func(*args, out)
        return [line.split(":")[0] for line in out]

    def test_parse_sections(self):
        led = ukui_check.parse_ledger(self.write("l.yaml", LEDGER))
        self.assertEqual(led["base"], "openEuler-24.03-LTS-SP2")
        self.assertEqual(len(led["segments"]), 5)
        self.assertEqual(led["policy"]["deferred"], "ukui-4.24")
        self.assertEqual(len(led["components"]), 9)
        self.assertEqual(led["components"][0]["nvra"],
                         "ukui-kwin-0:1.0.5-8.oe2403sp2.x86_64")

    def test_schema_rejects_drift(self):
        bad = LEDGER.replace("SP2", "SP3").replace("generation: 3.1",
                                                   "generation: 4.24")
        led = ukui_check.parse_ledger(self.write("l.yaml", bad))
        self.assertEqual(self.codes(ukui_check.check_schema, led),
                         ["schema/base", "schema/policy"])

    def test_schema_rejects_arch_and_segments(self):
        led = ukui_check.parse_ledger(
            self.write("l.yaml", LEDGER.replace("arch: x86_64",
                                                "arch: aarch64")))
        led["segments"] = led["segments"][:-1]
        self.assertEqual(self.codes(ukui_check.check_schema, led),
                         ["schema/arch", "schema/segments"])

    def test_items_core_and_absent(self):
        bad = LEDGER.replace("""  - name: ukui-kwin
    state: present""", """  - name: ukui-kwin
    state: absent""").replace("""  - name: ukui-shell
    state: absent""", """  - name: ukui-shell
    state: present
    segment: EPOL/main
    nvra: ukui-shell-0:1.0-1.x86_64""")
        led = ukui_check.parse_ledger(self.write("l.yaml", bad))
        got = self.codes(ukui_check.check_items, led)
        self.assertIn("ledger/core", got)
        self.assertIn("ledger/absent", got)
        self.assertIn("ledger/segment", got)

    def test_items_rejects_bad_nvra_and_dup(self):
        bad = LEDGER.replace("nvra: ukui-panel-0:3.1.0-14",
                             "nvra: ukui-panel-0:3.1.0")
        bad += "  - name: ukui-menu\n    state: present\n" \
               "    segment: EPOL/main\n    nvra: ukui-menu-0:1-1.x86_64\n"
        led = ukui_check.parse_ledger(self.write("l.yaml", bad))
        got = self.codes(ukui_check.check_items, led)
        self.assertIn("ledger/nvra", got)
        self.assertIn("ledger/name", got)

    def test_items_available_must_stay_unpicked(self):
        bad = LEDGER.replace("""  - name: ukui
    state: available""", """  - name: ukui
    state: present""")
        led = ukui_check.parse_ledger(self.write("l.yaml", bad))
        self.assertEqual(self.codes(ukui_check.check_items, led),
                         ["ledger/available"])

    def test_items_rejects_bad_state(self):
        bad = LEDGER.replace("""  - name: ukui-shell
    state: absent""", """  - name: ukui-shell
    state: gone""").replace(
            "nvra: ukui-0:2.0.2-20", "nvra: ukui-meta-0:2.0.2-20")
        led = ukui_check.parse_ledger(self.write("l.yaml", bad))
        self.assertEqual(self.codes(ukui_check.check_items, led),
                         ["ledger/nvra", "ledger/state", "ledger/absent"])


class CompsTest(unittest.TestCase):

    def load(self, text=COMPS):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "comps.xml"
        path.write_text(text, encoding="utf-8")
        return ukui_check.read_comps(path)

    def test_closure_skips_optional(self):
        groups, root = self.load()
        pres = {"ukui-kwin", "ukui-panel", "ukui-session-manager",
                "ukui-control-center", "ukui-menu", "ukui-biometric-auth"}
        out = []
        want = ukui_check.check_comps(groups, root, pres, out)
        self.assertEqual(out, [])
        self.assertNotIn("ukui-biometric-auth", want)
        self.assertEqual(len(want), 5)

    def test_phantom_and_missing(self):
        text = COMPS.replace(
            '<packagereq type="default">ukui-menu</packagereq>',
            '<packagereq type="optional">ukui-shell</packagereq>')
        groups, root = self.load(text)
        pres = {"ukui-kwin", "ukui-panel", "ukui-session-manager",
                "ukui-control-center", "ukui-menu", "ukui-biometric-auth"}
        out = []
        ukui_check.check_comps(groups, root, pres, out)
        codes = [line.split(":")[0] for line in out]
        self.assertIn("comps/phantom", codes)
        self.assertIn("comps/missing", codes)

    def test_duplicate_declaration(self):
        text = COMPS.replace(
            '<packagereq type="mandatory">ukui-control-center</packagereq>',
            '<packagereq type="mandatory">ukui-control-center</packagereq>'
            '\n      <packagereq type="default">ukui-menu</packagereq>')
        groups, root = self.load(text)
        pres = {"ukui-kwin", "ukui-panel", "ukui-session-manager",
                "ukui-control-center", "ukui-menu", "ukui-biometric-auth"}
        out = []
        ukui_check.check_comps(groups, root, pres, out)
        self.assertEqual([line.split(":")[0] for line in out], ["comps/dup"])


class SeedsTest(unittest.TestCase):

    def test_read_only_packages_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rpms.in.yaml"
            path.write_text(SEEDS, encoding="utf-8")
            self.assertEqual(ukui_check.read_seeds(path),
                             {"ukui-kwin", "ukui-panel",
                              "ukui-session-manager",
                              "ukui-control-center", "ukui-menu"})

    def test_reports_missing_and_phantom(self):
        pres = {"ukui-kwin", "ukui-panel", "ukui-session-manager",
                "ukui-control-center", "ukui-menu"}
        have = {"ukui-kwin", "ukui-shell"}
        want = {"ukui-kwin", "ukui-menu"}
        out = []
        ukui_check.check_seeds(have, pres, want, out)
        codes = [line.split(":")[0] for line in out]
        self.assertEqual(codes, ["seeds/phantom", "seeds/missing"])

    def test_ignores_non_ukui(self):
        out = []
        ukui_check.check_seeds({"NetworkManager-wifi"}, set(), set(), out)
        self.assertEqual(out, [])


class DocsTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / "ukui-delta.md").write_text(DELTA, encoding="utf-8")
        (self.dir / "ukui-424-feasibility.md").write_text(
            FEAS, encoding="utf-8")
        self.pres = [{"nvra": "ukui-kwin-0:1.0.5-8.oe2403sp2.x86_64"}]

    def codes(self):
        out = []
        ukui_check.check_docs(self.dir, self.pres, out)
        return [line.split(":")[0] for line in out]

    def test_complete(self):
        self.assertEqual(self.codes(), [])

    def test_missing_book(self):
        (self.dir / "ukui-424-feasibility.md").unlink()
        self.assertEqual(self.codes(), ["docs/missing"])

    def test_nvra_drift(self):
        (self.dir / "ukui-delta.md").write_text(
            DELTA.replace("1.0.5-8", "1.0.5-9"), encoding="utf-8")
        self.assertIn("docs/nvra", self.codes())

    def test_recalc_and_feas_marks(self):
        (self.dir / "ukui-delta.md").write_text(
            DELTA.replace("dnf -q repoquery", ""), encoding="utf-8")
        (self.dir / "ukui-424-feasibility.md").write_text(
            FEAS.replace("路线 B", ""), encoding="utf-8")
        self.assertEqual(self.codes(), ["docs/recalc", "docs/feas"])


class MainTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.docs = self.root / "docs"
        for sub in ("distro/lockfile", "distro/comps", "docs"):
            (self.root / sub).mkdir(parents=True)
        (self.root / "distro/lockfile/ukui-components.yaml").write_text(
            LEDGER, encoding="utf-8")
        (self.root / "distro/comps/airymaxos-comps.xml").write_text(
            COMPS, encoding="utf-8")
        (self.root / "distro/lockfile/rpms.in.yaml").write_text(
            SEEDS, encoding="utf-8")
        (self.docs / "ukui-delta.md").write_text(DELTA, encoding="utf-8")
        (self.docs / "ukui-424-feasibility.md").write_text(
            FEAS, encoding="utf-8")

    def run_main(self, *argv):
        args = ["ukui_check", "verify", "--root", str(self.root), *argv]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", args), \
                redirect_stdout(out), redirect_stderr(err):
            code = ukui_check.main()
        return code, out.getvalue(), err.getvalue()

    def test_verify_passes_with_docs(self):
        code, out, err = self.run_main("--docs", str(self.docs))
        self.assertEqual(code, 0, err)
        self.assertIn("台账 6 组件，默认安装集 5 项", out)

    def test_verify_reports_drift(self):
        path = self.root / "distro/lockfile/rpms.in.yaml"
        path.write_text(SEEDS.replace("  - ukui-menu\n", ""),
                        encoding="utf-8")
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("seeds/missing", err)
        self.assertIn("1 项失败", err)

    def test_missing_ledger(self):
        (self.root / "distro/lockfile/ukui-components.yaml").unlink()
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("ledger/missing", err)

    def test_unreadable_comps(self):
        (self.root / "distro/comps/airymaxos-comps.xml").write_text(
            "<comps>", encoding="utf-8")
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("comps/unreadable", err)


if __name__ == "__main__":
    unittest.main()
