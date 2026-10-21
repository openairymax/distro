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
import ks_spec

VALID = """\
text
lang zh_CN.UTF-8
keyboard us
timezone Asia/Shanghai --utc
url --url=https://example.invalid/os/
repo --name=airymaxos-offline --baseurl=file:///run/install/repo/airymax/Packages
bootloader --timeout=3
clearpart --all --initlabel
autopart --type=plain --fstype=ext4
network --bootproto=dhcp --activate
rootpw --iscrypted $6$testsalt$hash
user --name=demo --iscrypted --password=$6$testsalt2$hash
%packages
@airymax-core
airymaxos-kernel
-kernel
-kernel-tools
-openEuler-release
-openEuler-latest-release
%end
%post --log=/root/post.log
set -eu
echo done
%end
reboot
"""

ROOT = "rootpw --iscrypted $6$testsalt$hash"
USER = "user --name=demo --iscrypted --password=$6$testsalt2$hash"

# 桌面环境基线：四个上游仓库齐全且 URL 带 $basearch，离线仓库沿用基线
DESKTOP = (VALID
           .replace("https://example.invalid/os/",
                    "https://example.invalid/os/$basearch/")
           .replace("@airymax-core", "@^airymax-workstation")
           .replace("bootloader",
                    "repo --name=update --baseurl=https://example.invalid/u/"
                    "$basearch/\n"
                    "repo --name=epol --baseurl=https://example.invalid/e/"
                    "$basearch/\n"
                    "repo --name=epol-update --baseurl=https://example.invalid"
                    "/eu/$basearch/\n"
                    "repo --name=everything --baseurl=https://example.invalid"
                    "/x/$basearch/\n"
                    "bootloader"))


# 安装期姿态基线：安装源即载荷，桌面环境不再要求四个上游仓库
OFFLINE = (VALID
           .replace("@airymax-core", "@^airymax-workstation")
           .replace("url --url=https://example.invalid/os/",
                    "url --url=file:///run/install/repo/airymax/Packages"))


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
        pos = VALID.index("%packages")
        end = VALID.index("%end\n", pos) + len("%end\n")
        self.assertIn("K003", self.codes(VALID[:pos] + VALID[end:]))

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

    def test_stock_kernel(self):
        text = VALID.replace("airymaxos-kernel", "kernel")
        self.assertIn("K014", self.codes(text))

    def test_stock_kernel_subpkg(self):
        text = VALID.replace("airymaxos-kernel", "airymaxos-kernel\n"
                                                "kernel-core")
        self.assertIn("K014", self.codes(text))

    def test_kernel_missing(self):
        text = VALID.replace("airymaxos-kernel\n", "")
        self.assertIn("K014", self.codes(text))

    def test_exclude_kernel_missing(self):
        text = VALID.replace("-kernel\n", "")
        self.assertIn("K017", self.codes(text))

    def test_exclude_release_missing(self):
        text = VALID.replace("-openEuler-release\n", "")
        self.assertIn("K017", self.codes(text))

    def test_vendor_missing(self):
        text = VALID.replace(
            "repo --name=airymaxos-offline --baseurl=file:///run/install/"
            "repo/airymax/Packages\n", "")
        self.assertIn("K015", self.codes(text))

    def test_vendor_bad_url(self):
        text = VALID.replace("file:///run/install/repo/airymax/Packages",
                             "file:///mnt/payload")
        self.assertIn("K015", self.codes(text))

    def test_desktop_repos(self):
        self.assertEqual(self.codes(DESKTOP), [])

    def test_desktop_repo_missing(self):
        text = DESKTOP.replace(
            "repo --name=everything --baseurl=https://example.invalid"
            "/x/$basearch/\n", "")
        self.assertIn("K013", self.codes(text))

    def test_desktop_repo_no_arch(self):
        text = DESKTOP.replace("https://example.invalid/e/$basearch/",
                               "https://example.invalid/e/")
        self.assertIn("K013", self.codes(text))

    def test_desktop_src_no_arch(self):
        text = DESKTOP.replace("https://example.invalid/os/$basearch/",
                               "https://example.invalid/os/")
        self.assertIn("K013", self.codes(text))

    def test_services_list(self):
        text = VALID.replace("reboot\n", "services --enabled=a b\nreboot\n")
        self.assertIn("K016", self.codes(text))

    def test_user_option(self):
        text = VALID.replace(USER, USER + ' --comment="demo"')
        self.assertIn("K016", self.codes(text))

    def test_valid_services_list(self):
        text = VALID.replace("reboot\n", "services --enabled=a,b\nreboot\n")
        self.assertEqual(self.codes(text), [])

    def test_offline_pose(self):
        self.assertEqual(self.codes(OFFLINE), [])

    def test_offline_extra_repo(self):
        text = OFFLINE.replace(
            "bootloader",
            "repo --name=update --baseurl=https://example.invalid/u/"
            "$basearch/\nbootloader")
        self.assertIn("K015", self.codes(text))

    def test_offline_src_mismatch(self):
        text = OFFLINE.replace(
            "url --url=file:///run/install/repo/airymax/Packages",
            "url --url=file:///mnt/payload")
        self.assertIn("K015", self.codes(text))

    def test_install_pose(self):
        base = Path(__file__).resolve().parents[2]
        for path in sorted((base / "kickstart").glob("*.ks")):
            text = ks_spec.project(path.read_text(encoding="utf-8"))
            self.assertEqual(ks_lint.lint_text(text), [],
                             f"{path.name} install pose violates rules")

    def test_real_kickstarts(self):
        base = Path(__file__).resolve().parents[2]
        targets = sorted((base / "kickstart").glob("*.ks"))
        self.assertTrue(targets)
        for path in targets:
            self.assertEqual(ks_lint.lint_ks(path), [],
                             f"{path.name} violates kickstart rules")


if __name__ == "__main__":
    unittest.main()
