#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_payload_cache.py — 候选池校验/回填/漂移判定的回归测试
#
# 这三种不一致此前只有一种被处理：池与清单不符时离线重放会回落在线，但在线
# 求解仍把池里那一份当作本轮字节，损坏因此可以一路进载荷。用例把每种情形各
# 造一次，判据落在日志行、退出码与文件系统效果上——门禁读的就是这几样。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "payload_cache.sh"
BASH = shutil.which("bash") or "/bin/bash"
# 包自校验在真实构建里由 rpm -K 完成；用例只验证判据是否被调用、坏字节是否
# 被拦下，因此注入一个只认截断标记的替身，不依赖宿主装 rpm，也不依赖真包。
FAKE_RPM = """#!/bin/sh
for f in "$@"; do
    [ -f "$f" ] || continue
    grep -q TRUNC "$f" 2>/dev/null && exit 1
done
exit 0
"""


class PoolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.pool = self.root / "pool"
        self.dl = self.root / "dl"
        self.self_dir = self.root / "self"
        self.pool.mkdir()
        self.dl.mkdir()
        self.lock = self.root / "closure.lock"
        self.rpm = self.root / "fake-rpm"
        self.rpm.write_text(FAKE_RPM)
        self.rpm.chmod(0o755)

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return hashlib.sha256(body).hexdigest()

    def lock_line(self, sum_, base, nev="pkg-1-1.x86_64"):
        return "%s  %s  %s\n" % (sum_, base, nev)

    def run_lib(self, body, *args):
        script = 'CL_RPM="$FAKE_RPM"; . "$1"; shift; ' + body
        argv = [BASH, "-c", script, "bash", str(LIB)] + [str(a) for a in args]
        env = dict(os.environ, FAKE_RPM=str(self.rpm))
        return subprocess.run(argv, capture_output=True, text=True,
                              check=False, env=env)

    def test_reads_both_manifest_formats(self):
        self.lock.write_text(self.lock_line("a" * 64, "x.rpm")
                             + "rpm " + "b" * 64 + " y.rpm\n")
        res = self.run_lib(
            'pc_read "$1" && printf "%s:%s " "${PC_SUM[0]}" "${PC_BASE[1]}"',
            self.lock)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "a" * 64 + ":y.rpm ")

    def test_empty_manifest_is_unavailable(self):
        self.lock.write_text("")
        res = self.run_lib('pc_seed "$1" "$2"', self.pool, self.lock)
        self.assertEqual(res.returncode, 1)
        self.assertIn("falling back to full harvest", res.stdout)

    def test_seed_discards_polluted_entry(self):
        sum_ = self.put(self.pool / "a.rpm", b"good")
        self.put(self.pool / "b.rpm", b"corrupt")
        self.lock.write_text(self.lock_line(sum_, "a.rpm")
                             + self.lock_line("c" * 64, "b.rpm"))
        res = self.run_lib('pc_seed "$1" "$2"', self.pool, self.lock)
        self.assertEqual(res.returncode, 1)
        self.assertIn("payload cache: discard b.rpm", res.stdout)
        self.assertIn("payload cache: pool 1/2 verified", res.stdout)
        self.assertFalse((self.pool / "b.rpm").exists())
        self.assertTrue((self.pool / "a.rpm").exists())

    def test_stat_counts_identical_bytes_only(self):
        self.put(self.pool / "a.rpm", b"same")
        self.put(self.pool / "b.rpm", b"pool")
        self.put(self.dl / "a.rpm", b"same")
        self.put(self.dl / "b.rpm", b"round")
        res = self.run_lib('pc_stat "$1" "$2"', self.pool, self.dl)
        self.assertEqual(res.stdout, "payload cache: hit 1/2\n")

    def test_absorb_links_instead_of_copying(self):
        self.put(self.dl / "a.rpm", b"payload")
        self.put(self.dl / "done.rpm", b"old")
        self.put(self.pool / "done.rpm", b"old")
        res = self.run_lib('pc_absorb "$1" "$2"', self.pool, self.dl)
        self.assertIn("payload cache: absorb 1 (mode=link)", res.stdout)
        self.assertEqual((self.pool / "a.rpm").stat().st_ino,
                         (self.dl / "a.rpm").stat().st_ino)

    def test_absorb_skips_own_packages(self):
        """自建包不回填：池只缓存上游字节，本仓产物以当轮载荷为准。"""
        self.put(self.dl / "a.rpm", b"payload")
        self.put(self.dl / "airymaxos-system-0.0.4-44.noarch.rpm", b"built")
        res = self.run_lib('pc_absorb "$1" "$2" "$3"', self.pool, self.dl,
                           "airymaxos-*")
        self.assertIn("payload cache: absorb 1 (mode=link)", res.stdout)
        self.assertTrue((self.pool / "a.rpm").exists())
        self.assertFalse(
            (self.pool / "airymaxos-system-0.0.4-44.noarch.rpm").exists())

    def test_drift_fails_on_changed_bytes(self):
        self.lock.write_text(self.lock_line("d" * 64, "a.rpm"))
        self.put(self.dl / "a.rpm", b"changed")
        res = self.run_lib('pc_read "$1"; pc_drift "$1" "$2" "$3"',
                           self.lock, self.dl, self.self_dir)
        self.assertEqual(res.returncode, 1)
        self.assertIn("AIRY-PAYLOAD-DRIFT a.rpm", res.stderr)

    def test_drift_ignores_self_built(self):
        self.lock.write_text(self.lock_line("d" * 64, "a.rpm"))
        self.put(self.dl / "a.rpm", b"rebuilt")
        self.put(self.self_dir / "a.rpm", b"rebuilt")
        res = self.run_lib('pc_read "$1"; pc_drift "$1" "$2" "$3"',
                           self.lock, self.dl, self.self_dir)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_seed_drops_truncated_manifest_entry(self):
        """清单本身被污染：摘要相符仍要自校验，坏项不得留下。"""
        sum_ = self.put(self.pool / "a.rpm", b"TRUNC-partial")
        self.lock.write_text(self.lock_line(sum_, "a.rpm"))
        res = self.run_lib(
            'pc_seed "$1" "$2"; rc=$?; ' +
            'printf "left=%d\\n" "${#PC_BASE[@]}"; exit $rc',
            self.pool, self.lock)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("payload cache: discard a.rpm (digests bad)", res.stdout)
        self.assertIn("left=0", res.stdout)
        self.assertFalse((self.pool / "a.rpm").exists())

    def test_sweep_purges_unlisted_truncated_file(self):
        """失败轮次回填的包不在清单里，索引之前也必须被清扫。"""
        self.put(self.pool / "ok.rpm", b"payload")
        self.put(self.pool / "bad.rpm", b"TRUNC")
        res = self.run_lib('pc_sweep "$1"', self.pool)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("payload cache: purge bad.rpm (digests bad)", res.stdout)
        self.assertTrue((self.pool / "ok.rpm").exists())
        self.assertFalse((self.pool / "bad.rpm").exists())

    def test_absorb_skips_truncated_bytes(self):
        """被中断的下载不得以「事务通过」为由回填进池。"""
        self.put(self.dl / "ok.rpm", b"payload")
        self.put(self.dl / "cut.rpm", b"TRUNC")
        res = self.run_lib('pc_absorb "$1" "$2"', self.pool, self.dl)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("payload cache: absorb 1 (mode=link)", res.stdout)
        self.assertIn("payload cache: skip cut.rpm (digests bad)", res.stderr)
        self.assertFalse((self.pool / "cut.rpm").exists())


if __name__ == "__main__":
    unittest.main()
