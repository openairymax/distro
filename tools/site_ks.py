#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# site_ks.py — 站点介质派生：把产品配方改写成保留既有系统的配方
#
# 产品 ISO 的分区策略是 clearpart --all，整盘归 AirymaxOS，发行物语义
# 正确；装机现场已有别的系统时，需要的是「同一份字节、只改分区作用域」。
# 本工具从产品 ISO 取出 /ks.cfg，把整盘分区段换成显式 --onpart 绑定，
# 并在收尾命令前追加站点收尾段（登录密钥与无线配置）。
#
# 本工具只做配方变换，不碰 ISO。介质重建、三元对齐与校验块注入由
# scripts/site-iso.sh 调用 lib/iso_post.sh 完成，与主线构建共用同一条
# 后处理链，避免两条腿对「可引导」的口径漂移。
#
# 盘名与分区号是显式输入，不由安装器猜：--probe 时才用 lsblk 核对现场，
# CI 侧没有真实磁盘，故默认不探测。
#
# 退出码：0 成功；5 参数、内容或落点不满足。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DISTRO = Path(__file__).resolve().parents[1]
EINVAL = 5
EXPECT = {"esp": "vfat", "boot": "ext4", "swap": "swap", "root": "ext4"}
ROLES = tuple(EXPECT)


@dataclass(frozen=True)
class Site:
    """站点派生参数。分区号允许写成 p3，也允许写成完整节点名。"""

    disk: str
    esp: str
    boot: str
    swap: str
    root: str
    key: str
    ifcfg: str
    psk: str
    ssid: str


def bare(disk: str, part: str) -> str:
    """配方里写裸设备名：与 anaconda 既有站点配方同形，不引入新写法。"""
    return part if part.startswith("/dev/") else f"{disk}{part}"


def node(disk: str, part: str) -> str:
    return part if part.startswith("/dev/") else f"/dev/{disk}{part}"


def part_block(site: Site) -> str:
    esp = bare(site.disk, site.esp)
    boot = bare(site.disk, site.boot)
    swap = bare(site.disk, site.swap)
    root = bare(site.disk, site.root)
    return "\n".join([
        f"ignoredisk --only-use={site.disk}",
        "clearpart --none",
        f'part swap --fstype="swap" --onpart={swap}',
        f'part /boot/efi --fstype="efi" --onpart={esp} '
        '--fsoptions="defaults,uid=0,gid=0,umask=077,shortname=winnt"',
        f'part / --fstype="ext4" --onpart={root} --label=airymax-root',
        f'part /boot --fstype="ext4" --onpart={boot}',
    ])


def site_block(site: Site) -> str:
    key = Path(site.key).read_text(encoding="utf-8").strip()
    ifcfg = Path(site.ifcfg).read_text(encoding="utf-8").rstrip("\n")
    psk = Path(site.psk).read_text(encoding="utf-8").strip()
    cfg = "/etc/sysconfig/network-scripts"
    return "\n".join([
        "# ---- 站点收尾（site_ks.py 派生，产品 ISO 不含本段）----",
        "%post --log=/root/airymax-site.log",
        "set -eu",
        "cfg=" + cfg,
        "auth=/home/Airymax/.ssh",
        'install -d -m 0700 -o Airymax -g Airymax "${auth}"',
        'cat > "${auth}/authorized_keys" <<\'AIRYMAX_SITE_KEY\'',
        key,
        "AIRYMAX_SITE_KEY",
        'chmod 0600 "${auth}/authorized_keys"',
        'chown -R Airymax:Airymax "${auth}"',
        "if command -v restorecon >/dev/null 2>&1; then",
        '  restorecon -R "${auth}"',
        "fi",
        f'cat > "${{cfg}}/ifcfg-{site.ssid}" <<\'AIRYMAX_SITE_IFCFG\'',
        ifcfg,
        "AIRYMAX_SITE_IFCFG",
        f'chmod 0644 "${{cfg}}/ifcfg-{site.ssid}"',
        f'cat > "${{cfg}}/keys-{site.ssid}" <<\'AIRYMAX_SITE_PSK\'',
        psk,
        "AIRYMAX_SITE_PSK",
        f'chmod 0600 "${{cfg}}/keys-{site.ssid}"',
        "%end",
    ])


