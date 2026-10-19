#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airymax-smoke-report.sh — 验收 ISO 的串口结果上报
#
# 等待会话内 runner 写出 /var/log/airymax/smoke.tap，按 TAP 14 判定：
#   计划必须为 1..5；不得出现 not ok / Bail out!；ok 行必须为 5；
#   T5 不得 SKIP；summary 的 fail 必须为 0。
# 通过打印 AIRYMAX-SMOKE-PASS；失败打印 AIRYMAX-SMOKE-FAIL。
#
# 退出码：0 通过；1 失败或超时。
# ===========================================================================
set -uo pipefail

readonly TAP=/var/log/airymax/smoke.tap
readonly WAIT=240
readonly STEP=2

wait_tap()
{
    local waited=0
    while [ "${waited}" -lt "${WAIT}" ]; do
        [ -s "${TAP}" ] && return 0
        sleep "${STEP}"
        waited=$((waited + STEP))
    done
    return 1
}

count_ok()
{
    grep -cE '^ok [1-5] - ' "${TAP}" 2>/dev/null || :
}

verdict()
{
    grep -qE '^(not ok|Bail out!)' "${TAP}" && return 1
    grep -qxF '1..5' "${TAP}" || return 1
    [ "$(count_ok)" -eq 5 ] || return 1
    grep -qE '^ok 5 - .*# SKIP' "${TAP}" && return 1
    ! grep -qE '^# summary: .*fail=[1-9]' "${TAP}"
}

main()
{
    if ! wait_tap; then
        printf 'AIRYMAX-SMOKE-FAIL reason=timeout tap=%s\n' "${TAP}"
        return 1
    fi
    if verdict; then
        printf 'AIRYMAX-SMOKE-PASS tap=%s\n' "${TAP}"
        return 0
    fi
    printf 'AIRYMAX-SMOKE-FAIL reason=tap tap=%s\n' "${TAP}"
    return 1
}

main "$@"
