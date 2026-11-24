#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# test_system_pkg.py — 系统包交付完整性
#
# 配方把源码树里的命令、单元与 Python 包逐个搬到构建根，漏一条不会在
# 打包期报错：RPM 只校验「装了什么」，不校验「源码树下还有什么」。缺口
# 因此一路走到装机，表现是 %post 启用单元时 not-found，或者命令 203/EXEC。
#
# 判据取源码树事实：bin 下每个可执行文件、units 下每个单元、ops 与
# services/daemons 下每个带 __init__.py 的包，都必须出现在配方的安装清单
# 里。目标目录写成「以 / 结尾」时沿用源文件名，写成完整路径时按目标名。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.5
# ===========================================================================

import re
import unittest
from pathlib import Path

DISTRO = Path(__file__).resolve().parents[2]
ROOT = DISTRO.parent
SPEC = DISTRO / "specs" / "airymaxos-system.spec"
UNIT_SUFFIX = (".service", ".timer", ".target", ".slice", ".socket", ".path")
MACROS = ("%{_bindir}", "%{_unitdir}", "%{_tmpfilesdir}")
SRC_REF = re.compile(r"%\{SOURCE(\d+)\}")


def spec_text():
    return SPEC.read_text(encoding="utf-8")


def sources(text):
    return dict(re.findall(r"(?m)^Source(\d+):\s*(\S+)\s*$", text))


def section(text, head, tail):
    return text.split(head, 1)[1].split(tail, 1)[0]


def install_rows(text):
    """（安装目录, 安装名）对：按 install 指令的每个源文件展开。"""
    srcs = sources(text)
    body = section(text, "%install", "%files").replace("\\\n", " ")
    rows = []
    for line in body.splitlines():
        words = line.split()
        if len(words) < 2 or words[0] != "install":
            continue
        dest = words[-1].replace("%{buildroot}", "")
        for word in words[1:-1]:
            for num in SRC_REF.findall(word):
                name = Path(srcs.get(num, "")).name
                if not name:
                    continue
                head, _, tail = dest.rpartition("/")
                rows.append((head, tail or name))
    return rows


def installed(text, macro):
    return {name for head, name in install_rows(text) if head == macro}


def files_entries(text):
    return set(section(text, "%files", "%changelog").split())


class SystemPkgTest(unittest.TestCase):
    def setUp(self):
        self.text = spec_text()

    def test_bins_shipped(self):
        have = installed(self.text, "%{_bindir}")
        miss = sorted(p.name for p in (ROOT / "system/bin").iterdir()
                      if p.is_file() and p.stat().st_mode & 0o111
                      and p.name not in have)
        self.assertEqual(miss, [])

    def test_units_shipped(self):
        have = installed(self.text, "%{_unitdir}")
        miss = sorted(p.name for p in (ROOT / "system/units").iterdir()
                      if p.is_file() and p.name.endswith(UNIT_SUFFIX)
                      and p.name not in have)
        self.assertEqual(miss, [])

    def test_py_packages_shipped(self):
        entries = files_entries(self.text)
        miss = []
        for base in (ROOT / "system/ops", ROOT / "system/services/daemons"):
            for pkg in sorted(base.iterdir()):
                if not (pkg / "__init__.py").is_file():
                    continue
                if f"%{{python3_sitelib}}/{pkg.name}" not in entries:
                    miss.append(pkg.name)
        self.assertEqual(miss, [])

    def test_files_covers_installed(self):
        entries = files_entries(self.text)
        miss = []
        for macro in ("%{_bindir}", "%{_tmpfilesdir}"):
            for name in sorted(installed(self.text, macro)):
                if f"{macro}/{name}" not in entries:
                    miss.append(f"{macro}/{name}")
        self.assertEqual(miss, [])


if __name__ == "__main__":
    unittest.main()
