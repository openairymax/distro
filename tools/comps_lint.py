#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# comps_lint.py — AirymaxOS comps 包组定义静态校验
#
# 只依赖标准库。XML 结构由标准库解析，项目语义（组/环境标识、包名、
# 布尔字段、组引用与嵌套环、环境到组的引用、kickstart 选择）逐项复核；
# comps/comps.dtd 供 xmllint --valid 做 DTD 结构校验。规则编号
# C001~C014 与 tools/tests/test_comps.py 一一对应。
#
# C012~C014 锁住安装期事务的完整性：anaconda 在 %packages 未加
# --nocore 时隐式追加 @core，并在引导阶段无条件追加 grub2、grub2-tools
# 与时区 NTP 包。载荷 comps 缺任一项，装机就会停在「是否继续」问句，
# 无头安装直接失败（0.0.3 首次 L2 装机即由此暴露）。
#
# 退出码：0 通过；1 存在问题；2 用法或读取错误。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from lint_common import Issue, dump, report

PUBLIC = "-//Airymax//DTD Comps 1.0//EN"
SYSTEM = "comps.dtd"
DOCTYPE = re.compile(
    r'<!DOCTYPE\s+comps\s+PUBLIC\s+"([^"]+)"\s+"([^"]+)"\s*>')
PKGNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
TYPES = frozenset({"mandatory", "default", "optional", "conditional"})
BOOL = frozenset({"true", "false"})

# 上游身份包不得进入产品包组（C011）：上游 core 组的 mandatory 含 kernel，
# 并携带 openEuler-release 系列，与本产品 airymaxos-kernel /
# airymaxos-release 争用同一组文件路径和 system-release 能力，写进包组
# 会让 dnf 按求解顺序二选一（kickstart 侧的对应约束见 K014/K017）。
UPSTREAM = ("kernel", "openEuler-release", "openEuler-latest-release")

# 基础系统组及其必须携带的安装器隐式需求（C013/C014）
CORE = "airymax-core"
CORE_REF = "@" + CORE
CORE_NEEDS = ("grub2", "grub2-tools", "chrony")
NOCORE = "--nocore"


def text_of(node: ET.Element, tag: str) -> str:
    return (node.findtext(tag) or "").strip()


def tag_line(lines: list[str], tag: str, text: str) -> int:
    needle = f"<{tag}>{text}</{tag}>"
    for num, raw in enumerate(lines, 1):
        if needle in raw:
            return num
    return 1


def pkg_line(lines: list[str], name: str) -> int:
    needle = f">{name}</packagereq>"
    for num, raw in enumerate(lines, 1):
        if needle in raw:
            return num
    return 1


def check_doctype(text: str, issues: list[Issue]) -> None:
    hit = DOCTYPE.search(text)
    if not hit:
        issues.append(Issue("C002", 1, "missing comps DOCTYPE"))
        return
    if hit.group(1) != PUBLIC:
        issues.append(Issue("C002", 1, f"bad public id: {hit.group(1)}"))
    if hit.group(2) != SYSTEM:
        issues.append(Issue("C002", 1, f"bad system id: {hit.group(2)}"))


def grp_id(grp: ET.Element, seen: set[str],
           lines: list[str], issues: list[Issue]) -> str:
    gid = text_of(grp, "id")
    if not gid:
        issues.append(Issue("C003", 1, "group without id"))
        return ""
    line = tag_line(lines, "id", gid)
    if not PKGNAME.match(gid):
        issues.append(Issue("C003", line, f"bad group id: {gid}"))
    if gid in seen:
        issues.append(Issue("C003", line, f"duplicate group id: {gid}"))
    seen.add(gid)
    return gid


def grp_body(grp: ET.Element, gid: str,
             lines: list[str], issues: list[Issue]) -> None:
    line = tag_line(lines, "id", gid)
    if grp.find("name") is None:
        issues.append(Issue("C005", line, f"group {gid}: missing name"))
    pkglist = grp.find("packagelist")
    if pkglist is None:
        issues.append(Issue("C005", line, f"group {gid}: missing packagelist"))
    elif pkglist.find("packagereq") is None:
        issues.append(Issue("C005", line, f"group {gid}: empty packagelist"))


def req_name(name: str, seen: set[str], gid: str,
             line: int, issues: list[Issue]) -> None:
    if not PKGNAME.match(name):
        issues.append(Issue("C006", line, f"group {gid}: bad package "
                                         f"{name!r}"))
    if name in seen:
        issues.append(Issue("C006", line, f"group {gid}: duplicate package "
                                         f"{name}"))
    seen.add(name)


