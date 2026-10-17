#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# build-desktop.sh — AirymaxOS 桌面镜像组装驱动
#
# 把 build-rpms 与 build-kernel 的产物收敛成自包含离线仓库，随基础 ISO
# 一起分发，再委派 build-iso.sh 完成 kickstart 注入与引导复核。桌面安装
# 不依赖安装现场的网络，仓库根为 ISO 内 /airymax/Packages。
#
# 产物（0.0.3 任务方案 M-15；190-distribution/03-installer-design.md §7.1）：
#   DIR/payload/airymax/Packages/*.rpm        离线包集合
#   DIR/payload/airymax/Packages/repodata/    含 group 元数据的仓库索引
#   DIR/payload/airymax/payload-manifest.txt  包集合与 comps 的 SHA-256 清单
#   DIR/iso/                                  build-iso 产物与清单
#
# 退出码（190-distribution/01-rpm-packaging.md §8）：
#   0 成功；2 AIRY_EEXIST；5 AIRY_EINVAL；6 AIRY_EIO；
#   11 AIRY_ENOTSUP；12 AIRY_EPERM。
# ===========================================================================
set -euo pipefail

readonly E_EXIST=2
readonly E_INVAL=5
readonly E_IO=6
readonly E_NOSUP=11

DISTRO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly DISTRO_ROOT
readonly COMPS="${DISTRO_ROOT}/comps/airymaxos-comps.xml"

# shellcheck source=lib/outdir.sh
. "${DISTRO_ROOT}/scripts/lib/outdir.sh"

BASE=""
KS=""
OUT=""
ARCH=""
VOLID="AIRYMAXOS"
VERSION=""
GPG_KEY=""
MD5=1
RPMS=()
ADDS=()
OUT_ABS=""
PAY=""
AIRY=""
PKGDIR=""
OUT_ISO=""
NAMES=()

usage()
{
    cat <<'EOF'
用法: scripts/build-desktop.sh --iso SRC --ks FILE --out DIR --rpms DIR [选项]

  --iso PATH         基础安装 ISO（必填）
  --ks FILE          桌面 kickstart（必填，须通过 ks_lint）
  --out DIR          产物目录（必须在源码区之外，必填）
  --rpms DIR         待汇集的 RPM 目录，递归扫描，可重复（必填）
  --arch ARCH        x86_64|aarch64，缺省为宿主
  --volid NAME       ISO 卷标，缺省 AIRYMAXOS
  --version VER      版本号，缺省取 release/os-release 的 VERSION_ID
  --add PATH         额外加入 ISO 的文件或目录，可重复
  --gpg-key KEYID    生成 ISO 分离签名 .asc
  --no-md5           跳过 implantisomd5（仅限调试）
  -h, --help         显示本帮助

产出:
  DIR/payload/airymax/                离线仓库与载荷清单（注入 ISO 根）
  DIR/iso/airymaxos-<ver>-<arch>.iso  可引导桌面安装镜像
  DIR/iso/iso-manifest.txt            基础介质与 ISO 产物清单

离线仓库必须提供 airymaxos-release、airymaxos-kernel 及其 core/modules
子包，否则 kickstart 的包组与 %post 校验无法闭合。
EOF
}

die()
{
    local code="$1"
    shift
    printf 'build-desktop: %s\n' "$*" >&2
    exit "${code}"
}

need()
{
    command -v "$1" >/dev/null 2>&1 ||
        die "${E_NOSUP}" "缺少镜像构建工具: $1"
}

optarg()
{
    [ "$2" -ge 2 ] || die "${E_INVAL}" "$1 缺少参数"
}

parse_args()
{
    while [ $# -gt 0 ]; do
        case "$1" in
        --iso) optarg "$1" "$#"; BASE="$2"; shift 2 ;;
        --ks) optarg "$1" "$#"; KS="$2"; shift 2 ;;
        --out) optarg "$1" "$#"; OUT="$2"; shift 2 ;;
        --rpms) optarg "$1" "$#"; RPMS+=("$2"); shift 2 ;;
        --arch) optarg "$1" "$#"; ARCH="$2"; shift 2 ;;
        --volid) optarg "$1" "$#"; VOLID="$2"; shift 2 ;;
        --version) optarg "$1" "$#"; VERSION="$2"; shift 2 ;;
        --add) optarg "$1" "$#"; ADDS+=("$2"); shift 2 ;;
        --gpg-key) optarg "$1" "$#"; GPG_KEY="$2"; shift 2 ;;
        --no-md5) MD5=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "${E_INVAL}" "未知参数: $1" ;;
        esac
    done
}

