# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# 65-airymax-audio.sh — 会话启动前确保 PulseAudio 就绪
#
# 症状：285H 实机首启时 ukui-volume-control-applet-qt 在 7 秒内连续崩溃 12
# 次（dmesg: segfault at 8 in libQt5Core.so.5.15.10, error 4），面板反复重启
# 音量小程序的空隙里托盘没有音量图标，出声设备的第一次点击也无响应。
#
# 根因：PulseAudio 在本基线里没有 systemd 用户单元（openEuler 24.03 LTS-SP3
# 的 pulseaudio 17 只带 autospawn，目标机上 pulseaudio.socket 与
# pulseaudio.service 均为 not-found），进程靠第一个客户端连接时的
# libpulse 自动拉起。小程序启动早于该次拉起完成，连接失败路径不判空就解引用
# pa_context，直接终止。以不可达的 PULSE_SERVER 复现同一二进制得 SIGABRT
# (134)，而正常服务器下同一命令连跑 6 秒无异常——崩溃只在「套接字还没出现」
# 这个窗口里发生，与声卡型号无关。
#
# 修法：在会话脚本序列里主动拉起 PulseAudio 并等套接字可连，再让
# ukui-session 去启动面板。健康路径实测约 0.2 秒（守护进程 fork 后立即返回，
# 等待只覆盖套接字 bind 的窗口）；无声卡或音频栈损坏时最多等 2 秒，然后打一
# 行归因到 stderr 并放行——登录流程绝不因为音频不可用而阻塞。
#
# 为什么放在此处而不是做成用户单元：本文件由 Xsession 在启动会话命令之前
# source，是「面板启动前」这一时序约束唯一可靠的挂点；做成 WantedBy=
# default.target 的用户单元与图形会话并行，无法表达「先于面板」。
#
# 本文件被 POSIX sh source，禁止 bash 专有语法，禁止 set -e/-u 影响调用方，
# 失败一律以状态码表达并 return 0（会话必须继续）。编号大于 60：显示模式
# 在 60 段落定，本段不再判断分辨率；小于 70：输入法段之后就是面板。
# ===========================================================================

[ -x /usr/bin/pulseaudio ] || return 0
[ -n "${XDG_RUNTIME_DIR:-}" ] || return 0

sock="${XDG_RUNTIME_DIR}/pulse/native"

if [ -S "${sock}" ]; then
    return 0
fi

/usr/bin/pulseaudio --start >/dev/null 2>&1 || :

tries=0
while [ "${tries}" -lt 20 ]; do
    if [ -S "${sock}" ]; then
        return 0
    fi
    sleep 0.1
    tries=$((tries + 1))
done

printf 'airymax-audio: %s absent after 2s, volume applet may abort\n' \
    "${sock}" >&2

return 0
