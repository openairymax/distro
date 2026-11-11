#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# head_lint.py — 源文件头版本一致性校验
#
# distro 下每个带设计说明横幅的源文件都在头部声明 `# Author:` 与
# `# Version:`。这两个字段是人工维护的第二份事实：版本号本来只有三个权威
# 来源——release/os-release 的 VERSION_ID（发行版本）、配方的 airy_version
# 宏（包版本）、git 标签（历史）。横幅里的版本号不参与任何构建，因此没有任何
# 机制阻止它陈旧：0.0.4 冻结时 58 份横幅里有 24 份仍写着 0.0.3 与 0.0.1，
# 另有一份提前写成 0.0.5。读者据此判断「这个工具属于哪一版」时得到的是错答案，
# 而构建与验收全绿，漂移不会被任何门禁发现。
#
# 本校验把横幅版本绑到发布版本上，让漂移在提交期而不是阅读期暴露：
#   H001 有作者横幅却缺 `# Version:`（字段少一半，读者无从判断）
#   H002 `# Version:` 与 release/os-release 的 VERSION_ID 不等
#
# 配方里的包版本不在这里查：spec_lint 的 E012 已把每个配方的 Version 展开后
# 与同一个 VERSION_ID 比对，而 airymaxos-release 的 Version 就是
# %{airy_version}，两处规则若都写一遍，改口径时必然漏改一处。
#
# 只校验已经带横幅的文件，不强制新文件加横幅：横幅是设计说明的载体，短小
# 工具无需为了凑字段写一段空话。判定依据是有没有 `# Author:` 行——它与
# `# Version:` 在这批文件里始终成对出现，单独存在任一都是缺陷。
#
# 扫描范围是本仓库自有源码目录（不含 tests/fixture 里被夹具构造的假源文件）。
# 规则编号 H001~H002 与 tools/tests/test_head_lint.py 一一对应。
# 退出码：0 通过；1 存在问题；2 读取错误。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

from __future__ import annotations

import re
import sys
from pathlib import Path

from lint_common import Issue

ROOT = Path(__file__).resolve().parent.parent
OS_REL = ROOT / "release" / "os-release"
SCAN = ("specs", "tools", "scripts", "ci", "boot", "desktop", "firmware",
        "kickstart", "login", "network", "ostree")
SUFFIX = (".py", ".sh", ".spec")
# 横幅位于文件头，设计说明最长的一份也不足 80 行；再往后找会开始命中正文里的
# 示例注释，把「文档里提到的版本」当成声明值。
DEPTH = 80

AUTHOR = re.compile(r"^# Author: ")
VERSION = re.compile(r"^# Version: (\S+)$")


def rel_ver(path: Path) -> str:
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("VERSION_ID="):
            return raw.split("=", 1)[1].strip().strip('"')
    raise ValueError(f"{path}: VERSION_ID absent")


def banner(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def judge(want: str, lines: list[str]) -> list[Issue]:
    # 截断在判定这一侧做，不在读文件那一侧：深度约束是判定规则的一部分，
    # 放在 judge 里才能被单测直接覆盖。
    lines = lines[:DEPTH]
    found: list[Issue] = []
    author = next((i for i, l in enumerate(lines, 1) if AUTHOR.match(l)), 0)
    versions = [(i, VERSION.match(l).group(1))
                for i, l in enumerate(lines, 1) if VERSION.match(l)]
    if author and not versions:
        found.append(Issue("H001", author, "banner without '# Version:'"))
    found += [Issue("H002", i, f"banner version {got} != {want}")
              for i, got in versions if got != want]
    return found


def sources() -> list[Path]:
    files: list[Path] = []
    for name in SCAN:
        base = ROOT / name
        if not base.is_dir():
            continue
        files += [p for p in sorted(base.rglob("*"))
                  if p.is_file() and p.suffix in SUFFIX]
    return files


def main() -> int:
    try:
        want = rel_ver(OS_REL)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    files = sources()
    total = 0
    for path in files:
        for issue in judge(want, banner(path)):
            print(f"{path}:{issue.line}: {issue.code} {issue.msg}")
            total += 1
    print(f"head: {len(files)} file(s), {total} issue(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
