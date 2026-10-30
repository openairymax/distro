#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# gen_accept_ks.py — 生成验收 ISO 的 kickstart
#
# 产品配方与验收夹具必须分离：验收所需的行为（自动登录、会话内冒烟、
# 串口判定）只存在于 B 轮镜像，绝不能进入产品 ISO。本工具读取产品
# 配方，把 ci/ks/acceptance.part 插到最后一个收尾命令（reboot 等）
# 之前，输出到源码区之外的构建目录。夹具首行是幂等标记；重复插入
# 会被拒绝，避免夹具叠加改变判定语义。
#
# 退出码：0 成功；5 参数、内容或落点不满足。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARK = "# AIRYMAX-ACCEPTANCE-FIXTURE"
STOP = frozenset({"reboot", "poweroff", "halt", "shutdown"})
DISTRO = Path(__file__).resolve().parents[1]
EINVAL = 5


def stop_at(lines: list[str]) -> int | None:
    pos = None
    inside = False
    for num, line in enumerate(lines):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("%"):
            # %include 没有主体，不改变所处区块：漏掉它会让 inside 永为
            # 真，收尾命令就永远找不到。
            inside = text.split(None, 1)[0] not in ("%end", "%include")
            continue
        if inside:
            continue
        word = text.split(None, 1)
        if word and word[0] in STOP:
            pos = num
    return pos


def compose(base: str, overlay: str) -> str:
    if MARK in base:
        raise ValueError("基础配方已包含验收夹具")
    if not overlay.startswith(MARK):
        raise ValueError(f"夹具缺少幂等标记: {MARK}")
    part = overlay.splitlines(keepends=True)
    if not part:
        raise ValueError("夹具为空")
    lines = base.splitlines(keepends=True)
    pos = stop_at(lines)
    if pos is None:
        raise ValueError("基础配方缺少收尾命令")
    if not part[-1].endswith("\n"):
        part[-1] += "\n"
    lines[pos:pos] = part
    return "".join(lines)


def in_tree(path: Path) -> bool:
    try:
        path.resolve().relative_to(DISTRO)
    except ValueError:
        return False
    return True


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="gen_accept_ks.py", description="生成验收 kickstart")
    ap.add_argument("--base", required=True, type=Path)
    ap.add_argument("--overlay", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse(argv)
    try:
        if in_tree(args.out):
            raise ValueError(f"产物不得落在源码区: {args.out}")
        text = compose(args.base.read_text(encoding="utf-8"),
                       args.overlay.read_text(encoding="utf-8"))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    except (OSError, ValueError) as err:
        print(f"gen_accept_ks: {err}", file=sys.stderr)
        return EINVAL
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
