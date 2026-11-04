#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airy_observe.sh — 系统观察点报告（安装为 /usr/bin/airy-observe）
#
# 现状：AirymaxOS 的可观测标记分散在各自的服务里（BOOT-HEALTH 在就绪探针、
# RT-BUDGET 在预算脚本、DESKTOP-READY 在登录链）。要回答「这台机器是不是
# AirymaxOS、牌子对不对、内核归谁、桌面在哪块屏上」时，得逐个服务翻
# journal，还得自己拼。任何一次转述都可能把两套语义混在一起。
#
# 这里做的是把既有事实以固定 key=value 逐行摊开：每个字段只读一个权威
# 来源（os-release、rpm 数据库、systemd、procfs、xrandr），不做推断也不做
# 缓存，因此同一台机器任何时候跑出来的报告都可对照。字段缺失写 absent，
# 不省略该行——省略会让「没采到」和「没有这一项」长得一模一样；取值内部
# 含空格时整体加双引号（如 os.pretty），保证按空白切分不会错位。
#
# 报告另提供 --section，把同一批事实按主题切开单独输出（kernel/os/boot/
# net/sched/rtc）。默认证号仍是「身份 + 运行」两段，逐字未变；--section 只是
# 换一个视角看同一份采集，不引入第二套取值逻辑，因此同一个键在任何模式
# 下都来自同一个权威来源。展示与排障时一次只一屏，避免几十行混在一起
# 看不出卡在哪一项。
#
# hardware、firmware 与 system 是转交给 airymax_observe 的三个子命令：整机硬件
# 清点要按类别扫描十几个 sysfs 目录，固件实况要把模块自报的文件名与本次开机
# 日志对起来，系统清点要读 systemd 的失败单元、本次开机的 err 日志与
# rpm 数据库，三套判定都已经在模块里，这里只按名字转交。转交而不是再装
# 可执行文件，理由与 --section 相同——命令名只能有一个主人；两个包各装一个
# airy-observe，装在一起就是文件冲突。
#
# 报告分两段，字段名在两种模式下同义：
#   身份段（os.*、brand.*、asset.*、host.name）只读文件，静态与活体共用
#     同一份实现，因此「这台机器是谁」在构建期与装机后是同一组键、同一
#     个权威来源（os-release、grub 默认项、hostname）。
#   运行段（kernel.*、session.*、boot.* 等）需要真实内核与 systemd，只在
#     活体模式出现；--static 跳过它，不要求构建机有 X server 或 systemd。
# --root 指定观察根，与 --static 配合用于打包自检；运行段不受 --root 影响，
# 因为它问的是当前内核与当前 cgroup。
#
# 末两行固定为 mode、fields：调用方按 status 判一次结论即可，不必自己聚合
# 各行。status=ok 表示身份与桌面链都成立，非零退出码让脚本能直接用在 CI
# 断言里。
#
# 依赖：POSIX sh、awk、sed；活体模式另需 systemctl、xrandr、ip（可选）；
# hardware/firmware/system 子命令需要 python3 与 airymax_observe 包（firmware
# 另需 kmod 的 modinfo 与可读的内核日志，system 另需 rpm 数据库与 journal）。
# ===========================================================================

set -u

MARK=AIRYMAX-OBSERVE
WANT_ID=airymaxos
SLICES="system.slice user.slice airymax.slice airymax-desktop.slice"
ROOT=/
STATIC=0
SECTIONS=
OS_ID=absent
fields=0
absent_n=0
status=ok

emit() {
    val=${2:-absent}
    [ "$val" = absent ] && absent_n=$((absent_n + 1))
    case $val in
    *' '*) val="\"${val}\"" ;;
    esac
    printf '%s %s=%s\n' "$MARK" "$1" "$val"
    fields=$((fields + 1))
}

read_kv() {
    [ -r "$1" ] || return 1
    val=$(sed -n "s/^$2=//p" "$1" | head -n 1 | tr -d '"')
    [ -n "$val" ] || return 1
    printf '%s\n' "$val"
}

have() {
    [ -r "${ROOT}$1" ] && printf 'present' || printf 'absent'
}

