#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# cfg_brand.py — 引导菜单品牌化与缺省安装项改写
#
# AirymaxOS 0.0.3 的安装 ISO 以 openEuler 24.03-LTS-SP2 netinst 为底座，
# mkksiso 注入 kickstart 重建后，引导菜单仍保留底座原文（"Install
# openEuler 24.03-LTS-SP2"、"Rescue a openEuler system"），且缺省项停在
# "Test this media & install ..."（set default="1"）。无人值守安装会先跑
# rd.live.check 把整份 3.7 GB 介质从 U 盘读一遍才开始装，既拖慢装机又让
# 用户看到别家产品名。
#
# 本工具只改三样东西：菜单标题文字、default 行，以及 append 行缺失的串口
# 控制台参数。inst.ks= 与 LABEL= 必须原样保留——它们决定 kickstart 与
# stage2 的定位，改坏即装机失败；append 行只在末尾追加 console=，已有
# console=ttyS0 的行逐字节不动。改写前后整文件比对，只有真的变化才写回，
# 同一文件重复执行幂等（第二次退出 3）。
#
# 串口控制台是引导契约而非品牌问题：UEFI 腿的 grub.cfg 由底座带
# console=tty0 console=ttyS0,115200，BIOS 腿的 isolinux.cfg 却只有 quiet，
# 于是同一次装机在 UEFI 下串口有完整记录、在 BIOS 下一个字节都没有（run
# 41090215913：run-bios-1/install.log 全程 0 字节，门禁只能等到超时）。
# 两条固件腿必须给出同样的可观测性，否则 BIOS 装机现场卡住时无从定位。
#
# 介质还有三处底座暴露，按文件名分派到同一入口：ISO 根目录的 .treeinfo
# 是 anaconda 填写安装源产品名的来源（[general] 的 family/name/version），
# 同目录的 .discinfo 是介质自述（时间戳、发行版名、架构、变体），
# isolinux/boot.msg 则是老式 BIOS 欢迎文本。.treeinfo 按 INI 只改品牌键
# 的值，其余行与顺序逐字节保留；.discinfo 只改发行版名那一行，时间戳与
# 架构行不动；boot.msg 只替换明确的底座品牌串，不重排版面。三者遵守同一
# 份幂等契约。
#
# 用法：cfg_brand.py --product "AirymaxOS 0.0.3" FILE
# 退出码：0 有改写；3 已合规（无变化）；1 无法解析或无法满足（缺 inst.ks
#         安装项等）；2 用法错误。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

from __future__ import annotations

import re
import sys
from pathlib import Path

OK = 0
BAD = 1
ERR = 2
SAME = 3

USAGE = '用法: cfg_brand.py --product "AirymaxOS 0.0.3" FILE'

GRUB_RE = re.compile(r"^(menuentry|submenu)\s+(['\"])(.*?)\2")
GRUB_DEF = re.compile(r"^set\s+default=\S+")
MENU_RE = re.compile(r"^(\s*menu (?:label|title)\s+)(\^?)(.*)$")
LABEL_RE = re.compile(r"^label\s+(\S+)")
ISOLINUX_HINT = re.compile(r"^\s*(label|append|menu (?:label|title))\b")
APPEND_RE = re.compile(r"^\s*append\s")
SERIAL_RE = re.compile(r"console=ttyS0")
SERIAL_ARG = "console=tty0 console=ttyS0,115200"
DEF_RE = re.compile(r"^default=(\S+)")
SECT_RE = re.compile(r"^\[([^\]]+)\]")
TREE_KEY = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*=\s*)(.*)$")
TREE_SEC = ("general", "release", "product")
BASE_NAME = re.compile(r"openeuler", re.IGNORECASE)
BASE_MSG = re.compile(r"openEuler(?:[- ][0-9][^\s,;:.]*)?")

# 只认底座确实存在的三种标题；Troubleshooting 之类原样保留。
TITLE_RULES = (
    (re.compile(r"^Install\s+\S"), "Install {p}"),
    (re.compile(r"^Test this media & install\s+\S"),
     "Test this media & install {p}"),
    (re.compile(r"^Rescue a\s+\S.*\s+system$"), "Rescue {p} system"),
)


