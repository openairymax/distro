#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# net_ready.sh — 首启联机就绪探针（串口标记 + journal）
#
# 为什么要有它：net_doctor 回答「为什么没网」，只在开机后判一次、结论落
# journal；桌面就绪探针回答「桌面起没起」。装机验收关心的第三个问题——
# 「这台机器装完到底能不能联网」——此前没有产品侧的可观测结论：验收剖面
# 只能由 CI 的 T31 复述一遍，产品镜像上没有任何一行能证明联机成立。
#
# 证据来源只有 airy-observe：地址、来源、网关、DNS 四元组与验收 T31、桌面
# 状态面板取自同一段输出，本脚本不重复实现字段解析，只决定「等到什么时候
# 算就绪」——有界轮询加一行标记。判「为什么没就绪」仍是 net_doctor 的职责，
# 两者不互相替代：一个是快照归因，一个是就绪等待。
#
# 网关 ICMP 不进判据：CI 验收机是 slirp 用户态网络，ICMP 不回包是常态，
# 把 ping 不通判成断网会让能上网的机器报红。可达性归真机门禁
# ci/gates/net-online.sh --live。
#
# 标记（结论行只出现一次）：
#   AIRYMAX-NET-WAIT elapsed=<秒>        等待心跳，每 AIRYMAX_NET_BEAT 秒一行
#   AIRYMAX-NET-READY ipv4=... gw=... dns=...
#   AIRYMAX-NET-OFFLINE ipv4=... src=... gw=... dns=...
#
# 无论结论如何都以 0 退出：本单元是观测，不是门禁。退出非零会进
# systemctl --failed，被 boot_health 记成「系统有单元失败」，断网就从
# 「功能不好用」升格成「开机不健康」，判据失真。lib 缺失是打包缺陷，那时
# 才以非零退出。
#
# 部署：airymaxos-release 包安装到 /usr/lib/airymaxos/desktop/，由
# airymax-net-ready.service（WantedBy=graphical.target）拉起。
# 用法：net_ready.sh
# 环境：AIRYMAX_NET_WAIT（默认 60 秒）、AIRYMAX_NET_POLL（默认 2 秒）、
#       AIRYMAX_NET_BEAT（默认 6 秒）、AIRYMAX_OBSERVE（默认 PATH 上的
#       airy-observe，测试用替身）。
# ===========================================================================
set -uo pipefail

WAIT="${AIRYMAX_NET_WAIT:-60}"
POLL="${AIRYMAX_NET_POLL:-2}"
BEAT="${AIRYMAX_NET_BEAT:-6}"
OBS="${AIRYMAX_OBSERVE:-airy-observe}"
BOOT_STATE="${AIRYMAX_BOOT_STATE:-${BASH_SOURCE[0]%/*}/boot_state.sh}"

if [ ! -r "${BOOT_STATE}" ]; then
    printf 'AIRYMAX-NET-FAIL reason=no-boot-state path=%s\n' "${BOOT_STATE}" >&2
    exit 1
fi
# shellcheck source=./boot_state.sh
. "${BOOT_STATE}"

V4='([0-9]{1,3}\.){3}[0-9]{1,3}'

# 取 net 段单字段值：airy-observe 的一行是 `AIRYMAX-OBSERVE net.gw=10.0.2.2`。
field()
{
    sed -n "s/^[A-Z][A-Z-]* $2=//p" <<<"$1" | head -n 1
}

# 联机四元组：动态地址、至少一个全局 IPv4、点分网关、非空 DNS。
ready()
{
    local ipv4 src gw dns

    ipv4=$(field "$1" net.ipv4)
    src=$(field "$1" net.src)
    gw=$(field "$1" net.gw)
    dns=$(field "$1" net.dns)
    [ "${src}" = dhcp ] || return 1
    grep -Eq "${V4}" <<<"${ipv4}" || return 1
    grep -Eq "^${V4}$" <<<"${gw}" || return 1
    grep -Eq "${V4}" <<<"${dns}" || return 1
}

verdict()
{
    say "AIRYMAX-NET-%s ipv4=%s src=%s gw=%s dns=%s" "$1" \
        "$(field "$2" net.ipv4)" "$(field "$2" net.src)" \
        "$(field "$2" net.gw)" "$(field "$2" net.dns)"
}

main()
{
    local waited=0 next="${BEAT}" out=

    say 'AIRYMAX-NET-WAIT elapsed=0s'
    while :; do
        out=$("${OBS}" --section net 2>/dev/null) || out=
        if ready "${out}"; then
            verdict READY "${out}"
            return 0
        fi
        if [ "${waited}" -ge "${WAIT}" ]; then
            verdict OFFLINE "${out}"
            return 0
        fi
        if [ "${waited}" -ge "${next}" ]; then
            say 'AIRYMAX-NET-WAIT elapsed=%ss' "${waited}"
            next=$((next + BEAT))
        fi
        sleep "${POLL}"
        waited=$((waited + POLL))
    done
}

main
exit 0
