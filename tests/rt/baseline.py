#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# baseline.py — 实时性基线产出与回归比较
#
# 单次延迟测量只能回答「此刻达标吗」，回答不了「比上一版更差吗」。0.0.4
# 的验收口径是「本轮结果不劣于基线 ×1.2」，这要求两个动作分离：先在目标
# 机上把基线记下来，再在每次回归时用同一口径的数字比较。
#
# 测量本身不在这里重写。记录时调用 ci/gates/rt-accept.sh，比较时只读两份
# JSON。两处若各自实现一遍 cyclictest 参数与阈值，口径必然漂移，回归判定
# 就会变成「换了个脚本就变绿」。
#
# 可比性优先于结论：内核版本或能力等级不同的两份数据不是同一个被测对象，
# 此时给出 incomparable 与退出码 3，而不是把差异算成性能回归或改进。
#
# 用法：
#   baseline.py record [--out FILE] [--rounds N] [--duration S]
#   baseline.py check --baseline FILE [--current FILE] [--percent 120]
#
# 两个子命令的 stdout 都是一行 JSON，便于归档与批量比对。
# 退出码：0 通过；1 不通过或测量失败；2 用法错误；3 不可比。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = 1
EINVAL = 2
ENOCMP = 3
GATE = Path(__file__).resolve().parents[2] / "ci" / "gates" / "rt-accept.sh"


class Probe(Exception):
    """测量没有产出可用数字；与「测量结果不好」是两件事。"""


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError:
        return ""


def identity(proc: str, root: str) -> tuple[str, str]:
    """返回 (内核版本, 整机型号)；读不到时留空，由比较端判为不可比。"""
    kernel = _text(Path(proc) / "sys/kernel/osrelease")
    machine = _text(Path(root) / "devices/virtual/dmi/id/product_name")
    return kernel, machine


def _last_json(text: str) -> dict | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            found = json.loads(line)
        except json.JSONDecodeError:
            return None
        return found if isinstance(found, dict) else None
    return None


def run_gate(gate: str, duration: int) -> dict:
    proc = subprocess.run([gate, "--json", "--duration", str(duration)],
                          capture_output=True, text=True)
    found = _last_json(proc.stdout)
    if found is None:
        raise Probe(proc.stderr.strip() or proc.stdout.strip() or "无输出")
    if "max_us" not in found:
        raise Probe(str(found.get("reason", "门禁未给出最大延迟")))
    return found


def record(gate: str, duration: int, rounds: int,
           proc: str, root: str) -> dict:
    runs = [run_gate(gate, duration) for _ in range(rounds)]
    kernel, machine = identity(proc, root)
    return {
        "schema": SCHEMA,
        "recorded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kernel": kernel,
        "machine": machine,
        "grade": runs[-1].get("grade", ""),
        "duration_s": duration,
        "rounds": [{"max_us": int(item["max_us"]),
                    "limit_us": int(item.get("limit_us", 0)),
                    "verdict": item.get("verdict", "")} for item in runs],
        "max_us": max(int(item["max_us"]) for item in runs),
        "limit_us": int(runs[-1].get("limit_us", 0)),
    }


def _same(base: dict, cur: dict) -> str:
    if not base.get("kernel"):
        return "基线缺少 kernel 字段，无法确认被测对象"
    if not base.get("grade"):
        return "基线缺少 grade 字段，无法确认判定档位"
    if base["kernel"] != cur.get("kernel", ""):
        return "内核从 %s 变为 %s" % (base["kernel"], cur.get("kernel") or "未知")
    if base["grade"] != cur.get("grade", ""):
        return "等级从 %s 变为 %s" % (base["grade"], cur.get("grade") or "未知")
    return ""


def compare(base: dict, cur: dict, percent: int) -> dict:
    why = _same(base, cur)
    if why:
        return {"verdict": "incomparable", "reason": why}
    limit = int(base["max_us"]) * percent // 100
    now = int(cur["max_us"])
    return {
        "verdict": "pass" if now <= limit else "fail",
        "kernel": base["kernel"],
        "grade": base["grade"],
        "baseline_us": int(base["max_us"]),
        "current_us": now,
        "limit_us": limit,
        "percent": percent,
    }


def _load(path: str) -> dict | None:
    try:
        found = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return found if isinstance(found, dict) else None


def _record(args: argparse.Namespace) -> int:
    found = record(args.gate, args.duration, args.rounds,
                   args.proc, args.sys)
    text = json.dumps(found, ensure_ascii=False, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    bad = [r for r in found["rounds"] if r["verdict"] != "pass"]
    if not bad:
        return 0
    print("rt-baseline: %d/%d 轮未达门禁，数据已记录但不可作为合格基线"
          % (len(bad), len(found["rounds"])), file=sys.stderr)
    return 1


def _current(args: argparse.Namespace) -> dict | None:
    if args.current:
        return _load(args.current)
    return record(args.gate, args.duration, 1, args.proc, args.sys)


def _check(args: argparse.Namespace) -> int:
    base = _load(args.baseline)
    if base is None:
        print("rt-baseline: 基线不可读或不是 JSON: %s" % args.baseline,
              file=sys.stderr)
        return EINVAL
    cur = _current(args)
    if cur is None:
        print("rt-baseline: 当前数据不可读或不是 JSON: %s" % args.current,
              file=sys.stderr)
        return EINVAL
    found = compare(base, cur, args.percent)
    print(json.dumps(found, ensure_ascii=False, sort_keys=True))
    if found["verdict"] == "pass":
        return 0
    return ENOCMP if found["verdict"] == "incomparable" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="baseline.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("record", "check"):
        one = sub.add_parser(name)
        one.add_argument("--gate", default=str(GATE))
        one.add_argument("--proc", default="/proc")
        one.add_argument("--sys", default="/sys")
        one.add_argument("--duration", type=int, default=30)
    rec = sub.choices["record"]
    rec.add_argument("--out", default="")
    rec.add_argument("--rounds", type=int, default=3)
    chk = sub.choices["check"]
    chk.add_argument("--baseline", required=True)
    chk.add_argument("--current", default="")
    chk.add_argument("--percent", type=int, default=120)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    rounds = getattr(args, "rounds", 1)
    percent = getattr(args, "percent", 100)
    if min(rounds, args.duration, percent) < 1:
        print("rounds/duration/percent 必须为正整数", file=sys.stderr)
        return EINVAL
    try:
        return _record(args) if args.cmd == "record" else _check(args)
    except Probe as err:
        print("rt-baseline: %s" % err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
