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
#   - /ks.cfg 与输入 kickstart 的展开产物逐字节一致（共享脚本在暂存
#     阶段由 tools/ks_embed.py 嵌入，源码配方本身不含脚本正文）；
#   - BIOS/UEFI 引导配置含 inst.ks= 且引用最终卷标；
#   - 在主卷描述符应用数据区写入 ISO 校验和（implantisomd5）并以
#     checkisomd5 复核，支持 dracut 的 rd.live.check；
#   - isohybrid 三元一致：El Torito 引导目录、MBR 0xEF 分区项与 GPT
#     ISOHybrid1 条目必须指向同一段扇区，否则 USB 盘方式引导会静默失败
#     （tools/isohybrid_sync.py）；该校验必须早于校验块注入，否则会把
#     改写过的扇区算进旧摘要。
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
# shellcheck source=lib/iso_post.sh
. "${DISTRO_ROOT}/scripts/lib/iso_post.sh"
# shellcheck source=lib/arch.sh
. "${DISTRO_ROOT}/scripts/lib/arch.sh"

ISO=""
KS=""
OUT=""
VOLID="AIRYMAXOS"
ARCH=""
VERSION=""
GPG_KEY=""
# 装载器命令行只作用于安装器，不进已装系统的 grub（后者由 kickstart 的
# bootloader --append 决定）。inst.lang 因此是「安装界面用英文、装出来的
# 系统仍是中文」的唯一开关：安装器是 text 模式的 Linux VT，镜像 FONT 为
# latarcyrheb-sun16，没有 CJK 字形，VGA 文本模式装不进中文字库，一旦界面
# 跟随 ks 的 lang zh_CN.UTF-8，屏幕上的每一步都只剩方块（285H 装机实测）。
# 装出来的系统语言仍由 ks 的 lang 决定，桌面不受影响。
KARGS="console=tty0 console=ttyS0,115200 inst.lang=en_US.UTF-8"
MD5=1
PRODUCT=""
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
  --product TEXT     引导菜单显示的产品名（ASCII），缺省取 release/os-release
                     的 PRETTY_NAME（"<短名> <版本号>"）
  --kargs TEXT       追加到安装内核命令行的参数，缺省
                     "console=tty0 console=ttyS0,115200"；传空串则不追加
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
        --product) optarg "$1" "$#"; PRODUCT="$2"; shift 2 ;;
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

base_pretty()
{
    sed -n 's/^PRETTY_NAME="\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
        "${DISTRO_ROOT}/release/os-release"
}

# 引导菜单只显示产品名，不含发行版代号；缺省直接取 os-release 的 PRETTY_NAME，
# 与 manifest 的 version 字段各自独立。这里绝不读 NAME：NAME 是按 0.0.4 口径
# 给人读的完整名（可含中文），而产品名要进 ISO 卷标、.treeinfo、菜单标题与
# NVRAM 条目，全是 ASCII-only 通道——下面的字符白名单会直接拒绝非 ASCII，
# 放过它则菜单在非 UTF-8 控制台输出乱码。字符白名单用正则而非 case：bash 的
# case 模式在方括号里遇到圆括号会按语法解析。
check_product()
{
    if [ -z "$PRODUCT" ]; then
        PRODUCT="$(base_pretty)"
    fi
    if [[ "$PRODUCT" =~ [^A-Za-z0-9\ ._\(\)\&-] ]]; then
        die "${E_INVAL}" "产品名含非法字符: ${PRODUCT}"
    fi
    if [ "${#PRODUCT}" -gt 48 ]; then
        die "${E_INVAL}" "产品名长度超过 48 字节: ${PRODUCT}"
    fi
}

check_files()
{
    check_inputs
    pick_version
    pick_dest
}

check_inputs()
{
    local add
    [ -n "$ISO" ] || die "${E_INVAL}" "--iso 必填"
    [ -f "$ISO" ] || die "${E_INVAL}" "基础 ISO 不存在: ${ISO}"
    [ -n "$KS" ] || die "${E_INVAL}" "--ks 必填"
    [ -f "$KS" ] || die "${E_INVAL}" "kickstart 不存在: ${KS}"
    for add in "${ADDS[@]}"; do
        [ -e "$add" ] || die "${E_INVAL}" "--add 路径不存在: ${add}"
    done
}

# 版本号同时进文件名与 os-release 引用，故先定值、再验形态、最后对账：
# 空值取 os-release 基线，形态非法或超长当场拒绝，不一致只告警不阻断。
pick_version()
{
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
}

# 产物名与落点在写入前定死：已存在的同名产物不覆盖，避免半成品
# 与新构建混在一起。
pick_dest()
{
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
    # 共享脚本在此嵌入：验收配方由 gen_accept_ks 生成到构建目录，与
    # kickstart/ 不同级，故显式给出共享脚本目录，不按配方所在目录推断。
    python3 "${DISTRO_ROOT}/tools/ks_embed.py" \
        --include-dir "${DISTRO_ROOT}/kickstart" \
        "$KS" "${WORK}/ks.cfg" ||
        die "${E_INVAL}" "无法展开 kickstart: ${KS}"
}

lint_ks()
{
    local log="${WORK}/logs/ks-lint.log"
    if ! python3 "${DISTRO_ROOT}/tools/ks_lint.py" \
        --include-dir "${DISTRO_ROOT}/kickstart" "$KS" >"$log" 2>&1; then
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

post_iso()
{
    local flag=""
    if [ "$MD5" -ne 1 ]; then
        flag="--no-md5"
    fi
    if ! iso_post "$DEST" "${WORK}/ks.cfg" "$VOLID" "$WORK" \
        --product "$PRODUCT" "$flag"; then
        die "${E_IO}" "ISO 后处理失败（日志 ${WORK}/logs）"
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
    ks_sum="$(sum_of "${WORK}/ks.cfg")" ||
        die "${E_IO}" "sha256sum 失败: ${WORK}/ks.cfg"
    {
        printf '# AirymaxOS ISO build manifest\n'
        printf 'name=%s\n' "$NAME"
        printf 'version=%s\n' "$VERSION"
        printf 'arch=%s\n' "$ARCH"
        printf 'volid=%s\n' "$VOLID"
        printf 'product=%s\n' "$PRODUCT"
        printf 'source_date_epoch=%s\n' "$SOURCE_DATE_EPOCH"
        printf 'iso %s %s\n' "$1" "$NAME"
        printf 'ks %s %s\n' "$ks_sum" "ks.cfg"
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
    check_product
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
    post_iso
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
