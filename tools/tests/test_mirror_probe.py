#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_mirror_probe.py — 闭包镜像根探测契约
#
# 探测决定闭包收割先试哪个根。它只在两点上提供价值：能把快的根排在前面，
# 以及在全部根都不达标时仍给出一个可用的根（宁可比预期慢，也不猜地址）。
# 二者都用本地 HTTP 服务验证，不依赖任何公网镜像。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import http.server
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import mirror_probe  # noqa: E402

SCRIPT = TOOLS / "mirror_probe.py"
PYTHON = sys.executable


class _Quiet(http.server.SimpleHTTPRequestHandler):
    """静态服务，但把访问日志咽掉：测试输出只留结论。"""

    def log_message(self, *args):
        return

    def log_error(self, *args):
        return


def serve(root):
    """在后台线程起一个只读静态服务，返回 (baseurl, 关闭函数)。"""

    def handler(*args, **kwargs):
        return _Quiet(*args, directory=str(root), **kwargs)

    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def stop():
        httpd.shutdown()
        httpd.server_close()

    return "http://127.0.0.1:%d" % httpd.server_address[1], stop


def stage(root, payload=0):
    """写一个 update 仓库的元数据目录；payload=0 表示不写主索引（不可用根）。"""
    meta = Path(root) / "update" / "x86_64" / "repodata"
    meta.mkdir(parents=True, exist_ok=True)
    if not payload:
        return
    (meta / "h-primary.xml.gz").write_bytes(b"x" * payload)
    (meta / "repomd.xml").write_text(
        '<repomd><data type="primary"><location href='
        '"repodata/h-primary.xml.gz"/></data></repomd>', encoding="utf-8")


class MirrorProbeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def cli(self, *args):
        return subprocess.run([PYTHON, str(SCRIPT), *args],
                              text=True, capture_output=True)

    def test_rank_prefers_fastest(self):
        rows = [(10, "slow"), (900, "fast"), (400, "mid")]
        self.assertEqual(mirror_probe.rank(rows, 256),
                         [(900, "fast"), (400, "mid")])

    def test_rank_keeps_fastest_when_none_pass(self):
        rows = [(10, "slow"), (30, "less-slow")]
        self.assertEqual(mirror_probe.rank(rows, 256), [(30, "less-slow")])

    def test_usage_errors(self):
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(self.cli("--bogus", "http://x/y").returncode, 2)
        self.assertEqual(self.cli("--timeout").returncode, 2)
        self.assertEqual(self.cli("--floor", "abc", "http://x/y").returncode, 2)

    def test_help(self):
        res = self.cli("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("mirror_probe.py", res.stdout)

    def test_orders_by_measured_speed(self):
        stage(self.root / "a", payload=1 << 18)
        (self.root / "b").mkdir()
        base, stop = serve(self.root)
        self.addCleanup(stop)
        fast, dead = base + "/a", base + "/b"
        res = self.cli("--timeout", "5", "--span", "65536", "--floor", "1",
                       dead, fast)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.split(), [fast])
        self.assertIn(dead, res.stderr)

    def test_all_below_floor_still_picks_one(self):
        stage(self.root / "a", payload=1 << 18)
        (self.root / "b").mkdir()
        base, stop = serve(self.root)
        self.addCleanup(stop)
        res = self.cli("--timeout", "5", "--span", "65536",
                       "--floor", "1048576", base + "/b", base + "/a")
        self.assertEqual(res.returncode, 3)
        self.assertEqual(res.stdout.split(), [base + "/a"])


if __name__ == "__main__":
    unittest.main()
