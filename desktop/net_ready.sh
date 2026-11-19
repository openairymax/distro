#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
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
# 算就绪」。判「为什么没就绪」仍是 net_doctor 的职责，两者不互相替代：
# 一个是快照归因，一个是就绪等待。
#
# 等待分两段，因为 Wi-Fi 关联与认证的耗时不受本机控制：285H 实机首启时
# 快段在 54 秒仍未见租约，随后 NetworkManager 才拿到 DHCP，而旧实现只判
# 一次、判完即退，假阴性再也无法纠正。快段（AIRYMAX_NET_WAIT，默认 60 秒）
# 覆盖有线与正常的无线路径；快段过期只落一行边界标记并附带当时的四元组，
# 转入慢段（AIRYMAX_NET_LATE，默认 600 秒）继续观察，慢段内就绪同样产出
# READY。两段都只是观测，不挂 target 的等待面。
#
# 网关 ICMP 不进判据：CI 验收机是 slirp 用户态网络，ICMP 不回包是常态，
# 把 ping 不通判成断网会让能上网的机器报红。可达性归真机门禁
# ci/gates/net-online.sh --live。
#
# 标记（结论行只出现一次）：
#   AIRYMAX-NET-WAIT elapsed=<秒>        快段心跳，每 AIRYMAX_NET_BEAT 秒一行
#   AIRYMAX-NET-LATE ipv4=... gw=... dns=...  快段过期，转入慢段并附四元组
#   AIRYMAX-NET-SLOW elapsed=<秒>        慢段心跳，每 AIRYMAX_NET_LATE_BEAT 秒一行
#   AIRYMAX-NET-READY ipv4=... gw=... dns=...
#   AIRYMAX-NET-OFFLINE ipv4=... src=... gw=... dns=...
#
# 慢段心跳的 elapsed 自转入慢段起算，与快段同名但起点不同；两段之间由
# LATE 行分隔，journal 按顺序即可还原整条时间线，卡在哪一段一眼可见。
#
# 无论结论如何都以 0 退出：本单元是观测，不是门禁。退出非零会进
# systemctl --failed，被 boot_health 记成「系统有单元失败」，断网就从
# 「功能不好用」升格成「开机不健康」，判据失真。lib 缺失是打包缺陷，那时
# 才以非零退出。
#
# 部署：airymaxos-release 包安装到 /usr/lib/airymaxos/desktop/，由
# airymax-net-ready.service（WantedBy=graphical.target）拉起。
# 用法：net_ready.sh
# 环境：AIRYMAX_NET_WAIT（快段秒数，默认 60）、AIRYMAX_NET_LATE（慢段秒数，
#       默认 600）、AIRYMAX_NET_POLL（快段采样间隔，默认 2 秒）、
#       AIRYMAX_NET_SLOW（慢段采样间隔，默认 10 秒）、AIRYMAX_NET_BEAT（快段
#       心跳间隔，默认 6 秒）、AIRYMAX_NET_LATE_BEAT（慢段心跳间隔，默认
#       60 秒）、AIRYMAX_OBSERVE（默认 PATH 上的 airy-observe，测试用替身）。
# ===========================================================================
set -uo pipefail

WAIT="${AIRYMAX_NET_WAIT:-60}"
LATE="${AIRYMAX_NET_LATE:-600}"
POLL="${AIRYMAX_NET_POLL:-2}"
SLOW="${AIRYMAX_NET_SLOW:-10}"
BEAT="${AIRYMAX_NET_BEAT:-6}"
LBEAT="${AIRYMAX_NET_LATE_BEAT:-60}"
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

# 取一次 net 段观测。工具缺失或执行失败都按「尚未就绪」处理：等待期间
# 观察工具短暂不可用不该结束等待，归因由 net_doctor 在结论后负责。
# 失败时连输出一并丢弃——非零退出时的半截输出不能当证据。
observe()
{
    local out=

    out=$("${OBS}" --section net 2>/dev/null) || out=
    printf '%s' "${out}"
}

# 快段：有线与正常无线在这里就绪，默认 60 秒。过期不算结论，只落一行
# 边界标记并交给慢段——结论行在两段里只出现一次。
fast_wait()
{
    local waited=0 next="${BEAT}" out=

    say 'AIRYMAX-NET-WAIT elapsed=0s'
    while :; do
        out=$(observe)
        if ready "${out}"; then
            verdict READY "${out}"
            return 0
        fi
        if [ "${waited}" -ge "${WAIT}" ]; then
            verdict LATE "${out}"
            return 1
        fi
        if [ "${waited}" -ge "${next}" ]; then
            say 'AIRYMAX-NET-WAIT elapsed=%ss' "${waited}"
            next=$((next + BEAT))
        fi
        sleep "${POLL}"
        waited=$((waited + POLL))
    done
}

# 慢段：无线关联/认证慢于快段时把假阴性纠正回来。采样更稀、心跳更长，
# 因为这一段通常什么都不发生；就绪即 READY，走完仍不满足才 OFFLINE。
slow_wait()
{
    local spent=0 next="${LBEAT}" out=

    while [ "${spent}" -lt "${LATE}" ]; do
        sleep "${SLOW}"
        spent=$((spent + SLOW))
        out=$(observe)
        if ready "${out}"; then
            verdict READY "${out}"
            return 0
        fi
        if [ "${spent}" -ge "${next}" ]; then
            say 'AIRYMAX-NET-SLOW elapsed=%ss' "${spent}"
            next=$((next + LBEAT))
        fi
    done
    verdict OFFLINE "$(observe)"
}

main()
{
    fast_wait || slow_wait
}

main
exit 0
