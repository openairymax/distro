#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# install-test.sh — 无人值守安装验收（跨架构、双固件、TAP）
#
# 每条固件腿、每一轮验证两件事：
#   1. 安装：空 qcow2 从 ISO 引导，kickstart 执行完成并触发重启；
#   2. 启动：安装后的磁盘冷启动到登录提示（或验收标记
#      AIRYMAX-SMOKE-PASS），无内核 panic / 单元失败，且宿主机观测到的
#      启动墙钟不超过 --max-boot 秒。
#
# ISO 契约（190-distribution/03-installer-design.md §7.1）：
#   镜像由 build-iso.sh 经 mkksiso 注入：kickstart 位于 /ks.cfg，引导配置
#   携带 inst.ks=hd:LABEL=<卷标>:/ks.cfg，安装内核命令行含串口控制台；
#   本脚本只做黑盒观测，不向镜像注入任何参数。
#
# 退出码：0 全部通过；1 存在失败；5 参数或环境不满足；
#         6 产物目录不可用；77 缺少 QEMU 工具链（跳过）。
# ===========================================================================
set -uo pipefail

readonly SKIP=77
readonly EINVAL=5
readonly DISTRO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly BOOT_FAIL='Kernel panic|Failed to start|Welcome to emergency mode|dracut-initqueue.*timeout|AIRYMAX-DESKTOP-FAIL|AIRYMAX-SMOKE-FAIL'

. "${DISTRO_ROOT}/scripts/lib/outdir.sh"

ISO=""
OUT="${TMPDIR:-/tmp}/airymaxos-install-test"
RUNS=3
ARCH="$(uname -m)"
FIRMWARE="bios"
INSTALL_TIMEOUT=3600
BOOT_TIMEOUT=300
MAX_BOOT=30
MARKER="install complete"
BOOT_MARKER="login:"
FW_DIR=""

QEMU=""
QARGS=()
LEGS=()
ROWS=()
FW_CODE=""
FW_VARS=""
BOOT_S=0

PASS=0
FAIL=0

usage()
{
    cat <<'EOF'
用法: scripts/install-test.sh --iso PATH [选项]

  --iso PATH           被测安装 ISO（必填）
  --out DIR            产物目录，缺省 $TMPDIR/airymaxos-install-test
  --runs N             每种固件的连续安装轮次，缺省 3
  --arch ARCH          x86_64 或 aarch64，缺省宿主架构
  --firmware FW        bios、uefi 或 both，缺省 bios
  --install-timeout S  单轮安装超时秒数，缺省 3600
  --boot-timeout S     单轮启动硬超时秒数，缺省 300
  --max-boot S         启动墙钟上限秒数，缺省 30
  --marker TEXT        %post 完成标记，缺省 "install complete"
  --boot-marker TEXT   启动完成标记，缺省 "login:"
  --fw-dir DIR         优先在该目录探测 OVMF/AAVMF 固件
  -h, --help           显示本帮助

产物:
  DIR/run-FW-N/disk.qcow2      第 N 轮安装盘
  DIR/run-FW-N/vars.fd         UEFI NVRAM（安装与启动共用）
  DIR/run-FW-N/install.log     第 N 轮安装串口日志
  DIR/run-FW-N/boot.log        第 N 轮启动串口日志
  DIR/install-manifest.txt     轮次结果与 ISO 摘要

OUT 必须位于源码区之外；缺失 qemu-system-$ARCH / qemu-img 时以 77 跳过。
aarch64 仅支持 uefi 固件；UEFI 固件按 OVMF/AAVMF 常见路径探测。
EOF
}

tap_ok()
{
    printf 'ok %s - %s\n' "$1" "$2"
    PASS=$((PASS + 1))
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
    exit "${EINVAL}"
}

optarg()
{
    [ "$2" -ge 2 ] || die "$1 缺少参数"
}

need_num()
{
    case "$2" in
    ''|*[!0-9]*) die "$1 必须是非负整数: $2" ;;
    esac
}

parse_args()
{
    while [ $# -gt 0 ]; do
        case "$1" in
        --iso) optarg "$1" "$#"; ISO="$2"; shift 2 ;;
        --out) optarg "$1" "$#"; OUT="$2"; shift 2 ;;
        --runs) optarg "$1" "$#"; need_num "$1" "$2"; RUNS="$2"; shift 2 ;;
        --arch) optarg "$1" "$#"; ARCH="$2"; shift 2 ;;
        --firmware) optarg "$1" "$#"; FIRMWARE="$2"; shift 2 ;;
        --install-timeout)
            optarg "$1" "$#"; need_num "$1" "$2"; INSTALL_TIMEOUT="$2"; shift 2 ;;
        --boot-timeout)
            optarg "$1" "$#"; need_num "$1" "$2"; BOOT_TIMEOUT="$2"; shift 2 ;;
        --max-boot)
            optarg "$1" "$#"; need_num "$1" "$2"; MAX_BOOT="$2"; shift 2 ;;
        --marker) optarg "$1" "$#"; MARKER="$2"; shift 2 ;;
        --boot-marker) optarg "$1" "$#"; BOOT_MARKER="$2"; shift 2 ;;
        --fw-dir) optarg "$1" "$#"; FW_DIR="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "未知参数: $1" ;;
        esac
    done
    [ -n "${ISO}" ] || die "--iso 必填"
    [ -f "${ISO}" ] || die "ISO 不存在: ${ISO}"
    [ "${RUNS}" -ge 1 ] || die "--runs 必须大于 0"
}

