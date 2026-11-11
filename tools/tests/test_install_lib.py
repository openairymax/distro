#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_install_lib.py — 安装期打印与失败标记共享库的回归测试
#
# 库以 source 方式被 kickstart 嵌入，行为完全由环境与调用顺序决定；用例
# 用 bash 直接 source，AIRY_CONSOLE 指向临时文件，避免触碰真实 /dev。
# 覆盖阶段行格式与 AIRY_STEP、失败行的 family/reason/step/note 与退出码，
# 以及 EXIT 陷阱在 set -e 中止时补发 rc 失败行。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "kickstart" / "install-lib.sh"
BASH = shutil.which("bash") or "/bin/bash"


class InstallLibTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.console = self.dir / "console"
        self.console.write_text("", encoding="utf-8")
        self.env = {"PATH": os.environ.get("PATH", ""),
                    "AIRY_CONSOLE": str(self.console)}

    def tearDown(self):
        self._tmp.cleanup()

    def sh(self, snippet, **extra):
        env = dict(self.env)
        env.update({key: str(val) for key, val in extra.items()})
        return subprocess.run([BASH, "-c", 'set -eu\n. "$1"\n' + snippet,
                               "bash", str(LIB)], env=env, text=True,
                              capture_output=True)

    def console_lines(self):
        return self.console.read_text(encoding="utf-8").splitlines()

    def test_out_writes_stdout_and_console(self):
        res = self.sh('airy_out "hello"')
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "hello\n")
        self.assertEqual(self.console_lines(), ["hello"])

    def test_step_prints_and_records(self):
        res = self.sh('airy_step 3 7 disk\nprintf "STEP=%s\\n" "${AIRY_STEP}"')
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("AIRYMAX-INSTALL-STEP 3/7 disk", res.stdout)
        self.assertIn("STEP=3/7 disk", res.stdout)
        self.assertEqual(self.console_lines(),
                         ["AIRYMAX-INSTALL-STEP 3/7 disk"])

    def test_fail_reports_step_and_note(self):
        res = self.sh('airy_step 2 7 system\n'
                      'airy_fail DISK too-small "bytes=1"')
        self.assertEqual(res.returncode, 1)
        line = "AIRYMAX-DISK-FAIL reason=too-small step=2/7 system"
        self.assertIn(line + " note=bytes=1", res.stdout)
        self.assertEqual(self.console_lines(), [line + " note=bytes=1"])

    def test_fail_without_step_is_unknown(self):
        res = self.sh('airy_fail INSTALL release-pkg')
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-INSTALL-FAIL reason=release-pkg "
                      "step=unknown", res.stdout)
        self.assertNotIn("note=", res.stdout)

    def test_trap_reports_rc(self):
        res = self.sh('airy_trap INSTALL\nfalse')
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-INSTALL-FAIL reason=rc step=unknown "
                      "note=rc=1", res.stdout)

    def test_trap_silent_on_success(self):
        res = self.sh('airy_trap INSTALL\ntrue')
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("FAIL", res.stdout)

    def test_out_survives_unwritable_console(self):
        res = self.sh('set +e\nairy_out hi\nprintf "rc=%s\\n" "$?"',
                      AIRY_CONSOLE=str(self.dir))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "hi\nrc=0\n")


if __name__ == "__main__":
    sys.exit(unittest.main())
