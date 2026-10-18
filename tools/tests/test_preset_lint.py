#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_preset_lint.py — preset_lint 规则回归测试
#
# 每个用例以最小合法 preset 与单元集合为基线，只做单点变异，断言目标
# 规则号出现；规则间耦合时能立刻定位被破坏的那一条。用标准库 unittest
# 编写，可被 pytest 直接收集。
#
# Author: Decheng Li <lidecheng@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preset_lint

VALID = """\
# baseline preset
disable agentrt.target
disable agentrt-dsl.target
disable agentrt-*.service
"""

INSTALL = """\
[Unit]
Description=demo

[Install]
WantedBy=multi-user.target
"""

NO_INSTALL = """\
[Unit]
Description=demo template
"""

SPEC = (Path(__file__).resolve().parent.parent.parent
        / "specs" / "airymaxos-system.spec")


class PresetLintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.units = self.root / "units"
        self.units.mkdir()
        self.preset = self.root / "90-airymax.preset"
        for name in ("agentrt.target", "agentrt-dsl.target",
                     "agentrt-a.service"):
            (self.units / name).write_text(INSTALL, encoding="utf-8")
        (self.units / "agentrt-tmpl@.service").write_text(
            NO_INSTALL, encoding="utf-8")
        self.write(VALID)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text, mode=0o644):
        self.preset.write_text(text, encoding="utf-8")
        self.preset.chmod(mode)

    def codes(self):
        issues = preset_lint.lint_file(self.preset, self.units)
        return {issue.code for issue in issues}

    def test_valid(self):
        self.assertEqual(set(), self.codes())

    def test_comments_ignored(self):
        self.write("# disable agentrt-gone.service\n" + VALID)
        self.assertEqual(set(), self.codes())

    def test_bad_action(self):
        self.write(VALID + "enabled agentrt-a.service\n")
        self.assertIn("P002", self.codes())

    def test_empty_pattern(self):
        self.write(VALID + "disable\n")
        self.assertIn("P002", self.codes())

    def test_uncovered(self):
        self.write("disable agentrt.target\ndisable agentrt-dsl.target\n")
        self.assertIn("P003", self.codes())

    def test_no_install_free(self):
        (self.units / "agentrt-a.service").write_text(
            NO_INSTALL, encoding="utf-8")
        self.write("disable agentrt.target\ndisable agentrt-dsl.target\n")
        self.assertEqual(set(), self.codes())

    def test_enable_denied(self):
        self.write(VALID + "enable agentrt-a.service\n")
        self.assertIn("P004", self.codes())

    def test_ignore_denied(self):
        self.write(VALID + "ignore agentrt.target\n")
        self.assertIn("P004", self.codes())

    def test_stale_pattern(self):
        self.write(VALID + "disable agentrt-gone.service\n")
        self.assertIn("P005", self.codes())

    def test_crlf(self):
        self.write(VALID.replace("\n", "\r\n"))
        self.assertIn("P006", self.codes())

    def test_tab(self):
        self.write(VALID + "\tdisable agentrt-a.service\n")
        self.assertIn("P006", self.codes())

    def test_no_final_newline(self):
        self.write(VALID.rstrip("\n"))
        self.assertIn("P006", self.codes())

    def test_trailing_space(self):
        self.write(VALID + "disable agentrt-a.service \n")
        self.assertIn("P006", self.codes())

    def test_trailing_blank(self):
        self.write(VALID + "\n")
        self.assertIn("P006", self.codes())

    def test_mode(self):
        self.write(VALID, mode=0o600)
        self.assertIn("P006", self.codes())

    def test_non_utf8(self):
        self.preset.write_bytes(b"disable agentrt.target\n\xff\n")
        self.assertIn("P001", self.codes())

    def test_missing_preset(self):
        self.preset.unlink()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = preset_lint.main([str(self.preset), str(self.units)])
        self.assertEqual(2, rc)

    def test_missing_units(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = preset_lint.main([str(self.preset),
                                   str(self.root / "absent")])
        self.assertEqual(2, rc)

    def test_real_preset(self):
        issues = preset_lint.lint_file(preset_lint.DEFAULT,
                                       preset_lint.UNITS)
        self.assertEqual([], issues)

    def test_spec_installs(self):
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("Source19:       90-airymax.preset", text)
        self.assertIn("%{_presetdir}/90-airymax.preset", text)
        self.assertIn("install -m 0644 %{_sourcedir}/90-airymax.preset",
                      text)


if __name__ == "__main__":
    unittest.main()
