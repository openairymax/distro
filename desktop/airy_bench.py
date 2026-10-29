#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airy_bench.py — 内核 IPC 与并发能力实测（安装为 /usr/bin/airy-bench）
#
# 为什么要内置：AirymaxOS 的设计主张之一是「消息传递是系统的主干道」，
# 但既能被引用又能被复算的证据此前只有「功能能用」。任何一句「IPC 很快」
# 都不构成工程结论——必须给出在同一台机器上、由同一段代码测出的延迟分位
# 与并发标度，且测量本身可被第三方重放。
#
# 测量的三段都是系统调用路径本身，不做任何应用层封装：
#   pipe   单字节往返（双向管道），代表内核缓冲区的最小同步代价；
#   stream AF_UNIX 有连接字节流单字节往返，代表本地 RPC 的主路径；
#   dgram  AF_UNIX 数据报单字节往返，代表消息边界被保留的路径；
#   bulk   64 KiB 块经管道单向搬运，代表拷贝吞吐而非调度延迟。
#
# 并发段用 N 个进程各持一对 socketpair 同时往返，报告聚合速率与相对单进程
# 的标度。标度不等于核数：本机若是 8 核而标度显著低于 8，说明瓶颈在别处
# （调度、缓存行、或进程未被分散到不同核），这正是要观测的东西。
#
# 所有数字都是本次运行实测：分位取自逐次采样排序，速率取自总耗时，不做
# 任何外推、取整或平滑。丢弃前 1000 次预热采样，避免把首次缺页算进分位。
#
# 数字含解释器开销：跑在 python3 上，每次往返多一次 GIL 交接与对象分配，
# 因此这里的 p50 是「应用可见的往返代价」而非纯系统调用代价，`host` 行用
# lang=python3 显式标明。同一台机器上不同原语之间的相对关系仍可比，跨机器
# 比较时必须带上同一行。
#
# 输出与 airy-observe 同一口径：MARK 前缀 + 固定 key=value，末两行固定为
# fields 与 status。--check 只自检运行环境不测速，用于装机后先确认可跑。
#
# 依赖：python3（POSIX，无第三方模块）、/proc。
# ===========================================================================

import argparse
import multiprocessing
import os
import socket
import sys
import threading
import time

MARK = "AIRYMAX-BENCH"
CHUNK = 65536
WARM = 1000


def say(text: str) -> None:
    print(f"{MARK} {text}", flush=True)


def emit(key: str, **fields: object) -> None:
    body = " ".join(f"{k}={v}" for k, v in fields.items())
    say(f"{key} {body}")


def pair(kind: str):
    if kind == "pipe":
        r1, w1 = os.pipe()
        r2, w2 = os.pipe()
        return (w1, r2), (w2, r1)
    mode = socket.SOCK_STREAM if kind == "stream" else socket.SOCK_DGRAM
    left, right = socket.socketpair(socket.AF_UNIX, mode)
    left.settimeout(5)
    right.settimeout(5)
    return (left, left), (right, right)


def put(end, kind: str, data: bytes) -> None:
    if kind == "pipe":
        os.write(end[0], data)
    else:
        end[0].send(data)


def get(end, kind: str, size: int = 1) -> bytes:
    if kind == "pipe":
        return os.read(end[1], size)
    return end[1].recv(size)


def echo(end, kind: str, rounds: int, state: list) -> None:
    try:
        for _ in range(rounds):
            put(end, kind, get(end, kind))
    except OSError as err:
        state.append(err)


def pct(samples: list, frac: float) -> int:
    idx = int(len(samples) * frac) - 1
    return samples[max(idx, 0)]


def roundtrip(kind: str, rounds: int):
    me, peer = pair(kind)
    state = []
    back = threading.Thread(
        target=echo, args=(peer, kind, WARM + rounds, state), daemon=True
    )
    back.start()
    samples = []
    try:
        for _ in range(WARM + rounds):
            t0 = time.perf_counter_ns()
            put(me, kind, b"x")
            get(me, kind)
            samples.append(time.perf_counter_ns() - t0)
    finally:
        back.join(timeout=5)
    if state:
        raise OSError(str(state[0]))
    samples = sorted(samples[WARM:])
    return samples, rounds * 1e9 / max(sum(samples), 1)


