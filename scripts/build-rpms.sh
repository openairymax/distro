#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# build-rpms.sh — AirymaxOS RPM 批量构建驱动
#
# 用法与产出见 usage()。约束：--out 必须在源码区之外（0.0.3 任务方案
# §3.1）；配方须先通过 ci/run-lint.sh；跨架构构建由 mock profile 承担。
#
# 配方可用 `# spec-lint: source-bundle <相对配方目录的路径>` 声明整目录交付，
# 驱动在 staging 阶段把该目录打成确定性归档（<目录名>-<Version>.tar.gz），
# 配方以该文件名作为 Source 引用；归档不入库，由本次构建现场生成。
#
# 上游 tarball 用 `# spec-lint: source-url <文件名> <URL> <sha256>` 声明：
# 驱动下载到 --out 下的源缓存（跨轮复用，命中摘要即不再联网），逐字校验
# 摘要后才送进 rpmbuild。tarball 不入库，配方里的摘要就是唯一事实源；
# 只接受 https，取不到或摘要不符一律失败，不回落本地同名文件。
#
# 上游只发布 src.rpm、不发布裸 tarball 时用
# `# spec-lint: source-rpm <成员名> <src.rpm URL> <sha256>`：驱动下载并校验
# 官方 src.rpm，再从里面取出成员名对应的文件。摘要钉住的是整份 src.rpm，
# 成员内容随之被传递固定，判据仍是一个可复算的摘要。
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
# shellcheck source=lib/buildid.sh
. "${DISTRO_ROOT}/scripts/lib/buildid.sh"
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
FETCHED=()
OUT_ABS=""
WORK=""
TOPDIR=""
BUILD_ID=""
START_AT=""
START_EPOCH=0

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
  DIR/build-manifest.txt       配方与 RPM 的 SHA-256 清单，附 stage/arch 与
                               起止时刻、耗时（预算门禁的实测来源）；
                               source-url 取来的 tarball 记作 src 行

构建来源指纹（build-manifest.txt 的 build_id=）按 scripts/lib/buildid.sh 的
优先级取值：AIRYMAX_BUILD_ID → AIRYMAX_RUN_ID + AIRYMAX_COMMIT → git 短 sha
→ 配方摘要；同时以 airy_build_id 宏注入 rpmbuild，由 airymaxos-release 写入
os-release 的 BUILD_ID 与 /etc/airymaxos-build。
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

