#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# build-desktop.sh — AirymaxOS 镜像介质组装驱动
#
# 把 build-rpms 与 build-kernel 的产物收敛成自包含离线仓库，随基础 ISO
# 一起分发，再委派 build-iso.sh 完成 kickstart 注入与引导复核。minimal
# 与 desktop 两个剖面共用这一路径。本产品自有包只从 ISO 内
# /airymax/Packages 解析（cost 最低，保证 airymaxos-* 优先于上游同名
# 能力）。
#
# --closure 追加安装闭包收割：按 kickstart 声明的仓库求解一次完整事务，
# 把其中全部 RPM 收进同一载荷，安装期只读 file:// 仓库而不再依赖公网。
# 收割在构建容器内完成，载荷因此同时包含基础用户空间与 UKUI 闭包。
# 出镜像前再校验载荷仓库仍携带配方的环境组，避免交互安装与按环境解析
# 在现场才失败。
#
# --closure-only 把收割单独拎出来：跨境链路对托管运行商限速时，CI 的
# 180 分钟组装预算下不完 2.5 GB 闭包，而一台快机器几分钟就能收完，产物
# 再由 CI 侧注入缓存池（ci/gates/pool-seed.sh）。这条路径只做收割，不出
# ISO，也不要求 --iso/--rpms。收割机通常没有自建 RPM，配方点名的
# airymaxos-* 远端并不存在，--closure-skip 用来排除它们；排除项下的事务
# 不完整，因此即使 CLOSURE_LOCK_WRITE=1 也不写闭包清单。
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

# shellcheck source=lib/outdir.sh
. "${DISTRO_ROOT}/scripts/lib/outdir.sh"
# shellcheck source=lib/arch.sh
. "${DISTRO_ROOT}/scripts/lib/arch.sh"
# shellcheck source=lib/iso.sh
. "${DISTRO_ROOT}/scripts/lib/iso.sh"
# shellcheck source=lib/closure.sh
. "${DISTRO_ROOT}/scripts/lib/closure.sh"
# shellcheck source=lib/guard.sh
. "${DISTRO_ROOT}/scripts/lib/guard.sh"

BASE=""
KS=""
OUT=""
ARCH=""
VOLID="AIRYMAXOS"
VERSION=""
GPG_KEY=""
MD5=1
CLOSURE=0
CLOSURE_ONLY=0
LOCK=""
RPMS=()
ADDS=()
REQUIRE=()
SKIPS=()
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
  --ks FILE          安装 kickstart（必填，须通过 ks_lint）
  --out DIR          产物目录（必须在源码区之外，必填）
  --rpms DIR         待汇集的 RPM 目录，递归扫描，可重复（必填）
  --require PKG      离线仓库必须提供的包名，可重复；缺省为
                     airymaxos-release、airymaxos-system、airymaxos-kernel
                     及其 core/modules 子包
  --arch ARCH        x86_64|aarch64，缺省为宿主
  --volid NAME       ISO 卷标，缺省 AIRYMAXOS
  --version VER      版本号，缺省取 release/os-release 的 VERSION_ID
  --add PATH         额外加入 ISO 的文件或目录，可重复
  --gpg-key KEYID    生成 ISO 分离签名 .asc
  --no-md5           跳过 implantisomd5（仅限调试）
  --closure          收割完整安装闭包：按 kickstart 仓库求解安装事务并
                     将全部 RPM 收入载荷，装机不再访问公网（需 dnf 与
                     同架构宿主）
  --closure-only     只收割闭包并退出：不出 ISO，不要求 --iso 与 --rpms，
                     产物为 DIR/payload/airymax 下的离线仓库
  --closure-skip GLOB
                     在线求解时排除匹配 GLOB 的包，可重复；用于没有自建
                     RPM 的收割机（airymaxos-* 远端不存在），需与
                     --closure 同用
  --closure-lock FILE
                     闭包清单：缓存池与之逐项吻合时完全离线重放，不再
                     取任何远端元数据；缺项或摘要不符则回落在线求解
  -h, --help         显示本帮助

