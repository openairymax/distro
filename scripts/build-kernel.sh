#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# build-kernel.sh — AirymaxOS 内核归档与 RPM 构建入口
#
# 内核源码树同时是 airy 子系统的开发树，直接就地执行 kbuild 会在源码区
# 留下 .config、*.o 与模块符号（0.0.3 任务方案 §3.1）。因此构建拆成两步：
# 先用 git archive 从干净的 HEAD 导出确定性 tarball，再交给 build-rpms.sh
# 在源码区之外展开（190-distribution/05-reproducible-build.md）。
#
# 归档的确定性来自两点：git archive 以提交时间作为成员 mtime；gzip -n 不
# 写入归档名与时间。同一提交重复归档必须得到同一 SHA-256，构建清单因此
# 可复核。
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

OUT=""
KDIR=""
ARCH=""
JOBS=""
DIST=""
REPO=0
STREAM="BaseOS"
GPG_KEY=""
OUT_ABS=""
SRC=""
KV=""
TARBALL=""

readonly SPEC="${DISTRO_ROOT}/specs/kernel/airymaxos-kernel.spec"

usage()
{
    cat <<'EOF'
用法: scripts/build-kernel.sh --out DIR [选项]

  --out DIR          产物目录（必须在源码区之外，必填）
  --kernel DIR       内核源码树，缺省为 distro 同级的 kernel
  --arch ARCH        x86_64|aarch64|riscv64，缺省为宿主
  --jobs N           并行度，缺省由 build-rpms.sh 取 nproc
  --dist TAG         定义 %dist（如 .airy03），缺省沿用环境
  --repo             构建后生成 dnf 仓库元数据
  --stream NAME      BaseOS|AppStream|updates，缺省 BaseOS
  --gpg-key KEYID    仓库签名密钥（--repo 时必填）
  -h, --help         显示本帮助

产出:
  DIR/src/airymaxos-kernel-<ver>.tar.gz         确定性源码归档
  DIR/src/airymaxos-kernel-<ver>.tar.gz.sha256  归档校验和
  DIR/RPMS/<arch>/*.rpm                         内核 RPM
  DIR/build-manifest.txt                        配方与 RPM 的 SHA-256 清单
EOF
}

die()
{
    local code="$1"
    shift
    printf 'build-kernel: %s\n' "$*" >&2
    exit "${code}"
}

need()
{
    command -v "$1" >/dev/null 2>&1 ||
        die "${E_NOSUP}" "缺少内核构建工具: $1"
}

optarg()
{
    [ "$2" -ge 2 ] || die "${E_INVAL}" "$1 缺少参数"
}

parse_args()
{
    while [ $# -gt 0 ]; do
        case "$1" in
        --out) optarg "$1" "$#"; OUT="$2"; shift 2 ;;
        --kernel) optarg "$1" "$#"; KDIR="$2"; shift 2 ;;
        --arch) optarg "$1" "$#"; ARCH="$2"; shift 2 ;;
        --jobs) optarg "$1" "$#"; JOBS="$2"; shift 2 ;;
        --dist) optarg "$1" "$#"; DIST="$2"; shift 2 ;;
        --stream) optarg "$1" "$#"; STREAM="$2"; shift 2 ;;
        --gpg-key) optarg "$1" "$#"; GPG_KEY="$2"; shift 2 ;;
        --repo) REPO=1; shift ;;
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
    x86_64|aarch64|riscv64) ;;
    *) die "${E_INVAL}" "内核不支持的架构: $ARCH" ;;
    esac
}

check_kdir()
{
    local top inside
    if [ -z "$KDIR" ]; then
        KDIR="${DISTRO_ROOT}/../kernel"
    fi
    [ -d "$KDIR" ] || die "${E_INVAL}" "内核源码树不存在: ${KDIR}"
    KDIR="$(cd "$KDIR" && pwd -P)"
    [ -f "${KDIR}/Makefile" ] || die "${E_INVAL}" "缺少内核 Makefile: ${KDIR}"
    top="$(git -C "$KDIR" rev-parse --show-toplevel 2>/dev/null || true)"
    [ "$top" = "$KDIR" ] ||
        die "${E_INVAL}" "内核源码树必须是仓库根目录: ${KDIR}"
    inside="$(git -C "$KDIR" rev-parse --verify HEAD 2>/dev/null || true)"
    [ -n "$inside" ] || die "${E_INVAL}" "内核源码树没有提交: ${KDIR}"
}

check_tree()
{
    local dirty
    dirty="$(git -C "$KDIR" status --porcelain --untracked-files=no)" ||
        die "${E_IO}" "无法读取内核工作树状态: ${KDIR}"
    if [ -n "$dirty" ]; then
        printf '%s\n' "$dirty" | sed 's/^/  /' >&2
        die "${E_INVAL}" "内核工作树存在未提交改动，归档将与配方不一致"
    fi
    if [ -e "${KDIR}/.config" ]; then
        die "${E_INVAL}" \
            "内核源码树存在 .config，禁止在源码区构建（${KDIR}）"
    fi
}

make_ver()
{
    local key eq val rest v="" p="" s="" e=""
    while read -r key eq val rest; do
        case "$key" in
        VERSION) v="$val" ;;
        PATCHLEVEL) p="$val" ;;
        SUBLEVEL) s="$val" ;;
        EXTRAVERSION) e="$val" ;;
        esac
    done < "${KDIR}/Makefile"
    case "${v}${p}${s}" in
    ''|*[!0-9]*) die "${E_INVAL}" "内核版本字段非法: ${v}.${p}.${s}" ;;
    esac
    [ -z "$e" ] ||
        die "${E_INVAL}" "内核 Makefile 的 EXTRAVERSION 必须为空: ${e}"
    printf '%s.%s.%s\n' "$v" "$p" "$s"
}

spec_ver()
{
    local key val rest
    while read -r key val rest; do
        if [ "$key" = "%global" ] && [ "$val" = "kernel_version" ]; then
            printf '%s\n' "${rest%%[[:space:]]*}"
            return 0
        fi
    done < "$SPEC"
    return 1
}

check_ver()
{
    local want
    [ -f "$SPEC" ] || die "${E_INVAL}" "内核配方不存在: ${SPEC}"
    KV="$(make_ver)"
    want="$(spec_ver)" ||
        die "${E_INVAL}" "配方缺少 %global kernel_version: ${SPEC}"
    if [ "$KV" != "$want" ]; then
        die "${E_INVAL}" \
            "内核版本漂移: Makefile ${KV}，配方 ${want}"
    fi
}

prep_out()
{
    OUT_ABS="$(out_guard build-kernel "$OUT")"
    SRC="${OUT_ABS}/src"
    TARBALL="${SRC}/airymaxos-kernel-${KV}.tar.gz"
    if ! mkdir -p "$SRC"; then
        die "${E_IO}" "无法创建归档目录: ${SRC}"
    fi
}

make_tar()
{
    local tmp="${TARBALL}.part"
    rm -f "$tmp" "${TARBALL}.sha256"
    if ! git -C "$KDIR" archive --format=tar \
        --prefix="airymaxos-kernel-${KV}/" HEAD | gzip -n -9 > "$tmp"; then
        rm -f "$tmp"
        die "${E_IO}" "内核归档失败: ${KDIR}"
    fi
    if [ ! -s "$tmp" ]; then
        rm -f "$tmp"
        die "${E_IO}" "内核归档为空: ${KDIR}"
    fi
    mv -f "$tmp" "$TARBALL"
    (cd "$SRC" && sha256sum "$(basename "$TARBALL")" > "${TARBALL}.sha256") ||
        die "${E_IO}" "归档校验和生成失败: ${TARBALL}"
    printf '归档: %s\n' "$TARBALL"
    printf '校验: %s\n' "$(<"${TARBALL}.sha256")"
}

run_build()
{
    local -a args=(--spec "$SPEC" --src-dir "$SRC" --out "$OUT_ABS"
        --arch "$ARCH")
    if [ -n "$JOBS" ]; then
        args+=(--jobs "$JOBS")
    fi
    if [ -n "$DIST" ]; then
        args+=(--dist "$DIST")
    fi
    if [ "$REPO" -eq 1 ]; then
        args+=(--repo --stream "$STREAM")
    fi
    if [ -n "$GPG_KEY" ]; then
        args+=(--gpg-key "$GPG_KEY")
    fi
    exec "${DISTRO_ROOT}/scripts/build-rpms.sh" "${args[@]}"
}

main()
{
    parse_args "$@"
    check_arch
    check_kdir
    check_tree
    check_ver
    need git
    need gzip
    need sha256sum
    prep_out
    make_tar
    run_build
}

main "$@"
