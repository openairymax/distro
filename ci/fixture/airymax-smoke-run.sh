#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
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
readonly LIMIT=180

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
