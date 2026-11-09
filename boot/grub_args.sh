#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# grub_args.sh — 内核启动参数与菜单范围的持久来源
#
# 调用者：安装配方的 %post --nochroot（airymaxos-workstation.ks）。该段已把
#         ESP、efivarfs 与 /dev /proc /sys 挂进目标根，再在 chroot 内调用本
#         脚本：grub2-mkconfig 需要目标系统的配方与块设备视图，安装器环境
#         里两者都不完整。
#
# 为什么需要这一步：kickstart 的 bootloader --append 只作用于安装器本次生成
# 的 grub.cfg，anaconda 不把它写进 /etc/default/grub。此后任何一次
# grub2-mkconfig（内核升级、grub2 包升级、手工重建）都以 /etc/default/grub
# 为唯一输入，append 的参数随即消失，表现为「装好时参数在，升级一次全丢」。
# 真机 B50 取证：/proc/cmdline 与 grub.cfg 的 linux 行逐字一致，但都缺
# 安装器 append 的内容——缺失发生在生成期，不是运行期。
#
# 为什么本地屏幕逐行打印而不是启动画面：0.0.4 关闭 plymouth。285H 实测
# （2026-11-09）冷启动停在 "Tell Plymouth To Write Out Runtime Data"：
# 该单元 Type=oneshot，而 oneshot 不设 TimeoutStartSec 时默认就是 infinity，
# plymouthd 不应答即无界阻塞 sysinit.target，网络栈与 SSH 一起不上线，屏幕
# 停在最后一行不再变化，现场无从判断卡在哪一步。同一台机器更早一次启动该
# 单元 15ms 完成——故障是间歇的，不是必现的配置错误。该机 iGPU 无 KMS，
# plymouth 只能在 simpledrm 的 2880x1800 上绘制，画面本身也不可用。
# plymouth.enable=0 让 plymouth-start.service 的条件失配，启动路径上再没有
# 任何 plymouth 单元；loglevel=5 保留 info 级消息、压掉 debug，内核与
# systemd 的阶段行都留在屏幕上。装着的 plymouth 与主题不动，等 KMS 覆盖
# 到位再谈画面。
#
# 为什么控制台集合也由本脚本持有：kernel 把 /dev/console 路由到命令行里
# 最后一个 console=，因此顺序本身就是语义。0.0.3 的安装器把 tty0 写在前面，
# 285H 实测 /sys/class/tty/console/active = "tty0 ttyS0"，/dev/console 落在
# 串口上，systemd-vconsole-setup 报 "Failed to lock /dev/console: Input/output
# error"，连带 airymax-desktop-ready 门禁在每个启动周期失败。串口在前、tty0
# 在后：内核与 systemd 日志同时写两路，本地屏幕拿到 VT 所有权，无头验收仍
# 可从 ttyS0 取得 getty 与内核消息。bootloader --append 不持久化，这一串
# 只能写在这里；重新改写时先摘掉全部旧 console=，再按本常量重放——现场被
# 手工加进去的幽灵控制台（285H 的 ttyAMA0）因此在下一次收敛时消失。
#
# 为什么同时收敛菜单范围：未设 GRUB_DISABLE_OS_PROBER 时 os-prober 会把同盘
# 其他发行版的内核并进本产品菜单（B50 上是 19 个条目，含两个 Ubuntu 内核）。
# 菜单既长又不属于本产品的归属。站点叠加场景仍可从固件启动菜单选择其他
# 系统，本产品菜单只列自己的内核。
#
# 为什么不需要处理 BLS：本产品未启用 GRUB_ENABLE_BLSCFG，10_linux 直接从
# /etc/default/grub 取参数生成 menuentry，因此改写该文件即对后续生成生效，
# /boot/loader/entries 不存在也不需要维护。
#
# 为什么生成后还要同步品牌副本：EFI 下 grub 的 $prefix 取自被固件加载的
# grubx64.efi 所在目录，NVRAM 指向 \EFI\airymaxos，因此 /dev/console 与
# 菜单实际读的是 /boot/efi/EFI/airymaxos/grub.cfg，而 grub2-mkconfig 只写
# EFI/openEuler 那份。285H（2026-11-03）用两个不同的标记参数分别写进两份
# cfg 后重启，回来的命令行只含品牌副本的标记——品牌副本才是活动配置。只
# 重建不复制，改了参数重启后照旧（D-07），内核升级后菜单也停在旧内核。
#
# 为什么同时落字体：引导菜单的 gfxmode 段落以 loadfont 成功为前提，而
# loadfont 解析 $prefix/fonts/unicode.pf2，$prefix 就是上面那个被加载的
# 目录。字体缺失时该段落整段消失，菜单与 efifb 停在固件默认分辨率（真机
# B50 的 800x600）。因此字体在生效配置目录与品牌副本目录都要落一份：前者
# 是生成侧的一致性，后者才是引导期真正被读到的位置。
#
# 为什么菜单停留时间也归本文件：285H 冷启动分段里 loader 段 3.78s，其中 3s
# 是 GRUB_TIMEOUT 的默认停留，这段时间不产出任何信息，等于每次开机向用户
# 收 3 秒。菜单本身仍然可达——任何一个键都会中止倒数——缩短只改「不看菜单」
# 的默认路径。它和参数行一样只能有一个来源：这里的常量；spec 里写的是安装
# 器生成的初始文件，安装末期由本脚本归一化。
#
# 退出码：0 = 已收敛（含无需改动）；1 = 参数未能落地；2 = 用法错误。调用者
#         据 1 中止安装：静默降级只会把观感问题推迟到验收现场。
# ===========================================================================

