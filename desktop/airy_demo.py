#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airy_demo.py — 终端内的能力总览（安装为 /usr/bin/airy-demo）
#
# 为什么要有它：验收与对外展示都要回答同一个问题——「这台机器强在哪、证据
# 在哪一行」。此前证据散在 airy-observe 的 key=value 与 airy-bench 的若干
# 数字里，谁看谁自己拼；拼接过程不可复现，也就不能算证据。这里把两者按
# 固定顺序串成一份屏幕报告，顺序、单位、比较基准都写死在本文件里。
#
# 关键约束：本脚本不产生任何新数字。身份字段来自 airy-observe，延迟、吞吐
# 与并发标度来自 airy-bench，屏幕上每一行都能被那两个命令单独复算，因此
# 结论不依赖本文件的可信度。新增指标只能加在生产者一侧，禁止在此估算。
#
# 打印随数据到达即发生：airy-bench 按段测量、按段输出，本脚本一收到就对
# 应成行，等待期间终端持续有新内容，实机排障时不必猜进程是否还活着。三段
# 往返延迟共用一个基准画条，因此先攒齐三行再一次性画出，其余各段即时打印。
#
# 并发段做两次：一次是 airy-bench 自带的等核数测量，一次是本脚本按 1/2/4/8
# 进程递增重跑，用来给出手工可对的缩放曲线——单点数字看不出「加进程是否
# 还有收益」，曲线能。
#
# 非 TTY（管道、CI 日志）自动去色，并遵循 NO_COLOR；末行固定
# status=ok|degraded，调用方只判这一行即可。
#
# 依赖：python3（POSIX，无第三方模块）、同目录或 PATH 中的 airy-bench 与
# airy-observe。
# ===========================================================================

import argparse
import os
import shutil
import subprocess
import sys

MARK = "AIRYMAX-DEMO"
WANT_ID = "airymaxos"
WIDTH = 18
RULE = 74
HERE = os.path.dirname(os.path.abspath(__file__))
PEERS = {"airy-bench": "airy_bench.py", "airy-observe": "airy_observe.sh"}
OB_MARK = "AIRYMAX-OBSERVE"
BENCH_MARK = "AIRYMAX-BENCH"
SHOWN = (
    "os.id",
    "os.pretty",
    "host.name",
    "kernel.release",
    "kernel.owner",
    "cpu.count",
    "mem.total_kb",
    "display.outputs",
    "desktop.ready",
    "boot.health",
    "rt.budget",
    "net.ipv4",
)
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def rule() -> None:
    print(paint("-" * RULE, "2"))


def title(text: str) -> None:
    print()
    print(paint(text, "1;36"))


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "~"


def human(value: str) -> str:
    num = float(value)
    for unit in ("", "k", "M"):
        if num < 1000:
            return f"{num:.0f}{unit}"
        num /= 1000
    return f"{num:.1f}G"


def bar(value: float, top: float) -> str:
    fill = 0 if top <= 0 else min(WIDTH, int(round(value / top * WIDTH)))
    return "\u2588" * fill + "\u2591" * (WIDTH - fill)


def peer(name: str) -> list:
    found = shutil.which(name)
    if found:
        return [found]
    alt = os.path.join(HERE, PEERS[name])
    if not os.path.exists(alt):
        return []
    return ["/bin/sh", alt] if alt.endswith(".sh") else [sys.executable, alt]


def split(line: str, mark: str):
    if not line.startswith(mark + " "):
        return None
    head = None
    pairs = {}
    for token in line[len(mark) + 1:].split(" "):
        key, sep, val = token.partition("=")
        if sep:
            pairs[key] = val
        elif head is None:
            head = key
    return head, pairs


def stream(argv: list, mark: str, sink) -> bool:
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace",
    )
    for line in proc.stdout:
        pair = split(line.rstrip("\n"), mark)
        if pair:
            sink(*pair)
    detail = proc.stderr.read().strip().splitlines()
    proc.stdout.close()
    proc.stderr.close()
    rc = proc.wait()
    if rc != 0:
        tail = detail[-1] if detail else "no-detail"
        print(paint(f"  {os.path.basename(argv[0])} exit={rc} {tail}", "31"))
    return rc == 0


def greet() -> bool:
    argv = peer("airy-observe")
    if not argv:
        print(paint("  airy-observe 缺失，无法读取身份", "31"))
        return False
    space = {}

    def sock(head, pairs):
        space.update(pairs)

    stream(argv, OB_MARK, sock)
    title("身份与品牌")
    keys = [k for k in SHOWN if k != "mem.total_kb"] + ["mem.total_kb"]
    for key in keys:
        val = space.get(key, "absent").strip('"')
        if key == "mem.total_kb" and val.isdigit():
            val = f"{int(val) / (1 << 20):.1f} GiB"
        space[key] = val
    for i in range(0, len(keys), 2):
        cell = f"  {paint(f'{keys[i]:<15}', '2')} {clip(space[keys[i]], 24):<24}"
        if i + 1 < len(keys):
            left = clip(space[keys[i + 1]], 24)
            cell += f" {paint(f'{keys[i + 1]:<15}', '2')} {left}"
        print(cell)
    # 身份按取值判定，不按字段是否存在判定：观察点少了某个展示项只能说明
    # 这一行没显示，不能说明这台机器不是 AirymaxOS。判据只认 os.id 与发
    # 行标识是否一致，其余字段缺了就缺了，屏幕上照实显示 absent。
    return space.get("os.id") == WANT_ID


def show_rows(state: dict) -> None:
    if not state["rows"]:
        return
    top = max(row[3] for row in state["rows"])
    for kind, p50, p99, rate in state["rows"]:
        print(
            f"  {kind:<7} p50 {p50:>7} us  p99 {p99:>7} us  "
            f"{bar(rate, top)}  {human(rate)} rt/s"
        )
    state["rows"] = []


