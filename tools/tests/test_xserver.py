#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_xserver.py — 座位 X server 驱动选择封装契约回归测试
#
# 契约有三条：真实 KMS 驱动且存在「已连接 + 有模式 + 有 EDID」的输出时
# 不干预 X 的自动选择；三条缺任一（或只有 simpledrm）时必须以 fbdev 接管
# /dev/fb0，否则 vesa 与 modesetting 都拒绝运行，座位每次拉起即死；两者
# 都不成立（无卡也无 framebuffer）时判不适用，交回 Xorg 自行决定。
#
# 判定只看 sysfs 的驱动名、连接器状态、modes 内容与 EDID 大小，因此用伪
# DRM 目录与伪 Xorg 驱动，断言落在「转交给 Xorg 的 argv」、标记行与生成的
# 设备段内容上。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import subprocess
import tempfile
import unittest
from pathlib import Path

import fakes

BASE = Path(__file__).resolve().parents[2]
SCRIPT = BASE / "desktop" / "xserver.sh"
SEAT = BASE / "desktop" / "lightdm" / "50-airymax.conf"
SPEC = BASE / "specs" / "airymaxos-release.spec"
INSTALLED = "/usr/lib/airymaxos/desktop/xserver"
SH = "/bin/sh"
EDID = bytes(range(128))
XORG = """\
#!/bin/sh
printf 'ARG %s\\n' "$@"
exit 0
"""
ARGS = (":0", "-seat", "seat0", "-auth", "/run/lightdm/root/:0",
        "-nolisten", "tcp")


class XServerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fakes.link_tools(self.bin)
        self.drm = self.root / "drm"
        self.drm.mkdir()
        self.fb = self.root / "fb0"
        self.fb.write_text("", encoding="utf-8")
        self.conf = self.root / "run" / "airymaxos" / "xserver-fbdev.conf"
        self.state = self.root / "run" / "airymaxos" / "xserver.log"
        self.xorg = self.bin / "Xorg"
        self.xorg.write_text(XORG, encoding="utf-8")
        self.xorg.chmod(0o755)

    def tearDown(self):
        self._tmp.cleanup()

    def add_card(self, driver):
        target = self.root / "drivers" / driver
        target.mkdir(parents=True, exist_ok=True)
        device = self.drm / "card0" / "device"
        device.mkdir(parents=True, exist_ok=True)
        (device / "driver").symlink_to(target)
        return self.drm / "card0"

    def add_out(self, card, name="DP-1", status="connected",
                modes="1920x1080\n", edid=EDID):
        out = card.parent / f"{card.name}-{name}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "status").write_text(status + "\n", encoding="utf-8")
        (out / "modes").write_text(modes, encoding="utf-8")
        (out / "edid").write_bytes(edid)
        return out

    def run_seat(self, *args, **extra):
        env = {"PATH": str(self.bin), "AIRYMAX_DRM_DIR": str(self.drm),
               "AIRYMAX_FB_DEV": str(self.fb),
               "AIRYMAX_XSERVER_CONF": str(self.conf),
               "AIRYMAX_XSERVER_STATE": str(self.state),
               "AIRYMAX_XORG": str(self.xorg)}
        env.update(extra)
        return subprocess.run([SH, str(SCRIPT), *(args or ARGS)], env=env,
                              text=True, capture_output=True)

    def argv(self, stdout):
        return [line[4:] for line in stdout.splitlines()
                if line.startswith("ARG ")]

    def assert_fbdev(self, res, gap):
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"AIRYMAX-XSERVER driver=fbdev reason={gap} "
                      f"fb={self.fb} conf={self.conf}", res.stdout)
        argv = self.argv(res.stdout)
        self.assertEqual(argv[:2], ["-config", str(self.conf)])
        self.assertEqual(argv[2:], list(ARGS))
        self.assertIn(f"display gap {gap}", res.stderr)

    def test_posix_syntax(self):
        res = subprocess.run([SH, "-n", str(SCRIPT)], text=True,
                             capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_kms_ready_keeps_auto(self):
        self.add_out(self.add_card("i915"))
        res = self.run_seat()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("AIRYMAX-XSERVER driver=i915 kms=1", res.stdout)
        self.assertEqual(self.argv(res.stdout), list(ARGS))
        self.assertFalse(self.conf.exists())

    def test_connected_without_edid(self):
        self.add_out(self.add_card("i915"), edid=b"")
        self.assert_fbdev(self.run_seat(), "no-edid")

    def test_connected_without_mode(self):
        self.add_out(self.add_card("i915"), modes="\n")
        self.assert_fbdev(self.run_seat(), "no-mode")

    def test_disconnected_output_ignored(self):
        self.add_out(self.add_card("i915"), status="disconnected")
        self.assert_fbdev(self.run_seat(), "no-output")

    def test_simpledrm_never_auto(self):
        # simpledrm 也报 modes 与 EDID，但 X 1.20 的 modesetting 不接管它。
        self.add_out(self.add_card("simple-framebuffer"))
        self.assert_fbdev(self.run_seat(), "no-kms")

    def test_fbdev_when_no_card(self):
        self.assert_fbdev(self.run_seat(), "no-kms")

    def test_absent_framebuffer_defers(self):
        self.add_card("simple-framebuffer")
        self.fb.unlink()
        res = self.run_seat()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("AIRYMAX-XSERVER driver=none note=no-display", res.stdout)
        self.assertEqual(self.argv(res.stdout), list(ARGS))

    def test_unwritable_conf_defers(self):
        self.add_card("simple-framebuffer")
        blocker = self.root / "block"
        blocker.write_text("", encoding="utf-8")
        res = self.run_seat(AIRYMAX_XSERVER_CONF=str(blocker / "x.conf"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("note=conf-unwritable", res.stdout)
        self.assertEqual(self.argv(res.stdout), list(ARGS))

    def test_marker_persists(self):
        self.add_card("simple-framebuffer")
        res = self.run_seat()
        self.assertEqual(res.returncode, 0, res.stderr)
        line = (f"AIRYMAX-XSERVER driver=fbdev reason=no-kms fb={self.fb} "
                f"conf={self.conf}")
        self.assertIn(line, res.stdout)
        self.assertEqual(self.state.read_text(encoding="utf-8"), line + "\n")

    def test_seat_declares_wrapper(self):
        lines = [line.strip() for line in SEAT.read_text(
            encoding="utf-8").splitlines()]
        self.assertIn(f"xserver-command={INSTALLED}", lines)

    def test_spec_ships_wrapper(self):
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn(
            "install -m 0755 %{SOURCE26} \\\n"
            "    %{buildroot}/usr/lib/airymaxos/desktop/xserver", spec)
        self.assertIn(f"\n{INSTALLED}\n", spec)


if __name__ == "__main__":
    unittest.main()
