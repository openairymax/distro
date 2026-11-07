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
# 两种动词：
#   apply ORIGIN --list FILE [--modules DIR] [--requests FILE]
#       缺入口的扁平请求逐个补软链，并把自己补了哪些写进 FILE（清单）。
#   check ORIGIN --list FILE
#       按清单复核每条软链仍指向原目标；基线后来自己提供了同名文件也算
#       满足（此时不再需要软链）。
#
# 链接在安装事务里生成而不是打进包体：目标文件属 linux-firmware，若把
# 链接作为包的文件声明，同一路径会被两个包持有，dnf 事务直接失败。
# 由 %%posttrans 调用而非 %%post：rpm 按包顺序执行「装文件→%%post」，
# 固件包先于 linux-firmware 落地时 %%post 看不到目标文件，只能静默跳过。
#
# 本脚本按 POSIX sh 写：安装期由 `sh` 调用，不保证解释器是 bash，故不用
# local 等非 POSIX 扩展。函数之间只用带前缀的全局变量，前缀保证调用方
# 与被调方不会互相覆盖。
#
# 退出码：0 成功；1 复核失败或读写失败；2 用法错误。
# ===========================================================================
set -eu

E_FAIL=1
E_USE=2

VERB=${1:-}
ORIGIN=${2:-}
shift 2 2>/dev/null || true

LIST=""
MODULES="/usr/lib/modules"
REQFILE=""

usage()
{
    printf '%s\n' \
        '用法: fw-flat.sh apply|check ORIGIN --list FILE [选项]' \
        '' \
        '  apply          为缺扁平入口的请求补软链，并把补的条目写进 FILE' \
        '  check          按 FILE 复核软链与目标' \
        '  ORIGIN         固件根（如 /usr/lib/firmware）' \
        '  --list FILE    清单路径（apply 写、check 读，必填）' \
        '  --modules DIR  模块树根，缺省 /usr/lib/modules' \
        '  --requests F   请求名清单，缺省用 modinfo 从模块树读取'
}

while [ "$#" -gt 0 ]; do
    case "$1" in
    --list) LIST=${2:-}; shift 2 ;;
    --modules) MODULES=${2:-}; shift 2 ;;
    --requests) REQFILE=${2:-}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit "${E_USE}" ;;
    esac
done

case "${VERB}" in
apply|check) ;;
*)
    usage >&2
    exit "${E_USE}"
    ;;
esac
if [ -z "${ORIGIN}" ] || [ -z "${LIST}" ] || [ ! -d "${ORIGIN}" ]; then
    usage >&2
    exit "${E_USE}"
fi

# requests —— 驱动声明的固件名，一行一个，去重保序。
# modinfo 一次可读多个模块，按批传参避免命令行超限；只读 .modinfo 段，
# 不执行模块。读不到模块树时返回 2，由调用方决定是报错还是静默。
requests()
{
    if [ -n "${REQFILE}" ]; then
        [ -r "${REQFILE}" ] || return 2
        awk 'NF' "${REQFILE}"
        return 0
    fi
    [ -d "${MODULES}" ] || return 2
    command -v modinfo >/dev/null 2>&1 || return 2
    find "${MODULES}" -type f \( -name '*.ko' -o -name '*.ko.xz' \
        -o -name '*.ko.zst' -o -name '*.ko.gz' \) -print0 2>/dev/null |
        xargs -0 -r -n 64 modinfo -F firmware 2>/dev/null |
        awk 'NF' | sort -u
}

# missing NAME —— 该请求名在固件根上缺入口时，打印安装树内的候选相对
# 路径（字符最短优先）。返回 0 表示缺入口；1 表示已有入口；3 表示缺入口
# 且树内也没有同名文件（无从补起）。结果经 mf_hit 交回调用方。
missing()
{
    mf_hit=""

    if [ -e "${ORIGIN}/$1" ]; then
        return 1
    fi
    mf_hit=$(find "${ORIGIN}" -type f -path "*/$1" -print 2>/dev/null |
        awk '{ print length($0) " " $0 }' | sort -n -k1,1 |
        awk 'NR == 1 { $1 = ""; sub(/^ /, ""); print }')
    if [ -z "${mf_hit}" ]; then
        return 3
    fi
    printf '%s\n' "${mf_hit#"${ORIGIN}"/}"
}

