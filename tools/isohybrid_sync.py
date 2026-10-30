#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# isohybrid_sync.py — isohybrid 介质三元一致性检查与修复
#
# isohybrid 介质把同一份引导镜像登记在多处：
#   1. El Torito 引导目录（LBA 17 引导记录 → 目录块 → platform 条目，逻辑
#      块号为 2048 字节单位，扇区数为 512 字节单位）；BIOS 腿取 platform
#      0x00，UEFI 腿取 0xEF；
#   2. MBR 分区表（偏移 446 起 4 项，type 0xEF，512 字节单位）；
#   3. GPT 分区表（条目名 ISOHybrid1，512 字节单位）。
# 固件以 USB 盘方式启动时按分区表定位 ESP，只有三者指向同一段扇区才能
# 引导。用 xorriso/mkksiso 重新排布镜像后 El Torito 条目的逻辑块号会前移，
# 而 MBR/GPT 里的扇区号仍是旧值，形成静默错位：固件按分区表读到的是机器
# 码而非 FAT 卷，引导失败且无任何提示，只会在超时后静默回落到 BootOrder
# 首位（0.0.3 实机故障根因）。CI 以 -cdrom 走 El Torito 路径，结构性覆盖
# 不到这一层，故此处以独立门禁把三元一致性显式化。
#
# BIOS 腿另有第四处：isolinux.bin 偏移 8 起的 boot info table（bi_pvd、
# bi_file、bi_length、bi_csum）。isolinux 靠它定位自身、配置与内核，
# bi_file 以 2048 字节为单位且必须等于 El Torito 条目块号，bi_csum 是 64
# 字节起全部双字的小端累加。重排镜像只搬动条目而不会改写这张表；表一旦
# 陈旧，isolinux 找不到自己的配置，只往 VGA 报错，串口一个字都没有，BIOS
# 腿的现场就只剩空日志。故 BIOS 条目存在时一并断言，且可直接就地修正。
#
# 本工具以 El Torito 条目为唯一真值：--check 只判定，--sync 改写 MBR 与
# GPT 并重算 GPT 头 CRC，必要时同步改写 boot info table。备份 GPT 不处理
# ——isohybrid 介质按镜像尺寸截断，备份头位置无意义（sgdisk -v 已报
# invalid backup GPT header）。
#
# 用法：isohybrid_sync.py [--check|--sync] ISO
# 退出码：0 一致；1 不一致；2 用法或读取错误；77 非 El Torito 镜像（不适用）。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

BLK = 2048
SECT = 512
TORITO_LBA = 17
MBR_TABLE = 446
SLOT = 16
GPT_HDR_SECT = 1
GPT_HEAD = 92
BIOS_TYPE = 0x00
EFI_TYPE = 0xEF
SECTIONS = (0x90, 0x91)
ENTRY = 0x88
MAGIC = b"EL TORITO SPECIFICATION"
GPT_MAGIC = b"EFI PART"
PVD_LBA = 16
BIP = 8
BIP_LEN = 32
BIP_SUM = 64
BIP_MAX = 8 << 20
ISOLINUX = 0xFB
CAT_OFF = 32
REC_LEN = 32

OK = 0
BAD = 1
ERR = 2
SKIP = 77


class ReadError(Exception):
    pass


def read_at(fh, off, size):
    fh.seek(off)
    buf = fh.read(size)
    if len(buf) != size:
        raise ReadError(f"偏移 {off} 读取 {size} 字节失败")
    return buf


def write_at(fh, off, buf):
    fh.seek(off)
    fh.write(buf)
    fh.flush()


def torito_entries(fh):
    """返回 {"bios": (lba, sectors), "efi": (lba, sectors)}；非 El Torito 返回 None。

    目录里两种平台各取首个可引导条目。platform 0x00 的条目缺失是合法的
    （纯 UEFI 介质），调用方自行决定是否要求。
    """
    br = read_at(fh, TORITO_LBA * BLK, BLK)
    if MAGIC not in br[:40]:
        return None
    cat = struct.unpack_from("<I", br, 71)[0]
    blk = read_at(fh, cat * BLK, BLK)
    plat = struct.unpack_from("<B", blk, 1)[0]
    found = {}
    pos = CAT_OFF
    while pos + REC_LEN <= BLK:
        rec = blk[pos:pos + REC_LEN]
        pos += REC_LEN
        if rec[0] in SECTIONS:
            plat = rec[1]
        elif rec[0] == ENTRY and plat in (BIOS_TYPE, EFI_TYPE):
            key = "bios" if plat == BIOS_TYPE else "efi"
            if key not in found:
                found[key] = (struct.unpack_from("<I", rec, 8)[0],
                              struct.unpack_from("<H", rec, 6)[0])
    return found


