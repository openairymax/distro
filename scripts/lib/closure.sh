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
# 「这份载荷来自哪个快照」事后可查。换根不只在失败时发生：镜像站限速而
# 传输仍在推进时，静默判据永远不会触发，因此另设窗口速率下限，低于下限
# 同样换根（CLOSURE_FLOOR，见 cl_watch）。
#
# 先试哪个根不再取决于镜像表的书写顺序：求解前用 tools/mirror_probe.py 对
# 每个根做一次定长抽样，按实测吞吐降序排列并丢掉不达标的根（cl_probe）。
# 行序是人工维护的，与此刻哪台主机快无关，按行序尝试等于把最慢的根放在
# 第一位，而每一根都要花掉数分钟才轮到下一根（run 41039410608 三根共耗
# 15 分钟，日志里没有一行数字）。探测是优化而非前提：取不到样本时保持
# 原序继续，CLOSURE_PROBE=0 可整体关闭。
#
# 跨轮复用走缓存池（CLOSURE_POOL 指向的目录）：池内 RPM 由本地仓库以
# cost=1 参与同一次求解，远端只补差异；未完成的轮次也会把已校验的包留进
# 池里。于是「链路慢」只决定第一轮要多久，不决定每一轮都从零再走一遍。
#
# 池只解决「重复下载」，不解决「跨境链路根本来不及」：镜像站对托管运行商
# 的地址限速到 10–20 KiB/s 时，2.5 GB 闭包要三十小时以上，而组装步的预算
# 是 180 分钟（run 41039410608：三个根各 300 秒后被窗口速率判据逐个放弃，
# dnf 连 everything 的元数据都没取完）。因此求解结果可以钉成清单：一次
# 成功的收割按 sha256 与 NEVRA 逐包写入 CLOSURE_LOCK，此后只要池与清单
# 逐项吻合，求解就完全离线重放——reposdir 里只有池这一个 file:// 仓库，
# 不取任何远端元数据。
#
# 离线重放不按组求解，而按清单里的 NEVRA 逐个点名：组解析要读各仓库的
# comps，离线时远端 comps 并不存在；NEVRA 集合本身就是上一次成功事务的
# 结果，逐个点名还能关掉弱依赖补全，使重放的事务与钉住的那一次一致。
#
# 清单由 CLOSURE_LOCK_WRITE=1 在成功收割后写出并随源码提交；构建端只读
# 不写，池与清单不一致时（新增依赖、换了快照）自动回落到在线求解，不带
# 病产出镜像。
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
#   closure_lock     清单文件路径（CLOSURE_LOCK），空串表示不重放也不写。
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
readonly CL_STALL="${CLOSURE_STALL:-600}"
readonly CL_FLOOR="${CLOSURE_FLOOR:-524288}"
readonly CL_WARM="${CLOSURE_WARMUP:-180}"
readonly CL_SAMPLE="${CLOSURE_SAMPLE:-120}"
readonly CL_POOL="${CLOSURE_POOL:-}"
# 非 readonly：调用方在解析完选项后赋值（--closure-lock），而本库在解析
# 之前就被 source 了。
CL_LOCK="${CLOSURE_LOCK:-}"
readonly CL_LOCK_W="${CLOSURE_LOCK_WRITE:-0}"
readonly CL_MIRROR_LIST="${CL_ROOT}/repo/mirrors.list"
readonly CL_PROBE="${CLOSURE_PROBE:-1}"
readonly CL_PROBE_TOOL="${CLOSURE_PROBE_TOOL:-${CL_ROOT}/tools/mirror_probe.py}"
readonly CL_PTIME="${CLOSURE_PROBE_TIME:-8}"
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
CL_XOPTS=()
CL_BOOT=()
CL_NEW=0
CL_MIRRORS=()
CL_ROOTS=()
CL_CANON=""
CL_STALLED=0
CL_SLOW=0

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

