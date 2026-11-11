#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_console_font.py — 控制台字体策略的行为用例
#
# 这一层的全部判据只有三条：字体缺席时不写、有 FONT 时按行替换、其余键原样
# 保留。三条都在安装事务的最后一秒发生，装完再发现写错，代价是一屏读不出
# 的启动日志（验收 run 42960420278 的 T22）。用环境变量把字体目录、配置与
# 日志指到夹具树，脚本自身的默认路径与目标机一致。
#
# Author: Decheng Li <lidecheng@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import subprocess
import tempfile
import unittest
from pathlib import Path

FONT = Path(__file__).resolve().parents[2] / "desktop" / "console-font.sh"
NAME = "latarcyrheb-sun32"


class FontTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fonts = self.root / "consolefonts"
        self.fonts.mkdir()
        self.conf = self.root / "vconsole.conf"
        self.log = self.root / "log" / "console-font.log"

    def tearDown(self):
        self._tmp.cleanup()

    def provide(self, suffix=".psfu.gz"):
        path = self.fonts / f"{NAME}{suffix}"
        path.write_bytes(b"\x72\xb5\x6a\x86")
        return path

    def run_font(self, *args):
        env = {
            "PATH": "/usr/bin:/bin",
            "AIRY_CONSOLE_FONT_DIR": str(self.fonts),
            "AIRY_CONSOLE_CONF": str(self.conf),
            "AIRY_CONSOLE_LOG": str(self.log),
        }
        return subprocess.run(["sh", str(FONT), *args],
                              capture_output=True, text=True, env=env)

    def evidence(self):
        if not self.log.exists():
            return ""
        return self.log.read_text(encoding="utf-8").strip().splitlines()[-1]

    def test_absent_font_writes_nothing(self):
        """字体不在盘上时连配置文件都不创建：指向空字体比小字更糟。"""
        res = self.run_font()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(self.conf.exists())
        self.assertIn(f"skip font={NAME} reason=absent", self.evidence())

    def test_appends_when_conf_has_no_font(self):
        """anaconda 写下的配置只有 KEYMAP 时补一行 FONT，不动别的行。"""
        self.provide()
        self.conf.write_text('KEYMAP="us"\n', encoding="utf-8")
        res = self.run_font()
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self.conf.read_text(encoding="utf-8")
        self.assertIn('KEYMAP="us"\n', text)
        self.assertIn(f'FONT="{NAME}"\n', text)
        self.assertIn("state=written was=none", self.evidence())

    def test_replaces_default_font(self):
        """T22 的现场形态：sun16 被替换，KEYMAP 原样保留，且只留一行 FONT。"""
        self.provide()
        self.conf.write_text(
            'KEYMAP="us"\nFONT="latarcyrheb-sun16"\n', encoding="utf-8")
        res = self.run_font()
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self.conf.read_text(encoding="utf-8")
        self.assertIn('KEYMAP="us"\n', text)
        self.assertIn(f'FONT="{NAME}"\n', text)
        self.assertNotIn("sun16", text)
        self.assertEqual(text.count("FONT="), 1)
        self.assertIn("was=latarcyrheb-sun16", self.evidence())

    def test_second_run_is_idempotent(self):
        """重复调用不重写、不重复追加：升级与装机两条路径可能先后都跑。"""
        self.provide()
        self.conf.write_text(f'FONT="{NAME}"\n', encoding="utf-8")
        res = self.run_font()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.conf.read_text(encoding="utf-8"),
                         f'FONT="{NAME}"\n')
        self.assertIn("state=already", self.evidence())

    def test_uncompressed_font_counts(self):
        """未压缩的 .psf 也算在盘上：后缀口径必须与 T22 的四种一致。"""
        self.provide(".psf")
        res = self.run_font()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f'FONT="{NAME}"', self.conf.read_text(encoding="utf-8"))

    def test_unwritable_conf_fails(self):
        """写不进去必须留 fail 证据并以 1 退出：silent skip 会把 T22 拖到装机后。"""
        self.provide()
        self.conf = self.root / "missing" / "vconsole.conf"
        res = self.run_font()
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail font=" + NAME, self.evidence())

    def test_usage_error(self):
        """未知参数是用法错误，与判定失败分开报。"""
        res = self.run_font("--bogus")
        self.assertEqual(res.returncode, 2)
        self.assertIn("用法", res.stderr)

    def test_source_leaves_script_inert(self):
        """被 source 时正文只定义函数：调用点自己决定何时执行。"""
        res = subprocess.run(
            ["sh", "-c", '. "$1"; printf "sourced\\n"', "sh", str(FONT)],
            capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("sourced", res.stdout)


if __name__ == "__main__":
    unittest.main()
