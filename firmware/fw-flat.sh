#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# fw-flat.sh — 按驱动实际请求名补齐固件扁平入口
#
# 为什么需要这一层：固件的安装布局与内核的请求名是两套口径。基底
# openEuler 24.03 LTS-SP3 已按上游新布局把厂商固件放进子目录
# （intel/iwlwifi/、brcm/、ath11k/ ……），而部分驱动仍按裸文件名请求
# （iwlwifi 的 `modinfo -F firmware` 全部是 iwlwifi-<家族>-<版本>.ucode
# 与 .pnvm，没有任何目录前缀）。两者的交集为空时，驱动逐个文件报
# "Direct firmware load ... failed with error -2"，收束于 "no suitable
# firmware found"；此时设备枚举得到、rfkill 全开、固件包也装了，只有
# NetworkManager 报「未发现 Wi-Fi 设备」。2026-11-06 在 285H（BE200，
# 8086:272b）上以补齐 13 个扁平链接做加减对照复现并闭环。
#
# 为什么由请求名驱动，而不是列厂商目录：列目录只能修已知的那一块网卡。
# brcmfmac、ath11k、mt76、rtw88、i915、amdgpu 都存在同类可能，ARM 与
# RISC-V 的主用无线更不在 intel/ 下。请求名是驱动自己声明的（模块的
# .modinfo 段），按它反查安装树，三架构、全厂商走同一条路径，不再需要
# 维护任何厂商常量。这是本脚本存在的唯一理由。
#
# 压缩后缀：0.0.4 首烧复现的另一半。安装器 live 环境的固件树是 SP3 布局，
# intel/iwlwifi/ 下 165 个文件全是 .ucode.zst，未压缩的 0 个，而驱动请求
# 的仍是裸名。本内核配了 CONFIG_FW_LOADER_COMPRESS_{ZSTD,XZ}，取不到裸名
# 时按 <name>.zst、<name>.xz 在同一路径再各取一次
# （kernel/drivers/base/firmware_loader/main.c 的 assign_fw）。因此入口名
# 必须带真实后缀（x.ucode.zst -> intel/iwlwifi/x.ucode.zst）；补成无后缀
# 的链会让内核第一次尝试就读取压缩流并按裸文件解析，等于没补。
#
# 豁免表：驱动声明的请求名里，有一部分属于本发行版硬件矩阵不支持的器件
# （iwlwifi 一个模块就声明了 BZ/MA/SC/SO 各族 Wi-Fi 7 网卡的固件名）。它们
# 在固件树里确实没有，但不是打包失误，判据要能把「不支持」与「缺失」分开。
# 表由 distro/firmware/fw-exempt.txt 出，构建期预演与装机补链读同一份：
# 0.0.4 验收（run 42960420278）里预演按表放行、目标机 %%posttrans 却把 107
# 条不支持器件计成缺件，T26 因此必红——一处事实两套判据，修法只能是收敛到
# 一个实现，不是给计数放宽阈值。未给 --exempt 时全部请求名按缺失处理。
#
# 两种使用形态：
#   ① 命令行：fw-flat.sh apply|check ORIGIN --list FILE [选项]
#   ② 被安装配方嵌入：正文由构建期的嵌入标记展开进 kickstart 脚本段后
#      调用 fw_flat_main apply|check ...。安装器 live 环境没有本包，
#      同一套规则只能用嵌入，故正文除函数定义外不解析位置参数，末尾
#      按 $0 判定是否作为脚本运行。
#
# 为什么先建索引再查表：请求名数十条，逐条 find 整棵树是 O(请求数 ×
# 树规模)；一次 find 建「逻辑名 → 相对路径」索引，之后每请求一次查表。
# 树内同名文件按「未压缩 → .zst → .xz」与相对路径最短取一条，结论不随
# find 顺序漂移。
#
# 链接在安装事务里生成而不是打进包体：目标文件属 linux-firmware，若把
# 链接作为包的文件声明，同一路径会被两个包持有，dnf 事务直接失败。
# 由 %%posttrans 调用而非 %%post：rpm 按包顺序执行「装文件→%%post」，
# 固件包先于 linux-firmware 落地时 %%post 看不到目标文件，只能静默跳过。
#
# 本脚本按 POSIX sh 写：安装期由 `sh` 调用，不保证解释器是 bash，故不用
# local 等非 POSIX 扩展。函数与全局变量统一带 ff_/fw_flat_ 前缀，嵌入到
# 装机的脚本段后不会与 install-lib.sh、disk-select.sh 互相覆盖。
#
# 退出码：0 成功；1 请求集为空、复核失败或读写失败；2 用法错误。
# ===========================================================================
set -eu

FWFLAT_FAIL=1
FWFLAT_USE=2

