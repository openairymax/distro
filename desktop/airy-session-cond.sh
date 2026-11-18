#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airy-session-cond.sh — lightdm 与桌面就绪探针的启动前置判据
#
# 用法: airy-session-cond.sh <期望会话> [单元名]
# 退出码: 0 允许启动；1 本次开机选了另一种会话；2 参数非法。
#
# 由两处 ExecCondition 调用：lightdm.service 与 airymax-desktop-ready.service。
# 判据只有一条——`desired` 与本单元期望的会话不一致就跳过。文件缺失、不可读
# 或为空一律放行：选择器还没写结论（或这台机器没有选择器）时，桌面链路必须
# 保持 0.0.4 的行为，不能因为新加的前置判据把开机锁死。
#
# 跳过时打印一行带单元名的 journal 记录。systemd 会把消息归到调用它的单元
# 名下，但串口收集器只读文本，单元名必须在行内。
#
# SSoT: 0.0.5 方案 §14.1。
# ===========================================================================
set -u

CONF=/etc/airymaxos/session.conf
# shellcheck disable=SC1090
[ -r "${CONF}" ] && . "${CONF}"
DIR="${AIRY_SESSION_DIR:-/run/airymaxos/session}"

want="${1:-}"
unit="${2:-session}"
case "${want}" in
    gui|tui) ;;
    *)
        printf 'AIRYMAX-SESSION-COND invalid=%s\n' "${want}" >&2
        exit 2
        ;;
esac

cur=""
if [ -r "${DIR}/desired" ]; then
    cur="$(sed -n '1p' "${DIR}/desired" 2>/dev/null)"
fi

if [ -n "${cur}" ] && [ "${cur}" != "${want}" ]; then
    printf 'AIRYMAX-SESSION-SKIP unit=%s desired=%s\n' "${unit}" "${cur}" >&2
    exit 1
fi
exit 0
