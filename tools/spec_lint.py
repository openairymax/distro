#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# spec_lint.py — AirymaxOS RPM 配方静态校验
#
# 只依赖标准库，供 distro/ci 在无 rpmbuild 的构建机上做前置门禁。规则来源：
# docs-linux/190-distribution/01-rpm-packaging.md 与
# docs-linux/50-engineering-standards。规则编号 E001~E014 与测试一一对应。
#
# 源码包由构建驱动现场生成的配方（如内核 tarball）可在文件头注释中声明
#   # spec-lint: generated-source <文件名>
# 该声明只豁免 E010 的存在性与唯一性检查，文件名形式与去重仍然校验。
#
# Source 位于本仓库其它子树（如 system/units）的配方可声明额外的搜索根：
#   # spec-lint: source-root <相对配方目录的路径>
# 校验时与 distro 根一并建立索引；根不存在本身即按 E010 报告。
#
# 退出码：0 通过；1 存在问题；2 用法或读取错误。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import re
import sys
from pathlib import Path

from lint_common import Issue, dump, report

REQUIRED = ("Name", "Version", "Release", "Summary", "License",
            "URL", "Source0")
MUST = ("description", "prep", "install", "check", "files",
        "changelog")
SPDX = frozenset({
    "AGPL-3.0-or-later", "Apache-2.0", "BSD-3-Clause",
    "GPL-2.0-only", "GPL-3.0-only",
    "GPL-2.0-only OR AGPL-3.0-or-later",
    "GPL-2.0-only OR GPL-3.0-only", "LGPL-2.1-or-later", "MIT",
})
SECTION = ("description", "package", "prep", "build", "install",
           "check", "files", "changelog", "pre", "post", "preun",
           "postun", "clean", "conf", "triggerin", "triggerun",
           "triggerpostun")
TAG = re.compile(r"^(Name|Version|Release|Summary|License|URL|Epoch|"
                 r"BuildArch|ExclusiveArch|Source\d+|Patch\d+|"
                 r"BuildRequires|Requires|Provides|Obsoletes|"
                 r"Conflicts|Group):\s*(.*)$")
SEC = re.compile(r"^%(" + "|".join(SECTION) + r")(?:\s+(.*))?$")
LOG = re.compile(r"^\*\s+[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+"
                 r"\d{4}\s+.+<[^<>]+>\s+-\s+\S+$")
MACRO = re.compile(r"^%(?:global|define)\s+(\w+)\s+(.+)$")
BAD = re.compile(r"\b(TODO|FIXME|XXX)\b")
SRC = re.compile(r"^Source\d+$")
GEN = re.compile(r"^#\s*spec-lint:\s*generated-source\s+(\S+)$")
ROOT = re.compile(r"^#\s*spec-lint:\s*source-root\s+(\S+)$")


def strip_cmt(line: str) -> str:
    return line.split("#", 1)[0].strip()