def retitle(text, product):
    """按产品名改写菜单标题；不匹配的标题原样返回。"""
    for pat, fmt in TITLE_RULES:
        if pat.search(text):
            return fmt.format(p=product)
    return text


def g_end(lines, start):
    """返回 menuentry/submenu 体内列 0 的 '}' 行号；缺失则退到末行。"""
    for pos in range(start + 1, len(lines)):
        if lines[pos].rstrip("\n") == "}":
            return pos
    return len(lines) - 1


def g_entries(lines):
    """返回 [(起始行, 结束行, 标题)]，只含列 0 起的顶层项。"""
    hits = []
    for pos, line in enumerate(lines):
        m = GRUB_RE.match(line)
        if m:
            hits.append((pos, g_end(lines, pos), m.group(3)))
    return hits


def g_ok(body):
    """体内含 inst.ks= 且任何一行都不含 rd.live.check 即为安装项。"""
    has_ks = any("inst.ks=" in line for line in body)
    has_check = any("rd.live.check" in line for line in body)
    return has_ks and not has_check


def g_install(lines, entries):
    """返回第一个安装项的序号（0 基）；没有则返回 None。"""
    for idx, (start, end, _) in enumerate(entries):
        if g_ok(lines[start:end + 1]):
            return idx
    return None


def g_put(line, title):
    """只替换引号内的标题，引号与行尾保持原样。"""
    m = GRUB_RE.match(line)
    return line[:m.start(3)] + title + line[m.end(3):]


def g_retitle(lines, entries, product):
    """返回 (新行列表, [(旧标题, 新标题)])。"""
    out = list(lines)
    changes = []
    for start, _, title in entries:
        new = retitle(title, product)
        if new != title:
            out[start] = g_put(lines[start], new)
            changes.append((title, new))
    return out, changes


def g_default(lines, idx):
    """返回 (新行列表, 旧 default 行文本)；无 default 行时旧值为 None。"""
    new = f'set default="{idx}"'
    for pos, line in enumerate(lines):
        if GRUB_DEF.match(line):
            return lines[:pos] + [new + eol(line)] + lines[pos + 1:], \
                line.strip()
    return lines, None


def dmove(old, new, title):
    """default 行确有变化时返回报告用标题，否则返回 None。"""
    return None if old is None or old == new else title


def eol(line):
    """返回该行的换行符（含 CRLF），供替换行时保留。"""
    return line[len(line.rstrip("\r\n")):]


def grub(lines, product):
    """grub 改写计划；缺安装项返回 None。"""
    entries = g_entries(lines)
    idx = g_install(lines, entries)
    if idx is None:
        return None
    out, changes = g_retitle(lines, entries, product)
    title = retitle(entries[idx][2], product)
    out, old = g_default(out, idx)
    return out, changes, dmove(old, f'set default="{idx}"', title)


def i_blocks(lines):
    """按 label 行切块，返回 [(起始行, 结束行, label 名)]。"""
    marks = []
    for pos, line in enumerate(lines):
        m = LABEL_RE.match(line)
        if m:
            marks.append((pos, m.group(1)))
    out = []
    for idx, (start, name) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        out.append((start, end, name))
    return out


def i_ok(body):
    """append 行含 inst.ks= 且不含 rd.live.check 即为安装项。"""
    ap = [line for line in body if APPEND_RE.match(line)]
    has_ks = any("inst.ks=" in line for line in ap)
    has_check = any("rd.live.check" in line for line in ap)
    return has_ks and not has_check


def i_install(lines, blocks):
    """返回第一个安装项块；没有则返回 None。"""
    for blk in blocks:
        if i_ok(lines[blk[0] + 1:blk[1]]):
            return blk
    return None


def i_menu(line, product):
    """改写一条 menu label/title 行；无变化返回 None。"""
    text = line.rstrip("\r\n")
    m = MENU_RE.match(text)
    if not m:
        return None
    new = retitle(m.group(3), product)
    if new == m.group(3):
        return None
    return (m.group(1) + m.group(2) + new,
            (m.group(2) + m.group(3), m.group(2) + new))


