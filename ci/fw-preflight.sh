#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# fw-preflight.sh — 在装机之前按架构预演一次固件扁平入口
#
# 为什么需要这一层：T26 只在镜像自己的 rootfs 上复核「清单与入口一致」，
# 回答不了「该架构模块树请求的固件，固件树里到底有没有」。后者的输入是
# 别的架构的模块树，而四个架构的 kernel RPM 只在构建期同时在场。
# riscv64 没有实机兜底，ARM 的板载无线在 QEMU 里也不出现，这条只能在这里拦。
#
# 判据的输入是两个名字集，不是两份文件树：
#   ① 固件名字集：镜像将要装的那个 linux-firmware RPM 在 /usr/lib/firmware
#      下的相对路径，一行一个；
#   ② 模块请求名：该架构 kernel-modules 解出的 *.ko* 里 MODULE_FIRMWARE()
#      自报的名字，取法与安装期同一条（modinfo -F firmware）。
#
# 预演树是空文件骨架：按固件名字集建目录、建同名空文件。判据只看名字与
# 相对路径——后缀决定入口名，相对路径长度决定最短优先——不读内容，所以
# 空文件与真文件的判定完全等价，代价从「复制数 GB 固件」降到「建数千个
# 空 inode」。
#
# 补齐与判定都直接调用 firmware/fw-flat.sh，不复制实现：预演与装机共用
# 同一份规则，否则两处各判一套，预演绿了装机照样缺件。
#
# 本脚本随源码树交付，不入包：它读的是构建期的 RPM 与模块树，装到机器上
# 没有任何可做的事。
#
# 退出码：0 全部命中；1 有请求名在骨架里查不到、或骨架建不起来；2 用法错误。
# ===========================================================================
set -eu

FP_FAIL=1
FP_USE=2

fp_usage()
{
    printf '%s\n' \
        '用法: fw-preflight.sh --firmware FILE --modules DIR --arch NAME' \
        '' \
        '  --firmware  固件名字集，一行一个 /usr/lib/firmware 下的相对路径' \
        '  --modules   该架构模块树根（含 */kernel/.../*.ko*）' \
        '  --arch      报告用的架构名' \
        '  --requests  请求名清单；缺省由 modinfo 从模块树读取'
}

# fp_parse —— 解析参数。三个都必填：缺一个就无法构成判据，按用法错误退 2，
# 不拿缺省值猜，否则 --firmware 缺失会被读成「没有固件请求」而假绿。
fp_parse()
{
    fp_fw=
    fp_mods=
    fp_arch=
    fp_reqs=
    while [ "$#" -gt 0 ]; do
        case "$1" in
        -h | --help) fp_usage; exit 0 ;;
        --firmware | --modules | --arch | --requests) ;;
        *) fp_usage >&2; exit "${FP_USE}" ;;
        esac
        [ "$#" -ge 2 ] || { fp_usage >&2; exit "${FP_USE}"; }
        case "$1" in
        --firmware) fp_fw=$2 ;;
        --modules) fp_mods=$2 ;;
        --arch) fp_arch=$2 ;;
        --requests) fp_reqs=$2 ;;
        esac
        shift 2
    done
    if [ -z "${fp_fw}" ] || [ -z "${fp_mods}" ] || [ -z "${fp_arch}" ]
    then
        fp_usage >&2
        exit "${FP_USE}"
    fi
}

# fp_tree LIST ROOT —— 按名字集建空文件骨架。目录条目（以 / 结尾）与绝对
# 路径跳过：前者不是可请求的固件，后者不落在固件根之下，建了也索引不到。
fp_tree()
{
    [ -r "$1" ] || return 1
    while IFS= read -r ft_rel; do
        [ -n "${ft_rel}" ] || continue
        case "${ft_rel}" in
        /* | */) continue ;;
        esac
        install -d "$2/$(dirname "${ft_rel}")" 2>/dev/null || return 1
        : >"$2/${ft_rel}" 2>/dev/null || return 1
    done <"$1"
}

# fp_report TEXT —— 从 fw-flat 的输出里取 flat/miss 两个计数与逐条缺件。
# 只认最后一条 flat= 行：重复调用时早期故障行不代表本轮结论。
fp_report()
{
    fr_sum=$(printf '%s\n' "$1" | awk '/^flat=[0-9]+ miss=[0-9]+/ { s = $0 } END { print s }')
    if [ -z "${fr_sum}" ]; then
        fr_fail=$(printf '%s\n' "$1" | awk -F= '/^fail=/ { print $2; exit }')
        printf 'AIRYMAX-FW-PREFLIGHT arch=%s fail=%s modules=%s\n' \
            "${fp_arch}" "${fr_fail:-unknown}" "${fp_mods}"
        exit "${FP_FAIL}"
    fi
    fr_flat=$(printf '%s\n' "${fr_sum}" | sed 's/^flat=\([0-9]*\) .*/\1/')
    fr_miss=$(printf '%s\n' "${fr_sum}" | sed 's/.* miss=\([0-9]*\) .*/\1/')
    printf 'AIRYMAX-FW-PREFLIGHT arch=%s flat=%s miss=%s\n' \
        "${fp_arch}" "${fr_flat}" "${fr_miss}"
    if [ "${fr_miss}" -eq 0 ]; then
        return 0
    fi
    printf '%s\n' "$1" | awk '/^miss name=/ { print }' >&2
    exit "${FP_FAIL}"
}

# fp_main —— 建骨架、跑补齐、按计数判定。骨架在临时目录里，退出即删：
# 预演留下的是结论，不是一份可以和真树混淆的固件树。
fp_main()
{
    fp_parse "$@"
    fp_conf=$(dirname "$0")/../firmware/fw-flat.sh
    if [ ! -r "${fp_conf}" ]; then
        printf 'AIRYMAX-FW-PREFLIGHT arch=%s fail=no-flat\n' "${fp_arch}"
        exit "${FP_FAIL}"
    fi
    fp_tmp=$(mktemp -d)
    trap 'rm -rf "${fp_tmp}"' EXIT INT TERM
    if ! fp_tree "${fp_fw}" "${fp_tmp}/root"; then
        printf 'AIRYMAX-FW-PREFLIGHT arch=%s fail=no-tree firmware=%s\n' \
            "${fp_arch}" "${fp_fw}"
        exit "${FP_FAIL}"
    fi
    set -- apply "${fp_tmp}/root" --list "${fp_tmp}/flat.list" \
        --modules "${fp_mods}"
    [ -z "${fp_reqs}" ] || set -- "$@" --requests "${fp_reqs}"
    fp_out=$(sh "${fp_conf}" "$@" 2>&1) || :
    fp_report "${fp_out}"
}

fp_main "$@"
