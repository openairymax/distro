#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# 60-airymax-display.sh — AirymaxOS 会话分辨率自适应钩子
#
# 部署：airymaxos-release 包安装到 /etc/X11/xinit/xinitrc.d/。
# 加载：lightdm 以 /etc/X11/xinit/Xsession 作为 session-wrapper，后者
#       source xinitrc-common，再由其按文件名顺序 source 本目录全部脚本；
#       startx 走 xinitrc 时同样生效。
#
# 编号 60 同样大于 50，与 70-airymax-im.sh 一样排在 imsettings 的
# 50-xinput.sh 之后。分辨率必须在会话绘制首帧前落定，否则 ukui-panel
# 会按错误的工作区尺寸布局。策略本身（上限与阶梯）只在
# /usr/lib/airymaxos/desktop/display_mode.sh 中定义，此处仅负责调用，
# 不复制常量。
#
# 显示切换失败不得阻断会话：脚本以 || : 吞掉非零退出，交由 T10 在验收
# 阶段暴露问题。
#
# 本文件被 POSIX sh source，禁止使用 bash 专有语法，禁止 set -e/-u
# 影响调用方 shell。
# ===========================================================================

[ -x /usr/lib/airymaxos/desktop/display_mode.sh ] || return 0
command -v xrandr >/dev/null 2>&1 || return 0

/usr/lib/airymaxos/desktop/display_mode.sh >/dev/null 2>&1 || :

return 0
