#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# ks_spec.py — 从安装配方提取仓库、包规格与 comps 元数据
#
# 构建期闭包收割与安装期解析必须读同一份事实：kickstart 是仓库集合与
# 包清单的唯一来源（SSoT）。本工具把配方翻译成 dnf 可直接消费的仓库表
# 与包规格，避免构建脚本另抄一份包名而在两处漂移。
#
# 子命令：
#   repos [--skip-file] FILE   输出 <name>\t<baseurl>\t<cost>
#   pkgs [--comps FILE] FILE   输出 <install|exclude>\t<规格>
#   envs FILE                  输出配方引用的环境 <id>
#   verify DIR --env ID        校验载荷仓库 comps 是否携带该环境及其组
#   install FILE               输出安装期配方（安装源改指载荷，剔除网络仓库）
#
# 同一份配方表达两个姿态，投影是纯函数：
#   构建期 — 上游网络仓库 + 载荷仓库，闭包收割要能解析全部依赖；
#   安装期 — 只剩 file:// 载荷仓库，装机不触网，公网不可达也能装完。
# 安装期配方不手抄第二份，避免包清单与仓库表在两处漂移。
#
# @^环境 只在 anaconda 语境成立：dnf 命令行把 @^airymax-workstation 当作
# 组名 ^airymax-workstation 求解并报 "not available"。收割器因此按
# comps 的 environment/grouplist 展开为 @组，与安装期读同一份 comps，
# 两端事务才等价。展开同时下钻组引用（grouplist），保证桌面组与核心组
# 只解一次。
#
# verify 用在镜像组装之后：createrepo_c 重写 comps 时若丢弃 environment
# 段，交互安装的软件选择与按环境解析都会失败，必须在出镜像前拒绝。
# repomd.xml 带默认命名空间，comps 也可能带，XML 一律按本地名匹配，
# 否则真实仓库会被误判成没有 group 数据。
#
# 退出码：0 成功；5 配方或 comps 不满足。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import argparse
import gzip
import shlex
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

EINVAL = 5
ENV_HEAD = "@^"
GROUP_HEAD = "@"
GZIP_MAGIC = b"\x1f\x8b"
VENDOR = "airymaxos-offline"


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


def payload_url(rows: list[tuple[str, str, str]]) -> str:
    for name, base, _cost in rows:
        if name == VENDOR:
            return base
    raise ValueError(f"配方缺少 {VENDOR} 仓库")


def rewrite(line: str, key: str, val: str) -> str:
    words = shlex.split(line)
    out: list[str] = []
    pos = 0
    while pos < len(words):
        word = words[pos]
        if word == key:
            out += [key, val]
            pos += 2
        else:
            out.append(f"{key}={val}" if word.startswith(key + "=") else word)
            pos += 1
    return " ".join(out)


def proj_line(line: str, base: str) -> str | None:
    word = line.strip()
    if not word or word.startswith("#"):
        return line
    words = shlex.split(word)
    if words[0] == "url":
        return rewrite(word, "--url", base) + "\n"
    if words[0] == "repo" and opt(words, "--name") != VENDOR:
        return None
    return line


def check_pose(text: str, src: str, base: str) -> None:
    if pkgs(text) != pkgs(src):
        raise ValueError("投影改变了包清单")
    rows = repos(text)
    if [row[0] for row in rows] != ["baseos", VENDOR]:
        raise ValueError("投影后仓库表不纯净")
    if any(row[1] != base for row in rows):
        raise ValueError("投影后仓库未指向载荷")


def project(text: str) -> str:
    base = payload_url(repos(text))
    lines = text.splitlines(keepends=True)
    head = next((pos for pos, line in enumerate(lines)
                 if line.strip().startswith("%")), len(lines))
    body = [row for row in (proj_line(line, base) for line in lines[:head])
            if row is not None]
    flowed = "".join(body + lines[head:])
    check_pose(flowed, text, base)
    return flowed


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


def env_ids(rows: list[tuple[str, str]]) -> list[str]:
    return [spec[2:] for kind, spec in rows
            if kind == "install" and spec.startswith(ENV_HEAD)]


def comps_tree(path: Path) -> ET.Element:
    try:
        return ET.parse(path).getroot()
    except OSError as err:
        raise ValueError(f"comps 读取失败: {err}") from err
    except ET.ParseError as err:
        raise ValueError(f"comps 解析失败: {err}") from err


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _desc(root: ET.Element, name: str) -> list[ET.Element]:
    return [node for node in root.iter() if _local(node.tag) == name]


def _kids(node: ET.Element, name: str) -> list[ET.Element]:
    return [kid for kid in node if _local(kid.tag) == name]


def _text(node: ET.Element, name: str) -> str:
    kids = _kids(node, name)
    return (kids[0].text or "").strip() if kids else ""


def _refs(node: ET.Element) -> list[str]:
    return [ref.text.strip() for lst in _kids(node, "grouplist")
            for ref in _kids(lst, "groupid") if ref.text and ref.text.strip()]


