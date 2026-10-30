#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_cfg_brand.py — tools/cfg_brand.py 品牌化回归测试
#
# 底座引导菜单保留 openEuler 原文且缺省项停在「Test this media」，是 0.0.3
# 实测的装机缺陷根因。这里用与 netinst 同形的 grub/isolinux 配置驱动四个
# 判定：标题按产品名改写、default 指向含 inst.ks 且不含 rd.live.check 的
# 安装项、Troubleshooting/Rescue 类条目不误改、重复执行幂等。内核行与
# inst.ks=/LABEL= 必须逐字节保留，否则 kickstart 与 stage2 定位会失效。
# 另外覆盖 .treeinfo 的品牌键改写与 boot.msg 的品牌串替换，二者同样要求
# 其余内容逐字节不变、二次运行退出 3。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "cfg_brand.py"
PRODUCT = "AirymaxOS 0.0.3"

GRUB = """\
set default="1"
set timeout=60

menuentry 'Install openEuler 24.03-LTS-SP2' {
    linuxefi /vmlinuz inst.ks=hd:LABEL=AIRYMAXOS:/ks.cfg inst.stage2=hd:LABEL=AIRYMAXOS
}
menuentry 'Test this media & install openEuler 24.03-LTS-SP2' {
    linuxefi /vmlinuz inst.ks=hd:LABEL=AIRYMAXOS:/ks.cfg inst.stage2=hd:LABEL=AIRYMAXOS rd.live.check
}
menuentry 'Rescue a openEuler system' {
    linuxefi /vmlinuz inst.stage2=hd:LABEL=AIRYMAXOS
}
submenu 'Troubleshooting -->' {
    menuentry 'Install openEuler 24.03-LTS-SP2 in basic graphics mode' {
        linuxefi /vmlinuz inst.stage2=hd:LABEL=AIRYMAXOS
    }
}
"""

ISOLINUX = """\
default=1
timeout 600

label 0
  menu label ^Install openEuler 24.03-LTS-SP2
  append inst.ks=hd:LABEL=AIRYMAXOS:/ks.cfg inst.stage2=hd:LABEL=AIRYMAXOS quiet
label 1
  menu label Test this media & install openEuler 24.03-LTS-SP2
  append inst.ks=hd:LABEL=AIRYMAXOS:/ks.cfg inst.stage2=hd:LABEL=AIRYMAXOS rd.live.check quiet
label 2
  menu label ^Troubleshooting -->
  append inst.stage2=hd:LABEL=AIRYMAXOS rd.debug
"""

NO_KS = """\
set default="0"
menuentry 'Install openEuler 24.03-LTS-SP2' {
    linuxefi /vmlinuz inst.stage2=hd:LABEL=AIRYMAXOS
}
"""

TREEINFO = """\
[general]
timestamp = 1750912660.4513083
family = openEuler
version = 24.03-LTS-SP2
name = openEuler-24.03-LTS-SP2
variant = Server
arch = x86_64
packagedir = 

[stage2]
mainimage = images/install.img

[images-x86_64]
kernel = images/pxeboot/vmlinuz
initrd = images/pxeboot/initrd.img
efiboot.img = images/efiboot.img
"""

BOOTMSG = "\x0c \n\x18splash.lss\n\n -  Welcome to openEuler 24.03-LTS-SP2\n\n"
BOOTMSG_PLAIN = "\x0c \n\x18splash.lss\n\n -  Press the \x0f01<ENTER>\x0f07 key\n\n"


class CfgBrandTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, text, name="grub.cfg"):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args],
                              text=True, capture_output=True)

    def brand(self, path):
        return self.run_tool("--product", PRODUCT, str(path))

    def test_grub_brand_and_default(self):
        path = self.make(GRUB)
        res = self.brand(path)
        self.assertEqual(res.returncode, 0, res.stderr)
        text = path.read_text(encoding="utf-8")
        self.assertIn("menuentry 'Install AirymaxOS 0.0.3'", text)
        self.assertIn("menuentry 'Test this media & install AirymaxOS 0.0.3'",
                      text)
        self.assertIn("menuentry 'Rescue AirymaxOS 0.0.3 system'", text)
        self.assertIn('set default="0"', text)
        self.assertIn("inst.ks=hd:LABEL=AIRYMAXOS:/ks.cfg", text)
        self.assertIn("inst.stage2=hd:LABEL=AIRYMAXOS", text)
        self.assertIn("default -> Install AirymaxOS 0.0.3", res.stderr)

    def test_grub_already_default(self):
        path = self.make(GRUB.replace('set default="1"', 'set default="0"')
                         .replace("openEuler 24.03-LTS-SP2", "AirymaxOS 0.0.3")
                         .replace("Rescue a openEuler system",
                                  "Rescue AirymaxOS 0.0.3 system"))
        res = self.brand(path)
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertEqual(res.stderr, "")

    def test_isolinux_brand_and_default(self):
        path = self.make(ISOLINUX, "isolinux.cfg")
        res = self.brand(path)
        self.assertEqual(res.returncode, 0, res.stderr)
        text = path.read_text(encoding="utf-8")
        self.assertIn("default=0", text)
        self.assertIn("menu label ^Install AirymaxOS 0.0.3", text)
        self.assertIn("menu label Test this media & install AirymaxOS 0.0.3",
                      text)
        self.assertIn("menu label ^Troubleshooting -->", text)

    def test_untouched_titles(self):
        path = self.make(ISOLINUX, "isolinux.cfg")
        self.assertEqual(self.brand(path).returncode, 0)
        text = path.read_text(encoding="utf-8")
        self.assertIn("^Troubleshooting -->", text)
        self.assertNotIn("Troubleshooting AirymaxOS", text)
        self.assertIn("append inst.ks=hd:LABEL=AIRYMAXOS:/ks.cfg", text)

    def test_idempotent(self):
        path = self.make(GRUB)
        self.assertEqual(self.brand(path).returncode, 0)
        again = self.brand(path)
        self.assertEqual(again.returncode, 3, again.stderr)
        self.assertEqual(again.stderr, "")

    def test_missing_inst_ks(self):
        path = self.make(NO_KS)
        res = self.brand(path)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), NO_KS)

    def test_treeinfo_brand(self):
        path = self.make(TREEINFO, ".treeinfo")
        res = self.brand(path)
        self.assertEqual(res.returncode, 0, res.stderr)
        text = path.read_text(encoding="utf-8")
        self.assertIn("family = AirymaxOS", text)
        self.assertIn("version = 0.0.3", text)
        self.assertIn("name = AirymaxOS-0.0.3", text)
        self.assertIn("variant = Server", text)
        self.assertIn("mainimage = images/install.img", text)
        self.assertIn("general.name=openEuler-24.03-LTS-SP2 -> AirymaxOS-0.0.3",
                      res.stderr)

    def test_treeinfo_idempotent(self):
        path = self.make(TREEINFO, ".treeinfo")
        self.assertEqual(self.brand(path).returncode, 0)
        again = self.brand(path)
        self.assertEqual(again.returncode, 3, again.stderr)
        self.assertEqual(again.stderr, "")

    def test_bootmsg_brand(self):
        path = self.make(BOOTMSG, "boot.msg")
        res = self.brand(path)
        self.assertEqual(res.returncode, 0, res.stderr)
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("\x0c \n\x18splash.lss\n"))
        self.assertIn("Welcome to AirymaxOS 0.0.3", text)
        self.assertNotIn("openEuler", text)
        self.assertEqual(self.brand(path).returncode, 3)

    def test_bootmsg_plain(self):
        path = self.make(BOOTMSG_PLAIN, "boot.msg")
        res = self.brand(path)
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), BOOTMSG_PLAIN)

    def test_usage_error(self):
        path = self.make(GRUB)
        self.assertEqual(self.run_tool(str(path)).returncode, 2)
        self.assertEqual(self.run_tool("--product").returncode, 2)
        self.assertEqual(self.run_tool("--bogus", str(path)).returncode, 2)


if __name__ == "__main__":
    unittest.main()
