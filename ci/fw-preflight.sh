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
        '用法: fw-preflight.sh (--firmware FILE | --firmware-rpm RPM ...)' \
        '                     (--modules DIR | --modules-rpm RPM)' \
        '                     --arch NAME [--requests FILE] [--exempt FILE]' \
        '' \
        '  --firmware      固件名字集，一行一个 /usr/lib/firmware 下相对路径' \
        '  --firmware-rpm  固件包的 RPM，可重复；名字集取各包文件清单的并集' \
        '  --modules       该架构模块树根（含 */kernel/.../*.ko*）' \
        '  --modules-rpm   该架构 kernel-modules 的 RPM，就地解到临时目录' \
        '  --arch          报告用的架构名' \
        '  --requests      请求名清单；缺省由 modinfo 从模块树读取' \
        '  --exempt        豁免表：每行 <名字通配> <原因>，命中的缺件不计入 miss'
}

# fp_one A B —— 两个取件形式恰好给一个。都给时无法确定判据读的是哪一份，
# 都不给时判据没有输入，两种都按用法错误处理，不替调用方挑一个。
fp_one()
{
    [ -n "$1" ] && [ -z "$2" ] && return 0
    [ -z "$1" ] && [ -n "$2" ] && return 0
    return 1
}

# 解析参数。--arch 必填，两对取件形式各恰好给一个：缺一个就无法构成判据，
# 按用法错误退 2，不拿缺省值猜，否则固件缺失会被读成「没有固件请求」而假绿。
#
# 可重复的选项（--firmware-rpm）先落到临时目录里的清单文件，再以文件是否
# 存在判断「给没给」：POSIX sh 没有数组，用字符串拼接会在路径含空白时断词，
# 而这份清单每行恰好一个值，读回来还能保持原样。
fp_parse()
{
    fp_fw=
    fp_mods=
    fp_modrpm=
    fp_arch=
    fp_reqs=
    fp_exempts=
    fp_tmp=$(mktemp -d) || exit "${FP_FAIL}"
    trap 'rm -rf "${fp_tmp}"' EXIT INT TERM
    : >"${fp_tmp}/fwrpm.list"
    while [ "$#" -gt 0 ]; do
        case "$1" in
        -h | --help) fp_usage; exit 0 ;;
        --firmware | --firmware-rpm | --modules | --modules-rpm | \
            --arch | --requests | --exempt) ;;
        *) fp_usage >&2; exit "${FP_USE}" ;;
        esac
        [ "$#" -ge 2 ] || { fp_usage >&2; exit "${FP_USE}"; }
        case "$1" in
        --firmware) fp_fw=$2 ;;
        --firmware-rpm) printf '%s\n' "$2" >>"${fp_tmp}/fwrpm.list" ;;
        --modules) fp_mods=$2 ;;
        --modules-rpm) fp_modrpm=$2 ;;
        --arch) fp_arch=$2 ;;
        --requests) fp_reqs=$2 ;;
        --exempt) fp_exempts=$2 ;;
        esac
        shift 2
    done
    fp_fwrpm="${fp_tmp}/fwrpm.list"
    [ -s "${fp_fwrpm}" ] || fp_fwrpm=
    if [ -z "${fp_arch}" ] ||
        ! fp_one "${fp_fw}" "${fp_fwrpm}" ||
        ! fp_one "${fp_mods}" "${fp_modrpm}"
    then
        fp_usage >&2
        exit "${FP_USE}"
    fi
    [ -z "${fp_exempts}" ] || [ -r "${fp_exempts}" ] ||
        { fp_usage >&2; exit "${FP_USE}"; }
}

