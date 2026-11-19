#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# airy_status.py — 本机磁盘、网络与模型状态一屏（安装为 airy-status）
#
# 为什么要有它：这三项此前各有一个生产者——airy-disk、airy-observe、
# airy-model，判定都在退出码里，桌面用户既不知道命令名，也不知道该看哪
# 一行。本入口挂在应用菜单里，打开即按固定顺序把三项摊在一屏上；每行都
# 能在终端用同一命令复算，因此结论不依赖本文件的可信度。
#
# 本脚本不产生任何新数字：磁盘取自 airy-disk status --json，网络取自
# airy-observe --section net，模型取自 airy-model status --json。取不到
# 的项打 absent 并让末行降级，不用上一次结果顶替，也不隐藏缺件——缺件
# 与降级正是现场最该看到的两件事。
#
# 用法：airy-status [--check]
# 退出码：0 三项齐备且模型就绪；1 有缺项或模型降级；2 用法错误。
# ===========================================================================

"""AirymaxOS desktop status panel (R1-14)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any

__all__ = ["main"]

MARK = "airy-status"

TIMEOUT = 20

MODEL_OK = (0, 10)

PEERS = ("airy-disk", "airy-observe", "airy-model")


def _run(argv: list[str]) -> tuple[int, str]:
    """跑一个生产者；命令缺失或超时按 127 处理，不抛给调用方。"""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return proc.returncode, proc.stdout


def _load(text: str) -> dict[str, Any] | None:
    """解析生产者输出；不是 JSON 对象时返回 None。"""
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _parts(topo: dict[str, Any]) -> list[dict[str, Any]]:
    """摊平所有磁盘下的分区对象；缺项或类型不符一律当空。"""
    rows: list[dict[str, Any]] = []
    for disk in topo.get("disks") or ():
        if not isinstance(disk, dict):
            continue
        rows.extend(part for part in disk.get("parts") or ()
                    if isinstance(part, dict))
    return rows


def _inst(topo: dict[str, Any]) -> None:
    """打印安装期记录；字段缺失一律打短横，不用默认值猜测。"""
    inst = topo.get("install")
    inst = inst if isinstance(inst, dict) else {}
    print(f"{MARK} disk install={inst.get('verdict') or '-'} "
          f"layout={inst.get('layout') or '-'} "
          f"disk={inst.get('disk') or '-'}")


def _part(part: dict[str, Any]) -> None:
    """打印一个分区的角色与挂载点。"""
    print(f"{MARK} disk part {part.get('name') or '-'} "
          f"role={part.get('role') or '-'} "
          f"mount={part.get('mount') or '-'}")


def _disk() -> bool:
    """打印安装期记录与各分区角色；非零退出码或空输出即 absent。"""
    code, out = _run(["airy-disk", "status", "--json"])
    topo = _load(out)
    if code != 0 or topo is None:
        print(f"{MARK} disk=absent")
        return False
    _inst(topo)
    for part in _parts(topo):
        _part(part)
    return True


def _kv(out: str) -> dict[str, str]:
    """把「标记 键=值」逐行拆成 net.* 字典；非 net 段一律忽略。"""
    fields: dict[str, str] = {}
    for line in out.splitlines():
        key, sep, val = line.rsplit(" ", 1)[-1].partition("=")
        if sep and key.startswith("net."):
            fields[key] = val
    return fields


def _net() -> bool:
    """打印联机四元组；没有 net.* 行即 absent。

    airy-observe 每行是「标记 键=值」，键在第 2 段；取最后一段而不是整行，
    否则前缀会把 net.* 挡在外面，面板永远显示 absent。
    """
    code, out = _run(["airy-observe", "--section", "net"])
    fields = _kv(out)
    if code != 0 or not fields:
        print(f"{MARK} net=absent")
        return False
    print(f"{MARK} net ipv4={fields.get('net.ipv4') or '-'} "
          f"src={fields.get('net.src') or '-'} "
          f"gw={fields.get('net.gw') or '-'} "
          f"dns={fields.get('net.dns') or '-'}")
    return True


def _model() -> bool:
    """打印模型判定；10 为显式降级，仍属可读但不计入就绪。"""
    code, out = _run(["airy-model", "status", "--json"])
    entry = _load(out)
    if code not in MODEL_OK or entry is None:
        print(f"{MARK} model state=absent")
        return False
    digest = str(entry.get("digest") or "-")
    print(f"{MARK} model state={entry.get('state') or '-'} "
          f"backend={entry.get('backend') or '-'} "
          f"reason={entry.get('reason') or '-'} digest={digest[:12]}")
    return code == 0


def selfcheck() -> int:
    """只查三个生产者是否在 PATH 上，不跑它们；供打包自检调用。"""
    state = "ok"
    print(f"{MARK} check python={sys.version.split()[0]}")
    for name in PEERS:
        found = shutil.which(name)
        print(f"{MARK} check {name}={'present' if found else 'absent'}")
        if found is None:
            state = "degraded"
    print(f"{MARK} status={state}")
    return 0 if state == "ok" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="airy-status",
        description="Disk, network and model status on this machine",
    )
    parser.add_argument("--check", action="store_true",
                        help="只检查生产者是否齐备")
    args = parser.parse_args()
    if args.check:
        return selfcheck()
    rows = (_disk(), _net(), _model())
    good = all(rows)
    print(f"{MARK} status={'ok' if good else 'degraded'}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
