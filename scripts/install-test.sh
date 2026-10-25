#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# install-test.sh — 无人值守安装验收（跨架构、双固件、TAP）
#
# 每条固件腿、每一轮验证两件事：
#   1. 安装：空 qcow2 从 ISO 引导，kickstart 执行完成并触发重启；
#   2. 启动：安装后的磁盘冷启动到登录提示（或验收标记
#      AIRYMAX-SMOKE-PASS），无内核 panic，且会话内探针报告 systemd
#      记账里没有失败单元。
#
# 安装腿失败时该轮启动腿直接判负并跳过，不在无引导盘上空转；两条腿
# 每 30 秒回显一次串口尾行，便于失败现场在 CI 日志中直接可读。
#
# --max-boot 只约束 login: 腿：NFR-P-005 的 30s 口径是 systemd 到登录
# 提示的冷启动。桌面腿与验收腿的标记由会话内冒烟上报产生，墙钟包含
# 图形栈与会话初始化，不能用 30s 判定；未显式指定该选项时这两条腿
# 取消墙钟上限，启动完成与否由 --boot-timeout 兜底。
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
# 启动腿的判负只认两类证据：引导层失败（panic、emergency、dracut 超时），
# 以及会话内探针给出的结论标记（AIRYMAX-BOOT-DEGRADED / DESKTOP-FAIL /
# SMOKE-FAIL）。「Failed to start」这类通用文本不进判定集：它出现在启动
# 前几秒，按它提前结束会让启动腿在桌面尚未拉起时就收尾，既掩盖「UKUI 能否
# 进入」的证据，也把单元失败与桌面失败混成同一个结论。单元失败以探针读到
# 的 systemd 记账为准，宿主机只做归因，不立第二个事实源。
. "${DISTRO_ROOT}/scripts/lib/verdict.env"
readonly BOOT_FAIL
readonly INST_FAIL
# rpm 事务级错误（scriptlet 非零退出、依赖解析失败）会让 anaconda 停在
# “按 ENTER 退出:” 等待输入而不退出进程，必须与安装失败标记同等判负。
readonly RPM_FAIL
# 取包失败（仓库不可达、单一镜像重试耗尽）在 anaconda 里是致命错误，随后
# 停在「按 ENTER 退出:」等待输入；无头安装没有 stdin，进程既不自退也不打
# 失败标记，只能空耗 --install-timeout。取包致命提示本身即失败证据。
readonly PAY_FAIL
# anaconda 在配置阶段遇到无法自处理的错误时转为交互问句（引导装载程序写
# 配置失败即属此类），无头安装没有 stdin，进程不会退出也不会打印失败标记，
# 只能等到 --install-timeout。问句本身即失败证据，命中就判负。
readonly ASK_FAIL
readonly INST_ERR="${INST_FAIL}|${RPM_FAIL}|${PAY_FAIL}|${ASK_FAIL}"

. "${DISTRO_ROOT}/scripts/lib/outdir.sh"

ISO=""
OUT="${TMPDIR:-/tmp}/airymaxos-install-test"
RUNS=3
ARCH="$(uname -m)"
FIRMWARE="bios"
INSTALL_TIMEOUT=3600
BOOT_TIMEOUT=300
MAX_BOOT=30
MAX_BOOT_SET=0
PROGRESS_EVERY=30
PROG_AT=0
MARKER="install complete"
BOOT_MARKER="login:"
FW_DIR=""
ACCEL="tcg"

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
  --max-boot S         启动墙钟上限秒数，缺省 30；仅 login: 腿生效，
                       桌面/验收标记腿缺省不设上限
  --marker TEXT        %post 完成标记，缺省 "install complete"
  --boot-marker TEXT   启动完成标记，缺省 "login:"
  --fw-dir DIR         优先在该目录探测 OVMF/AAVMF 固件
  -h, --help           显示本帮助

