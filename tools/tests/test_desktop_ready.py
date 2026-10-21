#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_desktop_ready.py — 桌面登录链就绪探针契约回归测试
#
# 探针的职责是把「桌面能进」转换成宿主机可判定的串口标记与退出码。
# 用伪 loginctl/systemctl 精确控制 lightdm 单元状态、会话类别与状态，
# 每个用例只破坏一个前提，验证成功标记、失败标记与有界轮询。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import configparser
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import fakes

BASE = Path(__file__).resolve().parents[2]
SCRIPT = BASE / "desktop" / "desktop_ready.sh"
UNIT = BASE / "desktop" / "airymax-desktop-ready.service"
BASH = shutil.which("bash") or "/bin/bash"
READY = "AIRYMAX-DESKTOP-READY"
FAIL = "AIRYMAX-DESKTOP-FAIL"
DIAG = "AIRYMAX-DESKTOP-DIAG"
SESSION = """\
[Desktop Entry]
Name=UKUI
Comment=UKUI session
Exec=ukui-session
Type=Application
"""


class DesktopReadyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.xs = self.root / "xsessions"
        self.logs = self.root / "lightdm"
        self.bin.mkdir()
        self.xs.mkdir()
        self.logs.mkdir()
        fakes.link_tools(self.bin)
        fakes.write(self.bin, "loginctl", fakes.LOGINCTL)
        fakes.write(self.bin, "systemctl", fakes.SYSTEMCTL)
        fakes.write(self.bin, "journalctl", fakes.JOURNALCTL)
        fakes.write(self.bin, "ukui-session", "#!/bin/sh\nexit 0\n")
        self.write_session(SESSION)

    def tearDown(self):
        self._tmp.cleanup()

    def write_session(self, body):
        (self.xs / "ukui.desktop").write_text(body, encoding="utf-8")

    def run_probe(self, *args, **extra):
        env = {"PATH": str(self.bin), "HOME": str(self.root),
               "AIRYMAX_READY_WAIT": "0", "AIRYMAX_READY_POLL": "1",
               "AIRYMAX_XSESSIONS_DIR": str(self.xs),
               "AIRYMAX_LIGHTDM_LOG": str(self.logs)}
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def test_ready(self):
        res = self.run_probe()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("AIRYMAX-BOOT-HEALTH failed=0", res.stdout)
        self.assertIn(
            f"{READY} unit=lightdm class=greeter type=x11", res.stdout)
        self.assertNotIn(FAIL, res.stdout)

    def test_degraded_units(self):
        res = self.run_probe(FAKE_FAILED_UNITS="sssd.service upower.service")
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-BOOT-DEGRADED failed=2 "
                      "units=sssd.service,upower.service", res.stdout)
        self.assertNotIn(READY, res.stdout)

    def test_online_session_is_ready(self):
        res = self.run_probe(FAKE_STATE="online")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(READY, res.stdout)

    def test_lightdm_inactive(self):
        res = self.run_probe(FAKE_LIGHTDM="inactive")
        self.assertEqual(res.returncode, 1)
        self.assertIn(FAIL, res.stdout)
        self.assertNotIn(READY, res.stdout)

    def test_no_session(self):
        res = self.run_probe(FAKE_SESSIONS_ON="0")
        self.assertEqual(res.returncode, 1)
        self.assertIn(FAIL, res.stdout)

    def test_not_greeter(self):
        res = self.run_probe(FAKE_CLASS="user")
        self.assertEqual(res.returncode, 1)
        self.assertIn(FAIL, res.stdout)

    def test_not_x11(self):
        res = self.run_probe(FAKE_TYPE="tty")
        self.assertEqual(res.returncode, 1)
        self.assertIn(FAIL, res.stdout)

    def test_closing_session(self):
        res = self.run_probe(FAKE_STATE="closing")
        self.assertEqual(res.returncode, 1)
        self.assertIn(FAIL, res.stdout)

    def test_session_missing(self):
        (self.xs / "ukui.desktop").unlink()
        res = self.run_probe()
        self.assertEqual(res.returncode, 1)
        self.assertIn("reason=session", res.stdout)
        self.assertNotIn(READY, res.stdout)

    def test_session_without_exec(self):
        self.write_session("[Desktop Entry]\nName=UKUI\nType=Application\n")
        res = self.run_probe()
        self.assertEqual(res.returncode, 1)
        self.assertIn("reason=session", res.stdout)

    def test_session_exec_unresolved(self):
        self.write_session("[Desktop Entry]\nExec=ukui-session-missing\n")
        res = self.run_probe()
        self.assertEqual(res.returncode, 1)
        self.assertIn("reason=session", res.stdout)

    def test_session_exec_missing_file(self):
        self.write_session("[Desktop Entry]\nExec=/nonexistent/ukui-session\n")
        res = self.run_probe()
        self.assertEqual(res.returncode, 1)
        self.assertIn("reason=session", res.stdout)

    def test_session_fails_before_wait(self):
        (self.xs / "ukui.desktop").unlink()
        started = time.monotonic()
        res = self.run_probe(AIRYMAX_READY_WAIT="30")
        elapsed = time.monotonic() - started
        self.assertEqual(res.returncode, 1)
        self.assertLess(elapsed, 10)

    def test_wait_is_bounded(self):
        started = time.monotonic()
        res = self.run_probe(AIRYMAX_READY_WAIT="2",
                             FAKE_LIGHTDM="inactive")
        elapsed = time.monotonic() - started
        self.assertEqual(res.returncode, 1)
        self.assertLess(elapsed, 10)
        self.assertIn("wait=2s", res.stdout)

    def test_fail_reports_unit(self):
        res = self.run_probe(FAKE_LIGHTDM="inactive",
                             FAKE_ACTIVE_STATE="activating",
                             FAKE_SUB_STATE="start",
                             FAKE_RESULT="timeout")
        self.assertEqual(res.returncode, 1)
        self.assertIn(f"{DIAG} unit ActiveState=activating", res.stdout)
        self.assertIn(f"{DIAG} unit SubState=start", res.stdout)
        self.assertIn(f"{DIAG} unit Result=timeout", res.stdout)
        last = res.stdout.rstrip().splitlines()[-1]
        self.assertTrue(last.startswith(FAIL))

    def test_fail_reports_logs(self):
        (self.logs / "lightdm.log").write_text("seat0: waiting\n",
                                               encoding="utf-8")
        (self.logs / "seat0-greeter.log").write_text("greeter: no display\n",
                                                     encoding="utf-8")
        (self.logs / "x-0.log").write_text("Xorg: no screens found\n",
                                           encoding="utf-8")
        res = self.run_probe(FAKE_LIGHTDM="inactive")
        self.assertEqual(res.returncode, 1)
        self.assertIn(f"{DIAG} file=lightdm seat0: waiting", res.stdout)
        self.assertIn(f"{DIAG} file=greeter greeter: no display", res.stdout)
        self.assertIn(f"{DIAG} file=xorg Xorg: no screens found", res.stdout)

    def test_fail_reports_sessions(self):
        res = self.run_probe(FAKE_LIGHTDM="inactive", FAKE_TYPE="tty")
        self.assertEqual(res.returncode, 1)
        self.assertIn(f"{DIAG} session session=1 lightdm|greeter|tty|active",
                      res.stdout)

    def test_diag_is_bounded(self):
        body = "".join(f"line{i}\n" for i in range(100))
        (self.logs / "lightdm.log").write_text(body, encoding="utf-8")
        res = self.run_probe(FAKE_LIGHTDM="inactive", AIRYMAX_DIAG_LINES="3")
        self.assertEqual(res.returncode, 1)
        files = [ln for ln in res.stdout.splitlines()
                 if ln.startswith(f"{DIAG} file=lightdm")]
        self.assertEqual(len(files), 3)

    def test_session_fail_reports_diag(self):
        (self.xs / "ukui.desktop").unlink()
        res = self.run_probe()
        self.assertEqual(res.returncode, 1)
        self.assertIn(f"{DIAG} unit", res.stdout)
        self.assertIn("reason=session", res.stdout)

    def test_ready_has_no_diag(self):
        res = self.run_probe()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn(DIAG, res.stdout)

    def test_unit_contract(self):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        parser.read_string(UNIT.read_text(encoding="utf-8"))
        unit = parser["Unit"]
        service = parser["Service"]
        install = parser["Install"]
        self.assertEqual(unit["After"], "lightdm.service")
        self.assertEqual(unit["Wants"], "lightdm.service")
        self.assertEqual(unit["ConditionFileIsExecutable"], "/usr/sbin/lightdm")
        self.assertEqual(service["Type"], "oneshot")
        self.assertEqual(service["ExecStart"],
                         "/usr/lib/airymaxos/desktop/desktop_ready.sh")
        self.assertEqual(service["StandardOutput"], "journal+console")
        self.assertEqual(service["TimeoutStartSec"], "180")
        self.assertEqual(install["WantedBy"], "graphical.target")
        self.assertNotIn("User", service)


if __name__ == "__main__":
    unittest.main()