# anaconda 把 GRUB_DISTRIBUTOR 写成延迟展开的管道表达式，取值要等
# grub-mkconfig 求值。报告不 eval 别人的配置：按同一条 sed 规则（去掉
# " release " 及其后全部）从 /etc/system-release 推出菜单名。
grub_brand() {
    val=$(read_kv "${ROOT}/etc/default/grub" GRUB_DISTRIBUTOR) || {
        printf 'absent'
        return 0
    }
    case $val in
    *'$('*)
        rel=$(head -n 1 "${ROOT}/etc/system-release" 2>/dev/null) || rel=
        case $rel in
        *' release '*) printf '%s' "${rel%% release*}" ;;
        *) printf 'absent' ;;
        esac
        ;;
    *) printf '%s' "$val" ;;
    esac
}

is_pos() {
    case ${1:-0} in
    '' | *[!0-9]*) return 1 ;;
    esac
    [ "$1" -gt 0 ]
}

rt_budget() {
    for f in /sys/fs/cgroup/*/cpu.rt_runtime_us; do
        [ -f "$f" ] || continue
        root=${f%/*}
        applied=0
        for s in $SLICES; do
            v=$(cat "$root/$s/cpu.rt_runtime_us" 2>/dev/null) || v=0
            is_pos "$v" && applied=$((applied + 1))
        done
        [ "$applied" -eq 0 ] && {
            printf 'absent'
            return 0
        }
        [ "$applied" -lt 4 ] && {
            printf 'partial'
            return 0
        }
        printf 'ok'
        return 0
    done
    printf 'absent'
}

failed_count() {
    systemctl list-units --failed --no-legend --plain --no-pager 2>/dev/null |
        awk 'NF { n++ } END { print n + 0 }'
}

outputs() {
    command -v xrandr >/dev/null 2>&1 || {
        printf 'absent'
        return 0
    }
    list=$(xrandr --query 2>/dev/null | awk '
        / connected/ { printf "%s%s", (n++ ? "," : ""), $1 }')
    printf '%s' "${list:-none}"
}

net_v4() {
    command -v ip >/dev/null 2>&1 || {
        printf 'absent'
        return 0
    }
    list=$(ip -4 -o addr show scope global 2>/dev/null | awk '
        { sub(/\/.*/, "", $4); printf "%s%s=%s", (n++ ? "," : ""), $2, $4 }')
    printf '%s' "${list:-none}"
}

meminfo() {
    awk -v want="$1" '$1 == want ":" { printf "%s", $2; found = 1 }
        END { if (!found) printf "absent" }' /proc/meminfo
}

# 内核归属只认 rpm 数据库：/boot/vmlinuz-<release> 由哪个包安装，运行中的
# 内核就属于哪个包。查不到写 unowned，不用发行版名字兜底——那只能说明
# 机器叫什么，不能说明这个内核是谁装的。
kernel_owner() {
    local rel owner
    rel=$(uname -r 2>/dev/null) || {
        printf 'unowned'
        return 0
    }
    owner=$(rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}' \
        -f "/boot/vmlinuz-${rel}" 2>/dev/null) || owner=
    printf '%s' "${owner:-unowned}"
}

systemd_ver() {
    local v
    command -v systemctl >/dev/null 2>&1 || {
        printf 'absent'
        return 0
    }
    v=$(systemctl --version 2>/dev/null | head -n 1)
    printf '%s' "${v:-absent}"
}

# systemd-analyze 的耗时字符串含空格，emit 会整体加引号，按空白切分不会错位。
boot_total() {
    local v
    command -v systemd-analyze >/dev/null 2>&1 || {
        printf 'absent'
        return 0
    }
    v=$(systemd-analyze 2>/dev/null | sed -n 's/^Startup finished in //p' |
        head -n 1)
    printf '%s' "${v:-absent}"
}

net_gw() {
    command -v ip >/dev/null 2>&1 || {
        printf 'absent'
        return 0
    }
    v=$(ip -4 route show default 2>/dev/null | awk 'NR == 1 { print $3 }')
    printf '%s' "${v:-none}"
}

net_dns() {
    local v
    v=$(sed -n 's/^nameserver //p' /etc/resolv.conf 2>/dev/null | head -n 1)
    printf '%s' "${v:-none}"
}

