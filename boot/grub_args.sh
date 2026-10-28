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
# 为唯一输入，启动画面参数随即消失，表现为「装好有画面，升级一次又逐行滚
# 日志」。真机 B50 取证：/proc/cmdline 缺 rhgb quiet，且 grub.cfg 的 linux
# 行与 /etc/default/grub 完全一致——缺失发生在生成期，不是运行期。
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
# 为什么同时落字体：引导菜单的 gfxmode 段落以 loadfont 成功为前提，而
# loadfont 解析 $prefix/fonts/unicode.pf2，$prefix 由 grubx64.efi 内嵌、
# 指向发行版目录（openEuler），不是品牌副本目录。字体缺失时该段落整段消失，
# 菜单与 efifb 停在固件默认分辨率（真机 B50 的 800x600）。生效配置由
# pick_cfg 给出，其所在目录即 $prefix，因此字体只需落在它的 fonts/ 下。
#
# 退出码：0 = 已收敛（含无需改动）；1 = 参数未能落地；2 = 用法错误。调用者
#         据 1 中止安装：静默降级只会把观感问题推迟到验收现场。
# ===========================================================================

defaults=/etc/default/grub
esp=
cfg=
etc=/etc
state=/var/lib/airymaxos/grub-args
args='rhgb quiet'
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
    printf '       [--etc DIR] [--state FILE] [--append ARGS] [--font FILE]\n' >&2
    printf '       [--mkconfig CMD] [--check] [--no-regen]\n' >&2
}

while [ $# -gt 0 ]; do
    case "$1" in
    --defaults) defaults=${2:?--defaults 需要文件}; shift 2 ;;
    --cfg) cfg=${2:?--cfg 需要文件}; shift 2 ;;
    --esp) esp=${2:?--esp 需要目录}; shift 2 ;;
    --etc) etc=${2:?--etc 需要目录}; shift 2 ;;
    --state) state=${2:?--state 需要文件}; shift 2 ;;
    --append) args=${2?--append 需要参数}; shift 2 ;;
    --font) font=${2:?--font 需要文件}; shift 2 ;;
    --mkconfig) mkconfig=${2:?--mkconfig 需要命令}; shift 2 ;;
    --check) mode=check; shift ;;
    --no-regen) mode=edit; shift ;;
    *) usage; exit 2 ;;
    esac
done

[ -r "${defaults}" ] || fail "no ${defaults}"

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
    [ "$(read_prober)" = true ] || {
        note 'GRUB_DISABLE_OS_PROBER is not true'
        rc=1
    }
    [ "${rc}" -eq 0 ] || return 1
    note "ok: ${defaults} carries '${args}'"
}

# 改写走 awk 单遍：保留文件其余内容与顺序，只重写参数行与探测开关。写回用
# cat 覆盖而不是 rename，inode、属主与 SELinux 上下文因此都不变。
edit()
{
    local tmp="${defaults}.airy-tmp"
    awk -v add="${args}" -v prober=true '
    function emit(v,   i, n, out, tok) {
        n = split(v, tok, /[[:space:]]+/)
        out = ""
        for (i = 1; i <= n; i++) {
            if (tok[i] == "") continue
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
    BEGIN { seen = 0; pseen = 0 }
    /^[[:space:]]*GRUB_CMDLINE_LINUX=/ {
        v = substr($0, index($0, "=") + 1)
        gsub(/"/, "", v)
        sub(/^[[:space:]]+/, "", v)
        sub(/[[:space:]]+$/, "", v)
        printf "GRUB_CMDLINE_LINUX=\"%s\"\n", merge(emit(v))
        seen = 1
        next
    }
    /^[[:space:]]*#?[[:space:]]*GRUB_DISABLE_OS_PROBER=/ {
        if (!pseen) print "GRUB_DISABLE_OS_PROBER=" prober
        pseen = 1
        next
    }
    { print }
    END {
        if (!seen) print "GRUB_CMDLINE_LINUX=\"" add "\""
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
sync_font()
{
    local dir src
    dir=$(dirname "${cfg}")/fonts
    if ! src=$(font_src); then
        note "font source absent"
        return 0
    fi
    cmp -s "${src}" "${dir}/unicode.pf2" && return 0
    if install -d -m 0755 "${dir}" &&
        install -m 0644 "${src}" "${dir}/unicode.pf2"; then
        note "font placed: ${dir}/unicode.pf2"
        return 0
    fi
    note "font not placed: ${dir}/unicode.pf2"
    return 0
}

# ESP 内的 grub.cfg 只是品牌一致性副本（grubx64 内嵌 prefix 指向发行版
# 目录，真正生效的是上面那份）。生成后同步一次，副本就不会逐次升级老化。
sync_brand()
{
    local copy
    [ -n "${esp}" ] || return 0
    copy="${esp}/EFI/airymaxos/grub.cfg"
    [ -f "${copy}" ] || return 0
    cp -f "${cfg}" "${copy}" && note "brand copy refreshed: ${copy}" ||
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
printf 'defaults=%s\ncfg=%s\nargs=%s\n' "${defaults}" "${cfg}" "${args}" \
    >"${state}" || fail "write ${state} failed"
note "cfg=${cfg} args=${args}"