fw_probe()
{
    local -a cand
    local c name
    if [ -n "${FW_DIR}" ]; then
        cand=("${FW_DIR}"/OVMF_CODE*.fd "${FW_DIR}"/AAVMF_CODE*.fd
              "${FW_DIR}"/QEMU_EFI*.fd)
    else
        case "${ARCH}" in
        x86_64)
            cand=(/usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd
                  /usr/share/edk2/ovmf/OVMF_CODE.fd /usr/share/qemu/OVMF.fd)
            ;;
        aarch64)
            cand=(/usr/share/AAVMF/AAVMF_CODE.fd /usr/share/edk2/aarch64/QEMU_EFI.fd
                  /usr/share/qemu-efi-aarch64/QEMU_EFI.fd)
            ;;
        esac
    fi
    for c in "${cand[@]}"; do
        [ -r "${c}" ] || continue
        FW_CODE="$c"
        FW_VARS=""
        name="$(basename "${c}")"
        case "${name}" in
        *CODE*)
            FW_VARS="${c%/*}/$(printf '%s' "${name}" | sed 's/CODE/VARS/')"
            [ -r "${FW_VARS}" ] || FW_VARS=""
            ;;
        esac
        return 0
    done
    return 1
}

check_env()
{
    case "${ARCH}" in
    x86_64|aarch64) ;;
    *) die "不支持的架构: ${ARCH}" ;;
    esac
    case "${FIRMWARE}" in
    bios|uefi|both) ;;
    *) die "不支持的固件: ${FIRMWARE}" ;;
    esac
    if [ "${ARCH}" = aarch64 ] && [ "${FIRMWARE}" != uefi ]; then
        die "aarch64 仅支持 uefi 固件"
    fi
    if [ "${FIRMWARE}" != bios ] && ! fw_probe; then
        die "未找到 UEFI 固件（OVMF/AAVMF）"
    fi
}

need()
{
    command -v "$1" >/dev/null 2>&1
}

tools_ready()
{
    need "${QEMU}" && need qemu-img && need timeout
}

qemu_base()
{
    QARGS=(-m 4096 -smp 2 -display none -monitor none -no-reboot)
    if [ "${ARCH}" = aarch64 ]; then
        QARGS+=(-machine virt -cpu max)
    fi
    if [ -r /dev/kvm ] && [ "$(uname -m)" = "${ARCH}" ]; then
        QARGS+=(-accel kvm)
    fi
}

dev_disk()
{
    if [ "${ARCH}" = aarch64 ]; then
        QARGS+=(-drive "file=$1,if=none,id=hd0,format=qcow2"
                -device scsi-hd,drive=hd0)
    else
        QARGS+=(-drive "file=$1,if=virtio,format=qcow2")
    fi
}

dev_cdrom()
{
    if [ "${ARCH}" = aarch64 ]; then
        QARGS+=(-device virtio-scsi-pci,id=scsi0
                -drive "file=$1,if=none,id=cd0,media=cdrom,readonly=on"
                -device scsi-cd,drive=cd0)
    else
        QARGS+=(-cdrom "$1")
    fi
}

fw_args()
{
    local fw="$1" vars="$2/vars.fd"
    [ "${fw}" = uefi ] || return 0
    if [ -z "${FW_VARS}" ]; then
        QARGS+=(-bios "${FW_CODE}")
        return 0
    fi
    [ -f "${vars}" ] || cp "${FW_VARS}" "${vars}" || return 1
    QARGS+=(-drive "if=pflash,format=raw,readonly=on,file=${FW_CODE}"
            -drive "if=pflash,format=raw,file=${vars}")
}

install_run()
{
    local fw="$1" n="$2" dir="${OUT}/run-$1-$2" disk log rc
    mkdir -p "${dir}" || return 1
    disk="${dir}/disk.qcow2"
    log="${dir}/install.log"
    qemu-img create -f qcow2 "${disk}" 40G >"${dir}/qemu-img.log" 2>&1 ||
        { printf 'qemu-img create failed: run-%s-%s\n' "${fw}" "${n}" >&2; return 1; }
    qemu_base
    fw_args "${fw}" "${dir}" || return 1
    dev_disk "${disk}"
    dev_cdrom "${ISO}"
    QARGS+=(-boot order=d -netdev user,id=n0 -device virtio-net-pci,netdev=n0
            -serial "file:${log}")
    timeout "${INSTALL_TIMEOUT}" "${QEMU}" "${QARGS[@]}" >/dev/null 2>&1
    rc=$?
    if [ "${rc}" -ne 0 ]; then
        printf 'install run %s-%s exited rc=%s\n' "${fw}" "${n}" "${rc}" >&2
        return 1
    fi
    grep -q "${MARKER}" "${log}" 2>/dev/null ||
        { printf 'marker missing in run-%s-%s/install.log\n' "${fw}" "${n}" >&2; return 1; }
}