# 把配方里的源改写到指定镜像根：只有命中基准前缀的地址才换根，其余
# （离线 file:// 与第三方仓库）原样返回。空根表示不做改写。
#
# 基准不是镜像表的首项：探测会重排 CL_MIRRORS，把「当前排第一的根」当
# 前缀会让重排后的改写全部落空、地址退回原址，探测等于白做。基准由
# cl_canon 从配方自身求出（见下）。
cl_base()
{
    local base="$1" root="$2"
    if [ -z "$root" ] || [ -z "$CL_CANON" ]; then
        printf '%s' "$base"
        return 0
    fi
    case "$base" in
    "${CL_CANON}"/*) printf '%s/%s' "$root" "${base#"${CL_CANON}"/}" ;;
    *) printf '%s' "$base" ;;
    esac
}

# 改写基准 = 配方第一条非 file:// 源所落在的那个镜像根。它只取决于配方
# 与镜像表的成员关系，与行序无关，因此探测怎么重排都不影响改写结果；
# 一条也命中不了（第三方根、纯离线配方）时留空，表示不改写。
cl_canon()
{
    local name base cost root
    CL_CANON=""
    while IFS=$'\t' read -r name base cost; do
        case "$base" in
        file://*|"") continue ;;
        esac
        for root in "${CL_MIRRORS[@]}"; do
            case "$base" in
            "${root}"/*) CL_CANON="$root" ;;
            esac
            [ -n "$CL_CANON" ] && break
        done
        return 0
    done < <(python3 "$CL_SPEC" repos --skip-file "$1")
    return 0
}

# 待尝试的快照序列。镜像表缺失时退化为只用配方里那一个源——宁可比预期
# 慢，也不猜地址；空串在这里代表「不改写」。
cl_roots()
{
    CL_ROOTS=("${CL_MIRRORS[@]}")
    [ "${#CL_ROOTS[@]}" -gt 0 ] || CL_ROOTS=("")
}

# 按实测吞吐重排镜像根。行序是人工维护的，与此刻哪台主机快无关；按行序
# 尝试等于把最慢的根放在第一位，而每一根都要花掉数分钟才轮到下一根
# （run 41039410608：三根共耗 15 分钟，日志里没有一行数字说明谁快谁慢）。
# 探测是排序，不是前提：工具缺失、python3 不可用或一个样本都取不到时
# 保持原序继续，CLOSURE_PROBE=0 可整体关闭。测速表直接进构建日志。
cl_probe()
{
    local roots=() root out
    [ "$CL_PROBE" = "1" ] || return 0
    [ "${#CL_MIRRORS[@]}" -gt 1 ] || return 0
    [ -f "$CL_PROBE_TOOL" ] || return 0
    for root in "${CL_MIRRORS[@]}"; do
        case "$root" in
        http://*|https://*) roots+=("$root") ;;
        esac
    done
    [ "${#roots[@]}" -gt 1 ] || return 0
    if ! out="$(python3 "$CL_PROBE_TOOL" --timeout "$CL_PTIME" \
        --floor "$(( CL_FLOOR / 1024 ))" "${roots[@]}")"; then
        # 全部低于下限时探测仍给出最快的一个，只是用退出码 3 声明这件事。
        [ -n "$out" ] || return 0
    fi
    [ -n "$out" ] || return 0
    # shellcheck disable=SC2206  # 每行一个根，不含空格
    CL_MIRRORS=(${out})
    return 0
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
        "${CL_DNF_OPTS[@]}" ${CL_XOPTS[@]+"${CL_XOPTS[@]}"} --nogpgcheck \
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

# 目录树已落盘字节数合计：只读目录项，不解内容，每轮的成本与文件数同阶。
cl_bytes()
{
    local dir total=0 b
    for dir in "$@"; do
        b="$(du -sb "$dir" 2>/dev/null | cut -f1)"
        total=$(( total + ${b:-0} ))
    done
    printf '%s' "$total"
}

# 先 TERM 再 KILL：dnf 收到 TERM 会删掉写了一半的 .rpm 并留下已完成的包，
# 下一次求解据此只补残缺部分。
cl_kill()
{
    local pid="$1" i=0
    kill -TERM "$pid" 2>/dev/null
    while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 5 ]; do
        sleep 1
        i=$(( i + 1 ))
    done
    kill -KILL "$pid" 2>/dev/null
    return 0
}

# 子进程存活期间每 CL_BEAT 秒报一行落盘量，并在连续 CL_STALL 秒没有任何
# 字节落盘时判定为挂死：节拍只让静默可见，处置仍需有人做，否则整段构建
# 只能等 job 上限被强制取消（run 40839355885、40850633573 各沉默 80 分钟，
# 日志里既没有失败原因，也看不出卡在哪一步）。
#
# 落盘量以「下载目录 + installroot 的 dnf 缓存」合计：求解前期的元数据抓取
# 只写缓存，只盯 .rpm 个数会把正常的元数据阶段误判成挂死。轮询粒度固定
# 1 秒，子进程退出后不会多等一个节拍。
#
# 除了「没有落盘」，这里还设速率下限：镜像限速时传输仍在推进，静默判据
# 永远不会触发，整段却要跑几十小时（run 41023530128：2.5 GB 闭包以
# 29 KiB/s 爬了 30 分钟只到 53 MiB，最后撞上 step 时限）。预热 CL_WARM 秒
# 后，每 CL_SAMPLE 秒重算一次窗口速率，低于 CL_FLOOR 即换下一个镜像根——
# 快照之间是等价关系，慢根没有坚持的理由。
cl_watch()
{
    local work="$1" pid="$2" t0="$3"
    local dl="${work}/dl" cache="${work}/root/var/cache/dnf"
    local next=0 el n=0 s=0 mark prev="" quiet=0
    local sbase=0 tbase=0 rate=0 floor
    floor=$(( CL_FLOOR / 1024 ))
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        el=$(( $(date +%s) - t0 ))
        if [ "$el" -ge "$next" ]; then
            read -r n s <<<"$(cl_dlstat "$dl")"
            printf 'closure: 拉取中 files=%s size=%sMiB elapsed=%ss rate=%sKiB/s\n' \
                "$n" "$s" "$el" "$rate"
            next=$(( el + CL_BEAT ))
        fi
        mark="$(cl_bytes "$dl" "$cache")"
        if [ "$mark" = "$prev" ]; then
            quiet=$(( quiet + 1 ))
        else
            prev="$mark"
            quiet=0
        fi
        if [ "$tbase" -eq 0 ] && [ "$el" -ge "$CL_WARM" ]; then
            tbase=$el
            sbase=$mark
        fi
        if [ "$tbase" -gt 0 ] &&
            [ $(( el - tbase )) -ge "$CL_SAMPLE" ]; then
            rate=$(( (mark - sbase) / 1024 / (el - tbase) ))
            if [ "$rate" -lt "$floor" ]; then
                printf 'closure: 镜像根速率 %sKiB/s 低于下限 %sKiB/s（观测 %ss），换根\n' \
                    "$rate" "$floor" "$(( el - tbase ))" >&2
                cl_kill "$pid"
                CL_SLOW=1
                return 0
            fi
            tbase=$el
            sbase=$mark
        fi
        [ "$quiet" -lt "$CL_STALL" ] && continue
        printf 'closure: 静默 %s 秒无落盘（files=%s size=%sMiB），判定挂死，终止本次求解\n' \
            "$quiet" "$n" "$s" >&2
        cl_kill "$pid"
        CL_STALLED=1
        return 0
    done
    return 0
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
            cl_watch "$work" "$pid" "$t0"
            wait "$pid" && rc=0 || rc=$?
            if [ "$rc" -ne 0 ]; then
                # 未完成也把已校验的包收进缓存池：下一轮只在池外补缺，
                # 失败的次数不再等价于从零重来。
                cl_pool_keep "${work}/dl"
            fi
            [ "$rc" -eq 0 ] && return 0
            if [ "$CL_SLOW" -eq 1 ]; then
                CL_SLOW=0
                printf 'closure: 镜像根 %s 速率低于下限，跳过重试换下一个根\n' \
                    "$label" >&2
                break
            fi
            if [ "$CL_STALLED" -eq 1 ]; then
                # 挂死是快照侧的确定性故障，同一根上重试只会再静默一轮，
                # 把 3 次重试的等待压成一次，直接换快照。
                CL_STALLED=0
                printf 'closure: 镜像根 %s 求解挂死，跳过重试换下一个根\n' \
                    "$label" >&2
                break
            fi
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

# 缓存池：跨轮复用的 RPM 池，只由文件名（NEVRA）认身份。池里已有的包不再
# 从公网取，未完成的轮次也把已校验的包留在池内，于是「跨洋链路慢」只决定
# 第一轮要多久，不决定每一轮都要重来（run 41023530128 的 2.5 GB 闭包以
# 29 KiB/s 爬满 step 时限，正是每轮从零开始的结果）。
#
# 池本身作为 cost=1 的本地仓库参与同一次求解：EVRA 相同的包由本地提供，
# 远端只需补齐差异，且最终下载目录 dl 里只有本轮事务的包——旧快照的包
# 留在池里但不会进入载荷，NEVRA 混合的问题因此不因缓存而回归。
cl_pool_init()
{
    local cfg="$1" n
    [ -n "$CL_POOL" ] || return 0
    mkdir -p "$CL_POOL" || return 1
    n="$(find "$CL_POOL" -maxdepth 1 -type f -name '*.rpm' 2>/dev/null |
        wc -l)"
    [ "$n" -gt 0 ] || return 0
    if ! createrepo_c --quiet --general-compress-type gz "$CL_POOL" \
        >/dev/null 2>&1; then
        printf 'closure: 缓存池索引失败，本轮不使用（%s）\n' "$CL_POOL" >&2
        return 0
    fi
    {
        printf '[airymax-pool]\nname=airymax-pool\n'
        printf 'baseurl=file://%s\ncost=1\nenabled=1\ngpgcheck=0\n' "$CL_POOL"
        printf 'metadata_expire=0\n'
    } >"$cfg"
    printf 'closure: 缓存池 %s 个 RPM 参与求解（%s）\n' "$n" "$CL_POOL"
    return 0
}

cl_pool_keep()
{
    local dir="$1" rpm base kept=0
    [ -n "$CL_POOL" ] || return 0
    [ -d "$dir" ] || return 0
    while IFS= read -r rpm; do
        base="$(basename "$rpm")"
        [ -f "${CL_POOL}/${base}" ] && continue
        # 被 KILL 的 dnf 可能留下写了一半的包；摘要不符的包一旦进池，下一轮
        # 会以「本地已有」为由跳过下载，把损坏带进载荷。
        rpm -K --nosignature "$rpm" >/dev/null 2>&1 || continue
        cp -p "$rpm" "${CL_POOL}/${base}" || continue
        kept=$(( kept + 1 ))
    done < <(find "$dir" -maxdepth 1 -type f -name '*.rpm' 2>/dev/null)
    if [ "$kept" -gt 0 ]; then
        printf 'closure: 缓存池新增 %d 个 RPM（共 %s）\n' "$kept" "$CL_POOL"
    fi
    return 0
}

cl_harvest()
{
    local dl="$1" pkg="$2" rpm base
    while IFS= read -r rpm; do
        base="$(basename "$rpm")"
        if [ -f "${pkg}/${base}" ]; then
            continue
        fi
        cp -p "$rpm" "${pkg}/${base}"
        NAMES+=("$base")
        CL_NEW=$((CL_NEW + 1))
    done < <(find "$dl" -maxdepth 1 -type f -name '*.rpm' | sort)
    # 载荷已含全部包时新增数为 0，这不是失败：重放与重跑都会走到这里。
    # 事务本身是否成立由 cl_has_dl 与 cl_audit 判定。
    return 0
}

# 空事务也会返回 0：dnf 一个包都没解出来时，收割与审计都对着空目录真空
# 通过，镜像带着空闭包出门，装机现场才缺包。把「什么都没解」从成功里摘
# 出来。
cl_has_dl()
{
    [ -n "$(find "${1}/dl" -maxdepth 1 -type f -name '*.rpm' \
        2>/dev/null | head -n 1)" ]
}

# 清单每行「sha256  文件名  NEVRA」：文件名是池里的身份，NEVRA 供离线
# 重放逐个点名，sha256 使池里那一份可以被独立复核。先写临时文件再改名，
# 中途失败不会留下半份清单让下一轮误以为已钉住。
cl_lock_write()
{
    local dl="$1" lock="$2" rpm base nev n=0 sum
    : >"${lock}.tmp"
    while IFS= read -r rpm; do
        base="$(basename "$rpm")"
        sum="$(sha256sum "$rpm" | cut -d' ' -f1)" || return 1
        nev="$(rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}' \
            "$rpm" 2>/dev/null)" || return 1
        [ -n "$nev" ] || return 1
        printf '%s  %s  %s\n' "$sum" "$base" "$nev" >>"${lock}.tmp"
        n=$((n + 1))
    done < <(find "$dl" -maxdepth 1 -type f -name '*.rpm' | LC_ALL=C sort)
    if [ "$n" -eq 0 ]; then
        rm -f "${lock}.tmp"
        return 1
    fi
    mv "${lock}.tmp" "$lock" || return 1
    printf 'closure: 闭包清单写出 %s 个包（%s）\n' "$n" "$lock"
}

# 池与清单逐项吻合才允许离线重放。缺项或摘要不符说明池不完整或被人改过，
# 重放解出的事务会与钉住的那次不同——回落在线的代价远小于带病镜像。
cl_lock_load()
{
    local lock="$1" sum base nev miss=0
    [ -s "$lock" ] || return 1
    [ -n "$CL_POOL" ] || return 1
    CL_ARGS=()
    while read -r sum base nev; do
        [ -n "$nev" ] || continue
        if [ ! -f "${CL_POOL}/${base}" ]; then
            printf 'closure: 池缺 %s\n' "$base" >&2
            miss=$((miss + 1))
            continue
        fi
        if [ "$(sha256sum "${CL_POOL}/${base}" | cut -d' ' -f1)" != "$sum" ]; then
            printf 'closure: 池内 %s 摘要不符\n' "$base" >&2
            miss=$((miss + 1))
            continue
        fi
        CL_ARGS+=("$nev")
    done <"$lock"
    [ "$miss" -eq 0 ] && [ "${#CL_ARGS[@]}" -gt 0 ]
}

# 完全离线重放：reposdir 里只有池这一个 file:// 仓库，不取任何远端元数据。
# 按 NEVRA 点名而不按组求解——组解析要读远端 comps，离线时它并不存在；
# 关掉弱依赖补全，使事务与钉住的那一次一致。
cl_replay()
{
    local arch="$1" pkg="$2" work="$3" log="$4"
    [ -n "$CL_LOCK" ] || return 1
    cl_lock_load "$CL_LOCK" || return 1
    rm -rf "${work}/repos" "${work}/dl"
    mkdir -p "${work}/repos"
    cl_pool_init "${work}/repos/pool.repo" || return 1
    [ -f "${work}/repos/pool.repo" ] || return 1
    printf '%s\n' "$CL_POOL" >"${work}/mirror-root.txt"
    : >"$log"
    printf '## 离线重放 %s（%d 个包）\n' "$CL_LOCK" "${#CL_ARGS[@]}" >>"$log"
    CL_XOPTS=(--setopt=install_weak_deps=0)
    if ! cl_run "$work" "$arch" "$pkg" "$log"; then
        CL_XOPTS=()
        return 1
    fi
    CL_XOPTS=()
    cl_harvest "${work}/dl" "$pkg" || return 1
    cl_has_dl "$work" || return 1
    cl_audit "${work}/dl" "$pkg"
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
    # 池与清单吻合就先离线重放：跨境链路对托管运行商限速到 10–20 KiB/s 时，
    # 在线求解在一段预算内根本走不完（见文件头）。命中即返回，不碰任何远端。
    if cl_replay "$arch" "$pkg" "$work" "$log"; then
        printf 'closure: 离线重放命中，未访问远端（%s）\n' "$CL_LOCK"
        rm -rf "${work}/root"
        return 0
    fi
    printf 'closure: 未命中离线重放，转在线求解\n' >&2
    rm -rf "${work}/repos" "${work}/dl"
    mkdir -p "${work}/repos"
    cl_init_mirrors
    # 基准先算、再重排：canon 只认同「哪个根是配方源」，与顺序无关；若在
    # 探测之后再算，被探测丢掉的首根会让基准落空，改写失效。
    cl_canon "$ks"
    cl_probe
    cl_roots
    closure_specs "$ks" || return 1
    cl_args "$arch" || return 1
    # 池必须在求解前建好索引：reposdir 里所有 *.repo 都参与同一次求解，
    # 池以 cost=1 优先提供已有 NEVRA，远端只补差异。
    cl_pool_init "${work}/repos/pool.repo"
    cl_try "$ks" "$arch" "$pkg" "$work" "$log" || return 1
    cl_harvest "${work}/dl" "$pkg" || return 1
    cl_has_dl "$work" || return 1
    cl_audit "${work}/dl" "$pkg" || return 1
    # 本轮完整下完的包也入池：下一轮（换版本、换架构、重跑）不必再走
    # 公网。放在审计之后，只有通过审计的事务才扩大池的可信集合。
    cl_pool_keep "${work}/dl"
    # 清单只在显式要求时写：构建端只读不写，否则每轮都会用当轮的求解
    # 结果覆盖掉人工钉住的那一份。
    if [ "$CL_LOCK_W" = "1" ] && [ -n "$CL_LOCK" ]; then
        cl_lock_write "${work}/dl" "$CL_LOCK" || return 1
    fi
    rm -rf "${work}/root" "${work}/dl"
}
