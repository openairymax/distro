#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airymax-alive.sh — 验收镜像的存活心跳
#
# 冷启动判负时串口只留下「没有到达默认目标」这一段事实，分不清是 PID1
# 停住还是图形栈停住；机器上到底有没有 KMS 设备，也要等登进机器才知道。
# 心跳每 30 秒直写串口一行，把这两件事变成下一次开机能直接回读的事实：
# 有 AIRYMAX-ALIVE 就说明 PID1 与作业队列还在跑，dri=0 就说明没有图形
# 设备、X 无从启动。
#
# 直写 /dev/ttyS0 而不写 /dev/console：后者归内核命令行里最后一个
# console=，本项目是 console=ttyS0,115200 console=tty0，落点在本地屏，
# 只接串口的现场读不到（run 41925092075 因此丢了整段卡点证据）。
#
# 只进验收镜像，不进产品配方：产品机器的串口不该被周期性噪声占满。
# ===========================================================================
set -euo pipefail

readonly DEV="${AIRY_ALIVE_DEV:-/dev/ttyS0}"

cnt() {
    awk 'NF { c++ } END { print c + 0 }'
}

# 计数命令自身失败时按 0 处理：观测者不能因为一次查询失败就留下半行输出。
tally() {
    { "$@" 2>/dev/null || :; } | cnt
}

alive() {
    local jobs bad dri up tgt dm

    jobs="$(tally systemctl list-jobs --no-legend --plain --no-pager)"
    bad="$(tally systemctl list-units --failed --no-legend --plain --no-pager)"
    dri="$(tally ls -1 /dev/dri)"
    up="$(cut -d. -f1 /proc/uptime 2>/dev/null || :)"
    tgt="$(systemctl is-active graphical.target 2>/dev/null || :)"
    dm="$(systemctl is-active lightdm.service 2>/dev/null || :)"
    printf 'AIRYMAX-ALIVE uptime=%ss jobs=%s dri=%s graphical=%s dm=%s' \
        "${up:-0}" "${jobs:-0}" "${dri:-0}" "${tgt:-unknown}" "${dm:-unknown}"
    printf ' failed=%s\n' "${bad:-0}"
}

alive >"${DEV}" 2>&1 || :