def on_rtt(head, pairs, state):
    if not state["rows"]:
        title("IPC 往返延迟（单字节，含 python3 解释器开销）")
    state["rows"].append(
        (head, pairs.get("rtt_p50_us", "0"), pairs.get("rtt_p99_us", "0"),
         float(pairs.get("rate", "0")))
    )


def on_msgs(head, pairs, state):
    show_rows(state)
    title("消息边界与批量搬运")
    print(
        f"  {pairs.get('kind', '?'):<7} {pairs.get('count', '?')} 条 × "
        f"{pairs.get('size', '?')} B  {human(pairs.get('rate', '0'))} msg/s"
    )


def on_bulk(head, pairs, state):
    print(
        f"  pipe    {int(pairs.get('bytes', '0')) >> 20} MiB 单次搬运  "
        f"{pairs.get('mib_s', '?')} MiB/s"
    )


def on_fork(head, pairs, state):
    show_rows(state)
    print(
        f"  {pairs.get('procs', '?')} 进程 × {pairs.get('ops_per_proc', '?')} 次往返  "
        f"聚合 {human(pairs.get('rate', '0'))} rt/s  "
        f"相对单进程 {pairs.get('scale', '?')}x"
    )


def on_host(head, pairs, state):
    state["cpu"] = pairs.get("cpu", "?")
    print()
    print(
        paint(
            f"  测量基线与身份同机同次：{pairs.get('kernel', '?')} / "
            f"{state['cpu']} 核 / 每段 {pairs.get('ops', '?')} 次采样", "2"))


HANDLERS = {
    "host": on_host,
    "pipe": on_rtt,
    "stream": on_rtt,
    "dgram": on_rtt,
    "msgs": on_msgs,
    "bulk": on_bulk,
    "fork": on_fork,
}


def bench(argv: list, state: dict) -> bool:
    def sock(head, pairs):
        handler = HANDLERS.get(head)
        if handler:
            handler(head, pairs, state)

    ok = stream(argv, BENCH_MARK, sock)
    show_rows(state)
    return ok


def median(procs: int, argv: list) -> float:
    got = []
    for _ in range(3):
        box = {"rate": 0.0}

        def sock(head, pairs, box=box):
            if head == "fork":
                box["rate"] = float(pairs.get("rate", "0"))

        stream(argv + ["--ops", "2000", "--bulk-mib", "1", "--procs", str(procs)],
               BENCH_MARK, sock)
        got.append(box["rate"])
    return sorted(got)[1]


def sweep(cpu: str) -> None:
    argv = peer("airy-bench")
    if not argv:
        return
    cores = int(cpu) if str(cpu).isdigit() else 8
    levels = [p for p in (1, 2, 4, 8) if p <= cores] or [1]
    title("并发缩放（同机递增进程数，逐级三次取中位）")
    rows = [(procs, median(procs, argv)) for procs in levels]
    top = max(row[1] for row in rows)
    base = rows[0][1] or 1.0
    for procs, rate in rows:
        print(
            f"  {procs:>2} 进程  {bar(rate, top)}  {human(rate):>7} rt/s  "
            f"{rate / base:.2f}x"
        )


def selfcheck() -> int:
    status = "ok"
    print(f"{MARK} check python={sys.version.split()[0]}")
    for name in PEERS:
        argv = peer(name)
        print(f"{MARK} check {name}={'present' if argv else 'absent'}")
        if not argv:
            status = "degraded"
    print(f"{MARK} check tty={1 if sys.stdout.isatty() else 0}")
    print(f"{MARK} mode=check")
    print(f"{MARK} status={status}")
    return 0 if status == "ok" else 1


def hints() -> None:
    # 每行都能被单独复算：前六行取上方同一批字段，后四行是同一事实的标准
    # 工具入口。展示完就给出复算方法，读的人不必相信这段输出，也不必记住
    # 命令。命令列宽固定，长命令溢出时靠一格空格分隔，不挤掉说明。
    title("复算入口（逐行可执行，与上方输出同源）")
    for cmd, desc in (
        ("airy-observe --section kernel", "内核归属/构建/模块/命令行"),
        ("airy-observe --section os", "发行版/包数/SELinux"),
        ("airy-observe --section boot", "固件/GRUB/默认 target/启动耗时"),
        ("airy-observe --section net", "地址/网关/DNS/链路"),
        ("airy-observe --section sched", "loadavg/实时预算/时钟节拍"),
        ("airy-bench --ops 20000", "原始分位与并发标度"),
        ("rpm -qf /boot/vmlinuz-$(uname -r)", "内核包归属 kernel.owner"),
        ("systemd-analyze", "启动耗时 boot.total"),
        ("systemctl list-units --failed", "失败单元 boot.failed"),
        ("airy-record --tty -- airy-demo", "终端会话可回放录制"),
    ):
        print("  " + paint(f"{cmd:<34} {desc}", "2"))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="airy-demo",
        description="Terminal overview of AirymaxOS identity and IPC capability",
    )
    parser.add_argument("--ops", type=int, default=20000)
    parser.add_argument("--no-sweep", action="store_true")
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    global COLOR
    if args.plain:
        COLOR = False
    if args.check:
        return selfcheck()

    good = greet()
    argv = peer("airy-bench")
    if not argv:
        print(paint("  airy-bench 缺失，无法测量", "31"))
        print(f"{MARK} status=degraded")
        return 1

    state = {"cpu": "?", "rows": []}
    good = bench(argv + ["--ops", str(args.ops)], state) and good
    if not args.no_sweep:
        sweep(state["cpu"])

    hints()
    print()
    rule()
    print(f"{MARK} status={'ok' if good else 'degraded'}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