fw_flat_usage()
{
    printf '%s\n' \
        '用法: fw-flat.sh apply|check ORIGIN --list FILE [选项]' \
        '' \
        '  apply          为缺扁平入口的请求补软链，并把补的条目写进 FILE' \
        '  check          按 FILE 复核软链与目标' \
        '  ORIGIN         固件根（如 /usr/lib/firmware）' \
        '  --list FILE    清单路径（apply 写、check 读，必填）' \
        '  --modules DIR  模块树根，缺省 /usr/lib/modules' \
        '  --requests F   请求名清单，缺省用 modinfo 从模块树读取' \
        '  --exempt FILE  豁免表：每行 <名字通配> <原因>，命中的缺件不计入 miss'
}

# fw_flat_requests —— 驱动声明的固件名，一行一个，去重保序。
# modinfo 一次可读多个模块，按批传参避免命令行超限；只读 .modinfo 段，
# 不执行模块。读不到模块树时返回 2，由调用方决定是报错还是静默。
#
# 失败原因留在 fwfr_why，并由 fwfr_diag 逐条写进 stderr：模块树没解出来、
# 构建机没有 modinfo、模块全是没认出的压缩后缀，这三种在日志里原本都是
# 同一个 fail=no-requests，构建期预演每轮只能靠猜（run 42786640102 四架构
# 同形，15 秒一个）。
fwfr_diag()
{
    printf 'diag %s\n' "$*" >&2
}

fw_flat_requests()
{
    fwfr_why=
    if [ -n "${ff_reqfile}" ]; then
        [ -r "${ff_reqfile}" ] || { fwfr_why=no-reqfile; return 2; }
        awk 'NF' "${ff_reqfile}"
        return 0
    fi
    [ -d "${ff_modules}" ] || { fwfr_why=no-dir; return 2; }
    # modinfo 在部分镜像里只落在 sbin，而调用方的 PATH 未必含它：先按
    # 名字找，找不到再按固定路径找，两条都不通才算「没有 modinfo」。
    fwfr_mi=modinfo
    if ! command -v "${fwfr_mi}" >/dev/null 2>&1; then
        for fwfr_mi in /usr/sbin/modinfo /sbin/modinfo; do
            [ -x "${fwfr_mi}" ] && break
        done
        [ -x "${fwfr_mi}" ] || { fwfr_why=no-modinfo; return 2; }
    fi
    fwfr_tmp="${TMPDIR:-/tmp}/fw-flat.$$"
    find "${ff_modules}" -type f \( -name '*.ko' -o -name '*.ko.xz' \
        -o -name '*.ko.zst' -o -name '*.ko.gz' \) -print0 2>/dev/null \
        >"${fwfr_tmp}.mods"
    fwfr_n=$(tr -cd '\0' <"${fwfr_tmp}.mods" | wc -c)
    if [ "${fwfr_n}" -eq 0 ]; then
        fwfr_why=no-modfiles
        fwfr_diag "no-modfiles dir=${ff_modules} sample=$(find "${ff_modules}" \
            -type f 2>/dev/null | sed -n '1p;2p;3p' | tr '\n' ' ')"
        rm -f "${fwfr_tmp}.mods"
        return 2
    fi
    xargs -0 -r -n 64 "${fwfr_mi}" -F firmware <"${fwfr_tmp}.mods" \
        >"${fwfr_tmp}.out" 2>"${fwfr_tmp}.err"
    if [ ! -s "${fwfr_tmp}.out" ]; then
        fwfr_diag "modinfo-empty mods=${fwfr_n} ver=$("${fwfr_mi}" -V 2>&1 |
            head -1) err=$(head -1 "${fwfr_tmp}.err" 2>/dev/null)"
        fwfr_diag "sample=$(tr '\0' '\n' <"${fwfr_tmp}.mods" |
            sed -n '1p;2p;3p' | tr '\n' ' ')"
    fi
    awk 'NF' "${fwfr_tmp}.out" | sort -u
    rm -f "${fwfr_tmp}.mods" "${fwfr_tmp}.out" "${fwfr_tmp}.err"
}