# 来源指纹在配方集合确定之后解析：最末一级取值来源是配方摘要，必须只覆盖
# 本次真实参与构建的配方，否则同一个指纹会对应不同产物。非法指纹直接失败，
# 不让空值或说明文字流进 os-release。
set_build_id()
{
    BUILD_ID="$(airy_build_id "$DISTRO_ROOT" "${SPECS[@]}")"
    airy_bid_ok "$BUILD_ID" ||
        die "${E_INVAL}" "构建来源指纹非法: ${BUILD_ID}"
    DEFS+=("airy_build_id ${BUILD_ID}")
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
    local src="$1" dst
    dst="$TOPDIR/SOURCES/$(basename "$1")"
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

bundle_cfg()
{
    local spec="$1" expanded="$2" base dir ver
    base="$(dirname "$spec")"
    ver="$(sed -n -E \
        's/^Version:[[:space:]]*([^[:space:]]+).*/\1/p' "$expanded")"
    ver="${ver%%$'\n'*}"
    while IFS= read -r dir; do
        [ -n "$dir" ] || continue
        if [ -z "$ver" ]; then
            printf 'build-rpms: 配方缺少 Version: %s\n' "$spec" >&2
            return 1
        fi
        dir="${base}/${dir}"
        if [ ! -d "$dir" ]; then
            printf 'build-rpms: 源目录不存在: %s\n' "$dir" >&2
            return 1
        fi
        printf '%s %s\n' "$dir" "$(basename "$dir")-${ver}.tar.gz"
    done < <(sed -n -E \
        's/^#[[:space:]]*spec-lint:[[:space:]]*source-bundle[[:space:]]+([^[:space:]]+)[[:space:]]*$/\1/p' \
        "$spec")
}

url_cfg()
{
    src_cfg source-url "$1"
}

rpm_cfg()
{
    src_cfg source-rpm "$1"
}

src_cfg()
{
    sed -n -E \
        "s/^#[[:space:]]*spec-lint:[[:space:]]*$1[[:space:]]+([^[:space:]]+)[[:space:]]+([^[:space:]]+)[[:space:]]+([0-9a-f]{64})[[:space:]]*\$/\1 \2 \3/p" \
        "$2"
}

digest_ok()
{
    local got
    got="$(sum_of "$1")" || return 1
    [ "$got" = "$2" ]
}

check_src_url()
{
    local name="$1" url="$2"
    case "$url" in
    https://*) ;;
    *) die "${E_INVAL}" "取源 URL 只接受 https: $name（$url）" ;;
    esac
    case "$name" in
    */*|'') die "${E_INVAL}" "取源文件名非法: $name" ;;
    esac
}

dl_src()
{
    local url="$1" sum="$2" dst="$3" tmp got
    if [ -f "$dst" ] && digest_ok "$dst" "$sum"; then
        return 0
    fi
    need curl
    mkdir -p "$(dirname "$dst")"
    tmp="$(dirname "$dst")/.$(basename "$dst").part.$$"
    if ! curl -fsSL --retry 3 --connect-timeout 20 -o "$tmp" "$url"; then
        rm -f "$tmp"
        die "${E_IO}" "下载源失败: $(basename "$dst")（$url）"
    fi
    if ! got="$(sum_of "$tmp")"; then
        rm -f "$tmp"
        die "${E_IO}" "sha256sum 失败: $tmp"
    fi
    if [ "$got" != "$sum" ]; then
        rm -f "$tmp"
        die "${E_IO}" "源摘要不符: $(basename "$dst") 期望 $sum 实得 $got"
    fi
    mv -f "$tmp" "$dst"
}

fetch_src()
{
    local name="$1" url="$2" sum="$3" dst
    check_src_url "$name" "$url"
    dst="$OUT_ABS/src-cache/$name"
    dl_src "$url" "$sum" "$dst"
    stage_src "$dst"
}

fetch_rpm()
{
    local member="$1" url="$2" sum="$3" rpm dir
    check_src_url "$member" "$url"
    rpm="$OUT_ABS/src-cache/$(basename "$url")"
    dl_src "$url" "$sum" "$rpm"
    need rpm2cpio
    need cpio
    dir="$WORK/extract/${member}.d"
    rm -rf "$dir"
    mkdir -p "$dir"
    if ! ( cd "$dir" && rpm2cpio "$rpm" | cpio -idm --quiet -- "$member" ); then
        die "${E_IO}" "从 src.rpm 取出成员失败: $member（$rpm）"
    fi
    if [ ! -f "$dir/$member" ]; then
        die "${E_IO}" "src.rpm 内不存在成员: $member"
    fi
    stage_src "$dir/$member"
}

make_bundle()
{
    local dir="$1" name="$2" dst="$TOPDIR/SOURCES/$2"
    need tar
    need gzip
    if ! tar -C "$(dirname "$dir")" \
        --sort=name --mtime="@${SOURCE_DATE_EPOCH}" \
        --owner=0 --group=0 --numeric-owner \
        --exclude=__pycache__ --exclude='*.pyc' \
        -cf - "$(basename "$dir")" | gzip -n > "$dst"; then
        rm -f "$dst"
        die "${E_IO}" "生成源归档失败: $name"
    fi
}

stage_spec()
{
    local spec="$1" base name file stem log cfg dir bname url sum
    local -A bundles=()
    local -A urls=()
    local -A rpms=()
    base="$(dirname "$spec")"
    stem="$(basename "${spec%.spec}")"
    log="$WORK/logs/${stem}.rpmspec.log"
    if ! rpmspec -P "$spec" > "$WORK/expanded/${stem}.spec" 2> "$log"; then
        log_tail "$log"
        die "${E_INVAL}" "rpmspec 展开失败: $spec（日志 ${log}）"
    fi
    if ! cfg="$(bundle_cfg "$spec" "$WORK/expanded/${stem}.spec")"; then
        die "${E_INVAL}" "源归档声明无效: $spec"
    fi
    while read -r dir bname; do
        [ -n "$bname" ] || continue
        bundles["$bname"]="$dir"
    done <<< "$cfg"
    while read -r bname url sum; do
        [ -n "$sum" ] || continue
        urls["$bname"]="$url $sum"
    done <<< "$(url_cfg "$spec")"
    while read -r bname url sum; do
        [ -n "$sum" ] || continue
        rpms["$bname"]="$url $sum"
    done <<< "$(rpm_cfg "$spec")"
    while IFS= read -r name; do
        name="$(basename "$name")"
        if [ -n "${bundles[$name]:-}" ]; then
            make_bundle "${bundles[$name]}" "$name"
            continue
        fi
        if [ -n "${urls[$name]:-}" ]; then
            read -r url sum <<< "${urls[$name]}"
            FETCHED+=("$sum $name")
            fetch_src "$name" "$url" "$sum"
            continue
        fi
        if [ -n "${rpms[$name]:-}" ]; then
            read -r url sum <<< "${rpms[$name]}"
            FETCHED+=("$sum $name")
            fetch_rpm "$name" "$url" "$sum"
            continue
        fi
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

reset_out()
{
    # 产物目录按「本轮结果」解释：抬高 release 后旧 NEVRA 若留在原地，会
    # 一并进 build-manifest.txt 与 createrepo 元数据，且两条路径都不会报错。
    local dest="$OUT_ABS/RPMS/${ARCH}"
    rm -rf "$dest" "$OUT_ABS/build-manifest.txt"
    if [ "$REPO" -eq 1 ]; then
        rm -rf "$OUT_ABS/repo/${STREAM}/${ARCH}"
    fi
    mkdir -p "$dest"
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
    local file rel sum def manifest="$OUT_ABS/build-manifest.txt" end_at end
    end="$(date -u +%s)"
    end_at="$(date -u -d "@${end}" +%Y-%m-%dT%H:%M:%SZ)"
    {
        printf '# AirymaxOS RPM build manifest\n'
        printf 'stage=rpm\n'
        printf 'arch=%s\n' "$ARCH"
        # 时刻与耗时只作台账，不参与可复现性比较：可复现指纹仍是 build_id
        # 与 source_date_epoch。有了这一段，预算才有实测依据（见
        # ci/gates/build-budget.sh），否则一轮变慢只能靠事故去发现。
        printf 'started_at=%s\n' "$START_AT"
        printf 'finished_at=%s\n' "$end_at"
        printf 'elapsed_s=%d\n' "$((end - START_EPOCH))"
        printf 'source_date_epoch=%s\n' "$SOURCE_DATE_EPOCH"
        if [ -n "$DIST" ]; then
            printf 'dist=%s\n' "$DIST"
        fi
        printf 'build_id=%s\n' "$BUILD_ID"
        for def in "${DEFS[@]}"; do
            printf 'define=%s\n' "$def"
        done
        while IFS= read -r file; do
            sum="$(sum_of "$file")" ||
                die "${E_IO}" "sha256sum 失败: $file"
            printf 'spec %s %s\n' "$sum" "$(basename "$file")"
        done < <(printf '%s\n' "${SPECS[@]}" | sort)
        # 按 URL 取源的条目把摘要写进清单：发布后回答「这一版取了哪个上游
        # tarball」不必回读配方注释，摘要与配方声明也在此对上同一行。
        if [ "${#FETCHED[@]}" -gt 0 ]; then
            while IFS= read -r file; do
                printf 'src %s\n' "$file"
            done < <(printf '%s\n' "${FETCHED[@]}" | sort -u)
        fi
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
    START_EPOCH="$(date -u +%s)"
    START_AT="$(date -u -d "@${START_EPOCH}" +%Y-%m-%dT%H:%M:%SZ)"
    check_out
    check_arch
    check_jobs
    check_repo
    collect_specs
    uniq_specs
    set_build_id
    need rpmbuild
    need rpmspec
    need sha256sum
    export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1468923400}"
    export TZ=UTC LANG=C.UTF-8 LC_ALL=C.UTF-8
    export MAKEFLAGS="-j${JOBS} --no-print-directory"
    prep_work
    reset_out
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
