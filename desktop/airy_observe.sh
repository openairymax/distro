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
# --static 只读文件、不执行任何系统命令：构建期在 buildroot 上核对品牌与
# 资产是否落位，不要求构建机有 X server 或 systemd。--root 指定观察根，
# 与 --static 配合用于打包自检。
#
# 末三行固定为 mode、fields、status：调用方按 status 判一次结论即可，
# 不必自己聚合各行。status=ok 表示身份与桌面链都成立，非零退出码让脚本
# 能直接用在 CI 断言里。
#
# 依赖：POSIX sh、awk、sed；活体模式另需 systemctl、xrandr、ip（可选）。
# ===========================================================================

set -u

MARK=AIRYMAX-OBSERVE
WANT_ID=airymaxos
SLICES="system.slice user.slice airymax.slice airymax-desktop.slice"
ROOT=/
STATIC=0
fields=0
status=ok

emit() {
    val=${2:-absent}
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

static_report() {
    osr=${ROOT}/usr/lib/os-release
    [ -r "$osr" ] || osr=${ROOT}/etc/os-release
    os_id=$(read_kv "$osr" ID) || os_id=absent
    emit os.id "$os_id"
    emit os.version "$(read_kv "$osr" VERSION_ID || printf absent)"
    emit os.pretty "$(read_kv "$osr" PRETTY_NAME || printf absent)"
    emit brand.grub "$(read_kv "${ROOT}/etc/default/grub" GRUB_DISTRIBUTOR ||
        printf absent)"
    wallpaper=$(have /usr/share/backgrounds/airymaxos/airymaxos-default.jpg)
    emit brand.wallpaper "$wallpaper"
    schema=$(have /usr/share/glib-2.0/schemas/99-airymaxos-default.gschema.override)
    emit brand.schema "$schema"
    desktop=$(have /usr/lib/airymaxos/desktop/desktop_ready.sh)
    emit asset.desktop "$desktop"
    recorder=$(have /usr/lib/airymaxos/desktop/airy_record.sh)
    emit asset.record "$recorder"
    observer=$(have /usr/lib/airymaxos/desktop/airy_observe.sh)
    emit asset.observe "$observer"
    host=$(cat "${ROOT}/etc/hostname" 2>/dev/null) || host=
    emit host.name "${host:-absent}"
    [ "$os_id" = "$WANT_ID" ] || status=partial
    for v in "$wallpaper" "$schema" "$desktop" "$recorder" "$observer"; do
        [ "$v" = present ] || status=partial
    done
}

live_report() {
    emit kernel.release "$(uname -r 2>/dev/null || printf absent)"
    owner=$(rpm -q --qf '%{NAME}' -f "/boot/vmlinuz-$(uname -r)" 2>/dev/null) ||
        owner=unowned
    emit kernel.owner "${owner:-unowned}"
    sess=${XDG_SESSION_TYPE:-}
    [ -n "$sess" ] || {
        [ -n "${DISPLAY:-}" ] && sess=x11 || sess=absent
    }
    emit session.type "$sess"
    emit session.display "${DISPLAY:-absent}"
    emit display.outputs "$(outputs)"
    ready=$(systemctl is-active airymax-desktop-ready.service 2>/dev/null) ||
        ready=absent
    emit desktop.ready "${ready:-absent}"
    failed=$(failed_count)
    emit boot.health "$failed"
    emit rt.budget "$(rt_budget)"
    emit mem.total_kb "$(meminfo MemTotal)"
    emit mem.avail_kb "$(meminfo MemAvailable)"
    emit cpu.count "$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf absent)"
    emit root.used "$(df -P / 2>/dev/null | awk 'NR == 2 { print $5 }')"
    emit net.ipv4 "$(net_v4)"
    [ "$failed" = 0 ] || status=partial
    [ "$ready" = active ] || status=partial
}

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
    -h | --help)
        printf '用法: airy-observe [--static] [--root DIR]\n'
        exit 0
        ;;
    *)
        printf '%s fail reason=unknown-arg=%s\n' "$MARK" "$1" >&2
        exit 2
        ;;
    esac
done

if [ "$STATIC" -eq 1 ]; then
    static_report
    mode=static
else
    live_report
    mode=live
fi

printf '%s mode=%s fields=%s\n' "$MARK" "$mode" "$fields"
printf '%s status=%s\n' "$MARK" "$status"
[ "$status" = ok ]
