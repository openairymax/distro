#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airy-flash.sh — AirymaxOS 安装介质烧录工具
#
# 职责（烧录方案 SSoT）：
#   check   校验镜像结构与摘要：ISO 9660 PVD、MBR 引导签名、sha256
#   plan    列出候选目标盘，标注 ready / refused / fixed 及依据
#   write   校验后写入目标盘，并立刻回读比对（写完即证）
#   verify  只回读比对，不写
#
# 设计口径：
#   - 不做 GUI。介质写入是一条约 3.4 GiB 的顺序写，图形工具带来的是
#     不可审计的黑盒；本工具输出结构化段落并落盘固定字段的记录文件，
#     作为「可复现烧录」的取证链（镜像摘要、目标序列号、字节数、
#     写入耗时、回读结论）。
#   - 三拒绝：分区不写、已挂载不写、系统盘不写；非 USB 介质必须显式
#     --allow-fixed，非交互环境必须显式 --yes。
#   - 设备身份以 lsblk（sysfs/udev）为准，不用 test -b：分区同样是块
#     设备，只有 sysfs 的 TYPE 能区分整盘与分区；容量取 blockdev 的字节数。
#   - 只做整盘镜像写入，不做分区/文件系统层面的猜测：ISO 是混合镜像，
#     写入后由固件按 El Torito 与 MBR 各自引导。
#
# 退出码：0 通过；2 用法；3 守卫拒绝；4 校验不符；5 环境不满足；6 读写失败。
# ===========================================================================
set -uo pipefail

readonly E_USAGE=2
readonly E_REFUSE=3
readonly E_MISMATCH=4
readonly E_ENV=5
readonly E_IO=6

readonly NAME="airy-flash"
readonly VERSION="0.0.3"
readonly TOOL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly DISTRO_ROOT="$(cd "${TOOL_ROOT}/../.." && pwd -P)"
readonly SECTOR=2048
readonly PVD_OFF=$((16 * SECTOR))

ISO=""
TARGET=""
EXPECT=""
OUT="${TMPDIR:-/tmp}/airy-flash"
YES=0
FIXED=0
DRY=0
QUIET=0
CMD=""

ISO_BYTES=0
ISO_SHA=""
DEV_PATH=""
DEV_BYTES=0
DEV_MODEL=""
DEV_SERIAL=""
DEV_REMOVABLE="no"
MOUNTS=""
ROOTDEV=""
WRITE_S=0
VERIFY="skipped"
WLOG=""
KIND=""

usage()
{
    cat <<'EOF'
用法: airy-flash.sh <子命令> [选项]

子命令:
  check   --iso PATH [--expect SHA]        校验镜像结构与摘要
  plan                                     列出候选目标盘与判定
  write   --iso PATH --target DEV [选项]    写入目标盘并回读比对
  verify  --iso PATH --target DEV          只回读比对

选项:
  --iso PATH        AirymaxOS ISO
  --target DEV      目标整盘（如 /dev/sdb），不接受分区
  --expect SHA      期望的镜像 sha256；缺省读同名 .sha256
  --out DIR         记录文件目录，缺省 $TMPDIR/airy-flash，须在源码区外
  --yes             跳过交互确认（非交互环境必需）
  --allow-fixed     允许写入非 USB 介质（内置盘，谨慎）
  --dry-run         只跑校验与守卫，不写入
  --quiet           不转发 dd 进度
  -h, --help        显示本帮助

退出码: 0 通过；2 用法；3 守卫拒绝；4 校验不符；5 环境不满足；
        6 读写失败。
EOF
}

die()
{
    printf '%s: %s\n' "${NAME}" "$2" >&2
    exit "$1"
}

sect()
{
    printf '\n== %s ==\n' "$1"
}

say()
{
    printf '  %-11s %s\n' "$1" "$2"
}

