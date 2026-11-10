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
# 构建期这两个名字集都不是现成的：目标架构的 .ko 不在宿主上，固件树也还
# 没解包。因此本脚本另收两种取件形式——--firmware-rpm 与 --modules-rpm，
# 由它自己在临时目录里从 RPM 生成名字集、解出模块树。取件与判定留在同一
# 个脚本里，是为了让「预演的是哪份固件、哪份模块」与结论落在同一条日志。
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
# 取件用的三个外部命令做成可替换入口：与 fw-flat.sh 的 AIRY_MODINFO 同一
# 做法。用例要覆盖「工具缺席」这条分支，而缺席是环境属性，不钉住就只能
# 依赖跑用例那台机器恰好没装，判定随环境漂移。
FP_RPM=${AIRY_RPM:-rpm}
FP_RPM2CPIO=${AIRY_RPM2CPIO:-rpm2cpio}
FP_CPIO=${AIRY_CPIO:-cpio}

fp_usage()
{
    printf '%s\n' \
        '用法: fw-preflight.sh (--firmware FILE | --firmware-rpm RPM)' \
        '                     (--modules DIR | --modules-rpm RPM)' \
        '                     --arch NAME [--requests FILE]' \
        '' \
        '  --firmware      固件名字集，一行一个 /usr/lib/firmware 下相对路径' \
        '  --firmware-rpm  linux-firmware 的 RPM，名字集由文件清单生成' \
        '  --modules       该架构模块树根（含 */kernel/.../*.ko*）' \
        '  --modules-rpm   该架构 kernel-modules 的 RPM，就地解到临时目录' \
        '  --arch          报告用的架构名' \
        '  --requests      请求名清单；缺省由 modinfo 从模块树读取'
}

# fp_one A B —— 两个取件形式恰好给一个。都给时无法确定判据读的是哪一份，
# 都不给时判据没有输入，两种都按用法错误处理，不替调用方挑一个。
fp_one()
{
    [ -n "$1" ] && [ -z "$2" ] && return 0
    [ -z "$1" ] && [ -n "$2" ] && return 0
    return 1
}

# fp_parse —— 解析参数。--arch 必填，两对取件形式各恰好给一个：缺一个就
# 无法构成判据，按用法错误退 2，不拿缺省值猜，否则固件缺失会被读成
# 「没有固件请求」而假绿。
fp_parse()
{
    fp_fw=
    fp_fwrpm=
    fp_mods=
    fp_modrpm=
    fp_arch=
    fp_reqs=
    while [ "$#" -gt 0 ]; do
        case "$1" in
        -h | --help) fp_usage; exit 0 ;;
        --firmware | --firmware-rpm | --modules | --modules-rpm | \
            --arch | --requests) ;;
        *) fp_usage >&2; exit "${FP_USE}" ;;
        esac
        [ "$#" -ge 2 ] || { fp_usage >&2; exit "${FP_USE}"; }
        case "$1" in
        --firmware) fp_fw=$2 ;;
        --firmware-rpm) fp_fwrpm=$2 ;;
        --modules) fp_mods=$2 ;;
        --modules-rpm) fp_modrpm=$2 ;;
        --arch) fp_arch=$2 ;;
        --requests) fp_reqs=$2 ;;
        esac
        shift 2
    done
    if [ -z "${fp_arch}" ] ||
        ! fp_one "${fp_fw}" "${fp_fwrpm}" ||
        ! fp_one "${fp_mods}" "${fp_modrpm}"
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

# fp_fw_list RPM LIST —— 固件名字集从 RPM 的文件清单生成。只取
# /usr/lib/firmware 之下的条目并去掉该前缀：骨架按相对路径建，前缀留着会
# 让每个名字都变成绝对路径而被 fp_tree 整批跳过。
fp_fw_list()
{
    command -v "${FP_RPM}" >/dev/null 2>&1 || return 3
    "${FP_RPM}" -qlp "$1" 2>/dev/null |
        sed -n 's|^/usr/lib/firmware/||p' >"$2" || return 1
    [ -s "$2" ] || return 1
}

# fp_mod_tree RPM OUT —— 把模块包解到 OUT，返回模块根。用 cpio 直接解而
# 不装包：预演只要 *.ko* 里的 MODULE_FIRMWARE()，装进宿主反而会覆盖正在
# 运行的内核模块。
fp_mod_tree()
{
    install -d "$2" || return 1
    command -v "${FP_RPM2CPIO}" >/dev/null 2>&1 || return 3
    command -v "${FP_CPIO}" >/dev/null 2>&1 || return 4
    "${FP_RPM2CPIO}" "$1" 2>/dev/null |
        (cd "$2" && "${FP_CPIO}" -idm --quiet 2>/dev/null) || return 1
    [ -d "$2/usr/lib/modules" ] || return 5
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
    fp_rc=0
    if [ -n "${fp_fwrpm}" ]; then
        fp_fw="${fp_tmp}/firmware.list"
        fp_fw_list "${fp_fwrpm}" "${fp_fw}" || fp_rc=$?
        if [ "${fp_rc}" -ne 0 ]; then
            case "${fp_rc}" in
            3) fp_rc=no-rpm ;;
            *) fp_rc=no-firmware ;;
            esac
            printf 'AIRYMAX-FW-PREFLIGHT arch=%s fail=%s rpm=%s\n' \
                "${fp_arch}" "${fp_rc}" "${fp_fwrpm}"
            exit "${FP_FAIL}"
        fi
    fi
    if [ -n "${fp_modrpm}" ]; then
        fp_mod_tree "${fp_modrpm}" "${fp_tmp}/mods" || fp_rc=$?
        if [ "${fp_rc}" -ne 0 ]; then
            case "${fp_rc}" in
            3) fp_rc=no-rpm2cpio ;;
            4) fp_rc=no-cpio ;;
            5) fp_rc=no-modroot ;;
            *) fp_rc=no-modules ;;
            esac
            printf 'AIRYMAX-FW-PREFLIGHT arch=%s fail=%s rpm=%s\n' \
                "${fp_arch}" "${fp_rc}" "${fp_modrpm}"
            exit "${FP_FAIL}"
        fi
        fp_mods="${fp_tmp}/mods/usr/lib/modules"
    fi
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