net_up() {
    command -v ip >/dev/null 2>&1 || {
        printf 'absent'
        return 0
    }
    v=$(ip -o link show up 2>/dev/null | awk 'NF { n++ } END { print n + 0 }')
    printf '%s' "${v:-0}"
}

# 地址来源：DHCP 租约在 ip 的输出里带 dynamic 标志，静态配置没有。装机
# 验收问的是「拿到的是不是租约」而不是「有没有地址」——现场两者看起来都
# 是有一个 IPv4，区别只在续约时会消失还是不会。
net_src() {
    command -v ip >/dev/null 2>&1 || {
        printf 'absent'
        return 0
    }
    v=$(ip -4 -o addr show scope global 2>/dev/null | awk '
        { n++; for (i = 1; i <= NF; i++) if ($i == "dynamic") d++ }
        END {
            if (!n) print "none"
            else if (d) print "dhcp"
            else print "static"
        }')
    printf '%s' "${v:-none}"
}

# 无线设备：内核为该网卡建立 cfg80211 关联时才有 /sys/class/net/<if>/
# wireless。接口名取自内核，不读 NetworkManager——网络没起来时 NM 可能
# 尚未发现设备，而验收要回答的恰恰是「硬件在不在」。
net_wifi() {
    local d list=
    for d in /sys/class/net/*/wireless; do
        [ -d "$d" ] || continue
        d=${d%/wireless}
        list=${list:+$list,}${d##*/}
    done
    printf '%s' "${list:-none}"
}

# 内核命令行里的开关：只报「有没有这一项」，取值本身由 kernel.cmdline 给出。
cmdline_word() {
    [ -r /proc/cmdline ] || {
        printf 'absent'
        return 0
    }
    if tr ' ' '\n' </proc/cmdline 2>/dev/null | grep -q "^$1"; then
        printf 'present'
    else
        printf 'absent'
    fi
}

# os-release 的三个身份键由身份段与 --section os 共用：同一个键只能读同一
# 个文件，两处各读一次就可能对同一台机器给出不同答案。
os_keys() {
    local osr=${ROOT}/usr/lib/os-release
    [ -r "$osr" ] || osr=${ROOT}/etc/os-release
    OS_ID=$(read_kv "$osr" ID) || OS_ID=absent
    emit os.id "$OS_ID"
    emit os.version "$(read_kv "$osr" VERSION_ID || printf absent)"
    emit os.pretty "$(read_kv "$osr" PRETTY_NAME || printf absent)"
}

# 内核配置项：取值来自装机内核自带的 /boot/config-<release>，不做推断。
cfg() {
    local f="${ROOT}/boot/config-$(uname -r)" v
    [ -r "$f" ] || {
        printf 'absent'
        return 0
    }
    v=$(grep -m 1 "^$1=" "$f" 2>/dev/null) || {
        printf 'absent'
        return 0
    }
    printf '%s' "${v#*=}"
}

# 抢占模型：配置里只有被选中的那一项写成 =y，其余是注释行，所以按由强到弱
# 取第一个 =y 的项，不能只读某一项——只读 PREEMPT_DYNAMIC 时，非动态内核会
# 报 absent，把「没有这一档」误读成「采不到」。
preempt_model() {
    local m model=
    for m in PREEMPT_RT PREEMPT PREEMPT_VOLUNTARY PREEMPT_NONE; do
        [ "$(cfg "CONFIG_${m}")" = y ] || continue
        model=$m
        break
    done
    [ -n "$model" ] || {
        printf 'absent'
        return 0
    }
    # 动态抢占在运行期可切，构建期仍要选一个默认档；两个事实一起报，
    # 单写 dynamic 会丢掉「默认是哪一档」。
    if [ "$(cfg CONFIG_PREEMPT_DYNAMIC)" = y ]; then
        printf 'dynamic:%s' "$model"
    else
        printf '%s' "$model"
    fi
}

# 引导器归属：产品里没有名为 grub2 的包（真实包名带架构后缀，如
# grub2-efi-x64），按固定名查询只会拿到 rpm 的「not installed」文本。这里按
# 支持的架构逐个试，命中即报 name-version-release。
boot_loader() {
    local p out
    command -v rpm >/dev/null 2>&1 || {
        printf 'absent'
        return 0
    }
    for p in grub2-efi-x64 grub2-efi-aa64 grub2-efi-riscv64 \
        grub2-efi-loongarch64 grub2-pc; do
        out=$(rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}' "$p" 2>/dev/null) ||
            continue
        printf '%s' "$out"
        return 0
    done
    printf 'absent'
}

