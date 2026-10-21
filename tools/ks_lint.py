#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# ks_lint.py — AirymaxOS kickstart 静态校验
#
# 只依赖标准库。校验对象是无人值守安装的语法与安全性约束：安装源、
# 存储布局、账户口令（K005/K006：必须 --iscrypted $6$，禁止 --lock 与
# 明文）、脚本段闭合与失败即停、收尾状态、单例命令、安装界面互斥、
# 桌面仓库闭包完整性、离线仓库落点、内核包身份、上游身份包排除与命令行
# 参数语法。包组引用（@组 / @^环境）由 comps_lint 交叉校验，此处不重复
# 实现。规则编号 K001~K017 与 tools/tests/test_ks_lint.py 一一对应。
#
# 配方有两种姿态，判据不同：
#   构建期 — 安装源为上游 https，桌面环境要求四仓库齐全（K013）；
#   安装期 — 安装源为 file:// 载荷，只允许载荷仓库，多一个仓库即 K015。
# 姿态由安装源协议判定，同一份规则同时约束手写配方与投影产物。
#
# 退出码：0 通过；1 存在问题；2 用法或读取错误。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import shlex
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
SHA512 = "$6$"

# 桌面环境的安装闭包分布在四个上游仓库：ukui/lightdm/ukui-greeter 在
# EPOL，qt5-qtgraphicaleffects 等只在 everything；缺任一仓库时 Anaconda
# 解析包组即失败（M-15 安装闭包口径）。AirymaxOS 自建包由离线仓库供给，
# 其落点由 K015 单独约束。
DESKTOP_ENV = "@^airymax-workstation"
DESKTOP_REPOS = ("update", "epol", "epol-update", "everything")

# 离线仓库即安装闭包（M-15）：build-desktop.sh 以 createrepo_c 生成
# Packages 目录并注入 ISO 根 /airymax，安装期经 file:// 消费。所有剖面
# 都必须挂载它，否则 airymaxos-kernel 无法解析。
LOCAL_REPO = "airymaxos-offline"
VENDOR_URL = "file:///run/install/repo/airymax/Packages"

# 内核包身份（M-15）：安装期必须显式落在 AirymaxOS 内核上。上游 kernel
# 不含 Airymax 补丁，且与本包争用同一组文件路径；kickstart 一旦请求上游
# 包，dnf 只能靠 Obsoletes/Provides 兜底，结果依赖解析顺序而不可判定。
KERNEL_PKG = "airymaxos-kernel"
KERNEL_STOCK = "kernel"

# 上游身份包（K017）：桌面环境与上游包组会带入 kernel、kernel-tools
# （上游 core 组 mandatory / default），并携带 openEuler-release 与
# openEuler-latest-release。它们与本产品 airymaxos-kernel /
# airymaxos-release 争用同一组文件路径和 system-release 能力，不排除时
# dnf 只能按求解顺序二选一。
UPSTREAM_EXCLUDES = ("-kernel", "-kernel-tools", "-openEuler-release",
                     "-openEuler-latest-release")

# 允许裸参数（位置参数）的命令。pykickstart 只在少数命令上接受位置参数，
# 其余命令的每个词都必须是 --opt / --opt=value；把列表值写成空格分隔时
# 第二个词即落到这里，anaconda 在解析阶段终止安装。
BARE = frozenset({"lang", "keyboard", "timezone", "rootpw", "part",
                  "partition", "raid", "logvol", "volgroup", "btrfs",
                  "device", "driverdisk", "sshkey"})

# openEuler 24.03 的 anaconda 36 中 user 命令的选项集合（备注字段是
# --gecos，不存在 --comment）；未知选项同样令解析终止。
USER_OPTS = frozenset({"--name", "--gecos", "--groups", "--homedir",
                       "--lock", "--iscrypted", "--password", "--plaintext",
                       "--shell", "--uid", "--gid"})


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


def last_arg(args: str) -> str:
    return next((tok for tok in reversed(args.split())
                 if not tok.startswith("--")), "")


def check_rootpw(cmd: Cmd, issues: list[Issue]) -> None:
    if has_opt(cmd.args, "--lock"):
        issues.append(Issue("K005", cmd.num, "rootpw locked: no login"))
        return
    val = last_arg(cmd.args)
    if not has_opt(cmd.args, "--iscrypted") or not val.startswith(SHA512):
        issues.append(Issue("K005", cmd.num,
                            "rootpw must use --iscrypted $6$ hash"))


def check_user(cmd: Cmd, issues: list[Issue]) -> None:
    if has_opt(cmd.args, "--lock"):
        issues.append(Issue("K006", cmd.num, "user locked: no login"))
        return
    val = opt_val(cmd.args, "--password")
    if not has_opt(cmd.args, "--iscrypted") or not val.startswith(SHA512):
        issues.append(Issue("K006", cmd.num,
                            "user must use --iscrypted --password=$6$"))


def check_roots(cmds: list[Cmd], issues: list[Issue]) -> None:
    for cmd in cmds:
        if cmd.name == "rootpw":
            check_rootpw(cmd, issues)
        elif cmd.name == "user":
            check_user(cmd, issues)


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


