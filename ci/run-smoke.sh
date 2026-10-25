#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-smoke.sh — distro 组合冒烟（TAP 14）
#
# 用法:
#   ./run-smoke.sh <被测镜像/系统标识>
#   在已登录的 UKUI X11 桌面会话内执行；探测只读系统状态，不改配置。
#
# 覆盖:
#   T1  UKUI X11 会话：loginctl 会话属性、ukui-session 进程、X server 可达
#   T2  fcitx 4 输入法：守护进程、fcitx-remote 可达、会话输入法变量
#   T3  PulseAudio 音频栈：pactl 与守护进程握手
#   T4  桌面隔离 slice：user@UID.service 归属与 slice 资源参数
#   T5  内置壁纸：背景键指向内置路径，图像 sha256 与发行资产一致
#   T6  内核归属：运行的内核是包内 ALK，/boot 三件套齐全且配置一致
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
    for f in "/boot/vmlinuz-${rel}" "/boot/config-${rel}" \
        "/boot/System.map-${rel}"; do
        [ -s "${f}" ] || {
            echo "${f} missing"
            return 1
        }
    done
    grep -qx 'CONFIG_LOCALVERSION="-alk"' "/boot/config-${rel}" || {
        echo "config-${rel}: LOCALVERSION mismatch"
        return 1
    }
    grep -qx 'CONFIG_SECURITY_AIRY=y' "/boot/config-${rel}" || {
        echo "config-${rel}: CONFIG_SECURITY_AIRY not set"
        return 1
    }
    grep -q ' start_kernel$' "/boot/System.map-${rel}" || {
        echo "System.map-${rel}: start_kernel absent"
        return 1
    }
}

printf 'TAP version 14\n'
printf '1..6\n'
printf '# AirymaxOS distro smoke: target=%s date=%s\n' \
    "${TARGET}" "$(date -u '+%FT%TZ')"

probe 1 "T1 ukui x11 session" t1_x11
probe 2 "T2 fcitx input method" t2_ime
probe 3 "T3 pulseaudio stack" t3_audio
probe 4 "T4 desktop slice" t4_slice
probe 5 "T5 built-in wallpaper" t5_wallpaper
probe 6 "T6 kernel identity" t6_kernel_identity

printf '# summary: pass=%d fail=%d\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ]