# fw_flat_index ORIGIN DEST —— 建立「逻辑名 → 树内相对路径」索引。
# 逻辑名是文件名去掉压缩后缀后的形态，即驱动的请求名；值保留真实相对
# 路径，后缀随值一起带到入口名上。
fw_flat_index()
{
    fi_root=$1
    while [ "${fi_root%/}" != "${fi_root}" ] && [ -n "${fi_root%/}" ]; do
        fi_root=${fi_root%/}
    done
    find "${fi_root}" -type f -print 2>/dev/null |
        awk -v root="${fi_root}/" '
            index($0, root) == 1 {
                rel = substr($0, length(root) + 1)
                name = rel
                sub(/.*\//, "", name)
                rank = 0
                if (name ~ /\.zst$/) { rank = 1; sub(/\.zst$/, "", name) }
                else if (name ~ /\.xz$/) { rank = 2; sub(/\.xz$/, "", name) }
                print name, rel, rank, length(rel)
            }' |
        sort -k1,1 -k3,3n -k4,4n -k2,2 |
        awk '!seen[$1]++ { print $1, $2 }' >"$2"
}

# fw_flat_lookup INDEX NAME —— 打印 NAME 对应的相对路径；查不到则空。
fw_flat_lookup()
{
    awk -v key="$2" '$1 == key { print $2; exit }' "$1"
}

# fw_flat_exempt NAME —— 缺件是否在豁免表里，命中时把原因写进 fwe_why。
#
# 表里一行是 <名字通配> <原因>。豁免只对「驱动会请求、但本发行版不支持那类
# 器件」成立；名字本身写错、或链建不起来，仍然计 miss——豁免的是硬件矩阵的
# 边界，不是实现故障。
fw_flat_exempt()
{
    fwe_why=
    [ -n "${ff_exempt}" ] || return 1
    while IFS= read -r fwe_line; do
        case "${fwe_line}" in
        '' | '#'*) continue ;;
        esac
        fwe_pat=${fwe_line%%[[:space:]]*}
        fwe_why=${fwe_line#"${fwe_pat}"}
        # 表里为了让通配对齐写了连续空格，reason= 不该带这串空白。
        fwe_why=${fwe_why#"${fwe_why%%[! ]*}"}
        # fwe_pat 不引号展开：表里写的是通配，要按通配匹配。
        # shellcheck disable=SC2254
        case "$1" in
        ${fwe_pat}) return 0 ;;
        esac
    done <"${ff_exempt}"
    fwe_why=
    return 1
}

fw_flat_apply()
{
    ff_tmp="${ff_list}.tmp.$$"
    ff_reqs="${ff_tmp}.reqs"
    ff_idx="${ff_tmp}.idx"
    ff_links=0
    ff_miss=0
    ff_exm=0

    : >"${ff_tmp}"
    if ! fw_flat_requests >"${ff_reqs}"; then
        rm -f "${ff_tmp}" "${ff_reqs}"
        printf 'fail=no-requests modules=%s reason=%s\n' \
            "${ff_modules}" "${fwfr_why:-unknown}" >&2
        return "${FWFLAT_FAIL}"
    fi
    # 空请求集不是「无需补齐」，而是输入坏了：模块树没解出来、modinfo 缺席
    # 或请求名清单是空文件。此时继续走会得到 flat=0 miss=0，判定假绿——
    # 这正是构建期预演最需要拦的那一种形态，所以在此如实判负。
    if [ ! -s "${ff_reqs}" ]; then
        rm -f "${ff_tmp}" "${ff_reqs}"
        printf 'fail=no-requests modules=%s reason=empty\n' "${ff_modules}" >&2
        return "${FWFLAT_FAIL}"
    fi
    if ! fw_flat_index "${ff_origin}" "${ff_idx}"; then
        rm -f "${ff_tmp}" "${ff_reqs}" "${ff_idx}"
        printf 'fail=no-index origin=%s\n' "${ff_origin}" >&2
        return "${FWFLAT_FAIL}"
    fi

    while IFS= read -r ff_name; do
        case "${ff_name}" in
        '' | */*) continue ;;
        esac
        # 已有入口（基线实体文件，或前一轮补的链）：不动，也不计入本轮。
        if [ -e "${ff_origin}/${ff_name}" ]; then
            continue
        fi
        ff_rel=$(fw_flat_lookup "${ff_idx}" "${ff_name}") || ff_rel=
        if [ -z "${ff_rel}" ]; then
            # 请求名在树内也没有同名文件。先过豁免表：命中的是本版硬件矩阵
            # 之外的器件，逐条留证据但不计入 miss；未命中才是真的缺件。
            if fw_flat_exempt "${ff_name}"; then
                printf 'exempt name=%s reason=%s\n' \
                    "${ff_name}" "${fwe_why}" >&2
                ff_exm=$(( ff_exm + 1 ))
                continue
            fi
            # 不失败（脚本节不能阻断安装），但必须在安装日志里留一行判据，
            # 否则现场只会看到驱动 "no suitable firmware found"。
            printf 'miss name=%s\n' "${ff_name}" >&2
            ff_miss=$(( ff_miss + 1 ))
            continue
        fi
        ff_link=${ff_rel##*/}
        if [ -e "${ff_origin}/${ff_link}" ]; then
            continue
        fi
        if ! ln -s "${ff_rel}" "${ff_origin}/${ff_link}" 2>/dev/null; then
            printf 'miss name=%s rel=%s\n' "${ff_name}" "${ff_rel}" >&2
            ff_miss=$(( ff_miss + 1 ))
            continue
        fi
        printf '%s %s\n' "${ff_link}" "${ff_rel}" >>"${ff_tmp}"
        ff_links=$(( ff_links + 1 ))
    done <"${ff_reqs}"
    rm -f "${ff_reqs}" "${ff_idx}"
    if ! mv "${ff_tmp}" "${ff_list}" 2>/dev/null; then
        rm -f "${ff_tmp}"
        printf 'fail=write-list list=%s\n' "${ff_list}" >&2
        return "${FWFLAT_FAIL}"
    fi
    printf 'flat=%d miss=%d exempt=%d list=%s\n' \
        "${ff_links}" "${ff_miss}" "${ff_exm}" "${ff_list}"
}