defaults=/etc/default/grub
esp=
cfg=
etc=/etc
state=/var/lib/airymaxos/grub-args
consoles='ttyS0,115200 tty0'
args='loglevel=5 plymouth.enable=0'
# 旧版本写进命令行的画面参数。merge 只补不删，升级机器上它们一定还在；
# 不在这里摘掉，同一份配置在全新安装与升级两条路径上会得到两种观感——
# 前者逐行打印，后者被 splash 与 quiet 重新藏起来。
stale='rhgb quiet'
timeout=1
mkconfig=grub2-mkconfig
font=
mode=apply

note()
{
    printf 'AIRYMAX-GRUB-NOTE %s\n' "$*"
}

fail()
{
    note "fail: $*"
    exit 1
}

usage()
{
    printf 'usage: %s [--defaults FILE] [--cfg FILE] [--esp DIR]\n' "$0" >&2
    printf '       [--etc DIR] [--state FILE] [--append ARGS] [--timeout SECS]\n' >&2
    printf '       [--font FILE] [--mkconfig CMD] [--check] [--no-regen]\n' >&2
}

while [ $# -gt 0 ]; do
    case "$1" in
    --defaults) defaults=${2:?--defaults 需要文件}; shift 2 ;;
    --cfg) cfg=${2:?--cfg 需要文件}; shift 2 ;;
    --esp) esp=${2:?--esp 需要目录}; shift 2 ;;
    --etc) etc=${2:?--etc 需要目录}; shift 2 ;;
    --state) state=${2:?--state 需要文件}; shift 2 ;;
    --append) args=${2?--append 需要参数}; shift 2 ;;
    --timeout) timeout=${2:?--timeout 需要秒数}; shift 2 ;;
    --font) font=${2:?--font 需要文件}; shift 2 ;;
    --mkconfig) mkconfig=${2:?--mkconfig 需要命令}; shift 2 ;;
    --check) mode=check; shift ;;
    --no-regen) mode=edit; shift ;;
    *) usage; exit 2 ;;
    esac
done

# 非数字的停留时间会被生成器当成 0 或解析失败，菜单随即一闪而过，误用显式
# 失败而不是静默落一个不可预期的秒数。
case "${timeout}" in
'' | *[!0-9]*) usage; exit 2 ;;
esac

[ -r "${defaults}" ] || fail "no ${defaults}"

# console= 是顺序敏感项，不接受从命令行追加：--append 的用法是补普通参数，
# 塞进来的控制台会排到 tty0 之后并抢走 /dev/console。误用即用法错误，不静默
# 丢弃——静默丢弃会让调用者以为已经生效。
for tok in ${args}; do
    case "${tok}" in
    console=*) usage; exit 2 ;;
    esac