def req_kind(req: ET.Element, gid: str,
             line: int, issues: list[Issue]) -> None:
    kind = req.get("type", "default")
    if kind not in TYPES:
        issues.append(Issue("C006", line, f"group {gid}: bad type {kind}"))


def upstream_pkg(name: str) -> bool:
    return any(name == item or name.startswith(item + "-")
               for item in UPSTREAM)


def grp_pkgs(grp: ET.Element, gid: str,
             lines: list[str], issues: list[Issue]) -> None:
    seen: set[str] = set()
    for req in grp.findall("packagelist/packagereq"):
        name = (req.text or "").strip()
        line = pkg_line(lines, name)
        req_name(name, seen, gid, line, issues)
        req_kind(req, gid, line, issues)
        if upstream_pkg(name):
            issues.append(Issue("C011", line,
                                f"group {gid}: upstream package {name}"))


def grp_refs(grp: ET.Element, gid: str, gids: set[str],
             lines: list[str], issues: list[Issue]) -> list[str]:
    edges: list[str] = []
    for tag in ("grouplist", "optionlist"):
        for ref in grp.findall(f"{tag}/groupid"):
            name = (ref.text or "").strip()
            if name == gid or name not in gids:
                issues.append(Issue("C007", tag_line(lines, "groupid", name),
                                    f"group {gid}: bad group ref {name}"))
                continue
            edges.append(name)
    return edges


def walk_cycle(gid: str, edges: dict[str, list[str]], state: dict[str, int],
               path: list[str], lines: list[str], issues: list[Issue]) -> None:
    state[gid] = 1
    path.append(gid)
    for nxt in edges.get(gid, []):
        if state.get(nxt, 0) == 1:
            cycle = path[path.index(nxt):] + [nxt]
            issues.append(Issue("C010", tag_line(lines, "groupid", nxt),
                                f"group cycle: {' -> '.join(cycle)}"))
        elif state.get(nxt, 0) == 0:
            walk_cycle(nxt, edges, state, path, lines, issues)
    path.pop()
    state[gid] = 2


def check_cycles(edges: dict[str, list[str]], lines: list[str],
                 issues: list[Issue]) -> None:
    state: dict[str, int] = {}
    for gid in edges:
        if state.get(gid, 0) == 0:
            walk_cycle(gid, edges, state, [], lines, issues)


def check_core(grp: ET.Element, gid: str,
               lines: list[str], issues: list[Issue]) -> None:
    kinds = {(req.text or "").strip(): req.get("type", "default")
             for req in grp.findall("packagelist/packagereq")}
    for name in CORE_NEEDS:
        if kinds.get(name, "optional") == "optional":
            issues.append(Issue("C014", tag_line(lines, "id", gid),
                                f"group {gid}: {name} must be installed"))


def check_groups(root: ET.Element, lines: list[str],
                 issues: list[Issue]) -> set[str]:
    gids: set[str] = set()
    for grp in root.findall("group"):
        grp_id(grp, gids, lines, issues)
    edges: dict[str, list[str]] = {}
    for grp in root.findall("group"):
        gid = text_of(grp, "id")
        if not gid:
            continue
        grp_body(grp, gid, lines, issues)
        grp_pkgs(grp, gid, lines, issues)
        if gid == CORE:
            check_core(grp, gid, lines, issues)
        edges[gid] = grp_refs(grp, gid, gids, lines, issues)
    check_cycles(edges, lines, issues)
    return gids


def env_id(env: ET.Element, gids: set[str], seen: set[str],
           lines: list[str], issues: list[Issue]) -> str:
    eid = text_of(env, "id")
    if not eid:
        issues.append(Issue("C004", 1, "environment without id"))
        return ""
    line = tag_line(lines, "id", eid)
    if eid in seen or eid in gids:
        issues.append(Issue("C004", line, f"duplicate environment id: {eid}"))
    if not PKGNAME.match(eid):
        issues.append(Issue("C004", line, f"bad environment id: {eid}"))
    seen.add(eid)
    return eid


def env_body(env: ET.Element, eid: str, gids: set[str],
             lines: list[str], issues: list[Issue]) -> None:
    line = tag_line(lines, "id", eid)
    if env.find("grouplist") is None:
        issues.append(Issue("C007", line, f"environment {eid}: "
                                          f"missing grouplist"))
    refs = env.findall("grouplist/groupid")
    refs += env.findall("optionlist/groupid")
    for ref in refs:
        name = (ref.text or "").strip()
        if name not in gids:
            issues.append(Issue("C007", tag_line(lines, "groupid", name),
                                f"environment {eid}: undefined group {name}"))


