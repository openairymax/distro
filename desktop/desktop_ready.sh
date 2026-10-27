#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# desktop_ready.sh — UKUI 桌面登录链就绪探针
#
# 安装后的启动验收需要区分「内核起来了」与「桌面能进」。本脚本在
# graphical.target 达成后做三级校验：先读 systemd 的失败记账，再静态确认
# UKUI 会话定义存在且其 Exec 可执行（lightdm 的 user-session 指向它），
# 最后检查 lightdm 单元处于 active 且存在归其所有、Type=x11 的活动会话。
# 全部成立才向串口打印 AIRYMAX-DESKTOP-READY。
#
# 会话类别按交付的座位策略取并集，不钉死单一类别：50-airymax.conf 启用
# autologin（0.0.3 的免密桌面决策），lightdm 因此跳过 greeter，直接以
# lightdm-autologin 服务拉起 Class=user 的 X11 会话；未启用 autologin 的
# 机器停在 Class=greeter 的 greeter 会话。两者都表示登录链已到达 X11，
# 只认 greeter 会让启用 autologin 的镜像永远等不到就绪标记。桌面进程是否
# 真的活着由会话内冒烟（run-smoke.sh T1）判定，本探针不做第二事实源。
#
# 失败记账放在最前：系统是否「正常运行」的判据是 systemd 的单元状态，而
# 不是串口里有没有某行文本。宿主机按文本判负会与内核日志争抢截断点，
# 也会把单元失败与桌面失败混成同一个结论。这里如实上报一项，再由宿主
# 机按标记归因。
#
# 记账与取证由 boot_state.sh 提供：验收 ISO 的串口上报是同一套判据的另一
# 个消费者，两处各写一份实现会让观测点给出不同语义。库缺失按硬失败处理，
# 不做无取证的回退。
#
# 失败以非零退出码上报，由 install-test.sh 的 BOOT_FAIL 规则捕获；不写
# 任何状态文件，避免与 systemd 状态形成第二个事实源。
#
# 失败前的 AIRYMAX-DESKTOP-DIAG 行是观测通道，不参与任何判定，也不改变
# 退出码。冷启动失败时宿主只能拿到「等了 N 秒」，无法区分是单元未激活、
# greeter 崩溃、X server 未起还是进程阻塞在某个内核路径上；逐轮加日志重跑
# 的代价极高，因此这里一次性把可归因的五类证据（单元状态、单元 journal、
# lightdm 与 greeter 日志、X server 日志、主进程 wchan）有界地带出。
# 每类证据的行数固定上限，避免串口被日志淹没；证据缺失按正常情况跳过。
#
# 部署：airymaxos-release 包安装到 /usr/lib/airymaxos/desktop/。
# 调用：airymax-desktop-ready.service（WantedBy=graphical.target）。
# ===========================================================================
set -uo pipefail

BOOT_STATE="${AIRYMAX_BOOT_STATE:-${0%/*}/boot_state.sh}"
if [ ! -r "${BOOT_STATE}" ]; then
    printf 'AIRYMAX-DESKTOP-FAIL reason=boot-state path=%s\n' "${BOOT_STATE}"
    exit 1
fi
# shellcheck source=boot_state.sh
. "${BOOT_STATE}"

READY_WAIT="${AIRYMAX_READY_WAIT:-90}"
POLL="${AIRYMAX_READY_POLL:-2}"
SESS_SVC="lightdm"
SESS_CLASSES="greeter user"
SESS_TYPE="x11"
SESS_STATES="active online"
SESSION_NAME="ukui"
XSESSIONS_DIR="${AIRYMAX_XSESSIONS_DIR:-/usr/share/xsessions}"
UKUI_SESSION="${XSESSIONS_DIR}/${SESSION_NAME}.desktop"
DIAG_MAX="${AIRYMAX_DIAG_LINES:-20}"
LDM_LOG_DIR="${AIRYMAX_LIGHTDM_LOG:-/var/log/lightdm}"
READY_ID=""

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

