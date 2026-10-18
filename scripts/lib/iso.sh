#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# iso.sh — ISO 清单解析（被构建驱动 source）
#
# build-iso.sh 产出的 iso-manifest.txt 用 name= 记录镜像文件名，构建驱动
# 与镜像 CI 都要据此定位产物。解析规则收敛到一处，避免两侧对缺字段、
# 空值的判定口径漂移。
#
# 调用约定：iso_name <目录>，向 stdout 输出镜像文件名；清单缺失或无
# name 字段时以非零状态返回且不输出内容。
# ===========================================================================

iso_name()
{
    local dir="$1" line value=""
    [ -f "${dir}/iso-manifest.txt" ] || return 1
    while IFS= read -r line; do
        case "${line}" in
        name=*) value="${line#name=}" ;;
        esac
    done <"${dir}/iso-manifest.txt"
    [ -n "${value}" ] || return 1
    printf '%s\n' "${value}"
}
