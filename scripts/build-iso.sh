#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# build-iso.sh — AirymaxOS 无人值守安装 ISO 组装驱动
#
# 以 openEuler 官方安装介质为底座，注入 kickstart 与串口控制台参数，
# 重建卷标为 AIRYMAXOS 的可引导 ISO，并产出校验和与可选分离签名。
# 构建产物必须落在源码区之外（0.0.3 任务方案 §3.1）。
#
# 产物契约（190-distribution/03-installer-design.md §7.1）：
#   - /ks.cfg 与输入 kickstart 逐字节一致；
#   - BIOS/UEFI 引导配置含 inst.ks= 且引用最终卷标；
#   - 在主卷描述符应用数据区写入 ISO 校验和（implantisomd5）并以
#     checkisomd5 复核，支持 dracut 的 rd.live.check。
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
readonly E_PERM=12

DISTRO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly DISTRO_ROOT

# shellcheck source=lib/outdir.sh
. "${DISTRO_ROOT}/scripts/lib/outdir.sh"
# shellcheck source=lib/arch.sh
. "${DISTRO_ROOT}/scripts/lib/arch.sh"

ISO=""
KS=""
OUT=""
VOLID="AIRYMAXOS"
ARCH=""
VERSION=""
GPG_KEY=""
KARGS="console=ttyS0,115200"
MD5=1
ADDS=()
OUT_ABS=""
WORK=""
NAME=""
DEST=""
PART=""
ISO_SUM=""

usage()
{
    cat <<'EOF'
用法: scripts/build-iso.sh --iso SRC --ks FILE --out DIR [选项]

  --iso PATH         基础安装 ISO（必填）
  --ks FILE          kickstart 配方（必填，须通过 ks_lint）
  --out DIR          产物目录（必须在源码区之外，必填）
  --volid NAME       ISO 卷标，缺省 AIRYMAXOS
  --arch ARCH        x86_64|aarch64，缺省为宿主
  --version VER      版本号，缺省取 release/os-release 的 VERSION_ID
  --kargs TEXT       追加到安装内核命令行的参数，缺省
                     "console=ttyS0,115200"；传空串则不追加
  --add PATH         额外加入 ISO 的文件或目录，可重复
  --gpg-key KEYID    生成分离签名 .asc
  --no-md5           跳过尾部补齐与校验块注入（仅限调试）
  -h, --help         显示本帮助

产出:
  DIR/airymaxos-<ver>-<arch>.iso          可引导安装镜像
  DIR/airymaxos-<ver>-<arch>.iso.sha256   ISO 校验和
  DIR/airymaxos-<ver>-<arch>.iso.asc      可选分离签名
  DIR/iso-manifest.txt                    源介质与产物清单

mkksiso 需挂载源 ISO，实体机与 CI 均以 root 执行。
EOF
}

die()
{
    local code="$1"
    shift
    printf 'build-iso: %s\n' "$*" >&2
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
        --iso) optarg "$1" "$#"; ISO="$2"; shift 2 ;;
        --ks) optarg "$1" "$#"; KS="$2"; shift 2 ;;
        --out) optarg "$1" "$#"; OUT="$2"; shift 2 ;;
        --volid) optarg "$1" "$#"; VOLID="$2"; shift 2 ;;
        --arch) optarg "$1" "$#"; ARCH="$2"; shift 2 ;;
        --version) optarg "$1" "$#"; VERSION="$2"; shift 2 ;;
        --kargs) optarg "$1" "$#"; KARGS="$2"; shift 2 ;;
        --add) optarg "$1" "$#"; ADDS+=("$2"); shift 2 ;;
        --gpg-key) optarg "$1" "$#"; GPG_KEY="$2"; shift 2 ;;
        --no-md5) MD5=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "${E_INVAL}" "未知参数: $1" ;;
        esac
    done
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

check_volid()
{
    case "$VOLID" in
    ''|*[!A-Z0-9._-]*)
        die "${E_INVAL}" "卷标只允许大写字母、数字与 ._-: ${VOLID}"
        ;;
    esac
    if [ "${#VOLID}" -gt 32 ]; then
        die "${E_INVAL}" "卷标超过 ISO 9660 上限 32 字节: ${VOLID}"
    fi
}

base_ver()
{
    sed -n 's/^VERSION_ID="\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
        "${DISTRO_ROOT}/release/os-release"
}