产物:
  DIR/run-FW-N/disk.qcow2      第 N 轮安装盘
  DIR/run-FW-N/vars.fd         UEFI NVRAM（安装与启动共用）
  DIR/run-FW-N/install.log     第 N 轮安装串口日志
  DIR/run-FW-N/boot.log        第 N 轮启动串口日志
  DIR/run-FW-N/qemu.log        安装阶段 QEMU 自身 stderr
  DIR/run-FW-N/qemu-boot.log   启动阶段 QEMU 自身 stderr
  DIR/install-manifest.txt     轮次结果与 ISO 摘要

每轮开始前会删除本轮 install.log/boot.log，判读只看本轮内容。

OUT 必须位于源码区之外；缺失 qemu-system-$ARCH / qemu-img 时以 77 跳过。
aarch64 仅支持 uefi 固件；UEFI 固件按 OVMF/AAVMF 常见路径探测。
x86_64 装机盘按腿区分：uefi 腿为 NVMe（与目标机交付形态一致），
bios 腿为 SATA（QEMU 的 NVMe 没有 SeaBIOS 可用的选件 ROM，BIOS 看不到）。
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
            optarg "$1" "$#"; need_num "$1" "$2"
            MAX_BOOT="$2"; MAX_BOOT_SET=1; shift 2 ;;
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
    if [ "${MAX_BOOT_SET}" -eq 0 ] && [ "${BOOT_MARKER}" != "login:" ]; then
        MAX_BOOT=""
    fi
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
        # --firmware both 是「能测就测两条腿」的意图声明，宿主机没有
        # OVMF/AAVMF 时 UEFI 腿本就无从执行。此时按 bios 腿继续，而不是
        # 让整轮装机段以参数错误退出：否则一台未装 edk2 的构建机连 BIOS
        # 腿的证据也拿不到，缺陷被环境问题掩盖。
        if [ "${FIRMWARE}" = both ]; then
            printf 'install-test: 未找到 UEFI 固件，UEFI 腿降级为跳过，仅跑 BIOS 腿\n' >&2
            FIRMWARE=bios
        else
            die "未找到 UEFI 固件（OVMF/AAVMF）"
        fi
    fi
}

need()
{
    command -v "$1" >/dev/null 2>&1
}

tools_ready()
{
    need "${QEMU}" && need qemu-img
}

accel_set()
{
    if [ -r /dev/kvm ] && [ "$(uname -m)" = "${ARCH}" ]; then
        ACCEL="kvm"
    else
        ACCEL="tcg"
    fi
}

qemu_base()
{
    QARGS=(-m 4096 -smp 2 -display none -monitor none -no-reboot)
    # UKUI 会话经 lightdm 拉起后需要可用的 DRM/KMS 设备做 X 后端。
    # 内核基线只启用 DRM_VIRTIO_GPU（x86_64_defconfig），缺省 std VGA
    # 对应的 bochs 驱动未编译，故两种架构都接 virtio-gpu：x86_64 用
    # -vga virtio 替换缺省 VGA，aarch64 的 virt 机型没有缺省 VGA，直接
    # 追加 PCI 设备。
    if [ "${ARCH}" = aarch64 ]; then
        QARGS+=(-machine virt -device virtio-gpu-pci)
    else
        QARGS+=(-vga virtio)
    fi
    # openEuler 24.03 用户态以 x86-64-v2 为基线，glibc 在 PID1 缺少
    # SSE4.2 时直接 exit_group(127)，内核随即 panic。QEMU 缺省机型的
    # qemu64 不含该基线，故必须显式指定 CPU：KVM 下透传宿主特性，
    # 纯软件模拟下取 TCG 支持的最大特性集。
    if [ "${ACCEL}" = kvm ]; then
        QARGS+=(-accel kvm -cpu host)
    else
        QARGS+=(-cpu max)
    fi
}

disk_kind()
{
    if [ "${ARCH}" = aarch64 ]; then
        printf 'scsi'
    elif [ "$1" = uefi ]; then
        printf 'nvme'
    else
        printf 'sata'
    fi
}