host_arch()
{
    case "$(uname -m)" in
    amd64) printf 'x86_64\n' ;;
    arm64) printf 'aarch64\n' ;;
    *) uname -m ;;
    esac
}

check_arch()
{
    if [ -z "$ARCH" ]; then
        ARCH="$(host_arch)"
    fi
    case "$ARCH" in
    x86_64|aarch64) ;;
    *) die "${E_INVAL}" "不支持的 ISO 架构: $ARCH" ;;
    esac
}

check_args()
{
    local dir add
    [ -n "$BASE" ] || die "${E_INVAL}" "--iso 必填"
    [ -f "$BASE" ] || die "${E_INVAL}" "基础 ISO 不存在: ${BASE}"
    [ -n "$KS" ] || die "${E_INVAL}" "--ks 必填"
    [ -f "$KS" ] || die "${E_INVAL}" "kickstart 不存在: ${KS}"
    [ "${#RPMS[@]}" -gt 0 ] || die "${E_INVAL}" "--rpms 至少给出一个目录"
    for dir in "${RPMS[@]}"; do
        [ -d "$dir" ] || die "${E_INVAL}" "--rpms 目录不存在: ${dir}"
    done
    [ -f "$COMPS" ] || die "${E_INVAL}" "comps 定义缺失: ${COMPS}"
    for add in "${ADDS[@]}"; do
        [ -e "$add" ] || die "${E_INVAL}" "--add 路径不存在: ${add}"
    done
}

prep_payload()
{
    PAY="${OUT_ABS}/payload"
    AIRY="${PAY}/airymax"
    PKGDIR="${AIRY}/Packages"
    rm -rf "$PAY" "${OUT_ABS}/verify"
    mkdir -p "$PKGDIR" "${OUT_ABS}/logs" "${OUT_ABS}/verify"
    umask 022
    export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1468923400}"
    export TZ=UTC LANG=C.UTF-8 LC_ALL=C.UTF-8
}

arch_ok()
{
    case "$1" in
    *.noarch.rpm|*."${ARCH}".rpm) return 0 ;;
    esac
    return 1
}

collect_rpms()
{
    local dir rpm base
    local -A seen=()
    while IFS= read -r rpm; do
        base="$(basename "$rpm")"
        case "$base" in
        *.src.rpm) continue ;;
        esac
        arch_ok "$base" ||
            die "${E_INVAL}" "RPM 架构与 ${ARCH} 不符: ${base}"
        if [ -n "${seen[$base]:-}" ]; then
            die "${E_EXIST}" "同名 RPM 出现多次: ${base}"
        fi
        seen[$base]="$rpm"
        cp -p "$rpm" "${PKGDIR}/${base}"
        NAMES+=("$base")
    done < <(for dir in "${RPMS[@]}"; do
        find "$dir" -type f -name '*.rpm' -print
    done | sort)
    [ "${#NAMES[@]}" -gt 0 ] ||
        die "${E_INVAL}" "--rpms 目录内没有可用的 RPM"
}

check_closure()
{
    local want base have
    for want in airymaxos-release airymaxos-system airymaxos-kernel \
        airymaxos-kernel-core airymaxos-kernel-modules; do
        have=""
        for base in "${NAMES[@]}"; do
            case "$base" in
            "${want}-"[0-9]*) have="$base"; break ;;
            esac
        done
        [ -n "$have" ] ||
            die "${E_INVAL}" "离线仓库缺少必需包: ${want}"
    done
}

sum_of()
{
    local sum rest
    read -r sum rest < <(sha256sum "$1") || return 1
    printf '%s\n' "$sum"
}

write_payload()
{
    local base sum comps_sum
    comps_sum="$(sum_of "$COMPS")" || die "${E_IO}" "sha256sum 失败: ${COMPS}"
    {
        printf '# AirymaxOS desktop payload manifest\n'
        printf 'arch=%s\n' "$ARCH"
        printf 'count=%s\n' "${#NAMES[@]}"
        printf 'comps %s comps/airymaxos-comps.xml\n' "$comps_sum"
        for base in "${NAMES[@]}"; do
            sum="$(sum_of "${PKGDIR}/${base}")" ||
                die "${E_IO}" "sha256sum 失败: ${base}"
            printf 'rpm %s %s\n' "$sum" "$base"
        done
    } >"${AIRY}/payload-manifest.txt"
}