# fp_tree LIST ROOT —— 按名字集建空文件骨架。目录条目（以 / 结尾）与绝对
# 路径跳过：前者不是可请求的固件，后者不落在固件根之下，建了也索引不到。
#
# 两遍建，且失败不再静默中止。一遍边建目录边建文件时，只要名字集里同时有
# `a/b` 与 `a/b/c`（固件包用目录符号链接表达布局时就是这样），先落的
# `a/b` 是普通文件，后一条建目录直接 ENOTDIR，预演在第一条冲突处中止，
# 日志只剩 fail=no-tree——哪个名字、哪一步、什么错误都没留下（run
# 42783532965 四架构同时复现，只能靠猜）。两遍之后目录先成型，冲突只影响
# 那一个名字；判据仍是 fw-flat 的 miss 计数，这里不另立一套。
#
# 名字既是文件又是目录时以目录为准，与真树一致：符号链接指向目录的条目在
# `find -type f` 里本来就不出现，骨架照此丢弃才与装机后的索引同形。
# 其余失败（空间不足、权限、名字超长）计入 ft_bad 并报出首条原文。
fp_tree()
{
    [ -r "$1" ] || return 1
    mkdir -p "$2" 2>/dev/null || return 1
    ft_names=0
    ft_bad=0
    ft_why=
    for ft_step in dir file; do
        while IFS= read -r ft_rel; do
            [ -n "${ft_rel}" ] || continue
            case "${ft_rel}" in
            /* | */) continue ;;
            esac
            if [ "${ft_step}" = dir ]; then
                ft_names=$(( ft_names + 1 ))
                ft_err=$( { mkdir -p "$2/$(dirname "${ft_rel}")"; } 2>&1 ) &&
                    continue
            else
                ft_err=$( { : >"$2/${ft_rel}"; } 2>&1 ) && continue
                # 目录已经占了同名位置：真树里这是指向目录的符号链接，
                # 它不进 find -type f 的索引，骨架也不该留下同名空文件。
                [ -d "$2/${ft_rel}" ] && continue
            fi
            ft_bad=$(( ft_bad + 1 ))
            [ -n "${ft_why}" ] || ft_why="${ft_step}:${ft_rel}:${ft_err}"
        done <"$1"
    done
    [ "${ft_bad}" -eq 0 ]
}

# fp_report TEXT —— 取 fw-flat 的结论行，并把逐条证据原样转出。
#
# 判定只读 fw-flat 的 miss 计数，不在这里重算：豁免表已由 fw-flat 自己
# 消费（同一个 --exempt、同一份表，与装机期 %posttrans 是同一条路径）。
# 此前预演在本地再把 miss 过一遍豁免表，等于同一份台账养了两套判据——run
# 42960420278 里预演按表放行，目标机却把 107 条不支持器件计成缺件，T26
# 必红。判据留在实现里一处，才谈得上「预演绿了装机也绿」。
#
# 只认最后一条 flat= 行：重复调用时早期故障行不代表本轮结论。exempt 计数
# 照样打进结论行，因为它决定「miss=0」是「都补齐了」还是「都豁免掉了」。
fp_report()
{
    fr_sum=$(printf '%s\n' "$1" | awk '/^flat=[0-9]+ miss=[0-9]+/ { s = $0 } END { print s }')
    if [ -z "${fr_sum}" ]; then
        # 按第一个空格切出 fail= 的值，不用 -F=：fw-flat 的失败行后面还跟
        # 字段，-F= 会在第二个等号处截断，把 `fail=no-requests reason=no-dir`
        # 读成「no-requests reason」这种半截话（run 42786640102 的
        # fail=no-requests modules 就是这么来的）。
        fr_fail=$(printf '%s\n' "$1" | sed -n 's/^fail=\([^ ]*\).*/\1/p' |
            head -1)
        printf 'AIRYMAX-FW-PREFLIGHT arch=%s fail=%s modules=%s\n' \
            "${fp_arch}" "${fr_fail:-unknown}" "${fp_mods}"
        # fw-flat 的失败行与 diag 行原样留下：预演的结论要能被下一轮直接
        # 用来定位，而不是只留一个分类名。
        printf '%s\n' "$1" | awk '/^(fail=|diag )/ { print }' >&2
        exit "${FP_FAIL}"
    fi
    fr_flat=$(printf '%s\n' "${fr_sum}" | sed 's/^flat=\([0-9]*\) .*/\1/')
    fr_miss=$(printf '%s\n' "${fr_sum}" | sed 's/^.* miss=\([0-9]*\).*/\1/')
    fr_exm=$(printf '%s\n' "${fr_sum}" |
        sed -n 's/^.* exempt=\([0-9]*\).*/\1/p')
    # 逐条证据原样转出：下一轮看日志的人要能分辨「这 0 是都补齐了」还是
    # 「都豁免掉了」，只有计数说不清。
    printf '%s\n' "$1" | awk '/^(miss|exempt) / { print }' >&2
    printf 'AIRYMAX-FW-PREFLIGHT arch=%s flat=%s miss=%s exempt=%s\n' \
        "${fp_arch}" "${fr_flat}" "${fr_miss}" "${fr_exm:-0}"
    [ "${fr_miss}" -eq 0 ] || exit "${FP_FAIL}"
}