dev_disk()
{
    local file="$1" fw="$2"
    if [ "${ARCH}" = aarch64 ]; then
        QARGS+=(-drive "file=${file},if=none,id=hd0,format=qcow2"
                -device scsi-hd,drive=hd0)
    elif [ "$(disk_kind "${fw}")" = nvme ]; then
        # 装机盘按交付形态取 NVMe。目标机（如 B50）只有 NVMe，virtio-blk
        # 只存在于虚拟化环境：过去用 virtio 自检，内核漏编 NVMe 时门禁
        # 依然全绿，直到真机装完才发现根分区挂不上。
        QARGS+=(-drive "file=${file},if=none,id=hd0,format=qcow2"
                -device nvme,drive=hd0,serial=airy003)
    else
        # BIOS 腿改挂 SATA：QEMU 的 nvme 控制器没有 SeaBIOS 可用的选件
        # ROM，BIOS 固件看不到这块盘（qemu-project/qemu#665），装机成功
        # 后冷启动连引导器都进不去，串口一个字都不出。真机 BIOS 的 NVMe
        # 访问由主板固件自带驱动提供，不依赖 QEMU 这条通路，所以 NVMe
        # 覆盖交给与交付形态一致的 UEFI 腿，BIOS 腿只验证传统引导链。
        QARGS+=(-drive "file=${file},if=ide,format=qcow2")
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

log_tail()
{
    tail -c 600 "$1" 2>/dev/null | tr '\r' '\n' |
        sed 's/\x1b\[[0-9;]*[A-Za-z]//g' |
        grep -av '^[[:space:]]*$' | tail -n 1
}

progress()
{
    local log="$1" elapsed="$2"
    [ "${elapsed}" -ge "${PROG_AT}" ] || return 0
    printf '# %s +%ss: %.110s\n' "$(basename "$(dirname "${log}")")" \
        "${elapsed}" "$(log_tail "${log}")"
    PROG_AT=$((elapsed + PROGRESS_EVERY))
}

fail_hit()
{
    grep -oE "${INST_ERR}" "$1" 2>/dev/null | head -n 1
}

wait_inst()
{
    local log="$1" pid="$2" deadline="$3" start="$4" now
    while :; do
        grep -qE "${INST_ERR}" "${log}" 2>/dev/null && return 2
        if ! kill -0 "${pid}" 2>/dev/null; then
            wait "${pid}" 2>/dev/null
            return $?
        fi
        now=$(date +%s)
        [ "${now}" -lt "${deadline}" ] || return 3
        progress "${log}" "$((now - start))"
        sleep 1
    done
}

install_run()
{
    local fw="$1" n="$2" dir="${OUT}/run-$1-$2" disk log rc start pid
    mkdir -p "${dir}" || return 1
    disk="${dir}/disk.qcow2"
    log="${dir}/install.log"
    # 判读只看日志内容、不看时间戳，因此上一轮的串口日志必须先删掉。
    # wait_inst() 首轮就会 grep INST_ERR，残留日志能让空跑直接判失败；
    # 末尾的 MARKER 断言同样会被残留日志满足，从而假通过。
    rm -f "${log}" "${dir}/qemu.log" || return 1
    qemu-img create -f qcow2 "${disk}" 40G >"${dir}/qemu-img.log" 2>&1 ||
        { printf 'qemu-img create failed: run-%s-%s\n' "${fw}" "${n}" >&2; return 1; }
    qemu_base
    fw_args "${fw}" "${dir}" || return 1
    dev_disk "${disk}" "${fw}"
    dev_cdrom "${ISO}"
    QARGS+=(-boot order=d -netdev user,id=n0 -device virtio-net-pci,netdev=n0
            -serial "file:${log}")
    start=$(date +%s)
    PROG_AT=${PROGRESS_EVERY}
    "${QEMU}" "${QARGS[@]}" >/dev/null 2>"${dir}/qemu.log" &
    pid=$!
    wait_inst "${log}" "${pid}" "$((start + INSTALL_TIMEOUT))" "${start}"
    rc=$?
    stop_qemu "${pid}"
    if [ "${rc}" -ne 0 ]; then
        case "${rc}" in
        2) printf 'install failure pattern in run-%s-%s/install.log: %.110s\n' \
               "${fw}" "${n}" "$(fail_hit "${log}")" >&2 ;;
        3) printf 'install timeout in run-%s-%s after %ss\n' \
               "${fw}" "${n}" "$(($(date +%s) - start))" >&2 ;;
        *) printf 'install run %s-%s exited rc=%s\n' "${fw}" "${n}" "${rc}" >&2 ;;
        esac
        printf '#   serial tail: %.200s\n' "$(log_tail "${log}")" >&2
        # QEMU 自己起不来（缺 KVM、镜像被占）时串口日志根本不存在，
        # 上面的 tail 是空的；把 QEMU 的 stderr 打出来才定位得到。
        [ -f "${log}" ] ||
            printf '#   qemu: %.300s\n' \
                "$(tr '\n' ' ' <"${dir}/qemu.log" 2>/dev/null)" >&2
        return 1
    fi
    grep -q "${MARKER}" "${log}" 2>/dev/null ||
        { printf 'marker missing in run-%s-%s/install.log\n' "${fw}" "${n}" >&2
          printf '#   serial tail: %.200s\n' "$(log_tail "${log}")" >&2
          return 1; }
}

