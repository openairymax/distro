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
# （pyanaconda/modules/storage/bootloader/grub2.py 与 efi.py），这些包
# 不在包清单里，却必须能从载荷解析。安装器 GRUB2.packages 请求的是虚拟
# 名 grub2，上游由 grub2-pc 这类架构相关包提供；EFI 包同样按架构区分，
# 而 kickstart 无法表达架构条件，故在此按架构补齐。排除项同样照搬配方。
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
# 仓库地址来自配方，配方只能写一个源（anaconda 的 repo 行不接多值）。
# 构建环境另给一组同源的镜像根：默认取自 repo/mirrors.list（与装机镜像、
# 介质下载共用同一份声明），CLOSURE_MIRRORS 以空格分隔可覆盖，首项就是
# 配方里那个源的根。
#
# 镜像根之间是「换一个快照重试」的关系，不是同一个仓库的多个备用地址。
# 把两台主机的元数据挂在同一个 repo 段下当 failover，dnf 会各取一部分包，
# 解出的 NEVRA 组合没有任何一台主机保证过；于是同一份源码每次构建可能
# 解出不同的包集合，rpm 事务的拓扑序随之漂移，装机现场表现为依赖看似
# 齐全却事务失败（run 40896202774：coreutils 未进事务，glibc/bash 被压到
# 末尾，sound-theme-freedesktop 的 %post 报错后判死）。
#
# 因此每次求解只用单一镜像根：命中配方根的 baseurl 按同一相对路径改写到
# 该根，未命中前缀的地址（离线 file:// 与第三方仓库）原样保留，不做猜测；
# 某个根上的求解失败，整段事务换下一个根重来，上一个根已下的包一并丢弃，
# 避免两个快照的 NEVRA 混进同一份载荷。实际使用的根写入工作目录，使
# 「这份载荷来自哪个快照」事后可查。
#
# 拉取全程必须可见：2.5 GB 的传输一旦只写进日志文件，外部看到的就是
# 数十分钟静默，无法区分「在慢慢下」与「已经挂死」（run 40839355885 与
# 40850633573 都在这一段沉默 80 分钟后被人工取消）。因此求解期间按
# CLOSURE_BEAT 秒打印一行落盘进度，父进程据此判断这一段是否仍在推进。
#
# 调用约定：
#   closure_fetch KS ARCH PKGDIR WORK LOG
#                    新增包数写入 CL_NEW；收割到的文件名追加到调用方的
#                    NAMES 数组（与 collect_rpms 共用同一份载荷清单）；
#                    实际求解成功的镜像根留在 WORK/mirror-root.txt。
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
readonly CL_BEAT="${CLOSURE_BEAT:-30}"
readonly CL_MIRROR_LIST="${CL_ROOT}/repo/mirrors.list"
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
CL_MIRRORS=()
CL_ROOTS=()

# 镜像根表：每行一个根，# 起注释，空行跳过，行序即尝试顺序。
cl_mirrors()
{
    local line
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%%#*}"
        line="${line//[[:space:]]/}"
        if [ -n "$line" ]; then
            CL_MIRRORS+=("$line")
        fi
    done <"$1"
    return 0
}

cl_init_mirrors()
{
    if [ -n "${CLOSURE_MIRRORS:-}" ]; then
        # shellcheck disable=SC2206  # 镜像根不含空格，按空白切分即为预期语义
        CL_MIRRORS=(${CLOSURE_MIRRORS})
    elif [ -f "$CL_MIRROR_LIST" ]; then
        cl_mirrors "$CL_MIRROR_LIST"
    fi
}

