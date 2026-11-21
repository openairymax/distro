# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# 75-airymax-power-tray.sh — 会话启动前按硬件收口电量托盘
#
# 症状：run 44829873253 的 x86_64 UEFI 光盘腿，登录后一秒内
# ukui-power-manager-tray 崩溃。串口留下 print-fatal-signals 的寄存器转储
# （RIP 落在共享库、R12=0 后解引用），随后 systemd-coredump 报 dumped core；
# 同一轮的 U 盘腿与 BIOS 腿同样没有电池，托盘却在位未崩。
#
# 根因：托盘只在有电池时有显示对象。没有 power_supply 设备时它起手即退，
# 退出路径上的工作线程与已析构的对象竞争，偶发解引用空指针。这不是验收
# 环境独有的形态——没有电池的台式机同样命中，属于产品级稳定性缺口。
# 判定读 sysfs 的 type 而不是 BAT* 名称：type 是 ABI，命名是惯例，与
# system/services/airymax_power 的识别口径同源。
#
# 修法：与 65-airymax-audio.sh 同一类前置判据——「托盘何时该起」由会话脚本
# 表达，不留给每个组件自己猜。有电池时保持发行默认；没有电池时在用户级
# autostart 落一条 Hidden=true 的抑制条目：ukui-session 的搜索顺序以
# ~/.config/autostart 优先，同名条目覆盖 /etc/xdg/autostart 里的发行条目。
# 条目带 X-AirymaxOS-Gate 标记，只有确属本脚本所写时才删改。
#
# 只在需要时写：有电池且条目不存在时一次 stat 即返回，不产生文件写入；
# 判据读不到时按「有电池」处理——信息不足时不做减法，托盘照常起。
#
# 本文件被 POSIX sh source，禁止 bash 专有语法，禁止 set -e/-u 影响调用方，
# 失败一律 return 0（登录流程必须继续）。编号大于 70：输入法环境定完之后
# 再落判据；本段不做任何 IO 等待。
#
# SSoT: distro/ci/session-baseline.txt 的 gate 判据与本文同源；
#       distro/ci/run-smoke.sh 的 T30 断言抑制条目与硬件状态一致。
# ===========================================================================

[ -n "${HOME:-}" ] || return 0

airy_supply="${AIRY_POWER_SUPPLY:-/sys/class/power_supply}"
airy_vendor="${AIRY_AUTOSTART_DIR:-/etc/xdg/autostart}/ukui-power-manager-tray.desktop"
airy_udir="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart"
airy_drop="${airy_udir}/ukui-power-manager-tray.desktop"

airy_bat=0
for airy_type in "${airy_supply}"/*/type; do
    [ -r "${airy_type}" ] || continue
    if [ "$(cat "${airy_type}" 2>/dev/null)" = Battery ]; then
        airy_bat=1
        break
    fi
done

if [ "${airy_bat}" -eq 1 ]; then
    if [ -r "${airy_drop}" ] &&
        grep -qx 'X-AirymaxOS-Gate=power-tray' "${airy_drop}" 2>/dev/null; then
        rm -f "${airy_drop}" 2>/dev/null || :
    fi
    return 0
fi

[ -r "${airy_vendor}" ] || return 0
[ -d "${airy_udir}" ] || mkdir -p "${airy_udir}" 2>/dev/null || return 0

if ! grep -qx 'X-AirymaxOS-Gate=power-tray' "${airy_drop}" 2>/dev/null; then
    printf '%s\n' \
        '[Desktop Entry]' \
        'Type=Application' \
        'Name=Power Manager Tray (AirymaxOS hardware gate)' \
        'Hidden=true' \
        'X-AirymaxOS-Gate=power-tray' >"${airy_drop}.airy-new" 2>/dev/null &&
        mv -f "${airy_drop}.airy-new" "${airy_drop}" 2>/dev/null || :
fi

printf 'airymax-power-tray: no battery, tray gated\n' >&2

return 0