def i_retitle(lines, product):
    """返回 (新行列表, [(旧文字, 新文字)])，保留行首 ^ 热键标记与行尾。

    MENU_RE 的 $ 停在该行换行符之前，匹配结果不含换行；改写行必须把原
    行尾接回去，否则 menu label 会与下一条 append 拼成一行，isolinux 解
    析器随即把安装参数整体读成菜单文字，装机直接失败。
    """
    out = list(lines)
    changes = []
    for pos, line in enumerate(lines):
        hit = i_menu(line, product)
        if hit:
            out[pos] = hit[0] + eol(line)
            changes.append(hit[1])
    return out, changes


def i_serial(line):
    """给一条 append 行补齐串口控制台；已有 console=ttyS0 时返回 None。

    只在行尾追加，原有参数顺序与字节不动：inst.ks=/inst.stage2= 的位置
    由底座与 mkksiso 共同决定，重排会让 stage2 定位失效。
    """
    text = line.rstrip("\r\n")
    if not APPEND_RE.match(text) or SERIAL_RE.search(text):
        return None
    return text + " " + SERIAL_ARG + eol(line), ("append", SERIAL_ARG)


def i_serial_all(lines):
    """返回 (新行列表, [变化])；逐条覆盖所有 append 行。"""
    out = list(lines)
    changes = []
    for pos, line in enumerate(lines):
        hit = i_serial(line)
        if hit:
            out[pos] = hit[0]
            changes.append(hit[1])
    return out, changes


def i_title(lines, blk, product):
    """取安装项块的菜单标题（品牌化后的文字）；没有则退回 label 名。"""
    for line in lines[blk[0] + 1:blk[1]]:
        m = MENU_RE.match(line)
        if m:
            return retitle(m.group(3), product)
    return blk[2]


def i_default(lines, name):
    """返回 (新行列表, 旧 default 行文本)；无 default 行时旧值为 None。"""
    new = f"default={name}"
    for pos, line in enumerate(lines):
        if DEF_RE.match(line):
            return lines[:pos] + [new + eol(line)] + lines[pos + 1:], \
                line.strip()
    return lines, None


def isolinux(lines, product):
    """isolinux 改写计划；缺安装项返回 None。"""
    blk = i_install(lines, i_blocks(lines))
    if blk is None:
        return None
    out, changes = i_retitle(lines, product)
    out, serial = i_serial_all(out)
    changes += serial
    title = i_title(lines, blk, product)
    out, old = i_default(out, blk[2])
    return out, changes, dmove(old, f"default={blk[2]}", title)


def detect(lines):
    """按行首标记判别配置方言；都不像则返回 None。"""
    if any(GRUB_RE.match(line) for line in lines):
        return grub
    if any(ISOLINUX_HINT.match(line) for line in lines):
        return isolinux
    return None


def b_parts(product):
    """把产品名拆成 (名称, 版本, 名称-版本)；无版本时后两项退化为原名。"""
    name, _, ver = product.rpartition(" ")
    if not name or not ver[:1].isdigit():
        return product, "", product
    return name, ver, f"{name}-{ver}"


def t_val(key, value, brand):
    """返回品牌键改写后的值；非品牌键或已合规时原样返回。"""
    name, ver, slug = brand
    if key == "version":
        return ver or value
    if key in ("family", "short"):
        return name if BASE_NAME.search(value) else value
    if key == "name" and BASE_NAME.search(value):
        return slug if value.lower().startswith("openeuler-") else name
    return value


def t_key(line, sec, brand):
    """改写一条 .treeinfo 键值行；无变化返回 None。"""
    text = line.rstrip("\r\n")
    m = TREE_KEY.match(text)
    if not m:
        return None
    key = m.group(2).lower()
    val = m.group(4)
    tail = val[len(val.rstrip()):]
    new = t_val(key, val.rstrip(), brand)
    if new == val.rstrip():
        return None
    body = m.group(1) + m.group(2) + m.group(3) + new + tail
    return body + eol(line), (f"{sec}.{key}={val.rstrip()}", new)


