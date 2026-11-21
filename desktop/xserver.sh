#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# xserver.sh — 座位 X server 启动封装（lightdm 的 xserver-command）
#
# 部署：airymaxos-release 包安装为 /usr/lib/airymaxos/desktop/xserver。
#
# 为什么要这一层：X 1.20 的自动配置按「有没有 DRM 设备」选择驱动，有则
# modesetting，无则 vesa。只有 simpledrm 的机器两条路都走不通——simpledrm
# 登记了 card0 与 /dev/fb0，vesa 因此拒绝运行（Framebuffer or dri device
# present），而 1.20 的 modesetting 同样不接管 simpledrm，最终以
# "Cannot run in framebuffer mode" 收场，lightdm 每次拉起都失败，桌面永远
# 起不来。fbdev 是唯一直接消费 /dev/fb0 的后端，所以在缺口上显式交给它。
#
# 0.0.5 把判据收敛为两条：真实 KMS 驱动，且某个连接器已连接并有可枚举模式。
# 驱动名只能说明内核绑上了显卡，说明不了这块屏能不能用；连接器与模式才是
# X 真正消费的东西——modesetting 从连接器模式表取模式，不读 EDID。0.0.4 曾
# 把「EDID 非空」也列为前提，结果把 QEMU virtio-gpu 这类按设计不提供 EDID
# 的虚拟输出误判成缺口，落到 fbdev 后 X 报 "no screens found"，座位每次拉起
# 即死（aarch64 验收现场）。EDID 只说明面板身份与首选时序，不说明能否扫描
# 输出，因此不再参与判定；缺它时 modesetting 仍用连接器广播的模式。
#
# 判定只看 sysfs 的驱动名、连接器状态与 modes 内容，不看显卡型号：换任何
# 机器都不需要改这份脚本。
#
# 入口：lightdm 按 xserver-command 调用，参数原样转交 Xorg。
# 输出：一行 AIRYMAX-XSERVER 标记，同时写到 stdout 与固定状态文件
#       （默认 /run/airymaxos/xserver.log）。现场据此区分四种收场：
#         driver=<kms> kms=1                 自动选择（modesetting）
#         driver=fbdev reason=<缺口> fb=…      fbdev 兜底，缺口取值见 probe
#         driver=none note=no-display          不适用：无 KMS 也无 framebuffer
#         driver=fbdev … note=conf-unwritable  兜底配置写不进去，退回自动选择
#       lightdm 不接管 xserver-command 的 stdout，x-0.log 里看不到它
#       （B50 实测零命中），所以取证面是状态文件，stdout 只是给手工执行留
#       的即时回显。
# ===========================================================================

set -u

DRM="${AIRYMAX_DRM_DIR:-/sys/class/drm}"
FB="${AIRYMAX_FB_DEV:-/dev/fb0}"
CONF="${AIRYMAX_XSERVER_CONF:-/run/airymaxos/xserver-fbdev.conf}"
STATE="${AIRYMAX_XSERVER_STATE:-/run/airymaxos/xserver.log}"
XORG="${AIRYMAX_XORG:-Xorg}"
PLATFORM="simple-framebuffer"

mark()
{
    printf 'AIRYMAX-XSERVER %s\n' "$*"
    mkdir -p "${STATE%/*}" 2>/dev/null
    printf 'AIRYMAX-XSERVER %s\n' "$*" >"${STATE}" 2>/dev/null
}

driver_of()
{
    local drv

    [ -e "$1/device/driver" ] || return 1
    drv=$(readlink -f "$1/device/driver") || return 1
    drv=${drv##*/}
    [ "${drv}" = "${PLATFORM}" ] && return 1
    printf '%s\n' "${drv}"
}

has_mode()
{
    grep -q '[^[:space:]]' "$1" 2>/dev/null
}

# out_verdict <out> <drv> — 一个已连接输出的判定：模式表非空即认 kms。
# EDID 不参与判定：虚拟输出按设计可以没有 EDID，而 modesetting 用连接器
# 模式表，不用 EDID。
out_verdict()
{
    local out="$1" drv="$2"

    has_mode "${out}/modes" || {
        printf 'gap no-mode\n'
        return 0
    }
    printf 'kms %s\n' "${drv}"
}

# card_out <card> <drv> — 该卡第一个已连接输出的判定；无已连接输出返回非零。
card_out()
{
    local out

    for out in "$1"-*; do
        [ -d "${out}" ] || continue
        [ "$(cat "${out}/status" 2>/dev/null)" = connected ] || continue
        out_verdict "${out}" "$2"
        return 0
    done
    return 1
}

# probe — 一次扫描给出判定：`kms <驱动名>` 或 `gap <缺口>`。
# 缺口取值：no-kms（没有真实 KMS 卡）、no-output（有卡但无已连接输出）、
# no-mode（已连接但模式表为空）。
probe()
{
    local card drv seen=""

    for card in "${DRM}"/card[0-9]*; do
        [ -d "${card}" ] || continue
        case "${card##*/}" in
        *-*) continue ;;
        esac
        drv=$(driver_of "${card}") || continue
        seen=no-output
        card_out "${card}" "${drv}" && return 0
    done
    printf 'gap %s\n' "${seen:-no-kms}"
}

fbdev_conf()
{
    mkdir -p "${CONF%/*}" 2>/dev/null || return 1
    printf '%s\n' \
        'Section "Device"' \
        '    Identifier "airymax-fbdev"' \
        '    Driver "fbdev"' \
        "    Option \"fbdev\" \"${FB}\"" \
        'EndSection' >"${CONF}" 2>/dev/null || return 1
    printf '%s\n' "${CONF}"
}

main()
{
    local verdict why conf

    verdict=$(probe)
    if [ "${verdict%% *}" = kms ]; then
        mark "driver=${verdict#* } kms=1"
        exec "${XORG}" "$@"
    fi
    why=${verdict#* }
    if [ ! -e "${FB}" ]; then
        mark "driver=none note=no-display"
        exec "${XORG}" "$@"
    fi
    if ! conf=$(fbdev_conf); then
        mark "driver=fbdev reason=${why} note=conf-unwritable"
        exec "${XORG}" "$@"
    fi
    printf 'airymaxos: display gap %s, falling back to fbdev %s\n' \
        "${why}" "${FB}" >&2
    mark "driver=fbdev reason=${why} fb=${FB} conf=${conf}"
    exec "${XORG}" -config "${conf}" "$@"
}

main "$@"