human()
{
    awk -v b="$1" 'BEGIN {
        split("B KiB MiB GiB TiB", unit, " ")
        i = 1
        while (b >= 1024 && i < 5) { b /= 1024; i++ }
        if (i == 1) printf "%d %s", b, unit[i]
        else printf "%.2f %s", b, unit[i]
    }'
}

oneline()
{
    local joined

    joined="$(printf '%s' "$1" | tr '\n' ' ')"
    printf '%s' "${joined% }"
}

hash_of()
{
    sha256sum "$1" 2>/dev/null | awk 'NR == 1 { print $1 }'
}

hash_head()
{
    head -c "$2" "$1" 2>/dev/null | sha256sum | awk 'NR == 1 { print $1 }'
}

iso_pvd()
{
    local magic

    magic="$(dd if="$1" bs=1 skip=$((PVD_OFF + 1)) count=5 \
        status=none 2>/dev/null | tr -d '\000')"
    [ "${magic}" = "CD001" ]
}

iso_mbr()
{
    local sig

    sig="$(dd if="$1" bs=1 skip=510 count=2 status=none 2>/dev/null |
        od -An -tx1 | tr -d ' \n')"
    [ "${sig}" = "55aa" ]
}

blk_get()
{
    lsblk -dnro "$2" "$1" 2>/dev/null | awk 'NR == 1 { print }'
}

