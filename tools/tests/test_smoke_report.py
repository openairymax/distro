#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_smoke_report.py — ci/fixture/airymax-smoke-report.sh 契约回归测试
#
# 该脚本是验收 ISO 唯一的串口判定者：产品就绪单元在验收安装中被 mask，
# 因此 TAP 结论与关键链转发都只在这里发生。脚本运行于已登录的图形会话，
# CI 宿主机没有该环境；这里用 PATH 沙箱提供伪 systemd-analyze，用 TAP
# 文件与环境变量控制输入，逐项验证「先转发、后结论」的顺序、前缀原文
# 不改写、以及四种结论路径的退出码。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import fakes

SCRIPT = (Path(__file__).resolve().parents[2] / "ci" / "fixture" /
          "airymax-smoke-report.sh")
BASH = shutil.which("bash") or "/bin/bash"

PLAN = "TAP version 14\n1..5\n"
GOOD = PLAN + "".join(f"ok {n} - probe {n}\n" for n in range(1, 6))
PASS = GOOD + "# summary: pass=5 fail=0\n"
CHAIN = ("graphical.target @7.178s\n"
         "└─multi-user.target @7.178s\n"
         "  └─lightdm.service @6.976s +201ms\n")


class SmokeReportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.tap = self.root / "smoke.tap"
        self.chain = self.root / "chain.txt"
        fakes.link_tools(self.bin)
        fakes.report_tools(self.bin)

    def tearDown(self):
        self._tmp.cleanup()

    def report(self, tap=PASS, chain=CHAIN, **extra):
        if tap is not None:
            self.tap.write_text(tap, encoding="utf-8")
        if chain is not None:
            self.chain.write_text(chain, encoding="utf-8")
        env = {
            "PATH": str(self.bin),
            "AIRYMAX_SMOKE_TAP": str(self.tap),
            "AIRYMAX_SMOKE_WAIT": "0",
            "FAKE_CHAIN_FILE": str(self.chain),
        }
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT)], env=env, text=True,
                              capture_output=True)

    def lines(self, res, token):
        return [line for line in res.stdout.splitlines()
                if line.startswith(token)]

    def verdict_at(self, res, marker):
        for index, line in enumerate(res.stdout.splitlines()):
            if line.startswith(marker):
                return index
        self.fail(f"no {marker} in output")

    def test_pass(self):
        res = self.report()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.lines(res, "AIRYMAX-SMOKE-PASS"),
                         [f"AIRYMAX-SMOKE-PASS tap={self.tap}"])

    def test_tap_forwarded_verbatim(self):
        res = self.report()
        self.assertEqual(self.lines(res, "AIRYMAX-TAP|"),
                         [f"AIRYMAX-TAP|{line}"
                          for line in PASS.splitlines()])

    def test_chain_forwarded_verbatim(self):
        res = self.report()
        self.assertEqual(self.lines(res, "AIRYMAX-BOOT-CHAIN|"),
                         [f"AIRYMAX-BOOT-CHAIN|{line}"
                          for line in CHAIN.splitlines()])

    def test_chain_precedes_verdict(self):
        res = self.report()
        out = res.stdout.splitlines()
        marker = self.verdict_at(res, "AIRYMAX-SMOKE-PASS")
        for token in ("AIRYMAX-TAP|", "AIRYMAX-BOOT-CHAIN|"):
            last = max(index for index, line in enumerate(out)
                       if line.startswith(token))
            self.assertLess(last, marker)

    def test_chain_bounded(self):
        res = self.report(chain="".join(f"unit-{n}.service @1s\n"
                                        for n in range(40)))
        self.assertEqual(len(self.lines(res, "AIRYMAX-BOOT-CHAIN|")), 24)

    def test_chain_absent_is_not_fatal(self):
        res = self.report(chain=None)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.lines(res, "AIRYMAX-BOOT-CHAIN|"), [])

    def test_fail_keeps_chain(self):
        res = self.report(tap=GOOD + "not ok 3 - probe 3\n"
                          "# summary: pass=4 fail=1\n")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.lines(res, "AIRYMAX-SMOKE-FAIL"),
                         [f"AIRYMAX-SMOKE-FAIL reason=tap tap={self.tap}"])
        self.assertEqual(len(self.lines(res, "AIRYMAX-BOOT-CHAIN|")), 3)

    def test_timeout(self):
        res = self.report(tap=None)
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.lines(res, "AIRYMAX-SMOKE-FAIL"),
                         [f"AIRYMAX-SMOKE-FAIL reason=timeout tap={self.tap}"])
        self.assertEqual(self.lines(res, "AIRYMAX-TAP|"), [])
        self.assertEqual(len(self.lines(res, "AIRYMAX-BOOT-CHAIN|")), 3)

    def test_rejects_bad_tap(self):
        cases = {
            "missing probe": PASS.replace("ok 5 - probe 5\n", ""),
            "short plan": PASS.replace("1..5", "1..4"),
            "skip": PASS.replace("# summary", "# SKIP probe\n# summary"),
            "bail": PASS.replace("ok 2 - probe 2", "Bail out! no display"),
            "fail count": PASS.replace("fail=0", "fail=1"),
        }
        for name, tap in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.report(tap=tap).returncode, 1)


if __name__ == "__main__":
    unittest.main()
