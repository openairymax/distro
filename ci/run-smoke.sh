#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-smoke.sh — distro 组合冒烟（TAP 14）
#
# 用法:
#   ./run-smoke.sh <被测镜像/系统标识>
#   在已登录的 UKUI X11 桌面会话内执行；探测只读系统状态，不改配置。
#
# 环境:
#   AIRYMAX_SMOKE_WAIT  守护进程就绪等待秒数（默认 30）
#   AIRYMAX_SMOKE_HOST  期望的主机名（默认 airymaxos，即 workstation 配方值）
#   AIRYMAX_SMOKE_ROOT  只读系统视图的根前缀（默认空，即真实 /）。T6–T13 读取
#                       /boot、/sys、/etc 与 /usr/lib 下的发行版标识与资产，
#                       单测在沙箱里用该前缀复核判定，装机现场保持默认值。
#
# 覆盖:
#   T1  UKUI X11 会话：loginctl 会话属性、ukui-session 进程、X server 可达
#   T2  fcitx 4 输入法：守护进程、fcitx-remote 可达、会话输入法变量
#   T3  PulseAudio 音频栈：pactl 与守护进程握手
#   T4  桌面隔离 slice：user@UID.service 归属与 slice 资源参数
#   T5  内置壁纸：背景键指向内置路径，图像 sha256 与发行资产一致
#   T6  内核归属：运行的内核是包内 ALK，/boot 三件套齐全且配置一致
#   T7  LSM 注册表：airy 只登记一次，配套 lockdown LSM 在位
#   T8  主机名：/etc/hostname 是产品名，不是安装器缺省名
#   T9  品牌：/etc/os-release 的 NAME/ID/PRETTY_NAME/VERSION_ID 指向本产品
#   T10 分辨率：每个 connected 输出处于 display_mode.sh 定义的策略模式
#   T11 EFI 品牌：ESP 内 airymaxos 目录是完整签名套件，BootOrder 首位为本产品
#   T12 免密提权：交付账户能以 NOPASSWD 完成一次非交互提权
#   T13 免密桌面：空闲锁屏关闭，交付账户在 nopasswdlogin 组内
#
# 判定语义:
#   0  — 全部通过
#   1  — 存在失败用例
# 探测工具由被测镜像自身提供（loginctl/pgrep/xdpyinfo 来自本项目的包组合），
# 缺失说明镜像不完整，按失败计；不以 SKIP 掩盖，因为这里没有“不支持的外
# 部测试机”这一情形。
#
# 本脚本自身由 XDG autostart 拉起，与 fcitx、pulseaudio 的 autostart 条目
# 同阶段并发执行，守护进程此刻可能尚未就绪。因此这两项探测做有界等待：
# AIRYMAX_SMOKE_WAIT 秒内反复探测，超时仍不就绪即判失败（不放宽判定）。
# ===========================================================================
set -uo pipefail

TARGET="${1:?usage: run-smoke.sh <target-id>}"
WALLPAPER=/usr/share/backgrounds/airymaxos/airymaxos-default.jpg
PAPER_SHA=fee7f439834ac7dacfc75deaf80a1db1c4bc7459583248eecc87125d52a5ef18
START_WAIT="${AIRYMAX_SMOKE_WAIT:-30}"
HOSTNAME_WANT="${AIRYMAX_SMOKE_HOST:-airymaxos}"
SYSROOT="${AIRYMAX_SMOKE_ROOT:-}"

PASS=0
FAIL=0

tap_ok() {
    printf 'ok %s - %s\n' "$1" "$2"
    PASS=$((PASS + 1))
}

tap_fail() {
    printf 'not ok %s - %s\n' "$1" "$2"
    if [ -n "${3:-}" ]; then
        printf '#   %s\n' "$3"
    fi
    FAIL=$((FAIL + 1))
}

probe() { # probe <编号> <名称> <探测函数>
    local id="$1" name="$2" out rc
    shift 2
    out="$("$@" 2>&1)"
    rc=$?
    if [ "${rc}" -eq 0 ]; then
        [ -n "${out}" ] && printf '#   %s\n' "${out}"
        tap_ok "${id}" "${name}"
    else
        tap_fail "${id}" "${name}" "${out:-probe rc=${rc}}"
    fi
}

need() { # need <命令> — 探测工具随镜像交付，缺失即失败
    command -v "$1" >/dev/null 2>&1 && return 0
    printf '%s not installed\n' "$1"
    return 1
}

expect() { # expect <实际值> <期望值> <字段>
    [ "$1" = "$2" ] && return 0
    printf '%s: %s (want %s)\n' "$3" "${1:-unknown}" "$2"
    return 1
}