# 单文件取值（taint、cmdline、enforce 一类只有一个词的 sysctl/procfs）。
one_line() {
    local v
    [ -r "$1" ] || {
        printf 'absent'
        return 0
    }
    v=$(tr -d '\n' <"$1" 2>/dev/null)
    printf '%s' "${v:-absent}"
}

mod_count() {
    local f="${ROOT}/lib/modules/$(uname -r)/modules.dep"
    [ -r "$f" ] || {
        printf 'absent'
        return 0
    }
    awk 'NF { n++ } END { print n + 0 }' "$f"
}

# 编译器与构建时间只出现在 /proc/version，是「这个内核确实被编出来过」的
# 直接证据；发行包信息由 kernel.owner 给出，两者不互相替代。
kernel_build() {
    local v
    [ -r /proc/version ] || {
        printf 'absent'
        return 0
    }
    v=$(sed -n 's/^Linux version [^ ]* //p' /proc/version | head -n 1)
    printf '%s' "${v:-absent}"
}

kernel_report() {
    emit kernel.release "$(uname -r 2>/dev/null || printf absent)"
    emit kernel.owner "$(kernel_owner)"
    emit kernel.localversion "$(cfg CONFIG_LOCALVERSION)"
    emit kernel.build "$(kernel_build)"
    emit kernel.modules "$(mod_count)"
    emit kernel.preempt "$(preempt_model)"
    emit kernel.taint "$(one_line /proc/sys/kernel/tainted)"
    emit kernel.cmdline "$(one_line /proc/cmdline)"
}

# 包数只认 rpm 数据库；没有 rpm 时写 absent 而不是 0，否则「查不到」会被
# 读成「一个包也没有」。
pkg_count() {
    local v
    command -v rpm >/dev/null 2>&1 || {
        printf 'absent'
        return 0
    }
    v=$(rpm -qa "$@" 2>/dev/null | awk 'NF { n++ } END { print n + 0 }')
    printf '%s' "${v:-0}"
}

os_report() {
    os_keys
    emit os.systemd "$(systemd_ver)"
    emit os.packages "$(pkg_count)"
    emit os.kernel_pkgs "$(pkg_count 'airymaxos-*')"
    emit os.selinux "$(one_line /sys/fs/selinux/enforce)"
}

boot_report() {
    emit boot.firmware "$(have /sys/firmware/efi)"
    emit boot.loader "$(boot_loader)"
    emit boot.target "$(systemctl get-default 2>/dev/null || printf absent)"
    emit boot.total "$(boot_total)"
    emit boot.failed "$(failed_count)"
}

net_report() {
    emit net.ipv4 "$(net_v4)"
    emit net.src "$(net_src)"
    emit net.gw "$(net_gw)"
    emit net.dns "$(net_dns)"
    emit net.link "$(net_up)"
    emit net.wifi "$(net_wifi)"
}

sched_report() {
    emit sched.loadavg "$(cut -d ' ' -f 1-3 /proc/loadavg 2>/dev/null ||
        printf absent)"
    emit sched.iso "$(cmdline_word isolcpus)"
    emit sched.rt "$(rt_budget)"
    emit sched.hz "$(cfg CONFIG_HZ)"
}

# RTC 主题：装机最后一步把系统时钟写进硬件时钟，少数固件上会长时间阻塞，
# 因此这一步限时、只告警（kickstart/rtc-sync.sh）。验收要回答的是「写完
# 了没有」，所以这里只读内核暴露的三个事实：设备名、当前 RTC 读数与
# hctosys 开关，不读 hwclock、也不去写设备。
#
# since_epoch 是内核把 RTC 寄存器按 UTC 折算出的秒数（与 hwclock --utc
# 同口径）。systemd 的 hctosys 只影响启动时用 RTC 校准系统时钟的方向，与
# 本次写入无关，因此单独成项，不与 drift 混为一谈。
rtc_dir() {
    printf '%s' "${AIRY_RTC_DIR:-/sys/class/rtc/rtc0}"
}