def latency(kind: str, rounds: int) -> float:
    samples, rate = roundtrip(kind, rounds)
    emit(
        kind,
        rtt_p50_us=f"{pct(samples, 0.50) / 1000:.2f}",
        rtt_p99_us=f"{pct(samples, 0.99) / 1000:.2f}",
        rate=f"{rate:.0f}",
    )
    return rate


def drain(fd: int, total: int) -> None:
    left = total
    while left > 0:
        got = os.read(fd, CHUNK)
        if not got:
            return
        left -= len(got)


def sink(end, kind: str, count: int, state: list) -> None:
    try:
        for _ in range(count):
            get(end, kind, 64)
    except OSError as err:
        state.append(err)


def burst(kind: str, count: int, size: int = 64) -> float:
    me, peer = pair(kind)
    state = []
    reader = threading.Thread(target=sink, args=(peer, kind, count, state), daemon=True)
    reader.start()
    payload = b"\0" * size
    start = time.perf_counter_ns()
    for _ in range(count):
        put(me, kind, payload)
    reader.join(timeout=120)
    span = time.perf_counter_ns() - start
    if state:
        raise OSError(str(state[0]))
    rate = count * 1e9 / max(span, 1)
    emit("msgs", kind=kind, count=count, size=size, rate=f"{rate:.0f}")
    return rate


def bulk(total: int) -> None:
    r1, w1 = os.pipe()
    reader = threading.Thread(target=drain, args=(r1, total), daemon=True)
    reader.start()
    block = b"\0" * CHUNK
    start = time.perf_counter_ns()
    sent = 0
    while sent < total:
        sent += os.write(w1, block)
    span = time.perf_counter_ns() - start
    reader.join(timeout=10)
    os.close(w1)
    os.close(r1)
    emit("bulk", bytes=total, mib_s=f"{total / (1 << 20) / (span / 1e9):.1f}")


def worker(rounds: int) -> float:
    _, rate = roundtrip("stream", rounds)
    return rate


def fork(procs: int, rounds: int, single: float) -> None:
    with multiprocessing.get_context("fork").Pool(procs) as pool:
        rates = pool.map(worker, [rounds] * procs)
    total = sum(rates)
    emit(
        "fork",
        procs=procs,
        ops_per_proc=rounds,
        rate=f"{total:.0f}",
        scale=f"{total / single:.2f}" if single else "absent",
    )


def selfcheck() -> int:
    status = "ok"
    emit("check", python=sys.version.split()[0], cpu=os.cpu_count() or "absent")
    for kind in ("pipe", "stream", "dgram"):
        try:
            samples, _ = roundtrip(kind, 200)
        except OSError as err:
            emit(f"check.{kind}", status="fail", reason=str(err).replace(" ", "_"))
            status = "degraded"
            continue
        emit(f"check.{kind}", status="ok", rtt_us=f"{pct(samples, 0.5) / 1000:.2f}")
    try:
        allowed = len(os.sched_getaffinity(0))
        emit("check.affinity", cpus=allowed)
    except AttributeError:
        emit("check.affinity", cpus="absent")
    say("mode=check")
    say(f"status={status}")
    return 0 if status == "ok" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="airy-bench", description="AirymaxOS kernel IPC and concurrency probe"
    )
    parser.add_argument("--ops", type=int, default=20000)
    parser.add_argument("--procs", type=int, default=0)
    parser.add_argument("--bulk-mib", type=int, default=64)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        return selfcheck()
    if args.ops < WARM * 2:
        say("fail reason=ops-too-small")
        return 2

    procs = args.procs or min(os.cpu_count() or 1, 8)
    emit(
        "host",
        kernel=os.uname().release,
        cpu=os.cpu_count() or "absent",
        ops=args.ops,
        procs=procs,
        lang="python3",
    )

    single = latency("pipe", args.ops)
    latency("stream", args.ops)
    latency("dgram", args.ops)
    burst("stream", args.ops)
    bulk(args.bulk_mib << 20)
    fork(procs, max(args.ops // 4, WARM * 2), single)

    say("mode=live fields=7")
    say("status=ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
