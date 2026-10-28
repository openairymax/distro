#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# rt_budget.sh — AirymaxOS 实时调度带宽预算分配
#
# 部署：airymaxos-release 包安装到 /usr/lib/airymaxos/desktop/，由同包的
# airymax-rt-budget.service 在 rtkit-daemon 与显示管理器之前执行一次。
#
# 问题：内核启用 CONFIG_RT_GROUP_SCHED 后，RT 带宽按 cgroup 层级记账，
# 新建 cgroup 的 cpu.rt_runtime_us 默认为 0。0 不是「不限」而是「禁止」：
# 该组内的 sched_setscheduler(SCHED_RR/SCHED_FIFO) 一律返回 EPERM。
# rtkit-daemon 因此每次启动都报
#   Failed to make ourselves RT: Operation not permitted
# 并退化为非实时运行；音频线程拿不到 SCHED_RR，桌面在高负载下出现
# 爆音与卡顿，而所有上层配置看起来都是对的。
#
# 为什么是「分层切分」而不是「给某处写满」：带宽是层级预算，子组之和
# 不得超过父组，写入超额值直接 EINVAL。把总预算全给 system.slice，则
# user.slice 永远是 0，SSH 会话与桌面会话里任何 RT 请求都失败（真机 B50
# 实测：system.slice 写满 950000 后，user.slice 写任何值都 EINVAL）。
#
# 策略：总预算取自 /proc/sys/kernel/sched_rt_runtime_us，按固定份数均分
# 给一级 slice，剩余份额留给未列出的组与内核自身。只写「已存在且可写」
# 的 cpu.rt_runtime_us，缺失的组静默跳过——slice 可能在本次启动中尚未
# 建立，或 cgroup v1 未在该层级启用 cpu 控制器；两种情况都由 systemd
# 回落到最近的可记账祖先，不是故障。
#
# 本文件由 POSIX sh 解释执行，禁止 bash 专有语法。
# ===========================================================================

set -u

PROC=/proc/sys/kernel/sched_rt_runtime_us
CGROOT=/sys/fs/cgroup
SLICES="system.slice user.slice airymax.slice airymax-desktop.slice"
DIVISOR=5
MARK=AIRYMAX-RT-BUDGET

# 单行可观测标记：不写 journal 之外的任何状态，验收侧只认这一行。
emit() {
    printf '%s status=%s total=%s share=%s applied=%s\n' \
        "$MARK" "$1" "$2" "$3" "$4"
}

# 总预算：-1 表示内核不限制，此时无从切分，按 0 处理让上层记录原因。
# 这里不能用 read 内建：dash 从 procfs 读取会读到不完整的值并返回非零，
# 得到的是被截断的预算而不是真值。
read_total() {
    val=$(cat "$PROC" 2>/dev/null || printf '0\n')
    case $val in
    '' | *[!0-9]*) val=0 ;;
    esac
    printf '%s\n' "$val"
}

# cgroup v1 的 cpu 控制器可能挂在任意已命名层级下，以 cpu.rt_runtime_us
# 顶层文件反查实际挂载点，而不是假定 /sys/fs/cgroup/cpu。
cpu_root() {
    for f in "$CGROOT"/*/cpu.rt_runtime_us; do
        [ -f "$f" ] || continue
        printf '%s\n' "${f%/*}"
        return 0
    done
    return 1
}

write_one() {
    [ -w "$1" ] || return 1
    printf '%s\n' "$2" 2>/dev/null > "$1"
}

# 逐个 slice 写入同一份额；返回成功写入的个数。
fill_all() {
    applied=0
    for name in $SLICES; do
        write_one "$1/$name/cpu.rt_runtime_us" "$2" &&
            applied=$((applied + 1))
    done
    printf '%s\n' "$applied"
}

main() {
    total=$(read_total)
    share=$((total / DIVISOR))
    if [ "$total" -le 0 ]; then
        emit disabled "$total" 0 0
        return 0
    fi
    root=$(cpu_root) || {
        emit no-cgroup-v1 "$total" "$share" 0
        return 0
    }
    applied=$(fill_all "$root" "$share")
    emit ok "$total" "$share" "$applied"
}

main "$@"
