#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# outdir.sh — 产物目录边界守卫（被构建驱动 source）
#
# 源码区只存放配方与配置，任何构建产物都必须落在检出区之外
# （0.0.3 任务方案 §3.1）。本库把路径解析、源码区判定和目录创建集中在
# 一处，避免各驱动各写一套判定而出现口径漂移。
#
# 调用约定：out_guard <prog> <out>，成功时向 stdout 输出绝对路径；
# 失败时以 AIRY_EINVAL(5) 或 AIRY_EIO(6) 退出。
# ===========================================================================

OUTLIB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
readonly OUTLIB_ROOT

src_root()
{
    local top="" parent=""
    if command -v git >/dev/null 2>&1; then
        top="$(git -C "${OUTLIB_ROOT}" rev-parse \
            --show-toplevel 2>/dev/null || true)"
        while [ -n "$top" ]; do
            parent="$(git -C "$top" rev-parse \
                --show-superproject-working-tree 2>/dev/null || true)"
            [ -n "$parent" ] || break
            top="$parent"
        done
    fi
    if [ -z "$top" ]; then
        top="$(dirname "$(dirname "${OUTLIB_ROOT}")")"
    fi
    (cd "$top" && pwd -P)
}

out_guard()
{
    local prog="$1" out="$2" parent name abs src
    if [ -z "$out" ]; then
        printf '%s: --out 必填\n' "$prog" >&2
        exit 5
    fi
    parent="$(dirname "$out")"
    name="$(basename "$out")"
    case "$name" in
    .|..)
        printf '%s: 输出目录不得以 . 或 .. 结尾: %s\n' "$prog" "$out" >&2
        exit 5
        ;;
    esac
    if [ ! -d "$parent" ]; then
        printf '%s: 输出目录的父目录不存在: %s\n' "$prog" "$parent" >&2
        exit 5
    fi
    abs="$(cd "$parent" && pwd -P)/${name}"
    src="$(src_root)"
    case "${abs}/" in
    "${src}"/*)
        printf '%s: 输出目录位于源码区（%s），禁止在源码区构建: %s\n' \
            "$prog" "$src" "$abs" >&2
        exit 5
        ;;
    esac
    if ! mkdir -p "$abs"; then
        printf '%s: 无法创建产物目录: %s\n' "$prog" "$abs" >&2
        exit 6
    fi
    printf '%s\n' "$abs"
}
