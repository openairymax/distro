#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_grub_args.py — 启动参数持久来源（grub_args.sh）行为回归
#
# 脚本要在安装末期把启动画面参数写进 /etc/default/grub 并关闭 os-prober，
# 因为 kickstart 的 bootloader --append 只进安装器生成的那一份 grub.cfg。
# --no-regen 只改写输入文件，不碰块设备，因此可在临时目录里判定；每个用例
# 只破坏一个前提，覆盖三种失败：参数缺失、探测开关未关、文件不可读。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
SCRIPT = BASE / "boot" / "grub_args.sh"
SH = shutil.which("sh") or "/bin/sh"

# 安装器生成的形态：参数行带 console，os-prober 以注释形式给出。
STOCK = """\
GRUB_TIMEOUT=3
GRUB_DEFAULT=saved
GRUB_TERMINAL_OUTPUT="console"
GRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200"
#GRUB_DISABLE_OS_PROBER=true
GRUB_DISABLE_RECOVERY="true"
"""


class GrubArgsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.defaults = self.root / "grub"
        self.state = self.root / "state" / "grub-args"

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, body=STOCK):
        self.defaults.write_text(body, encoding="utf-8")
        return self.defaults

    def run_args(self, *args):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        return subprocess.run([SH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def apply(self, *extra, body=None):
        self.write(body or STOCK)
        return self.run_args("--defaults", str(self.defaults),
                             "--state", str(self.state),
                             "--no-regen", *extra)

    def check(self):
        return self.run_args("--defaults", str(self.defaults),
                             "--state", str(self.state), "--check")

    def text(self):
        return self.defaults.read_text(encoding="utf-8")

    def cmdline(self):
        for line in self.text().splitlines():
            if line.startswith("GRUB_CMDLINE_LINUX="):
                return line.split("=", 1)[1].strip('"')
        self.fail("GRUB_CMDLINE_LINUX absent")

    def prober(self):
        values = [line.split("=", 1)[1] for line in self.text().splitlines()
                  if line.startswith("GRUB_DISABLE_OS_PROBER=")]
        self.assertEqual(len(values), 1, self.text())
        return values[0]

    def test_syntax_is_posix(self):
        res = subprocess.run([SH, "-n", str(SCRIPT)], text=True,
                             capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_args_appended(self):
        res = self.apply()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.cmdline(),
                         "console=tty0 console=ttyS0,115200 rhgb quiet")
        self.assertEqual(self.prober(), "true")
        self.assertIn("updated:", res.stdout)

    def test_other_lines_kept(self):
        self.apply()
        lines = self.text().splitlines()
        self.assertEqual(lines[0], "GRUB_TIMEOUT=3")
        self.assertEqual(lines[1], "GRUB_DEFAULT=saved")
        self.assertEqual(lines[2], 'GRUB_TERMINAL_OUTPUT="console"')
        self.assertEqual(lines[-1], 'GRUB_DISABLE_RECOVERY="true"')

    def test_idempotent(self):
        self.apply()
        first = self.text()
        res = self.apply(body=first)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("unchanged:", res.stdout)
        self.assertEqual(self.text(), first)

    def test_unquoted_normalized(self):
        # 手改过的文件可能没有引号；生成器读不出这种行，必须归一化
        self.apply(body='GRUB_TIMEOUT=3\nGRUB_CMDLINE_LINUX=console=tty0\n')
        self.assertEqual(self.cmdline(), "console=tty0 rhgb quiet")
        self.assertNotIn("GRUB_CMDLINE_LINUX=console", self.text())

    def test_commented_prober_replaced(self):
        # 注释行若不替换而是另起一行，配置里就出现两条同名赋值，后者生效
        self.apply()
        self.assertNotIn("#GRUB_DISABLE_OS_PROBER", self.text())
        self.assertEqual(self.prober(), "true")

    def test_prober_appended_when_absent(self):
        body = STOCK.replace("#GRUB_DISABLE_OS_PROBER=true\n", "")
        self.apply(body=body)
        self.assertEqual(self.prober(), "true")

    def test_cmdline_appended_when_absent(self):
        body = STOCK.replace(
            'GRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200"\n', "")
        self.apply(body=body)
        self.assertEqual(self.cmdline(), "rhgb quiet")

    def test_custom_append(self):
        self.apply("--append", "console=ttyAMA0,115200")
        self.assertEqual(self.cmdline(), "console=tty0 console=ttyS0,115200 "
                                         "console=ttyAMA0,115200")
        self.assertEqual(self.prober(), "true")

    def test_no_state_without_regen(self):
        # --no-regen 只判定改写；状态文件是安装期落地的凭证，不能由它伪造
        self.apply()
        self.assertFalse(self.state.exists())

    def test_check_converged(self):
        self.apply()
        res = self.check()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("ok:", res.stdout)

    def test_check_missing_tokens(self):
        self.write()
        res = self.check()
        self.assertEqual(res.returncode, 1)
        self.assertIn("missing: rhgb", res.stdout)
        self.assertIn("missing: quiet", res.stdout)

    def test_check_prober_off(self):
        body = STOCK.replace("#GRUB_DISABLE_OS_PROBER=true",
                             "GRUB_DISABLE_OS_PROBER=false")
        body = body.replace('GRUB_CMDLINE_LINUX="console=tty0 '
                            'console=ttyS0,115200"',
                            'GRUB_CMDLINE_LINUX="console=tty0 rhgb quiet"')
        self.write(body)
        res = self.check()
        self.assertEqual(res.returncode, 1)
        self.assertIn("GRUB_DISABLE_OS_PROBER is not true", res.stdout)

    def test_defaults_absent(self):
        res = self.run_args("--defaults", str(self.defaults),
                            "--state", str(self.state), "--no-regen")
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail: no", res.stdout)

    def test_bad_option(self):
        res = self.run_args("--regen")
        self.assertEqual(res.returncode, 2)
        self.assertIn("usage:", res.stderr)


if __name__ == "__main__":
    unittest.main()