check_files()
{
    local add
    [ -n "$ISO" ] || die "${E_INVAL}" "--iso 必填"
    [ -f "$ISO" ] || die "${E_INVAL}" "基础 ISO 不存在: ${ISO}"
    [ -n "$KS" ] || die "${E_INVAL}" "--ks 必填"
    [ -f "$KS" ] || die "${E_INVAL}" "kickstart 不存在: ${KS}"
    for add in "${ADDS[@]}"; do
        [ -e "$add" ] || die "${E_INVAL}" "--add 路径不存在: ${add}"
    done
    if [ -z "$VERSION" ]; then
        VERSION="$(base_ver)"
    fi
    case "$VERSION" in
    ''|*[!A-Za-z0-9._-]*) die "${E_INVAL}" "版本号非法: ${VERSION}" ;;
    esac
    if [ "${#VERSION}" -gt 32 ]; then
        die "${E_INVAL}" "版本号长度超过 32 字节: ${VERSION}"
    fi
    if [ "$VERSION" != "$(base_ver)" ]; then
        printf 'build-iso: 警告：版本 %s 与 os-release 不一致\n' \
            "$VERSION" >&2
    fi
    NAME="airymaxos-${VERSION}-${ARCH}.iso"
    DEST="${OUT_ABS}/${NAME}"
    if [ -e "$DEST" ]; then
        die "${E_EXIST}" "产物已存在，请先移除: ${DEST}"
    fi
}

prep()
{
    WORK="${OUT_ABS}/work"
    PART="${OUT_ABS}/.${NAME}.part"
    rm -rf "$WORK"
    rm -f "$PART"
    mkdir -p "${WORK}/logs"
    trap 'rm -f "${PART}"' EXIT
    umask 022
    export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1468923400}"
    export TZ=UTC LANG=C.UTF-8 LC_ALL=C.UTF-8
    # mkksiso 以 basename 把 kickstart 映射进 ISO 根，产物契约要求固定为
    # /ks.cfg，故先按契约名暂存，再由 inst.ks=hd:LABEL=…:/ks.cfg 引用。
    cp -f "$KS" "${WORK}/ks.cfg" ||
        die "${E_IO}" "无法暂存 kickstart: ${WORK}/ks.cfg"
}

lint_ks()
{
    local log="${WORK}/logs/ks-lint.log"
    if ! python3 "${DISTRO_ROOT}/tools/ks_lint.py" "$KS" >"$log" 2>&1; then
        sed 's/^/  /' "$log" >&2
        die "${E_INVAL}" "kickstart 未通过静态校验: ${KS}"
    fi
}

build_iso()
{
    local -a args=(-V "$VOLID")
    local add
    if [ -n "$KARGS" ]; then
        args+=(-c "$KARGS")
    fi
    for add in "${ADDS[@]}"; do
        args+=(-a "$add")
    done
    if ! mkksiso "${args[@]}" "${WORK}/ks.cfg" "$ISO" "$PART" \
        >"${WORK}/logs/mkksiso.log" 2>&1; then
        die "${E_IO}" "mkksiso 失败（日志 ${WORK}/logs/mkksiso.log）"
    fi
    if [ ! -s "$PART" ]; then
        die "${E_IO}" "mkksiso 未产出 ISO: ${PART}"
    fi
    mv -f "$PART" "$DEST"
}

extract()
{
    local path="$1" dest="$2"
    rm -f "$dest"
    xorriso -osirrox on -indev "$DEST" -extract "$path" "$dest" \
        >>"${WORK}/logs/xorriso.log" 2>&1
}

check_cfg()
{
    local cfg="$1" name="$2" arg
    grep -Eq 'inst[.]ks=[^[:space:]]+' "$cfg" ||
        die "${E_IO}" "引导配置 ${name} 未注入 inst.ks"
    grep -Eq "(^|[^A-Za-z0-9_.-])LABEL=${VOLID}([^A-Za-z0-9_.-]|$)" \
        "$cfg" ||
        die "${E_IO}" "引导配置 ${name} 未引用卷标 ${VOLID}"
    while IFS= read -r arg; do
        case "$arg" in
        *"LABEL=${VOLID}"*) ;;
        *)
            die "${E_IO}" \
                "引导配置 ${name} 的 ${arg} 与卷标 ${VOLID} 不一致"
            ;;
        esac
    done < <(grep -Eo 'inst[.]stage2=[^[:space:]]+' "$cfg" || true)
}

