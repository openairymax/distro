#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# ukui_check.py — UKUI 组件台账与消费侧的离线校验
#
# 只依赖标准库，不联网。台账是 UKUI 包名与 NVRA 的唯一事实源：基底五段
# repodata 中 UKUI 组件只存在于 EPOL/main，且没有 ukui-shell；元包 ukui 与
# ukui-desktop-environment 有，但本版不用。因此桌面闭包只能逐组件声明——
# 本校验器断言台账、comps、冻结输入与内部取证册四者同源，任一环漂移即判红。
#
#   verify --root DIR [--docs DIR]
#
# 判据（由 ci/gates/ukui-lock.sh 调用）：
#   1. 台账 schema：基底、架构、五段、策略与 NVRA 正则；
#   2. 核心四件 present，两个元包 available，ukui-shell absent；
#   3. comps 的 UKUI 闭包与台账 present 集合相等，且每个组件只登记一次；
#      闭包集合是 ukui* 命名空间与台账 present 项的并集——认证后端这类
#      组件按上游包名不带 ukui 前缀，只按命名空间过滤会漏判；
#   4. 冻结输入覆盖默认安装集的同一闭包，且只含 present 项；
#   5. 取证册逐字包含全部 present NVRA，并保留 4.24 取舍与复算命令。
# ===========================================================================

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = "openEuler-24.03-LTS-SP2"
ARCH = "x86_64"
SEGS = ["OS", "update", "EPOL/main", "EPOL/update/main", "everything"]
ENV = "airymax-workstation"
# 会话可登录的最小集合；缺任一件都进不了桌面。
CORE = ("ukui-kwin", "ukui-panel", "ukui-session-manager",
        "ukui-control-center")
# 基底有、本版刻意不选的元包；回流到闭包即失去逐组件钉版。
UNPICKED = ("ukui", "ukui-desktop-environment")
# 基底全条线不提供的包；一旦回流到闭包，装机求解必然失败。
GONE = ("ukui-shell",)
STATES = ("present", "available", "absent")
NVRA = re.compile(r"^(.+)-0:([^-]+)-([^-]+)\.x86_64$")


def say(msg):
    print(msg)


def bad(out, code, msg):
    out.append("%s: %s" % (code, msg))


def parse_ledger(path):
    """解析台账的行式 YAML 子集：顶层键、两段列表与策略表。"""
    dat = {"segments": [], "policy": {}, "components": []}
    sect, cur = "", None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            key, _, val = line.partition(":")
            sect = key.strip()
            if sect in ("base", "arch"):
                dat[sect] = val.strip()
            continue
        if sect == "segments":
            dat["segments"].append(line.strip().lstrip("- ").strip())
        elif sect == "policy":
            key, _, val = line.strip().partition(":")
            dat["policy"][key.strip()] = val.strip()
        elif sect == "components":
            if cur is None or line.startswith("  - "):
                cur = {}
                dat["components"].append(cur)
                line = "    " + line[len("  - "):]
            key, _, val = line.strip().partition(":")
            cur[key.strip()] = val.strip()
    return dat


def check_schema(led, out):
    if led.get("base") != BASE:
        bad(out, "schema/base", "%s != %s" % (led.get("base"), BASE))
    if led.get("arch") != ARCH:
        bad(out, "schema/arch", "%s != %s" % (led.get("arch"), ARCH))
    if led.get("segments") != SEGS:
        bad(out, "schema/segments", "--".join(led.get("segments", [])))
    pol = led.get("policy", {})
    for key, want in (("route", "base-highest-stable"),
                      ("generation", "3.1"), ("deferred", "ukui-4.24")):
        if pol.get(key) != want:
            bad(out, "schema/policy", "%s=%s 应为 %s"
                % (key, pol.get(key), want))


def check_pkg(name, rec, out):
    state = rec.get("state", "")
    if state not in STATES:
        bad(out, "ledger/state", "%s state=%s" % (name, state))
        return
    if state == "absent":
        if rec.get("segment") != "五段均无":
            bad(out, "ledger/segment", "%s absent 应标五段均无" % name)
        return
    if rec.get("segment") not in SEGS:
        bad(out, "ledger/segment", "%s segment=%s"
            % (name, rec.get("segment")))
    hit = NVRA.match(rec.get("nvra", ""))
    if not hit or hit.group(1) != name:
        bad(out, "ledger/nvra", "%s nvra=%s" % (name, rec.get("nvra")))


def check_items(led, out):
    seen = {}
    for rec in led.get("components", []):
        name = rec.get("name", "")
        if not name or name in seen:
            bad(out, "ledger/name", "组件名缺失或重复: %s" % name)
            continue
        seen[name] = rec.get("state", "")
        check_pkg(name, rec, out)
    for name in CORE:
        if seen.get(name) != "present":
            bad(out, "ledger/core", "%s 未登记为 present" % name)
    for name in UNPICKED:
        if seen.get(name) != "available":
            bad(out, "ledger/available", "%s 未登记为 available" % name)
    for name in GONE:
        if seen.get(name) != "absent":
            bad(out, "ledger/absent", "%s 未登记为 absent" % name)
    return seen


