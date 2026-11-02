# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
#
# tests/rt/baseline.py 回归测试
#
# 基线工具的风险不在于数字算错，而在于把不该比较的两份数据比出结论：
# 换内核、换等级、缺标识字段都应判为不可比，而不是通过或失败。用例覆盖
# 记录（多轮取最坏、超阈值仍如实记录、测量失败即报错）与比较（边界值、
# 系数覆盖、三类不可比、数据缺失）两条路径。

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tests" / "rt" / "baseline.py"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.base = Path(self._dir.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.proc = self.base / "proc"
        self.sys = self.base / "sys"
        self.ident()
        self.values = self.base / "values"
        self.gate(self.values, '{"verdict":"pass","grade":"ready",'
                               '"max_us":%s,"limit_us":100}')

    def ident(self, kernel: str = "6.6.157-alk",
              model: str = "Airymax 285H") -> None:
        self.write(self.proc / "sys/kernel/osrelease", kernel + "\n")
        self.write(self.sys / "devices/virtual/dmi/id/product_name",
                   model + "\n")

    def write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def gate(self, values: Path, payload: str) -> None:
        values.write_text("40\n42\n38\n", encoding="ascii")
        body = (
            "#!/bin/sh\n"
            f'line=$(head -n 1 "{values}")\n'
            f'tail -n +2 "{values}" > "{values}.tmp" && '
            f'mv "{values}.tmp" "{values}"\n'
            f"printf '{payload}' \"$line\"\n"
        )
        path = self.bin / "gate"
        path.write_text(body, encoding="ascii")
        path.chmod(0o755)

    def tools(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *argv,
             "--gate", str(self.bin / "gate"),
             "--proc", str(self.proc), "--sys", str(self.sys)],
            capture_output=True, text=True, check=False)

    def record_file(self, **over: object) -> Path:
        return self.json_file("base.json", **over)

    def current_file(self, **over: object) -> Path:
        return self.json_file("now.json", **over)

    def json_file(self, name: str, **over: object) -> Path:
        data = {"schema": 1, "kernel": "6.6.157-alk",
                "machine": "Airymax 285H", "grade": "ready",
                "duration_s": 30, "rounds": [], "max_us": 40,
                "limit_us": 100}
        data.update(over)
        path = self.base / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path


class RecordTest(Base):
    def test_takes_worst_round(self) -> None:
        out = self.base / "rt.json"
        done = self.tools("record", "--rounds", "3", "--out", str(out))
        self.assertEqual(done.returncode, 0, done.stderr)
        found = json.loads(done.stdout)
        self.assertEqual(found["max_us"], 42)
        self.assertEqual(len(found["rounds"]), 3)
        self.assertEqual(found["kernel"], "6.6.157-alk")
        self.assertEqual(found["machine"], "Airymax 285H")
        self.assertEqual(json.loads(out.read_text()), found)

    def test_records_over_limit(self) -> None:
        self.values.write_text("180\n", encoding="ascii")
        body = ('#!/bin/sh\nline=$(head -n 1 "%s")\n'
                'printf \'{"verdict":"fail","grade":"ready",'
                '"max_us":%%s,"limit_us":100}\\n\' "$line"\n') % self.values
        path = self.bin / "gate"
        path.write_text(body, encoding="ascii")
        done = self.tools("record", "--rounds", "1")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["max_us"], 180)

    def test_measure_failure(self) -> None:
        body = ('#!/bin/sh\n'
                'printf \'{"verdict":"fail","reason":"no rt-tests"}\\n\'\n'
                "exit 1\n")
        path = self.bin / "gate"
        path.write_text(body, encoding="ascii")
        path.chmod(0o755)
        done = self.tools("record", "--rounds", "1")
        self.assertEqual(done.returncode, 1)
        self.assertIn("rt-tests", done.stderr)

    def test_missing_gate(self) -> None:
        done = subprocess.run(
            [sys.executable, str(TOOL), "record", "--rounds", "1",
             "--gate", str(self.base / "nope")],
            capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 1)

    def test_usage(self) -> None:
        done = self.tools("record", "--rounds", "0")
        self.assertEqual(done.returncode, 2)


class CheckTest(Base):
    def check(self, *argv: str) -> subprocess.CompletedProcess[str]:
        base = self.record_file()
        return self.tools("check", "--baseline", str(base), *argv)

    def test_pass_at_limit(self) -> None:
        now = self.current_file(max_us=48)
        done = self.check("--current", str(now))
        self.assertEqual(done.returncode, 0, done.stderr)
        found = json.loads(done.stdout)
        self.assertEqual(found["verdict"], "pass")
        self.assertEqual(found["limit_us"], 48)

    def test_fail_over_limit(self) -> None:
        now = self.current_file(max_us=49)
        done = self.check("--current", str(now))
        self.assertEqual(done.returncode, 1)
        self.assertEqual(json.loads(done.stdout)["verdict"], "fail")

    def test_percent_override(self) -> None:
        now = self.current_file(max_us=49)
        done = self.check("--current", str(now), "--percent", "130")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["limit_us"], 52)

    def test_kernel_mismatch(self) -> None:
        now = self.current_file(kernel="6.6.158-alk")
        done = self.check("--current", str(now))
        self.assertEqual(done.returncode, 3)
        self.assertEqual(json.loads(done.stdout)["verdict"], "incomparable")

    def test_grade_mismatch(self) -> None:
        now = self.current_file(grade="soft")
        done = self.check("--current", str(now))
        self.assertEqual(done.returncode, 3)

    def test_missing_identity(self) -> None:
        base = self.record_file(kernel="")
        now = self.current_file()
        done = self.tools("check", "--baseline", str(base),
                          "--current", str(now))
        self.assertEqual(done.returncode, 3)

    def test_missing_baseline(self) -> None:
        done = self.tools("check", "--baseline", str(self.base / "nope"))
        self.assertEqual(done.returncode, 2)

    def test_live_measurement(self) -> None:
        done = self.check()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["current_us"], 40)


if __name__ == "__main__":
    unittest.main()