def comps_ids(root: ET.Element):
    groups: dict[str, list[str]] = {}
    for node in _desc(root, "group"):
        gid = _text(node, "id")
        if not gid:
            raise ValueError("comps 包组缺少 id")
        groups[gid] = _refs(node)
    envs: dict[str, list[str]] = {}
    for node in _desc(root, "environment"):
        eid = _text(node, "id")
        if not eid:
            raise ValueError("comps 环境缺少 id")
        envs[eid] = _refs(node)
    return envs, groups


def add_group(gid: str, groups: dict[str, list[str]], out: list[str]) -> None:
    if gid in out:
        return
    out.append(gid)
    for ref in groups.get(gid, ()):
        add_group(ref, groups, out)


def expand_env(eid: str, envs: dict[str, list[str]],
               groups: dict[str, list[str]]) -> list[str]:
    if eid not in envs:
        raise ValueError(f"comps 未定义环境: {eid}")
    if not envs[eid]:
        raise ValueError(f"comps 环境没有默认组: {eid}")
    out: list[str] = []
    for gid in envs[eid]:
        if gid not in groups:
            raise ValueError(f"环境 {eid} 引用的组未定义: {gid}")
        add_group(gid, groups, out)
    return [GROUP_HEAD + gid for gid in out]


def expand_envs(rows: list[tuple[str, str]],
                comps: Path) -> list[tuple[str, str]]:
    envs, groups = comps_ids(comps_tree(Path(comps)))
    out: list[tuple[str, str]] = []
    for kind, spec in rows:
        if kind == "install" and spec.startswith(ENV_HEAD):
            spawned = [("install", row)
                       for row in expand_env(spec[2:], envs, groups)]
        else:
            spawned = [(kind, spec)]
        for row in spawned:
            if row not in out:
                out.append(row)
    return out


def group_meta(pkgdir: Path) -> bytes:
    repomd = pkgdir / "repodata" / "repomd.xml"
    try:
        root = ET.parse(repomd).getroot()
    except OSError as err:
        raise ValueError(f"仓库索引读取失败: {err}") from err
    except ET.ParseError as err:
        raise ValueError(f"仓库索引解析失败: {err}") from err
    for data in _desc(root, "data"):
        if data.get("type") != "group":
            continue
        loc = _kids(data, "location")
        href = loc[0].get("href") if loc else None
        if not href:
            raise ValueError("仓库 group 元数据缺少 location")
        try:
            raw = (pkgdir / href).read_bytes()
        except OSError as err:
            raise ValueError(f"仓库 group 元数据读取失败: {err}") from err
        return gzip.decompress(raw) if raw[:2] == GZIP_MAGIC else raw
    raise ValueError("仓库索引缺少 group 元数据")


def verify_repo(pkgdir: Path, env: str) -> None:
    try:
        root = ET.fromstring(group_meta(Path(pkgdir)))
    except ET.ParseError as err:
        raise ValueError(f"仓库 comps 解析失败: {err}") from err
    envs, groups = comps_ids(root)
    if env not in envs:
        raise ValueError(f"仓库 comps 缺少环境: {env}")
    for gid in envs[env]:
        if gid not in groups:
            raise ValueError(f"环境 {env} 引用的组缺失: {gid}")
    print(f"env\t{env}")
    for gid in sorted(groups):
        print(f"group\t{gid}")


def emit_repos(text: str, skip_file: bool) -> None:
    rows = repos(text)
    if skip_file:
        rows = [row for row in rows if not row[1].startswith("file:")]
    for name, base, cost in rows:
        print(f"{name}\t{base}\t{cost}")


def emit_pkgs(text: str, comps: Path | None) -> None:
    rows = pkgs(text)
    if comps is not None:
        rows = expand_envs(rows, comps)
    elif env_ids(rows):
        raise ValueError("配方含环境组，需 --comps 展开")
    for kind, spec in rows:
        print(f"{kind}\t{spec}")


def emit_envs(text: str) -> None:
    for eid in env_ids(pkgs(text)):
        print(eid)


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="ks_spec.py", description="提取安装配方规格")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("repos")
    rep.add_argument("--skip-file", action="store_true")
    rep.add_argument("file", type=Path)
    pkg = sub.add_parser("pkgs")
    pkg.add_argument("--comps", type=Path)
    pkg.add_argument("file", type=Path)
    env = sub.add_parser("envs")
    env.add_argument("file", type=Path)
    ins = sub.add_parser("install")
    ins.add_argument("file", type=Path)
    ver = sub.add_parser("verify")
    ver.add_argument("--env", required=True)
    ver.add_argument("dir", type=Path)
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse(argv)
    try:
        if args.cmd == "verify":
            verify_repo(args.dir, args.env)
            return 0
        text = args.file.read_text(encoding="utf-8")
        if args.cmd == "repos":
            emit_repos(text, args.skip_file)
        elif args.cmd == "envs":
            emit_envs(text)
        elif args.cmd == "install":
            sys.stdout.write(project(text))
        else:
            emit_pkgs(text, args.comps)
    except (OSError, ValueError) as err:
        print(f"ks_spec: {err}", file=sys.stderr)
        return EINVAL
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