产出:
  DIR/payload/airymax/                离线仓库与载荷清单（注入 ISO 根）
  DIR/iso/airymaxos-<ver>-<arch>.iso  可引导安装镜像
  DIR/iso/iso-manifest.txt            基础介质与 ISO 产物清单

  --require 必须覆盖 kickstart %packages 的离线依赖：minimal 剖面只要求
  内核三包，desktop 剖面另需发行版标识与系统包。任一所列包缺失即拒绝出
  镜像，避免安装现场才暴露解析失败。
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

need_closure()
{
    if [ "$CLOSURE" -ne 1 ]; then
        return 0
    fi
    need dnf
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
        --require) optarg "$1" "$#"; REQUIRE+=("$2"); shift 2 ;;
        --arch) optarg "$1" "$#"; ARCH="$2"; shift 2 ;;
        --volid) optarg "$1" "$#"; VOLID="$2"; shift 2 ;;
        --version) optarg "$1" "$#"; VERSION="$2"; shift 2 ;;
        --add) optarg "$1" "$#"; ADDS+=("$2"); shift 2 ;;
        --gpg-key) optarg "$1" "$#"; GPG_KEY="$2"; shift 2 ;;
        --no-md5) MD5=0; shift ;;
        --closure) CLOSURE=1; shift ;;
        --closure-only) CLOSURE=1; CLOSURE_ONLY=1; shift ;;
        --closure-skip) optarg "$1" "$#"; SKIPS+=("$2"); shift 2 ;;
        --closure-lock) optarg "$1" "$#"; LOCK="$2"; shift 2 ;;
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

check_args()
{
    local dir add pkg skip
    if [ "$CLOSURE_ONLY" -eq 0 ]; then
        [ -n "$BASE" ] || die "${E_INVAL}" "--iso 必填"
        [ -f "$BASE" ] || die "${E_INVAL}" "基础 ISO 不存在: ${BASE}"
    fi
    [ -n "$KS" ] || die "${E_INVAL}" "--ks 必填"
    [ -f "$KS" ] || die "${E_INVAL}" "kickstart 不存在: ${KS}"
    if [ "$CLOSURE_ONLY" -eq 0 ]; then
        [ "${#RPMS[@]}" -gt 0 ] ||
            die "${E_INVAL}" "--rpms 至少给出一个目录"
    fi
    for dir in "${RPMS[@]}"; do
        [ -d "$dir" ] || die "${E_INVAL}" "--rpms 目录不存在: ${dir}"
    done
    for pkg in "${REQUIRE[@]}"; do
        [ -n "$pkg" ] || die "${E_INVAL}" "--require 包名不得为空"
    done
    for skip in "${SKIPS[@]}"; do
        [ -n "$skip" ] || die "${E_INVAL}" "--closure-skip 不得为空"
    done
    if [ "${#SKIPS[@]}" -gt 0 ] && [ "$CLOSURE" -eq 0 ]; then
        die "${E_INVAL}" "--closure-skip 需与 --closure 同时使用"
    fi
    [ -f "$CL_COMPS" ] || die "${E_INVAL}" "comps 定义缺失: ${CL_COMPS}"
    [ -f "$CL_SPEC" ] || die "${E_INVAL}" "规格提取器缺失: ${CL_SPEC}"
    if [ -n "$LOCK" ]; then
        [ "$CLOSURE" -eq 1 ] ||
            die "${E_INVAL}" "--closure-lock 需与 --closure 同时使用"
        [ -f "$LOCK" ] || die "${E_INVAL}" "闭包清单不存在: ${LOCK}"
    fi
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
    # 只收割闭包时载荷可以从空开始：本机不必有自建 RPM。
    if [ "${#NAMES[@]}" -eq 0 ] && [ "$CLOSURE_ONLY" -eq 0 ]; then
        die "${E_INVAL}" "--rpms 目录内没有可用的 RPM"
    fi
}

# 排除项以环境变量交给 closure.sh：驱动与收割库之间没有别的参数通道，
# 环境变量在子 shell 与测试直调库时同样可见。
export_skip()
{
    [ "${#SKIPS[@]}" -gt 0 ] || return 0
    CLOSURE_SKIP="${SKIPS[*]}"
    export CLOSURE_SKIP
}

closure_default()
{
    if [ "${#REQUIRE[@]}" -ne 0 ]; then
        return 0
    fi
    REQUIRE=(airymaxos-release airymaxos-system airymaxos-kernel \
        airymaxos-kernel-core airymaxos-kernel-modules)
}

