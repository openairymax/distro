#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# preset_lint.py — AirymaxOS systemd preset 静态校验
#
# 校验对象是 distro/presets 下随 airymaxos-system 落盘的启用策略，确保
# 自有单元不会因 systemctl preset-all 的默认 enable 语义被意外拉起：
#   1. 全部含 [Install] 段的自有单元必须被 disable 覆盖（P003）；
#   2. 禁止 enable/ignore 命中自有单元（P004）；
#   3. 指令必须命中至少一个单元，避免拼写漂移与过期条目（P005）；
#   4. 文本与权限卫生（P006）。
# 单元集合取自 system/units；与该目录的增删保持同源，不维护第二份清单。
#
# 规则编号 P001~P006 与 tools/tests/test_preset_lint.py 一一对应。
# 退出码：0 通过；1 存在问题；2 用法或读取错误。
#
# Author: Decheng Li <lidecheng@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import fnmatch
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lint_common import Issue, dump, report

DIRECTIVE = re.compile(r"^(enable|disable|ignore)(?:\s+(.*))?$")
TYPES = (".service", ".target")
ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "presets" / "90-airymax.preset"
UNITS = ROOT.parent / "system" / "units"


@dataclass(frozen=True)
class Rule:
    line: int
    action: str
    pattern: str


def has_install(text: str) -> bool:
    sect = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            sect = line
        elif sect == "[Install]" and line and not line.startswith("#"):
            return True
    return False


def read_units(path: Path) -> dict[str, bool]:
    units: dict[str, bool] = {}
    for item in sorted(path.iterdir()):
        if item.suffix in TYPES and item.is_file():
            units[item.name] = has_install(
                item.read_text(encoding="utf-8"))
    return units


def parse(text: str) -> tuple[list[Rule], list[Issue]]:
    rules: list[Rule] = []
    issues: list[Issue] = []
    for num, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        hit = DIRECTIVE.match(line)
        if not hit:
            issues.append(Issue("P002", num, f"invalid directive: {line}"))
            continue
        body = (hit.group(2) or "").strip()
        if not body:
            issues.append(Issue("P002", num, f"empty pattern: {line}"))
            continue
        for pattern in body.split():
            rules.append(Rule(num, hit.group(1), pattern))
    return rules, issues


def hit_units(rule: Rule, units: Mapping[str, bool]) -> list[str]:
    return [name for name in units if fnmatch.fnmatchcase(name, rule.pattern)]


def check_cover(rules: list[Rule], units: Mapping[str, bool],
                issues: list[Issue]) -> None:
    off = [rule for rule in rules if rule.action == "disable"]
    for name in sorted(units):
        if not units[name]:
            continue
        if not any(fnmatch.fnmatchcase(name, rule.pattern) for rule in off):
            issues.append(Issue("P003", 1, f"unit not pinned off: {name}"))


def check_deny(rules: list[Rule], units: Mapping[str, bool],
               issues: list[Issue]) -> None:
    for rule in rules:
        if rule.action == "disable":
            continue
        for name in hit_units(rule, units):
            issues.append(Issue("P004", rule.line,
                                f"{rule.action} hits own unit: {name}"))


def check_stale(rules: list[Rule], units: Mapping[str, bool],
                issues: list[Issue]) -> None:
    for rule in rules:
        if not hit_units(rule, units):
            issues.append(Issue("P005", rule.line,
                                f"pattern matches no unit: {rule.pattern}"))


def check_text(raw: bytes, mode: int, issues: list[Issue]) -> None:
    if b"\r\n" in raw:
        issues.append(Issue("P006", 1, "CRLF line ending"))
    if b"\t" in raw:
        issues.append(Issue("P006", 1, "tab character"))
    if raw and not raw.endswith(b"\n"):
        issues.append(Issue("P006", 1, "missing final newline"))
    if raw.endswith(b"\n\n"):
        issues.append(Issue("P006", 1, "trailing blank line"))
    text = raw.decode("utf-8")
    for num, line in enumerate(text.splitlines(), 1):
        if line != line.rstrip():
            issues.append(Issue("P006", num, "trailing whitespace"))
    if mode & 0o777 != 0o644:
        issues.append(Issue("P006", 1, f"mode {mode & 0o777:04o} != 0644"))


def lint_text(text: str, units: Mapping[str, bool]) -> list[Issue]:
    rules, issues = parse(text)
    check_cover(rules, units, issues)
    check_deny(rules, units, issues)
    check_stale(rules, units, issues)
    return issues


def lint_file(preset: Path, units_dir: Path) -> list[Issue]:
    raw = preset.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as err:
        return [Issue("P001", 1, f"not UTF-8: {err.reason}")]
    issues: list[Issue] = []
    check_text(raw, preset.stat().st_mode, issues)
    issues.extend(lint_text(text, read_units(units_dir)))
    return sorted(issues, key=lambda item: (item.line, item.code))


def main(argv: list[str]) -> int:
    preset = Path(argv[1]) if len(argv) > 1 else DEFAULT
    units = Path(argv[2]) if len(argv) > 2 else UNITS
    if not units.is_dir():
        print(f"preset_lint: missing unit directory: {units}", file=sys.stderr)
        return 2
    try:
        issues = lint_file(preset, units)
    except OSError as err:
        print(f"preset_lint: {err}", file=sys.stderr)
        return 2
    return report("preset_lint", dump(preset, issues))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
