#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# desktop_ready.sh — UKUI 桌面登录链就绪探针
#
# 安装后的启动验收需要区分「内核起来了」与「桌面能进」。本脚本在
# graphical.target 达成后做两级校验：先静态确认 UKUI 会话定义存在且其
# Exec 可执行（lightdm 的 user-session 指向它），再检查 lightdm 单元处于
# active 且存在 Service=lightdm、Class=greeter、Type=x11 的活动会话。
# 全部成立才向串口打印 AIRYMAX-DESKTOP-READY。
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
