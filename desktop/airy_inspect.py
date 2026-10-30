#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airy_inspect.py — 内核与整机身份取证（安装为 airy-kernel / airy-os）
#
# 为什么要两个命令：airy-observe 出的是「这台机器此刻是谁」的固定短表，
# 面向自动化判定；现场演示与排障要回答的是另一个问题——「这条结论出自
# 哪个文件、哪一行为什么可信」。把两类读者塞进一份输出，前者会被淹没，
# 后者又会缺证据。故本文件只做后者：逐项打印取值与它的权威来源路径，
# 任何一行都能被人工用同一路径复核。
#
# 与其它 airy 命令同一口径：不产生新数字。内核身份取自 uname 与 procfs，
# 归属取自 rpm 数据库，能力取自 /boot/config-<release> 与 /proc/kallsyms。
# 取不到的项照常打印 key=absent，不省略——省略会让「没采到」与「没有这
# 一项」长得一样，而这正是现场最容易误判的一处。
#
# --root 对每个文件取值生效，并同时切到静态模式：静态模式下不查 rpm 数据
# 库、不取 uname(2)，因为二者回答的是「本机」而不是「这棵树」。冻结的树
# 与活体机因此跑的是同一套解析，打包自检与实机演示不会各写一份。
#
# 用法：airy-kernel [--root DIR]
#       airy-os     [--root DIR]
# 退出码：0 正常；2 用法错误。
# ===========================================================================

import hashlib
import os
import subprocess
import sys
from pathlib import Path

MARKS = {"airy-kernel": "AIRYMAX-KERNEL", "airy-os": "AIRYMAX-OS"}
USAGE = ("用法: airy-kernel [--root DIR] | airy-os [--root DIR]\n"
         "  airy-kernel  内核身份、镜像摘要、Airymax 自有配置项与符号数\n"
         "  airy-os      发行版身份、软件包归属、仓库段、CPU/内存/根盘\n")

# /boot/config-<release> 里必须为 y 的自有配置项（D-12 内核归属）。
AIRY_CFG = (
    "CONFIG_SECURITY_AIRY",
    "CONFIG_AIRY_SYSCALL",
    "CONFIG_AIRY_COREKERN",
    "CONFIG_AIRY_LOG",
    "CONFIG_AIRY_IPC",
    "CONFIG_AIRY_AGENT_TRACING",
    "CONFIG_AIRY_CAP_TABLE_SIZE",
)


def txt(path):
    """读文本；不存在或不可读返回 None，由调用方决定 absent 的写法。"""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def first_of(text):
    """取首个非空行；文件缺失或全空返回 None。"""
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return None


