#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_lockfile.py — lock_check 解析 / 覆盖校验 / 冻结集 diff 回归测试
#
# 夹具按 rpm-lockfile-prototype 的真实输出结构构造： arches 段内的 packages
# 是安装集，source 与 module_metadata 段同形但必须被排除在外。comps 夹具
# 覆盖三类边界： mandatory/default 计入、optional 与 optionlist 组不计入、
# 组嵌套通过 grouplist 递归展开。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "lockfile"))

import lock_check

COMPS = """\
<?xml version="1.0" encoding="UTF-8"?>
<comps>
  <group>
    <id>core</id>
    <packagelist>
      <packagereq type="mandatory">airymaxos-release</packagereq>
      <packagereq type="mandatory">pkg-a</packagereq>
      <packagereq type="default">pkg-b</packagereq>
      <packagereq type="optional">pkg-opt</packagereq>
    </packagelist>
    <grouplist>
      <groupid>base</groupid>
    </grouplist>
  </group>
  <group>
    <id>base</id>
    <packagelist>
      <packagereq type="default">pkg-c</packagereq>
    </packagelist>
  </group>
  <group>
    <id>extra</id>
    <packagelist>
      <packagereq type="mandatory">pkg-x</packagereq>
    </packagelist>
  </group>
  <environment>
    <id>env</id>
    <grouplist>
      <groupid>core</groupid>
    </grouplist>
    <optionlist>
      <groupid>extra</groupid>
    </optionlist>
  </environment>
</comps>
"""

LOCK = """\
---
lockfileVersion: 1
lockfileVendor: redhat
arches:
- arch: x86_64
  packages:
  - url: https://example.invalid/pkg-a-1.0-1.x86_64.rpm
    repoid: os
    size: 10
    checksum: sha256:aa
    name: pkg-a
    evr: 1.0-1
    sourcerpm: pkg-a-1.0-1.src.rpm
  - url: https://example.invalid/pkg-b-2.0-3.x86_64.rpm
    repoid: epol
    size: 20
    checksum: sha256:bb
    name: pkg-b
    evr: 2.0-3
    sourcerpm: pkg-b-2.0-3.src.rpm
  - url: https://example.invalid/pkg-c-3.0-1.x86_64.rpm
    repoid: os
    size: 30
    checksum: sha256:cc
    name: pkg-c
    evr: 3.0-1
    sourcerpm: pkg-c-3.0-1.src.rpm
  source:
  - url: https://example.invalid/src-9.9-9.src.rpm
    repoid: os
    size: 40
    checksum: sha256:dd
    name: src-only
    evr: 9.9-9
  module_metadata: []
"""


class LockCheckTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.comps = self._write("comps.xml", COMPS)
        self.lock = self._write("lock.yaml", LOCK)

    def _write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def _run(self, func, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = func(*args)
        return code, out.getvalue(), err.getvalue()

    def test_packages_skips_source(self):
        self.assertEqual(lock_check.packages(self.lock),
                         {"x86_64": {"pkg-a": "1.0-1", "pkg-b": "2.0-3",
                                     "pkg-c": "3.0-1"}})

    def test_verify_covers_closure(self):
        code, out, _ = self._run(lock_check.verify, self.comps, self.lock, "env")
        self.assertEqual(code, 0)
        self.assertIn("3 个上游必装包", out)

    def test_verify_ignores_local_packages(self):
        # airymaxos-release 由本项目构建，不应要求出现在上游冻结集
        code, _, err = self._run(lock_check.verify, self.comps, self.lock, "env")
        self.assertEqual(code, 0)
        self.assertNotIn("airymaxos-release", err)

    def test_verify_reports_missing(self):
        text = LOCK.replace("name: pkg-c", "name: pkg-z")
        lock = self._write("missing.yaml", text)
        code, _, err = self._run(lock_check.verify, self.comps, lock, "env")
        self.assertEqual(code, 1)
        self.assertIn("pkg-c", err)

    def test_verify_unknown_env(self):
        with self.assertRaises(SystemExit):
            lock_check.verify(self.comps, self.lock, "no-such-env")

    def test_diff_summary(self):
        text = LOCK.replace("evr: 1.0-1", "evr: 1.1-1").replace(
            "name: pkg-b", "name: pkg-z")
        new = self._write("new.yaml", text)
        code, out, _ = self._run(lock_check.diff, self.lock, new)
        self.assertEqual(code, 0)
        self.assertIn("新增 1", out)
        self.assertIn("升级 1", out)
        self.assertIn("移除 1", out)
        self.assertIn("x86_64:pkg-a 1.0-1 -> 1.1-1", out)
        self.assertIn("x86_64:pkg-z - -> 2.0-3", out)
        self.assertIn("x86_64:pkg-b 2.0-3 -> -", out)


if __name__ == "__main__":
    unittest.main()