# lightdm 的 greeter 与 autologin 走各自独立的 PAM 服务，logind 分别记为
# Service=lightdm-greeter / lightdm-autologin，只有显式登录才记为 lightdm；
# 判定按服务家族前缀归属，不把服务名钉死成单一字面量。类别取交付策略的
# 并集（greeter、user），四元组复用 session_key 与诊断通道保持同一事实源。
session_ready()
{
    local key="$1" svc cls typ state want

    IFS='|' read -r svc cls typ state <<<"${key}"
    case "${svc}" in "${SESS_SVC}"*) ;; *) return 1 ;; esac
    [ "${typ}" = "${SESS_TYPE}" ] || return 1
    case " ${SESS_STATES} " in *" ${state} "*) ;; *) return 1 ;; esac
    for want in ${SESS_CLASSES}; do
        [ "${cls}" = "${want}" ] && return 0
    done
    return 1
}

login_session()
{
    local id

    for id in $(loginctl list-sessions --no-legend 2>/dev/null |
                    awk '{print $1}'); do
        session_ready "$(session_key "${id}")" || continue
        printf '%s\n' "${id}"
        return 0
    done
    return 1
}

unit_active()
{
    systemctl is-active --quiet "$1.service" 2>/dev/null
}

ready_once()
{
    unit_active "${SESS_SVC}" || return 1
    READY_ID="$(login_session)" || return 1
    [ -n "${READY_ID}" ]
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

# 诊断通道：每类证据独立取，取不到就跳过，绝不影响返回值。
diag_out()
{
    head -n "${DIAG_MAX}" 2>/dev/null |
        sed "s/^/AIRYMAX-DESKTOP-DIAG ${1} /"
}

diag_unit()
{
    systemctl show -p ActiveState -p SubState -p Result \
        -p NRestarts -p MainPID "${SESS_SVC}.service" 2>/dev/null |
        diag_out unit
}

diag_journal()
{
    journalctl -b -u "${SESS_SVC}.service" -n "${DIAG_MAX}" \
        -o cat --no-pager 2>/dev/null | diag_out journal
}

# 逐会话复用判定用的四元组，一眼能看出是被哪一项否掉的。
diag_session()
{
    local id

    for id in $(loginctl list-sessions --no-legend 2>/dev/null |
                    awk '{print $1}'); do
        printf 'session=%s %s\n' "${id}" "$(session_key "${id}")" |
            diag_out session
    done
}

diag_tail()
{
    [ -r "$2" ] || return 0
    tail -n "${DIAG_MAX}" -- "$2" 2>/dev/null | diag_out "file=$1"
}

diag_wchan()
{
    local pid path

    pid=$(systemctl show -p MainPID --value "${SESS_SVC}.service" \
        2>/dev/null)
    path="/proc/${pid}/wchan"
    [ -r "${path}" ] || return 0
    diag_out wchan <"${path}"
}

diagnose()
{
    diag_unit
    diag_session
    diag_journal
    diag_tail lightdm "${LDM_LOG_DIR}/lightdm.log"
    diag_tail greeter "${LDM_LOG_DIR}/seat0-greeter.log"
    diag_tail xorg "${LDM_LOG_DIR}/x-0.log"
    diag_wchan
}

main()
{
    boot_health || return 1
    if ! session_exec; then
        diagnose
        printf 'AIRYMAX-DESKTOP-FAIL reason=session path=%s\n' \
            "${UKUI_SESSION}"
        return 1
    fi
    if wait_ready; then
        printf 'AIRYMAX-DESKTOP-READY unit=%s class=%s type=%s\n' \
            "${SESS_SVC}" "$(session_field "${READY_ID}" Class)" "${SESS_TYPE}"
        return 0
    fi
    diagnose
    printf 'AIRYMAX-DESKTOP-FAIL unit=%s wait=%ss\n' \
        "${SESS_SVC}" "${READY_WAIT}"
    return 1
}

main "$@"
