#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-smoke.sh — distro 组合冒烟（TAP）
#
# 用法:
#   ./run-smoke.sh <被测镜像/系统标识>
#   在已引导的 AirymaxOS 镜像或 DevStation 测试机上执行；CI 内以 TAP 输出。
#
# 判定语义:
#   0  — 通过
#   1  — 失败（探测能力具备，但被测特性未满足）
#   77 — 跳过（测试机缺少探测工具，不代表特性通过）
# 退出码仅在存在失败用例时为 1；跳过不掩盖失败。
# ===========================================================================
set -uo pipefail

TARGET="${1:?usage: run-smoke.sh <target-id>}"
SKIP=77

PASS=0
FAIL=0
SKIPPED=0

tap_ok() {
    printf 'ok %s - %s\n' "$1" "$2"
    PASS=$((PASS + 1))
}

tap_skip() {
    printf 'ok %s - %s # SKIP %s\n' "$1" "$2" "$3"
    SKIPPED=$((SKIPPED + 1))
}

tap_fail() {
    printf 'not ok %s - %s\n' "$1" "$2"
    [ -n "${3:-}" ] && printf '#   %s\n' "$3"
    FAIL=$((FAIL + 1))
}

probe() { # probe <编号> <名称> <探测函数>
    local id="$1" name="$2" out rc
    shift 2
    out="$("$@" 2>&1)"
    rc=$?
    case "${rc}" in
    0) tap_ok "${id}" "${name}" ;;
    "${SKIP}") tap_skip "${id}" "${name}" "${out:-unsupported}" ;;
    *) tap_fail "${id}" "${name}" "${out:-probe rc=${rc}}" ;;
    esac
}

need() { # need <命令> — 探测工具缺失时跳过当前用例
    command -v "$1" >/dev/null 2>&1 && return 0
    printf '%s not installed\n' "$1"
    return "${SKIP}"
}

# T1: Tauri 桌面应用窗口（webkit2gtk on X11）
t1_tauri() {
    need xdpyinfo || return $?
    need pgrep || return $?
    [ -n "${DISPLAY:-}" ] || { echo "DISPLAY unset"; return "${SKIP}"; }
    xdpyinfo >/dev/null 2>&1 || {
        echo "X11 unreachable: ${DISPLAY}"
        return 1
    }
    pgrep -f WebKitWebProcess >/dev/null || {
        echo "no WebKitWebProcess (Tauri webview absent)"
        return 1
    }
}

# T2: 输入法（fcitx5 中文输入）
t2_ime() {
    need pgrep || return $?
    need fcitx5-remote || return $?
    pgrep -x fcitx5 >/dev/null || {
        echo "fcitx5 not running"
        return 1
    }
    fcitx5-remote >/dev/null 2>&1
    case $? in
    0 | 1 | 2) : ;;
    *)
        echo "fcitx5-remote cannot reach daemon"
        return 1
        ;;
    esac
}

# T3: 音频栈（PipeWire）
t3_audio() {
    need pw-cli || return $?
    need pgrep || return $?
    pw-cli info 0 >/dev/null 2>&1 || {
        echo "PipeWire core unreachable"
        return 1
    }
    pgrep -x pipewire-pulse >/dev/null || {
        echo "pipewire-pulse not running"
        return 1
    }
}

# T4: 分级冻结（kylin-app-cgroupd / cgroup v2 freezer）
t4_freeze() {
    need pgrep || return $?
    [ -e /sys/fs/cgroup/cgroup.freeze ] || {
        echo "cgroup v2 freezer unavailable"
        return 1
    }
    pgrep -f kylin-app-cgroupd >/dev/null || {
        echo "kylin-app-cgroupd not running"
        return 1
    }
}

printf 'TAP version 14\n'
printf '1..4\n'
printf '# AirymaxOS distro smoke: target=%s date=%s\n' \
    "${TARGET}" "$(date -u '+%FT%TZ')"

probe 1 "T1 tauri window" t1_tauri
probe 2 "T2 input method" t2_ime
probe 3 "T3 pipewire audio" t3_audio
probe 4 "T4 cgroup freeze" t4_freeze

printf '# summary: pass=%d fail=%d skip=%d\n' "${PASS}" "${FAIL}" "${SKIPPED}"
[ "${FAIL}" -eq 0 ]
