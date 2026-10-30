#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# par_tests.py — 并行执行 tools/tests 下的规则回归用例
#
# 串行跑完 626 条用例要四分多钟，而其中没有任何一个模块超过二十三秒：
# 时间花在等子进程与轮询上，不在 CPU。逐个模块起一个解释器、按核数并行，
# 覆盖集合、断言与退出码语义完全不变，墙钟降到最慢模块的量级。静态门禁
# 是镜像流水线里唯一排在组装之前的步骤，它的耗时直接加在每一轮上。
#
# 并行安全的前提是模块之间不共享状态：每个模块在自己的临时目录里建仓、
# 起本地 HTTP 服务（端口由内核分配）、跑被测脚本，没有固定端口、固定
# 路径或跨模块全局变量。失败模块的输出原样转出，避免并行后只剩一行
# 汇总而无从定位。
#
# 用法: par_tests.py [--jobs N]
# 退出码: 0 全部通过；1 有用例失败；5 参数或用例目录不满足。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import argparse
import concurrent.futures as futures
import os
import re
import subprocess
import sys
from pathlib import Path

EINVAL = 5
CAP = 4
ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tools" / "tests"
RAN = re.compile(r"^Ran (\d+) tests?", re.M)


def mods() -> list[str]:
    return sorted(path.stem for path in TESTS.glob("test_*.py"))


def run_one(mod: str) -> tuple[str, int, str]:
    # 逐个模块仍走 discover：tools/tests 没有 __init__.py，模块是以顶层名
    # 导入的（与串行时的收集口径一致），写成 tools.tests.<mod> 会 ImportError。
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover",
         "-s", "tools/tests", "-p", f"{mod}.py"],
        cwd=str(ROOT), capture_output=True, text=True)
    return mod, proc.returncode, proc.stdout + proc.stderr


def count(text: str) -> int:
    found = RAN.search(text)
    return int(found.group(1)) if found else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=0)
    args = parser.parse_args()

    if not TESTS.is_dir():
        print(f"用例目录不存在: {TESTS}", file=sys.stderr)
        return EINVAL
    names = mods()
    if not names:
        print(f"用例目录为空: {TESTS}", file=sys.stderr)
        return EINVAL
    jobs = args.jobs or min(CAP, os.cpu_count() or 1)
    if jobs < 1:
        print("--jobs 必须为正整数", file=sys.stderr)
        return EINVAL

    # 并行度不得超过模块数：空 worker 会让池白起解释器，也让「本轮几个
    # worker」这类观察值失去意义。
    jobs = min(jobs, len(names))
    with futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(run_one, names))

    failed = [(mod, out) for mod, code, out in results if code != 0]
    for mod, out in failed:
        print(f"== FAIL {mod} ==", file=sys.stderr)
        print(out, file=sys.stderr)
    total = sum(count(out) for _mod, _code, out in results)
    print(f"Ran {total} tests across {len(names)} modules "
          f"(jobs={jobs}), failures={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