apply_run()
{
    ap_tmp="${LIST}.tmp.$$"
    ap_reqs="${ap_tmp}.reqs"
    ap_links=0
    ap_miss=0

    : >"${ap_tmp}"
    if ! requests >"${ap_reqs}"; then
        rm -f "${ap_tmp}" "${ap_reqs}"
        printf 'fail=no-requests modules=%s\n' "${MODULES}" >&2
        return "${E_FAIL}"
    fi
    while IFS= read -r ap_name; do
        case "${ap_name}" in
        ''|*/*) continue ;;
        esac
        ap_rc=0
        ap_rel=$(missing "${ap_name}") || ap_rc=$?
        case "${ap_rc}" in
        1) continue ;;
        3)
            # 请求名在树内也没有同名文件：不是布局问题而是固件缺失。这里
            # 不失败（脚本节不能阻断安装），但必须在安装日志里留一行判据，
            # 否则现场只会看到驱动 "no suitable firmware found"。
            printf 'miss name=%s\n' "${ap_name}" >&2
            ap_miss=$(( ap_miss + 1 ))
            continue
            ;;
        esac
        if ! ln -s "${ap_rel}" "${ORIGIN}/${ap_name}" 2>/dev/null; then
            ap_miss=$(( ap_miss + 1 ))
            continue
        fi
        printf '%s %s\n' "${ap_name}" "${ap_rel}" >>"${ap_tmp}"
        ap_links=$(( ap_links + 1 ))
    done <"${ap_reqs}"
    rm -f "${ap_reqs}"
    if ! mv "${ap_tmp}" "${LIST}" 2>/dev/null; then
        rm -f "${ap_tmp}"
        printf 'fail=write-list list=%s\n' "${LIST}" >&2
        return "${E_FAIL}"
    fi
    printf 'flat=%d miss=%d list=%s\n' "${ap_links}" "${ap_miss}" "${LIST}"
}

check_run()
{
    ck_bad=0
    ck_rows=0

    if [ ! -r "${LIST}" ]; then
        printf 'fail=no-list list=%s\n' "${LIST}" >&2
        return "${E_FAIL}"
    fi
    while IFS=' ' read -r ck_name ck_rel; do
        [ -n "${ck_name}" ] || continue
        ck_rows=$(( ck_rows + 1 ))
        if [ ! -e "${ORIGIN}/${ck_rel}" ]; then
            printf 'fail=no-target name=%s target=%s\n' \
                "${ck_name}" "${ck_rel}" >&2
            ck_bad=$(( ck_bad + 1 ))
            continue
        fi
        if [ -L "${ORIGIN}/${ck_name}" ]; then
            if [ "$(readlink "${ORIGIN}/${ck_name}")" != "${ck_rel}" ]; then
                printf 'fail=wrong-link name=%s target=%s\n' \
                    "${ck_name}" "${ck_rel}" >&2
                ck_bad=$(( ck_bad + 1 ))
            fi
        elif [ ! -e "${ORIGIN}/${ck_name}" ]; then
            printf 'fail=no-entry name=%s target=%s\n' \
                "${ck_name}" "${ck_rel}" >&2
            ck_bad=$(( ck_bad + 1 ))
        fi
    done <"${LIST}"
    printf 'rows=%d bad=%d list=%s\n' "${ck_rows}" "${ck_bad}" "${LIST}"
    [ "${ck_bad}" -eq 0 ] || return "${E_FAIL}"
}

if [ "${VERB}" = apply ]; then
    apply_run
else
    check_run
fi
