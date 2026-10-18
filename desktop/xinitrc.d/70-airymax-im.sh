# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# 70-airymax-im.sh — AirymaxOS 会话输入法环境
#
# 部署：airymaxos-release 包安装到 /etc/X11/xinit/xinitrc.d/。
# 加载：lightdm 以 /etc/X11/xinit/Xsession 作为 session-wrapper，后者
#       source xinitrc-common，再由其按文件名顺序 source 本目录全部脚本；
#       startx 走 xinitrc 时同样生效。
#
# 编号必须大于 50：imsettings 的 50-xinput.sh 先清空输入法变量，并在 UKUI
# 不属于其支持桌面时把 XIM 置为 none。本脚本在其之后重新导出 fcitx4 会话
# 环境，是发行版输入法环境变量的唯一事实来源（SSoT）。
#
# 输入法进程本身由 /etc/xdg/autostart/airymax-input-method.desktop 拉起，
# 此处不 fork，避免 startx 与 ukui-session 双路径重复启动。
#
# 本文件被 POSIX sh source，禁止使用 bash 专有语法，禁止 set -e/-u
# 影响调用方 shell。
# ===========================================================================

[ -x /usr/bin/fcitx ] || return 0

export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
