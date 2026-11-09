#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_audio_init.py — 首启声卡初始化脚本与单元的契约回归测试
#
# 285H 实测的因果链是：HDA 功放上电停在索引 0（Master 0/87，-65 dB，开关
# off），上游初始化库只白名单两台旧笔记本，alsa-state 在状态文件缺失时只
# 恢复、不初始化，于是首启的静音被 asound.state 与 PulseAudio 的用户态
# 音量一起固化。脚本要做的就是「有卡则逐卡初始化一次并落盘，无卡不算错，
# 退出码 99 是通用方法成功」。这里用伪 alsactl 驱动每条分支，并把单元、
# boot-set 与 spec 三处接线一并断言：漏接任何一处，症状都是无声而不是
# 报错，只能靠构建期拦下。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import fakes

BASE = Path(__file__).resolve().parents[2]
SCRIPT = BASE / "desktop" / "audio_init.sh"
UNIT = BASE / "desktop" / "airymax-audio-init.service"
BOOTSET = BASE / "presets" / "boot-set"
SPEC = BASE / "specs" / "airymaxos-release.spec"
BASH = shutil.which("bash") or "/bin/bash"

ALSACTL = """\
#!/bin/sh
printf '%s\\n' "$*" >> "${FAKE_ALSACTL_LOG:?}"
case " $* " in
*" init "*) exit "${FAKE_ALSACTL_RC:-0}" ;;
*" store "*) exit "${FAKE_ALSACTL_STORE_RC:-0}" ;;
esac
exit 0
"""


def fields(unit):
    """把单元文件读成「段落.键 -> 值」的字典，重复键保留最后一条。"""
    out = {}
    section = ""
    for line in unit.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        key, _, value = line.partition("=")
        out[f"{section}.{key.strip()}"] = value.strip()
    return out


class AudioInitTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="airymax-audio-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        fakes.link_tools(self.bin)
        fakes.write(self.bin, "alsactl", ALSACTL)
        self.root = self.tmp / "asound"
        self.root.mkdir()
        self.log = self.tmp / "alsactl.log"

    def calls(self):
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def invoke(self, cards=(0,), **extra):
        for card in cards:
            (self.root / f"card{card}").mkdir()
        env = dict(os.environ)
        env.update({
            "PATH": f"{self.bin}:{env.get('PATH', '')}",
            "AIRYMAX_CARD_ROOT": str(self.root),
            "AIRYMAX_ALSACTL": str(self.bin / "alsactl"),
            "FAKE_ALSACTL_LOG": str(self.log),
            "FAKE_ALSACTL_RC": "0",
            "FAKE_ALSACTL_STORE_RC": "0",
        })
        env.update({key: str(value) for key, value in extra.items()})
        return subprocess.run([BASH, str(SCRIPT)], env=env,
                              capture_output=True, text=True)

    def test_each_card_is_initialized_then_stored(self):
        got = self.invoke(cards=(0, 1))
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(self.calls(), ["init 0", "init 1", "store"])
        self.assertIn("AIRYMAX-AUDIO card=0 action=init result=ok rc=0",
                      got.stdout)
        self.assertIn("AIRYMAX-AUDIO card=1 action=init result=ok rc=0",
                      got.stdout)
        self.assertIn("AIRYMAX-AUDIO result=done cards=2", got.stdout)
        self.assertEqual(got.stderr, "")

    def test_generic_method_exit_99_is_success(self):
        got = self.invoke(FAKE_ALSACTL_RC="99")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("card=0 action=init result=ok rc=99", got.stdout)
        self.assertIn("result=done cards=1", got.stdout)

    def test_init_failure_is_visible_and_skips_store(self):
        got = self.invoke(FAKE_ALSACTL_RC="3")
        self.assertEqual(got.returncode, 1)
        self.assertIn("AIRYMAX-AUDIO card=0 action=init result=fail rc=3",
                      got.stderr)
        self.assertIn("AIRYMAX-AUDIO result=failed cards=1", got.stderr)
        self.assertNotIn("store", self.calls())

    def test_store_failure_is_visible(self):
        got = self.invoke(FAKE_ALSACTL_STORE_RC="1")
        self.assertEqual(got.returncode, 1)
        self.assertIn("AIRYMAX-AUDIO result=failed cards=1 action=store",
                      got.stderr)

    def test_missing_card_is_not_an_error(self):
        got = self.invoke(cards=())
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("AIRYMAX-AUDIO result=absent cards=0", got.stdout)
        self.assertEqual(self.calls(), [])

    def test_unit_runs_once_per_absent_state(self):
        unit = fields(UNIT)
        self.assertEqual(
            unit["Unit.ConditionPathExists"],
            "!/var/lib/alsa/asound.state",
            "条件少了 ! 会在每次启动重设音量，覆盖用户设置")
        self.assertEqual(unit["Unit.After"], "alsa-state.service")
        self.assertEqual(unit["Unit.Before"], "sound.target")
        self.assertEqual(unit["Service.Type"], "oneshot")
        self.assertEqual(unit["Service.ExecStart"],
                         "/usr/lib/airymaxos/desktop/audio_init.sh")
        self.assertEqual(unit["Install.WantedBy"], "sound.target")

    def test_boot_set_enables_the_unit(self):
        names = [line.strip()
                 for line in BOOTSET.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.startswith("#")]
        self.assertIn("airymax-audio-init.service", names)

    def test_spec_ships_unit_and_script(self):
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn("Source44:       airymax-audio-init.service", spec)
        self.assertIn("Source45:       audio_init.sh", spec)
        self.assertIn(
            "install -m 0644 %{SOURCE44} \\\n"
            "    %{buildroot}%{_unitdir}/airymax-audio-init.service", spec)
        self.assertIn(
            "install -m 0755 %{SOURCE45} \\\n"
            "    %{buildroot}/usr/lib/airymaxos/desktop/audio_init.sh", spec)
        self.assertIn("%{_unitdir}/airymax-audio-init.service\n", spec)
        self.assertIn("/usr/lib/airymaxos/desktop/audio_init.sh\n", spec)

    def test_console_markers_stay_ascii(self):
        for number, line in enumerate(
                SCRIPT.read_text(encoding="utf-8").splitlines(), 1):
            text = line.strip()
            if not text.startswith(("say ", "warn ")):
                continue
            try:
                text.encode("ascii")
            except UnicodeEncodeError:
                self.fail(f"标记行 {number} 含非 ASCII：VT 字体无对应字形")


if __name__ == "__main__":
    unittest.main()
