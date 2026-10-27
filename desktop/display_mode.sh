#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# display_mode.sh — AirymaxOS 会话显示分辨率自适应
#
# 部署：airymaxos-release 包安装到 /usr/lib/airymaxos/desktop/。
# 调用：/etc/X11/xinit/xinitrc.d/60-airymax-display.sh 在会话启动时执行默认
#       入口；ci/run-smoke.sh 的 T10 与 RPM %check 使用 --check / --plan。
#
# 策略（决策 2026-10-27）：逐个 connected 输出独立决策——
#   1. 首选模式（xrandr 标记 +）在上限内则采用；
#   2. 否则在常用分辨率阶梯中取该输出确实广播的最大一项；
#   3. 阶梯全不匹配时回退首选模式，不做无法落地的切换。
# 上限与阶梯是策略的唯一事实来源（SSoT），单测与验收脚本只读本文件。
#
# 入口：
#   无参数    应用策略，仅对当前模式与策略不符的输出执行 xrandr --output
#   --check   校验所有 connected 输出已处于策略模式；不符或拓扑为空即失败
#   --plan    从 stdin 读取 xrandr --query 文本，输出 "<输出> <当前> <策略>"
#
# 本文件由 POSIX sh 解释执行，禁止 bash 专有语法。
# ===========================================================================

set -u

CAP_W=1920
CAP_H=1200
LADDER="1920x1080 1600x900 1440x900 1366x768 1280x720 1024x768"

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

die() {
    printf 'display_mode: %s\n' "$1" >&2
    exit 1
}

read_topo() {
    command -v xrandr >/dev/null 2>&1 || die "缺少 xrandr"
    topo=$(xrandr --query) || die "xrandr --query 失败"
    plan_out=$(printf '%s\n' "$topo" | plan)
}

apply() {
    read_topo
    rc=0
    while IFS=' ' read -r out cur want; do
        [ -n "$out" ] || continue
        [ "$cur" = "$want" ] && continue
        xrandr --output "$out" --mode "$want" || rc=1
    done <<EOF
${plan_out}
EOF
    return "$rc"
}

check() {
    read_topo
    rows=0
    bad=""
    while IFS=' ' read -r out cur want; do
        [ -n "$out" ] || continue
        rows=$((rows + 1))
        [ "$cur" = "$want" ] || bad="${bad} ${out}:${cur}->${want}"
    done <<EOF
${plan_out}
EOF
    [ "$rows" -gt 0 ] || die "无 connected 输出"
    [ -z "$bad" ] || die "分辨率未达策略:${bad}"
}

case "${1:-}" in
'') apply ;;
--check) check ;;
--plan) plan ;;
*) die "未知参数: $1（可用: --check --plan）" ;;
esac