expect_prefix() { # expect_prefix <实际值> <期望前缀> <字段>
    case "$1" in
    "$2"*) return 0 ;;
    esac
    printf '%s: %s (want %s*)\n' "$3" "${1:-unknown}" "$2"
    return 1
}

retry() { # retry <秒> <命令...> — 等待并发启动的守护进程，超时即失败
    local limit="$1" waited=0
    shift
    until "$@" >/dev/null 2>&1; do
        [ "${waited}" -ge "${limit}" ] && return 1
        sleep 1
        waited=$((waited + 1))
    done
}

session_prop() { # session_prop <loginctl 属性>
    loginctl show-session "${XDG_SESSION_ID}" -p "$1" --value 2>/dev/null || :
}

slice_prop() { # slice_prop <systemd 属性>
    systemctl show airymax-desktop.slice -p "$1" --value 2>/dev/null || :
}

os_rel() { # os_rel <os-release 键> — 去掉赋值两侧的引号
    sed -n "s/^$1=//p" "${SYSROOT}/etc/os-release" | tr -d '"'
}

# T1: UKUI X11 会话（lightdm 会话 + 会话进程 + X server）
t1_x11() {
    need loginctl || return $?
    need pgrep || return $?
    need xdpyinfo || return $?
    [ -n "${DISPLAY:-}" ] || { echo "DISPLAY unset"; return 1; }
    [ -n "${XDG_SESSION_ID:-}" ] || { echo "XDG_SESSION_ID unset"; return 1; }
    expect "$(session_prop Type)" x11 "session type" || return 1
    expect_prefix "$(session_prop Service)" lightdm "session service" ||
        return 1
    expect "$(session_prop Active)" yes "session active" || return 1
    pgrep -f ukui-session >/dev/null || {
        echo "ukui-session not running"
        return 1
    }
    xdpyinfo >/dev/null 2>&1 || {
        echo "X11 unreachable: ${DISPLAY}"
        return 1
    }
}

ime_state() { # ime_state — 打印 fcitx 状态，socket 不可达时返回非零
    fcitx-remote 2>/dev/null
}

# T2: 输入法（fcitx 4 守护进程与会话变量）
t2_ime() {
    need pgrep || return $?
    command -v fcitx-remote >/dev/null 2>&1 || {
        echo "fcitx-remote not installed"
        return 1
    }
    retry "${START_WAIT}" pgrep -x fcitx || {
        echo "fcitx not running"
        return 1
    }
    retry "${START_WAIT}" ime_state || {
        echo "fcitx-remote cannot reach daemon"
        return 1
    }
    local state
    state="$(ime_state)"
    case "${state}" in
    0 | 1 | 2) : ;;
    *)
        echo "fcitx-remote state: ${state:-empty}"
        return 1
        ;;
    esac
    expect "${GTK_IM_MODULE:-}" fcitx "GTK_IM_MODULE" || return 1
    expect "${QT_IM_MODULE:-}" fcitx "QT_IM_MODULE" || return 1
    expect "${XMODIFIERS:-}" "@im=fcitx" "XMODIFIERS" || return 1
}

# T3: 音频栈（PulseAudio 客户端握手）
t3_audio() {
    command -v pactl >/dev/null 2>&1 || {
        echo "pactl not installed"
        return 1
    }
    retry "${START_WAIT}" pactl info || {
        echo "PulseAudio unreachable"
        return 1
    }
}

# T4: 桌面隔离 slice（会话归属与资源参数）
t4_slice() {
    need systemctl || return $?
    local tasks
    expect "$(systemctl show "user@${UID}.service" -p Slice --value 2>/dev/null)" \
        airymax-desktop.slice "user@ service slice" || return 1
    expect "$(systemctl is-active airymax-desktop.slice 2>/dev/null)" \
        active "slice state" || return 1
    expect "$(slice_prop CPUWeight)" 50 "slice CPUWeight" || return 1
    expect "$(slice_prop IOWeight)" 50 "slice IOWeight" || return 1
    tasks="$(slice_prop TasksMax)"
    [ -n "${tasks}" ] && [ "${tasks}" != infinity ] || {
        echo "slice TasksMax: ${tasks:-unknown}"
        return 1
    }
}

# T5: 内置壁纸（背景键与图像内容）
t5_wallpaper() {
    command -v gsettings >/dev/null 2>&1 || {
        echo "gsettings not installed"
        return 1
    }
    local path sum
    path="$(gsettings get org.mate.background picture-filename 2>&1)" || {
        echo "org.mate.background picture-filename: ${path:-unavailable}"
        return 1
    }
    expect "${path//\'/}" "${WALLPAPER}" "picture-filename" || return 1
    sum="$(sha256sum "${WALLPAPER}" 2>&1)" || {
        echo "wallpaper unreadable: ${WALLPAPER}"
        return 1
    }
    expect "${sum%% *}" "${PAPER_SHA}" "wallpaper sha256" || return 1
}