def collect_macros(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in lines:
        hit = MACRO.match(strip_cmt(raw))
        if hit:
            out.setdefault(hit.group(1), hit.group(2).strip())
    return out


def expand(text: str, macros: dict[str, str], depth: int = 0) -> str:
    if depth > 8:
        return text
    out = text
    for name, val in macros.items():
        out = out.replace("%{" + name + "}", val)
    if out == text:
        return out
    return expand(out, macros, depth + 1)


def parse_tags(lines: list[str]) -> dict[str, tuple[int, str]]:
    tags: dict[str, tuple[int, str]] = {}
    live = True
    for num, raw in enumerate(lines, 1):
        line = strip_cmt(raw)
        if not line:
            continue
        if SEC.match(raw):
            live = False
            continue
        hit = TAG.match(line) if live else None
        if hit:
            tags.setdefault(hit.group(1), (num, hit.group(2).strip()))
    return tags


def parse_secs(lines: list[str]) -> list[tuple[str, str, int]]:
    out = []
    for num, raw in enumerate(lines, 1):
        hit = SEC.match(raw.rstrip())
        if hit:
            out.append((hit.group(1), (hit.group(2) or "").strip(), num))
    return out


def walk_files(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        index.setdefault(path.name, []).append(path)
    return index


def build_index(roots: list[Path]) -> dict[str, set[Path]]:
    index: dict[str, set[Path]] = {}
    for root in roots:
        for name, hits in walk_files(root).items():
            index.setdefault(name, set()).update(hits)
    return index


def check_tags(tags: dict, ver: str, issues: list[Issue]) -> None:
    for name in REQUIRED:
        if name not in tags:
            issues.append(Issue("E001", 1, f"missing required tag: {name}"))
    if "BuildArch" not in tags and "ExclusiveArch" not in tags:
        issues.append(Issue("E001", 1, "missing BuildArch or ExclusiveArch"))
    if "License" in tags:
        num, val = tags["License"]
        if val not in SPDX:
            issues.append(Issue("E004", num, f"license not allowed: {val}"))
    if "Release" in tags:
        num, val = tags["Release"]
        if not val.endswith("%{?dist}"):
            issues.append(Issue("E003", num, "Release must end with %{?dist}"))


def check_name(tags: dict, path: Path, issues: list[Issue]) -> None:
    if "Name" not in tags:
        return
    num, val = tags["Name"]
    if not val.startswith("airymaxos-"):
        issues.append(Issue("E002", num, f"bad package prefix: {val}"))
    if val != path.stem:
        issues.append(Issue("E014", num, "file name differs from Name"))


def parse_gen(lines: list[str]) -> set[str]:
    out: set[str] = set()
    for raw in lines:
        hit = GEN.match(raw.strip())
        if hit:
            out.add(hit.group(1))
    return out


def parse_roots(lines: list[str], path: Path) -> list[tuple[int, Path]]:
    out = []
    for num, raw in enumerate(lines, 1):
        hit = ROOT.match(raw.strip())
        if hit:
            out.append((num, (path.parent / hit.group(1)).resolve()))
    return out


def check_srcs(tags: dict, roots: list[Path], macros: dict[str, str],
               gen: set[str], issues: list[Issue]) -> None:
    index = build_index(roots)
    seen: set[str] = set()
    for tag in sorted(tags):
        if not SRC.match(tag):
            continue
        num, raw = tags[tag]
        val = expand(raw, macros)
        if "/" in val or "://" in val:
            issues.append(Issue("E010", num, "Source must be a file name"))
            continue
        if val in seen:
            issues.append(Issue("E010", num, f"duplicate source: {val}"))
            continue
        seen.add(val)
        if val in gen:
            continue
        hits = index.get(val, set())
        if not hits:
            issues.append(Issue("E010", num, f"missing source: {val}"))
        elif len(hits) > 1:
            issues.append(Issue("E010", num, f"ambiguous source: {val}"))


def check_secs(secs: list[tuple[str, str, int]],
               issues: list[Issue]) -> None:
    names = [item[0] for item in secs]
    for name in MUST:
        if name not in names:
            issues.append(Issue("E007", 1, f"missing section: %{name}"))
    subs = names.count("package")
    if names.count("files") < subs + 1:
        issues.append(Issue("E009", 1, "subpackage without %files"))
    if names.count("description") < subs + 1:
        issues.append(Issue("E009", 1, "subpackage without %description"))


def check_files(lines: list[str], secs: list[tuple[str, str, int]],
                issues: list[Issue]) -> None:
    for pos, (name, _arg, num) in enumerate(secs):
        if name != "files":
            continue
        end = secs[pos + 1][2] - 1 if pos + 1 < len(secs) else len(lines)
        body = [strip_cmt(x) for x in lines[num:end]]
        body = [x for x in body if x]
        if not body:
            issues.append(Issue("E008", num, "%files section is empty"))
        elif not any(x.startswith(("/", "%")) for x in body):
            issues.append(Issue("E008", num, "%files has no path"))


def check_log(lines: list[str], secs: list[tuple[str, str, int]],
              issues: list[Issue]) -> None:
    logs = [item for item in secs if item[0] == "changelog"]
    if not logs:
        return
    num = logs[-1][2]
    body = [x for x in lines[num:] if x.strip()]
    if not body:
        issues.append(Issue("E011", num, "%changelog is empty"))
        return
    if not LOG.match(body[0].strip()):
        issues.append(Issue("E011", num + 1, "bad changelog header"))
    if len(body) < 2 or not body[1].lstrip().startswith("- "):
        issues.append(Issue("E011", num + 1, "missing changelog entry"))


def check_scan(lines: list[str], issues: list[Issue]) -> None:
    for num, raw in enumerate(lines, 1):
        if re.match(r"^%(?:define|undefine)\b", raw):
            issues.append(Issue("E005", num, "use %global, not %define"))
        if re.match(r"^BuildRoot\s*:", raw):
            issues.append(Issue("E006", num, "BuildRoot is forbidden"))
        if BAD.search(raw):
            issues.append(Issue("E013", num, "placeholder marker found"))


def check_ver(ver: str, root: Path, issues: list[Issue]) -> None:
    path = root / "release" / "os-release"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        issues.append(Issue("E012", 1, f"cannot read {path}"))
        return
    hit = re.search(r'^VERSION_ID="?([^"\n]+)"?$', text, re.M)
    if not hit:
        issues.append(Issue("E012", 1, "VERSION_ID missing in os-release"))
    elif hit.group(1) != ver:
        issues.append(Issue("E012", 1, f"version {ver} != "
                                       f"VERSION_ID {hit.group(1)}"))


def lint_text(text: str, path: Path, root: Path) -> list[Issue]:
    lines = text.splitlines()
    macros = collect_macros(lines)
    tags = parse_tags(lines)
    secs = parse_secs(lines)
    gen = parse_gen(lines)
    ver = expand(tags.get("Version", (0, ""))[1], macros)
    macros["version"] = ver
    issues: list[Issue] = []
    roots = [root]
    for num, extra in parse_roots(lines, path):
        if extra.is_dir():
            roots.append(extra)
        else:
            issues.append(Issue("E010", num, f"missing source root: {extra}"))
    check_tags(tags, ver, issues)
    check_name(tags, path, issues)
    check_srcs(tags, roots, macros, gen, issues)
    check_secs(secs, issues)
    check_files(lines, secs, issues)
    check_log(lines, secs, issues)
    check_scan(lines, issues)
    check_ver(ver, root, issues)
    return sorted(issues, key=lambda item: (item.line, item.code))


def lint_spec(path: Path, root: Path) -> list[Issue]:
    return lint_text(path.read_text(encoding="utf-8"), path, root)


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    targets = [Path(arg) for arg in argv[1:]]
    if not targets:
        targets = sorted((root / "specs").rglob("*.spec"))
    if not targets:
        print("spec_lint: no spec file found", file=sys.stderr)
        return 2
    total = 0
    for path in targets:
        try:
            issues = lint_spec(path, root)
        except OSError as err:
            print(f"spec_lint: {err}", file=sys.stderr)
            return 2
        total += dump(path, issues)
    return report("spec_lint", total)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
