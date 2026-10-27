#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_airy_flash.py — 烧录工具（airy-flash.sh）行为回归
#
# 烧录是整条交付链上唯一不可撤销的动作，因此每条拒绝都必须有测试：
# 分区、已挂载、系统盘、非 USB、容量不足、非交互未确认、非 root。
# 块层内省经伪 lsblk/blockdev/findmnt 注入，写入目标用普通文件承载，
# 而 dd/head/sha256sum 全走真实 I/O —— 回读比对是真读真比，
# 不是对桩返回值的断言。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import fakes

BASE = Path(__file__).resolve().parents[2]
TOOL = BASE / "tools" / "airy-flash" / "airy-flash.sh"
BASH = "/bin/bash"
SECTOR = 2048
GIB = 1024 ** 3


class FlashTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fakes.link_tools(self.bin)
        fakes.flash_tools(self.bin)
        self.db = self.root / "blocks"
        self.out = self.root / "out"
        self.iso = self.root / "airymaxos.iso"
        self.write_iso(self.iso)

    def tearDown(self):
        self._tmp.cleanup()

    def write_iso(self, path, sectors=24, mbr=True, pvd=True):
        data = bytearray(sectors * SECTOR)
        if pvd:
            off = 16 * SECTOR
            data[off] = 1
            data[off + 1:off + 6] = b"CD001"
            data[off + 6] = 1
        if mbr:
            data[510:512] = b"\x55\xaa"
        path.write_bytes(bytes(data))

    def blocks(self, *rows):
        self.db.write_text("".join(f"{row}\n" for row in rows),
                           encoding="utf-8")

    def disk(self, name, size=8 * GIB, rm=0, tran="sata", mounts="",
             model="FAKE DISK"):
        return (f"{self.root}/{name}|disk|{size}|{rm}|{tran}||"
                f"{model}|{mounts}")

    def dev(self, name):
        path = self.root / name
        path.write_bytes(b"")
        return path

    def run_tool(self, *args, uid=0, root=None):
        env = {
            "PATH": str(self.bin),
            "HOME": str(self.root),
            "FAKE_LSBLK_DB": str(self.db),
            "FAKE_FINDMNT_ROOT": root or str(self.root / "sda1"),
            "FAKE_UID": str(uid),
        }
        return subprocess.run([BASH, str(TOOL), *args], env=env, text=True,
                              stdin=subprocess.DEVNULL, capture_output=True)

    def plan_rows(self, stdout):
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        rows = []
        for pos, line in enumerate(lines):
            if not line.lstrip().startswith("#"):
                continue
            tail = lines[pos + 1].split()
            rows.append((line.split()[1], tail[0], " ".join(tail[1:])))
        return rows

    def record(self):
        recs = sorted(self.out.glob("flash-*.txt"))
        self.assertEqual(len(recs), 1, recs)
        body = recs[0].read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in body.splitlines()
                    if "=" in line)

    def test_syntax(self):
        res = subprocess.run([BASH, "-n", str(TOOL)], text=True,
                             capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_check_accepts_hybrid_image(self):
        res = self.run_tool("check", "--iso", str(self.iso))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("CD001", res.stdout)
        self.assertIn("55AA", res.stdout)
        self.assertIn(hashlib.sha256(self.iso.read_bytes()).hexdigest(),
                      res.stdout)
        self.assertIn("未提供", res.stdout)

    def test_check_rejects_missing_pvd(self):
        self.write_iso(self.iso, pvd=False)
        res = self.run_tool("check", "--iso", str(self.iso))
        self.assertEqual(res.returncode, 4)
        self.assertIn("CD001", res.stderr)

    def test_check_rejects_missing_mbr(self):
        self.write_iso(self.iso, mbr=False)
        res = self.run_tool("check", "--iso", str(self.iso))
        self.assertEqual(res.returncode, 4)
        self.assertIn("55AA", res.stderr)

    def test_check_rejects_truncated_image(self):
        self.iso.write_bytes(b"\x01CD001")
        res = self.run_tool("check", "--iso", str(self.iso))
        self.assertEqual(res.returncode, 4)
        self.assertIn("最小结构", res.stderr)

    def test_check_rejects_expect_mismatch(self):
        res = self.run_tool("check", "--iso", str(self.iso),
                            "--expect", "0" * 64)
        self.assertEqual(res.returncode, 4)
        self.assertIn("摘要不符", res.stderr)

    def test_check_reads_sidecar_digest(self):
        digest = hashlib.sha256(self.iso.read_bytes()).hexdigest()
        side = self.iso.with_name(self.iso.name + ".sha256")
        side.write_text(f"{digest}  {self.iso.name}\n", encoding="utf-8")
        res = self.run_tool("check", "--iso", str(self.iso))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"{digest} (from", res.stdout)
        self.assertIn("(matched)", res.stdout)

    def test_check_requires_iso(self):
        res = self.run_tool("check")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--iso 必填", res.stderr)

    def test_unknown_subcommand(self):
        res = self.run_tool("burn")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--help", res.stderr)

    def test_plan_classifies_every_disk(self):
        sysdisk = self.disk("sda")
        stick = self.disk("sdb", rm=1, tran="usb")
        busy = self.disk("sdc", mounts="/media/airymax data")
        fixed = self.disk("sdd")
        self.blocks(sysdisk, stick, busy, fixed)
        res = self.run_tool("plan")
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = {path: (kind, note) for path, kind, note in
                self.plan_rows(res.stdout)}
        self.assertEqual(len(rows), 4, res.stdout)
        self.assertEqual(rows[str(self.root / "sda")][0], "refused")
        self.assertIn("系统盘", rows[str(self.root / "sda")][1])
        self.assertEqual(rows[str(self.root / "sdb")][0], "ready")
        self.assertEqual(rows[str(self.root / "sdc")][0], "refused")
        self.assertIn("/media/airymax data", rows[str(self.root / "sdc")][1])
        self.assertEqual(rows[str(self.root / "sdd")][0], "fixed")

    def test_plan_skips_partitions(self):
        part = (f"{self.root}/sdb1|part|{GIB}|1|usb|||")
        self.blocks(self.disk("sdb", rm=1, tran="usb"), part)
        res = self.run_tool("plan")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([p for p, _, _ in self.plan_rows(res.stdout)],
                         [str(self.root / "sdb")])

    def test_write_writes_and_records(self):
        target = self.dev("sdb")
        self.blocks(self.disk("sdb", rm=1, tran="usb"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--yes",
                            "--out", str(self.out))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(target.read_bytes(), self.iso.read_bytes())
        rec = self.record()
        self.assertEqual(rec["result"], "pass")
        self.assertEqual(rec["verify"], "pass")
        self.assertEqual(rec["image_sha256"],
                         hashlib.sha256(self.iso.read_bytes()).hexdigest())
        self.assertEqual(rec["target_removable"], "yes")
        self.assertIn("airy-flash: pass", res.stdout)

    def test_write_needs_object_confirmation(self):
        target = self.dev("sdb")
        self.blocks(self.disk("sdb", rm=1, tran="usb"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--out", str(self.out))
        self.assertEqual(res.returncode, 3)
        self.assertIn("--yes", res.stderr)
        self.assertEqual(target.read_bytes(), b"")

    def test_write_needs_root_after_confirmation(self):
        target = self.dev("sdb")
        self.blocks(self.disk("sdb", rm=1, tran="usb"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--yes",
                            "--out", str(self.out), uid=1000)
        self.assertEqual(res.returncode, 5)
        self.assertIn("root", res.stderr)
        self.assertEqual(target.read_bytes(), b"")

    def test_dry_run_needs_no_root(self):
        target = self.dev("sdb")
        self.blocks(self.disk("sdb", rm=1, tran="usb"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--dry-run",
                            "--out", str(self.out), uid=1000)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("未写入", res.stdout)
        self.assertEqual(target.read_bytes(), b"")
        self.assertFalse(self.out.exists())

    def test_write_refuses_partition(self):
        part = self.dev("sdb1")
        self.blocks(f"{part}|part|{8 * GIB}|1|usb|||")
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(part), "--yes", uid=0)
        self.assertEqual(res.returncode, 3)
        self.assertIn("分区不可写", res.stderr)

    def test_write_refuses_mounted_target(self):
        target = self.dev("sdb")
        self.blocks(self.disk("sdb", rm=1, tran="usb", mounts="/run/media/u"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--yes")
        self.assertEqual(res.returncode, 3)
        self.assertIn("已挂载", res.stderr)
        self.assertEqual(target.read_bytes(), b"")

    def test_write_refuses_system_disk(self):
        target = self.dev("sda")
        self.blocks(self.disk("sda"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--yes")
        self.assertEqual(res.returncode, 3)
        self.assertIn("系统盘", res.stderr)
        self.assertEqual(target.read_bytes(), b"")

    def test_write_refuses_fixed_without_flag(self):
        target = self.dev("sdd")
        self.blocks(self.disk("sdd"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--yes")
        self.assertEqual(res.returncode, 3)
        self.assertIn("--allow-fixed", res.stderr)
        self.assertEqual(target.read_bytes(), b"")

    def test_write_allows_fixed_with_flag(self):
        target = self.dev("sdd")
        self.blocks(self.disk("sdd"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--yes",
                            "--allow-fixed", "--out", str(self.out))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(target.read_bytes(), self.iso.read_bytes())
        self.assertEqual(self.record()["target_removable"], "no")

    def test_write_refuses_small_target(self):
        target = self.dev("sdb")
        self.blocks(self.disk("sdb", size=4096, rm=1, tran="usb"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--yes")
        self.assertEqual(res.returncode, 3)
        self.assertIn("小于镜像", res.stderr)
        self.assertEqual(target.read_bytes(), b"")

    def test_write_rejects_outside_source_tree_guard(self):
        target = self.dev("sdb")
        self.blocks(self.disk("sdb", rm=1, tran="usb"))
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--yes",
                            "--out", str(BASE / "dist-out"))
        self.assertEqual(res.returncode, 5)
        self.assertIn("源码区", res.stderr)
        self.assertFalse((BASE / "dist-out").exists())

    def test_write_reports_readback_mismatch(self):
        # 介质写入成功不等于介质可用：劣质 U 盘会吞掉写缓存。
        # 用不落数据的伪 dd 复刻该场景，验证回读失败时仍落取证记录。
        target = self.dev("sdb")
        self.blocks(self.disk("sdb", rm=1, tran="usb"))
        fakes.write(self.bin, "dd", fakes.DD_SWALLOW)
        res = self.run_tool("write", "--iso", str(self.iso),
                            "--target", str(target), "--yes",
                            "--out", str(self.out))
        self.assertEqual(res.returncode, 4, res.stdout + res.stderr)
        self.assertIn("回读摘要与镜像不符", res.stderr)
        self.assertEqual(self.record()["result"], "fail")

    def test_verify_passes_on_written_media(self):
        target = self.dev("sdb")
        target.write_bytes(self.iso.read_bytes())
        self.blocks(self.disk("sdb", rm=1, tran="usb"))
        res = self.run_tool("verify", "--iso", str(self.iso),
                            "--target", str(target))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("回读摘要与镜像一致", res.stdout)

    def test_verify_detects_corruption(self):
        target = self.dev("sdb")
        body = bytearray(self.iso.read_bytes())
        body[4096] ^= 0xff
        target.write_bytes(bytes(body))
        self.blocks(self.disk("sdb", rm=1, tran="usb"))
        res = self.run_tool("verify", "--iso", str(self.iso),
                            "--target", str(target))
        self.assertEqual(res.returncode, 4)
        self.assertIn("回读摘要与镜像不符", res.stderr)

    def test_verify_requires_target(self):
        res = self.run_tool("verify", "--iso", str(self.iso))
        self.assertEqual(res.returncode, 2)
        self.assertIn("--target", res.stderr)


if __name__ == "__main__":
    unittest.main()