def include_span(lines: list[str]) -> tuple[int, int]:
    """定位「%pre 选盘 + %include 片段」段，返回首末行号。

    产品配方把存储布局交给 %pre 依现场选盘生成（D-32），站点派生必须把
    整段换掉：站点机的分区由 --onpart 显式绑定，不能再让脚本挑盘。只认
    %pre 正文确实写出该文件的情形，避免误删有别的用途的 %pre。

    紧贴 %pre 的注释属于该段：它们解释的是选盘规则，留在派生配方里会描述
    一段已经不存在的逻辑。
    """
    start = end = None
    for num, raw in enumerate(lines):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        word = text.split(None, 1)[0]
        if word == "%pre":
            start, end = num, None
        elif text == "%end" and start is not None:
            end = num
        elif word == "%include" and start is not None:
            body = "\n".join(lines[start:end if end is not None else num])
            if text.split(None, 1)[-1] in body:
                while start > 0 and lines[start - 1].lstrip().startswith("#"):
                    start -= 1
                return start, num
    raise ValueError("产品配方缺少 %pre 选盘段与 %include 引用")


def transform(text: str, site: Site) -> str:
    """把选盘段换成显式绑定，并在收尾命令前插入站点段。

    bootloader 行补 --location=mbr --boot-drive：BIOS 侧写 MBR、EFI 侧仍写
    自身 ESP，与既有系统各用各的引导目录。
    """
    lines = text.splitlines()
    first, last = include_span(lines)
    out: list[str] = []
    for num, line in enumerate(lines):
        if num == first:
            out.append(part_block(site))
        if first <= num <= last:
            continue
        head = line.strip()
        if head.startswith("bootloader ") and "--boot-drive" not in head:
            line = f"{line} --location=mbr --boot-drive={site.disk}"
        if head == "reboot":
            out.append(site_block(site))
            out.append("")
        out.append(line)
    return "\n".join(out) + "\n"


def probe(path: str) -> tuple[str, str]:
    res = subprocess.run(["lsblk", "-dno", "FSTYPE,TYPE", path],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise ValueError(f"lsblk {path} 失败: {res.stderr.strip()}")
    fields = res.stdout.split()
    return (fields[0] if fields else "",
            fields[1] if len(fields) > 1 else "")


def check_media(site: Site) -> None:
    """装机现场核对：分区必须存在且类型与站点配方将要写入的一致。

    生成期核对比装机期失败便宜得多——后者要等一个完整安装事务跑完。
    """
    for role in ROLES:
        path = node(site.disk, getattr(site, role))
        fstype, kind = probe(path)
        if kind != "part":
            raise ValueError(f"{path} 不是分区（type={kind or 'unknown'}）")
        want = EXPECT[role]
        if role == "esp" and fstype != want:
            raise ValueError(f"{path} fstype={fstype or 'none'}，期望 {want}")
        if role != "esp" and fstype not in (want, ""):
            raise ValueError(f"{path} fstype={fstype}，期望 {want} 或空")


def read_ks(iso: Path, work: Path) -> str:
    out = work / "product.ks"
    res = subprocess.run(["xorriso", "-osirrox", "on", "-indev", str(iso),
                          "-extract", "/ks.cfg", str(out)],
                         capture_output=True, text=True)
    # xorriso 用 32 报告 SORRY 级问题（混合镜像的 MBR/GPT 项越过文件末尾），
    # 但文件本身已完整落地，此时内容才是判据，不看返回码。
    if not out.is_file():
        raise ValueError(
            f"提取 /ks.cfg 失败: {(res.stderr or res.stdout).strip()}")
    return out.read_text(encoding="utf-8")


def in_tree(path: Path) -> bool:
    try:
        path.resolve().relative_to(DISTRO)
    except ValueError:
        return False
    return True


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="site_ks.py", description="生成保留既有系统的站点配方")
    ap.add_argument("--iso", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--disk", required=True)
    for role in ROLES:
        ap.add_argument(f"--{role}", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--ifcfg", required=True)
    ap.add_argument("--psk", required=True)
    ap.add_argument("--ssid", default="")
    ap.add_argument("--lint", default="")
    ap.add_argument("--probe", action="store_true")
    return ap.parse_args(argv)


def lint(script: str, ks: Path) -> None:
    if not script:
        return
    res = subprocess.run([sys.executable, script, str(ks)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise ValueError(
            f"派生配方未通过静态校验:\n{res.stdout}{res.stderr}")


def main(argv: list[str]) -> int:
    args = parse(argv)
    try:
        if in_tree(args.out):
            raise ValueError(f"产物不得落在源码区: {args.out}")
        if not args.iso.is_file():
            raise ValueError(f"输入 ISO 不存在: {args.iso}")
        ssid = args.ssid or Path(args.ifcfg).name.removeprefix("ifcfg-")
        site = Site(args.disk, args.esp, args.boot, args.swap, args.root,
                    args.key, args.ifcfg, args.psk, ssid)
        if args.probe:
            check_media(site)
        args.work.mkdir(parents=True, exist_ok=True)
        text = transform(read_ks(args.iso, args.work), site)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        lint(args.lint, args.out)
    except (OSError, ValueError) as err:
        print(f"site_ks: {err}", file=sys.stderr)
        return EINVAL
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
