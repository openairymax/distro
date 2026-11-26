# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# 62-airymax-compose.sh — 无 render 节点机器的合成后端裁决
#
# 部署：airymaxos-release 包安装到 /etc/X11/xinit/xinitrc.d/。
# 加载：与 60/70 两份同一通路——lightdm 的 session-wrapper
#       /etc/X11/xinit/Xsession source xinitrc-common，后者按文件名顺序
#       source 本目录全部脚本；此处 export 的变量被随后的 ukui-session
#       及其子进程继承，而 xinitrc-common 不判可执行位。
#
# 判据只看设备事实：/dev/dri/renderD* 是否存在。只有 simpledrm 的机器上
# 不存在该节点，合成器仍会走 GL——Mesa 在没有 DRM 设备时落到 llvmpipe，
# 而 llvmpipe 的着色器物化在该基线上失败（JIT session error: Permission
# denied），合成器随即在绘制路径 SIGSEGV，现场表现是「桌面一起来就反复
# 崩溃，每几秒一个 coredump」。钉住 KWIN_COMPOSE=X 让合成器直接走
# XRender，不进 GL 路径，崩溃从根上不发生。
#
# 有 render 节点的机器一概不改写：硬件合成是默认路径，不因本脚本降级。
# AIRY_DRI_DIR 只给自检用：打包期在无 DRM 的构建机上复跑两个出口。
#
# 本文件被 POSIX sh source，禁止 bash 专有语法，禁止 set -e/-u 影响调用方。
# ===========================================================================

airy_dri=${AIRY_DRI_DIR:-/dev/dri}

for airy_node in "${airy_dri}"/renderD*; do
    [ -e "${airy_node}" ] && return 0
done

KWIN_COMPOSE=X
export KWIN_COMPOSE
