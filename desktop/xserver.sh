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
# 起不来。fbdev 是唯一直接消费 /dev/fb0 的后端，所以在「有 card 但没有任何
# 真实 KMS 驱动」时显式交给它；其余情形保持 X 的自动选择，正常机器行为不变。
#
# 判定只看 sysfs 的驱动名，不看显卡型号：i915、amdgpu、virtio_gpu、nouveau
# 等一律视为正常路径，只有 simple-framebuffer 视为缺口，因此换任何机器都不
# 需要改这份脚本。
#
# 入口：lightdm 按 xserver-command 调用，参数原样转交 Xorg。
# 输出：一行 AIRYMAX-XSERVER 标记，落在 /var/log/lightdm/x-*.log 里，
#       现场据此区分「走了自动选择」与「走了 fbdev 兜底」。
# ===========================================================================

set -u

DRM="${AIRYMAX_DRM_DIR:-/sys/class/drm}"
FB="${AIRYMAX_FB_DEV:-/dev/fb0}"
CONF="${AIRYMAX_XSERVER_CONF:-/run/airymaxos/xserver-fbdev.conf}"
XORG="${AIRYMAX_XORG:-Xorg}"
PLATFORM="simple-framebuffer"

dev_driver()
{
    local link drv

    for link in "${DRM}"/card[0-9]*/device/driver; do
        [ -e "${link}" ] || continue
        drv=$(readlink -f "${link}") || continue
        [ "${drv##*/}" = "${PLATFORM}" ] && continue
        printf '%s\n' "${drv##*/}"
        return 0
    done
    return 1
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
    local drv conf

    if drv=$(dev_driver); then
        printf 'AIRYMAX-XSERVER driver=%s\n' "${drv}"
        exec "${XORG}" "$@"
    fi
    if [ ! -e "${FB}" ]; then
        printf 'AIRYMAX-XSERVER driver=none note=no-fb\n'
        exec "${XORG}" "$@"
    fi
    if ! conf=$(fbdev_conf); then
        printf 'AIRYMAX-XSERVER driver=fbdev note=conf-unwritable\n'
        exec "${XORG}" "$@"
    fi
    printf 'AIRYMAX-XSERVER driver=fbdev fb=%s conf=%s\n' "${FB}" "${conf}"
    exec "${XORG}" -config "${conf}" "$@"
}

main "$@"
