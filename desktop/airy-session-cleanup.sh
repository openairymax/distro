#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# airy-session-cleanup.sh — lightdm 会话结束钩子：注销即回 TUI
#
# 交付口径：交付账户是自动登录的，注销若回到 greeter，greeter 会按
# autologin-user-timeout=0 立刻再登进桌面——用户看到的是「注销没反应」。
# 这里把注销解释为「切到 TUI」：写下去向原因，提交切换作业，随即返回，
# lightdm 自己会在座位停掉时退出。
#
# 三处不动作，都是为了避免把别的流程搅进去：
#   * 系统不在 running/degraded（关机、早期引导）：此时停座位属于关机链路；
#   * desired 已是 tui：切换正在进行，重复提交只会让两个作业抢同一批单元；
#   * 目录不可写：没有状态面就没有切换，直接返回，不猜。
#
# 本脚本不改 mode：实际态只由切换单元在会话真正就绪后写（§14.15 F-50）。
#
# 用法（lightdm 调用，无参数）：session-cleanup-script=/usr/lib/airymaxos/desktop/airy-session-cleanup.sh
# SSoT: 0.0.5 方案 §14.15。
# ===========================================================================
set -u

DIR=/run/airymaxos/session
CONF=/etc/airymaxos/session.conf

# shellcheck disable=SC1090  # 部署期路径，构建机上不存在该文件
[ -r "$CONF" ] && . "$CONF"
: "${AIRY_SESSION_DIR:=$DIR}"

state=$(systemctl is-system-running 2>/dev/null)
case "$state" in
    running | degraded) ;;
    *) exit 0 ;;
esac

want=$(cat "$AIRY_SESSION_DIR/desired" 2>/dev/null)
[ "$want" = "tui" ] && exit 0

# 目录由写者自建（0755 root，§14.15 F-48）；先建再定权限，避免父目录
# 不存在时 mkdir -p -m 只对最深一层生效的差异。
mkdir -p "$AIRY_SESSION_DIR" 2>/dev/null || exit 0
chmod 0755 "$AIRY_SESSION_DIR" 2>/dev/null || exit 0
printf 'logout\n' >"$AIRY_SESSION_DIR/.switch-reason.new" 2>/dev/null || exit 0
mv -f "$AIRY_SESSION_DIR/.switch-reason.new" "$AIRY_SESSION_DIR/switch-reason" ||
    exit 0

echo "AIRYMAX-SESSION-LOGOUT reason=logout"
systemctl --no-block start airy-session-switch@tui.service 2>/dev/null
exit 0
