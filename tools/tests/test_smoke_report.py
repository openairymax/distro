#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_smoke_report.py — ci/fixture/airymax-smoke-report.sh 契约回归测试
#
# 该脚本是验收 ISO 唯一的串口判定者：产品就绪单元在验收安装中被 mask，
# 因此 TAP 结论、关键链转发与失败单元记账都只在这里发生。脚本运行于已
# 登录的图形会话，CI 宿主机没有该环境；这里用 PATH 沙箱提供伪
# systemd-analyze/systemctl/journalctl，用 TAP 文件与环境变量控制输入，
# 逐项验证「先转发、后结论」的顺序、前缀原文不改写、取证行数有界，以及
# 五种结论路径的退出码。
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
BOOT_STATE = Path(__file__).resolve().parents[2] / "desktop" / "boot_state.sh"
CON = Path(__file__).resolve().parents[2].parent / "system" / "scripts" / "con.sh"
BASH = shutil.which("bash") or "/bin/bash"

PROBES = 9
BOOT_ID = "test-boot"
PLAN = f"TAP version 14\n1..{PROBES}\n# boot={BOOT_ID}\n"
GOOD = PLAN + "".join(f"ok {n} - probe {n}\n" for n in range(1, PROBES + 1))
PASS = GOOD + f"# summary: pass={PROBES} fail=0\n"
STALE = PASS.replace(f"# boot={BOOT_ID}", "# boot=previous-boot")
LEGACY = PASS.replace(f"# boot={BOOT_ID}\n", "")
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
        self.boot = self.root / "boot_id"
        self.boot.write_text(f"{BOOT_ID}\n", encoding="utf-8")
        # 串口与本地屏用空的普通文件顶替：con_init/con_sink 以可写性判定
        # 通道，与真设备走同一条路径
        (self.root / "ttyS0").touch()
        (self.root / "console").touch()
        # 活动控制台列表必须自己钉住：con_init 用它判断串口是否已是 /dev/console
        # 的落点，留空即读宿主机的 /sys/class/tty/console/active。宿主机末位是
        # ttyS0 时本地屏按去重规则被跳过，断言「结论上屏」的用例便随构建机
        # 变化（run 42504510518 就是这样失败的）。产品命令行末位是 tty0。
        self.active = self.root / "console_active"
        self.active.write_text("tty0 tty1\n", encoding="utf-8")
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
            "AIRYMAX_BOOT_ID_FILE": str(self.boot),
            "AIRYMAX_BOOT_STATE": str(BOOT_STATE),
            "AIRYMAX_CON_LIB": str(CON),
            "AIRY_CON_ACTIVE": str(self.active),
            "AIRYMAX_CONSOLE": str(self.root / "console"),
            "AIRY_CON_SERIAL": str(self.root / "ttyS0"),
            "FAKE_CHAIN_FILE": str(self.chain),
        }
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT)], env=env, text=True,
                              capture_output=True)

    def journal(self, units, lines=2):
        log_dir = self.root / "journal"
        log_dir.mkdir(exist_ok=True)
        for unit in units:
            (log_dir / unit).write_text(
                "".join(f"{unit} line{n}\n" for n in range(lines)),
                encoding="utf-8")
        return {"FAKE_JOURNAL_DIR": str(log_dir)}

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

    def channel(self, name):
        path = self.root / name
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def test_detail_kept_off_console(self):
        # 明细按原文转发，探针会报中文字体名；VT 字体没有 CJK 字形，同一行
        # 落到本地屏只剩方块。屏幕只留结论，明细由串口与 journal 承接。
        res = self.report()
        console = self.channel("console")
        self.assertEqual(console, [
            "AIRYMAX-BOOT-HEALTH failed=0",
            f"AIRYMAX-SMOKE-PASS tap={self.tap}",
        ])

    def test_serial_is_console_not_duplicated(self):
        # 串口正是 /dev/console 的落点时，同一行写两遍只是重复噪声；去重由
        # con_init 判定，结论仍须到串口。这一条与上一条互为两个分支，缺任一
        # 分支的用例都会让通道判据回到「各调用方自行猜测」。
        self.active.write_text("tty0 ttyS0\n", encoding="utf-8")
        res = self.report()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.channel("console"), [])
        self.assertIn(f"AIRYMAX-SMOKE-PASS tap={self.tap}",
                      self.channel("ttyS0"))

    def test_detail_reaches_serial(self):
        res = self.report()
        serial = self.channel("ttyS0")
        self.assertEqual([line for line in serial
                          if line.startswith("AIRYMAX-TAP|")],
                         [f"AIRYMAX-TAP|{line}"
                          for line in PASS.splitlines()])
        self.assertIn(f"AIRYMAX-SMOKE-PASS tap={self.tap}", serial)

    def test_console_is_ascii(self):
        # 本地屏的判据是字节集而不是措辞：任何非 ASCII 字节都会变成方块
        res = self.report(tap=PASS.replace(
            "ok 4 - probe 4", "ok 4 - probe 4 # font: 文泉驿等宽微米黑"))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        console = self.channel("console")
        self.assertTrue(console)
        for line in console:
            self.assertTrue(line.isascii(), line)

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

    def test_stale_tap_is_not_evidence(self):
        # /var/log 跨开机保留：上一轮开机的结论与本次无关，既不能判负也不能
        # 判过，只能继续等本轮写出（285H 实测报告在开机 5 秒后读到旧文件）。
        res = self.report(tap=STALE)
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.lines(res, "AIRYMAX-SMOKE-FAIL"),
                         [f"AIRYMAX-SMOKE-FAIL reason=timeout tap={self.tap}"])
        self.assertEqual(self.lines(res, "AIRYMAX-TAP|"), [])

    def test_unstamped_tap_is_not_evidence(self):
        # 没有 boot 行的旧格式同理：无法证明属于本轮，就不算证据
        res = self.report(tap=LEGACY)
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.lines(res, "AIRYMAX-SMOKE-FAIL"),
                         [f"AIRYMAX-SMOKE-FAIL reason=timeout tap={self.tap}"])

    def test_health_reported(self):
        res = self.report()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.lines(res, "AIRYMAX-BOOT-HEALTH"),
                         ["AIRYMAX-BOOT-HEALTH failed=0"])
        self.assertEqual(self.lines(res, "AIRYMAX-UNIT-STATE|"), [])
        self.assertEqual(self.lines(res, "AIRYMAX-UNIT-JOURNAL|"), [])

    def test_degraded_units_fail_run(self):
        res = self.report(FAKE_FAILED_UNITS="sssd.service upower.service",
                          **self.journal(["sssd.service", "upower.service"]))
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.lines(res, "AIRYMAX-BOOT-DEGRADED"),
                         ["AIRYMAX-BOOT-DEGRADED failed=2 "
                          "units=sssd.service,upower.service"])
        self.assertEqual(self.lines(res, "AIRYMAX-SMOKE-FAIL"),
                         [f"AIRYMAX-SMOKE-FAIL reason=degraded "
                          f"tap={self.tap}"])
        self.assertIn("AIRYMAX-UNIT-STATE|upower.service|"
                      "ActiveState=active SubState=running Result=success "
                      "NRestarts=0 MainPID=0", res.stdout)
        self.assertEqual(len(self.lines(
            res, "AIRYMAX-UNIT-JOURNAL|upower.service|")), 2)
        self.assertEqual(res.stdout.rstrip().splitlines()[-1],
                         f"AIRYMAX-SMOKE-FAIL reason=degraded tap={self.tap}")

    def test_evidence_is_bounded(self):
        units = [f"u{n}.service" for n in range(12)]
        res = self.report(FAKE_FAILED_UNITS=" ".join(units),
                          **self.journal(units, lines=40))
        self.assertEqual(res.returncode, 1)
        shown = sorted(units)[:8]
        self.assertIn("AIRYMAX-BOOT-DEGRADED failed=12 units="
                      + ",".join(shown), res.stdout)
        self.assertEqual(len(self.lines(res, "AIRYMAX-UNIT-STATE|")), 8)
        for unit in shown:
            logs = self.lines(res, f"AIRYMAX-UNIT-JOURNAL|{unit}|")
            self.assertEqual(len(logs), 12)

    def test_evidence_precedes_fail(self):
        res = self.report(FAKE_FAILED_UNITS="sssd.service",
                          **self.journal(["sssd.service"]))
        marker = self.verdict_at(res, "AIRYMAX-SMOKE-FAIL")
        last = max(index for index, line in enumerate(res.stdout.splitlines())
                   if line.startswith("AIRYMAX-UNIT-"))
        self.assertLess(last, marker)

    def test_boot_state_missing(self):
        absent = self.root / "absent.sh"
        res = self.report(AIRYMAX_BOOT_STATE=str(absent))
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.lines(res, "AIRYMAX-SMOKE-FAIL"),
                         [f"AIRYMAX-SMOKE-FAIL reason=boot-state "
                          f"path={absent}"])

    def test_timeout_reports_health(self):
        res = self.report(tap=None)
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-BOOT-HEALTH failed=0", res.stdout)
        self.assertEqual(res.stdout.rstrip().splitlines()[-1],
                         f"AIRYMAX-SMOKE-FAIL reason=timeout tap={self.tap}")

    def test_rejects_bad_tap(self):
        cases = {
            "missing probe": PASS.replace(
                f"ok {PROBES} - probe {PROBES}\n", ""),
            "short plan": PASS.replace(f"1..{PROBES}", f"1..{PROBES - 1}"),
            "duplicate probe": PASS.replace("ok 3 - probe 3",
                                            "ok 2 - probe 3"),
            "skip": PASS.replace("# summary", "# SKIP probe\n# summary"),
            "bail": PASS.replace("ok 2 - probe 2", "Bail out! no display"),
            "fail count": PASS.replace("fail=0", "fail=1"),
        }
        for name, tap in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.report(tap=tap).returncode, 1)


if __name__ == "__main__":
    unittest.main()
