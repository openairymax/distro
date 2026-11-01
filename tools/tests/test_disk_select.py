#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_disk_select.py — 安装期选盘器的行为回归测试
#
# 选盘器决定装到哪块盘、怎么分区，装错一块就是不可引导的机器（D-33）。
# 用例以 PATH 沙箱里的伪 lsblk/findmnt 复刻块层输出面，固件根、介质挂载点
# 与容量注入点全部经环境给出，因此每条判定都能在没有 root、没有真实
# 磁盘的机器上被驱动。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import fakes

LIB = Path(__file__).resolve().parents[2] / "kickstart" / "disk-select.sh"
BASH = shutil.which("bash") or "/bin/bash"
GIB = 1024 ** 3

NVME = ("/dev/nvme0n1", "disk", 1000204886016, 0, "nvme", "S1", "M1", "")
SATA = ("/dev/sda", "disk", 500107862016, 0, "sata", "S2", "M2", "")
USB = ("/dev/sdb", "disk", 2000398934016, 1, "usb", "S3", "M3", "")
MED = ("/dev/sdc", "disk", 16000000000, 0, "", "S4", "M4", "")
MED_P1 = ("/dev/sdc1", "part", 15900000000, 0, "", "", "",
          "/run/install/repo")


class DiskSelectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fakes.link_tools(self.bin)
        fakes.flash_tools(self.bin)
        self.db = self.root / "block"
        self.fw = self.root / "fw"
        self.work = self.root / "work"
        self.work.mkdir()
        self.env = {"PATH": str(self.bin), "HOME": str(self.root),
                    "AIRY_FW": str(self.fw), "FAKE_LSBLK_DB": str(self.db)}

    def tearDown(self):
        self._tmp.cleanup()

    def table(self, *rows):
        self.db.write_text("".join("|".join(str(x) for x in row) + "\n"
                                   for row in rows), encoding="utf-8")

    def sh(self, snippet, **extra):
        env = dict(self.env)
        env.update({key: str(val) for key, val in extra.items()})
        return subprocess.run([BASH, "-c", 'set -eu\n. "$1"\n' + snippet,
                               "bash", str(LIB)], env=env, text=True,
                              capture_output=True)

    def test_scan_single(self):
        self.table(NVME)
        res = self.sh("airy_scan")
        self.assertEqual(res.stdout.strip(),
                         "/dev/nvme0n1 1000204886016 nvme")

    def test_scan_largest_first(self):
        self.table(SATA, NVME)
        lines = self.sh("airy_scan").stdout.splitlines()
        self.assertEqual(lines[0].split()[0], "/dev/nvme0n1")

    def test_scan_skips_usb(self):
        self.table(USB, SATA)
        self.assertEqual(self.sh("airy_scan").stdout.split()[0], "/dev/sda")

    def test_scan_skips_partition(self):
        self.table(MED, MED_P1)
        self.assertEqual(self.sh("airy_scan").stdout.split()[0],
                         "/dev/sdc")

    def test_scan_skips_medium(self):
        self.table(MED, MED_P1, SATA)
        self.assertNotIn("/dev/sdc", self.sh("airy_scan sdc").stdout)
        self.assertIn("/dev/sdc", self.sh("airy_scan").stdout)

    def test_medium_from_mount(self):
        self.table(MED, MED_P1)
        res = self.sh("airy_medium", FAKE_FINDMNT_ROOT="/dev/sdc1")
        self.assertEqual(res.stdout.strip(), "sdc")

    def test_medium_unknown(self):
        self.table(MED)
        self.assertEqual(self.sh("airy_medium").stdout.strip(), "")

    def test_firmware_uefi(self):
        (self.fw / "efi").mkdir(parents=True)
        self.assertEqual(self.sh("airy_fw").stdout.strip(), "uefi")

    def test_firmware_bios(self):
        self.assertEqual(self.sh("airy_fw").stdout.strip(), "bios")

    def test_pick_skips_busy(self):
        """双系统：更大的盘已有分区，系统盘落在空盘上。"""
        self.table(NVME, ("/dev/nvme0n1p1", "part", 200 * GIB, 0, "", "", "",
                          ""), SATA)
        self.assertEqual(self.sh("airy_pick").stdout.split()[0], "/dev/sda")

    def test_pick_fallback_busy(self):
        """全部盘都被占用时退回容量最大者，重装本系统仍可进行。"""
        self.table(NVME, ("/dev/nvme0n1p1", "part", 100 * GIB, 0, "", "", "",
                          ""))
        self.assertEqual(self.sh("airy_pick").stdout.split()[0],
                         "/dev/nvme0n1")

    def test_pre_dual_boot_keeps_windows(self):
        """双系统只清空盘：既有系统盘不得出现在任何清除指令里。"""
        self.table(NVME, ("/dev/nvme0n1p1", "part", 200 * GIB, 0, "", "", "",
                          ""), SATA)
        res, ks, rec = self.pre()
        self.assertEqual(res.returncode, 0, res.stderr)
        body = ks.read_text(encoding="utf-8")
        self.assertIn("ignoredisk --only-use=sda\n", body)
        self.assertNotIn("nvme0n1", body)
        record = json.loads(rec.read_text(encoding="utf-8"))
        self.assertEqual(record["disk"], "sda")
        self.assertEqual(record["layout"], "single")

    def test_layout_uefi_single(self):
        out = self.sh("airy_layout nvme0n1 '' uefi %d" % (100 * GIB)).stdout
        self.assertNotIn("biosboot", out)
        self.assertIn("ignoredisk --only-use=nvme0n1\n", out)
        self.assertIn("clearpart --all --initlabel --disklabel=gpt "
                      "--drives=nvme0n1\n", out)
        self.assertIn("part /boot/efi --fstype=efi --size=600 "
                      "--ondisk=nvme0n1\n", out)
        self.assertIn("part swap --size=8192 --ondisk=nvme0n1\n", out)
        self.assertIn("part / --fstype=ext4 --size=46291 --ondisk=nvme0n1\n",
                      out)
        self.assertIn("part /data --fstype=ext4 --size=10240 --grow "
                      "--ondisk=nvme0n1\n", out)
        self.assertNotIn("/home", out)

    def test_layout_bios_single(self):
        out = self.sh("airy_layout nvme0n1 '' bios %d" % (100 * GIB)).stdout
        self.assertIn("part biosboot --fstype=biosboot --size=1 "
                      "--ondisk=nvme0n1\n", out)

    def test_layout_dual(self):
        out = self.sh("airy_layout nvme0n1 sda uefi %d" % (100 * GIB)).stdout
        self.assertIn("ignoredisk --only-use=nvme0n1,sda\n", out)
        self.assertIn("--drives=nvme0n1,sda\n", out)
        self.assertIn("part / --fstype=ext4 --size=1 --grow "
                      "--ondisk=nvme0n1\n", out)
        self.assertIn("part /data --fstype=ext4 --size=1 --grow "
                      "--ondisk=sda\n", out)

    def test_root_mib_small(self):
        self.assertEqual(self.sh("airy_root_mib %d" % (32 * GIB)).stdout.strip(),
                         "11475")

    def test_root_mib_floor(self):
        self.assertEqual(self.sh("airy_root_mib %d" % (40 * GIB)).stdout.strip(),
                         "20480")

    def test_root_mib_large(self):
        self.assertEqual(
            self.sh("airy_root_mib %d" % (512 * GIB)).stdout.strip(),
            "257235")

    def test_busy_partition(self):
        self.table(NVME, ("/dev/nvme0n1p1", "part", 1073741824, 0, "", "", "",
                          ""))
        self.assertEqual(self.sh("airy_busy nvme0n1").returncode, 0)

    def test_busy_mounted(self):
        self.table(NVME, ("/dev/nvme0n1p2", "part", 1073741824, 0, "", "", "",
                          "/data"))
        self.assertEqual(self.sh("airy_busy nvme0n1").returncode, 0)

    def test_busy_spare(self):
        self.table(NVME, ("/dev/nvme0n1p1", "part", 1073741824, 0, "", "", "",
                          ""), SATA)
        res = self.sh("airy_busy sda")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(res.stdout.strip(), "")

    def test_data_prefers_spare(self):
        self.table(NVME, ("/dev/nvme0n1p1", "part", 1073741824, 0, "", "", "",
                          ""), SATA)
        self.assertEqual(self.sh("airy_data '' nvme0n1").stdout.strip(), "sda")

    def test_data_skips_system(self):
        self.table(NVME, SATA)
        self.assertEqual(self.sh("airy_data '' nvme0n1").stdout.strip(), "sda")

    def test_data_none(self):
        self.table(NVME)
        self.assertEqual(self.sh("airy_data '' nvme0n1").stdout.strip(), "")

    def test_record_schema(self):
        rec = self.work / "rec.json"
        self.sh(f'airy_rec "{rec}" sda 100 sata uefi dual sdb sdc')
        self.assertEqual(json.loads(rec.read_text(encoding="utf-8")),
                         {"schema": 1, "disk": "sda", "bytes": 100,
                          "bus": "sata", "firmware": "uefi",
                          "layout": "dual", "medium": "sdb", "data": "sdc"})

    def test_record_no_data(self):
        rec = self.work / "rec.json"
        self.sh(f'airy_rec "{rec}" sda 100 sata uefi single sdb')
        self.assertEqual(json.loads(rec.read_text(encoding="utf-8"))["data"],
                         "")

    def pre(self, **extra):
        ks = self.work / "disk.ks"
        rec = self.work / "disk.json"
        res = self.sh(f'airy_pre "{ks}" "{rec}"', **extra)
        return res, ks, rec

    def test_pre_single(self):
        self.table(("/dev/nvme0n1", "disk", 64 * GIB, 0, "nvme", "S1", "M1",
                    ""))
        res, ks, rec = self.pre()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("AIRYMAX-DISK-OK disk=nvme0n1 bytes=%d "
                      "bus=nvme layout=single fw=bios data=-" % (64 * GIB),
                      res.stdout)
        body = ks.read_text(encoding="utf-8")
        self.assertIn("part /data --fstype=ext4 --size=10240 --grow "
                      "--ondisk=nvme0n1\n", body)
        self.assertEqual(json.loads(rec.read_text(encoding="utf-8")),
                         {"schema": 1, "disk": "nvme0n1",
                          "bytes": 64 * GIB, "bus": "nvme",
                          "firmware": "bios", "layout": "single",
                          "medium": "", "data": ""})

    def test_pre_dual(self):
        self.table(NVME, SATA)
        res, ks, rec = self.pre()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("layout=dual", res.stdout)
        self.assertIn("data=sda", res.stdout)
        self.assertIn("part /data --fstype=ext4 --size=1 --grow "
                      "--ondisk=sda\n", ks.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(rec.read_text(encoding="utf-8"))["data"],
                         "sda")

    def test_pre_skips_medium(self):
        self.table(MED, MED_P1, SATA)
        res, _, rec = self.pre(FAKE_FINDMNT_ROOT="/dev/sdc1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(rec.read_text(encoding="utf-8"))["medium"],
                         "sdc")
        self.assertIn("disk=sda", res.stdout)

    def test_pre_no_disk(self):
        self.table(USB)
        res, ks, _ = self.pre()
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-DISK-FAIL reason=no-internal-disk", res.stdout)
        self.assertFalse(ks.exists())

    def test_pre_too_small(self):
        self.table(("/dev/sda", "disk", 16 * GIB, 0, "sata", "S5", "M5", ""))
        res, ks, _ = self.pre()
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-DISK-FAIL reason=too-small", res.stdout)
        self.assertFalse(ks.exists())

    def keep(self, **extra):
        return self.sh("airy_keep", **extra)

    def target(self):
        root = self.root / "target"
        (root / "etc").mkdir(parents=True)
        return root

    def test_keep_ok(self):
        root = self.target()
        rec = self.work / "rec.json"
        rec.write_text('{"schema":1}\n', encoding="utf-8")
        res = self.keep(AIRY_REC=str(rec), INSTALL_ROOT=str(root))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("AIRYMAX-DISK-KEEP-OK", res.stdout)
        dst = root / "var/lib/airymaxos/install-disk.json"
        self.assertEqual(dst.read_text(encoding="utf-8"),
                         '{"schema":1}\n')

    def test_keep_no_root(self):
        res = self.keep()
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRYMAX-DISK-KEEP-FAIL reason=no-install-root",
                      res.stdout)

    def test_keep_bad_record(self):
        root = self.target()
        rec = self.work / "rec.json"
        rec.write_text("{}\n", encoding="utf-8")
        res = self.keep(AIRY_REC=str(rec), INSTALL_ROOT=str(root))
        self.assertEqual(res.returncode, 1)
        self.assertIn("reason=bad-record", res.stdout)

    def test_keep_write_fail(self):
        root = self.target()
        (root / "var/lib").mkdir(parents=True)
        (root / "var/lib/airymaxos").write_text("x", encoding="utf-8")
        rec = self.work / "rec.json"
        rec.write_text('{"schema":1}\n', encoding="utf-8")
        res = self.keep(AIRY_REC=str(rec), INSTALL_ROOT=str(root))
        self.assertEqual(res.returncode, 1)
        self.assertIn("reason=write", res.stdout)


if __name__ == "__main__":
    unittest.main()