# T6: 内核归属（运行内核、/boot 三件套与配置一致）
t6_kernel_identity() {
    local rel f
    rel="$(uname -r)"
    # 发行版内核带 -alk 本地版本后缀，这是「跑的是不是自己的内核」最便宜的
    # 判别。上游 openEuler 内核为 6.6.0-*.oe*，不会被误判为通过。
    case "${rel}" in
    *-alk) : ;;
    *)
        echo "uname -r: ${rel} (want *-alk)"
        return 1
        ;;
    esac
    for f in "${SYSROOT}/boot/vmlinuz-${rel}" "${SYSROOT}/boot/config-${rel}" \
        "${SYSROOT}/boot/System.map-${rel}"; do
        [ -s "${f}" ] || {
            echo "${f} missing"
            return 1
        }
    done
    grep -qx 'CONFIG_LOCALVERSION="-alk"' "${SYSROOT}/boot/config-${rel}" || {
        echo "config-${rel}: LOCALVERSION mismatch"
        return 1
    }
    grep -qx 'CONFIG_SECURITY_AIRY=y' "${SYSROOT}/boot/config-${rel}" || {
        echo "config-${rel}: CONFIG_SECURITY_AIRY not set"
        return 1
    }
    grep -q ' start_kernel$' "${SYSROOT}/boot/System.map-${rel}" || {
        echo "System.map-${rel}: start_kernel absent"
        return 1
    }
}

# T7: LSM 注册表（同名模块只能登记一次）
t7_lsm_registry() {
    local list seen
    list="$(cat "${SYSROOT}/sys/kernel/security/lsm" 2>&1)" || {
        echo "lsm registry unreadable: ${list}"
        return 1
    }
    # security_add_hooks() 顺带把模块名写进这张表，而 lsm_append() 只与
    # 末尾名字去重。补充钩子若在 late_initcall 里以同名二次注册，"airy"
    # 就会出现两次：这不是两个模块，而是同一个模块被登记了两遍。
    seen="$(printf '%s\n' "${list}" | tr ',' '\n' | grep -cx 'airy')"
    [ "${seen}" -eq 1 ] || {
        echo "airy registered ${seen} time(s): ${list}"
        return 1
    }
    # airy_lockdown 是独立命名的一层（只挂 locked_down），随产品内核交付。
    printf '%s\n' "${list}" | tr ',' '\n' | grep -qx 'airy_lockdown' || {
        echo "airy_lockdown absent: ${list}"
        return 1
    }
}

# T8: 主机名（配方不写 hostname 时安装器会留下缺省名，产品身份就丢了）
t8_hostname() {
    local file="${SYSROOT}/etc/hostname"
    [ -r "${file}" ] || {
        echo "${file} unreadable"
        return 1
    }
    expect "$(cat "${file}")" "${HOSTNAME_WANT}" "hostname" || return 1
}

# T9: 品牌（os-release 是发行版身份的唯一载体，桌面与会话代理都读它）
t9_brand() {
    local file="${SYSROOT}/etc/os-release" ver
    [ -r "${file}" ] || {
        echo "${file} unreadable"
        return 1
    }
    expect "$(os_rel NAME)" AirymaxOS "os-release NAME" || return 1
    expect "$(os_rel ID)" airymaxos "os-release ID" || return 1
    expect_prefix "$(os_rel PRETTY_NAME)" "AirymaxOS " "os-release PRETTY_NAME" ||
        return 1
    ver="$(os_rel VERSION_ID)"
    case "${ver}" in
    [0-9]*.[0-9]*.[0-9]*) : ;;
    *)
        echo "os-release VERSION_ID: ${ver:-absent} (want X.Y.Z)"
        return 1
        ;;
    esac
}

# T10: 分辨率（会话输出必须处于策略模式，策略单点在 display_mode.sh）
t10_display() {
    local script="${SYSROOT}/usr/lib/airymaxos/desktop/display_mode.sh"
    need xrandr || return $?
    [ -x "${script}" ] || {
        echo "${script} not installed"
        return 1
    }
    # 会话内的收敛是并发的有界过程（xinitrc.d 钩子 + autostart），本探测
    # 同样等待到同一个上界再判定，避免把「尚未收敛」误判成「策略失效」。
    retry "${START_WAIT}" "${script}" --check && return 0
    "${script}" --check
}