make_repo()
{
    local log="${OUT_ABS}/logs/createrepo.log"
    if ! createrepo_c --groupfile "$COMPS" "$PKGDIR" >"$log" 2>&1; then
        die "${E_IO}" "createrepo_c 失败（日志 ${log}）"
    fi
    [ -f "${PKGDIR}/repodata/repomd.xml" ] ||
        die "${E_IO}" "仓库元数据缺失: ${PKGDIR}/repodata/repomd.xml"
    grep -q 'type="group"' "${PKGDIR}/repodata/repomd.xml" ||
        die "${E_IO}" "仓库缺少 comps 分组元数据"
}

run_iso()
{
    local add rc=0
    local -a args=(--iso "$BASE" --ks "$KS" --out "${OUT_ABS}/iso"
                   --arch "$ARCH" --volid "$VOLID" --add "$AIRY")
    for add in "${ADDS[@]}"; do
        args+=(--add "$add")
    done
    if [ -n "$VERSION" ]; then
        args+=(--version "$VERSION")
    fi
    if [ -n "$GPG_KEY" ]; then
        args+=(--gpg-key "$GPG_KEY")
    fi
    if [ "$MD5" -ne 1 ]; then
        args+=(--no-md5)
    fi
    "${DISTRO_ROOT}/scripts/build-iso.sh" "${args[@]}" \
        >"${OUT_ABS}/logs/build-iso.log" 2>&1 || rc=$?
    case "$rc" in
    0) ;;
    2|5|6|11|12) die "$rc" "ISO 组装失败（日志 ${OUT_ABS}/logs/build-iso.log）" ;;
    *) die "${E_IO}" "ISO 组装失败（日志 ${OUT_ABS}/logs/build-iso.log）" ;;
    esac
}

iso_path()
{
    local line value=""
    [ -f "${OUT_ABS}/iso/iso-manifest.txt" ] ||
        die "${E_IO}" "缺少 ISO 清单: ${OUT_ABS}/iso/iso-manifest.txt"
    while IFS= read -r line; do
        case "$line" in
        name=*) value="${line#name=}" ;;
        esac
    done <"${OUT_ABS}/iso/iso-manifest.txt"
    [ -n "$value" ] || die "${E_IO}" "ISO 清单缺少 name 字段"
    OUT_ISO="${OUT_ABS}/iso/${value}"
    [ -f "$OUT_ISO" ] || die "${E_IO}" "ISO 产物不存在: ${OUT_ISO}"
}

check_payload()
{
    local got="${OUT_ABS}/verify" log="${OUT_ABS}/logs/xorriso.log"
    if ! xorriso -osirrox on -indev "$OUT_ISO" \
        -extract /airymax/payload-manifest.txt \
        "${got}/payload-manifest.txt" >"$log" 2>&1; then
        die "${E_IO}" "ISO 内缺少 /airymax/payload-manifest.txt"
    fi
    if ! xorriso -osirrox on -indev "$OUT_ISO" \
        -extract /airymax/Packages/repodata/repomd.xml \
        "${got}/repomd.xml" >>"$log" 2>&1; then
        die "${E_IO}" "ISO 内缺少 /airymax/Packages/repodata/repomd.xml"
    fi
    cmp -s "${AIRY}/payload-manifest.txt" "${got}/payload-manifest.txt" ||
        die "${E_IO}" "ISO 内载荷清单与源文件不一致"
    cmp -s "${PKGDIR}/repodata/repomd.xml" "${got}/repomd.xml" ||
        die "${E_IO}" "ISO 内仓库索引与源文件不一致"
}

main()
{
    parse_args "$@"
    OUT_ABS="$(out_guard build-desktop "$OUT")"
    check_arch
    check_args
    need createrepo_c
    need xorriso
    need sha256sum
    need find
    need sort
    prep_payload
    collect_rpms
    check_closure
    make_repo
    write_payload
    printf '汇集 RPM: %d 个（架构 %s）\n' "${#NAMES[@]}" "$ARCH"
    run_iso
    iso_path
    check_payload
    printf '产物: %s\n' "$OUT_ISO"
    printf '载荷: %s\n' "$PKGDIR"
    printf '清单: %s\n' "${OUT_ABS}/iso/iso-manifest.txt"
}

main "$@"