def bip_read(fh, lba):
    """读引导镜像的 isolinux boot info table。

    返回 (bi_pvd, bi_file, bi_length, bi_csum, 镜像字节)；镜像没有
    isolinux 签名（偏移 64 的 0xFB）或不具备合理长度时返回 None。
    bi_length 来自表本身，越界值直接判为非 isolinux，避免按垃圾长度读盘。
    """
    head = read_at(fh, lba * BLK, BIP + BIP_LEN)
    pvd, file, length, csum = struct.unpack_from("<IIII", head, BIP)
    if length <= BIP_SUM or length > BIP_MAX:
        return None
    img = read_at(fh, lba * BLK, length)
    if img[BIP_SUM] != ISOLINUX:
        return None
    return pvd, file, length, csum, img


def bip_sum(img):
    """bi_csum：镜像 64 字节起全部双字的小端累加，模 2^32。

    校验和字段自身位于偏移 20，落在累加区间之前，无需清零。
    """
    n = (len(img) - BIP_SUM) & ~3
    return sum(struct.unpack_from(f"<{n // 4}I", img, BIP_SUM)) & 0xFFFFFFFF


def bip_ok(tab, lba):
    """boot info table 与本条目块号自洽：PVD=16、bi_file=条目块号、校验和相符。"""
    pvd, file, _, csum, img = tab
    return pvd == PVD_LBA and file == lba and csum == bip_sum(img)


def mbr_slot(fh):
    """返回 (索引, start, size, type)；无 0xEF 项返回 None。"""
    mbr = read_at(fh, 0, SECT)
    for idx in range(4):
        off = MBR_TABLE + idx * SLOT
        if mbr[off + 4] == EFI_TYPE:
            return (idx, *struct.unpack_from("<II", mbr, off + 8))
    return None


def gpt_table(fh):
    """返回 (header, table, 条目数, 条目大小)；无 GPT 返回 None。"""
    hdr = read_at(fh, GPT_HDR_SECT * SECT, GPT_HEAD)
    if hdr[:8] != GPT_MAGIC:
        return None
    ent_lba, num, size = struct.unpack_from("<QII", hdr, 72)
    table = read_at(fh, ent_lba * SECT, num * size)
    return hdr, table, num, size


def gpt_span(table, num, size):
    """按条目名 ISOHybrid1 返回 (索引, first, last)；缺失则退回长度匹配。"""
    cand = []
    for idx in range(num):
        rec = table[idx * size:(idx + 1) * size]
        if rec[:16] == b"\0" * 16:
            continue
        first, last = struct.unpack_from("<QQ", rec, 32)
        name = rec[56:size].decode("utf-16-le", "ignore").split("\0")[0]
        cand.append((idx, first, last, name))
    for idx, first, last, name in cand:
        if name == "ISOHybrid1":
            return idx, first, last
    return None


def patch_mbr(fh, start, size):
    mbr = bytearray(read_at(fh, 0, SECT))
    off = MBR_TABLE + mbr_slot(fh)[0] * SLOT
    struct.pack_into("<II", mbr, off + 8, start, size)
    write_at(fh, 0, mbr)


def patch_gpt(fh, start, size):
    hdr, table, num, esz = gpt_table(fh)
    idx, _, _ = gpt_span(table, num, esz)
    buf = bytearray(table)
    struct.pack_into("<QQ", buf, idx * esz + 32, start, start + size - 1)
    write_at(fh, struct.unpack_from("<Q", hdr, 72)[0] * SECT, buf)
    head = bytearray(hdr)
    struct.pack_into("<I", head, 88, zlib.crc32(bytes(buf)) & 0xFFFFFFFF)
    struct.pack_into("<I", head, 16, 0)
    struct.pack_into("<I", head, 16, zlib.crc32(bytes(head)) & 0xFFFFFFFF)
    write_at(fh, GPT_HDR_SECT * SECT, head)


def patch_bip(fh, lba, tab):
    """把 boot info table 的 bi_file 改成本条目块号并重算 bi_csum。"""
    _, _, _, _, img = tab
    buf = bytearray(img)
    struct.pack_into("<I", buf, BIP + 4, lba)
    struct.pack_into("<I", buf, BIP + 12, bip_sum(bytes(buf)))
    write_at(fh, lba * BLK, buf)