# fp_fw_list RPMS OUT —— 固件名字集从 RPM 的文件清单生成。只取
# /usr/lib/firmware 之下的条目并去掉该前缀：骨架按相对路径建，前缀留着会
# 让每个名字都变成绝对路径而被 fp_tree 整批跳过。
#
# RPMS 是清单文件而不是单个包：镜像里的固件树是几个包的并集，linux-firmware
# 之外还有 wireless-regdb 这类小包。只读其中一个包，另一个包的条目就会在
# 判定里显示为「缺件」——run 42797570216 的 regulatory.db/regulatory.db.p7s
# 正是这么来的，而镜像里它们由 wireless-regdb 提供。
fp_fw_list()
{
    command -v "${FP_RPM}" >/dev/null 2>&1 || return 3
    : >"$2"
    while IFS= read -r ffl_rpm; do
        [ -n "${ffl_rpm}" ] || continue
        # 管道放进条件里：set -e 下直接失败会终止脚本，调用方拿不到返回码。
        if ! "${FP_RPM}" -qlp "${ffl_rpm}" 2>/dev/null |
            sed -n 's|^/usr/lib/firmware/||p' >>"$2"; then
            return 1
        fi
    done <"$1"
    [ -s "$2" ] || return 1
}

# fp_mod_diag TEXT —— 解包失败的证据走 stderr。容器日志会原样留下它，而
# 只落在被丢掉的变量里等于没写：run 42790132617 四个架构都只剩一行
# fail=no-modfiles，包坏、工具坏、还是包里本来就没文件，无从分辨。
fp_mod_diag()
{
    printf 'diag %s\n' "$*" >&2
}

# fp_mod_tree RPM OUT —— 把模块包解到 OUT，返回模块根。用 cpio 直接解而
# 不装包：预演只要 *.ko* 里的 MODULE_FIRMWARE()，装进主机反而会覆盖正在
# 运行的内核模块。
#
# 解出目录但一个文件都没有（返回 6）与「解包本身失败」（返回 1）必须分开：
# 前者要么是包真的只有目录，要么是工具链吃不下该包的载荷压缩；后者是
# cpio 报了错。两种情况修法完全不同，而此前它们都收束成同一个 fail=。
fp_mod_tree()
{
    install -d "$2" || return 1
    fp_mod_tools || return $?
    fp_mod_extract "$1" "$2" || return 1
    [ -d "$2/usr/lib/modules" ] || return 5
    fm_files=$(find "$2/usr/lib/modules" -type f 2>/dev/null | wc -l)
    [ "${fm_files}" -eq 0 ] || return 0
    fp_mod_empty "$1" "$2"
    return 6
}

# fp_mod_tools —— 解包所需的三个工具都在：rpm2cpio(3)、cpio(4)、find(7)。
#
# find 缺席时上面的计数会读成 0 个文件，看起来就像「包里只有目录」。工具缺
# 与包缺必须各有名字，否则每轮都得从头猜一遍。
fp_mod_tools()
{
    command -v "${FP_RPM2CPIO}" >/dev/null 2>&1 || return 3
    command -v "${FP_CPIO}" >/dev/null 2>&1 || return 4
    command -v find >/dev/null 2>&1 || {
        fp_mod_diag "no-find path=${PATH}"
        return 7
    }
}