mounts_of()
{
    lsblk -nrPo PATH,MOUNTPOINT 2>/dev/null |
        awk -v t="$1" '
            {
                if (!match($0, /PATH="[^"]*"/))
                    next
                p = substr($0, RSTART + 6, RLENGTH - 7)
                if (p != t) {
                    if (index(p, t) != 1)
                        next
                    if (substr(p, length(t) + 1) !~ /^p?[0-9]/)
                        next
                }
                if (!match($0, /MOUNTPOINT="[^"]*"/))
                    next
                mp = substr($0, RSTART + 12, RLENGTH - 13)
                if (mp != "")
                    print mp
            }'
}

is_sys_of()
{
    local dev="$1" suffix

    [ -n "${ROOTDEV}" ] || return 1
    [ "${ROOTDEV}" = "${dev}" ] && return 0
    suffix="${ROOTDEV#"${dev}"}"
    [ "${suffix}" != "${ROOTDEV}" ] || return 1
    case "${suffix}" in
    p[0-9]*|[0-9]*) return 0 ;;
    esac
    return 1
}

is_sys()
{
    is_sys_of "${DEV_PATH}"
}

check_iso()
{
    local want="${EXPECT}" side=""

    [ -n "${ISO}" ] || die "${E_USAGE}" "--iso 必填"
    [ -f "${ISO}" ] || die "${E_MISMATCH}" "镜像不存在: ${ISO}"
    ISO_BYTES="$(stat -c %s "${ISO}" 2>/dev/null)" ||
        die "${E_IO}" "无法读取镜像大小: ${ISO}"
    [ "${ISO_BYTES}" -gt "$((PVD_OFF + SECTOR))" ] ||
        die "${E_MISMATCH}" "镜像不足 ISO 9660 最小结构: ${ISO_BYTES} 字节"

    sect "image"
    say path "${ISO}"
    say bytes "$(human "${ISO_BYTES}") (${ISO_BYTES})"

    iso_pvd "${ISO}" || die "${E_MISMATCH}" \
        "缺少 ISO 9660 PVD：偏移 $((PVD_OFF + 1)) 处不是 CD001"
    say iso9660 "ok (CD001 at sector 16)"

    iso_mbr "${ISO}" || die "${E_MISMATCH}" \
        "缺少 MBR 引导签名：偏移 510 处不是 55AA，BIOS 无法引导"
    say mbr "ok (55AA at 510)"

    ISO_SHA="$(hash_of "${ISO}")"
    [ -n "${ISO_SHA}" ] || die "${E_IO}" "无法计算镜像 sha256"
    say sha256 "${ISO_SHA}"

    if [ -z "${want}" ] && [ -f "${ISO}.sha256" ]; then
        side="$(basename "${ISO}").sha256"
        want="$(awk 'NR == 1 { print $1 }' "${ISO}.sha256" 2>/dev/null)"
        [ -n "${want}" ] && say expect "${want} (from ${side})"
    fi
    if [ -z "${want}" ]; then
        say expect "未提供（--expect 或同名 .sha256）"
        say verdict "ok (结构通过，摘要未核对)"
        return 0
    fi
    [ "${want}" = "${ISO_SHA}" ] || die "${E_MISMATCH}" \
        "镜像摘要不符：实际 ${ISO_SHA}，期望 ${want}"
    say expect "${want} (matched)"
    say verdict "ok (结构与摘要均通过)"
}

dev_facts()
{
    local type

    DEV_PATH="$(readlink -f "${TARGET}" 2>/dev/null || printf '%s' "${TARGET}")"
    type="$(blk_get "${DEV_PATH}" TYPE)"
    [ -n "${type}" ] || die "${E_REFUSE}" "目标不是块设备: ${TARGET}"
    [ "${type}" = disk ] || die "${E_REFUSE}" \
        "目标不是整盘（分区不可写）: ${DEV_PATH}"
    DEV_BYTES="$(blockdev --getsize64 "${DEV_PATH}" 2>/dev/null)" ||
        die "${E_ENV}" "无法读取目标容量: ${DEV_PATH}"
    DEV_MODEL="$(blk_get "${DEV_PATH}" MODEL)"
    DEV_SERIAL="$(blk_get "${DEV_PATH}" SERIAL)"
    MOUNTS="$(mounts_of "${DEV_PATH}")"
    [ -n "${ROOTDEV}" ] || ROOTDEV="$(findmnt -nro SOURCE / 2>/dev/null)"
    if [ "$(blk_get "${DEV_PATH}" RM)" = 1 ] ||
            [ "$(blk_get "${DEV_PATH}" TRAN)" = usb ]; then
        DEV_REMOVABLE="yes"
    fi
}

mount_str()
{
    if [ -z "${MOUNTS}" ]; then
        printf 'no'
        return 0
    fi
    printf 'yes (%s)' "$(oneline "${MOUNTS}")"
}

show_facts()
{
    sect "target"
    say device "${DEV_PATH}"
    say model "${DEV_MODEL:-unknown}"
    say serial "${DEV_SERIAL:-none}"
    say bytes "$(human "${DEV_BYTES}") (${DEV_BYTES})"
    say removable "${DEV_REMOVABLE}"
    say mounted "$(mount_str)"
}

guard_target()
{
    dev_facts
    show_facts

    [ -z "${MOUNTS}" ] || die "${E_REFUSE}" \
        "目标或其分区已挂载，先卸载: $(oneline "${MOUNTS}")"
    if is_sys; then
        die "${E_REFUSE}" "目标是系统盘（承载 ${ROOTDEV}），拒绝写入"
    fi
    [ "${DEV_REMOVABLE}" = yes ] || [ "${FIXED}" -eq 1 ] || die "${E_REFUSE}" \
        "目标不是 USB 介质，确认后加 --allow-fixed: ${DEV_PATH}"
    [ "${DEV_BYTES}" -ge "${ISO_BYTES}" ] || die "${E_REFUSE}" \
        "目标容量 $(human "${DEV_BYTES}") 小于镜像 $(human "${ISO_BYTES}")"
    say verdict "ok (未挂载、非系统盘、容量足够)"
}

confirm()
{
    local reply=""

    [ "${YES}" -eq 1 ] && return 0
    [ -t 0 ] || die "${E_REFUSE}" "非交互环境需 --yes 显式确认"
    printf '  将覆盖 %s 上的全部数据。输入 %s 确认: ' \
        "${DEV_PATH}" "$(basename "${DEV_PATH}")"
    read -r reply || reply=""
    [ "${reply}" = "$(basename "${DEV_PATH}")" ] ||
        die "${E_REFUSE}" "确认串不匹配，已中止"
}

do_write()
{
    local rc=0

    sect "write"
    if [ "${QUIET}" -eq 1 ]; then
        dd if="${ISO}" of="${DEV_PATH}" bs=4M conv=fsync status=none \
            2>"${WLOG}"
        rc=$?
    else
        dd if="${ISO}" of="${DEV_PATH}" bs=4M conv=fsync status=progress \
            2>&1 >/dev/null | tee "${WLOG}"
        rc=${PIPESTATUS[0]}
    fi
    WRITE_S=${SECONDS}
    [ "${rc}" -eq 0 ] || die "${E_IO}" "写入失败 rc=${rc}，日志 ${WLOG}"
    say wrote "$(human "${ISO_BYTES}") in ${WRITE_S}s"
    say verdict "ok (dd rc=0，待回读确认)"
}

do_verify()
{
    local got

    sect "verify"
    got="$(hash_head "${DEV_PATH}" "${ISO_BYTES}")"
    if [ -z "${got}" ]; then
        say verdict "fail (回读失败)"
        return 1
    fi
    say readback "$(human "${ISO_BYTES}")"
    say sha256 "${got}"
    if [ "${got}" = "${ISO_SHA}" ]; then
        say verdict "ok (回读摘要与镜像一致)"
        return 0
    fi
    say verdict "fail (回读摘要与镜像不符)"
    return 1
}

write_rec()
{
    local rec="${OUT}/flash-$(basename "${DEV_PATH}")-$(date -u +%Y%m%dT%H%M%SZ).txt"

    {
        printf '# AirymaxOS flash record\n'
        printf 'tool=%s %s\n' "${NAME}" "${VERSION}"
        printf 'utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'image=%s\nimage_bytes=%s\nimage_sha256=%s\n' \
            "$(basename "${ISO}")" "${ISO_BYTES}" "${ISO_SHA}"
        printf 'target=%s\ntarget_bytes=%s\ntarget_model=%s\n' \
            "${DEV_PATH}" "${DEV_BYTES}" "${DEV_MODEL:-unknown}"
        printf 'target_serial=%s\ntarget_removable=%s\n' \
            "${DEV_SERIAL:-none}" "${DEV_REMOVABLE}"
        printf 'write_seconds=%s\nverify=%s\n' "${WRITE_S}" "${VERIFY}"
        printf 'write_log=%s\n' "$(basename "${WLOG}")"
        printf 'result=%s\n' "${VERIFY}"
    } >"${rec}" || die "${E_IO}" "无法写记录文件: ${rec}"
    say record "${rec}"
}

plan_head()
{
    printf '  %-4s %-14s %-10s %-5s %-3s %s\n' \
        "idx" "device" "size" "bus" "rm" "model"
}

plan_line()
{
    printf '  #%-3s %-14s %-10s %-5s %-3s %s\n' "$1" "$2" "$3" "$4" "$5" "$6"
    printf '       %-9s %s\n' "$8" "$7"
}

plan_one()
{
    local n="$1" path="$2" raw size tran rm model mounts note kind

    raw="$(blockdev --getsize64 "${path}" 2>/dev/null)"
    size="$(blk_get "${path}" SIZE)"
    [ -z "${raw}" ] || size="$(human "${raw}")"
    tran="$(blk_get "${path}" TRAN)"
    rm="$(blk_get "${path}" RM)"
    model="$(blk_get "${path}" MODEL)"
    mounts="$(mounts_of "${path}")"
    if [ -n "${mounts}" ]; then
        kind="refused"
        note="已挂载: $(oneline "${mounts}")"
    elif is_sys_of "${path}"; then
        kind="refused"
        note="系统盘（承载 ${ROOTDEV}）"
    elif [ "${rm}" = 1 ] || [ "${tran}" = usb ]; then
        kind="ready"
        note="可写入"
    else
        kind="fixed"
        note="内置介质，需 --allow-fixed"
    fi
    KIND="${kind}"
    plan_line "${n}" "${path}" "${size}" "${tran:-—}" "${rm:-0}" \
        "${model}" "${note}" "${kind}"
}

do_plan()
{
    local n=0 ready=0 fixed=0 refused=0 path

    command -v lsblk >/dev/null 2>&1 ||
        die "${E_ENV}" "缺少 lsblk（util-linux）"
    ROOTDEV="$(findmnt -nro SOURCE / 2>/dev/null)"
    sect "candidates"
    plan_head
    while read -r path; do
        [ -n "${path}" ] || continue
        n=$((n + 1))
        plan_one "${n}" "${path}"
        case "${KIND}" in
        ready) ready=$((ready + 1)) ;;
        fixed) fixed=$((fixed + 1)) ;;
        *) refused=$((refused + 1)) ;;
        esac
    done < <(lsblk -dnrPo PATH,TYPE 2>/dev/null |
        awk -F'"' '$4 == "disk" { print $2 }')

    [ "${n}" -gt 0 ] || die "${E_ENV}" "未发现可用磁盘（lsblk 无输出）"
    say verdict "ok (ready ${ready} / fixed ${fixed} / refused ${refused})"
}

