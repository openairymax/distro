# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
#
# rt-accept.sh 回归测试
#
# 门禁的价值在于「该失败时一定失败」。这里用假 airy-rt-cap 与假 cyclictest
# 覆盖五条关键路径：ready 通过、soft 超阈值失败、none 直接拒收且不做测量、
# 依赖缺失或执行出错时明确报错、以及 matrix 用退出码表达等级时不误判。
# 最后两类尤其重要：静默跳过会让整条流水线看起来通过，实际上从未验证过
# 实时性；把 soft 的退出码 3 当成执行失败，则软实时机器永远无法验收。
#
# 拒收与测量出错都退出 4（blocked），与超阈值的 1（fail）分开：前者说明
# 这台机器没有给出结论，后者说明结论是否。混成一个码就无法区分「机器不
# 具备实时能力」和「实时性回归」，而这两种情况要做的处置完全不同。

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "ci" / "gates" / "rt-accept.sh"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.base = Path(self._dir.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.mark = self.base / "cycle.called"

    def tool(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n", encoding="ascii")
        path.chmod(0o755)

    def matrix(self, payload: str, rc: int = 0) -> None:
        self.tool("airy-rt-cap", f"printf '%s\\n' '{payload}'; exit {rc}")

    def cycle(self, max_us: int | None = 42) -> None:
        if max_us is None:
            self.tool(
                "cyclictest",
                f'echo called > "{self.mark}"; echo "boom"; exit 1',
            )
            return
        line = f"T: 0 ( 1) P:90 I:200 C:1 Min: 1 Act: 2 Avg: 3 Max: {max_us}"
        self.tool(
            "cyclictest",
            f'echo called > "{self.mark}"; printf "%s\\n" "{line}"',
        )

    def lat(self, max_us: int | None = 42, payload: str = "") -> None:
        if max_us is None:
            self.tool(
                "airy-rt-lat",
                f'echo called > "{self.mark}"; echo "boom"; exit 1',
            )
            return
        line = payload or ('{"tool":"airy-rt-lat","policy":"fifo",'
                          '"max_us":%d}' % max_us)
        self.tool(
            "airy-rt-lat",
            f'echo called > "{self.mark}"; printf "%s\\n" \'{line}\'',
        )

    def gate(self, *argv: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        return subprocess.run(
            ["bash", str(GATE), *argv],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def called(self) -> bool:
        return self.mark.exists()


class ReadyTest(Base):
    def test_pass(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.cycle(42)
        done = self.gate()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("grade=ready", done.stdout)
        self.assertIn("max=42us", done.stdout)
        self.assertIn("verdict=pass", done.stdout)

    def test_over_hard_limit(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.cycle(180)
        done = self.gate()
        self.assertEqual(done.returncode, 1)
        self.assertIn("verdict=fail", done.stdout)

    def test_limit_override(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.cycle(180)
        done = self.gate("--hard-us", "200")
        self.assertEqual(done.returncode, 0, done.stderr)


class SoftTest(Base):
    def test_within_soft_limit(self) -> None:
        self.matrix('{"grade":"soft","pending":["realtime"]}', rc=3)
        self.cycle(900)
        done = self.gate()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("limit=1000us", done.stdout)

    def test_over_soft_limit(self) -> None:
        self.matrix('{"grade":"soft","pending":["realtime"]}', rc=3)
        self.cycle(1200)
        done = self.gate()
        self.assertEqual(done.returncode, 1)
        self.assertIn("verdict=fail", done.stdout)


class RejectTest(Base):
    def test_none_skips_measurement(self) -> None:
        self.matrix('{"grade":"none","pending":["budget"]}', rc=1)
        self.cycle()
        done = self.gate()
        self.assertEqual(done.returncode, 4)
        self.assertIn("不接受", done.stderr)
        self.assertFalse(self.called())

    def test_broken_matrix(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}', rc=2)
        self.cycle()
        done = self.gate()
        self.assertEqual(done.returncode, 4)
        self.assertIn("matrix 执行失败", done.stderr)
        self.assertFalse(self.called())

    def test_missing_cap(self) -> None:
        self.cycle()
        done = self.gate()
        self.assertEqual(done.returncode, 4)
        self.assertIn("airy-rt-cap", done.stderr)

    def test_missing_cyclictest(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        done = self.gate()
        self.assertEqual(done.returncode, 4)
        self.assertIn("rt-tests", done.stderr)

    def test_measurement_error(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.cycle(None)
        done = self.gate()
        self.assertEqual(done.returncode, 4)
        self.assertIn("cyclictest 执行失败", done.stderr)

    def test_bad_matrix_json(self) -> None:
        self.matrix("not json")
        self.cycle()
        done = self.gate()
        self.assertEqual(done.returncode, 4)
        self.assertIn("合法 JSON", done.stderr)

    def test_usage(self) -> None:
        done = self.gate("--bogus")
        self.assertEqual(done.returncode, 2)


class JsonTest(Base):
    def test_shape(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.cycle(42)
        done = self.gate("--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('"verdict":"pass"', done.stdout)
        self.assertIn('"max_us":42', done.stdout)

    def test_blocked_shape(self) -> None:
        self.matrix('{"grade":"none","pending":["budget"]}', rc=1)
        self.cycle()
        done = self.gate("--json")
        self.assertEqual(done.returncode, 4)
        found = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(found["verdict"], "blocked")
        self.assertIn("none", found["reason"])


class NativeTest(Base):
    def test_pass(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.lat(42)
        done = self.gate()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("tool=lat", done.stdout)
        self.assertIn("max=42us", done.stdout)

    def test_preferred_over_cyclictest(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.lat(42)
        self.cycle(900)
        done = self.gate()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("max=42us", done.stdout)

    def test_over_limit(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.lat(140)
        done = self.gate()
        self.assertEqual(done.returncode, 1)
        self.assertIn("verdict=fail", done.stdout)

    def test_measurement_error(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.lat(None)
        done = self.gate()
        self.assertEqual(done.returncode, 4)
        self.assertIn("airy-rt-lat 执行失败", done.stderr)

    def test_bad_json(self) -> None:
        self.matrix('{"grade":"ready","pending":[]}')
        self.lat(0, payload="not json")
        done = self.gate()
        self.assertEqual(done.returncode, 4)
        self.assertIn("合法 JSON", done.stderr)


if __name__ == "__main__":
    unittest.main()