def t_plan(lines, product):
    """只改 general/release/product 段的品牌键，段名与其余行原样保留。"""
    brand = b_parts(product)
    sec = ""
    out = list(lines)
    changes = []
    for pos, line in enumerate(lines):
        m = SECT_RE.match(line)
        if m:
            sec = m.group(1).strip().lower()
            continue
        if sec not in TREE_SEC:
            continue
        hit = t_key(line, sec, brand)
        if hit:
            out[pos] = hit[0]
            changes.append(hit[1])
    return out, changes, None


def bm_plan(lines, product):
    """只替换 boot.msg 里明确的底座品牌串，行序与版面不动。"""
    text = "".join(lines)
    hits = BASE_MSG.findall(text)
    if not hits:
        return list(lines), [], None
    out = BASE_MSG.sub(product, text)
    return out.splitlines(True), [(hit, product) for hit in hits], None


def d_plan(lines, product):
    """只改 .discinfo 的发行版名行（第二行），时间戳与架构行原样保留。

    该文件四行固定为「时间戳 / 发行版 / 架构 / 变体」，行序是 anaconda 的
    读取契约，因此不按内容搜行、直接落在第二行；不以 openEuler 开头的
    第二行原样返回，避免把非底座介质误改成产品名。
    """
    if len(lines) < 2:
        return list(lines), [], None
    text = lines[1].rstrip("\r\n")
    if not BASE_NAME.search(text):
        return list(lines), [], None
    out = list(lines)
    out[1] = product + eol(lines[1])
    return out, [(text, product)], None


def dialect(path, lines):
    """按文件名后缀分派介质类型，其余回落到引导配置方言判别。

    后缀而非全等：回读校验把提取副本命名为 verify.<原名>，全等匹配会
    让数据文件在幂等断言处退化成「无法识别」。
    """
    name = path.name
    if name.endswith(".treeinfo"):
        return t_plan
    if name.endswith(".discinfo"):
        return d_plan
    if name.endswith("boot.msg"):
        return bm_plan
    return detect(lines)


def report(path, changes, dchg):
    """每个变化向 stderr 打一行。"""
    for old, new in changes:
        print(f"cfg_brand: {path}: {old} -> {new}", file=sys.stderr)
    if dchg:
        print(f"cfg_brand: {path}: default -> {dchg}", file=sys.stderr)


def apply(path, raw, product):
    """生成改写计划；确有变化才写回。"""
    plan = dialect(path, raw.splitlines(keepends=True))
    if plan is None:
        print(f"cfg_brand: {path}: 无法识别引导配置或缺少 inst.ks 安装项",
              file=sys.stderr)
        return BAD
    result = plan(raw.splitlines(keepends=True), product)
    if result is None:
        print(f"cfg_brand: {path}: 缺少含 inst.ks 且不含 rd.live.check 的"
              "安装项", file=sys.stderr)
        return BAD
    out, changes, dchg = result
    text = "".join(out)
    if text == raw:
        return SAME
    report(path, changes, dchg)
    path.write_bytes(text.encode("utf-8"))
    return OK


def parse(argv):
    """解析 CLI；返回 (product, path)，--help 返回 (None, None)。"""
    if any(arg in ("-h", "--help") for arg in argv):
        return None, None
    product = None
    files = []
    pos = 0
    while pos < len(argv):
        arg = argv[pos]
        if arg == "--product" and pos + 1 < len(argv):
            product = argv[pos + 1]
            pos += 2
        elif arg.startswith("--product="):
            product = arg.split("=", 1)[1]
            pos += 1
        elif arg.startswith("-"):
            raise ValueError(f"未知参数: {arg}")
        else:
            files.append(arg)
            pos += 1
    if not product or len(files) != 1:
        raise ValueError("需要 --product 与唯一 FILE")
    return product, files[0]


def main(argv):
    try:
        product, name = parse(argv)
    except ValueError as exc:
        print(f"cfg_brand: {exc}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return ERR
    if product is None:
        print(USAGE)
        return OK
    path = Path(name)
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"cfg_brand: {exc}", file=sys.stderr)
        return BAD
    return apply(path, raw, product)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
