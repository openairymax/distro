#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# lock_check.py — rpm lockfile 的离线校验与冻结点差异摘要
#
# 只依赖 Python 标准库，不联网，可在 L0 静态门禁内执行。两个子命令：
#
#   verify  断言 lockfile 覆盖 comps 中指定 environment 的闭包必装包
#           （mandatory 与 default），防止 kickstart 装得上、冻结集却漏包
#   diff    比较两份 lockfile，输出 新增 / 升级 / 移除 三段摘要
#
# lockfile 结构由 rpm-lockfile-prototype 生成（Hermeto 兼容）：
#   arches 段以 `- arch: <名>` 起头，其 packages 列表项为 `- url: ...`
#   后跟 name/evr/sourcerpm 等字段；source 与 module_metadata 段同形但
#   不属于安装集，解析时按段名截断。
# ===========================================================================

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ARCH_HEAD = re.compile(r"(?m)^- arch: ")
SECT_END = re.compile(r"(?m)^  (?:source|module_metadata):$")
PKG_HEAD = re.compile(r"(?m)^  - url: ")


def _field(block, key):
    hit = re.search(r"(?m)^    %s: (\S+?)\s*$" % key, block)
    return hit.group(1) if hit else ""


def _pkg_map(body):
    return {_field(b, "name"): _field(b, "evr") for b in PKG_HEAD.split(body)[1:]}


def _arch_bodies(text):
    bodies = {}
    for chunk in ARCH_HEAD.split(text)[1:]:
        name, _, rest = chunk.partition("\n")
        bodies[name.strip()] = SECT_END.split(rest)[0]
    return bodies


def packages(path):
    """返回 {arch: {包名: EVR}}，仅含安装集。"""
    return {arch: _pkg_map(body) for arch, body in _arch_bodies(
        Path(path).read_text(encoding="utf-8")).items()}


def _flat(path):
    return {"%s:%s" % (arch, name): evr
            for arch, pkgs in packages(path).items()
            for name, evr in pkgs.items()}


def _group_map(comps):
    return {g.findtext("id"): g for g in ET.parse(comps).iter("group")}


def _env_groups(comps, env):
    """环境默认组；optionlist 是可选组，默认安装集不含。"""
    for node in ET.parse(comps).iter("environment"):
        if node.findtext("id") == env:
            return [g.text for g in node.findall("grouplist/groupid")]
    raise SystemExit("environment 未定义: %s" % env)


def _reqs(group):
    """组内必装包：mandatory 与 default；optional 不在默认安装集。"""
    return {r.text for r in group.iter("packagereq")
            if r.get("type", "default") in ("mandatory", "default")}


def _closure(groups, ids):
    seen, want, stack = set(), set(), list(ids)
    while stack:
        gid = stack.pop()
        if gid in seen or gid not in groups:
            continue
        seen.add(gid)
        want.update(_reqs(groups[gid]))
        stack.extend(g.text for g in groups[gid].iter("groupid"))
    return want


def verify(comps, lock, env, local="airymaxos"):
    want = _closure(_group_map(comps), _env_groups(comps, env))
    have = {name for pkgs in packages(lock).values() for name in pkgs}
    ours = {name for name in want - have if name.startswith(local)}
    missing = sorted(want - have - ours)
    if missing:
        sys.stderr.write("lockfile 缺少 comps 必装包: %s\n" % " ".join(missing))
        return 1
    print("lockfile 覆盖 %d 个上游必装包（environment=%s；本项目包 %d 项由 "
          "assumeProvides 承担）" % (len(want) - len(ours), env, len(ours)))
    return 0


def diff(old, new):
    before, after = _flat(old), _flat(new)
    rows = (("新增", sorted(set(after) - set(before))),
            ("升级", sorted(n for n in set(before) & set(after)
                            if before[n] != after[n])),
            ("移除", sorted(set(before) - set(after))))
    for tag, names in rows:
        print("%s %d" % (tag, len(names)))
        for name in names:
            print("  %s %s -> %s" % (name, before.get(name, "-"),
                                     after.get(name, "-")))
    return 0


def main():
    ap = argparse.ArgumentParser(description="rpm lockfile 离线校验")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--comps", required=True)
    v.add_argument("--lock", required=True)
    v.add_argument("--environment", required=True)
    v.add_argument("--local-prefix", default="airymaxos",
                   help="本项目自建包名前缀，不要求出现在上游冻结集")
    d = sub.add_parser("diff")
    d.add_argument("--old", required=True)
    d.add_argument("--new", required=True)
    args = ap.parse_args()
    if args.cmd == "verify":
        return verify(args.comps, args.lock, args.environment,
                      args.local_prefix)
    return diff(args.old, args.new)


if __name__ == "__main__":
    sys.exit(main())
