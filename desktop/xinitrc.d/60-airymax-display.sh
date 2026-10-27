#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# 60-airymax-display.sh — AirymaxOS 会话分辨率自适应钩子
#
# 部署：airymaxos-release 包安装到 /etc/X11/xinit/xinitrc.d/。
# 加载：lightdm 以 /etc/X11/xinit/Xsession 作为 session-wrapper，后者
#       source xinitrc-common，再由其按文件名顺序 source 本目录全部脚本；
#       startx 走 xinitrc 时同样生效。xinitrc-common 不判可执行位，
#       0644 同样会被 source，因此权限不是加载条件。
#
# 编号 60 大于 50，与 70-airymax-im.sh 一样排在 imsettings 的 50-xinput.sh
# 之后。此刻 X 刚起来，虚拟输出的 connected 拓扑可能还没建立，一次性写入
# 会落空；真正兜住「会话就绪后 settings-daemon 又改模式」的是
# /etc/xdg/autostart/airymax-display.desktop。这里只做一轮短预算收敛，
# 让首帧尽量已经在正确尺寸上布局，两者共用同一策略脚本。
#
# 显示切换失败不得阻断会话：脚本不设 set -e，收敛失败留给 T10 暴露。
#
# 本文件被 POSIX sh source，禁止使用 bash 专有语法，禁止 set -e/-u
# 影响调用方 shell。
# ===========================================================================

[ -x /usr/lib/airymaxos/desktop/display_mode.sh ] || return 0
command -v xrandr >/dev/null 2>&1 || return 0

/usr/lib/airymaxos/desktop/display_mode.sh --settle 10 >/dev/null 2>&1 || :

return 0
