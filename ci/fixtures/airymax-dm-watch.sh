#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# airymax-dm-watch.sh — 登录管理器地址空间快照（仅验收 ISO）
#
# 症状：aarch64 的 lightdm 主进程起来后约 1.1 秒必崩，串口只有
# print-fatal-signals 的寄存器转储——pc/lr 是库内偏移，没有模块名。
# systemd-coredump 编译时未带 elfutils，core 解析不出来（同一行
# "elfutils disabled" 也计入 T23 的 base 误差）。没有模块名就只剩猜，
# 而这条崩溃是发布判据上的硬失败。
#
# 做法：lightdm 每崩一次 systemd 就重启一次，存活窗口一秒以上，足够取一次
# /proc/<pid>/maps。把每个实例的可执行段连同 PID 落到串口，转储里的 PID
# 就能对上它自己的地址空间——ASLR 每次重启都变，只有同实例的 maps 才解释
# 得了同实例的 pc。取满三个实例即收手：一次崩溃就够定位，多取只是刷串口。
#
# 只在会话管理器缺席或反复重启时有输出：正常路径打一行 armed 即静默。
# 收尾把 lightdm 自己的日志整份带上——它的失败步骤常常只写文件不写 stderr。
# ===========================================================================

ink=/dev/ttyS0
[ "$(uname -m)" = aarch64 ] && ink=/dev/ttyAMA0

printf 'AIRYMAX-DM-WATCH armed ink=%s\n' "${ink}" >>"${ink}" 2>/dev/null

seen=' '
got=0
hub=$(( $(cut -d. -f1 /proc/uptime 2>/dev/null || printf 0) + 180 ))
while [ "${got}" -lt 3 ] && [ "$(cut -d. -f1 /proc/uptime)" -lt "${hub}" ]; do
    for proc in /proc/[0-9]*; do
        [ "$(cat "${proc}/comm" 2>/dev/null)" = lightdm ] || continue
        pid=${proc#/proc/}
        case "${seen}" in
        *" ${pid} "*) continue ;;
        esac
        seen="${seen}${pid} "
        got=$(( got + 1 ))
        printf 'AIRYMAX-DM-MAP pid=%s begin\n' "${pid}" >>"${ink}"
        awk '$2 ~ /x/ && $6 ~ /^\// { print "AIRYMAX-DM-SEG " $1 " " $6 }' \
            "${proc}/maps" >>"${ink}" 2>/dev/null
        printf 'AIRYMAX-DM-MAP pid=%s end\n' "${pid}" >>"${ink}"
    done
    sleep 0.2 2>/dev/null || sleep 1
done

if [ -r /var/log/lightdm/lightdm.log ]; then
    sed 's/^/AIRYMAX-DM-LOG /' /var/log/lightdm/lightdm.log >>"${ink}" 2>/dev/null
fi

printf 'AIRYMAX-DM-WATCH done seen=%s\n' "$(printf '%s' "${seen}" | wc -w)" \
    >>"${ink}" 2>/dev/null
exit 0
