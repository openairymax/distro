#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_rtc_sync.py — 装机期 RTC 写入限时与打点的回归测试
#
# 库只定义函数，行为由环境决定；用例用 bash 直接 source install-lib.sh 与
# rtc-sync.sh，AIRY_CONSOLE 指向临时文件。五个注入点（AIRY_RTC_DIR、
# AIRY_RTC_TOOL、AIRY_RTC_LIMIT、AIRY_RTC_TRACE、AIRY_RTC_TRACE_FILE）把
# 「无设备」「无工具」「超时」「写失败」「成功但超限」五条分支都变成可以
# 在任意机器上复现的普通调用，不依赖真实 RTC。
#
# 断言读标准输出：控制台在真机上是字符设备、在测试里是普通文件，每次
# airy_out 都以 `>` 写入（真机上无截断语义），因此只有最后一行留在文件
# 里；完整序列只能从标准输出取。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.1
# ===========================================================================

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
KS = TESTS.parents[1] / "kickstart"
BASH = shutil.which("bash") or "/bin/bash"


class RtcSyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.console = self.dir / "console"
        self.console.write_text("", encoding="utf-8")
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.rtc = self.dir / "rtc0"
        self.rtc.mkdir()
        (self.rtc / "since_epoch").write_text("%d\n" % (int(time.time()) - 10),
                                              encoding="utf-8")
        self.trace = self.dir / "trace"
        self.env = {
            "PATH": "%s:%s" % (self.bin, os.environ.get("PATH", "")),
            "AIRY_CONSOLE": str(self.console),
            "AIRY_RTC_DIR": str(self.rtc),
            "AIRY_RTC_TRACE": "0",
            "AIRY_RTC_TRACE_FILE": str(self.trace),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)

    def sh(self, snippet, **extra):
        env = dict(self.env)
        env.update({key: str(val) for key, val in extra.items()})
        script = ('set -eu\n. "%s"\n. "%s"\n' %
                  (KS / "install-lib.sh", KS / "rtc-sync.sh")) + snippet
        return subprocess.run([BASH, "-c", script], env=env, text=True,
                              capture_output=True)

    def test_fast_write_reports_ok_and_drift(self):
        self.tool("hwclock", "exit 0")
        res = self.sh('airy_rtc_sync; printf "RC=%s\\n" "$?"')
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.splitlines()
        self.assertIn("RC=0", out)
        self.assertTrue(out[0].startswith("AIRYMAX-RTC-BEGIN t="), out)
        self.assertRegex(out[1], r"^AIRYMAX-RTC-END ms=\d+$")
        self.assertRegex(out[2], r"^AIRYMAX-RTC-OK ms=\d+$")
        self.assertRegex(out[3], r"^AIRYMAX-RTC-DRIFT sec=-?1[0-2]$")

    def test_timeout_only_warns(self):
        self.tool("hwclock", "sleep 5")
        res = self.sh('airy_rtc_sync; printf "RC=%s\\n" "$?"',
                      AIRY_RTC_LIMIT=1)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.splitlines()
        self.assertIn("RC=0", out)
        slow = [ln for ln in out if "AIRYMAX-RTC-SLOW" in ln]
        self.assertEqual(len(slow), 1, out)
        self.assertIn("reason=timeout", slow[0])
        self.assertIn("limit=1000", slow[0])

    def test_over_limit_after_success_is_slow(self):
        # limit=0 让 timeout 不限时（GNU 语义），写入成功但耗时必然大于
        # 0 ms，正是「写完却慢」这条分支。
        self.tool("hwclock", "sleep 2")
        res = self.sh('airy_rtc_sync; printf "RC=%s\\n" "$?"',
                      AIRY_RTC_LIMIT=0)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.splitlines()
        slow = [ln for ln in out if "AIRYMAX-RTC-SLOW" in ln]
        self.assertEqual(len(slow), 1, out)
        self.assertNotIn("reason=", slow[0])
        self.assertIn("limit=0", slow[0])

    def test_write_failure_is_skip_with_rc(self):
        self.tool("hwclock", "exit 3")
        res = self.sh('airy_rtc_sync; printf "RC=%s\\n" "$?"')
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.splitlines()
        self.assertIn("AIRYMAX-RTC-SKIP reason=write-failed rc=3", out)
        self.assertFalse([ln for ln in out if "TRACE" in ln], out)

    def test_missing_device_is_skip(self):
        res = self.sh('airy_rtc_sync; printf "RC=%s\\n" "$?"',
                      AIRY_RTC_DIR=self.dir / "none")
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.splitlines()
        self.assertEqual(out[1:4], [
            "AIRYMAX-RTC-END ms=0",
            "AIRYMAX-RTC-SKIP reason=no-device",
            "RC=0",
        ])

    def test_missing_tool_is_skip(self):
        res = self.sh('airy_rtc_sync; printf "RC=%s\\n" "$?"',
                      AIRY_RTC_TOOL="no-such-clock-tool")
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.splitlines()
        self.assertEqual(out[1:4], [
            "AIRYMAX-RTC-END ms=0",
            "AIRYMAX-RTC-SKIP reason=no-tool",
            "RC=0",
        ])

    def test_trace_keeps_three_slowest(self):
        self.trace.write_text(
            "clock_settime(CLOCK_REALTIME, {...}) = 0 <0.000011>\n"
            "ioctl(3, RTC_SET_TIME, {...}) = 0 <0.420000>\n"
            "settimeofday([...], NULL) = 0 <0.130000>\n"
            "ioctl(3, RTC_EPOCH_READ, 0x7f) = 8 <1.500000>\n"
            "nanosleep({0, 1000}, NULL) = 0 <0.000900>\n",
            encoding="utf-8")
        res = self.sh('airy_rtc_trace "$AIRY_RTC_TRACE_FILE"')
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.splitlines(), [
            "AIRYMAX-RTC-TRACE call=ioctl ms=1500",
            "AIRYMAX-RTC-TRACE call=ioctl ms=420",
            "AIRYMAX-RTC-TRACE call=settimeofday ms=130",
        ])

    def test_trace_absent_file_is_quiet(self):
        res = self.sh('airy_rtc_trace "$AIRY_RTC_TRACE_FILE"; '
                      'printf "RC=%s\\n" "$?"')
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "RC=0\n")


if __name__ == "__main__":
    sys.exit(unittest.main())
