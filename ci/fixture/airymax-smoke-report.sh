#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airymax-smoke-report.sh — 验收 ISO 的串口结果上报
#
# 等待会话内 runner 写出 /var/log/airymax/smoke.tap，按 TAP 14 判定：
#   计划必须为 1..5；不得出现 not ok / Bail out! / SKIP；ok 行必须为 5；
#   summary 的 fail 必须为 0。
# 探测工具由产品镜像自身提供，runner 不产生 SKIP；出现 SKIP 说明跑的不是
# 本版 runner，按失败计，避免旧语义把缺失的探测放行。
# 通过打印 AIRYMAX-SMOKE-PASS；失败打印 AIRYMAX-SMOKE-FAIL。
#
# 结论标记之外，TAP 原文逐行以 AIRYMAX-TAP| 前缀转发到串口，供宿主机从
# 串口日志还原 smoke.tap 归档（验收发行方案 §9.3）。转发先于结论标记，
# 保证 install-test.sh 命中 --boot-marker 时全文已经落盘。
#
# AIRYMAX-BOOT-CHAIN| 一并转发 `systemd-analyze critical-chain` 原文，
# 供宿主侧对账 NFR-P-005 的服务级门限。本单元 After=lightdm.service，
# 关键链在此时已经完整；产品就绪单元在验收 ISO 被 mask，因此观测点只留
# 这一处，避免两个判定者各说一套。
#
# 失败单元记账同样落在本观测点：产品就绪单元被 mask 后，DEGRADED 不会由
# 产品路径上报，只能由这里给出。记账与取证来自 boot_state.sh，与产品探针
# 共用同一实现，避免两个观测点对「什么算失败」各持一套语义。
#
# 退出码：0 通过；1 失败（超时、单元失败或 TAP 判负）。
# ===========================================================================
set -uo pipefail

BOOT_STATE="${AIRYMAX_BOOT_STATE:-/usr/lib/airymaxos/desktop/boot_state.sh}"
if [ ! -r "${BOOT_STATE}" ]; then
    printf 'AIRYMAX-SMOKE-FAIL reason=boot-state path=%s\n' "${BOOT_STATE}"
    exit 1
fi
# shellcheck source=../../desktop/boot_state.sh
. "${BOOT_STATE}"

readonly TAP="${AIRYMAX_SMOKE_TAP:-/var/log/airymax/smoke.tap}"
readonly WAIT="${AIRYMAX_SMOKE_WAIT:-240}"
readonly STEP=2
readonly TAP_TOKEN='AIRYMAX-TAP|'
readonly CHAIN_MAX="${AIRYMAX_CHAIN_LINES:-24}"
readonly CHAIN_TOKEN='AIRYMAX-BOOT-CHAIN|'

wait_tap()
{
    local waited=0
    while :; do
        [ -s "${TAP}" ] && return 0
        [ "${waited}" -ge "${WAIT}" ] && return 1
        sleep "${STEP}"
        waited=$((waited + STEP))
    done
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
    grep -q '# SKIP' "${TAP}" && return 1
    ! grep -qE '^# summary: .*fail=[1-9]' "${TAP}"
}

emit_tap()
{
    local line
    while IFS= read -r line; do
        printf '%s%s\n' "${TAP_TOKEN}" "${line}"
    done <"${TAP}"
}

# 关键链只在会话建立后才有意义：图形目标此时已达成，systemd 记下的
# 单元时刻与自身耗时才是完整的。超时路径照转一次，让宿主拿到失败现场。
boot_chain()
{
    systemd-analyze critical-chain --no-pager 2>/dev/null |
        head -n "${CHAIN_MAX}" |
        sed "s/^/${CHAIN_TOKEN}/"
}

conclude()
{
    printf 'AIRYMAX-SMOKE-FAIL reason=%s tap=%s\n' "$1" "${TAP}"
    return 1
}

main()
{
    if ! wait_tap; then
        boot_chain
        boot_health
        conclude timeout
        return 1
    fi
    emit_tap
    boot_chain
    boot_health || { conclude degraded; return 1; }
    verdict || { conclude tap; return 1; }
    printf 'AIRYMAX-SMOKE-PASS tap=%s\n' "${TAP}"
    return 0
}

main "$@"
