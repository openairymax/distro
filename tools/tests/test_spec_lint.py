#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_spec_lint.py — spec_lint 规则回归测试
#
# 每个用例以最小合法仓库为基线，只做单点变异，断言目标规则号出现；这样
# 规则间耦合时能立刻定位到被破坏的那一条。用标准库 unittest 编写，可被
# pytest 直接收集。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import spec_lint

VALID = """\
%global demo_version 0.0.3

Name:           airymaxos-demo
Version:        %{demo_version}
Release:        1%{?dist}
Summary:        Demo package
License:        AGPL-3.0-or-later
URL:            https://atomgit.com/openairymax/agent-linux
BuildArch:      noarch

Source0:        demo.conf

%description
Demo package for lint tests.

%prep
%setup -q -c -T

%build

%install
install -D -m 0644 %{SOURCE0} %{buildroot}/etc/demo.conf

%check
test -s %{buildroot}/etc/demo.conf

%files
/etc/demo.conf

%changelog
* Sat Oct 17 2026 SPHARX <dev@spharx.com> - 0.0.3-1
- Initial
"""


class SpecLintTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "release").mkdir()
        self.osrel = self.root / "release" / "os-release"
        self.osrel.write_text('ID=airymaxos\nVERSION_ID="0.0.3"\n',
                              encoding="utf-8")
        (self.root / "demo.conf").write_text("x\n", encoding="utf-8")
        self.spec = self.root / "specs" / "airymaxos-demo.spec"
        self.spec.parent.mkdir()
        self.write(VALID)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, text, path=None):
        (path or self.spec).write_text(text, encoding="utf-8")

    def codes(self, text=None):
        if text is not None:
            self.write(text)
        return [item.code for item in spec_lint.lint_spec(self.spec,
                                                          self.root)]

    def test_valid(self):
        self.assertEqual(self.codes(), [])

    def test_missing_tag(self):
        self.assertIn("E001", self.codes(VALID.replace("Summary:", "#")))

    def test_bad_prefix(self):
        text = VALID.replace("Name:           airymaxos-demo",
                             "Name:           demo")
        self.assertIn("E002", self.codes(text))

    def test_release_dist(self):
        text = VALID.replace("1%{?dist}", "1")
        self.assertIn("E003", self.codes(text))

    def test_license(self):
        text = VALID.replace("AGPL-3.0-or-later", "WTFPL")
        self.assertIn("E004", self.codes(text))

    def test_define(self):
        self.assertIn("E005", self.codes("%define foo bar\n" + VALID))

    def test_buildroot(self):
        self.assertIn("E006", self.codes(VALID + "\nBuildRoot: /tmp/x\n"))

    def test_section(self):
        text = VALID.replace("%check\ntest -s "
                             "%{buildroot}/etc/demo.conf\n\n", "")
        self.assertIn("E007", self.codes(text))

    def test_empty_files(self):
        text = VALID.replace("%files\n/etc/demo.conf\n", "%files\n\n")
        self.assertIn("E008", self.codes(text))

    def test_subpackage(self):
        text = VALID + "\n%package devel\nSummary: devel\n"
        self.assertIn("E009", self.codes(text))

    def test_missing_source(self):
        text = VALID.replace("demo.conf", "gone.conf")
        self.assertIn("E010", self.codes(text))

    def test_macro_source(self):
        text = VALID.replace("Source0:        demo.conf",
                             "%global demo_src demo.conf\n"
                             "Source0:        %{demo_src}")
        self.assertEqual(self.codes(text), [])

    def test_generated_source(self):
        text = VALID.replace("Source0:        demo.conf",
                             "# spec-lint: generated-source demo.tar.gz\n"
                             "Source0:        demo.tar.gz")
        self.assertEqual(self.codes(text), [])

    def test_source_root(self):
        with tempfile.TemporaryDirectory() as extra:
            (Path(extra) / "demo.conf").write_text("x\n", encoding="utf-8")
            (self.root / "demo.conf").unlink()
            text = f"# spec-lint: source-root {extra}\n" + VALID
            self.assertEqual(self.codes(text), [])

    def test_missing_root(self):
        (self.root / "demo.conf").unlink()
        text = "# spec-lint: source-root nowhere\n" + VALID
        self.assertIn("E010", self.codes(text))

    def test_generated_dup(self):
        text = VALID.replace("Source0:        demo.conf",
                             "# spec-lint: generated-source demo.tar.gz\n"
                             "Source0:        demo.tar.gz\n"
                             "Source1:        demo.tar.gz")
        codes = self.codes(text)
        self.assertEqual(codes.count("E010"), 1)

    def test_changelog(self):
        text = VALID.replace("* Sat Oct 17 2026", "* 2026-10-17")
        self.assertIn("E011", self.codes(text))

    def test_version(self):
        self.osrel.write_text('ID=airymaxos\nVERSION_ID="9.9.9"\n',
                              encoding="utf-8")
        self.assertIn("E012", self.codes())

    def test_placeholder(self):
        self.assertIn("E013", self.codes(VALID + "\n# TODO finish\n"))

    def test_filename(self):
        other = self.spec.with_name("airymaxos-other.spec")
        self.write(VALID, other)
        flat = [item.code for item in spec_lint.lint_spec(other, self.root)]
        self.assertIn("E014", flat)

    def test_comment_macro(self):
        self.assertIn("E015", self.codes(VALID + "\n# 由 %post 完成\n"))

    def test_comment_escaped(self):
        self.assertEqual(self.codes(VALID + "\n# 由 %%post 完成\n"), [])

    def test_real_specs(self):
        root = Path(__file__).resolve().parents[2]
        specs = sorted((root / "specs").rglob("*.spec"))
        self.assertTrue(specs)
        for path in specs:
            self.assertEqual(spec_lint.lint_spec(path, root), [],
                             f"{path.name} violates lint rules")


if __name__ == "__main__":
    unittest.main()