probe_log()
{
    grep -q "${BOOT_MARKER}" "$1" 2>/dev/null && return 0
    grep -qE "${BOOT_FAIL}" "$1" 2>/dev/null && return 2
    return 1
}

# 归因用，不参与判定：systemd 在失败单元之后会打印
# 「See 'systemctl status <unit>' for details.」，这里的 unit 才是关键字，
# 上一行的 daemon 描述文本不是。清单写进 CI 日志，便于直接定位到单元。
note_units()
{
    local units

    units=$(grep -oE "systemctl status [^']+" "$1" 2>/dev/null |
                awk '{ print $3 }' | sort -u | head -n 8)
    [ -n "${units}" ] || return 0
    printf '#   boot unit failures: %s\n' "${units//$'\n'/,}" >&2
}

wait_marker()
{
    local log="$1" pid="$2" deadline="$3" start="$4" rc now
    while :; do
        probe_log "${log}"
        rc=$?
        [ "${rc}" -eq 0 ] && return 0
        [ "${rc}" -eq 2 ] && return 2
        if ! kill -0 "${pid}" 2>/dev/null; then
            # 进程可能刚写完标记就被回收，退出后必须再判一次，
            # 否则短生命周期生产者会被误报为启动未完成。
            probe_log "${log}"
            return $?
        fi
        now=$(date +%s)
        [ "${now}" -lt "${deadline}" ] || return 1
        progress "${log}" "$((now - start))"
        sleep 1
    done
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
    # 同 install_run：boot.log 若不轮转，wait_marker 首轮就能被上一轮的
    # 标记满足，空跑会被判为启动成功。
    rm -f "${log}" "${dir}/qemu-boot.log" || return 1
    qemu_base
    fw_args "${fw}" "${dir}" || return 1
    dev_disk "${disk}" "${fw}"
    QARGS+=(-boot order=c -serial "file:${log}")
    start=$(date +%s)
    PROG_AT=${PROGRESS_EVERY}
    "${QEMU}" "${QARGS[@]}" >/dev/null 2>"${dir}/qemu-boot.log" &
    pid=$!
    wait_marker "${log}" "${pid}" "$((start + BOOT_TIMEOUT))" "${start}"
    code=$?
    stop_qemu "${pid}"
    note_units "${log}"
    now=$(date +%s)
    BOOT_S=$((now - start))
    case "${code}" in
    0) ;;
    2) printf 'boot failure pattern in run-%s-%s/boot.log\n' "${fw}" "${n}" >&2
       printf '#   serial tail: %.200s\n' "$(log_tail "${log}")" >&2
       return 1 ;;
    *) printf 'boot incomplete in run-%s-%s/boot.log after %ss\n' \
           "${fw}" "${n}" "${BOOT_S}" >&2
       printf '#   serial tail: %.200s\n' "$(log_tail "${log}")" >&2
       [ -f "${log}" ] ||
           printf '#   qemu: %.300s\n' \
               "$(tr '\n' ' ' <"${dir}/qemu-boot.log" 2>/dev/null)" >&2
       return 1 ;;
    esac
    if [ -n "${MAX_BOOT}" ] && [ "${BOOT_S}" -gt "${MAX_BOOT}" ]; then
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

