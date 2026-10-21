#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# ks_spec.py — 从安装配方提取仓库与包规格
#
# 构建期闭包收割与安装期解析必须读同一份事实：kickstart 是仓库集合与
# 包清单的唯一来源（SSoT）。本工具把配方翻译成 dnf 可直接消费的仓库表
# 与包规格，避免构建脚本另抄一份包名而在两处漂移。
#
# 子命令：
#   repos [--skip-file] FILE   输出 <name>\t<baseurl>\t<cost>
#   pkgs FILE                  输出 <install|exclude>\t<规格>
#
# 退出码：0 成功；5 配方结构不满足。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

EINVAL = 5


def opt(words: list[str], key: str) -> str | None:
    for pos, word in enumerate(words):
        if word == key:
            return words[pos + 1] if pos + 1 < len(words) else None
        if word.startswith(key + "="):
            return word[len(key) + 1:]
    return None


def top_lines(text: str):
    for line in text.splitlines():
        word = line.strip()
        if not word or word.startswith("#"):
            continue
        if word.startswith("%"):
            return
        yield word


def repos(text: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for word in top_lines(text):
        words = shlex.split(word)
        if words[0] == "url":
            base = opt(words, "--url")
            if not base:
                raise ValueError("url 指令缺少 --url")
            rows.append(("baseos", base, "1000"))
        elif words[0] == "repo":
            name = opt(words, "--name")
            base = opt(words, "--baseurl")
            if not name or not base:
                raise ValueError("repo 指令缺少 --name 或 --baseurl")
            rows.append((name, base, opt(words, "--cost") or "1000"))
    return rows


def pkgs(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    inside = False
    for line in text.splitlines():
        word = line.strip()
        if word.startswith("%packages"):
            if inside:
                raise ValueError("嵌套 %packages")
            inside = True
        elif inside and word == "%end":
            return rows
        elif inside and word and not word.startswith("#"):
            if word.startswith("-"):
                rows.append(("exclude", word[1:]))
            else:
                rows.append(("install", word))
    if inside:
        raise ValueError("%packages 缺少 %end")
    return rows


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="ks_spec.py", description="提取安装配方规格")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("repos")
    rep.add_argument("--skip-file", action="store_true")
    rep.add_argument("file", type=Path)
    pkg = sub.add_parser("pkgs")
    pkg.add_argument("file", type=Path)
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse(argv)
    try:
        text = args.file.read_text(encoding="utf-8")
        if args.cmd == "repos":
            rows = repos(text)
            if args.skip_file:
                rows = [row for row in rows if not row[1].startswith("file:")]
            for name, base, cost in rows:
                print(f"{name}\t{base}\t{cost}")
        else:
            for kind, spec in pkgs(text):
                print(f"{kind}\t{spec}")
    except (OSError, ValueError) as err:
        print(f"ks_spec: {err}", file=sys.stderr)
        return EINVAL
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
