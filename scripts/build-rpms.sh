#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# build-rpms.sh — AirymaxOS RPM 批量构建驱动
#
# 用法与产出见 usage()。约束：--out 必须在源码区之外（0.0.3 任务方案
# §3.1）；配方须先通过 ci/run-lint.sh；跨架构构建由 mock profile 承担。
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
# shellcheck source=lib/log.sh
. "${DISTRO_ROOT}/scripts/lib/log.sh"

OUT=""
ARCH=""
JOBS=""
DIST=""
REPO=0
STREAM="BaseOS"
GPG_KEY=""
NODEPS=0
SPECS=()
SPEC_DIRS=()
SRC_DIRS=()
DEFS=()
OUT_ABS=""
WORK=""
TOPDIR=""

usage()
{
    cat <<'EOF'
用法: scripts/build-rpms.sh --out DIR [选项]

  --out DIR          产物输出目录（必须在源码区之外，必填）
  --spec FILE        指定配方，可重复
  --spec-dir DIR     收集 DIR/*.spec，可重复；缺省为 distro/specs
  --src-dir DIR      Source 额外搜索目录，可重复
  --arch ARCH        x86_64|aarch64|riscv64|ppc64le|loongarch64，
                     缺省为宿主
  --jobs N           MAKEFLAGS 并行度，缺省为 nproc
  --dist TAG         定义 %dist（如 .airy03），缺省沿用环境
  --define "N V"     追加 rpmbuild 宏，可重复；值不得为空
                     （如 --define "cross_prefix aarch64-linux-gnu-"）
  --nodeps           跳过 BuildRequires 解析，供无 rpmdb 的构建机使用
  --repo             生成 dnf 仓库元数据
  --stream NAME      BaseOS|AppStream|updates，缺省 BaseOS
  --gpg-key KEYID    仓库签名密钥（--repo 时必填）
  -h, --help         显示本帮助

产出:
  DIR/RPMS/<arch>/*.rpm        构建产物
  DIR/repo/<stream>/<arch>/    可选 dnf 仓库（repodata 已签名）
  DIR/build-manifest.txt       配方与 RPM 的 SHA-256 清单
EOF
}

die()
{
    local code="$1"
    shift
    printf 'build-rpms: %s\n' "$*" >&2
    exit "${code}"
}

need()
{
    command -v "$1" >/dev/null 2>&1 ||
        die "${E_NOSUP}" "缺少构建工具: $1"
}

optarg()
{
    [ "$2" -ge 2 ] || die "${E_INVAL}" "$1 缺少参数"
}

def_split()
{
    local raw="$1" name val
    name="${raw%%[[:space:]]*}"
    val="${raw#"$name"}"
    val="${val#"${val%%[![:space:]]*}"}"
    [ -n "$name" ] && [ -n "$val" ] || return 1
}

check_def()
{
    def_split "$1" ||
        die "${E_INVAL}" "--define 必须为 \"名字 值\" 形式: ${1}"
}

parse_args()
{
    while [ $# -gt 0 ]; do
        case "$1" in
        --out) optarg "$1" "$#"; OUT="$2"; shift 2 ;;
        --spec) optarg "$1" "$#"; SPECS+=("$2"); shift 2 ;;
        --spec-dir) optarg "$1" "$#"; SPEC_DIRS+=("$2"); shift 2 ;;
        --src-dir) optarg "$1" "$#"; SRC_DIRS+=("$2"); shift 2 ;;
        --arch) optarg "$1" "$#"; ARCH="$2"; shift 2 ;;
        --jobs) optarg "$1" "$#"; JOBS="$2"; shift 2 ;;
        --dist) optarg "$1" "$#"; DIST="$2"; shift 2 ;;
        --define) optarg "$1" "$#"; check_def "$2"
            DEFS+=("$2"); shift 2 ;;
        --nodeps) NODEPS=1; shift ;;
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
    x86_64|aarch64|riscv64|ppc64le|loongarch64) ;;
    *) die "${E_INVAL}" "不支持的架构: $ARCH" ;;
    esac
}

check_jobs()
{
    if [ -z "$JOBS" ]; then
        JOBS="$(nproc 2>/dev/null || printf '1\n')"
    fi
    case "$JOBS" in
    ''|*[!0-9]*) die "${E_INVAL}" "--jobs 必须为正整数: $JOBS" ;;
    esac
    if [ "$JOBS" -lt 1 ]; then
        die "${E_INVAL}" "--jobs 必须为正整数: $JOBS"
    fi
}

check_out()
{
    OUT_ABS="$(out_guard build-rpms "$OUT")"
}

collect_specs()
{
    local dir file
    if [ "${#SPECS[@]}" -eq 0 ] && [ "${#SPEC_DIRS[@]}" -eq 0 ]; then
        SPEC_DIRS=("${DISTRO_ROOT}/specs")
    fi
    for dir in "${SPEC_DIRS[@]}"; do
        if [ ! -d "$dir" ]; then
            die "${E_INVAL}" "配方目录不存在: $dir"
        fi
        while IFS= read -r file; do
            SPECS+=("$file")
        done < <(find "$dir" -maxdepth 1 -type f -name '*.spec' | sort)
    done
    if [ "${#SPECS[@]}" -eq 0 ]; then
        die "${E_INVAL}" "未找到配方（--spec/--spec-dir）"
    fi
}

uniq_specs()
{
    local path name
    local -A seen=()
    local -A names=()
    local keep=()
    for path in "${SPECS[@]}"; do
        if [ ! -f "$path" ]; then
            die "${E_INVAL}" "配方不存在: $path"
        fi
        path="$(cd "$(dirname "$path")" && pwd -P)/$(basename "$path")"
        if [ -n "${seen[$path]:-}" ]; then
            continue
        fi
        name="$(basename "$path")"
        if [ -n "${names[$name]:-}" ]; then
            die "${E_EXIST}" "配方重名，无法同批构建: $name"
        fi
        seen[$path]=1
        names[$name]=1
        keep+=("$path")
    done
    SPECS=("${keep[@]}")
}

find_src()
{
    local name="$1" dir hit
    local hits=()
    shift
    for dir in "$@"; do
        if [ ! -d "$dir" ]; then
            continue
        fi
        hits=()
        while IFS= read -r hit; do
            hits+=("$hit")
        done < <(find "$dir" \( -name .git -prune \) -o \
            \( -type f -name "$name" -print \) | sort)
        if [ "${#hits[@]}" -eq 0 ]; then
            continue
        fi
        if [ "${#hits[@]}" -ne 1 ]; then
            die "${E_INVAL}" "Source 命中多处: $name（${hits[*]}）"
        fi
        printf '%s\n' "${hits[0]}"
        return 0
    done
    return 1
}

stage_src()
{
    local src="$1" dst="$TOPDIR/SOURCES/$(basename "$1")"
    if [ ! -f "$dst" ]; then
        cp -p "$src" "$dst"
        return 0
    fi
    if ! cmp -s "$src" "$dst"; then
        die "${E_EXIST}" "同名 Source 内容冲突: $(basename "$src")"
    fi
}

source_names()
{
    sed -n -E \
        's/^(Source|Patch)[0-9]*:[[:space:]]*([^[:space:]]+).*/\2/p' "$1"
}

