#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_ks_lint.py — ks_lint 规则回归测试
#
# 以最小合法 kickstart 为基线，每次只做单点变异，断言目标规则号出现；
# 末尾追加对仓库内真实 kickstart 的全量校验。标准库 unittest 编写，
# 可被 pytest 直接收集。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ks_lint

VALID = """\
text
lang zh_CN.UTF-8
keyboard us
timezone Asia/Shanghai --utc
url --url=https://example.invalid/os/
bootloader --timeout=3
clearpart --all --initlabel
autopart --type=plain --fstype=ext4
network --bootproto=dhcp --activate
rootpw --iscrypted $6$testsalt$hash
user --name=demo --iscrypted --password=$6$testsalt2$hash
%packages
@core
%end
%post --log=/root/post.log
set -eu
echo done
%end
reboot
"""

ROOT = "rootpw --iscrypted $6$testsalt$hash"
USER = "user --name=demo --iscrypted --password=$6$testsalt2$hash"


class KsLintTest(unittest.TestCase):
    def codes(self, text=VALID):
        return [item.code for item in ks_lint.lint_text(text)]

    def test_valid(self):
        self.assertEqual(self.codes(), [])

    def test_section_unclosed(self):
        pos = VALID.rindex("%end\n")
        text = VALID[:pos] + VALID[pos + len("%end\n"):]
        self.assertIn("K001", self.codes(text))

    def test_stray_end(self):
        self.assertIn("K001", self.codes("%end\n" + VALID))

    def test_unknown_section(self):
        text = VALID.replace("reboot\n", "%weird\nx\n%end\nreboot\n")
        self.assertIn("K001", self.codes(text))

    def test_two_sources(self):
        text = VALID.replace("bootloader", "cdrom\nbootloader")
        self.assertIn("K002", self.codes(text))

    def test_missing_cmd(self):
        text = VALID.replace("keyboard us\n", "")
        self.assertIn("K003", self.codes(text))

    def test_missing_packages(self):
        text = VALID.replace("%packages\n@core\n%end\n", "")
        self.assertIn("K003", self.codes(text))

    def test_storage_conflict(self):
        text = VALID.replace("autopart --type=plain --fstype=ext4",
                             "autopart --type=plain\npart / --size=1024")
        self.assertIn("K004", self.codes(text))

    def test_storage_missing(self):
        text = VALID.replace("clearpart --all --initlabel\n", "")
        text = text.replace("autopart --type=plain --fstype=ext4\n", "")
        self.assertIn("K004", self.codes(text))

    def test_rootpw_plain(self):
        text = VALID.replace(ROOT, "rootpw secret")
        self.assertIn("K005", self.codes(text))

    def test_rootpw_locked(self):
        text = VALID.replace(ROOT, "rootpw --lock")
        self.assertIn("K005", self.codes(text))

    def test_rootpw_not_sha512(self):
        text = VALID.replace(ROOT, "rootpw --iscrypted $1$salt$hash")
        self.assertIn("K005", self.codes(text))

    def test_user_plain(self):
        text = VALID.replace(USER, "user --name=demo")
        self.assertIn("K006", self.codes(text))

    def test_user_locked(self):
        text = VALID.replace(USER, "user --name=demo --lock")
        self.assertIn("K006", self.codes(text))

    def test_user_not_sha512(self):
        text = VALID.replace(USER, "user --name=demo --iscrypted "
                                   "--password=$1$salt$hash")
        self.assertIn("K006", self.codes(text))

    def test_http_url(self):
        text = VALID.replace("https://example.invalid/os/",
                             "http://example.invalid/os/")
        self.assertIn("K007", self.codes(text))

    def test_repo_unnamed(self):
        text = VALID.replace("bootloader",
                             "repo --baseurl=https://example.invalid/u/\n"
                             "bootloader")
        self.assertIn("K007", self.codes(text))

    def test_post_no_strict(self):
        text = VALID.replace("set -eu\n", "")
        self.assertIn("K008", self.codes(text))

    def test_post_no_log(self):
        text = VALID.replace("%post --log=/root/post.log", "%post")
        self.assertIn("K009", self.codes(text))

    def test_no_stop(self):
        text = VALID.replace("reboot\n", "")
        self.assertIn("K010", self.codes(text))

    def test_stop_not_last(self):
        text = VALID.replace("reboot\n", "reboot\nfirstboot\n")
        self.assertIn("K010", self.codes(text))

    def test_duplicate_cmd(self):
        text = VALID.replace("keyboard us\n", "keyboard us\nkeyboard de\n")
        self.assertIn("K011", self.codes(text))

    def test_mode_conflict(self):
        self.assertIn("K012", self.codes("graphical\n" + VALID))

    def test_real_kickstarts(self):
        base = Path(__file__).resolve().parents[2]
        targets = sorted((base / "kickstart").glob("*.ks"))
        self.assertTrue(targets)
        for path in targets:
            self.assertEqual(ks_lint.lint_ks(path), [],
                             f"{path.name} violates kickstart rules")


if __name__ == "__main__":
    unittest.main()
