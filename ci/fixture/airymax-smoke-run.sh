#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# airymax-smoke-run.sh — 验收 ISO 的会话内冒烟 runner
#
# 由 /etc/xdg/autostart/airymax-smoke.desktop 在 UKUI 会话建立后拉起，
# 调用与 CI 同源的 run-smoke.sh，并把 TAP 原子写入
# /var/log/airymax/smoke.tap，供 airymax-smoke-report.service 判定并
# 转发到串口。
#
# 退出码：0 TAP 已写入；1 无法写入或 runner 异常终止。
# ===========================================================================
set -uo pipefail

readonly CI_DIR=/usr/lib/airymaxos/ci
readonly LOG_DIR=/var/log/airymax
readonly TAP="${LOG_DIR}/smoke.tap"
# 会话内 runner 的硬上限。run-smoke.sh 的每个探针各自有界，但项数多，
# 逐项等待会叠加：aarch64 TCG 上仅 T1（会话建立）一项就约 185s。180s 的
# 全局上限会在合法等待中杀掉 runner，TAP 只剩 T1 与 Bail out! smoke
# timeout，报告侧据此判负——这是观测器的缺陷，不是产品缺陷。
# 600s 是逐项界之和的余量；它与 airymax-smoke-report.sh 的轮询上限
# （660s）和单元的 TimeoutStartSec（720s）成对改动，顺序为
# LIMIT < WAIT < unit，任一处放宽都要同步后面两处。
readonly LIMIT="${AIRYMAX_SMOKE_LIMIT:-600}"

write_tap()
{
    local tmp rc
    tmp="$(mktemp "${TAP}.XXXXXX")" || return 1
    timeout "${LIMIT}" "${CI_DIR}/run-smoke.sh" "$1" >"${tmp}" 2>&1
    rc=$?
    case "${rc}" in
    0 | 1) ;;
    124) printf 'Bail out! smoke timeout after %ss\n' "${LIMIT}" >>"${tmp}" ;;
    *) printf 'Bail out! smoke runner rc=%s\n' "${rc}" >>"${tmp}" ;;
    esac
    mv -f "${tmp}" "${TAP}"
}

main()
{
    local target
    target="$(hostname 2>/dev/null || printf 'airymaxos')"
    install -d -m 0755 "${LOG_DIR}" || exit 1
    write_tap "${target}"
}

main "$@"
