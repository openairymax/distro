#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# closure.sh — 安装闭包收割（被 build-desktop.sh source）
#
# 安装期的 anaconda 与构建期的 dnf 必须解出同一个事务，否则 ISO 内的
# 离线仓库会在装机现场缺包，退回公网下载而在弱网或镜像抖动时失败。
# 本库用 kickstart 声明的仓库表与包清单在构建容器内跑一次真实解析，
# 把事务中的全部 RPM 收进载荷，使安装只读 file:// 仓库。
#
# 包规格来自 tools/ks_spec.py（SSoT）。配方以 %packages --nocore 关闭
# anaconda 隐式追加的 @core，基础用户空间改由 airymax-core 组显式声明，
# 因此两端求解条件一致。安装器在引导阶段又自行追加引导包
# （pyanaconda/modules/storage/bootloader/efi.py），这些包不在包清单里，
# 却必须能从载荷解析；EFI 包按架构区分而 kickstart 无法表达，故在此
# 按架构补齐。排除项同样照搬配方。
#
# 配方里的 @^环境 只对 anaconda 成立，dnf 命令行会把 ^ 当组名的一部分。
# 因此收割前按 comps 的 environment/grouplist 展开为 @组（ks_spec.py
# pkgs --comps），与环境安装读同一份定义。
#
# 收割要从公网拉取约 2.5 GB RPM，而镜像的并发限速会让单连接速率跌破
# 最低速率、HTTP/2 流的瞬时错误也会中止单个文件。因此求解限定并行度
# （并发越高越容易触发限速）、放宽最低速率与超时，并在事务级重试：
# dnf 会跳过 --downloaddir 里已完成的包，重试只补拉残缺部分，把链路
# 抖动从「整份镜像失败」降为「多花一轮时间」。
#
# 调用约定：
#   closure_fetch KS ARCH PKGDIR WORK LOG
#                    新增包数写入 CL_NEW；收割到的文件名追加到调用方的
#                    NAMES 数组（与 collect_rpms 共用同一份载荷清单）。
#   closure_specs    从配方填充 CL_SPECS/CL_EXCL，供测试单独调用。
#
# 退出码：0 表示事务内全部 RPM 已落盘并通过审计；非 0 时调用方据此
# 判定构建失败，不得带病产出镜像。
#
# 依赖：dnf、python3；PKGDIR 须已由调用方 createrepo_c 索引，否则
# 本地包与 comps 分组无法参与求解。
# ===========================================================================

CL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
readonly CL_ROOT
readonly CL_SPEC="${CL_ROOT}/tools/ks_spec.py"
readonly CL_COMPS="${CL_ROOT}/comps/airymaxos-comps.xml"
readonly CL_VER="${CLOSURE_VER:-24.03}"
readonly CL_TRY="${CLOSURE_TRY:-3}"
readonly CL_WAIT="${CLOSURE_WAIT:-10}"
readonly -a CL_DNF_OPTS=(
    --setopt=strict=1
    --setopt=max_parallel_downloads=4
    --setopt=timeout=60
    --setopt=minrate=200
    --setopt=retries=10
)

CL_SPECS=()
CL_EXCL=()
CL_ARGS=()
CL_BOOT=()
CL_NEW=0

cl_repos()
{
    local ks="$1" cfg="$2" name base cost
    : >"$cfg"
    while IFS=$'\t' read -r name base cost; do
        {
            printf '[%s]\n' "$name"
            printf 'name=%s\n' "$name"
            printf 'baseurl=%s\n' "$base"
            printf 'cost=%s\n' "$cost"
            printf 'enabled=1\n'
            printf 'gpgcheck=0\n'
            printf 'metadata_expire=0\n'
        } >>"$cfg"
    done < <(python3 "$CL_SPEC" repos --skip-file "$ks")
    [ -s "$cfg" ]
}

