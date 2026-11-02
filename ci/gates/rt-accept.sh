#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# rt-accept.sh — 实时性验收门禁
#
# 职责：
#   1. 先跑 airy-rt-cap matrix，拿到整机等级。等级是门禁的前置条件：
#      none 时直接拒收，不做延迟测量——在没有实时带宽的机器上测出来的
#      数字没有判读意义；soft 时按软实时基线判定；
#   2. 用 cyclictest 测最大唤醒延迟，按等级选阈值；
#   3. 输出一行机读结论并以退出码收尾，供镜像 CI 与现场验收共用。
#
# 依赖（缺一即失败，不做降级）：
#   airy-rt-cap  —— airymaxos-system 提供，matrix 子命令输出 JSON；
#   cyclictest   —— rt-tests 提供，必须在真实内核上运行。
#   两者缺失时给出明确原因而不是静默跳过：验收门禁静默跳过等于没有门禁。
#
# 阈值可用 --hard-us / --soft-us 覆盖，缺省按 0.0.4 基线：
#   ready  完整实时：最大延迟 <= 100 us
#   soft   软实时：  最大延迟 <= 1000 us
# 超阈值即失败；测量本身出错（无输出、非数字）同样失败。
#
# 退出码：0 通过；1 不通过或环境不满足；2 用法错误。
# ===========================================================================
set -euo pipefail

CAP="${AIRY_RT_CAP:-airy-rt-cap}"
CYCLE="${CYCLIC:-cyclictest}"
DURATION=30
HARD_US=100
SOFT_US=1000
JSON=0

usage() {
    echo "usage: $0 [--json] [--duration SEC] [--hard-us N] [--soft-us N]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --json) JSON=1 ;;
        --duration) DURATION="${2:?}"; shift ;;
        --hard-us) HARD_US="${2:?}"; shift ;;
        --soft-us) SOFT_US="${2:?}"; shift ;;
        -h|--help) usage ;;
        *) usage ;;
    esac
    shift
done

fail() {
    echo "rt-accept: $*" >&2
    if [ "${JSON}" -eq 1 ]; then
        printf '{"verdict":"fail","reason":"%s"}\n' "$*"
    fi
    exit 1
}

command -v "${CAP}" >/dev/null 2>&1 ||
    fail "找不到 ${CAP}，先安装 airymaxos-system"
command -v "${CYCLE}" >/dev/null 2>&1 ||
    fail "找不到 ${CYCLE}，先安装 rt-tests"

matrix="$("${CAP}" matrix --json 2>&1)" ||
    fail "matrix 执行失败：${matrix}"
grade="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["grade"])' \
    <<<"${matrix}" 2>/dev/null)" || fail "matrix 输出不是合法 JSON"

case "${grade}" in
    ready) limit="${HARD_US}" ;;
    soft) limit="${SOFT_US}" ;;
    *) fail "等级 ${grade} 不接受，拒绝测量" ;;
esac

log="$(mktemp)"
trap 'rm -f "${log}"' EXIT
"${CYCLE}" -q -m -Sp90 -i200 -h400 -D "${DURATION}s" >"${log}" 2>&1 ||
    fail "cyclictest 执行失败"
max="$(sed -n 's/.*Max:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "${log}" |
    tail -n 1)"
[ -n "${max}" ] || fail "cyclictest 未输出最大延迟"

verdict=pass
[ "${max}" -le "${limit}" ] || verdict=fail

if [ "${JSON}" -eq 1 ]; then
    printf '{"verdict":"%s","grade":"%s","max_us":%s,"limit_us":%s}\n' \
        "${verdict}" "${grade}" "${max}" "${limit}"
else
    echo "rt-accept grade=${grade} max=${max}us limit=${limit}us" \
        "verdict=${verdict}"
fi

[ "${verdict}" = pass ]