# 把配方里的源改写到指定镜像根：只有命中首根前缀的地址才换根，其余
# （离线 file:// 与第三方仓库）原样返回。空根表示不做改写。
cl_base()
{
    local base="$1" root="$2"
    if [ -z "$root" ] || [ "${#CL_MIRRORS[@]}" -eq 0 ]; then
        printf '%s' "$base"
        return 0
    fi
    case "$base" in
    "${CL_MIRRORS[0]}"/*) printf '%s/%s' "$root" "${base#"${CL_MIRRORS[0]}"/}" ;;
    *) printf '%s' "$base" ;;
    esac
}

# 待尝试的快照序列。镜像表缺失时退化为只用配方里那一个源——宁可比预期
# 慢，也不猜地址；空串在这里代表「不改写」。
cl_roots()
{
    CL_ROOTS=("${CL_MIRRORS[@]}")
    [ "${#CL_ROOTS[@]}" -gt 0 ] || CL_ROOTS=("")
}

cl_repos()
{
    local ks="$1" cfg="$2" root="$3" name base cost
    : >"$cfg"
    while IFS=$'\t' read -r name base cost; do
        {
            printf '[%s]\n' "$name"
            printf 'name=%s\n' "$name"
            printf 'baseurl=%s\n' "$(cl_base "$base" "$root")"
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
    x86_64) CL_BOOT=(grub2-pc grub2-efi-x64 shim-x64 efibootmgr) ;;
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

cl_dlstat()
{
    local dl="$1" size
    size="$(du -sm "${dl}" 2>/dev/null | cut -f1)"
    printf '%s %s' "$(find "${dl}" -maxdepth 1 -type f -name '*.rpm' \
        2>/dev/null | wc -l)" "${size:-0}"
}

# 子进程存活期间每 CL_BEAT 秒报一行落盘量：父进程据此把「还在传」与
# 「已经挂死」分开。轮询粒度固定 1 秒，子进程退出后不会多等一个节拍。
cl_watch()
{
    local dl="$1" pid="$2" t0="$3" next=0 el n s
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        el=$(( $(date +%s) - t0 ))
        [ "$el" -ge "$next" ] || continue
        read -r n s <<<"$(cl_dlstat "$dl")"
        printf 'closure: 拉取中 files=%s size=%sMiB elapsed=%ss\n' "$n" "$s" "$el"
        next=$(( el + CL_BEAT ))
    done
}

# 按镜像根逐个求解，每个根内最多 CL_TRY 次事务级重试（重试复用已下的包，
# 只补残缺部分）。换根即换快照，上轮残留的包必须先清掉：不同快照的 NEVRA
# 一起留在沙箱里会被当作本轮载荷收割，等于把两个快照混进同一份镜像。
cl_try()
{
    local ks="$1" arch="$2" pkg="$3" work="$4" log="$5"
    local root label n rc t0 pid
    : >"$log"
    for root in "${CL_ROOTS[@]}"; do
        label="${root:-<配方原址>}"
        cl_repos "$ks" "${work}/repos/closure.repo" "$root" || return 1
        printf '%s\n' "$label" >"${work}/mirror-root.txt"
        rm -rf "${work}/dl"
        n=1
        while :; do
            printf '\n## 求解尝试 %d 镜像根=%s\n' "$n" "$label" >>"$log"
            t0="$(date +%s)"
            mkdir -p "${work}/dl"
            cl_run "$work" "$arch" "$pkg" "$log" &
            pid=$!
            cl_watch "${work}/dl" "$pid" "$t0"
            wait "$pid" && rc=0 || rc=$?
            [ "$rc" -eq 0 ] && return 0
            [ "$n" -lt "$CL_TRY" ] || break
            printf 'closure: 镜像根 %s 第 %d 次求解未完成，%d 秒后重试\n' \
                "$label" "$n" "$CL_WAIT" >&2
            n=$((n + 1))
            sleep "$CL_WAIT"
        done
        printf 'closure: 镜像根 %s 求解失败，换下一个根\n' "$label" >&2
    done
    return 1
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
    cl_init_mirrors
    cl_roots
    closure_specs "$ks" || return 1
    cl_args "$arch" || return 1
    cl_try "$ks" "$arch" "$pkg" "$work" "$log" || return 1
    cl_harvest "${work}/dl" "$pkg" || return 1
    cl_audit "${work}/dl" "$pkg" || return 1
    rm -rf "${work}/root" "${work}/dl"
}