fw_flat_check()
{
    fk_bad=0
    fk_rows=0

    if [ ! -r "${ff_list}" ]; then
        printf 'fail=no-list list=%s\n' "${ff_list}" >&2
        return "${FWFLAT_FAIL}"
    fi
    while IFS=' ' read -r fk_name fk_rel; do
        [ -n "${fk_name}" ] || continue
        fk_rows=$(( fk_rows + 1 ))
        if [ ! -e "${ff_origin}/${fk_rel}" ]; then
            printf 'fail=no-target name=%s target=%s\n' \
                "${fk_name}" "${fk_rel}" >&2
            fk_bad=$(( fk_bad + 1 ))
            continue
        fi
        if [ -L "${ff_origin}/${fk_name}" ]; then
            if [ "$(readlink "${ff_origin}/${fk_name}")" != "${fk_rel}" ]; then
                printf 'fail=wrong-link name=%s target=%s\n' \
                    "${fk_name}" "${fk_rel}" >&2
                fk_bad=$(( fk_bad + 1 ))
            fi
        elif [ ! -e "${ff_origin}/${fk_name}" ]; then
            printf 'fail=no-entry name=%s target=%s\n' \
                "${fk_name}" "${fk_rel}" >&2
            fk_bad=$(( fk_bad + 1 ))
        fi
    done <"${ff_list}"
    printf 'rows=%d bad=%d list=%s\n' "${fk_rows}" "${fk_bad}" "${ff_list}"
    [ "${fk_bad}" -eq 0 ] || return "${FWFLAT_FAIL}"
}

fw_flat_main()
{
    if [ "$#" -lt 2 ]; then
        fw_flat_usage >&2
        return "${FWFLAT_USE}"
    fi
    ff_verb=$1
    ff_origin=$2
    shift 2

    ff_list=
    ff_modules=/usr/lib/modules
    ff_reqfile=
    ff_exempt=

    while [ "$#" -gt 0 ]; do
        case "$1" in
        -h | --help)
            fw_flat_usage
            return 0
            ;;
        --list | --modules | --requests | --exempt) ;;
        *)
            fw_flat_usage >&2
            return "${FWFLAT_USE}"
            ;;
        esac
        if [ "$#" -lt 2 ]; then
            fw_flat_usage >&2
            return "${FWFLAT_USE}"
        fi
        case "$1" in
        --list) ff_list=$2 ;;
        --modules) ff_modules=$2 ;;
        --requests) ff_reqfile=$2 ;;
        --exempt) ff_exempt=$2 ;;
        esac
        shift 2
    done

    case "${ff_verb}" in
    apply | check) ;;
    *)
        fw_flat_usage >&2
        return "${FWFLAT_USE}"
        ;;
    esac
    if [ -z "${ff_origin}" ] || [ -z "${ff_list}" ] ||
        [ ! -d "${ff_origin}" ]; then
        fw_flat_usage >&2
        return "${FWFLAT_USE}"
    fi
    # 豁免表缺席不阻断补链：缺的只是分类依据，链接本身照做。但要在日志里
    # 明说——没有表时每条请求名都会落成 miss，看起来像固件树塌了。
    if [ -n "${ff_exempt}" ] && [ ! -r "${ff_exempt}" ]; then
        printf 'diag exempt-unreadable path=%s\n' "${ff_exempt}" >&2
        ff_exempt=
    fi

    if [ "${ff_verb}" = apply ]; then
        fw_flat_apply
    else
        fw_flat_check
    fi
}

# 作为脚本运行时才执行；被 kickstart 段展开时 $0 是安装器的临时脚本，
# 不匹配，正文只留下函数定义。
case "${0##*/}" in
fw-flat.sh)
    fw_flat_main "$@" || exit $?
    ;;
esac
