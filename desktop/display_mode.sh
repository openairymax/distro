#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# display_mode.sh — AirymaxOS 会话显示分辨率自适应
#
# 部署：airymaxos-release 包安装到 /usr/lib/airymaxos/desktop/。
# 调用面：
#   /etc/X11/xinit/xinitrc.d/60-airymax-display.sh  会话早期收敛一轮
#   /etc/xdg/autostart/airymax-display.desktop      会话就绪后再次收敛
#   ci/run-smoke.sh 的 T10、RPM %check               只读 --check / --plan
#
# 为什么是「有界收敛」而不是「一次性写入」：Xsession 载入 xinitrc.d 时，
# 虚拟输出的 connected 拓扑常常尚未建立（xrandr 只有 Screen 行），此刻
# 写入无从落地；而会话就绪后 ukui 的 settings-daemon 会按自身记录再设一次
# 模式，把早期结果覆盖成面板最大值。两种时序在验收基线上都出现过，因此
# 入口必须在预算内反复「读取拓扑 → 纠正 → 复核」，收敛即返回，预算耗尽
# 才判失败，并把最后一次偏差记进 journal（--settle）。
#
# 策略（决策 2026-10-27）：逐个 connected 输出独立决策——
#   1. 首选模式（xrandr 标记 +）在上限内则采用；
#   2. 否则在常用分辨率阶梯中取该输出确实广播的最大一项；
#   3. 阶梯全不匹配时回退首选模式，不做无法落地的切换。
# 上限与阶梯是策略的唯一事实来源（SSoT），单测与验收脚本只读本文件。
#
# 入口：
#   无参数     应用策略一次，仅对当前模式与策略不符的输出执行 xrandr
#   --settle [秒]  在预算内反复应用并复核，收敛返回 0，预算耗尽返回 1
#   --check    校验所有 connected 输出已处于策略模式；不符或拓扑为空即失败
#   --plan     从 stdin 读取 xrandr --query 文本，输出 "<输出> <当前> <策略>"
#
# 本文件由 POSIX sh 解释执行，禁止 bash 专有语法。
# ===========================================================================

set -u

CAP_W=1920
CAP_H=1200
LADDER="1920x1080 1600x900 1440x900 1366x768 1280x720 1024x768"
BUDGET=15

# xrandr --query 的拓扑按输出分段：输出行顶格，模式行缩进。
# 模式行可能带 i 后缀（隔行）与 * / + 标记，数值比较前先截断。
POLICY='
function fits(m,   a) {
    split(m, a, "x")
    return (a[1] + 0) <= CAP_W && (a[2] + 0) <= CAP_H
}

function pick(   i, j, nl, L) {
    if (pref != "" && fits(pref))
        return pref
    nl = split(LADDER, L, " ")
    for (i = 1; i <= nl; i++)
        for (j = 1; j <= nm; j++)
            if (modes[j] == L[i])
                return L[i]
    return pref
}

function emit(   want) {
    if (!conn)
        return
    want = pick()
    if (want == "")
        want = cur
    if (want == "")
        return
    printf "%s %s %s\n", out, (cur == "" ? "none" : cur), want
}

/^Screen/ { next }

/^[^ \t]/ {
    emit()
    out = $1
    conn = ($2 == "connected")
    cur = ""
    pref = ""
    nm = 0
    delete modes
    next
}

conn && $1 ~ /^[0-9]+x[0-9]+[a-zA-Z]*$/ {
    modes[++nm] = $1
    if ($0 ~ /\*/)
        cur = $1
    if ($0 ~ /\+/)
        pref = $1
}

END { emit() }
'

plan() {
    awk -v CAP_W="$CAP_W" -v CAP_H="$CAP_H" -v LADDER="$LADDER" "$POLICY"
}

log() {
    command -v logger >/dev/null 2>&1 &&
        logger -t airymaxos-display -- "$*" 2>/dev/null
    return 0
}

die() {
    printf 'display_mode: %s\n' "$1" >&2
    exit 1
}

read_topo() {
    command -v xrandr >/dev/null 2>&1 || die "缺少 xrandr"
    topo=$(xrandr --query) || die "xrandr --query 失败"
    plan_out=$(printf '%s\n' "$topo" | plan)
}

# 逐行比对拓扑与策略：rows 是 connected 输出数，bad 记录偏差。
# 偏差行同时用于纠正（apply 与 settle 共用同一判定口径，避免两处漂移）。
scan() {
    rows=0
    bad=""
    while IFS=' ' read -r out cur want; do
        [ -n "$out" ] || continue
        rows=$((rows + 1))
        [ "$cur" = "$want" ] && continue
        bad="${bad} ${out}:${cur}->${want}"
    done <<EOF
${plan_out}
EOF
}

apply() {
    read_topo
    scan
    rc=0
    set -- ${bad}
    for row in "$@"; do
        out=${row%%:*}
        want=${row#*->}
        xrandr --output "$out" --mode "$want" >/dev/null 2>&1 || {
            log "apply ${out} -> ${want} failed"
            rc=1
        }
    done
    log "apply${bad:- all outputs on policy} rc=${rc}"
    return "$rc"
}

check() {
    read_topo
    scan
    [ "$rows" -gt 0 ] || die "无 connected 输出"
    [ -z "$bad" ] || die "分辨率未达策略:${bad}"
}

settle() {
    budget=${1:-$BUDGET}
    waited=0
    while :; do
        read_topo
        scan
        if [ "$rows" -gt 0 ] && [ -z "$bad" ]; then
            [ "$waited" -gt 0 ] && log "settled after ${waited}s"
            return 0
        fi
        if [ "$waited" -ge "$budget" ]; then
            log "unsettled after ${budget}s:${bad:- no connected output}"
            printf 'display_mode: 收敛失败:%s\n' \
                "${bad:- 无 connected 输出}" >&2
            return 1
        fi
        set -- ${bad}
        for row in "$@"; do
            out=${row%%:*}
            want=${row#*->}
            xrandr --output "$out" --mode "$want" >/dev/null 2>&1 || :
        done
        sleep 1
        waited=$((waited + 1))
    done
}

case "${1:-}" in
'') apply ;;
--settle) settle "${2:-$BUDGET}" ;;
--check) check ;;
--plan) plan ;;
*) die "未知参数: $1（可用: --settle --check --plan）" ;;
esac