def too_small(fh):
    fh.seek(0, 2)
    return fh.tell() < (TORITO_LBA + 2) * BLK


def survey(fh):
    if too_small(fh):
        return None
    ent = torito_entries(fh)
    if not ent or "efi" not in ent:
        return None
    mbr = mbr_slot(fh)
    gpt = gpt_table(fh)
    span = gpt_span(gpt[1], gpt[2], gpt[3]) if gpt else None
    bip = bip_read(fh, ent["bios"][0]) if "bios" in ent else None
    return {"lba": ent["efi"][0], "size": ent["efi"][1], "mbr": mbr,
            "gpt": span, "bios": ent.get("bios"), "bip": bip}


def report(sig):
    print(f"torito: lba2048={sig['lba']} sectors512={sig['size']} "
          f"lba512={sig['lba'] * (BLK // SECT)}")
    if sig["mbr"]:
        idx, start, size = sig["mbr"]
        print(f"mbr: slot={idx + 1} start={start} size={size}")
    if sig["gpt"]:
        idx, first, last = sig["gpt"]
        print(f"gpt: slot={idx + 1} first={first} last={last}")
    if not sig["bios"]:
        print("bios: absent")
        return
    lba, sectors = sig["bios"]
    if not sig["bip"]:
        print(f"bios: lba2048={lba} sectors512={sectors} bootinfo=none")
        return
    pvd, file, length, csum, _ = sig["bip"]
    print(f"bios: lba2048={lba} sectors512={sectors} bi_pvd={pvd} "
          f"bi_file={file} bi_length={length} bi_csum=0x{csum:08x} "
          f"bootinfo={'ok' if bip_ok(sig['bip'], lba) else 'stale'}")


def aligned(sig):
    want = sig["lba"] * (BLK // SECT)
    want_size = sig["size"]
    if not sig["mbr"] or not sig["gpt"]:
        return False
    if sig["bios"] and sig["bip"] and not bip_ok(sig["bip"], sig["bios"][0]):
        return False
    return (sig["mbr"][1] == want and sig["mbr"][2] == want_size and
            sig["gpt"][1] == want and sig["gpt"][2] - sig["gpt"][1] + 1
            == want_size)


def sync(path):
    with path.open("rb+") as fh:
        sig = survey(fh)
        if sig is None:
            return SKIP
        report(sig)
        if aligned(sig):
            print("status: ok")
            return OK
        if not sig["mbr"] or not sig["gpt"]:
            print("status: mismatch")
            return BAD
        want = sig["lba"] * (BLK // SECT)
        notes = []
        if sig["mbr"][1] != want or sig["mbr"][2] != sig["size"]:
            patch_mbr(fh, want, sig["size"])
            notes.append("mbr")
        if sig["gpt"][1] != want or sig["gpt"][2] != want + sig["size"] - 1:
            patch_gpt(fh, want, sig["size"])
            notes.append("gpt")
        if sig["bios"] and sig["bip"] and not bip_ok(sig["bip"], sig["bios"][0]):
            patch_bip(fh, sig["bios"][0], sig["bip"])
            notes.append("bootinfo")
        print(f"sync: {'+'.join(notes)} -> start={want} size={sig['size']}")
        done = survey(fh)
        report(done)
        print(f"status: {'fixed' if aligned(done) else 'broken'}")
        return OK if aligned(done) else BAD


def check(path):
    with path.open("rb") as fh:
        sig = survey(fh)
        if sig is None:
            return SKIP
        report(sig)
        print(f"status: {'ok' if aligned(sig) else 'mismatch'}")
        return OK if aligned(sig) else BAD


def main(argv):
    mode = check
    args = []
    for arg in argv:
        if arg == "--sync":
            mode = sync
        elif arg == "--check":
            mode = check
        elif arg in ("-h", "--help"):
            print("用法: isohybrid_sync.py [--check|--sync] ISO")
            return OK
        elif arg.startswith("-"):
            print(f"isohybrid_sync: 未知参数 {arg}", file=sys.stderr)
            return ERR
        else:
            args.append(arg)
    if len(args) != 1:
        print("用法: isohybrid_sync.py [--check|--sync] ISO", file=sys.stderr)
        return ERR
    path = Path(args[0])
    if not path.is_file():
        print(f"isohybrid_sync: 不是文件: {path}", file=sys.stderr)
        return ERR
    try:
        return mode(path)
    except ReadError as exc:
        print(f"isohybrid_sync: {exc}", file=sys.stderr)
        return ERR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