# 偏差 = 系统时钟 - RTC 读数。装机写入成功时两者应当在一个时区内相等；
# 明显偏移说明写没落地（RTC 停在出厂时间）或写的是本地时间而非 UTC，两
# 种现场故障在这里分得开，不必再去翻装机日志。
rtc_drift() {
    local base now
    [ -r "$1/since_epoch" ] || {
        printf 'absent'
        return 0
    }
    base=$(cat "$1/since_epoch" 2>/dev/null) || base=
    case $base in
    '' | *[!0-9]*)
        printf 'absent'
        return 0
        ;;
    esac
    now=$(date +%s 2>/dev/null) || now=
    case $now in
    '' | *[!0-9]*)
        printf 'absent'
        return 0
        ;;
    esac
    printf '%s' "$((now - base))"
}

rtc_report() {
    local d
    d=$(rtc_dir)
    if [ ! -d "$d" ]; then
        emit rtc.device absent
        emit rtc.name absent
        emit rtc.epoch absent
        emit rtc.drift absent
        emit rtc.hctosys absent
        return 0
    fi
    emit rtc.device "${d##*/}"
    emit rtc.name "$(one_line "$d/name")"
    emit rtc.epoch "$(one_line "$d/since_epoch")"
    emit rtc.drift "$(rtc_drift "$d")"
    emit rtc.hctosys "$(one_line "$d/hctosys")"
}

identity_report() {
    os_keys
    emit brand.grub "$(grub_brand)"
    wallpaper=$(have \
        /usr/share/backgrounds/airymaxos/qilian_photo_from_zhenyi.jpg)
    emit brand.wallpaper "$wallpaper"
    schema=$(have /usr/share/glib-2.0/schemas/99-airymaxos-default.gschema.override)
    emit brand.schema "$schema"
    desktop=$(have /usr/lib/airymaxos/desktop/desktop_ready.sh)
    emit asset.desktop "$desktop"
    recorder=$(have /usr/lib/airymaxos/desktop/airy_record.sh)
    emit asset.record "$recorder"
    observer=$(have /usr/lib/airymaxos/desktop/airy_observe.sh)
    emit asset.observe "$observer"
    bencher=$(have /usr/lib/airymaxos/desktop/airy_bench.py)
    emit asset.bench "$bencher"
    demo=$(have /usr/lib/airymaxos/desktop/airy_demo.py)
    emit asset.demo "$demo"
    host=$(cat "${ROOT}/etc/hostname" 2>/dev/null) || host=
    emit host.name "${host:-absent}"
    [ "$OS_ID" = "$WANT_ID" ] || status=partial
    for v in "$wallpaper" "$schema" "$desktop" "$recorder" "$observer" \
        "$bencher" "$demo"; do
        [ "$v" = present ] || status=partial
    done
}

# 就绪探针是 Type=oneshot：跑成功后单元回到 inactive，is-active 永远答
# inactive。判定必须看单元留下的结果与调用号——Result=success 且有过一次
# 调用，才等于「桌面链已验证过」。
ready_state() {
    show=$(systemctl show -p ActiveState -p Result -p InvocationID \
        airymax-desktop-ready.service 2>/dev/null) || show=
    [ -n "$show" ] || {
        printf 'absent'
        return 0
    }
    active=$(printf '%s\n' "$show" | sed -n 's/^ActiveState=//p')
    case $active in
    active | activating | reloading)
        printf '%s' "$active"
        return 0
        ;;
    failed)
        printf 'failed'
        return 0
        ;;
    esac
    result=$(printf '%s\n' "$show" | sed -n 's/^Result=//p')
    inv=$(printf '%s\n' "$show" | sed -n 's/^InvocationID=//p')
    [ -n "$inv" ] && [ "$result" = success ] || {
        printf 'absent'
        return 0
    }
    printf 'ready'
}

