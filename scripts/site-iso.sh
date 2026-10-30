#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# site-iso.sh — 站点介质派生：在已验证系统旁装机用的派生镜像
#
# 产品 ISO 的配方是 clearpart --all，整盘归 AirymaxOS，发行物语义正确。
# 装机现场已有别的系统（双系统、保留数据盘）时，需要的是同一份字节、只
# 改分区作用域：配方改写由 tools/site_ks.py 完成，本驱动负责重建介质，
# 并复用主线构建的 lib/iso_post.sh 完成全部后处理。
#
# 两条腿共用后处理链的理由是实机故障：重新打包后 El Torito 条目的逻辑
# 块号前移，MBR/GPT 仍是旧扇区号，USB 盘方式引导会读到机器码而静默回落
# BootOrder 首位；同时 PVD 应用数据区里的旧校验记录会让默认菜单的
# rd.live.check 误报介质损坏。分区表对齐由后处理链统一完成，派生路径不在
# 调用侧另加开关。
#
# 产物契约（190-distribution/03-installer-design.md §7.4）：
#   - /ks.cfg 与派生配方逐字节一致；
#   - 卷标与源镜像一致，引导配置的 inst.stage2= 仍指向该卷标；
#   - BIOS/UEFI 三元一致，校验块可在 rd.live.check 下通过；
#   - 产物长度不小于源镜像：混合镜像的 MBR/GPT 尾部项按输入长度布局，
#     重新打包会丢掉末尾填充扇区，短一截就等于切掉 ESP 尾段。
#
# 退出码（190-distribution/01-rpm-packaging.md §8）：
#   0 成功；2 AIRY_EEXIST；5 AIRY_EINVAL；6 AIRY_EIO；11 AIRY_ENOTSUP。
# ===========================================================================
set -euo pipefail

readonly E_EXIST=2
readonly E_INVAL=5
readonly E_IO=6
readonly E_NOSUP=11

DISTRO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly DISTRO_ROOT

# shellcheck source=lib/outdir.sh
. "${DISTRO_ROOT}/scripts/lib/outdir.sh"
# shellcheck source=lib/iso_post.sh
. "${DISTRO_ROOT}/scripts/lib/iso_post.sh"

SRC=""
OUT=""
VOLID=""
DISK=""
ESP=""
BOOT=""
SWAP=""
ROOT=""
KEY=""
IFCFG=""
PSK=""
SSID=""
MD5=1
PROBE=0
OUT_ABS=""
WORK=""
NAME=""
DEST=""
PART=""

usage()
{
    cat <<'EOF'
用法: scripts/site-iso.sh --iso SRC --out DIR --disk DEV \
           --esp P --boot P --swap P --root P \
           --key FILE --ifcfg FILE --psk FILE [选项]

  --iso PATH         产品 ISO（必填，须由 build-iso.sh 产出）
  --out DIR          产物目录（必须在源码区之外，必填）
  --disk DEV         目标盘名，如 nvme0n1（必填）
  --esp P            EFI 系统分区，分区号或完整节点名（必填）
  --boot P           /boot 分区（必填）
  --swap P           交换分区（必填）
  --root P           根分区（必填）
  --key FILE         站点登录公钥（必填）
  --ifcfg FILE       无线 ifcfg 片段（必填）
  --psk FILE         无线预共享密钥文件（必填）
  --ssid NAME        无线 SSID，缺省取 ifcfg 文件名去掉 ifcfg- 前缀
  --volid NAME       卷标，缺省沿用源镜像主卷描述符
  --probe            派生前后用 lsblk 核对现场分区（仅限实体机）
  --no-md5           跳过校验块注入（仅限调试）
  -h, --help         显示本帮助

产出:
  DIR/<源镜像名>-site.iso          可引导的站点派生镜像
  DIR/<源镜像名>-site.iso.sha256   镜像校验和
  DIR/site-manifest.txt            源镜像与派生配方清单

装机现场须以 root 执行：xorriso 需要读取源镜像并写入产物目录。
EOF
}

die()
{
    local code="$1"
    shift
    printf 'site-iso: %s\n' "$*" >&2
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
        --iso) optarg "$1" "$#"; SRC="$2"; shift 2 ;;
        --out) optarg "$1" "$#"; OUT="$2"; shift 2 ;;
        --volid) optarg "$1" "$#"; VOLID="$2"; shift 2 ;;
        --disk) optarg "$1" "$#"; DISK="$2"; shift 2 ;;
        --esp) optarg "$1" "$#"; ESP="$2"; shift 2 ;;
        --boot) optarg "$1" "$#"; BOOT="$2"; shift 2 ;;
        --swap) optarg "$1" "$#"; SWAP="$2"; shift 2 ;;
        --root) optarg "$1" "$#"; ROOT="$2"; shift 2 ;;
        --key) optarg "$1" "$#"; KEY="$2"; shift 2 ;;
        --ifcfg) optarg "$1" "$#"; IFCFG="$2"; shift 2 ;;
        --psk) optarg "$1" "$#"; PSK="$2"; shift 2 ;;
        --ssid) optarg "$1" "$#"; SSID="$2"; shift 2 ;;
        --probe) PROBE=1; shift ;;
        --no-md5) MD5=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "${E_INVAL}" "未知参数: $1" ;;
        esac
    done
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

