#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# session_env.sh — X11 会话环境发现（共享库）
#
# 问题：录屏与观察点都要在「当前图形会话」里取 DISPLAY 与 XAUTHORITY，
# 但调用方可能来自 SSH、systemd 单元或桌面内终端，三者环境完全不同。SSH
# 会话里没有 DISPLAY；systemd 单元继承的是管理器的空环境；桌面内终端虽然
# 有 DISPLAY，XAUTHORITY 也可能指向已失效的临时文件。任何一处猜错，
# x11grab 与 xrandr 都只会得到 "Cannot open display"，而错误信息不指向
# 真正缺的那个变量。
#
# 发现顺序（从最可信到最兜底）：
#   1. 现成环境：DISPLAY 非空且 XAUTHORITY 是可读文件，直接采用；
#   2. logind：列出会话，取 Type=x11 且 Display 非空者，从会话 Leader 进程
#      的 /proc/<pid>/environ 读它启动时拿到的 XAUTHORITY。这是唯一能拿到
#      「会话真实凭据」的权威来源，lightdm 生成的临时 xauthority 只有会话
#      自己知道路径；
#   3. X socket：/tmp/.X11-unix/X* 存在且能找到可读 xauthority 时配对。
#
# 失败时不修改任何环境变量：调用方据此决定降级还是放弃，而不是拿到一个
# 半配置的 DISPLAY 继续跑。
#
# 本文件是被 source 的库，不设 set -u，也不在加载时做任何探测。
# 依赖：loginctl、awk、sed、tr、head。
# ===========================================================================

# 读某进程启动时的环境变量：environ 以 NUL 分隔，sed 按行取首个匹配。
airy_proc_env() {
    [ -r "/proc/$1/environ" ] || return 1
    tr '\000' '\n' <"/proc/$1/environ" | sed -n "s/^$2=//p" | head -n 1
}

# logind 里的 X11 会话：只认 Type=x11 且有 Display 的，wayland 会话没有
# X socket 可供 x11grab 使用。
airy_logind_session() {
    for sid in $(loginctl list-sessions --no-legend 2>/dev/null |
        awk '$1 ~ /^[0-9]+$/ { print $1 }'); do
        [ "$(loginctl show-session "$sid" -p Type --value 2>/dev/null)" = x11 ] ||
            continue
        disp=$(loginctl show-session "$sid" -p Display --value 2>/dev/null)
        [ -n "$disp" ] || continue
        leader=$(loginctl show-session "$sid" -p Leader --value 2>/dev/null)
        [ -n "$leader" ] || continue
        auth=$(airy_proc_env "$leader" XAUTHORITY)
        [ -n "$auth" ] && [ -r "$auth" ] || continue
        airy_display=$disp
        airy_xauthority=$auth
        return 0
    done
    return 1
}

# 兜底：socket 存在只说明 X server 活着，凭据仍要从磁盘找一个可读的。
airy_x_socket() {
    for sock in /tmp/.X11-unix/X*; do
        [ -S "$sock" ] || continue
        for auth in /run/lightdm/*/xauthority "$HOME/.Xauthority"; do
            [ -r "$auth" ] || continue
            airy_display=":${sock##*/X}"
            airy_xauthority=$auth
            return 0
        done
    done
    return 1
}

# 对外入口：成功后导出 DISPLAY 与 XAUTHORITY，两者互为配套，不单独导出。
airy_session_env() {
    if [ -n "${DISPLAY:-}" ] && [ -n "${XAUTHORITY:-}" ] &&
        [ -r "${XAUTHORITY}" ]; then
        airy_display=$DISPLAY
        airy_xauthority=$XAUTHORITY
    elif ! airy_logind_session; then
        airy_x_socket || return 1
    fi
    DISPLAY=$airy_display
    XAUTHORITY=$airy_xauthority
    export DISPLAY XAUTHORITY
    return 0
}