done

# 期望的 console= 串与主控制台各由 consoles 唯一推出，判定与改写都读它。
console_args()
{
    local d out=
    for d in ${consoles}; do
        out="${out} console=${d}"
    done
    printf '%s\n' "${out# }"
}

main_console()
{
    printf 'console=%s\n' "${consoles##* }"
}

# 参数行是生成器的输入，判定与改写都读同一个来源，避免「文件里有、生成后
# 没有」这类只在下次重启才暴露的偏差。
read_args()
{
    awk '/^[[:space:]]*GRUB_CMDLINE_LINUX=/ {
        v = substr($0, index($0, "=") + 1)
        gsub(/"/, "", v)
        print v
        exit
    }' "${defaults}"
}

read_prober()
{
    awk -F= '/^[[:space:]]*GRUB_DISABLE_OS_PROBER=/ {
        v = $2
        gsub(/["[:space:]]/, "", v)
        print v
        exit
    }' "${defaults}"
}

read_timeout()
{
    awk -F= '/^[[:space:]]*GRUB_TIMEOUT=/ {
        v = $2
        gsub(/["[:space:]]/, "", v)
        print v
        exit
    }' "${defaults}"
}

verify()
{
    local line tok rc=0
    line=$(read_args)
    for tok in ${args}; do
        case " ${line} " in
        *" ${tok} "*) continue ;;
        esac
        note "missing: ${tok}"
        rc=1
    done
    for tok in ${stale}; do
        case " ${line} " in
        *" ${tok} "*) note "stale: ${tok}"; rc=1 ;;
        esac
    done
    check_consoles "${line}" || rc=1
    [ "$(read_prober)" = true ] || {
        note 'GRUB_DISABLE_OS_PROBER is not true'
        rc=1
    }
    [ "$(read_timeout)" = "${timeout}" ] || {
        note "GRUB_TIMEOUT is not ${timeout}"
        rc=1
    }
    [ "${rc}" -eq 0 ] || return 1
    note "ok: ${defaults} carries '$(console_args) ${args}' timeout=${timeout}"
}

# 控制台集合三个方向都要成立：缺项丢一路日志，外来项指向不存在的设备并
# 抢占 /dev/console（285H 的 ttyAMA0），顺序错则 /dev/console 落到串口。
check_consoles()
{
    local line=$1 got= tok d rc=0 last=
    for tok in ${line}; do
        case "${tok}" in
        console=?*) got="${got} ${tok}" ;;
        esac
    done
    for d in ${consoles}; do
        case " ${got} " in
        *" console=${d} "*) continue ;;
        esac
        note "missing: console=${d}"
        rc=1
    done
    for tok in ${got}; do
        case " $(console_args) " in
        *" ${tok} "*) continue ;;
        esac
        note "foreign: ${tok}"
        rc=1
    done
    for tok in ${got}; do
        last=${tok}
    done
    [ "${last}" = "$(main_console)" ] || {
        note "order: ${last:-none} is not the primary console"
        rc=1
    }
    return "${rc}"
}

