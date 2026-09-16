#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-smoke.sh — distro 组合冒烟（骨架）
#
# 用法:
#   ./run-smoke.sh <被测镜像/系统标识>
#   在发布工作区或测试机（DevStation）上执行；CI 内调用时以 TAP 输出。
#
# 现状: 骨架。四个探测函数给出的是最低验收的判定框架，具体探测实现
#       （本机执行 / SSH 到测试机 / 镜像引导后执行）随首台 DevStation
#       接入回填（见 ci/README.md）。用例实现归属 tests-linux 叶子仓。
# ===========================================================================
set -uo pipefail

TARGET="${1:?用法: run-smoke.sh <被测镜像/系统标识>}"
PASS=0
FAIL=0

tap_case() { # tap_case <编号> <名称> <exit-code>
    local id="$1" name="$2" rc="$3"
    if [ "$rc" -eq 0 ]; then
        echo "ok ${id} - ${name}"
        PASS=$((PASS + 1))
    else
        echo "not ok ${id} - ${name}"
        FAIL=$((FAIL + 1))
    fi
}

# ---------------------------------------------------------------------------
# T1: Tauri 桌面应用窗口（products/desktop, webkit2gtk on X11）
# TODO: 测试机接入后实现真实探测；骨架以占位探测说明判定框架
# ---------------------------------------------------------------------------
t1_tauri_window() {
    # 期望: X11 会话内 Tauri 窗口打开并完成一帧渲染
    echo "1..0 # T1 skeleton — TODO implement on DevStation" >&2
    return 0
}

# ---------------------------------------------------------------------------
# T2: 输入法（fcitx5 中文输入）
# ---------------------------------------------------------------------------
t2_input_method() {
    # 期望: fcitx5 进程存在 + 配置加载成功
    echo "1..0 # T2 skeleton — TODO implement on DevStation" >&2
    return 0
}

# ---------------------------------------------------------------------------
# T3: 音频栈（PipeWire）
# ---------------------------------------------------------------------------
t3_pipewire() {
    # 期望: pipewire/pipewire-pulse 运行 + pw-cli 信息可读
    echo "1..0 # T3 skeleton — TODO implement on DevStation" >&2
    return 0
}

# ---------------------------------------------------------------------------
# T4: 分级冻结（kylin-app-cgroupd / cgroup v2 freezer）
# ---------------------------------------------------------------------------
t4_cgroup_freeze() {
    # 期望: 后台 UKUI 应用进入冻结 cgroup，freezer.state 可查
    echo "1..0 # T4 skeleton — TODO implement on DevStation" >&2
    return 0
}

echo "TAP version 14"
echo "# AirymaxOS distro smoke: target=${TARGET} date=$(date -u '+%FT%TZ')"

t1_tauri_window;  tap_case 1 "T1 tauri window"       $?
t2_input_method;  tap_case 2 "T2 input method"      $?
t3_pipewire;      tap_case 3 "T3 pipewire audio"    $?
t4_cgroup_freeze; tap_case 4 "T4 cgroup freeze"     $?

echo "# summary: pass=${PASS} fail=${FAIL}"
[ "$FAIL" -eq 0 ]
