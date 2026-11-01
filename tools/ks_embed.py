#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# ks_embed.py — 把共享安装脚本展开进 kickstart 的脚本段
#
# 安装期的选盘规则必须同时出现在 %pre（生成分区片段）与 %post（落盘选盘
# 记录）里。installer 运行时没有可信的仓库挂载可以 source，复制两份又会让
# 规则在两处漂移；唯一稳的做法是构建期嵌入：源配方只写一行
# 「# %airy-embed: disk-select.sh」，本工具把它换成脚本正文，写出的配方
# 仍然是一份自足的 kickstart。
#
# anaconda 只认字面指令，嵌入必须发生在脚本段内部；标记落在段外说明写错
# 了位置，anaconda 会把它当注释静默忽略，识别行为要到装机现场才暴露，
# 因此在展开与校验两条路径上都拒绝段外标记。
#
# 展开与校验读同一份段解析：lint 用 audit 报 K019，构建用 expand 出产物，
# 两者对「什么算脚本段」「哪些标记算数」只有一个口径。
#
# 退出码：0 成功；5 配方、标记或共享脚本不满足。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EINVAL = 5
MARK = "# %airy-embed: "
SCRIPTS = frozenset({"pre", "post", "onerror", "traceback"})
SHARED = frozenset({"disk-select.sh"})


class EmbedError(ValueError):
    """带行号的展开失败。"""

    def __init__(self, line: int, msg: str):
        super().__init__(msg)
        self.line = line


def segments(lines: list[str]) -> list[tuple[str, int, int]]:
    """返回脚本段 (种类, 首行, 末行) —— 末行是 %end，不含下一行。"""
    out: list[tuple[str, int, int]] = []
    kind: str | None = None
    start = 0
    for num, raw in enumerate(lines):
        word = raw.strip()
        if not word or word.startswith("#"):
            continue
        key = word.split(None, 1)[0]
        if kind is None:
            if key.startswith("%") and key[1:] in SCRIPTS:
                kind, start = key[1:], num
        elif word == "%end":
            out.append((kind, start, num))
            kind = None
    if kind is not None:
        out.append((kind, start, len(lines)))
    return out


def seg_kinds(lines: list[str]) -> dict[int, str]:
    return {num: kind for kind, first, last in segments(lines)
            for num in range(first, last)}


def body(name: str, base: Path, line: int) -> str:
    if name not in SHARED:
        raise EmbedError(line, f"未知的共享脚本: {name or '(空)'}")
    path = base / name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise EmbedError(line, f"共享脚本读取失败: {err}") from err
    if MARK in text:
        raise EmbedError(line, f"共享脚本不得再嵌入: {name}")
    return text if text.endswith("\n") else text + "\n"


def expand(text: str, base: Path) -> str:
    """把段内标记换成共享脚本正文；段外标记视为配方错误。"""
    lines = text.splitlines(keepends=True)
    kinds = seg_kinds(lines)
    out: list[str] = []
    for num, raw in enumerate(lines):
        word = raw.strip()
        if not word.startswith(MARK):
            out.append(raw)
            continue
        if num not in kinds:
            raise EmbedError(num + 1, "嵌入标记不在脚本段内")
        out.append(body(word[len(MARK):].strip(), base, num + 1))
    return "".join(out)


def audit(text: str) -> list[tuple[int, str]]:
    """静态检查嵌入标记，返回 (行号, 说明)。

    除段外标记外，还拒绝「存储片段由 %pre 生成却未嵌入选盘器」的配方：
    那正是 D-33 收尾时手抄第二份选盘规则会走回来的形态，规则一旦分叉，
    装机布局就取决于哪一份先被改。
    """
    lines = text.splitlines()
    kinds = seg_kinds(lines)
    issues: list[tuple[int, str]] = []
    for num, raw in enumerate(lines):
        if raw.strip().startswith(MARK) and num not in kinds:
            issues.append((num + 1, "嵌入标记不在脚本段内"))
    includes = [row.split(None, 1)[1].strip() for row in lines
                if row.strip().startswith("%include ")
                and len(row.split(None, 1)) > 1]
    for kind, first, last in segments(lines):
        if kind != "pre":
            continue
        joined = "\n".join(lines[first:last])
        if not any(path in joined for path in includes):
            continue
        marked = any(lines[num].strip() == MARK + name
                     for num in range(first, last) for name in SHARED)
        if not marked:
            issues.append((first + 1, "%pre 生成存储片段但未嵌入选盘器"))
    return sorted(issues)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="ks_embed.py", description="展开 kickstart 中的共享脚本")
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--include-dir", type=Path, default=None,
                    help="共享脚本目录，缺省取 src 所在目录")
    args = ap.parse_args(argv)
    base = args.include_dir if args.include_dir else args.src.parent
    try:
        text = args.src.read_text(encoding="utf-8")
        out = expand(text, base)
        args.dst.parent.mkdir(parents=True, exist_ok=True)
        args.dst.write_text(out, encoding="utf-8")
    except EmbedError as err:
        print(f"ks_embed: {args.src}:{err.line}: {err}", file=sys.stderr)
        return EINVAL
    except (OSError, ValueError) as err:
        print(f"ks_embed: {err}", file=sys.stderr)
        return EINVAL
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