wait_marker()
{
    local log="$1" pid="$2" deadline="$3"
    while [ "$(date +%s)" -lt "${deadline}" ]; do
        grep -q "${BOOT_MARKER}" "${log}" 2>/dev/null && return 0
        grep -qE "${BOOT_FAIL}" "${log}" 2>/dev/null && return 2
        kill -0 "${pid}" 2>/dev/null || return 3
        sleep 1
    done
    return 1
}

stop_qemu()
{
    kill "$1" 2>/dev/null || true
    wait "$1" 2>/dev/null || true
}

boot_run()
{
    local fw="$1" n="$2" dir="${OUT}/run-$1-$2"
    local disk="${dir}/disk.qcow2" log="${dir}/boot.log"
    local pid start now code
    [ -f "${disk}" ] || { printf 'no disk for run-%s-%s\n' "${fw}" "${n}" >&2; return 1; }
    qemu_base
    fw_args "${fw}" "${dir}" || return 1
    dev_disk "${disk}"
    QARGS+=(-boot order=c -serial "file:${log}")
    start=$(date +%s)
    "${QEMU}" "${QARGS[@]}" >/dev/null 2>&1 &
    pid=$!
    wait_marker "${log}" "${pid}" "$((start + BOOT_TIMEOUT))"
    code=$?
    stop_qemu "${pid}"
    now=$(date +%s)
    BOOT_S=$((now - start))
    case "${code}" in
    0) ;;
    2) printf 'boot failure pattern in run-%s-%s/boot.log\n' "${fw}" "${n}" >&2; return 1 ;;
    *) printf 'boot incomplete in run-%s-%s/boot.log\n' "${fw}" "${n}" >&2; return 1 ;;
    esac
    if [ "${BOOT_S}" -gt "${MAX_BOOT}" ]; then
        printf 'boot run %s-%s took %ss > %ss\n' "${fw}" "${n}" \
            "${BOOT_S}" "${MAX_BOOT}" >&2
        return 1
    fi
}

legs_build()
{
    case "${FIRMWARE}" in
    both) LEGS=(bios uefi) ;;
    *) LEGS=("${FIRMWARE}") ;;
    esac
}

iso_sum()
{
    local sum rest
    read -r sum rest <<<"$(sha256sum "${ISO}")"
    printf '%s' "${sum}"
}

manifest()
{
    local row
    {
        printf '# AirymaxOS install test manifest\n'
        printf 'iso %s %s\n' "$(iso_sum)" "$(basename "${ISO}")"
        printf 'arch=%s\nfirmware=%s\nruns=%s\nmax_boot=%s\n' \
            "${ARCH}" "${FIRMWARE}" "${RUNS}" "${MAX_BOOT}"
        for row in "${ROWS[@]}"; do
            printf 'run %s\n' "${row}"
        done
        if [ "${FAIL}" -eq 0 ]; then
            printf 'result=pass\n'
        else
            printf 'result=fail\n'
        fi
    } >"${OUT}/install-manifest.txt"
}

run_leg()
{
    local fw="$1" n id
    for n in $(seq 1 "${RUNS}"); do
        id=$((TOTAL + 1))
        if install_run "${fw}" "${n}"; then
            tap_ok "${id}" "install ${fw} run ${n}"
            ROWS+=("${fw} run=${n} install=pass")
        else
            tap_fail "${id}" "install ${fw} run ${n}" "see ${OUT}/run-${fw}-${n}"
            ROWS+=("${fw} run=${n} install=fail")
        fi
        TOTAL=$((TOTAL + 1))
        id=$((TOTAL + 1))
        if boot_run "${fw}" "${n}"; then
            tap_ok "${id}" "boot ${fw} run ${n} ${BOOT_S}s"
            ROWS+=("${fw} run=${n} boot=pass boot_s=${BOOT_S}")
        else
            tap_fail "${id}" "boot ${fw} run ${n}" "see ${OUT}/run-${fw}-${n}"
            ROWS+=("${fw} run=${n} boot=fail")
        fi
        TOTAL=$((TOTAL + 1))
    done
}

TOTAL=0

main()
{
    local fw
    parse_args "$@"
    check_env
    OUT="$(out_guard install-test "${OUT}")" || exit $?
    QEMU="qemu-system-${ARCH}"
    if ! tools_ready; then
        printf 'TAP version 14\n1..0 # SKIP QEMU toolchain unavailable\n'
        exit "${SKIP}"
    fi
    legs_build
    printf 'TAP version 14\n1..%d\n' "$((RUNS * 2 * ${#LEGS[@]}))"
    printf '# AirymaxOS install test: iso=%s arch=%s firmware=%s runs=%s\n' \
        "$(basename "${ISO}")" "${ARCH}" "${FIRMWARE}" "${RUNS}"
    for fw in "${LEGS[@]}"; do
        run_leg "${fw}"
    done
    manifest
    printf '# summary: pass=%d fail=%d\n' "${PASS}" "${FAIL}"
    [ "${FAIL}" -eq 0 ]
}

main "$@"
