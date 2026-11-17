#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_net_ready.py — 首启联机就绪探针契约回归测试
#
# 探针的职责是把「装完能不能联网」转换成宿主机可判定的串口标记。判据只有
# 四元组（地址/来源/网关/DNS），全部取自 airy-observe——网关 ICMP 在 CI 的
# slirp 网络里不回包，若把它写进判据，验收腿会永远判负。
#
# 每个用例只破坏一个前提：缺网关、缺 DNS、非 DHCP、观察工具失败，都要落
# AIRYMAX-NET-OFFLINE 而不是崩溃；探针始终 0 退出，否则它会把自己写进
# systemctl --failed，被 AIRYMAX-BOOT-HEALTH 当成启动失败。
#
# 等待分两段：快段过期只落 AIRYMAX-NET-LATE 边界行，不代表离线；慢段内
# 拿到租约仍要产出 READY。用例默认把慢段设为 0，让离线断言保持瞬时；慢段
# 自身的行为由 AIRYMAX_NET_LATE 显式驱动的三个用例覆盖。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
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
SCRIPT = BASE / "desktop" / "net_ready.sh"
UNIT = BASE / "desktop" / "airymax-net-ready.service"
UI = BASE.parent / "system" / "scripts" / "ui.sh"
CON = BASE.parent / "system" / "scripts" / "con.sh"
BASH = shutil.which("bash") or "/bin/bash"
READY = "AIRYMAX-NET-READY"
OFFLINE = "AIRYMAX-NET-OFFLINE"
FAIL = "AIRYMAX-NET-FAIL"

NET_OK = """\
AIRYMAX-OBSERVE net.ipv4=ens3=10.0.2.15
AIRYMAX-OBSERVE net.src=dhcp
AIRYMAX-OBSERVE net.gw=10.0.2.2
AIRYMAX-OBSERVE net.dns=10.0.2.3
"""


class NetReadyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.vt_dir = self.root / "dev"
        self.bin.mkdir()
        self.vt_dir.mkdir()
        fakes.link_tools(self.bin)
        self.console_active = self.root / "console-active"
        self.console_active.write_text("tty0 ttyS0\n", encoding="utf-8")
        self.vt_active = self.root / "vt-active"
        self.vt_active.write_text("tty1\n", encoding="utf-8")
        (self.vt_dir / "tty1").write_text("", encoding="utf-8")
        self.observe(NET_OK)

    def tearDown(self):
        self._tmp.cleanup()

    def observe(self, body, rc=0):
        fakes.write(self.bin, "airy-observe",
                    "#!/bin/sh\n"
                    f"printf '%s' '{body}'\n"
                    f"exit {rc}\n")

    def observe_seq(self, bodies):
        """按调用次数回放观测正文，用来驱动慢段内「先无后有」的时序。"""
        state = self.root / "observe-count"
        state.write_text("0\n", encoding="utf-8")
        cases = "".join(f"  {i}) printf '%s' '{body}' ;;\n"
                        for i, body in enumerate(bodies, 1))
        fakes.write(self.bin, "airy-observe",
                    "#!/bin/sh\n"
                    f"n=$(cat '{state}')\n"
                    "n=$((n + 1))\n"
                    f"printf '%s\\n' \"$n\" >'{state}'\n"
                    "case \"$n\" in\n"
                    f"{cases}"
                    f"  *) printf '%s' '{bodies[-1]}' ;;\n"
                    "esac\n")

    def run_probe(self, *args, **extra):
        self.serial = self.root / "ttyS0"
        self.serial.write_text("", encoding="utf-8")
        env = {"PATH": str(self.bin), "HOME": str(self.root),
               "AIRYMAX_NET_WAIT": "0", "AIRYMAX_NET_LATE": "0",
               "AIRYMAX_NET_POLL": "1",
               "AIRYMAX_OBSERVE": str(self.bin / "airy-observe"),
               "AIRYMAX_UI_LIB": str(UI),
               "AIRYMAX_CON_LIB": str(CON),
               "AIRY_CON_SERIAL": str(self.serial),
               "UI_CONSOLE": str(self.root / "console"),
               "AIRYMAX_CONSOLE_ACTIVE": str(self.console_active),
               "AIRYMAX_VT_ACTIVE": str(self.vt_active),
               "AIRYMAX_VT_DIR": str(self.vt_dir)}
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def test_ready_reports_quartet(self):
        res = self.run_probe()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(
            f"{READY} ipv4=ens3=10.0.2.15 src=dhcp "
            "gw=10.0.2.2 dns=10.0.2.3", res.stdout)
        self.assertNotIn(OFFLINE, res.stdout)

    def test_marker_reaches_the_serial_console(self):
        """单元 stdout 只进 journal，宿主机读的是串口：结论必须自己走通道。"""
        self.run_probe()
        self.assertIn(f"{READY} ipv4=ens3=10.0.2.15",
                      self.serial.read_text(encoding="utf-8"))

    def test_gateway_missing_is_offline(self):
        self.observe(NET_OK.replace(
            "AIRYMAX-OBSERVE net.gw=10.0.2.2\n",
            "AIRYMAX-OBSERVE net.gw=none\n"))
        res = self.run_probe()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"{OFFLINE} ", res.stdout)
        self.assertNotIn(READY, res.stdout)

    def test_dns_missing_is_offline(self):
        self.observe(NET_OK.replace(
            "AIRYMAX-OBSERVE net.dns=10.0.2.3\n",
            "AIRYMAX-OBSERVE net.dns=absent\n"))
        res = self.run_probe()
        self.assertIn(OFFLINE, res.stdout)

    def test_static_addressing_is_offline(self):
        """来源不是 DHCP 说明地址不是本轮协商来的，不能算「装完能联网」。"""
        self.observe(NET_OK.replace("net.src=dhcp", "net.src=static"))
        res = self.run_probe()
        self.assertIn(OFFLINE, res.stdout)

    def test_absent_network_is_offline(self):
        res = self.run_probe(AIRYMAX_OBSERVE=str(self.root / "missing"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(OFFLINE, res.stdout)

    def test_observer_failure_is_offline(self):
        self.observe(NET_OK, rc=1)
        res = self.run_probe()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(OFFLINE, res.stdout)

    def test_wait_is_bounded(self):
        self.observe("AIRYMAX-OBSERVE net.src=none\n")
        started = time.monotonic()
        res = self.run_probe(AIRYMAX_NET_WAIT="2")
        elapsed = time.monotonic() - started
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertLess(elapsed, 10)
        self.assertIn("AIRYMAX-NET-WAIT elapsed=0s", res.stdout)
        self.assertIn(OFFLINE, res.stdout)

    def test_wait_emits_heartbeat(self):
        self.observe("AIRYMAX-OBSERVE net.src=none\n")
        res = self.run_probe(AIRYMAX_NET_WAIT="3", AIRYMAX_NET_BEAT="1")
        self.assertIn("AIRYMAX-NET-WAIT elapsed=1s", res.stdout)
        self.assertIn(OFFLINE, res.stdout)

    def test_short_wait_has_no_heartbeat(self):
        self.observe("AIRYMAX-OBSERVE net.src=none\n")
        res = self.run_probe(AIRYMAX_NET_WAIT="2", AIRYMAX_NET_BEAT="6")
        self.assertEqual(
            res.stdout.count("AIRYMAX-NET-WAIT"), 1, res.stdout)

    def test_fast_expiry_is_not_a_verdict(self):
        """快段过期只是转段：LATE 在 OFFLINE 之前，离线结论只出现一次。"""
        self.observe("AIRYMAX-OBSERVE net.src=none\n")
        res = self.run_probe(AIRYMAX_NET_WAIT="1", AIRYMAX_NET_LATE="1",
                             AIRYMAX_NET_SLOW="1")
        self.assertIn("AIRYMAX-NET-LATE ipv4=", res.stdout)
        self.assertLess(res.stdout.index("AIRYMAX-NET-LATE"),
                        res.stdout.index(OFFLINE))
        self.assertEqual(res.stdout.count(OFFLINE), 1, res.stdout)
        self.assertEqual(res.stdout.count(READY), 0, res.stdout)

    def test_late_window_recovers_ready(self):
        """慢段内才拿到租约仍要 READY：285H 假阴性的回归用例。"""
        self.observe_seq(["AIRYMAX-OBSERVE net.src=none\n", NET_OK])
        res = self.run_probe(AIRYMAX_NET_WAIT="0", AIRYMAX_NET_LATE="4",
                             AIRYMAX_NET_SLOW="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"{READY} ipv4=ens3=10.0.2.15", res.stdout)
        self.assertNotIn(OFFLINE, res.stdout)

    def test_slow_heartbeat_reports_progress(self):
        self.observe("AIRYMAX-OBSERVE net.src=none\n")
        res = self.run_probe(AIRYMAX_NET_WAIT="0", AIRYMAX_NET_LATE="2",
                             AIRYMAX_NET_SLOW="1",
                             AIRYMAX_NET_LATE_BEAT="1")
        self.assertIn("AIRYMAX-NET-SLOW elapsed=1s", res.stdout)
        self.assertIn(OFFLINE, res.stdout)

    def test_missing_boot_state_fails(self):
        res = self.run_probe(
            AIRYMAX_BOOT_STATE=str(self.root / "absent.sh"))
        self.assertEqual(res.returncode, 1)
        self.assertIn(f"{FAIL} reason=no-boot-state", res.stderr)

    def test_unit_contract(self):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        parser.read_string(UNIT.read_text(encoding="utf-8"))
        unit = parser["Unit"]
        service = parser["Service"]
        install = parser["Install"]
        self.assertEqual(unit["After"], "NetworkManager.service")
        self.assertEqual(unit["Wants"], "NetworkManager.service")
        self.assertEqual(service["Type"], "simple")
        self.assertEqual(service["ExecStart"],
                         "/usr/lib/airymaxos/desktop/net_ready.sh")
        self.assertEqual(service["StandardOutput"], "journal")
        self.assertEqual(service["StandardError"], "journal+console")
        self.assertEqual(install["WantedBy"], "graphical.target")
        self.assertNotIn("User", service)


if __name__ == "__main__":
    unittest.main()
