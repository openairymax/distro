#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# desktop_ready.sh — UKUI 桌面登录链就绪探针
#
# 安装后的启动验收需要区分「内核起来了」与「桌面能进」。本脚本在
# graphical.target 达成后做三级校验：先读 systemd 的失败记账，再静态确认
# UKUI 会话定义存在且其 Exec 可执行（lightdm 的 user-session 指向它），
# 最后检查 lightdm 单元处于 active 且存在 Service=lightdm、Class=greeter、
# Type=x11 的活动会话。全部成立才向串口打印 AIRYMAX-DESKTOP-READY。
#
# 失败记账放在最前：系统是否「正常运行」的判据是 systemd 的单元状态，而
# 不是串口里有没有某行文本。宿主机按文本判负会与内核日志争抢截断点，
# 也会把单元失败与桌面失败混成同一个结论。这里如实上报一项，再由宿主
# 机按标记归因。
#
# 失败以非零退出码上报，由 install-test.sh 的 BOOT_FAIL 规则捕获；不写
# 任何状态文件，避免与 systemd 状态形成第二个事实源。
#
# 部署：airymaxos-release 包安装到 /usr/lib/airymaxos/desktop/。
# 调用：airymax-desktop-ready.service（WantedBy=graphical.target）。
# ===========================================================================
set -uo pipefail

READY_WAIT="${AIRYMAX_READY_WAIT:-90}"
POLL="${AIRYMAX_READY_POLL:-2}"
GREETER_SVC="lightdm"
GREETER_CLASS="greeter"
GREETER_TYPE="x11"
SESSION_NAME="ukui"
XSESSIONS_DIR="${AIRYMAX_XSESSIONS_DIR:-/usr/share/xsessions}"
UKUI_SESSION="${XSESSIONS_DIR}/${SESSION_NAME}.desktop"

session_exec()
{
    local line value=""

    [ -r "${UKUI_SESSION}" ] || return 1
    while IFS= read -r line; do
        case "${line}" in
        Exec=*) value="${line#Exec=}" ;;
        esac
    done <"${UKUI_SESSION}"
    value="${value%% *}"
    [ -n "${value}" ] || return 1
    case "${value}" in
    /*) [ -x "${value}" ] ;;
    *) command -v "${value}" >/dev/null 2>&1 ;;
    esac
}

session_field()
{
    loginctl show-session "$1" -p "$2" --value 2>/dev/null || true
}

session_key()
{
    printf '%s|%s|%s|%s\n' \
        "$(session_field "$1" Service)" \
        "$(session_field "$1" Class)" \
        "$(session_field "$1" Type)" \
        "$(session_field "$1" State)"
}

greeter_session()
{
    local id

    for id in $(loginctl list-sessions --no-legend 2>/dev/null |
                    awk '{print $1}'); do
        case "$(session_key "${id}")" in
        "${GREETER_SVC}|${GREETER_CLASS}|${GREETER_TYPE}|active" | \
        "${GREETER_SVC}|${GREETER_CLASS}|${GREETER_TYPE}|online")
            printf '%s\n' "${id}"
            return 0
            ;;
        esac
    done
    return 1
}

unit_active()
{
    systemctl is-active --quiet "$1.service" 2>/dev/null
}

# 失败记账只在本次启动内有效，不落盘；空集合才打印 HEALTH，非空打印
# DEGRADED 并附单元清单，宿主机据此直接归因到具体单元。
boot_health()
{
    local list

    list=$(systemctl list-units --failed --no-legend --plain --no-pager \
        2>/dev/null | awk 'NF { print $1 }' | sort -u)
    if [ -z "${list}" ]; then
        printf 'AIRYMAX-BOOT-HEALTH failed=0\n'
        return 0
    fi
    printf 'AIRYMAX-BOOT-DEGRADED failed=%s units=%s\n' \
        "$(printf '%s\n' "${list}" | wc -l)" "${list//$'\n'/,}"
    return 1
}

ready_once()
{
    unit_active "${GREETER_SVC}" || return 1
    greeter_session >/dev/null || return 1
}

wait_ready()
{
    local waited=0

    while :; do
        ready_once && return 0
        [ "${waited}" -ge "${READY_WAIT}" ] && return 1
        sleep "${POLL}"
        waited=$((waited + POLL))
    done
}

main()
{
    boot_health || return 1
    if ! session_exec; then
        printf 'AIRYMAX-DESKTOP-FAIL reason=session path=%s\n' \
            "${UKUI_SESSION}"
        return 1
    fi
    if wait_ready; then
        printf 'AIRYMAX-DESKTOP-READY unit=%s class=%s type=%s\n' \
            "${GREETER_SVC}" "${GREETER_CLASS}" "${GREETER_TYPE}"
        return 0
    fi
    printf 'AIRYMAX-DESKTOP-FAIL unit=%s wait=%ss\n' \
        "${GREETER_SVC}" "${READY_WAIT}"
    return 1
}

main "$@"