stage_spec()
{
    local spec="$1" base name file stem log
    base="$(dirname "$spec")"
    stem="$(basename "${spec%.spec}")"
    log="$WORK/logs/${stem}.rpmspec.log"
    if ! rpmspec -P "$spec" > "$WORK/expanded/${stem}.spec" 2> "$log"; then
        log_tail "$log"
        die "${E_INVAL}" "rpmspec 展开失败: $spec（日志 ${log}）"
    fi
    while IFS= read -r name; do
        name="$(basename "$name")"
        if ! file="$(find_src "$name" "$base" "${SRC_DIRS[@]}" \
            "$DISTRO_ROOT")"; then
            die "${E_IO}" "找不到 Source: $name（$spec），用 --src-dir 指定"
        fi
        stage_src "$file"
    done < <(source_names "$WORK/expanded/${stem}.spec")
}

lint_spec()
{
    local spec="$1" stem log
    if ! command -v rpmlint >/dev/null 2>&1; then
        printf '  跳过 rpmlint（未安装）: %s\n' "$(basename "$spec")"
        return 0
    fi
    stem="$(basename "${spec%.spec}")"
    log="$WORK/logs/${stem}.rpmlint.log"
    if ! rpmlint -i "$spec" > "$log" 2>&1; then
        log_tail "$log"
        die "${E_IO}" "rpmlint 未通过: $spec（日志 ${log}）"
    fi
}

prep_work()
{
    WORK="$OUT_ABS/work"
    TOPDIR="$WORK/rpmbuild"
    rm -rf "$WORK"
    mkdir -p "$TOPDIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS} \
        "$WORK/expanded" "$WORK/logs"
}

build_one()
{
    local spec="$1" stem log def
    local -a defs=()
    stem="$(basename "${spec%.spec}")"
    log="$WORK/logs/${stem}.build.log"
    if [ -n "$DIST" ]; then
        defs+=(--define "dist ${DIST}")
    fi
    for def in "${DEFS[@]}"; do
        defs+=(--define "$def")
    done
    if [ "$NODEPS" -eq 1 ]; then
        defs+=(--nodeps)
    fi
    if ! rpmbuild -bb "$spec" \
        --define "_topdir ${TOPDIR}" \
        --define "_sourcedir ${TOPDIR}/SOURCES" \
        --define "_builddir ${TOPDIR}/BUILD" \
        --define "_buildrootdir ${TOPDIR}/BUILDROOT" \
        --define "_rpmdir ${TOPDIR}/RPMS" \
        --target "${ARCH}" \
        "${defs[@]}" > "$log" 2>&1; then
        log_tail "$log"
        die "${E_IO}" "构建失败: ${stem}（日志 ${log}）"
    fi
}