disk_map()
{
    local f out=""
    for f in "${LEGS[@]}"; do
        out="${out}${out:+,}${f}:$(disk_kind "${f}")"
    done
    printf '%s' "${out}"
}

manifest()
{
    local row
    {
        printf '# AirymaxOS install test manifest\n'
        printf 'iso %s %s\n' "$(iso_sum)" "$(basename "${ISO}")"
        printf 'arch=%s\nfirmware=%s\nruns=%s\nmax_boot=%s\n' \
            "${ARCH}" "${FIRMWARE}" "${RUNS}" "${MAX_BOOT:-auto}"
        printf 'disk=%s\n' "$(disk_map)"
        printf 'accel=%s\ninstall_timeout=%s\nboot_timeout=%s\n' \
            "${ACCEL}" "${INSTALL_TIMEOUT}" "${BOOT_TIMEOUT}"
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

leg_boot()
{
    local fw="$1" n="$2" id="$3" skip="$4"
    if [ "${skip}" -ne 0 ]; then
        tap_fail "${id}" "boot ${fw} run ${n}" "skipped: install failed"
        ROWS+=("${fw} run=${n} boot=skip")
    elif boot_run "${fw}" "${n}"; then
        tap_ok "${id}" "boot ${fw} run ${n} ${BOOT_S}s"
        ROWS+=("${fw} run=${n} boot=pass boot_s=${BOOT_S}")
    else
        tap_fail "${id}" "boot ${fw} run ${n}" "see ${OUT}/run-${fw}-${n}"
        ROWS+=("${fw} run=${n} boot=fail")
    fi
}

leg_run()
{
    local fw="$1" n="$2" id skip=0
    id=$((TOTAL + 1))
    if install_run "${fw}" "${n}"; then
        tap_ok "${id}" "install ${fw} run ${n}"
        ROWS+=("${fw} run=${n} install=pass")
    else
        skip=1
        tap_fail "${id}" "install ${fw} run ${n}" "see ${OUT}/run-${fw}-${n}"
        ROWS+=("${fw} run=${n} install=fail")
    fi
    TOTAL=$((TOTAL + 1))
    leg_boot "${fw}" "${n}" "$((TOTAL + 1))" "${skip}"
    TOTAL=$((TOTAL + 1))
}

run_leg()
{
    local fw="$1" n
    for n in $(seq 1 "${RUNS}"); do
        leg_run "${fw}" "${n}"
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
    accel_set
    legs_build
    printf 'TAP version 14\n1..%d\n' "$((RUNS * 2 * ${#LEGS[@]}))"
    printf '# AirymaxOS install test: iso=%s arch=%s firmware=%s runs=%s accel=%s\n' \
        "$(basename "${ISO}")" "${ARCH}" "${FIRMWARE}" "${RUNS}" "${ACCEL}"
    for fw in "${LEGS[@]}"; do
        run_leg "${fw}"
    done
    manifest
    printf '# summary: pass=%d fail=%d\n' "${PASS}" "${FAIL}"
    [ "${FAIL}" -eq 0 ]
}

main "$@"