optarg()
{
    [ "$2" -ge 2 ] || die "${E_USAGE}" "$1 缺少参数"
}

parse_args()
{
    while [ $# -gt 0 ]; do
        case "$1" in
        --iso) optarg "$1" "$#"; ISO="$2"; shift 2 ;;
        --target) optarg "$1" "$#"; TARGET="$2"; shift 2 ;;
        --expect) optarg "$1" "$#"; EXPECT="$2"; shift 2 ;;
        --out) optarg "$1" "$#"; OUT="$2"; shift 2 ;;
        --yes) YES=1; shift ;;
        --allow-fixed) FIXED=1; shift ;;
        --dry-run) DRY=1; shift ;;
        --quiet) QUIET=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "${E_USAGE}" "未知参数: $1" ;;
        esac
    done
}

need_root()
{
    [ "$(id -u)" -eq 0 ] ||
        die "${E_ENV}" "写入目标盘需要 root（可先 sudo 或加 --dry-run）"
}

run_write()
{
    parse_args "$@"
    check_iso
    guard_target
    if [ "${DRY}" -eq 1 ]; then
        sect "write"
        say plan "dry-run：校验与守卫通过，未写入"
        return 0
    fi
    confirm
    need_root
    OUT="$(out_guard "${NAME}" "${OUT}")" || exit $?
    WLOG="${OUT}/write-$(basename "${DEV_PATH}")-$(date -u +%Y%m%dT%H%M%SZ).log"
    SECONDS=0
    do_write
    VERIFY="fail"
    do_verify && VERIFY="pass"
    write_rec
    [ "${VERIFY}" = pass ] ||
        die "${E_MISMATCH}" "回读摘要与镜像不符，介质不可用"
    printf '\n%s: pass\n' "${NAME}"
}

run_verify()
{
    parse_args "$@"
    check_iso
    [ -n "${TARGET}" ] || die "${E_USAGE}" "--target 必填"
    dev_facts
    show_facts
    [ "${DEV_BYTES}" -ge "${ISO_BYTES}" ] || die "${E_REFUSE}" \
        "目标容量小于镜像"
    do_verify || die "${E_MISMATCH}" "回读摘要与镜像不符"
    printf '\n%s: pass\n' "${NAME}"
}

main()
{
    CMD="${1:-}"
    [ $# -gt 0 ] && shift
    printf '%s %s\n' "AirymaxOS flash" "${VERSION}"
    case "${CMD}" in
    check) parse_args "$@"; check_iso ;;
    plan) parse_args "$@"; do_plan ;;
    write) . "${DISTRO_ROOT}/scripts/lib/outdir.sh"; run_write "$@" ;;
    verify) run_verify "$@" ;;
    -h|--help|help|"") usage ;;
    *) die "${E_USAGE}" "未知子命令: ${CMD}（见 --help）" ;;
    esac
}

main "$@"