def line_of(text, prefix):
    """取首行以 prefix 开头的内容，去掉前缀与空白；无匹配返回 None。"""
    for line in (text or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def unquote(value):
    """去掉 os-release 允许的一对单双引号。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def kv_of(text):
    """把 KEY=VALUE 文本解析成字典；无等号的行跳过。"""
    out = {}
    for line in (text or "").splitlines():
        key, sep, value = line.partition("=")
        if sep and key and not key.startswith(("#", "[")):
            out[key.strip()] = unquote(value.strip())
    return out


def sha_of(path):
    """分块摘要，避免把 40 MB 的 vmlinuz 整个读进内存。

    非 root 读不读得到 /boot 取决于发行版的目录权限，与内核本身无关；
    读不到时返回 None 由调用方写 absent，不能让整条命令带栈退出——那会
    把「这一项没采到」显示成「这台机器身份不明」。
    """
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def rpm_q(names):
    """查 rpm 数据库；rpm 缺失或无该包时返回 None。"""
    try:
        res = subprocess.run(["rpm", "-q", "--qf", "%{NAME}-%{VERSION}-%{RELEASE}"]
                             + list(names), capture_output=True, text=True,
                             check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def rpm_f(path):
    """查文件归属的包；未装 rpm 或文件无归属时返回 None。"""
    try:
        res = subprocess.run(["rpm", "-qf", str(path)], capture_output=True,
                             text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


class Report:
    """按 <mark> key=value 逐行输出；含空白的取值整体加引号。"""

    def __init__(self, mark):
        self.mark = mark
        self.n = 0

    def put(self, key, value):
        text = "absent" if value in (None, "") else str(value)
        if any(ch.isspace() for ch in text):
            text = '"%s"' % text.replace('"', "'")
        print("%s %s=%s" % (self.mark, key, text))
        self.n += 1


def krel(root, live):
    """内核 release：活体取 uname(2)，静态取 procfs 快照。"""
    if live:
        return os.uname().release
    return first_of(txt(root / "proc/sys/kernel/osrelease"))


def kver(root, live):
    """内核构建串：活体取 uname -v，静态取 procfs 快照。"""
    if live:
        return os.uname().version
    return first_of(txt(root / "proc/sys/kernel/version"))


def cfg_map(root, rel):
    """读 /boot/config-<release>；返回 (路径, 字典)，缺失时字典为空。"""
    path = root / ("boot/config-%s" % rel) if rel else None
    body = txt(path) if path else None
    return path, kv_of(body)


def ksym(root):
    """统计 /proc/kallsyms 中 airy_ 前缀符号数；非 root 读到的地址为 0，
    但符号名照常可读，故只数名不看地址。"""
    body = txt(root / "proc/kallsyms")
    if body is None:
        return None
    return sum(1 for line in body.splitlines()
               if line.split(" ")[-1].startswith("airy_"))


def mods(root, rel):
    """已登记模块数：modules.dep 每行一个模块，空文件即无外部模块。"""
    path = root / ("lib/modules/%s/modules.dep" % rel) if rel else None
    body = txt(path) if path else None
    if body is None:
        return None
    return sum(1 for line in body.splitlines() if line.strip())


def kernel(root, live):
    """airy-kernel：身份、镜像、归属、自有配置与符号。"""
    rep = Report(MARKS["airy-kernel"])
    rel = krel(root, live)
    ver = kver(root, live)
    rep.put("kernel.release", rel)
    rep.put("kernel.version", ver)
    rep.put("kernel.machine", os.uname().machine if live else None)
    rep.put("kernel.build", first_of(txt(root / "proc/version")))
    rep.put("kernel.cmdline", (txt(root / "proc/cmdline") or "").strip())
    img = root / ("boot/vmlinuz-%s" % rel) if rel else None
    if img is not None and img.is_file():
        rep.put("image.path", img)
        rep.put("image.bytes", img.stat().st_size)
        rep.put("image.sha256", sha_of(img))
        rep.put("image.owner", rpm_f(img) if live else None)
    else:
        for key in ("image.path", "image.bytes", "image.sha256", "image.owner"):
            rep.put(key, None)
    smap = root / ("boot/System.map-%s" % rel) if rel else None
    rep.put("map.path", smap if smap is not None and smap.is_file() else None)
    path, cfg = cfg_map(root, rel)
    rep.put("config.path", path if cfg else None)
    for sym in AIRY_CFG:
        rep.put("config." + sym[len("CONFIG_"):].lower(), cfg.get(sym))
    rep.put("ksym.airy", ksym(root))
    rep.put("module.count", mods(root, rel))
    return 0


def root_disk(root):
    """根分区的设备与文件系统：从挂载表里找挂载点为 / 的那一行。"""
    for line in (txt(root / "proc/mounts") or "").splitlines():
        cols = line.split()
        if len(cols) >= 3 and cols[1] == "/":
            return cols[0], cols[2]
    return None, None


def cpu_info(root):
    """CPU 型号与在线核数；型号取 model name 首条，核数取 processor 计数。"""
    body = txt(root / "proc/cpuinfo") or ""
    model = None
    count = 0
    for line in body.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if model is None and key.strip() == "model name":
            model = value.strip()
        if key.strip() == "processor":
            count += 1
    return model, count or None


def mem_total(root):
    """物理内存总量（KiB），取自 /proc/meminfo 的 MemTotal。"""
    value = line_of(txt(root / "proc/meminfo"), "MemTotal:")
    if not value:
        return None
    head = value.split()[0]
    return head if head.isdigit() else None


def os_of(root, live):
    """airy-os：发行版身份、包归属、仓库段、硬件与默认会话。"""
    rep = Report(MARKS["airy-os"])
    fields = kv_of(txt(root / "usr/lib/os-release")
                   or txt(root / "etc/os-release"))
    for key, name in (("os.id", "ID"), ("os.name", "NAME"),
                      ("os.pretty", "PRETTY_NAME"),
                      ("os.version", "VERSION"),
                      ("os.version_id", "VERSION_ID"),
                      ("os.variant", "VARIANT_ID")):
        rep.put(key, fields.get(name))
    rep.put("host.name", (txt(root / "etc/hostname") or "").strip() or None)
    if live:
        for key, name in (("pkg.release", "airymaxos-release"),
                          ("pkg.system", "airymaxos-system"),
                          ("pkg.kernel", "airymaxos-kernel")):
            rep.put(key, rpm_q([name]))
    else:
        for key in ("pkg.release", "pkg.system", "pkg.kernel"):
            rep.put(key, None)
    repo = root / "etc/yum.repos.d/airymaxos.repo"
    body = txt(repo)
    rep.put("repo.path", repo if body else None)
    rep.put("repo.sections",
            None if body is None else sum(1 for line in body.splitlines()
                                          if line.startswith("[")))
    model, cores = cpu_info(root)
    rep.put("cpu.model", model)
    rep.put("cpu.count", cores)
    rep.put("mem.total_kb", mem_total(root))
    device, fstype = root_disk(root)
    rep.put("disk.root.source", device)
    rep.put("disk.root.fstype", fstype)
    lconf = kv_of(txt(root / "etc/lightdm/lightdm.conf.d/50-airymax.conf"))
    rep.put("session.autologin", lconf.get("autologin-user"))
    return 0


def main(argv):
    """按 argv[0] 的基名分派；未知入口按用法错误处理。"""
    name = os.path.basename(argv[0])
    if name not in MARKS:
        print("用法错误: 入口名须为 airy-kernel 或 airy-os，当前 %s" % name,
              file=sys.stderr)
        return 2
    args = argv[1:]
    root = Path("/")
    if args[:1] in (["-h"], ["--help"]):
        print(USAGE, end="")
        return 0
    if args:
        if args[0] != "--root" or len(args) != 2:
            print("用法错误: 只接受 [--root DIR]", file=sys.stderr)
            print(USAGE, end="", file=sys.stderr)
            return 2
        root = Path(args[1])
    live = root == Path("/")
    if name == "airy-kernel":
        return kernel(root, live)
    return os_of(root, live)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