run_report() {
    emit kernel.release "$(uname -r 2>/dev/null || printf absent)"
    emit kernel.owner "$(kernel_owner)"
    sess=${XDG_SESSION_TYPE:-}
    [ -n "$sess" ] || {
        [ -n "${DISPLAY:-}" ] && sess=x11 || sess=absent
    }
    emit session.type "$sess"
    emit session.display "${DISPLAY:-absent}"
    emit display.outputs "$(outputs)"
    ready=$(ready_state)
    emit desktop.ready "$ready"
    failed=$(failed_count)
    emit boot.health "$failed"
    emit rt.budget "$(rt_budget)"
    emit mem.total_kb "$(meminfo MemTotal)"
    emit mem.avail_kb "$(meminfo MemAvailable)"
    emit cpu.count "$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf absent)"
    emit root.used "$(df -P / 2>/dev/null | awk 'NR == 2 { print $5 }')"
    net_report
    [ "$failed" = 0 ] || status=partial
    case $ready in
    ready | active | activating) ;;
    *) status=partial ;;
    esac
}

# hardware / firmware / system 的整份输出归 airymax_observe，父命令不再追加
# mode/fields：三份报告的字段集不同，混在一起会让按行解析的调用方进退两难。
# 缺依赖时报一行明确的结论并退出 2，不把 python 的 traceback 当成报告交给
# 调用方。
if [ $# -gt 0 ] && { [ "$1" = hardware ] || [ "$1" = firmware ] ||
    [ "$1" = system ]; }; then
    python3 -B -c 'import airymax_observe' 2>/dev/null || {
        printf '%s fail reason=no-observe-package\n' "$MARK" >&2
        exit 2
    }
    exec python3 -B -m airymax_observe "$@"
fi

while [ $# -gt 0 ]; do
    case $1 in
    --root)
        ROOT=${2:-}
        [ -n "$ROOT" ] || {
            printf '%s fail reason=bad-root\n' "$MARK" >&2
            exit 2
        }
        ROOT=${ROOT%/}
        shift 2
        ;;
    --static)
        STATIC=1
        shift
        ;;
    --section)
        [ -n "${2:-}" ] || {
            printf '%s fail reason=missing-section\n' "$MARK" >&2
            exit 2
        }
        SECTIONS="${SECTIONS:+$SECTIONS,}$2"
        shift 2
        ;;
    -h | --help)
        printf '用法: airy-observe [--static] [--root DIR]\n'
        printf '      airy-observe --section NAME[,NAME...]\n'
        printf '      airy-observe hardware [--json] [--root DIR]\n'
        printf '      airy-observe firmware [--json] [--dmesg FILE]\n'
        printf '      airy-observe system [--json] [--manifest FILE]\n'
        printf '主题: kernel os boot net sched rtc\n'
        printf 'hardware: 整机硬件清点，cpu/block/net 必检，其余类别可选\n'
        printf 'firmware: 驱动期望的固件文件名与本次开机的载入实况\n'
        printf 'system: 失败单元、本次开机 err 日志与包集合对账\n'
        exit 0
        ;;
    *)
        printf '%s fail reason=unknown-arg=%s\n' "$MARK" "$1" >&2
        exit 2
        ;;
    esac
done

# 主题视图：同一批采集按主题切片输出，每段给出自己的字段数，便于把一个
# 屏里的一行对回完整报告。段内任何一项取不到都判 partial——主题视图的
# 用途就是「这一段是否完整」，不是「整机是否可用」。
section_report() {
    local sec before
    for sec in $(printf '%s' "$SECTIONS" | tr ',' ' '); do
        before=$fields
        case $sec in
        kernel) kernel_report ;;
        os) os_report ;;
        boot) boot_report ;;
        net) net_report ;;
        sched) sched_report ;;
        rtc) rtc_report ;;
        *)
            printf '%s fail reason=bad-section=%s\n' "$MARK" "$sec" >&2
            return 2
            ;;
        esac
        printf '%s section=%s fields=%s\n' "$MARK" "$sec" \
            "$((fields - before))"
    done
    [ "$absent_n" -eq 0 ] || status=partial
    return 0
}

if [ -n "$SECTIONS" ]; then
    section_report || exit $?
    mode=section
elif [ "$STATIC" -eq 1 ]; then
    identity_report
    mode=static
else
    identity_report
    run_report
    mode=live
fi

printf '%s mode=%s fields=%s\n' "$MARK" "$mode" "$fields"
printf '%s status=%s\n' "$MARK" "$status"
[ "$status" = ok ]