collect_rpms()
{
    local file dest="$OUT_ABS/RPMS/${ARCH}"
    mkdir -p "$dest"
    while IFS= read -r file; do
        cp -p "$file" "$dest/"
    done < <(find "$TOPDIR/RPMS" -type f -name '*.rpm' | sort)
    if [ -z "$(find "$dest" -type f -name '*.rpm' -print -quit)" ]; then
        die "${E_IO}" "构建未产出任何 RPM: ${dest}"
    fi
}

sum_of()
{
    local sum rest
    read -r sum rest < <(sha256sum "$1") || return 1
    printf '%s\n' "$sum"
}

write_manifest()
{
    local file rel sum def manifest="$OUT_ABS/build-manifest.txt"
    {
        printf '# AirymaxOS RPM build manifest\n'
        printf 'arch=%s\n' "$ARCH"
        printf 'source_date_epoch=%s\n' "$SOURCE_DATE_EPOCH"
        if [ -n "$DIST" ]; then
            printf 'dist=%s\n' "$DIST"
        fi
        for def in "${DEFS[@]}"; do
            printf 'define=%s\n' "$def"
        done
        while IFS= read -r file; do
            sum="$(sum_of "$file")" ||
                die "${E_IO}" "sha256sum 失败: $file"
            printf 'spec %s %s\n' "$sum" "$(basename "$file")"
        done < <(printf '%s\n' "${SPECS[@]}" | sort)
        while IFS= read -r file; do
            rel="${file#"$OUT_ABS"/}"
            sum="$(sum_of "$file")" ||
                die "${E_IO}" "sha256sum 失败: $file"
            printf 'rpm %s %s\n' "$sum" "$rel"
        done < <(find "$OUT_ABS/RPMS" -type f -name '*.rpm' | sort)
    } > "$manifest"
}

check_repo()
{
    if [ "$REPO" -ne 1 ]; then
        return 0
    fi
    case "$STREAM" in
    BaseOS|AppStream|updates) ;;
    *) die "${E_INVAL}" "--stream 非法: $STREAM" ;;
    esac
    if [ -z "$GPG_KEY" ]; then
        die "${E_INVAL}" "--repo 需要 --gpg-key（客户端 repo_gpgcheck=1）"
    fi
}

make_repo()
{
    local dest="$OUT_ABS/repo/${STREAM}/${ARCH}" log
    log="$WORK/logs/createrepo.log"
    need createrepo_c
    need gpg
    mkdir -p "$dest"
    cp -p "$OUT_ABS/RPMS/${ARCH}/"*.rpm "$dest/"
    if ! createrepo_c --update "$dest" > "$log" 2>&1; then
        die "${E_IO}" "createrepo_c 失败（日志 ${log}）"
    fi
    if [ ! -f "$dest/repodata/repomd.xml" ]; then
        die "${E_IO}" "仓库元数据缺失: ${dest}/repodata/repomd.xml"
    fi
    if ! gpg --batch --yes --armor --detach-sign --local-user "$GPG_KEY" \
        --output "$dest/repodata/repomd.xml.asc" \
        "$dest/repodata/repomd.xml" > "$log" 2>&1; then
        die "${E_PERM}" "仓库元数据签名失败（密钥 ${GPG_KEY}，日志 ${log}）"
    fi
    printf '仓库: %s\n' "$dest"
}

main()
{
    local spec
    parse_args "$@"
    check_out
    check_arch
    check_jobs
    check_repo
    collect_specs
    uniq_specs
    need rpmbuild
    need rpmspec
    need sha256sum
    export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1468923400}"
    export TZ=UTC LANG=C.UTF-8 LC_ALL=C.UTF-8
    export MAKEFLAGS="-j${JOBS} --no-print-directory"
    prep_work
    printf '构建 %d 个配方 → %s（%s）\n' "${#SPECS[@]}" "$OUT_ABS" "$ARCH"
    for spec in "${SPECS[@]}"; do
        lint_spec "$spec"
        stage_spec "$spec"
    done
    for spec in "${SPECS[@]}"; do
        build_one "$spec"
    done
    collect_rpms
    if [ "$REPO" -eq 1 ]; then
        make_repo
    fi
    write_manifest
    printf '产物: %s\n' "$OUT_ABS/RPMS/${ARCH}"
    printf '清单: %s\n' "$OUT_ABS/build-manifest.txt"
}

main "$@"