check_closure()
{
    local want base have
    for want in "${REQUIRE[@]}"; do
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
    comps_sum="$(sum_of "$CL_COMPS")" ||
        die "${E_IO}" "sha256sum 失败: ${CL_COMPS}"
    {
        printf '# AirymaxOS payload manifest\n'
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

derive_ks()
{
    local out="${OUT_ABS}/install.ks" log="${OUT_ABS}/logs/install-ks.log"
    python3 "$CL_SPEC" install "$KS" >"$out" 2>"$log" ||
        die "${E_INVAL}" "安装期配方投影失败（日志 ${log}）"
    KS="$out"
    printf '安装期配方: %s\n' "$KS"
}

make_repo()
{
    local log="${OUT_ABS}/logs/createrepo.log"
    if ! createrepo_c --general-compress-type gz \
        --groupfile "$CL_COMPS" "$PKGDIR" >"$log" 2>&1; then
        die "${E_IO}" "createrepo_c 失败（日志 ${log}）"
    fi
    [ -f "${PKGDIR}/repodata/repomd.xml" ] ||
        die "${E_IO}" "仓库元数据缺失: ${PKGDIR}/repodata/repomd.xml"
    grep -q 'type="group"' "${PKGDIR}/repodata/repomd.xml" ||
        die "${E_IO}" "仓库缺少 comps 分组元数据"
}

check_comps()
{
    local env log="${OUT_ABS}/logs/comps.log"
    : >"$log"
    while IFS= read -r env; do
        [ -n "$env" ] || continue
        python3 "$CL_SPEC" verify "$PKGDIR" --env "$env" >>"$log" 2>&1 ||
            die "${E_IO}" "载荷 comps 缺环境 ${env}（日志 ${log}）"
    done < <(python3 "$CL_SPEC" envs "$KS")
    # 只有闭包收割才宣称载荷可离线安装；未收割的载荷仅含本地产物，
    # 按安装事务解析没有意义。
    if [ "$CLOSURE" -eq 1 ]; then
        python3 "$CL_SPEC" resolve "$KS" "$PKGDIR" --comps "$CL_COMPS" >>"$log" 2>&1 ||
            die "${E_IO}" "载荷缺 comps 成员（日志 ${log}）"
    fi
}

run_closure()
{
    if [ "$CLOSURE" -ne 1 ]; then
        return 0
    fi
    local work="${OUT_ABS}/closure" log="${OUT_ABS}/logs/closure.log"
    CL_LOCK="$LOCK"
    closure_fetch "$KS" "$ARCH" "$PKGDIR" "$work" "$log" ||
        die "${E_IO}" "安装闭包收割失败（日志 ${log}）"
    printf '闭包收割: 新增 %d 个 RPM（总计 %d）\n' "$CL_NEW" "${#NAMES[@]}"
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
    local name
    name="$(iso_name "${OUT_ABS}/iso")" ||
        die "${E_IO}" "ISO 清单缺失或没有 name 字段: ${OUT_ABS}/iso/iso-manifest.txt"
    OUT_ISO="${OUT_ABS}/iso/${name}"
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
    if [ "$CLOSURE_ONLY" -eq 0 ]; then
        need xorriso
    fi
    need sha256sum
    need find
    need sort
    need python3
    need_closure
    export_skip
    prep_payload
    collect_rpms
    closure_default
    make_repo
    run_closure
    if [ "$CLOSURE_ONLY" -eq 1 ]; then
        printf '闭包池: %s（%d 个 RPM）\n' "$PKGDIR" "${#NAMES[@]}"
        return 0
    fi
    guard_payload "$PKGDIR" "$OUT_ABS" ||
        die "${E_IO}" "载荷兜底重打包失败"
    make_repo
    check_comps
    check_closure
    write_payload
    derive_ks
    printf '汇集 RPM: %d 个（架构 %s）\n' "${#NAMES[@]}" "$ARCH"
    run_iso
    iso_path
    check_payload
    printf '产物: %s\n' "$OUT_ISO"
    printf '载荷: %s\n' "$PKGDIR"
    printf '清单: %s\n' "${OUT_ABS}/iso/iso-manifest.txt"
}

main "$@"