# fp_mod_extract RPM OUT —— rpm2cpio | cpio 直接解到 OUT，失败时留下证据。
#
# 管道放进 if 条件里：set -e 下普通管道失败会直接终止脚本，下面的 fm_rc=$?
# 永远拿不到非零值，cpio 的错误原文也随 stderr 重定向一起丢掉。这就是
# run 42790132617 只留下一个分类名的原因之一。
fp_mod_extract()
{
    fm_err="$2.err"
    if "${FP_RPM2CPIO}" "$1" 2>"${fm_err}.rpm" |
        (cd "$2" && "${FP_CPIO}" -idm --quiet 2>"${fm_err}.cpio")
    then
        return 0
    else
        fm_rc=$?
    fi
    fp_mod_diag "extract rc=${fm_rc} cpio=$("${FP_CPIO}" --version 2>&1 |
        sed -n '1p')"
    fp_mod_diag "rpm2cpio-err=$(sed -n '1,2p' "${fm_err}.rpm" 2>/dev/null |
        tr '\n' ' ')"
    fp_mod_diag "cpio-err=$(sed -n '1,2p' "${fm_err}.cpio" 2>/dev/null |
        tr '\n' ' ')"
    return 1
}

# fp_mod_empty RPM OUT —— 目录建起来了、文件却一个都没有：包自己怎么说、
# 树里剩下什么、哪件工具不在，三样一起留下。此前只报 no-modfiles，包空、
# 工具缺、还是 find 不在，读日志的人无从分辨（run 42790132617 四架构同形）。
fp_mod_empty()
{
    fm_err="$2.err"
    fp_mod_diag "no-files files=${fm_files} dirs=$(find "$2/usr/lib/modules" \
        -type d 2>/dev/null | wc -l) top=$(find "$2/usr/lib/modules" \
        -mindepth 1 2>/dev/null | sed -n '1p;2p;3p' | tr '\n' ' ')"
    fp_mod_diag "tools find=$(command -v find || echo none) \
cpio=$(command -v "${FP_CPIO}" || echo none) \
rpm2cpio=$(command -v "${FP_RPM2CPIO}" || echo none)"
    fp_mod_diag "cpio-err=$(sed -n '1,2p' "${fm_err}.cpio" 2>/dev/null |
        tr '\n' ' ')"
    if command -v rpm >/dev/null 2>&1; then
        fm_qf='%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}'
        fm_qf="${fm_qf} %{PAYLOADCOMPRESSOR}/%{PAYLOADFORMAT}"
        fm_id=$(rpm -qp --qf "${fm_qf}" "$1" 2>/dev/null) || :
        fm_n=$(rpm -qlp "$1" 2>/dev/null | wc -l) || :
        fp_mod_diag "rpm=${fm_id} files=${fm_n}"
    fi
    rm -f "${fm_err}.rpm" "${fm_err}.cpio"
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
            6) fp_rc=no-modfiles ;;
            7) fp_rc=no-find ;;
            *) fp_rc=no-modules ;;
            esac
            printf 'AIRYMAX-FW-PREFLIGHT arch=%s fail=%s rpm=%s\n' \
                "${fp_arch}" "${fp_rc}" "${fp_modrpm}"
            exit "${FP_FAIL}"
        fi
        fp_mods="${fp_tmp}/mods/usr/lib/modules"
    fi
    if ! fp_tree "${fp_fw}" "${fp_tmp}/root"; then
        printf 'AIRYMAX-FW-PREFLIGHT arch=%s fail=no-tree names=%s bad=%s firmware=%s\n' \
            "${fp_arch}" "${ft_names:-0}" "${ft_bad:-0}" "${fp_fw}"
        printf 'tree %s\n' "${ft_why:-unknown}" >&2
        exit "${FP_FAIL}"
    fi
    set -- apply "${fp_tmp}/root" --list "${fp_tmp}/flat.list" \
        --modules "${fp_mods}"
    [ -z "${fp_reqs}" ] || set -- "$@" --requests "${fp_reqs}"
    # 豁免表交给补链实现去消费，预演不另判一套：装机期 %posttrans 与这里
    # 读的是同一份表，判据才可能一致。
    [ -z "${fp_exempts}" ] || set -- "$@" --exempt "${fp_exempts}"
    fp_out=$(sh "${fp_conf}" "$@" 2>&1) || :
    fp_report "${fp_out}"
}

fp_main "$@"
