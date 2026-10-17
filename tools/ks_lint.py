#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# ks_lint.py — AirymaxOS kickstart 静态校验
#
# 只依赖标准库。校验对象是无人值守安装的语法与安全性约束：安装源、
# 存储布局、账户口令、仓库传输、脚本段闭合与失败即停、收尾状态、
# 单例命令与安装界面互斥。包组引用（@组 / @^环境）由 comps_lint 交叉
# 校验，此处不重复实现。规则编号 K001~K012 与 tools/tests/test_ks_lint.py
# 一一对应。
#
# 退出码：0 通过；1 存在问题；2 用法或读取错误。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from lint_common import Issue, dump, report

SOURCES = frozenset({"cdrom", "harddrive", "nfs", "url", "hmc", "liveimg",
                     "ostreesetup"})
STORAGE = frozenset({"part", "partition", "logvol", "volgroup", "raid",
                     "btrfs"})
SINGLETON = frozenset({"lang", "keyboard", "timezone", "bootloader",
                       "rootpw", "clearpart", "autopart"})
STOP = frozenset({"reboot", "poweroff", "halt", "shutdown"})
SCRIPTS = frozenset({"pre", "post", "onerror", "traceback"})
SECTIONS = SCRIPTS | {"packages", "anaconda", "addon"}
REQUIRED = ("lang", "keyboard", "timezone", "bootloader")
SCHEME = ("https://", "file://")


@dataclass
class Cmd:
    num: int
    name: str
    args: str


@dataclass
class Sect:
    name: str
    num: int
    opts: str
    body: list[tuple[int, str]] = field(default_factory=list)


def uncomment(raw: str) -> str:
    out: list[str] = []
    quote = False
    for char in raw:
        if char == '"':
            quote = not quote
        elif char == "#" and not quote:
            break
        out.append(char)
    return "".join(out).strip()


def split_cmd(line: str, num: int) -> Cmd:
    name, _, args = line.partition(" ")
    return Cmd(num, name, args.strip())


def open_sect(line: str, num: int, cur: Sect | None,
              issues: list[Issue]) -> Sect:
    word, _, opts = line.partition(" ")
    tag = word[1:]
    if cur is not None:
        issues.append(Issue("K001", num, f"%{tag} inside %{cur.name}"))
    if tag not in SECTIONS:
        issues.append(Issue("K001", num, f"unknown section %{tag}"))
    return Sect(tag, num, opts.strip())


def close_sect(num: int, cur: Sect | None, sects: list[Sect],
               issues: list[Issue]) -> None:
    if cur is None:
        issues.append(Issue("K001", num, "%end without section"))
        return
    sects.append(cur)


def parse(lines: list[str]) -> tuple[list[Cmd], list[Sect],
                                    list[Issue]]:
    cmds: list[Cmd] = []
    sects: list[Sect] = []
    issues: list[Issue] = []
    cur: Sect | None = None
    for num, raw in enumerate(lines, 1):
        line = uncomment(raw)
        if not line:
            continue
        if line.startswith("%"):
            if line == "%end":
                close_sect(num, cur, sects, issues)
                cur = None
            else:
                cur = open_sect(line, num, cur, issues)
        elif cur is not None:
            cur.body.append((num, line))
        else:
            cmds.append(split_cmd(line, num))
    if cur is not None:
        issues.append(Issue("K001", cur.num, f"%{cur.name} not closed"))
        sects.append(cur)
    return cmds, sects, issues


def has_opt(args: str, opt: str) -> bool:
    return any(tok == opt or tok.startswith(opt + "=")
               for tok in args.split())


def opt_val(args: str, opt: str) -> str:
    for tok in args.split():
        if tok.startswith(opt + "="):
            return tok[len(opt) + 1:]
    return ""


def check_src(cmds: list[Cmd], issues: list[Issue]) -> None:
    srcs = [cmd for cmd in cmds if cmd.name in SOURCES]
    if not srcs:
        issues.append(Issue("K003", 1, "no install source"))
        return
    for cmd in srcs[1:]:
        issues.append(Issue("K002", cmd.num,
                            f"extra install source: {cmd.name}"))


def check_required(cmds: list[Cmd], sects: list[Sect],
                   issues: list[Issue]) -> None:
    names = {cmd.name for cmd in cmds}
    for name in REQUIRED:
        if name not in names:
            issues.append(Issue("K003", 1, f"missing command: {name}"))
    if not any(sect.name == "packages" for sect in sects):
        issues.append(Issue("K003", 1, "missing %packages"))


