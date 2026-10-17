#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# install-test.sh — 无人值守安装三连测（TAP 14）
#
# 每个轮次验证两件事：
#   1. 安装：空 qcow2 从 ISO 引导，kickstart 执行完成并触发关机/重启；
#   2. 启动：安装后的磁盘冷启动到登录提示，且无内核 panic。
#
# ISO 契约（190-distribution/03-installer-design.md §7.1）：
#   镜像由 build-iso.sh 经 mkksiso 注入：kickstart 位于 /ks.cfg，引导配置
#   携带 inst.ks=hd:LABEL=<卷标>:/ks.cfg，且安装内核命令行含
#   console=ttyS0,115200；本脚本因此只做黑盒观测，不注入参数。
#
# 退出码：0 全部通过；1 存在失败；77 缺少 QEMU 工具链（跳过）。
# ===========================================================================
set -uo pipefail

readonly SKIP=77
readonly DISTRO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

ISO=""
OUT="${TMPDIR:-/tmp}/airymaxos-install-test"
RUNS=3
INSTALL_TIMEOUT=3600
BOOT_TIMEOUT=300
MARKER="install complete"
BOOT_MARKER="login:"

PASS=0
FAIL=0
SKIPPED=0

usage()
{
    cat <<'EOF'
用法: scripts/install-test.sh --iso PATH [选项]

  --iso PATH           被测安装 ISO（必填）
  --out DIR            产物目录，缺省 $TMPDIR/airymaxos-install-test
  --runs N             连续安装轮次，缺省 3
  --install-timeout S  单轮安装超时秒数，缺省 3600
  --boot-timeout S     单轮启动超时秒数，缺省 300
  --marker TEXT        %post 完成标记，缺省 "install complete"
  --boot-marker TEXT   启动完成标记，缺省 "login:"
  -h, --help           显示本帮助

产物:
  DIR/run-N/disk.qcow2   第 N 轮安装盘
  DIR/run-N/install.log  第 N 轮安装串口日志
  DIR/run-N/boot.log     第 N 轮启动串口日志

OUT 必须位于源码区之外；缺失 qemu-system-x86_64 / qemu-img 时以 77 跳过。
EOF
}

tap_ok()
{
    printf 'ok %s - %s\n' "$1" "$2"
    PASS=$((PASS + 1))
}

tap_skip()
{
    printf 'ok %s - %s # SKIP %s\n' "$1" "$2" "$3"
    SKIPPED=$((SKIPPED + 1))
}

tap_fail()
{
    printf 'not ok %s - %s\n' "$1" "$2"
    [ -n "${3:-}" ] && printf '#   %s\n' "$3"
    FAIL=$((FAIL + 1))
}

die()
{
    printf 'install-test: %s\n' "$*" >&2
    exit 2
}

optarg()
{
    [ "$2" -ge 2 ] || die "$1 缺少参数"
}

parse_args()
{
    while [ $# -gt 0 ]; do
        case "$1" in
        --iso) optarg "$1" "$#"; ISO="$2"; shift 2 ;;
        --out) optarg "$1" "$#"; OUT="$2"; shift 2 ;;
        --runs) optarg "$1" "$#"; RUNS="$2"; shift 2 ;;
        --install-timeout) optarg "$1" "$#"; INSTALL_TIMEOUT="$2"; shift 2 ;;
        --boot-timeout) optarg "$1" "$#"; BOOT_TIMEOUT="$2"; shift 2 ;;
        --marker) optarg "$1" "$#"; MARKER="$2"; shift 2 ;;
        --boot-marker) optarg "$1" "$#"; BOOT_MARKER="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "未知参数: $1" ;;
        esac
    done
    [ -n "${ISO}" ] || die "--iso 必填"
    [ -f "${ISO}" ] || die "ISO 不存在: ${ISO}"
}

check_out()
{
    local root
    root="$(cd "${DISTRO_ROOT}" && pwd -P)"
    OUT="$(realpath -m "${OUT}")"
    case "${OUT}/" in
    "${root}"/*) die "产物目录位于源码区，禁止在源码区构建: ${OUT}" ;;
    esac
    mkdir -p "${OUT}" || die "无法创建产物目录: ${OUT}"
}

need()
{
    command -v "$1" >/dev/null 2>&1
}

tools_ready()
{
    need qemu-system-x86_64 && need qemu-img
}

install_run()
{
    local run="$1" dir="${OUT}/run-$1" disk log rc
    mkdir -p "${dir}" || return 1
    disk="${dir}/disk.qcow2"
    log="${dir}/install.log"
    qemu-img create -f qcow2 "${disk}" 40G >"${dir}/qemu-img.log" 2>&1 ||
        { printf 'qemu-img create failed\n'; return 1; }
    timeout "${INSTALL_TIMEOUT}" qemu-system-x86_64 \
        -m 4096 -smp 2 \
        -drive "file=${disk},if=virtio,format=qcow2" \
        -cdrom "${ISO}" -boot order=d \
        -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
        -no-reboot -display none -monitor none \
        -serial "file:${log}" >/dev/null 2>&1
    rc=$?
    if [ "${rc}" -ne 0 ]; then
        printf 'qemu install run %s exited rc=%s\n' "${run}" "${rc}"
        return 1
    fi
    grep -q "${MARKER}" "${log}" ||
        { printf 'marker missing in install log\n'; return 1; }
}

boot_run()
{
    local run="$1" dir="${OUT}/run-$1" disk log rc
    disk="${dir}/disk.qcow2"
    log="${dir}/boot.log"
    [ -f "${disk}" ] || { printf 'no disk from install\n'; return 1; }
    timeout "${BOOT_TIMEOUT}" qemu-system-x86_64 \
        -m 4096 -smp 2 \
        -drive "file=${disk},if=virtio,format=qcow2" \
        -boot order=c -display none -monitor none \
        -serial "file:${log}" >/dev/null 2>&1
    rc=$?
    if [ "${rc}" -ne 124 ] && [ "${rc}" -ne 0 ]; then
        printf 'qemu boot run %s exited rc=%s\n' "${run}" "${rc}"
        return 1
    fi
    if grep -q 'Kernel panic' "${log}"; then
        printf 'kernel panic on boot\n'
        return 1
    fi
    grep -q "${BOOT_MARKER}" "${log}" ||
        { printf 'marker %s missing in boot log\n' "${BOOT_MARKER}"; return 1; }
}

main()
{
    local run id
    parse_args "$@"
    check_out
    if ! tools_ready; then
        printf 'TAP version 14\n1..0 # SKIP QEMU toolchain unavailable\n'
        exit "${SKIP}"
    fi
    printf 'TAP version 14\n1..%d\n' "$((RUNS * 2))"
    printf '# AirymaxOS install test: iso=%s runs=%s\n' "$(basename "${ISO}")" \
        "${RUNS}"
    for run in $(seq 1 "${RUNS}"); do
        id=$(((run - 1) * 2 + 1))
        if install_run "${run}"; then
            tap_ok "${id}" "install run ${run}"
        else
            tap_fail "${id}" "install run ${run}" "see ${OUT}/run-${run}"
        fi
        id=$((id + 1))
        if [ -f "${OUT}/run-${run}/disk.qcow2" ] && boot_run "${run}"; then
            tap_ok "${id}" "boot run ${run}"
        else
            tap_fail "${id}" "boot run ${run}" "see ${OUT}/run-${run}"
        fi
    done
    printf '# summary: pass=%d fail=%d skip=%d\n' "${PASS}" "${FAIL}" \
        "${SKIPPED}"
    [ "${FAIL}" -eq 0 ]
}

main "$@"