def check_envs(root: ET.Element, gids: set[str], lines: list[str],
               issues: list[Issue]) -> set[str]:
    eids: set[str] = set()
    for env in root.findall("environment"):
        eid = env_id(env, gids, eids, lines, issues)
        env_body(env, eid, gids, lines, issues)
    return eids


def check_bool(grp: ET.Element, gid: str, tag: str,
               lines: list[str], issues: list[Issue]) -> None:
    val = grp.findtext(tag)
    if val is None:
        return
    val = val.strip()
    if val not in BOOL:
        issues.append(Issue("C008", tag_line(lines, tag, val),
                            f"group {gid}: {tag}={val}"))


def check_bools(root: ET.Element, lines: list[str],
                issues: list[Issue]) -> None:
    for grp in root.findall("group"):
        gid = text_of(grp, "id")
        for tag in ("default", "uservisible"):
            check_bool(grp, gid, tag, lines, issues)


Sect = tuple[int, str, list[tuple[int, str]]]


def ks_sects(lines: list[str]) -> list[Sect]:
    sects: list[Sect] = []
    live = False
    head, opts, items = 1, "", []
    for num, raw in enumerate(lines, 1):
        line = raw.split("#", 1)[0].strip()
        if line.startswith("%packages"):
            live, head = True, num
            opts = line[len("%packages"):].strip()
            items = []
        elif live and line == "%end":
            sects.append((head, opts, items))
            live = False
        elif live and line:
            items.append((num, line))
    return sects


def check_env_ref(ref: str, num: int, eids: set[str],
                  issues: list[Issue]) -> None:
    if ref not in eids:
        issues.append(Issue("C009", num, f"undefined environment @^{ref}"))


def check_grp_ref(ref: str, num: int, gids: set[str], eids: set[str],
                  issues: list[Issue]) -> None:
    if ref in eids:
        issues.append(Issue("C009", num, f"use @^{ref} for environment"))
    elif ref.startswith("airymax-") and ref not in gids:
        issues.append(Issue("C009", num, f"undefined group @{ref}"))


def check_ref(line: str, num: int, gids: set[str], eids: set[str],
              issues: list[Issue]) -> None:
    if line.startswith("-"):
        return
    if line.startswith("@^"):
        check_env_ref(line[2:].strip(), num, eids, issues)
    elif line.startswith("@"):
        check_grp_ref(line[1:].strip(), num, gids, eids, issues)


def check_base(name: str, sect: Sect, gids: set[str],
               issues: list[Issue]) -> None:
    head, opts, items = sect
    if NOCORE in opts.split():
        if CORE_REF not in [spec for _num, spec in items]:
            issues.append(Issue("C013", head,
                                f"{name}: %packages {NOCORE} without "
                                f"{CORE_REF}"))
    elif "core" not in gids:
        issues.append(Issue("C012", head,
                            f"{name}: implicit @core undefined in comps"))


def walk_ks(base: Path, gids: set[str], eids: set[str],
            issues: list[Issue]) -> None:
    for path in sorted((base / "kickstart").glob("*.ks")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as err:
            issues.append(Issue("C009", 1, f"cannot read {path.name}: {err}"))
            continue
        for sect in ks_sects(lines):
            check_base(path.name, sect, gids, issues)
            for num, line in sect[2]:
                check_ref(line, num, gids, eids, issues)


def lint_text(text: str, base: Path) -> list[Issue]:
    lines = text.splitlines()
    issues: list[Issue] = []
    check_doctype(text, issues)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as err:
        issues.append(Issue("C001", err.position[0], f"XML parse error: {err}"))
        return issues
    if root.tag != "comps":
        issues.append(Issue("C001", 1, f"root is {root.tag}, want comps"))
        return issues
    gids = check_groups(root, lines, issues)
    eids = check_envs(root, gids, lines, issues)
    check_bools(root, lines, issues)
    walk_ks(base, gids, eids, issues)
    return sorted(issues, key=lambda item: (item.line, item.code))


def lint_comps(path: Path, base: Path) -> list[Issue]:
    return lint_text(path.read_text(encoding="utf-8"), base)


def main(argv: list[str]) -> int:
    base = Path(__file__).resolve().parent.parent
    targets = [Path(arg) for arg in argv[1:]]
    if not targets:
        targets = sorted((base / "comps").glob("*.xml"))
    if not targets:
        print("comps_lint: no comps file found", file=sys.stderr)
        return 2
    total = 0
    for path in targets:
        try:
            issues = lint_comps(path, base)
        except OSError as err:
            print(f"comps_lint: {err}", file=sys.stderr)
            return 2
        total += dump(path, issues)
    return report("comps_lint", total)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