closure_specs()
{
    local kind spec
    CL_SPECS=()
    CL_EXCL=()
    while IFS=$'\t' read -r kind spec; do
        case "$kind" in
        install) CL_SPECS+=("$spec") ;;
        exclude) CL_EXCL+=("$spec") ;;
        esac
    done < <(python3 "$CL_SPEC" pkgs --comps "$CL_COMPS" "$1")
    [ "${#CL_SPECS[@]}" -gt 0 ]
}

cl_boot()
{
    case "$1" in
    x86_64) CL_BOOT=(grub2-efi-x64 shim-x64 efibootmgr) ;;
    aarch64) CL_BOOT=(grub2-efi-aa64 shim-aa64 efibootmgr) ;;
    *)
        printf 'closure: 未定义引导包架构 %s\n' "$1" >&2
        return 1
        ;;
    esac
}

cl_args()
{
    local list
    cl_boot "$1" || return 1
    CL_ARGS=("${CL_SPECS[@]}" "${CL_BOOT[@]}")
    list="$(IFS=,; printf '%s' "${CL_EXCL[*]}")"
    if [ -n "$list" ]; then
        CL_ARGS+=("--exclude=${list}")
    fi
}

cl_arch()
{
    local host
    host="$(uname -m)"
    [ "$1" = "$host" ] && return 0
    printf 'closure: 收割需本机架构 %s，宿主为 %s\n' "$1" "$host" >&2
    return 1
}

cl_run()
{
    local work="$1" arch="$2" pkg="$3" log="$4"
    mkdir -p "${work}/root" "${work}/dl" "${work}/repos"
    dnf -y install --downloadonly --downloaddir="${work}/dl" \
        --installroot="${work}/root" --releasever="$CL_VER" \
        --forcearch="$arch" --setopt="reposdir=${work}/repos" \
        "${CL_DNF_OPTS[@]}" --nogpgcheck \
        --repofrompath="airymax-local,${pkg}" \
        "${CL_ARGS[@]}" >>"$log" 2>&1
}

cl_try()
{
    local work="$1" arch="$2" pkg="$3" log="$4" n=1
    : >"$log"
    while :; do
        printf '\n## 求解尝试 %d\n' "$n" >>"$log"
        cl_run "$work" "$arch" "$pkg" "$log" && return 0
        [ "$n" -lt "$CL_TRY" ] || return 1
        printf 'closure: 第 %d 次求解未完成，%d 秒后重试\n' "$n" "$CL_WAIT" >&2
        n=$((n + 1))
        sleep "$CL_WAIT"
    done
}

cl_harvest()
{
    local dl="$1" pkg="$2" rpm base
    CL_NEW=0
    while IFS= read -r rpm; do
        base="$(basename "$rpm")"
        if [ -f "${pkg}/${base}" ]; then
            continue
        fi
        cp -p "$rpm" "${pkg}/${base}"
        NAMES+=("$base")
        CL_NEW=$((CL_NEW + 1))
    done < <(find "$dl" -maxdepth 1 -type f -name '*.rpm' | sort)
    [ "$CL_NEW" -gt 0 ]
}

cl_audit()
{
    local dl="$1" pkg="$2" rpm base miss=0
    while IFS= read -r rpm; do
        base="$(basename "$rpm")"
        if [ ! -f "${pkg}/${base}" ]; then
            [ "$miss" -gt 0 ] || printf 'closure: 载荷缺包 %s\n' "$base" >&2
            miss=$((miss + 1))
        fi
    done < <(find "$dl" -maxdepth 1 -type f -name '*.rpm')
    [ "$miss" -eq 0 ]
}

closure_fetch()
{
    local ks="$1" arch="$2" pkg="$3" work="$4" log="$5"
    rm -rf "$work"
    mkdir -p "${work}/repos"
    cl_arch "$arch" || return 1
    cl_repos "$ks" "${work}/repos/closure.repo" || return 1
    closure_specs "$ks" || return 1
    cl_args "$arch" || return 1
    cl_try "$work" "$arch" "$pkg" "$log" || return 1
    cl_harvest "${work}/dl" "$pkg" || return 1
    cl_audit "${work}/dl" "$pkg" || return 1
    rm -rf "${work}/root" "${work}/dl"
}
