#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_comps.py — comps_lint 规则回归测试
#
# 每个用例以最小合法 comps 为基线，只做单点变异，断言目标规则号出现；
# kickstart 交叉校验在临时 kickstart/ 目录内构造。标准库 unittest 编写，
# 可被 pytest 直接收集。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import comps_lint

VALID = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE comps PUBLIC "-//Airymax//DTD Comps 1.0//EN" "comps.dtd">
<comps>
  <group>
    <id>airymax-core</id>
    <name>AirymaxOS Base</name>
    <default>true</default>
    <uservisible>false</uservisible>
    <packagelist>
      <packagereq type="mandatory">grub2-tools</packagereq>
      <packagereq type="mandatory">chrony</packagereq>
    </packagelist>
  </group>
  <group>
    <id>airymax-demo</id>
    <name>AirymaxOS Demo</name>
    <default>false</default>
    <uservisible>true</uservisible>
    <packagelist>
      <packagereq type="mandatory">demo</packagereq>
    </packagelist>
  </group>
  <environment>
    <id>airymax-demo-env</id>
    <name>AirymaxOS Demo Environment</name>
    <display_order>99</display_order>
    <grouplist>
      <groupid>airymax-core</groupid>
      <groupid>airymax-demo</groupid>
    </grouplist>
  </environment>
</comps>
"""

DEMO_END = ('      <packagereq type="mandatory">demo</packagereq>\n'
            '    </packagelist>\n  </group>\n')


def demo_refs(*refs):
    """在 demo 组末尾追加 grouplist，作为组引用类规则的单点变异基线。"""
    body = "".join(f"      <groupid>{ref}</groupid>\n" for ref in refs)
    return VALID.replace(
        DEMO_END,
        '      <packagereq type="mandatory">demo</packagereq>\n'
        '    </packagelist>\n    <grouplist>\n' + body +
        '    </grouplist>\n  </group>\n')


class CompsLintTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "kickstart").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def codes(self, text=VALID):
        return [item.code for item in comps_lint.lint_text(text, self.root)]

    def ks(self, text, name="test.ks"):
        (self.root / "kickstart" / name).write_text(text, encoding="utf-8")

    def test_valid(self):
        self.assertEqual(self.codes(), [])

    def test_not_xml(self):
        self.assertIn("C001", self.codes(VALID.replace("</comps>", "")))

    def test_root(self):
        text = VALID.replace("<comps>", "<groups>").replace("</comps>",
                                                            "</groups>")
        text = text.replace("<!DOCTYPE comps", "<!DOCTYPE groups")
        self.assertIn("C001", self.codes(text))

    def test_doctype_missing(self):
        text = VALID.replace('<!DOCTYPE comps PUBLIC "-//Airymax//DTD Comps '
                             '1.0//EN" "comps.dtd">\n', "")
        self.assertIn("C002", self.codes(text))

    def test_doctype_public(self):
        text = VALID.replace("-//Airymax//DTD Comps 1.0//EN",
                             "-//Red Hat, Inc.//DTD Comps info//EN")
        self.assertIn("C002", self.codes(text))

    def test_comment_double_hyphen(self):
        text = VALID.replace("<comps>", "<!-- xmllint --valid -->\n<comps>", 1)
        self.assertIn("C015", self.codes(text))

    def test_group_id(self):
        text = VALID.replace("<id>airymax-demo</id>",
                             "<id>airymax demo</id>", 1)
        self.assertIn("C003", self.codes(text))

    def test_group_dup(self):
        grp = VALID[VALID.index("  <group>"):VALID.index("  </group>") + 10]
        text = VALID.replace("  <environment>", grp + "\n  <environment>")
        self.assertIn("C003", self.codes(text))

    def test_env_dup(self):
        text = VALID.replace("<id>airymax-demo-env</id>",
                             "<id>airymax-demo</id>")
        self.assertIn("C004", self.codes(text))

    def test_group_name(self):
        text = VALID.replace("<name>AirymaxOS Demo</name>\n", "")
        self.assertIn("C005", self.codes(text))

    def test_group_pkgs(self):
        text = VALID.replace(
            "      <packagereq type=\"mandatory\">demo</packagereq>\n", "")
        self.assertIn("C005", self.codes(text))

    def test_pkg_name(self):
        text = VALID.replace(">demo</packagereq>", ">/bad</packagereq>")
        self.assertIn("C006", self.codes(text))

    def test_pkg_dup(self):
        text = VALID.replace(
            "</packagelist>",
            "  <packagereq type=\"optional\">grub2-tools</packagereq>\n"
            "    </packagelist>", 1)
        self.assertIn("C006", self.codes(text))

    def test_pkg_type(self):
        text = VALID.replace('type="mandatory"', 'type="required"')
        self.assertIn("C006", self.codes(text))

    def test_upstream_kernel(self):
        text = VALID.replace(
            "</packagelist>",
            "  <packagereq type=\"mandatory\">kernel-core</packagereq>\n"
            "    </packagelist>", 1)
        self.assertIn("C011", self.codes(text))

    def test_upstream_release(self):
        text = VALID.replace(
            "</packagelist>",
            "  <packagereq type=\"mandatory\">openEuler-release</packagereq>\n"
            "    </packagelist>", 1)
        self.assertIn("C011", self.codes(text))

    def test_env_ref(self):
        text = VALID.replace("<groupid>airymax-demo</groupid>",
                             "<groupid>airymax-gone</groupid>")
        self.assertIn("C007", self.codes(text))

    def test_group_ref(self):
        self.assertIn("C007", self.codes(demo_refs("airymax-gone")))

    def test_group_self_ref(self):
        self.assertIn("C007", self.codes(demo_refs("airymax-demo")))

    def test_group_cycle(self):
        text = demo_refs("airymax-demo-two")
        peer = """\
  <group>
    <id>airymax-demo-two</id>
    <name>AirymaxOS Demo Two</name>
    <packagelist>
      <packagereq type="mandatory">demo2</packagereq>
    </packagelist>
    <grouplist>
      <groupid>airymax-demo</groupid>
    </grouplist>
  </group>
