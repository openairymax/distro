#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# console-font.sh — 控制台字体策略的唯一实现
#
# 为什么单独成文件：同一件事要落在两个时刻，而它们的触发者不同。新装机时
# 包事务跑完之后，anaconda 才按 kickstart 的 keyboard 指令重写
# /etc/vconsole.conf，包 %post 写下的 FONT 被覆盖回默认 sun16；升级路径上
# 没有 anaconda，只有包 %post 会跑。两条路径各写一遍，就必然在某一侧漂移
# ——0.0.4 验收 run 42960420278 的 T22 正是这样红的：包 %post 改过，装机
# 末尾被 anaconda 覆盖，/dev/vcs1 上仍是 8x16。
#
# 因此两个调用点都只调用本脚本：包 %post（升级）与 kickstart %post（新装，
# 在 anaconda 写完配置之后）。判据、写入口径、证据格式只在这里定义一次。
#
# 为什么值得改：默认 latarcyrheb-sun16 是 8x16，在 285H 的 2880x1800 面板上
# 一屏 360x112 个约 0.8x1.7 mm 的字形，九行阶段行即使全是 ASCII 也读不出
# （2026-11-09 实机）。同一 kbd 字体集里的 latarcyrheb-sun32 是 16x32，得到
# 180x56，不需要改内核配置，也不影响桌面：X 跑在 fbdev 上用自己的分辨率与
# Xft 字号。
#
# 字体文件缺席时一个字节都不写：指向不存在的字体只会让控制台黑屏，比小字
# 更糟。%{_sysconfdir}/vconsole.conf 归 systemd-udev 包，本脚本再持有同一
# 路径会让安装事务整体失败（与 /etc/motd、plymouthd.conf 同一条约束）；
# vconsole.conf.d 的 drop-in 要 systemd 256，基线是 255。所以只按行替换
# FONT，其余键（KEYMAP 等本包并不拥有的口径）原样保留。
#
# 自证：每次运行追加一行到 /var/log/airymaxos/console-font.log。%post 的
# stdout 不进 install.log，装机现场只能靠这一行判断本节跑没跑、写没写、是
# 因为字体缺席而跳过。
#
# 退出码：0 已收敛或按判据跳过；1 写入失败；2 用法错误。
# ===========================================================================
set -eu

CF_FAIL=1
CF_USE=2
airy_cf_font=${AIRY_CONSOLE_FONT:-latarcyrheb-sun32}
airy_cf_dir=${AIRY_CONSOLE_FONT_DIR:-/usr/lib/kbd/consolefonts}
airy_cf_conf=${AIRY_CONSOLE_CONF:-/etc/vconsole.conf}
airy_cf_log=${AIRY_CONSOLE_LOG:-/var/log/airymaxos/console-font.log}

airy_cf_usage()
{
    printf '%s\n' '用法: console-font.sh'
}

# airy_cf_note TEXT —— 自证行。日志写不进去时静默返回：字体本身已经收敛，
# 证据丢了不该让调用方（包 %post / 装机 %post）失败。
airy_cf_note()
{
    mkdir -p "${airy_cf_log%/*}" 2>/dev/null || return 0
    printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" \
        >>"${airy_cf_log}" 2>/dev/null || :
    return 0
}

# airy_cf_cur —— 打印当前 FONT 值（去掉引号），没有则空。
airy_cf_cur()
{
    [ -r "${airy_cf_conf}" ] || return 0
    sed -n 's/^[[:space:]]*FONT=//p' "${airy_cf_conf}" | sed -n '1p' |
        tr -d '"'
}

# airy_cf_write —— 按行替换或追加。返回 1 表示写失败，由调用方落证据。
airy_cf_write()
{
    if [ -n "$1" ]; then
        sed -i "s|^[[:space:]]*FONT=.*|FONT=\"${airy_cf_font}\"|" \
            "${airy_cf_conf}"
    else
        printf 'FONT="%s"\n' "${airy_cf_font}" >>"${airy_cf_conf}"
    fi
}

# airy_cf_has —— 字体文件是否在盘上。四种后缀都要认：kbd 的打包姿态随
# 基底变化，只认 .psfu.gz 时换成未压缩的包就会静默跳过（T22 判据同样认四种，
# 两处口径必须一致）。
airy_cf_has()
{
    for cf_ext in psfu.gz psf.gz psfu psf; do
        if [ -f "${airy_cf_dir}/${airy_cf_font}.${cf_ext}" ]; then
            return 0
        fi
    done
    return 1
}

airy_cf_apply()
{
    if ! airy_cf_has; then
        airy_cf_note "skip font=${airy_cf_font} reason=absent dir=${airy_cf_dir}"
        return 0
    fi
    cf_cur=$(airy_cf_cur) || cf_cur=
    if [ "${cf_cur}" = "${airy_cf_font}" ]; then
        airy_cf_note "ok font=${airy_cf_font} state=already"
        return 0
    fi
    if ! airy_cf_write "${cf_cur}"; then
        airy_cf_note "fail font=${airy_cf_font} conf=${airy_cf_conf}"
        return "${CF_FAIL}"
    fi
    airy_cf_note "ok font=${airy_cf_font} state=written was=${cf_cur:-none}"
}

airy_cf_main()
{
    case "${1:-}" in
    '') ;;
    -h | --help) airy_cf_usage; return 0 ;;
    *) airy_cf_usage >&2; return "${CF_USE}" ;;
    esac
    airy_cf_apply
}

case "${0##*/}" in
console-font.sh) airy_cf_main "$@" || exit $? ;;
esac
