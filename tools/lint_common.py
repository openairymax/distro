#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# lint_common.py — 静态校验器共享类型与报告输出
#
# spec/comps/kickstart 三个校验器统一使用同一 Issue 结构与
# path:line: CODE message 输出格式，使 CI 日志可被同一套解析器消费。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Issue:
    code: str
    line: int
    msg: str


def dump(path: Path, issues: Iterable[Issue]) -> int:
    total = 0
    for issue in issues:
        print(f"{path}:{issue.line}: {issue.code} {issue.msg}")
        total += 1
    if not total:
        print(f"{path}: OK")
    return total


def report(name: str, total: int) -> int:
    if not total:
        return 0
    print(f"{name}: {total} issue(s)", file=sys.stderr)
    return 1
