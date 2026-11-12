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
# 抽样对象是该根 update 仓库的主索引（primary.xml.gz 或 primary.xml.zst）：
# 求解必须先拿到它，它也是整段事务里第一个大件。元数据文件名带内容哈希，
# 各根不一定相同，因此先从 repomd.xml 读出真实路径再取首段；Range 只取前
# 1 MiB，超时即按已读字节折算速率——被限速的根给不出更多数据，正是要测的量。
#
# 用法：
#   mirror_probe.py [--timeout S] [--floor KIB] [--span BYTES] ROOT...
#
# 输出：stdout 每行一个根的 URL，按实测速率降序，一个都不丢；stderr 是完整
# 测速表。低于 --floor 的根只是排到后面，不再从候选里删除——它们是慢，不是
# 不可用。删减曾把「慢」变成「没有备用」：run 41616948930 里探测只留下腾讯云
# 一根，该根对 EPOL/update 返回 HTTP 567，求解随即没有任何根可换，整段构建
# 以「All mirrors were tried」告终，而其余五根当时都返回 200。没有任何根达标
# 时以退出码 3 告知调用方，排序照常输出。用法错误退出码 2。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
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
# 主索引的压缩格式随镜像演进：openEuler 24.03-SP2 已把 repodata 换成
# primary.xml.zst，仍按 .gz 匹配会让每个根都取不到样本、全部记为 0 KiB/s，
# 排序退回书写顺序——探测静默失效，日志里只看到「速率低于下限」。
HREF = re.compile(r'href="([^"]*primary\.xml\.(?:gz|zst))"')
USAGE = "usage: mirror_probe.py [--timeout S] [--floor KIB] ROOT..."


def meta_of(root, timeout):
    """返回该根主索引的地址；取不到 repomd 时返回空串。"""
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


def rank(rows):
    """按速率降序排列 (速率, 根)；只排序，不删除任何根。"""
    return sorted(rows, key=lambda row: row[0], reverse=True)


class BadArg(Exception):
    """用法错误：由 main 折成退出码 2，消息原样写 stderr。"""


class BadHelp(Exception):
    """请求帮助：打印用法并正常退出。"""


def take_opt(argv, i):
    """取一个带值选项 → (名字, 数值, 下一个下标)；缺值或非数字抛 BadArg。"""
    name = argv[i]
    if i + 1 >= len(argv):
        raise BadArg("缺少参数值: %s" % name)
    raw = argv[i + 1]
    try:
        value = float(raw) if name == "--timeout" else int(raw)
    except ValueError:
        raise BadArg("参数不是数字: %s" % name) from None
    return name, value, i + 2


def parse(argv):
    """解析命令行 → ({选项名: 数值}, [根...])。"""
    opts = {"--timeout": 6.0, "--floor": 256, "--span": SPAN}
    roots = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            raise BadHelp()
        if arg in ("--timeout", "--floor", "--span"):
            name, value, i = take_opt(argv, i)
            opts[name] = value
            continue
        if arg.startswith("-"):
            raise BadArg("未知选项: %s" % arg)
        roots.append(arg)
        i += 1
    if not roots:
        raise BadArg("至少需要一个镜像根")
    return opts, roots


def probe(roots, timeout, span):
    """逐根取样，测速表写 stderr，返回待排序的 (速率, 根) 行。"""
    rows = []
    for root in roots:
        rate, got, why = sample(root, timeout, span)
        rows.append((rate, root))
        print("%6d KiB/s  %8d B  %s%s"
              % (rate, got, root, "  (%s)" % why if why else ""),
              file=sys.stderr)
    return rows


def main(argv):
    try:
        opts, roots = parse(argv)
    except BadHelp:
        print(__doc__ or USAGE)
        return 0
    except BadArg as exc:
        print(str(exc), file=sys.stderr)
        return 2
    picked = rank(probe(roots, opts["--timeout"], opts["--span"]))
    for _, root in picked:
        print(root)
    if picked[0][0] < opts["--floor"]:
        print("没有镜像根达到 %d KiB/s，按实测速率降序全部保留"
              % opts["--floor"], file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