def read_comps(path):
    root = ET.parse(path).getroot()
    return {g.findtext("id"): g for g in root.iter("group")}, root


def reqs(group):
    """组内默认安装包：mandatory 与 default；optional 不在默认集。"""
    return {r.text for r in group.iter("packagereq")
            if r.get("type", "default") in ("mandatory", "default")}


def env_ids(root):
    for node in root.iter("environment"):
        if node.findtext("id") == ENV:
            return [g.text for g in node.findall("grouplist/groupid")]
    return []


def closure(groups, ids):
    seen, want, stack = set(), set(), list(ids)
    while stack:
        gid = stack.pop()
        if gid in seen or gid not in groups:
            continue
        seen.add(gid)
        want.update(reqs(groups[gid]))
        stack.extend(g.text for g in groups[gid].iter("groupid"))
    return want


def ukui_in(groups, pres):
    """{闭包包名: 出现的组数}；可选组也计入，重复声明会让归属不可判定。"""
    out = {}
    for group in groups.values():
        for req in group.iter("packagereq"):
            name = req.text or ""
            if name.startswith("ukui") or name in pres:
                out[name] = out.get(name, 0) + 1
    return out


def check_comps(groups, root, pres, out):
    have = ukui_in(groups, pres)
    for name, num in have.items():
        if name not in pres:
            bad(out, "comps/phantom", "%s 不在台账 present 项" % name)
        if num > 1:
            bad(out, "comps/dup", "%s 在 %d 个组重复声明" % (name, num))
    for name in pres:
        if name not in have:
            bad(out, "comps/missing", "%s 未进入任何组" % name)
    return {n for n in closure(groups, env_ids(root))
            if n.startswith("ukui") or n in pres}


def read_seeds(path):
    names, sect = set(), ""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line and not line[0].isspace():
            sect = line.split(":", 1)[0].strip()
            continue
        if sect == "packages" and line.strip().startswith("- "):
            names.add(line.strip()[2:].strip())
    return names


def check_seeds(have, pres, want, out):
    have = {name for name in have
            if name.startswith("ukui") or name in pres}
    for name in sorted(have - pres):
        bad(out, "seeds/phantom", "%s 不在台账 present 项" % name)
    for name in sorted(want - have):
        bad(out, "seeds/missing", "%s 属默认安装集却未冻结" % name)


def check_docs(docs, pres, out):
    delta = Path(docs) / "ukui-delta.md"
    feas = Path(docs) / "ukui-424-feasibility.md"
    if not delta.is_file() or not feas.is_file():
        bad(out, "docs/missing", "%s 缺少取证册" % docs)
        return
    text = delta.read_text(encoding="utf-8")
    for rec in pres:
        nvra = rec.get("nvra", "")
        if nvra and nvra not in text:
            bad(out, "docs/nvra", "%s 未逐字记录" % nvra)
    if "dnf -q repoquery" not in text:
        bad(out, "docs/recalc", "取证册缺少可复算命令")
    text = feas.read_text(encoding="utf-8")
    for mark in ("4.24", "ukui-shell", "路线 A", "路线 B", "顺延"):
        if mark not in text:
            bad(out, "docs/feas", "可行性册缺少 %s" % mark)


def main():
    ap = argparse.ArgumentParser(description="UKUI 组件台账离线校验")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ver = sub.add_parser("verify")
    ver.add_argument("--root", required=True)
    ver.add_argument("--docs", default="", help="内部取证册目录（可选）")
    args = ap.parse_args()

    root = Path(args.root)
    path = root / "distro/lockfile/ukui-components.yaml"
    if not path.is_file():
        sys.stderr.write("ledger/missing: %s\n" % path)
        return 1
    led = parse_ledger(path)
    out = []
    check_schema(led, out)
    check_items(led, out)
    pres = {c.get("name") for c in led["components"]
            if c.get("state") == "present"}
    try:
        groups, xroot = read_comps(
            root / "distro/comps/airymaxos-comps.xml")
    except (OSError, ET.ParseError) as err:
        sys.stderr.write("comps/unreadable: %s\n" % err)
        return 1
    want = check_comps(groups, xroot, pres, out)
    check_seeds(read_seeds(root / "distro/lockfile/rpms.in.yaml"),
                pres, want, out)
    if args.docs:
        check_docs(args.docs, [c for c in led["components"]
                               if c.get("state") == "present"], out)
    for line in out:
        sys.stderr.write("%s\n" % line)
    if out:
        sys.stderr.write("ukui-lock: %d 项失败\n" % len(out))
        return 1
    say("台账 %d 组件，默认安装集 %d 项与冻结输入同源"
        % (len(pres), len(want)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