# T11: EFI 品牌（安装期品牌化把 NVRAM 首选项换成 AirymaxOS，ESP 内是一整套
# 已签名二级加载器；shim 只从自身目录取 grubx64.efi，缺一即不可引导）
t11_efi_brand() {
    local esp="${SYSROOT}/boot/efi" out first
    if [ ! -d "${SYSROOT}/sys/firmware/efi" ]; then
        echo "non-EFI target: no NVRAM entry to brand"
        return 0
    fi
    for f in shimx64.efi grubx64.efi; do
        [ -f "${esp}/EFI/airymaxos/${f}" ] || {
            echo "${esp}/EFI/airymaxos/${f} missing"
            return 1
        }
    done
    [ -s "${esp}/EFI/airymaxos/BOOTX64.CSV" ] || {
        echo "${esp}/EFI/airymaxos/BOOTX64.CSV missing"
        return 1
    }
    # 只读复核时 NVRAM 属于宿主而非被测系统，到此为止。
    [ -n "${SYSROOT}" ] && return 0
    need efibootmgr || return $?
    out=$(efibootmgr 2>/dev/null) || {
        echo "efibootmgr failed"
        return 1
    }
    first=$(printf '%s\n' "${out}" | sed -n 's/^BootOrder: *//p' |
        cut -d, -f1)
    printf '%s\n' "${out}" | grep -q "^Boot${first}\* AirymaxOS" || {
        echo "BootOrder head=${first}: $(printf '%s\n' "${out}" |
            grep "^Boot${first}")"
        return 1
    }
}

# T12: 免密提权（airymax 交付为空口令，而空口令在 sudo 的 PAM 栈里不是可用
# 的交互凭据；缺了 NOPASSWD，装机后没有任何非交互提权路径，从桌面上却看不出
# 异常。这里直接以交付账户身份试一次，不读配置文件）
t12_passwordless() {
    local f="${SYSROOT}/etc/sudoers.d/90-airymax"
    if [ -n "${SYSROOT}" ]; then
        [ -f "${f}" ] || {
            echo "${f} missing"
            return 1
        }
        grep -qxF 'airymax ALL=(ALL) NOPASSWD: ALL' "${f}" || {
            echo "policy line absent in ${f}"
            return 1
        }
        echo "policy file ok (offline check)"
        return 0
    fi
    need sudo || return $?
    sudo -n true 2>&1 || {
        echo "sudo -n refused: policy not in effect"
        return 1
    }
    echo "sudo -n ok without password"
}

# T13: 免密桌面（空口令账户一旦被空闲锁屏拦住，解锁框就成了口令墙：锁屏挡
# 不住任何人，只把「开机即桌面」变成「每五分钟输一次口令」。策略以 dconf
# 系统库交付，键文件在位但未 dconf update 时不会生效，所以这里必须读实际
# 键值，而不是看文件是否存在）
t13_passwordless_desktop() {
    local f="${SYSROOT}/etc/dconf/db/local.d/00-airymax-screensaver"
    if [ -n "${SYSROOT}" ]; then
        [ -f "${f}" ] || {
            echo "${f} missing"
            return 1
        }
        grep -qxF 'idle-lock-enabled=false' "${f}" || {
            echo "idle-lock-enabled not disabled in ${f}"
            return 1
        }
        grep -qxF 'lock-enabled=false' "${f}" || {
            echo "lock-enabled not disabled in ${f}"
            return 1
        }
        echo "screensaver policy ok (offline check)"
        return 0
    fi
    need dconf || return $?
    expect "$(dconf read /org/ukui/screensaver/lock-enabled 2>&1)" false \
        "lock-enabled" || return 1
    expect "$(dconf read /org/ukui/screensaver/idle-lock-enabled 2>&1)" false \
        "idle-lock-enabled" || return 1
    id -nG airymax 2>/dev/null | tr ' ' '\n' | grep -qxF nopasswdlogin || {
        echo "airymax not in nopasswdlogin"
        return 1
    }
}

printf 'TAP version 14\n'
printf '1..13\n'
printf '# AirymaxOS distro smoke: target=%s date=%s\n' \
    "${TARGET}" "$(date -u '+%FT%TZ')"

probe 1 "T1 ukui x11 session" t1_x11
probe 2 "T2 fcitx input method" t2_ime
probe 3 "T3 pulseaudio stack" t3_audio
probe 4 "T4 desktop slice" t4_slice
probe 5 "T5 built-in wallpaper" t5_wallpaper
probe 6 "T6 kernel identity" t6_kernel_identity
probe 7 "T7 lsm registry" t7_lsm_registry
probe 8 "T8 product hostname" t8_hostname
probe 9 "T9 release brand" t9_brand
probe 10 "T10 display mode policy" t10_display
probe 11 "T11 efi boot brand" t11_efi_brand
probe 12 "T12 passwordless elevation" t12_passwordless
probe 13 "T13 passwordless desktop" t13_passwordless_desktop

printf '# summary: pass=%d fail=%d\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ]