def pkg_names(body: list[tuple[int, str]]) -> set[str]:
    return {line.split(".", 1)[0] for _, line in body
            if not line.startswith(("-", "@"))}


def stock_kernel(name: str) -> bool:
    return name == KERNEL_STOCK or name.startswith(KERNEL_STOCK + "-")


def check_kernel(sects: list[Sect], issues: list[Issue]) -> None:
    for sect in sects:
        if sect.name != "packages":
            continue
        for num, line in sect.body:
            if line.startswith("-"):
                continue
            if stock_kernel(line.split(".", 1)[0]):
                issues.append(Issue("K014", num,
                                    f"upstream kernel package: {line}"))
        if KERNEL_PKG not in pkg_names(sect.body):
            issues.append(Issue("K014", sect.num,
                                f"%packages must include {KERNEL_PKG}"))


def check_excludes(sects: list[Sect], issues: list[Issue]) -> None:
    for sect in sects:
        if sect.name != "packages":
            continue
        body = {line for _, line in sect.body}
        for want in UPSTREAM_EXCLUDES:
            if want not in body:
                issues.append(Issue("K017", sect.num,
                                    f"%packages must list {want}"))


def pkg_set(sects: list[Sect]) -> set[str]:
    return {line for sect in sects if sect.name == "packages"
            for _, line in sect.body}


def repo_map(cmds: list[Cmd]) -> dict[str, Cmd]:
    return {opt_val(cmd.args, "--name"): cmd
            for cmd in cmds if cmd.name == "repo"}


def check_repo(name: str, cmd: Cmd | None, issues: list[Issue]) -> None:
    if cmd is None:
        issues.append(Issue("K013", 1, f"desktop repo missing: {name}"))
        return
    url = opt_val(cmd.args, "--baseurl")
    if url and "$basearch" not in url:
        issues.append(Issue("K013", cmd.num,
                            f"repo {name} url needs $basearch"))


def check_repos(cmds: list[Cmd], sects: list[Sect],
                issues: list[Issue]) -> None:
    if is_offline(cmds) or DESKTOP_ENV not in pkg_set(sects):
        return
    repos = repo_map(cmds)
    for name in DESKTOP_REPOS:
        check_repo(name, repos.get(name), issues)
    for cmd in cmds:
        if cmd.name == "url" and "$basearch" not in opt_val(cmd.args, "--url"):
            issues.append(Issue("K013", cmd.num,
                                "install url needs $basearch"))


def src_cmd(cmds: list[Cmd]) -> Cmd | None:
    return next((cmd for cmd in cmds if cmd.name in SOURCES), None)


def is_offline(cmds: list[Cmd]) -> bool:
    cmd = src_cmd(cmds)
    return (cmd is not None and cmd.name == "url"
            and opt_val(cmd.args, "--url").startswith("file://"))


def check_vendor(cmds: list[Cmd], issues: list[Issue]) -> None:
    cmd = repo_map(cmds).get(LOCAL_REPO)
    if cmd is None:
        issues.append(Issue("K015", 1, f"missing offline repo: {LOCAL_REPO}"))
        return
    url = opt_val(cmd.args, "--baseurl")
    if url != VENDOR_URL:
        issues.append(Issue("K015", cmd.num,
                            f"{LOCAL_REPO} must use {VENDOR_URL}"))
        return
    if is_offline(cmds):
        check_off_src(cmds, issues)


def check_off_src(cmds: list[Cmd], issues: list[Issue]) -> None:
    for cmd in cmds:
        if cmd.name == "url" and opt_val(cmd.args, "--url") != VENDOR_URL:
            issues.append(Issue("K015", cmd.num,
                                "offline source must be the payload"))
        elif cmd.name == "repo" and opt_val(cmd.args, "--name") != LOCAL_REPO:
            issues.append(Issue("K015", cmd.num,
                                "offline recipe must not add repos"))


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


def arg_issue(cmd: Cmd, tok: str, issues: list[Issue]) -> None:
    if not tok.startswith("-"):
        if cmd.name not in BARE:
            issues.append(Issue("K016", cmd.num, f"stray argument: {tok}"))
        return
    opt = tok.split("=", 1)[0]
    if cmd.name == "user" and opt not in USER_OPTS:
        issues.append(Issue("K016", cmd.num, f"unknown user option: {opt}"))


def check_args(cmds: list[Cmd], issues: list[Issue]) -> None:
    for cmd in cmds:
        try:
            toks = shlex.split(cmd.args)
        except ValueError:
            issues.append(Issue("K016", cmd.num,
                                f"unbalanced quote: {cmd.name}"))
            continue
        for tok in toks:
            arg_issue(cmd, tok, issues)


def lint_text(text: str) -> list[Issue]:
    cmds, sects, issues = parse(text.splitlines())
    check_src(cmds, issues)
    check_required(cmds, sects, issues)
    check_storage(cmds, issues)
    check_roots(cmds, issues)
    check_urls(cmds, issues)
    check_kernel(sects, issues)
    check_excludes(sects, issues)
    check_repos(cmds, sects, issues)
    check_vendor(cmds, issues)
    check_scripts(sects, issues)
    check_stop(cmds, issues)
    check_dup(cmds, issues)
    check_mode(cmds, issues)
    check_args(cmds, issues)
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
