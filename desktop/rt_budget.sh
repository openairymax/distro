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
# 策略：总预算取自 /proc/sys/kernel/sched_rt_runtime_us，按固定份数均分
# 给一级 slice，剩余份额留给未列出的组与内核自身。
#
# 为什么必须自己建目录：systemd 在 cgroup v1 上按控制器按需建立单元
# cgroup。只设 Slice= 而未启用 cpu 控制器的单元，其 slice 在 cpu 层级
# 里没有目录；显示器建立 user@ 之前，cpu 层级往往只有 root。此时「只写
# 已存在的组」会一组都写不进，而脚本仍然跑完（B50 新装机实测 applied=0，
# rtkit 依旧拿不到 SCHED_RR）。因此缺目录就先建，建完再写。
#
# 判定：每次写入都回读，只有回读等于目标值才算生效。目录建不出、文件不
# 可写、内核拒绝（EINVAL）都计入 missing，并让 status 从 ok 降级——不用
# 「脚本跑完了」冒充「预算生效了」。
#
# 本文件由 POSIX sh 解释执行，禁止 bash 专有语法。
# ===========================================================================

set -u

PROC=${AIRYMAX_RT_PROC:-/proc/sys/kernel/sched_rt_runtime_us}
CGROOT=${AIRYMAX_RT_CGROOT:-/sys/fs/cgroup}
SLICES="system.slice user.slice airymax.slice airymax-desktop.slice"
DIVISOR=5
MARK=AIRYMAX-RT-BUDGET

# 单行可观测标记：验收侧只认这一行；missing 只在降级时非空。
emit() {
    printf '%s status=%s total=%s share=%s applied=%s wanted=%s missing=[%s]\n' \
        "$MARK" "$1" "$2" "$3" "$4" "$5" "$6"
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

# 建目录、写入、回读：cgroupfs 在 mkdir 时由内核生成 cpu.rt_runtime_us，
# 因此建目录本身就是「让这个组可记账」的必要一步。
apply_one() {
    [ -d "$1" ] || mkdir "$1" 2>/dev/null
    [ -w "$1/cpu.rt_runtime_us" ] || return 1
    printf '%s\n' "$2" 2>/dev/null > "$1/cpu.rt_runtime_us" || return 1
    [ "$(cat "$1/cpu.rt_runtime_us" 2>/dev/null)" = "$2" ]
}

# 逐个 slice 写入同一份额，结果留在 applied/wanted/missing 三个全局量里。
fill_all() {
    applied=0
    wanted=0
    missing=
    for name in $SLICES; do
        wanted=$((wanted + 1))
        if apply_one "$1/$name" "$2"; then
            applied=$((applied + 1))
        else
            missing="$missing $name"
        fi
    done
}

verdict() { # verdict <实到> <应有>
    [ "$1" -eq 0 ] && {
        printf 'failed'
        return 0
    }
    [ "$1" -lt "$2" ] && {
        printf 'partial'
        return 0
    }
    printf 'ok'
}

main() {
    total=$(read_total)
    share=$((total / DIVISOR))
    if [ "$total" -le 0 ]; then
        emit disabled "$total" 0 0 0 -
        return 0
    fi
    root=$(cpu_root) || {
        emit no-cgroup-v1 "$total" "$share" 0 0 -
        return 0
    }
    fill_all "$root" "$share"
    emit "$(verdict "$applied" "$wanted")" "$total" "$share" \
        "$applied" "$wanted" "${missing# }"
}

main "$@"
