#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# install-lib.sh — 安装期打印、阶段与失败标记（被 kickstart 嵌入）
#
# anaconda 把脚本段的标准输出收进 --log 指定的文件，串口上一片空白；无头
# 验收只读串口，因此每一行结论都必须单独再写一次可用控制台。内核按
# console= 的注册顺序把 /dev/console 路由到最后一个可用控制台：x86_64 为
# ttyS0，aarch64 为 ttyAMA0。AIRY_CONSOLE 是测试注入点，指向临时文件即可
# 在不碰真实 /dev 的机器上驱动全部行为。
#
# 阶段行带序号：装机卡住时串口最后一行就是正在执行的阶段（n/m <name>），
# 不必复现就能判断停在哪一段。失败行同时带 reason= 与 step=：reason 说明
# 是哪一条断言失败，step 说明流程走到哪一段，两者合起来才能直接归因。
#
# 嵌入顺序是语义：本文件必须先于 disk-select.sh 展开——选盘器依赖这里
# 的 airy_out 与 airy_fail。tools/ks_embed.py 的 audit 对同一脚本段强制
# 这条顺序。
#
# 阶段行只说明「进了哪一段」，说明不了这一段是在跑还是已经死掉：dnf 移除、
# grub2-mkconfig 与把它们的输出收进日志的两段回放，耗时都在十几秒以上，
# 屏幕在这段时间里没有任何新行。卡在这里时，人无法区分「慢」与「死」。
# 因此长命令一律经 airy_wait 执行：超过 BEAT 秒就在控制台补一行心跳，写明
# 哪一段、在跑哪条命令、已经等了多久。心跳只报已等秒数，不编造上限——装
# 机脚本段没有 TimeoutStartSec，写一个预期上限等于把别人的判据搬进一个不
# 存在的机制。
#
# 调用约定：只定义函数，无顶层副作用，可同时嵌入 %pre 与 %post。
#   airy_out   <text>                     写标准输出与可用控制台
#   airy_beat  <text>                     只写可用控制台（心跳通道）
#   airy_step  <idx> <total> <name>       记录并打印阶段行
#   airy_wait  [-q] <name> <cmd...>       跑命令，慢于 AIRY_BEAT 秒就报心跳
#   airy_fail  <family> <reason> [note]   发布失败标记并终止脚本段
#   airy_trap  <family>                   置 EXIT 兜底失败标记
#   set_default / acct_state / acct_req   目标根内断言（chroot %post）
# ===========================================================================

AIRY_STEP=
AIRY_TAG=INSTALL

# airy_beat <text> — 只写可用控制台。心跳走这条通道：写进标准输出会被
# %post 的 --log 收走，随后又被逐行回放抄一遍，同一行于是在串口上出现
# 两次，第二次还带着回放前缀。
airy_beat()
{
    local dev

    for dev in ${AIRY_CONSOLE:-/dev/console /dev/ttyS0 /dev/ttyAMA0}; do
        if [ -w "${dev}" ] && printf '%s\n' "$*" >"${dev}" 2>/dev/null
        then
            break
        fi
    done
    return 0
}

# airy_out <text> — 同时写标准输出与可用控制台。
airy_out()
{
    printf '%s\n' "$*"
    airy_beat "$@"
}

# airy_step <idx> <total> <name> — 记录当前流程段并打印阶段行。
airy_step()
{
    AIRY_STEP="$1/$2 $3"
    airy_out "AIRYMAX-INSTALL-STEP $1/$2 $3"
}

# wait_beat <name> — 心跳循环，每 AIRY_BEAT 秒一行。
#
# 计数从调用开始累计，报的是「已经等了多久」，不是墙钟时刻：装机现场没有
# 对时保证，绝对时刻读不出意义。sleep 必须自己丢掉输出，否则它比命令活得
# 久，继承到的管道要等下一次 tick 才关，采集端会连带挂住（与 stage_run.sh
# 同一处理）。主脚本段已经不在时自行退出，不在装机介质上留一个每 15 秒往
# 串口写一行的孤儿。
wait_beat()
{
    local name="$1" used=0 beat="${AIRY_BEAT:-15}"

    while sleep "${beat}" >/dev/null 2>&1; do
        kill -0 "$$" 2>/dev/null || return 0
        used=$((used + beat))
        airy_beat "AIRYMAX-INSTALL-WAIT step=${AIRY_STEP:-unknown}" \
            "name=${name} t=${used}s"
    done
}