# 改写走 awk 单遍：保留文件其余内容与顺序，只重写参数行与探测开关。写回用
# cat 覆盖而不是 rename，inode、属主与 SELinux 上下文因此都不变。
edit()
{
    local tmp="${defaults}.airy-tmp"
    awk -v add="${args}" -v cons="${consoles}" -v tout="${timeout}" \
        -v prober=true -v drop="${stale}" '
    # 旧 console= 全部摘掉：它们的顺序与集合都属于上一次安装或手工改动，
    # 保留任何一个都可能抢走 /dev/console。stale 里的旧画面参数同理——它们
    # 与新策略直接冲突，留着等于没改。
    function nocons(v,   i, n, out, tok) {
        n = split(v, tok, /[[:space:]]+/)
        out = ""
        for (i = 1; i <= n; i++) {
            if (tok[i] == "" || tok[i] ~ /^console=/) continue
            if (index(" " drop " ", " " tok[i] " ") > 0) continue
            out = (out == "" ? tok[i] : out " " tok[i])
        }
        return out
    }
    function merge(v,   i, j, n, m, want, tok, have) {
        n = split(add, want, /[[:space:]]+/)
        m = split(v, tok, /[[:space:]]+/)
        for (j = 1; j <= n; j++) {
            if (want[j] == "") continue
            have = 0
            for (i = 1; i <= m; i++)
                if (tok[i] == want[j]) have = 1
            if (have) continue
            v = (v == "" ? want[j] : v " " want[j])
        }
        return v
    }
    # 控制台按常量重放到最前，末位固定是 tty0。
    function lead(v,   i, n, tok, out) {
        n = split(cons, tok, /[[:space:]]+/)
        out = ""
        for (i = 1; i <= n; i++) {
            if (tok[i] == "") continue
            out = (out == "" ? "console=" tok[i] : out " console=" tok[i])
        }
        return (v == "" ? out : out " " v)
    }
    BEGIN { seen = 0; pseen = 0; tseen = 0 }
    /^[[:space:]]*GRUB_CMDLINE_LINUX=/ {
        v = substr($0, index($0, "=") + 1)
        gsub(/"/, "", v)
        sub(/^[[:space:]]+/, "", v)
        sub(/[[:space:]]+$/, "", v)
        printf "GRUB_CMDLINE_LINUX=\"%s\"\n", lead(merge(nocons(v)))
        seen = 1
        next
    }
    # 只重写生效的那一条；同名多赋值时后者生效，保留前者会把旧秒数留在
    # 文件里，下一次手工编辑看不出哪条算数。
    /^[[:space:]]*GRUB_TIMEOUT=/ {
        if (!tseen) print "GRUB_TIMEOUT=" tout
        tseen = 1
        next
    }
    /^[[:space:]]*#?[[:space:]]*GRUB_DISABLE_OS_PROBER=/ {
        if (!pseen) print "GRUB_DISABLE_OS_PROBER=" prober
        pseen = 1
        next
    }
    { print }
    END {
        if (!tseen) print "GRUB_TIMEOUT=" tout
        if (!seen) print "GRUB_CMDLINE_LINUX=\"" lead(merge("")) "\""
        if (!pseen) print "GRUB_DISABLE_OS_PROBER=" prober
    }' "${defaults}" >"${tmp}" || fail "rewrite ${defaults} failed"
    if cmp -s "${tmp}" "${defaults}"; then
        rm -f "${tmp}"
        note "unchanged: ${defaults}"
        return 1
    fi
    cat "${tmp}" >"${defaults}" || fail "write ${defaults} failed"
    rm -f "${tmp}"
    note "updated: ${defaults}"
    return 0
}

# 生效配置由发行版自己决定（EFI 是 /etc/grub2-efi.cfg，BIOS 是
# /etc/grub2.cfg），这里跟随符号链接，不猜路径。
#
# 只打印不赋值：调用方用命令替换取结果，命令替换在子 shell 里执行，函数
# 内对全局变量的赋值出了子 shell 就没了。0.0.3 的 UEFI 装机正是栽在这里——
# cfg 拿到空串，真正的生成步骤无文件可写，安装器在最后的 %post 中止。
pick_cfg()
{
    local f
    for f in "${etc}/grub2-efi.cfg" "${etc}/grub2.cfg"; do
        [ -e "${f}" ] || continue
        readlink -f "${f}" || return 1
        return 0
    done
    return 1
}

# 生成失败而旧配置可用时保留旧配置：引导能力优先于菜单整洁，且旧配置来自
# 安装器的 --append，首启仍有启动画面。这种情况必须以 skip 显式上报。
regen()
{
    local bak="${state%/*}/grub.cfg.prev"
    command -v "${mkconfig}" >/dev/null 2>&1 ||
        fail "${mkconfig} unavailable"
    [ -s "${cfg}" ] || fail "grub config '${cfg}' missing or empty"
    cp -f "${cfg}" "${bak}" || fail "backup ${cfg} failed"
    if "${mkconfig}" -o "${cfg}" >/dev/null 2>&1 && [ -s "${cfg}" ] &&
        grep -q 'menuentry' "${cfg}"; then
        rm -f "${bak}"
        note "regenerated: ${cfg}"
        return 0
    fi
    cp -f "${bak}" "${cfg}" || fail "restore ${cfg} failed"
    rm -f "${bak}"
    note "skip: kept previous ${cfg} (generation failed)"
}

