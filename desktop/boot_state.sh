#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# boot_state.sh — 启动期失败单元记账与有界取证（共享库）
#
# 产品就绪探针（desktop_ready.sh）与验收 ISO 的串口上报
# （airymax-smoke-report.sh）回答的是同一个问题：本次启动有没有单元失败，
# 分别是哪几个。判定与上报若各写一份实现，两个观测点迟早给出两套语义，
# 因此记账与取证只在这里实现，调用方只决定何时调用、失败如何落结论。
#
# 记账不落盘：systemd 已经是唯一事实源，再写状态文件会制造第二个事实源。
# 有界取证只在存在失败单元时输出，干净启动不受影响：
#   AIRYMAX-UNIT-STATE|<unit>|ActiveState=... SubState=... Result=...
#       NRestarts=... MainPID=...
#   AIRYMAX-UNIT-JOURNAL|<unit>|<journal 原文行>
# 每单元最多 UNIT_LOG_MAX 行，最多覆盖 UNIT_LIST_MAX 个单元；DEGRADED 行
# 的 failed= 始终是真实总数，units= 只列被取证的前若干个，两者不混用，
# 避免把「截断后的清单」误读成「全部失败单元」。
#
# 这两个标记是观测通道，不参与任何判定；判定只看 AIRYMAX-BOOT-HEALTH 与
# AIRYMAX-BOOT-DEGRADED。
#
# 部署：airymaxos-release 包安装到 /usr/lib/airymaxos/desktop/。
# 依赖：bash、systemctl、journalctl、awk、sed。
# ===========================================================================

UNIT_LOG_MAX="${AIRYMAX_UNIT_LOG:-12}"
UNIT_LIST_MAX="${AIRYMAX_UNIT_LIST:-8}"

failed_units()
{
    local out

    out=$(systemctl list-units --failed --no-legend --plain --no-pager \
        2>/dev/null) || return 1
    printf '%s\n' "${out}" | awk 'NF { print $1 }' | sort -u
}

unit_state()
{
    local out

    out=$(systemctl show -p ActiveState -p SubState -p Result \
        -p NRestarts -p MainPID "$1" 2>/dev/null) || return 0
    [ -n "${out}" ] || return 0
    printf 'AIRYMAX-UNIT-STATE|%s|%s\n' "$1" "${out//$'\n'/ }"
}

unit_log()
{
    journalctl -b -u "$1" -n "${UNIT_LOG_MAX}" -o cat --no-pager \
        2>/dev/null | sed "s#^#AIRYMAX-UNIT-JOURNAL|$1|#"
}

unit_evidence()
{
    local unit count=0

    while IFS= read -r unit; do
        [ -n "${unit}" ] || continue
        unit_state "${unit}"
        unit_log "${unit}"
        count=$((count + 1))
        [ "${count}" -ge "${UNIT_LIST_MAX}" ] && break
    done
}

boot_health()
{
    local list total shown

    if ! list=$(failed_units); then
        printf 'AIRYMAX-BOOT-DEGRADED failed=unknown units=none\n'
        return 1
    fi
    if [ -z "${list}" ]; then
        printf 'AIRYMAX-BOOT-HEALTH failed=0\n'
        return 0
    fi
    total=$(printf '%s\n' "${list}" | awk 'END { print NR }')
    shown=$(printf '%s\n' "${list}" |
        awk -v max="${UNIT_LIST_MAX}" 'NR <= max')
    printf 'AIRYMAX-BOOT-DEGRADED failed=%s units=%s\n' \
        "${total}" "${shown//$'\n'/,}"
    printf '%s\n' "${shown}" | unit_evidence
    return 1
}
