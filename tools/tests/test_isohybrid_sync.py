#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_isohybrid_sync.py — tools/isohybrid_sync.py 三元一致性回归测试
#
# 用最小合成镜像覆盖判定与修复：镜像自带 El Torito 引导目录、MBR 0xEF
# 分区项与 GPT 表，按真实 isohybrid 布局排布（引导记录在 LBA 17，目录在
# LBA 18，EFI 镜像条目在 platform 0xEF 段内）。每个用例只破坏一个前提，
# 修复后必须能重新读出合法 GPT 头 CRC。无 El Torito 记录的镜像按「不适用」
# 退出 77，使 build-iso 的伪 ISO 沙箱用例不受本门禁影响。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "isohybrid_sync.py"
BLK = 2048
SECT = 512
UEFI_LBA = 24
UEFI_LEN = 8
GPT_ESZ = 128
GPT_NUM = 4


def crc32(buf):
    return zlib.crc32(buf) & 0xFFFFFFFF


def gpt_entry(first, last, name):
    rec = bytearray(GPT_ESZ)
    rec[0:16] = bytes(range(16))
    struct.pack_into("<QQ", rec, 32, first, last)
    enc = name.encode("utf-16-le")
    rec[56:56 + len(enc)] = enc
    return bytes(rec)


def gpt_head(table):
    head = bytearray(92)
    head[0:8] = b"EFI PART"
    struct.pack_into("<I", head, 8, 0x00010000)
    struct.pack_into("<Q", head, 72, 2)
    struct.pack_into("<I", head, 80, GPT_NUM)
    struct.pack_into("<I", head, 84, GPT_ESZ)
    struct.pack_into("<I", head, 88, crc32(table))
    struct.pack_into("<I", head, 16, crc32(bytes(head)))
    return bytes(head)


def torito(lba):
    br = bytearray(BLK)
    br[0:7] = b"\x00CD001\x01"
    br[7:39] = b"EL TORITO SPECIFICATION"
    struct.pack_into("<I", br, 71, 18)
    cat = bytearray(BLK)
    cat[0] = 1
    cat[32] = 0x88
    struct.pack_into("<H", cat, 38, 4)
    struct.pack_into("<I", cat, 40, 20)
    cat[64] = 0x91
    cat[65] = 0xEF
    struct.pack_into("<H", cat, 66, 1)
    cat[96] = 0x88
    struct.pack_into("<H", cat, 102, UEFI_LEN)
    struct.pack_into("<I", cat, 104, lba)
    return bytes(br), bytes(cat)


def image(lba=UEFI_LBA, mbr=(UEFI_LBA * 4, UEFI_LEN), gpt=None):
    first, last = gpt or (mbr[0], mbr[0] + mbr[1] - 1)
    table = gpt_entry(0, 0, "ISOHybrid")
    table += gpt_entry(first, last, "ISOHybrid1")
    table += b"\0" * (GPT_ESZ * (GPT_NUM - 2))
    raw = bytearray(b"\0" * (20 * BLK))
    raw[446 + 16 + 4] = 0xEF
    struct.pack_into("<II", raw, 446 + 16 + 8, *mbr)
    raw[SECT:SECT + 92] = gpt_head(table)
    raw[2 * SECT:2 * SECT + len(table)] = table
    br, cat = torito(lba)
    raw[17 * BLK:18 * BLK] = br
    raw[18 * BLK:19 * BLK] = cat
    return bytes(raw)


class IsohybridTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, **kw):
        path = self.dir / "media.iso"
        path.write_bytes(image(**kw))
        return path

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args],
                              text=True, capture_output=True)

    def test_aligned_passes(self):
        res = self.run_tool("--check", str(self.make()))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("status: ok", res.stdout)

    def test_mismatch_detected(self):
        res = self.run_tool("--check", str(self.make(lba=23)))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("status: mismatch", res.stdout)

    def test_sync_repairs(self):
        path = self.make(lba=23)
        res = self.run_tool("--sync", str(path))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        raw = path.read_bytes()
        self.assertEqual(struct.unpack_from("<I", raw, 446 + 16 + 8)[0], 92)
        head = raw[SECT:SECT + 92]
        ent_lba, num, esz = struct.unpack_from("<QII", head, 72)
        table = raw[ent_lba * SECT:ent_lba * SECT + num * esz]
        self.assertEqual(struct.unpack_from("<I", head, 88)[0], crc32(table))
        self.assertEqual(struct.unpack_from("<I", head, 16)[0],
                         crc32(bytes(head[:16]) + b"\0\0\0\0" + head[20:]))
        first, last = struct.unpack_from("<QQ", table, esz + 32)
        self.assertEqual((first, last), (92, 99))

    def test_gpt_size_mismatch(self):
        path = self.make(gpt=(UEFI_LBA * 4, UEFI_LBA * 4 + UEFI_LEN))
        res = self.run_tool("--check", str(path))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)

    def test_plain_iso_skipped(self):
        path = self.dir / "plain.iso"
        path.write_bytes(b"\0" * (20 * BLK))
        res = self.run_tool("--check", str(path))
        self.assertEqual(res.returncode, 77, res.stdout + res.stderr)

    def test_usage_error(self):
        res = self.run_tool("--check")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