# 字体是 gfxmode 段落的前提：00_header 的 `loadfont $font` 找的是
# $prefix/fonts/<name>.pf2，$prefix 由 grubx64.efi 内嵌，指向发行版自己的
# ESP 目录，与本产品的品牌副本目录不同名。B50 实测：品牌目录里有字体、
# 真正被加载的目录没有，loadfont 失败后 gfxmode 段落整段消失，菜单与 efifb
# 一起停在固件默认 800x600，而 cfg 里候选列表一应俱全。因此字体只按生效
# 配置所在目录落位——那正是 $prefix，不按目录名猜。
font_src()
{
    local f
    if [ -n "${font}" ]; then
        [ -r "${font}" ] || return 1
        printf '%s\n' "${font}"
        return 0
    fi
    for f in /usr/share/grub/unicode.pf2 /boot/grub2/fonts/unicode.pf2; do
        [ -r "${f}" ] || continue
        printf '%s\n' "${f}"
        return 0
    done
    return 1
}

# 字体缺失只降级不中止：菜单字形与分辨率是观感问题，而退出码 1 会中止整个
# 安装。note 足以在装机日志里留下归因线索。
put_font()
{
    local dir=$1 src=$2
    [ -f "${dir}/unicode.pf2" ] && cmp -s "${src}" "${dir}/unicode.pf2" &&
        return 0
    if install -d -m 0755 "${dir}" &&
        install -m 0644 "${src}" "${dir}/unicode.pf2"; then
        note "font placed: ${dir}/unicode.pf2"
        return 0
    fi
    note "font not placed: ${dir}/unicode.pf2"
    return 0
}

# 品牌副本目录与被加载的 grubx64.efi 同目录，因此它同时是引导期的 $prefix。
# --esp 显式给出时装机场景使用；未给出时按生效配置的兄弟目录推断。
brand_dir()
{
    if [ -n "${esp}" ]; then
        printf '%s\n' "${esp}/EFI/airymaxos"
        return 0
    fi
    printf '%s\n' "${cfg%/*}/../airymaxos"
}

sync_font()
{
    local dir src
    if ! src=$(font_src); then
        note "font source absent"
        return 0
    fi
    put_font "${cfg%/*}/fonts" "${src}"
    dir=$(brand_dir)
    [ -d "${dir}" ] || return 0
    put_font "${dir}/fonts" "${src}"
}

# 品牌副本是活动配置：生成后必须整份覆盖，否则下一次引导仍按旧命令行。
# install 而非 cp，保持项目统一的落位手法与权限；内容相同则不动，重复调用
# 不产生写放大。
sync_brand()
{
    local dir copy
    dir=$(brand_dir)
    copy="${dir}/grub.cfg"
    [ -f "${copy}" ] || return 0
    cmp -s "${cfg}" "${copy}" && return 0
    install -m 700 "${cfg}" "${copy}" &&
        note "brand copy refreshed: ${copy}" ||
        note "brand copy not refreshed: ${copy}"
}

if [ "${mode}" = check ]; then
    verify || exit 1
    exit 0
fi

# --no-regen 只改写输入文件：生成与 ESP 副本同步需要真机块设备视图，回归
# 测试用它在临时目录里判定改写本身（与 display_mode.sh --plan 同一个用意）。
edit
[ "${mode}" = edit ] && exit 0

[ -n "${cfg}" ] || cfg=$(pick_cfg) ||
    fail "no ${etc}/grub2-efi.cfg or ${etc}/grub2.cfg"
install -d -m 0755 "${state%/*}" || fail "create ${state%/*} failed"
sync_font
regen
sync_brand
verify || fail "args not present in ${defaults}"
printf 'defaults=%s\ncfg=%s\nargs=%s\n' "${defaults}" "${cfg}" \
    "$(console_args) ${args}" >"${state}" || fail "write ${state} failed"
note "cfg=${cfg} args=$(console_args) ${args}"
