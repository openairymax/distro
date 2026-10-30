#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# mirror_probe.py — 按实测吞吐给闭包镜像根排序
#
# 安装闭包要跨公网取约 2.5 GB。镜像表的行序是人工写的，与此刻哪台主机
# 可达、哪台被限速无关；求解端按行序逐个尝试，慢根与死根在日志里同形，
# 都要等到 step 时限才暴露（run 41039410608：三根在 15 分钟内被逐个放弃，
# 日志里只有「速率低于下限」，没有一行数字说明谁快谁慢）。
#
# 探测在求解之前做一次定长抽样，把「先试谁」从书写顺序改为实测吞吐。
# 抽样对象是该根 update 仓库的 primary.xml.gz：求解必须先拿到它，它也是
# 整段事务里第一个大件。元数据文件名带内容哈希，各根不一定相同，因此
# 先从 repomd.xml 读出真实路径再取首段；Range 只取前 1 MiB，超时即按已读
# 字节折算速率——被限速的根给不出更多数据，正是要测的量。
#
# 用法：
#   mirror_probe.py [--timeout S] [--floor KIB] [--span BYTES] ROOT...
#
# 输出：stdout 每行一个入选根的 URL，按实测速率降序；stderr 是完整测速表。
# 全部低于 --floor 时仍输出最快的一个——宁可比预期慢，也不猜地址——并以
# 退出码 3 告知调用方「没有根达标」。用法错误退出码 2。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import re
import sys
import time
import urllib.request

UA = {"User-Agent": "airy-closure-probe"}
# 固定取 x86_64 的 update 仓库：测的是同一台主机的链路，与包头架构无关。
REPO = "update/x86_64"
SPAN = 1 << 20
CHUNK = 1 << 16
HREF = re.compile(r'href="([^"]*primary\.xml\.gz)"')


def meta_of(root, timeout):
    """返回该根 primary.xml.gz 的地址；取不到 repomd 时返回空串。"""
    base = root.rstrip("/")
    url = "%s/%s/repodata/repomd.xml" % (base, REPO)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception:                            # noqa: BLE001 - 失败只表示没有样本
        return ""
    found = HREF.search(body)
    if not found:
        return ""
    return "%s/%s/%s" % (base, REPO, found.group(1))


def sample(root, timeout, span):
    """读最多 span 字节或 timeout 秒，返回 (速率 KiB/s, 字节数, 失败原因)。"""
    url = meta_of(root, timeout)
    if not url:
        return 0, 0, "repomd"
    req = urllib.request.Request(url, headers={
        "Range": "bytes=0-%d" % (span - 1), **UA})
    start, got, why = time.monotonic(), 0, ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            while got < span:
                chunk = resp.read(min(CHUNK, span - got))
                if not chunk:
                    break
                got += len(chunk)
                if time.monotonic() - start >= timeout:
                    break
    except Exception as exc:                     # noqa: BLE001 - 任何失败都只是样本缺失
        why = type(exc).__name__
    spent = max(time.monotonic() - start, 0.001)
    return int(got / 1024 / spent), got, why


def rank(rows, floor):
    """按速率降序排列 (速率, 根)；达标者全出，全不达标时只留最快的一个。"""
    rows = sorted(rows, key=lambda row: row[0], reverse=True)
    keep = [row for row in rows if row[0] >= floor]
    return keep or rows[:1]


def main(argv):
    timeout, floor, span, roots = 6.0, 256, SPAN, []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            print(__doc__ or "usage: mirror_probe.py [--timeout S] [--floor KIB] ROOT...")
            return 0
        if arg in ("--timeout", "--floor", "--span"):
            if i + 1 >= len(argv):
                print("缺少参数值: %s" % arg, file=sys.stderr)
                return 2
            try:
                value = float(argv[i + 1]) if arg == "--timeout" else int(argv[i + 1])
            except ValueError:
                print("参数不是数字: %s" % arg, file=sys.stderr)
                return 2
            if arg == "--timeout":
                timeout = value
            elif arg == "--floor":
                floor = value
            else:
                span = value
            i += 2
            continue
        if arg.startswith("-"):
            print("未知选项: %s" % arg, file=sys.stderr)
            return 2
        roots.append(arg)
        i += 1
    if not roots:
        print("至少需要一个镜像根", file=sys.stderr)
        return 2
    rows = []
    for root in roots:
        rate, got, why = sample(root, timeout, span)
        rows.append((rate, root))
        print("%6d KiB/s  %8d B  %s%s"
              % (rate, got, root, "  (%s)" % why if why else ""), file=sys.stderr)
    picked = rank(rows, floor)
    for _, root in picked:
        print(root)
    if picked and picked[0][0] < floor:
        print("没有镜像根达到 %d KiB/s，只用最快的一个" % floor, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
