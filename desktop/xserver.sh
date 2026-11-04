#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
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
# 0.0.4 把判据从「驱动名不是 simple-framebuffer」升级为三条同时成立：
# 真实 KMS 驱动、某个连接器已连接、该连接器同时给出可枚举模式与非空 EDID。
# 驱动名只能说明内核绑上了显卡，说明不了这块屏能不能用。i915/amdgpu 加载
# 成功但面板未点亮、eDP 无 EDID、或者只剩 disconnected 端口时，旧判据照旧
# 交给 X 自动选择，X 随后在模式求交上失败，表现为「进了桌面但黑屏」。三条
# 全成立才走自动选择（即 modesetting），否则落 fbdev 并把缺的哪一条写进
# 标记，让现场一眼看出是驱动没起来、屏没接、还是 EDID 没读到。
#
# 判定只看 sysfs 的驱动名、连接器状态、modes 内容与 EDID 大小，不看显卡型
# 号：换任何机器都不需要改这份脚本。
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

# probe — 一次扫描给出判定：`kms <驱动名>` 或 `gap <缺口>`。
# 缺口取值：no-kms（没有真实 KMS 卡）、no-output（有卡但无已连接输出）、
# no-mode（已连接但模式表为空）、no-edid（有模式但 EDID 为空）。
probe()
{
    local card out drv seen=""

    for card in "${DRM}"/card[0-9]*; do
        [ -d "${card}" ] || continue
        case "${card##*/}" in
        *-*) continue ;;
        esac
        drv=$(driver_of "${card}") || continue
        seen=no-output
        for out in "${card}"-*; do
            [ -d "${out}" ] || continue
            [ "$(cat "${out}/status" 2>/dev/null)" = connected ] || continue
            has_mode "${out}/modes" || {
                printf 'gap no-mode\n'
                return 0
            }
            [ -s "${out}/edid" ] || {
                printf 'gap no-edid\n'
                return 0
            }
            printf 'kms %s\n' "${drv}"
            return 0
        done
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