verify_cfg()
{
    local cfg path dest found=0
    for cfg in isolinux/isolinux.cfg EFI/BOOT/grub.cfg; do
        path="/${cfg}"
        dest="${WORK}/cfg.$(basename "$cfg")"
        if extract "$path" "$dest"; then
            found=1
            check_cfg "$dest" "$cfg"
        fi
    done
    [ "$found" -eq 1 ] ||
        die "${E_IO}" "ISO 内未找到 BIOS/UEFI 引导配置"
}

verify()
{
    local got="${WORK}/ks.cfg"
    if ! extract /ks.cfg "$got"; then
        die "${E_IO}" "ISO 内缺少 /ks.cfg"
    fi
    cmp -s "$KS" "$got" ||
        die "${E_IO}" "ISO 内 kickstart 与源文件不一致"
    verify_cfg
}

md5_tag()
{
    if [ "$MD5" -ne 1 ]; then
        return 0
    fi
    # mkksiso 沿用基础介质的 PVD，其应用数据区仍留有底座镜像的校验记录；
    # 该记录对新镜像已失效，必须覆盖，否则 implantisomd5 拒绝写入。
    if ! implantisomd5 --force "$DEST" \
        >"${WORK}/logs/implantisomd5.log" 2>&1; then
        die "${E_IO}" "implantisomd5 失败" \
            "（日志 ${WORK}/logs/implantisomd5.log）"
    fi
    if ! checkisomd5 --md5sumonly "$DEST" \
        >"${WORK}/logs/checkisomd5.log" 2>&1; then
        die "${E_IO}" "checkisomd5 复核失败" \
            "（日志 ${WORK}/logs/checkisomd5.log）"
    fi
}

sum_of()
{
    local sum rest
    read -r sum rest < <(sha256sum "$1") || return 1
    printf '%s\n' "$sum"
}

write_sum()
{
    printf '%s  %s\n' "$1" "$NAME" >"${DEST}.sha256"
}

sign_iso()
{
    if ! gpg --batch --yes --armor --detach-sign --local-user "$GPG_KEY" \
        --output "${DEST}.asc" "$DEST" \
        >"${WORK}/logs/gpg.log" 2>&1; then
        die "${E_PERM}" "ISO 签名失败（密钥 ${GPG_KEY}）"
    fi
}

write_manifest()
{
    local base_sum ks_sum
    base_sum="$(sum_of "$ISO")" || die "${E_IO}" "sha256sum 失败: ${ISO}"
    ks_sum="$(sum_of "$KS")" || die "${E_IO}" "sha256sum 失败: ${KS}"
    {
        printf '# AirymaxOS ISO build manifest\n'
        printf 'name=%s\n' "$NAME"
        printf 'version=%s\n' "$VERSION"
        printf 'arch=%s\n' "$ARCH"
        printf 'volid=%s\n' "$VOLID"
        printf 'source_date_epoch=%s\n' "$SOURCE_DATE_EPOCH"
        printf 'iso %s %s\n' "$1" "$NAME"
        printf 'ks %s %s\n' "$ks_sum" "$(basename "$KS")"
        printf 'base %s %s\n' "$base_sum" "$(basename "$ISO")"
    } >"${OUT_ABS}/iso-manifest.txt"
}

main()
{
    parse_args "$@"
    OUT_ABS="$(out_guard build-iso "$OUT")"
    check_arch
    check_volid
    check_files
    need mkksiso
    need xorriso
    need sha256sum
    need python3
    if [ "$MD5" -eq 1 ]; then
        need implantisomd5
        need checkisomd5
    fi
    if [ -n "$GPG_KEY" ]; then
        need gpg
    fi
    prep
    lint_ks
    printf '构建 ISO: %s（卷标 %s，架构 %s）\n' "$NAME" "$VOLID" "$ARCH"
    build_iso
    verify
    md5_tag
    ISO_SUM="$(sum_of "$DEST")" || die "${E_IO}" "sha256sum 失败: ${DEST}"
    write_sum "$ISO_SUM"
    if [ -n "$GPG_KEY" ]; then
        sign_iso
    fi
    write_manifest "$ISO_SUM"
    printf '产物: %s\n' "$DEST"
    printf '校验: %s.sha256\n' "$DEST"
    printf '清单: %s\n' "${OUT_ABS}/iso-manifest.txt"
}

main "$@"
