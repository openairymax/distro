#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# rtc-sync.sh — 装机期 RTC 写入的限时与打点（被 kickstart 嵌入）
#
# anaconda 曾在「update rtc with system clock」一步长时间停住，串口上没
# 有任何输出：看不出是 RTC 设备忙、hwclock 在等锁，还是 ioctl 卡在硬件
# 上。本文件把这一步收成唯一实现，三条要求同时满足：
#
#   * 不在关键路径上：写入限时（默认 60 秒），超时只告警不判负。时钟没写
#     进 RTC 的后果是首启时间偏，不是装不上系统；把它当致命错误，会让一
#     台本来能用的机器装机失败。
#   * 停在哪儿看得见：BEGIN/END 成对打印，END 行带毫秒数。卡住时串口最后
#     一行就是 AIRYMAX-RTC-BEGIN，不必复现就能判断停在这一步。
#   * 慢有归因：AIRY_RTC_TRACE 不为 0 且装了 strace 时，用 -T 记录时钟调用
#     与 ioctl 的耗时，把最慢的三条摊成 AIRYMAX-RTC-TRACE 行——是
#     clock_settime 慢还是 RTC_SET_TIME 的 ioctl 慢，决定后续往哪查。
#
# 标记形状固定，解析只认这个形状（ci/gates/rtc-probe.sh 按它判定）：
#   AIRYMAX-RTC-BEGIN t=<epoch>
#   AIRYMAX-RTC-END   ms=<毫秒>
#   AIRYMAX-RTC-OK    ms=<毫秒>
#   AIRYMAX-RTC-SLOW  ms=<毫秒> limit=<毫秒> [reason=timeout]
#   AIRYMAX-RTC-SKIP  reason=<no-device|no-tool|write-failed> [rc=<n>]
#   AIRYMAX-RTC-DRIFT sec=<有符号秒>
#   AIRYMAX-RTC-TRACE call=<系统调用> ms=<毫秒>
#
# 调用约定：只定义函数，无顶层副作用；被 set -eu 的脚本段 source。
#   airy_rtc_sync  写入 RTC 并打点，恒返回 0
#   airy_rtc_trace 解析 strace -T 输出，打印最慢三条
# ===========================================================================

# airy_ms — 墙钟毫秒。没有 %N（busybox 或旧 coreutils）时退到秒级精度：
# 判超限够用，只是 END 行的分辨率变粗，不会退回「无打点」。
airy_ms()
{
    local ns

    ns=$(date +%s%N 2>/dev/null) || ns=
    case ${ns} in
    ''|*[!0-9]*) printf '%s' "$(($(date +%s) * 1000))" ;;
    *) printf '%s' "$((ns / 1000000))" ;;
    esac
}

# airy_rtc_trace <file> — 取 strace -T 里最慢的三条系统调用。
#
# -T 把耗时写在行尾的 <0.000123> 里；syscall 名是行首第一段到左括号为止。
# 只报前三条：再往后都是毫秒级以下的噪声，列出来反而把真正的慢调用埋掉。
airy_rtc_trace()
{
    [ -r "$1" ] || return 0
    awk '
        match($0, /<[0-9]+\.[0-9]+>$/) {
            d = substr($0, RSTART + 1, RLENGTH - 2) + 0
            name = $1
            sub(/\(.*/, "", name)
            printf "%d %s\n", d * 1000 + 0.5, name
        }' "$1" | sort -rn | head -n 3 |
        while read -r ms name; do
            airy_out "AIRYMAX-RTC-TRACE call=${name} ms=${ms}"
        done
}

# airy_rtc_drift <rtc-dir> — 写回读：系统时钟减 RTC 自己报的秒数。
#
# hwclock 在部分固件上会「成功返回但没写进去」，只看退出码看不出来。读数
# 来自 /sys/class/rtc/rtc0/since_epoch，是内核向 RTC 取回的当前秒数。正值
# 表示 RTC 落后于系统时钟，负值表示它是超前；两种符号都与
# airy-observe --section rtc 的 rtc.drift 同向，现场对表不必自己换算。
airy_rtc_drift()
{
    local sec sys

    sec=$(tr -d '\n' <"$1/since_epoch" 2>/dev/null) || sec=
    case ${sec} in
    ''|*[!0-9]*) return 0 ;;
    esac
    sys=$(date +%s)
    airy_out "AIRYMAX-RTC-DRIFT sec=$((sys - sec))"
}

# airy_rtc_sync — 把系统时钟写进 RTC，无论成败都返回 0。
#
# 测试注入点：AIRY_RTC_DIR（RTC 目录）、AIRY_RTC_TOOL（默认 hwclock）、
# AIRY_RTC_LIMIT（秒）、AIRY_RTC_TRACE（0 关闭）、AIRY_RTC_TRACE_FILE。
airy_rtc_sync()
{
    local dir="${AIRY_RTC_DIR:-/sys/class/rtc/rtc0}"
    local limit="${AIRY_RTC_LIMIT:-60}"
    local lim_ms=$((limit * 1000))
    local tool="${AIRY_RTC_TOOL:-hwclock}"
    local trace="${AIRY_RTC_TRACE_FILE:-/root/airymax-rtc.trace}"
    local begin end ms rc=0

    airy_out "AIRYMAX-RTC-BEGIN t=$(date +%s)"
    begin=$(airy_ms)
    if [ ! -d "${dir}" ]; then
        airy_out "AIRYMAX-RTC-END ms=0"
        airy_out "AIRYMAX-RTC-SKIP reason=no-device"
        return 0
    fi
    if ! command -v "${tool}" >/dev/null 2>&1; then
        airy_out "AIRYMAX-RTC-END ms=0"
        airy_out "AIRYMAX-RTC-SKIP reason=no-tool"
        return 0
    fi
    rm -f "${trace}" >/dev/null 2>&1 || true
    if [ "${AIRY_RTC_TRACE:-auto}" != 0 ] &&
        command -v strace >/dev/null 2>&1; then
        timeout "${limit}" strace -f -T \
            -e trace=clock_settime,settimeofday,ioctl -o "${trace}" \
            "${tool}" --systohc --utc >/dev/null 2>&1 || rc=$?
    else
        timeout "${limit}" "${tool}" --systohc --utc >/dev/null 2>&1 || rc=$?
    fi
    end=$(airy_ms)
    ms=$((end - begin))
    [ "${ms}" -ge 0 ] || ms=0
    airy_out "AIRYMAX-RTC-END ms=${ms}"
    case ${rc} in
    0)
        if [ "${ms}" -gt "${lim_ms}" ]; then
            airy_out "AIRYMAX-RTC-SLOW ms=${ms} limit=${lim_ms}"
        else
            airy_out "AIRYMAX-RTC-OK ms=${ms}"
        fi
        airy_rtc_drift "${dir}"
        ;;
    124)
        airy_out "AIRYMAX-RTC-SLOW ms=${ms} limit=${lim_ms} reason=timeout"
        ;;
    *)
        airy_out "AIRYMAX-RTC-SKIP reason=write-failed rc=${rc}"
        ;;
    esac
    airy_rtc_trace "${trace}"
    return 0
}