"""
        text = text.replace("  <environment>", peer + "  <environment>")
        self.assertIn("C010", self.codes(text))

    def test_bool(self):
        text = VALID.replace("<uservisible>true</uservisible>",
                             "<uservisible>yes</uservisible>")
        self.assertIn("C008", self.codes(text))

    def test_ks_env_syntax(self):
        self.ks("%packages --nocore\n@airymax-core\n"
                "@airymax-demo-env\n%end\n")
        self.assertEqual(self.codes(), ["C009"])

    def test_ks_undefined(self):
        self.ks("%packages --nocore\n@airymax-core\n"
                "@airymax-missing\n%end\n")
        self.assertEqual(self.codes(), ["C009"])

    def test_ks_ok(self):
        self.ks("%packages --nocore\n@airymax-core\n@^airymax-demo-env\n"
                "@airymax-demo\nkernel\n-xorg*\n%end\n")
        self.assertEqual(self.codes(), [])

    def test_implicit_core(self):
        self.ks("%packages\n@^airymax-demo-env\n%end\n")
        self.assertIn("C012", self.codes())

    def test_nocore_without_base(self):
        self.ks("%packages --nocore\n@^airymax-demo-env\n%end\n")
        self.assertEqual(self.codes(), ["C013"])

    def test_core_needs(self):
        text = VALID.replace(
            '      <packagereq type="mandatory">chrony</packagereq>\n', "")
        self.assertIn("C014", self.codes(text))

    def test_real_comps(self):
        base = Path(__file__).resolve().parents[2]
        targets = sorted((base / "comps").glob("*.xml"))
        self.assertTrue(targets)
        for path in targets:
            self.assertEqual(comps_lint.lint_comps(path, base), [],
                             f"{path.name} violates comps rules")

    def test_real_ukui_nesting(self):
        base = Path(__file__).resolve().parents[2]
        root = ET.parse(base / "comps" / "airymaxos-comps.xml").getroot()
        groups = {grp.findtext("id"): grp for grp in root.findall("group")}
        core = groups["airymax-desktop-core"]
        desktop = groups["airymax-desktop"]
        self.assertIn("airymax-desktop-core",
                      {ref.text for ref in desktop.findall(
                          "grouplist/groupid")})
        self.assertFalse(_packages(core) & _packages(desktop))
        self.assertIn("airymaxos-release", _packages(core))
        envs = {env.findtext("id"): env for env in root.findall("environment")}
        chosen = {ref.text for ref in envs["airymax-workstation"].findall(
            "grouplist/groupid")}
        self.assertTrue({"airymax-core", "airymax-desktop-core",
                         "airymax-desktop"} <= chosen)


def _packages(group):
    return {req.text for req in group.findall("packagelist/packagereq")}


if __name__ == "__main__":
    unittest.main()
