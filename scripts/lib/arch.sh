#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# arch.sh — 宿主架构归一（被构建驱动 source）
#
# uname -m 在部分发行版与容器里返回 amd64/arm64 别名，而 RPM 命名、ISO
# 卷内目录与清单只接受 x86_64/aarch64。归一化收敛到一处，避免各驱动各写
# 一份 case 而产生口径漂移。
#
# 调用约定：host_arch，向 stdout 输出归一化架构名。
# ===========================================================================

host_arch()
{
    case "$(uname -m)" in
    amd64) printf 'x86_64\n' ;;
    arm64) printf 'aarch64\n' ;;
    *) uname -m ;;
    esac
}
