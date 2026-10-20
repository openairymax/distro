#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# iso_pad.py — 为 ISO 尾部补足 isomd5sum 校验块所需的空间
#
# implantisomd5 把校验块写在 ISO9660 主卷描述符（PVD）声明的卷空间之后，
# 因此要求镜像在卷空间之外还有 32KiB 余量。mkksiso 重建的镜像长度恰好
# 等于卷空间（无尾部 padding），直接注入会失败，安装期 rd.live.check
# 也就无从校验。本工具按 PVD 核对文件长度，在余量不足时以零补齐。
# 补零落在卷空间之外，不进入任何目录项或文件数据。
#
# 用法：iso_pad.py ISO
# 退出码：0 已具备余量或已补齐；1 镜像损坏、被截断或写入失败；2 用法错误。
#
# Author: Decheng Li <lidecheng@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import os
import sys

SECTOR = 2048
PVD_OFF = 16 * SECTOR
FRAGMENT = 32 * 1024


def fail(msg):
    sys.stderr.write(f"iso_pad: {msg}\n")
    raise SystemExit(1)


def vol_bytes(fh):
    fh.seek(PVD_OFF)
    pvd = fh.read(SECTOR)
    if len(pvd) < SECTOR or pvd[0] != 1 or pvd[1:6] != b"CD001":
        fail("未找到 ISO9660 主卷描述符")
    lo = int.from_bytes(pvd[80:84], "little")
    hi = int.from_bytes(pvd[84:88], "big")
    if lo != hi or lo == 0:
        fail("主卷描述符的卷空间大小两端字节序不一致")
    return lo * SECTOR


def pad(path):
    with open(path, "r+b") as fh:
        vol = vol_bytes(fh)
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size < vol:
            fail(f"镜像被截断：{size} 字节，卷空间 {vol} 字节")
        need = vol + FRAGMENT - size
        if need > 0:
            fh.write(b"\0" * need)


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("用法: iso_pad.py ISO\n")
        return 2
    try:
        pad(argv[1])
    except OSError as exc:
        fail(f"无法处理 {argv[1]}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
