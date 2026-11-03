#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_boot_set.py — 开机启用清单与启用动作的回归测试
#
# 2026-11 现场发现：0.0.4 的治理单元全部被 preset 钉在 disabled，只有装机的
# kickstart 会启用它们，升级路径没有任何组件碰 systemd，于是升上来的机器
# 换页无上界、电源与热治理不接管，而 systemctl 的配置视图看起来一切正常。
# 修复把清单收敛成一份 boot-set，把动作收敛成一份 boot_set.sh，三个消费者
# （两份 kickstart 与 %posttrans）都调它。
#
# 本用例守三件事：清单自身合法且每项都能在源码树里找到归属；两个消费者
# 都指向同一份清单与同一个脚本；脚本对 enabled / absent / masked 三种
# 状态的判定与退出码不变。脚本行为用 PATH 前置的假 systemctl 验证，不碰
# 本机的 systemd。
#
# Author: Decheng Li <lidecheng@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DISTRO = Path(__file__).resolve().parents[2]
ROOT = DISTRO.parent
LIST = DISTRO / "presets" / "boot-set"
TOOL = ROOT / "system" / "scripts" / "boot_set.sh"
UNITS = ROOT / "system" / "units"
DESKTOP = DISTRO / "desktop"
SPEC = DISTRO / "specs" / "airymaxos-system.spec"
KS_WORKSTATION = DISTRO / "kickstart" / "airymaxos-workstation.ks"
KS_MINIMAL = DISTRO / "kickstart" / "airymaxos-minimal.ks"

# 清单里的上游单元：不在本仓库，逐个列出而不是放过任意名字，否则
# lightdm.servce 这类拼写错误要到装机现场才暴露。
UPSTREAM = {
    "lightdm.service",
    "bluetooth.service",
    "NetworkManager.service",
    "chronyd.service",
    "firewalld.service",
    "sshd.service",
}

# 本包交付的治理单元：删掉任何一项都意味着对应治理装完即静默缺席。
GOVERNANCE = {
    "airy-rt-bandwidth.service",
    "airy-rt-memcap.service",
    "airy-power.service",
    "airy-power.timer",
    "airy-rt-coexist.service",
    "airy-rt-coexist.timer",
    "airy-disk-mount.service",
    "airy-disk-health.timer",
    "airymax-update-check.timer",
}

UNIT_RE = re.compile(
    r"^[A-Za-z0-9@._-]+\.(service|timer|target|slice|socket|path)$")

FAKE = """\
#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG"
root=
while [ "$#" -gt 0 ]; do
    case "$1" in
    --root=*) root=${1#*=} ;;
    *) break ;;
    esac
    shift
done
for u in $FAKE_ABSENT; do
    [ "$2" = "$u" ] && exit 1
done
for u in $FAKE_MASKED; do
    [ "$2" = "$u" ] && { echo masked; exit 1; }
done
[ "$1" = is-enabled ] && echo enabled
exit 0
"""


def entries():
    out = []
    for line in LIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def locate(unit):
    for base in (UNITS, DESKTOP):
        if (base / unit).is_file():
            return True
    return unit in UPSTREAM


class BootSetTest(unittest.TestCase):
    def test_list_shape(self):
        text = LIST.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertNotIn("\r", text)
        self.assertNotIn("\t", text)
        for line in text.splitlines():
            self.assertEqual(line, line.rstrip(), f"trailing blank: {line!r}")

    def test_entries_unique(self):
        items = entries()
        self.assertTrue(items)
        self.assertEqual(len(items), len(set(items)))

    def test_entries_named(self):
        for unit in entries():
            self.assertRegex(unit, UNIT_RE)

    def test_entries_owned(self):
        for unit in entries():
            self.assertTrue(locate(unit), f"no unit file for {unit}")

    def test_governance_listed(self):
        missing = GOVERNANCE - set(entries())
        self.assertEqual(set(), missing)

    def test_no_agent_stack(self):
        gated = [u for u in entries() if u.startswith("agentrt-")
                 and u.endswith(".service")]
        self.assertEqual([], gated)

    def test_spec_consumes(self):
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("Source49:       boot-set", text)
        self.assertIn("Source50:       boot_set.sh", text)
        self.assertIn(
            "install -m 0644 %{SOURCE49} "
            "%{buildroot}/usr/lib/airymaxos/boot-set", text)
        self.assertIn("%posttrans", text)
        self.assertIn("/usr/lib/airymaxos/scripts/boot_set.sh || :", text)
        self.assertIn("/usr/lib/airymaxos/boot-set", text.split("%files")[1])

    def test_kickstart_consumes(self):
        for ks in (KS_WORKSTATION, KS_MINIMAL):
            text = ks.read_text(encoding="utf-8")
            self.assertIn("/usr/lib/airymaxos/scripts/boot_set.sh", text,
                          ks.name)
            self.assertIn("AIRYMAX-BOOT-SET", text, ks.name)
            self.assertIn("--root=/", text, ks.name)

    def test_no_services_directive(self):
        text = KS_MINIMAL.read_text(encoding="utf-8")
        self.assertNotIn("services --enabled=", text)


class BootSetToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "calls"
        fake = self.bin / "systemctl"
        fake.write_text(FAKE, encoding="utf-8")
        fake.chmod(0o755)
        self.list = root / "list"
        self.rootdir = root / "target"
        self.rootdir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, units, absent="", masked=""):
        self.list.write_text(
            "# comment\n\n" + "".join(f"{u}\n" for u in units),
            encoding="utf-8")
        env = dict(os.environ)
        env.update(PATH=f"{self.bin}:{env['PATH']}", FAKE_LOG=str(self.log),
                   FAKE_ABSENT=absent, FAKE_MASKED=masked)
        return subprocess.run(
            ["bash", str(TOOL), f"--file={self.list}",
             f"--root={self.rootdir}"],
            capture_output=True, text=True, env=env)

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_enabled(self):
        done = self.run_tool(["sshd.service", "airy-power.timer"])
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(
            ["unit=sshd.service state=enabled",
             "unit=airy-power.timer state=enabled"],
            done.stdout.splitlines())
        self.assertIn(f"--root={self.rootdir} enable sshd.service",
                      self.calls())

    def test_absent_is_tolerated(self):
        done = self.run_tool(["lightdm.service"], absent="lightdm.service")
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(["unit=lightdm.service state=absent"],
                         done.stdout.splitlines())

    def test_masked_fails(self):
        done = self.run_tool(["airymax-update-check.timer"],
                             masked="airymax-update-check.timer")
        self.assertEqual(1, done.returncode)
        self.assertEqual(
            ["unit=airymax-update-check.timer state=masked"],
            done.stdout.splitlines())

    def test_missing_list(self):
        env = dict(os.environ)
        env.update(PATH=f"{self.bin}:{env['PATH']}", FAKE_LOG=str(self.log))
        done = subprocess.run(
            ["bash", str(TOOL), f"--file={self.list}"],
            capture_output=True, text=True, env=env)
        self.assertEqual(1, done.returncode)
        self.assertIn("no list", done.stderr)

    def test_bad_usage(self):
        done = subprocess.run(["bash", str(TOOL), "--bogus"],
                              capture_output=True, text=True)
        self.assertEqual(2, done.returncode)
        self.assertIn("usage", done.stderr)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)