def check_storage(cmds: list[Cmd], issues: list[Issue]) -> None:
    auto = [cmd for cmd in cmds if cmd.name == "autopart"]
    expl = [cmd for cmd in cmds if cmd.name in STORAGE]
    if auto and expl:
        issues.append(Issue("K004", expl[0].num,
                            f"autopart conflicts with {expl[0].name}"))
    if not auto and not expl:
        issues.append(Issue("K004", 1, "no storage layout"))


def check_roots(cmds: list[Cmd], issues: list[Issue]) -> None:
    for cmd in cmds:
        if cmd.name not in ("rootpw", "user"):
            continue
        if has_opt(cmd.args, "--lock") or has_opt(cmd.args, "--iscrypted"):
            continue
        code = "K005" if cmd.name == "rootpw" else "K006"
        issues.append(Issue(code, cmd.num,
                            f"{cmd.name} without --lock/--iscrypted"))


def check_urls(cmds: list[Cmd], issues: list[Issue]) -> None:
    for cmd in cmds:
        if cmd.name == "repo" and not has_opt(cmd.args, "--name"):
            issues.append(Issue("K007", cmd.num, "repo without --name"))
        opt = {"url": "--url", "repo": "--baseurl"}.get(cmd.name)
        if opt is None:
            continue
        val = opt_val(cmd.args, opt)
        if not val:
            issues.append(Issue("K007", cmd.num, f"{cmd.name} without {opt}"))
        elif not val.startswith(SCHEME):
            issues.append(Issue("K007", cmd.num,
                                f"insecure {cmd.name}: {val}"))


def strict(body: list[tuple[int, str]]) -> bool:
    return any(line.split(";", 1)[0].strip() == "set -eu"
               for _, line in body)


def check_scripts(sects: list[Sect], issues: list[Issue]) -> None:
    for sect in sects:
        if sect.name not in SCRIPTS:
            continue
        if not strict(sect.body):
            issues.append(Issue("K008", sect.num,
                                f"%{sect.name} without set -eu"))
        if sect.name == "post" and not has_opt(sect.opts, "--log"):
            issues.append(Issue("K009", sect.num, "%post without --log"))


def check_stop(cmds: list[Cmd], issues: list[Issue]) -> None:
    stops = [cmd for cmd in cmds if cmd.name in STOP]
    if not cmds or not stops:
        issues.append(Issue("K010", 1, "missing reboot/poweroff"))
        return
    for cmd in stops[1:]:
        issues.append(Issue("K010", cmd.num, f"extra stop: {cmd.name}"))
    if cmds[-1].name not in STOP:
        issues.append(Issue("K010", cmds[-1].num,
                            f"{cmds[-1].name} after {stops[0].name}"))


def check_dup(cmds: list[Cmd], issues: list[Issue]) -> None:
    seen: set[str] = set()
    for cmd in cmds:
        if cmd.name not in SINGLETON:
            continue
        if cmd.name in seen:
            issues.append(Issue("K011", cmd.num, f"duplicate {cmd.name}"))
        seen.add(cmd.name)


def check_mode(cmds: list[Cmd], issues: list[Issue]) -> None:
    names = {cmd.name for cmd in cmds}
    if "text" in names and "graphical" in names:
        issues.append(Issue("K012", 1, "text and graphical both set"))


def lint_text(text: str) -> list[Issue]:
    cmds, sects, issues = parse(text.splitlines())
    check_src(cmds, issues)
    check_required(cmds, sects, issues)
    check_storage(cmds, issues)
    check_roots(cmds, issues)
    check_urls(cmds, issues)
    check_scripts(sects, issues)
    check_stop(cmds, issues)
    check_dup(cmds, issues)
    check_mode(cmds, issues)
    return sorted(issues, key=lambda item: (item.line, item.code))


def lint_ks(path: Path) -> list[Issue]:
    return lint_text(path.read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    base = Path(__file__).resolve().parent.parent
    targets = [Path(arg) for arg in argv[1:]]
    if not targets:
        targets = sorted((base / "kickstart").glob("*.ks"))
    if not targets:
        print("ks_lint: no kickstart file found", file=sys.stderr)
        return 2
    total = 0
    for path in targets:
        try:
            issues = lint_ks(path)
        except OSError as err:
            print(f"ks_lint: {err}", file=sys.stderr)
            return 2
        total += dump(path, issues)
    return report("ks_lint", total)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
