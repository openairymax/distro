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
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "payload_cache.sh"
BASH = shutil.which("bash") or "/bin/bash"


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

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return hashlib.sha256(body).hexdigest()

    def lock_line(self, sum_, base, nev="pkg-1-1.x86_64"):
        return "%s  %s  %s\n" % (sum_, base, nev)

    def run_lib(self, body, *args):
        script = '. "$1"; shift; ' + body
        argv = [BASH, "-c", script, "bash", str(LIB)] + [str(a) for a in args]
        return subprocess.run(argv, capture_output=True, text=True,
                              check=False)

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


if __name__ == "__main__":
    unittest.main()