check_files()
{
    [ -n "$SRC" ] || die "${E_INVAL}" "--iso 必填"
    [ -f "$SRC" ] || die "${E_INVAL}" "产品镜像不存在: ${SRC}"
    [ -n "$DISK" ] || die "${E_INVAL}" "--disk 必填"
    [ -n "$ESP" ] || die "${E_INVAL}" "--esp 必填"
    [ -n "$BOOT" ] || die "${E_INVAL}" "--boot 必填"
    [ -n "$SWAP" ] || die "${E_INVAL}" "--swap 必填"
    [ -n "$ROOT" ] || die "${E_INVAL}" "--root 必填"
    [ -f "$KEY" ] || die "${E_INVAL}" "公钥文件不存在: ${KEY}"
    [ -f "$IFCFG" ] || die "${E_INVAL}" "无线配置不存在: ${IFCFG}"
    [ -f "$PSK" ] || die "${E_INVAL}" "预共享密钥不存在: ${PSK}"
    NAME="$(basename "$SRC" .iso)-site.iso"
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
    export TZ=UTC LANG=C.UTF-8 LC_ALL=C.UTF-8
}

derive()
{
    local -a args=(
        --iso "$SRC" --out "${WORK}/site.ks" --work "${WORK}/pick"
        --disk "$DISK" --esp "$ESP" --boot "$BOOT" --swap "$SWAP"
        --root "$ROOT" --key "$KEY" --ifcfg "$IFCFG" --psk "$PSK"
        --lint "${DISTRO_ROOT}/tools/ks_lint.py"
    )
    if [ -n "$SSID" ]; then
        args+=(--ssid "$SSID")
    fi
    if [ "$PROBE" -eq 1 ]; then
        args+=(--probe)
    fi
    python3 "${DISTRO_ROOT}/tools/site_ks.py" "${args[@]}" \
        >"${WORK}/logs/site-ks.log" 2>&1 || {
        sed 's/^/  /' "${WORK}/logs/site-ks.log" >&2
        die "${E_IO}" "站点配方派生失败（日志 ${WORK}/logs/site-ks.log）"
    }
}

rebuild()
{
    if ! xorriso -indev "$SRC" -outdev "$PART" \
        -map "${WORK}/site.ks" /ks.cfg -boot_image any keep \
        >"${WORK}/logs/xorriso.log" 2>&1; then
        die "${E_IO}" "xorriso 重建失败（日志 ${WORK}/logs/xorriso.log）"
    fi
    [ -s "$PART" ] || die "${E_IO}" "xorriso 未产出镜像: ${PART}"
}

pad_iso()
{
    local want got
    want="$(wc -c <"$SRC")"
    got="$(wc -c <"$PART")"
    if [ "$got" -gt "$want" ]; then
        die "${E_IO}" "派生镜像比源镜像长 ${got} > ${want}，布局已变"
    fi
    if [ "$got" -lt "$want" ]; then
        truncate -s "$want" "$PART" ||
            die "${E_IO}" "补齐末尾填充扇区失败: ${PART}"
    fi
    mv -f "$PART" "$DEST"
}

post_iso()
{
    local -a flags=()
    if [ "$MD5" -ne 1 ]; then
        flags+=(--no-md5)
    fi
    iso_post "$DEST" "${WORK}/site.ks" "$VOLID" "$WORK" "${flags[@]}" ||
        die "${E_IO}" "站点介质后处理失败（日志 ${WORK}/logs）"
}

sum_of()
{
    local sum rest
    read -r sum rest < <(sha256sum "$1") || return 1
    printf '%s\n' "$sum"
}

write_meta()
{
    local sha="$1" src_sum
    printf '%s  %s\n' "$sha" "$NAME" >"${DEST}.sha256"
    src_sum="$(sum_of "$SRC")" || die "${E_IO}" "sha256sum 失败: ${SRC}"
    {
        printf '# AirymaxOS site medium manifest\n'
        printf 'name=%s\n' "$NAME"
        printf 'volid=%s\n' "$VOLID"
        printf 'disk=%s\n' "$DISK"
        printf 'parts esp=%s boot=%s swap=%s root=%s\n' \
            "$ESP" "$BOOT" "$SWAP" "$ROOT"
        printf 'iso %s %s\n' "$sha" "$NAME"
        printf 'ks %s site.ks\n' "$(sum_of "${WORK}/site.ks")"
        printf 'base %s %s\n' "$src_sum" "$(basename "$SRC")"
    } >"${OUT_ABS}/site-manifest.txt"
}

report()
{
    local check="已植入，rd.live.check 可用"
    if [ "$MD5" -ne 1 ]; then
        check="已跳过（--no-md5，仅限调试）"
    fi
    printf '\n站点介质已就绪\n'
    printf '  镜像    %s\n' "$DEST"
    printf '  卷标    %s（沿用源镜像）\n' "$VOLID"
    printf '  磁盘    %s  esp=%s boot=%s swap=%s root=%s\n' \
        "$DISK" "$ESP" "$BOOT" "$SWAP" "$ROOT"
    printf '  校验块  %s\n' "$check"
    printf '  引导    BIOS/UEFI 三元一致\n'
    printf '  校验和  %s\n' "$1"
    printf '  清单    %s\n' "${OUT_ABS}/site-manifest.txt"
}

main()
{
    parse_args "$@"
    OUT_ABS="$(out_guard site-iso "$OUT")"
    check_files
    need xorriso
    need python3
    need truncate
    need sha256sum
    if [ "$MD5" -eq 1 ]; then
        need implantisomd5
        need checkisomd5
    fi
    if [ -z "$VOLID" ]; then
        VOLID="$(iso_volid "$SRC")" ||
            die "${E_INVAL}" "无法读取源镜像卷标，请显式指定 --volid"
    fi
    check_volid
    prep
    derive
    rebuild
    pad_iso
    post_iso
    local sha
    sha="$(sum_of "$DEST")" || die "${E_IO}" "sha256sum 失败: ${DEST}"
    write_meta "$sha"
    report "$sha"
}

main "$@"