# airy_wait [-q] <name> <cmd...> — 前台跑命令，慢于 BEAT 秒就持续报心跳。
# 退出码原样透传，调用方的 || 分支与 set -e 语义都不变。-q 只丢掉命令自身
# 的输出，心跳仍走控制台。
airy_wait()
{
    local quiet=0 name bpid= rc=0

    case "${1:-}" in
    -q) quiet=1; shift ;;
    esac
    name="${1:?airy_wait 缺少命令名}"
    shift
    wait_beat "${name}" &
    bpid=$!
    if [ "${quiet}" -eq 1 ]; then
        "$@" >/dev/null 2>&1 || rc=$?
    else
        "$@" || rc=$?
    fi
    kill "${bpid}" 2>/dev/null || :
    wait "${bpid}" 2>/dev/null || :
    return "${rc}"
}

# airy_fail <family> <reason> [note] — 置失败标记并终止所在脚本段。
airy_fail()
{
    local note=

    trap - EXIT
    [ -z "${3:-}" ] || note=" note=$3"
    airy_out "AIRYMAX-$1-FAIL reason=$2 step=${AIRY_STEP:-unknown}${note}"
    exit 1
}

# airy_on_exit — set -e 中止时补发失败标记，避免装机空耗到超时。
airy_on_exit()
{
    local rc=$?

    [ "${rc}" -eq 0 ] && return 0
    airy_fail "${AIRY_TAG:-INSTALL}" rc "rc=${rc}"
}

# airy_trap <family> — 本段失败时归到 <family>。
airy_trap()
{
    AIRY_TAG="$1"
    trap airy_on_exit EXIT
}

# 安装器的 chroot 内没有可用的 systemd 总线，单元文件类动词必须显式走
# --root 离线语义。判定不看命令退出码，而看落盘状态：不同 systemd 版本在
# chroot 内对 set-default 的退出码语义不一致，default.target 符号链接才是
# 唯一事实。
set_default()
{
    local want="$1"

    systemctl --root=/ set-default "${want}" ||
        airy_out "AIRYMAX-INSTALL-NOTE set-default rc=$?"
    [ "$(readlink -f /etc/systemd/system/default.target)" = \
        "/usr/lib/systemd/system/${want}" ] ||
        airy_fail INSTALL default-target
}

# 账户状态只读 /etc/shadow 的哈希字段：安装器写口令走 chpasswd -e，哈希
# 原样落盘，锁定语义是前缀 !，禁用是 *。空口令与「账户不存在」在 $2 上
# 都是空串，awk 因此对存在的账户打印 @empty 哨兵，避免把免密账户误判为
# 缺失。passwd -S 依赖 PAM 与本地化输出，在 chroot 内的判读条件不如直接
# 读文件确定。
acct_state()
{
    local pw

    pw=$(awk -F: -v n="$1" \
        '$1 == n { print ($2 == "" ? "@empty" : $2); exit }' /etc/shadow)
    case "${pw}" in
    '') printf 'missing' ;;
    '@empty') printf 'empty' ;;
    '!'*) printf 'locked' ;;
    '*'*) printf 'nologin' ;;
    "\$6\$"*) printf 'sha512' ;;
    '$'*) printf 'hashed' ;;
    *) printf 'plain' ;;
    esac
}

# 断言与归因合一：失配时先打印状态分类（不含哈希），装机失败可直接判读。
acct_req()
{
    local state

    state=$(acct_state "$1")
    [ "${state}" = "$2" ] && return 0
    airy_out "AIRYMAX-INSTALL-DIAG acct=$1 state=${state} want=$2"
    airy_fail INSTALL "$3"
}
