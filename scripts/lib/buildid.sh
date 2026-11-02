#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# buildid.sh — 构件来源指纹（被构建驱动 source）
#
# 同一版本号会随每次提交产出不同镜像。发布清单若只记录 VERSION_ID，装机后
# 无法回答「这台机器上的 0.0.4 来自哪次构建」；镜像文件名也不能承担这件事，
# 分发渠道会重命名，归档也不保证保留原名。指纹因此写进 os-release 的
# BUILD_ID 与 /etc/airymaxos-build，由发布清单与运行期探针比对。
#
# 取值优先级（越靠前越具体，取值来源本身随清单归档）：
#   1. AIRYMAX_BUILD_ID               发布流水线显式指定，原样使用
#   2. AIRYMAX_RUN_ID + AIRYMAX_COMMIT
#                                     r<run>-g<sha12>，流水线原生量
#   3. git 短 sha                      g<sha12>，本地开发构建
#   4. 配方摘要                        src-<sha12>，脱离 git 的最小可复算来源
#
# 第 4 级不是兜底占位：它由本次实际参与构建的配方内容算出，同配方同摘要，
# 配方变更必然改变指纹，因此在无 git、无流水线变量的构建机上仍可归因。
#
# 调用约定：
#   airy_build_id DIR [SPEC...]  向 stdout 输出指纹；SPEC 为空时取
#                                DIR/specs/*.spec，目录缺失则退化为空输入。
#   airy_bid_ok ID               字符集与长度合法返回 0，否则返回 1。
# ===========================================================================

# 指纹要同时写进 os-release 的带引号值与一行式文件，故只接受在两者中都
# 无需转义的字集；长度上限防止把路径或说明文字误当指纹传入。
readonly BID_MAX=64

airy_bid_ok()
{
    case "${1:-}" in
    ''|*[!A-Za-z0-9._+-]*) return 1 ;;
    esac
    [ "${#1}" -le "${BID_MAX}" ]
}

# 取短 sha。git 缺失或目录不是仓库时输出为空而不是非零：调用方用「空」
# 表示该级不可用，与「指纹为空」区分开。
aid_commit()
{
    { git -C "$1" rev-parse HEAD 2>/dev/null || :; } | cut -c1-12
}

aid_digest()
{
    local f
    for f in "$@"; do
        [ -f "${f}" ] || continue
        printf '%s\n' "${f}"
    done | LC_ALL=C sort | while IFS= read -r f; do
        printf '%s %s\n' "$(sha256sum "${f}" | cut -d' ' -f1)" "${f##*/}"
    done | sha256sum | cut -c1-12
}

airy_build_id()
{
    local root="$1" id=""
    shift
    [ "$#" -gt 0 ] || set -- "${root}"/specs/*.spec

    id="${AIRYMAX_BUILD_ID:-}"
    if [ -z "${id}" ] && [ -n "${AIRYMAX_RUN_ID:-}" ] &&
        [ -n "${AIRYMAX_COMMIT:-}" ]; then
        id="r${AIRYMAX_RUN_ID}-g$(printf '%s' "${AIRYMAX_COMMIT}" | cut -c1-12)"
    fi
    if [ -z "${id}" ]; then
        id="$(aid_commit "${root}")"
        [ -z "${id}" ] || id="g${id}"
    fi
    if [ -z "${id}" ]; then
        id="src-$(aid_digest "$@")"
    fi
    printf '%s\n' "${id}"
}
