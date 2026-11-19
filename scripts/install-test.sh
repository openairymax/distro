#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# install-test.sh — 无人值守安装验收（跨架构、双固件、TAP）
#
# 每条固件腿、每一轮验证两件事：
#   1. 安装：空 qcow2 从 ISO 引导，kickstart 执行完成并触发重启；
#   2. 启动：安装后的磁盘冷启动到登录提示（或验收标记
#      AIRYMAX-SMOKE-PASS），无内核 panic，且会话内探针报告 systemd
#      记账里没有失败单元。
#
# 安装腿失败时该轮启动腿直接判负并跳过，不在无引导盘上空转；两条腿每
# 30 秒回显一次串口尾行，便于失败现场在 CI 日志中直接可读。失败归因统一
# 走 fail_note：串口 0 字节时明确报「该固件腿没有向 ttyS0 写任何东西」，
# 并附 QEMU 自身 stderr，避免空日志现场无从定位。
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
# 介质形态（--media）：
#   cdrom 让 QEMU 以 CD-ROM 挂载，固件走 El Torito 引导目录，不读分区表；
#   usb 把同一份 ISO 以裸盘形态挂在 XHCI 后面，固件必须先解析 MBR/GPT
#   找到 ESP。两者覆盖的引导通路不同：isohybrid 三元（El Torito、MBR 0xEF
#   分区项、GPT 条目）只有 usb 形态能证伪，这也是真机 U 盘装机的实际路径。
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
# rpm 事务级错误（依赖解析失败、文件冲突、scriptlet 失败）会让 anaconda
# 停在「按 ENTER 退出:」等待输入而不退出进程，必须与安装失败标记同等判负。
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
# 固件层失败：SeaBIOS 找不到可引导介质时只往 VGA 与调试口写这一行，串口
# 一个字都不会有。没有这份证据时，该腿要空转到装机超时才判负（run
# 41121955316 的 run-bios-1 空转 3600 秒），且现场只剩「串口静默」。
readonly FW_FAIL='Boot failed|No bootable device|could not read the boot disk'

. "${DISTRO_ROOT}/scripts/lib/outdir.sh"
# 剖面归一化只有一份实现（ci/lib/profile.sh）。段完整性断言要按剖面给出
# 期望集，而剖面判断若在本脚本再抄一遍 case，就会重演「三处各写一份、其中
# 两份把 true 归一成 0」的旧故障。
. "${DISTRO_ROOT}/../ci/lib/profile.sh"

ISO=""
OUT="${TMPDIR:-/tmp}/airymaxos-install-test"
RUNS=3
ARCH="$(uname -m)"
FIRMWARE="bios"
MEDIA="cdrom"
INSTALL_TIMEOUT=3600
BOOT_TIMEOUT=300
MAX_BOOT=30
MAX_BOOT_SET=0
PROGRESS_EVERY=30
STAGE_WAIT=10
PROG_AT=0
MARKER="install complete"
BOOT_MARKERS=()
BOOT_MARKER_SET=0
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
  --media KIND         cdrom 或 usb，缺省 cdrom；usb 以裸盘挂载镜像，
                       固件按 MBR/GPT 定位 ESP，与真机 U 盘装机同路径
  --install-timeout S  单轮安装超时秒数，缺省 3600
  --boot-timeout S     单轮启动硬超时秒数，缺省 300
  --max-boot S         启动墙钟上限秒数，缺省 30；仅 login: 腿生效，
                       桌面/验收标记腿缺省不设上限
  --marker TEXT        %post 完成标记，缺省 "install complete"
  --boot-marker TEXT   启动完成标记，可重复；全部出现才算启动完成，缺省 "login:"
  --fw-dir DIR         优先在该目录探测 OVMF/AAVMF 固件
  -h, --help           显示本帮助

产物:
  DIR/run-FW-N/disk.qcow2      第 N 轮安装盘
  DIR/run-FW-N/vars.fd         UEFI NVRAM（安装与启动共用）
  DIR/run-FW-N/install.log     第 N 轮安装串口日志
  DIR/run-FW-N/boot.log        第 N 轮启动串口日志
  DIR/run-FW-N/qemu.log        安装阶段 QEMU 自身 stderr
  DIR/run-FW-N/qemu-boot.log   启动阶段 QEMU 自身 stderr
  DIR/run-FW-N/firmware.log    固件调试口（SeaBIOS 0x402），BIOS+光盘腿
  DIR/install-manifest.txt     轮次结果与 ISO 摘要

每轮开始前会删除本轮 install.log/boot.log/firmware.log，判读只看本轮内容。

OUT 必须位于源码区之外；缺失 qemu-system-$ARCH / qemu-img 时以 77 跳过。
同一个 --out 只承载一种 --media：cdrom 与 usb 的轮次目录同名，混用会
互相覆盖，两种形态要分目录存放。
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
        --media) optarg "$1" "$#"; MEDIA="$2"; shift 2 ;;
        --install-timeout)
            optarg "$1" "$#"; need_num "$1" "$2"
            INSTALL_TIMEOUT="$2"; shift 2 ;;
        --boot-timeout)
            optarg "$1" "$#"; need_num "$1" "$2"; BOOT_TIMEOUT="$2"; shift 2 ;;
        --max-boot)
            optarg "$1" "$#"; need_num "$1" "$2"
            MAX_BOOT="$2"; MAX_BOOT_SET=1; shift 2 ;;
        --marker) optarg "$1" "$#"; MARKER="$2"; shift 2 ;;
        --boot-marker)
            optarg "$1" "$#"
            # 首个标记顶替缺省值，后续追加：调用方给几个就等几个，
            # 不缺省混入 login:——否则桌面腿会在登录提示一出现就判过。
            [ "${BOOT_MARKER_SET}" -eq 1 ] || BOOT_MARKERS=()
            BOOT_MARKERS+=("$2"); BOOT_MARKER_SET=1; shift 2 ;;
        --fw-dir) optarg "$1" "$#"; FW_DIR="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "未知参数: $1" ;;
        esac
    done
    [ -f "${ISO:-}" ] || die "--iso 必填且必须是存在的文件: ${ISO:-未给出}"
    [ "${RUNS}" -ge 1 ] || die "--runs 必须大于 0"
    # 首个 --boot-marker 顶替缺省值后，MAX_BOOT 的语义从「30s 上限」变成
    # 「未指定」：桌面腿与验收腿的墙钟包含会话初始化，不能被 30s 截断。
    [ "${BOOT_MARKER_SET}" -eq 1 ] || BOOT_MARKERS=("login:")
    [ "${MAX_BOOT_SET}" -eq 1 ] || [ "${BOOT_MARKERS[*]}" = "login:" ] || MAX_BOOT=""
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
            # 与 ci/lib/host.sh 的 uefi_fw_paths 逐字一致：Ubuntu 24.04
            # 起只有 4M 形态，Debian 另有合并镜像 OVMF.fd，故用 glob
            # 覆盖命名变化。
            cand=(/usr/share/OVMF/OVMF_CODE*.fd /usr/share/ovmf/OVMF.fd
                  /usr/share/edk2/ovmf/OVMF_CODE*.fd /usr/share/qemu/OVMF.fd)
            ;;
        aarch64)
            cand=(/usr/share/AAVMF/AAVMF_CODE.fd
                  /usr/share/edk2/aarch64/QEMU_EFI.fd
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
    # 架构与固件是一个二维约束：拆成三条 case 时，「aarch64 只能 uefi」要
    # 单列一条 if，且非法架构与非法固件会在同一条输入上互相遮盖。合成一张
    # 表后每种组合只出现一次，报错落在真正不合法的那个维度上。
    case "${ARCH}:${FIRMWARE}" in
    x86_64:bios|x86_64:uefi|x86_64:both|aarch64:uefi) ;;
    x86_64:*) die "不支持的固件: ${FIRMWARE}" ;;
    aarch64:*) die "aarch64 仅支持 uefi 固件: ${FIRMWARE}" ;;
    *) die "不支持的架构: ${ARCH}" ;;
    esac
    case "${MEDIA}" in
    cdrom|usb) ;;
    *) die "不支持的介质形态: ${MEDIA}" ;;
    esac
    if [ "${FIRMWARE}" != bios ] && ! fw_probe; then
        # --firmware both 是「能测就测两条腿」的意图声明，宿主机没有
        # OVMF/AAVMF 时 UEFI 腿本就无从执行。此时按 bios 腿继续，而不是
        # 让整轮装机段以参数错误退出：否则一台未装 edk2 的构建机连 BIOS
        # 腿的证据也拿不到，缺陷被环境问题掩盖。
        if [ "${FIRMWARE}" = both ]; then
            printf 'install-test: 未找到 UEFI 固件，' >&2
            printf 'UEFI 腿降级为跳过，仅跑 BIOS 腿\n' >&2
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

# 跳过的理由要能直接指向缺失的那一条命令。只写「工具链不可用」时，现场
# 得回到宿主手工复现才知道缺的是 qemu-system-<arch> 还是 qemu-img；0.0.5 的
# 验收镜像里三条腿都是这一行，而宿主其实只装上了固件、一条 qemu 命令都没
# 有，事后翻日志也看不出这个区别。
missing_tools()
{
    local c out=""

    for c in "${QEMU}" qemu-img; do
        need "${c}" || out="${out}${out:+ }${c}"
    done
    printf '%s' "${out}"
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
    # UKUI 会话经 lightdm 拉起后需要可用的 DRM/KMS 设备做 X 后端。内核基线
    # 是 openeuler_defconfig，DRM_VIRTIO_GPU 与 DRM_BOCHS 都是 =m，由 udev
    # 按设备匹配加载；这里仍统一接 virtio-gpu，让两架构的显示后端同源：
    # aarch64 的 virt 机型没有缺省显示设备，必须显式追加 PCI 设备，x86_64
    # 则以 -vga virtio 替换缺省 std VGA。
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

dev_media()
{
    local iso="$1"
    if [ "${MEDIA}" = usb ]; then
        # 裸盘形态：固件按 MBR/GPT 找 ESP。真机 U 盘装机走的就是这条路，
        # 站点派生后若漏掉 MBR 0xEF 分区项与 GPT 条目的对齐，这里装不上，
        # 而 -cdrom 腿仍然全绿。bootindex 让固件优先选它，不依赖型号排序。
        local usb="usb-storage,drive=usb0,bus=xhci.0"
        QARGS+=(-device qemu-xhci,id=xhci
                -drive "file=${iso},if=none,id=usb0,format=raw,readonly=on"
                -device "${usb},removable=on,bootindex=1")
        return 0
    fi
    if [ "${ARCH}" = aarch64 ]; then
        QARGS+=(-device virtio-scsi-pci,id=scsi0
                -drive "file=$1,if=none,id=cd0,media=cdrom,readonly=on"
                -device scsi-cd,drive=cd0)
    else
        QARGS+=(-cdrom "$1")
    fi
}

# dev_dbg <fw> <dir>
# SeaBIOS 的调试输出走 0x402 端口，QEMU 缺省不落盘；-serial 只接 guest
# ttyS0。引导链断在固件时两条通路都空，现场无法区分「介质不可引导」与
# 「介质可引导但内核没起」。把 0x402 接进 firmware.log 后，该腿会留下
# "Booting from DVD/CD..." 或 "Boot failed" 这类事实，卡点直接落在层上。
# UEFI 固件的诊断走 OVMF 自己的调试口（0x402 的另一套），不在本步范围。
dev_dbg()
{
    local fw="$1" dir="$2"
    [ "${fw}" = bios ] && [ "${ARCH}" = x86_64 ] || return 0
    QARGS+=(-chardev "file,id=fwdbg,path=${dir}/firmware.log"
            -device isa-debugcon,iobase=0x402,chardev=fwdbg)
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
    local log="$1" elapsed="$2" line bytes
    [ "${elapsed}" -ge "${PROG_AT}" ] || return 0
    line="$(log_tail "${log}")"
    if [ -z "${line}" ]; then
        # 空尾行不是「正在启动」，而是该腿一个字都没往 ttyS0 写。引导参数
        # 缺 console=ttyS0 时安装器把全部输出留在 VGA，心跳连打两小时后
        # 仍只有空行，读日志的人分不清是慢还是静默（run 41121955316 的
        # run-bios-1：120 次心跳全空，直到 3600 秒超时才由 fail_note 归因）。
        # 字节数一并给出，0 B 就是该腿从未写过串口。
        bytes="$(stat -c %s "${log}" 2>/dev/null || printf 0)"
        line="(串口静默 ${bytes}B，无引导输出)"
    fi
    printf '# %s +%ss: %.110s\n' "$(basename "$(dirname "${log}")")" \
        "${elapsed}" "${line}"
    PROG_AT=$((elapsed + PROGRESS_EVERY))
}

fail_hit()
{
    grep -oE "${INST_ERR}" "$1" 2>/dev/null | head -n 1
}

# fail_note <fw> <log> <qemu-log> <fw-log> <spent>
# 失败归因的唯一出口：串口有内容就回显尾行；0 字节则显式说明该固件腿
# 从未向 ttyS0 写过东西，并依次附上固件调试口与 QEMU 自身 stderr。
# 此前只在日志文件不存在时才打 QEMU 输出，而安装器把全部输出送到 VGA 时
# 日志是存在的空文件，现场只剩一行空的 serial tail，读日志的人分不清是
# 固件没引导、内核没起来，还是引导参数缺 console（run 41090215913 的
# run-bios-1）。固件尾行补上这一层：有 "Boot failed" 就是介质不可引导，
# 有 "Booting from DVD/CD" 才是「已引导、内核没起」。
fail_note()
{
    local fw="$1" log="$2" qlog="$3" fwlog="$4" spent="$5" qemu fwline

    if [ -s "${log}" ]; then
        printf '#   serial tail: %.200s\n' "$(log_tail "${log}")" >&2
    else
        printf '#   serial empty after %ss: %s boot path wrote nothing' \
            "${spent}" "${fw}" >&2
        printf ' to ttyS0\n' >&2
    fi
    fwline="$(log_tail "${fwlog}")"
    if [ -n "${fwline}" ]; then
        printf '#   firmware tail: %.200s\n' "${fwline}" >&2
    elif [ "${fw}" = bios ] && [ "${ARCH}" = x86_64 ]; then
        printf '#   firmware silent: %s 未写调试口，引导链未进入固件阶段\n' \
            "SeaBIOS" >&2
    fi
    qemu="$(tr '\n' ' ' <"${qlog}" 2>/dev/null)"
    [ -n "${qemu}" ] || return 0
    printf '#   qemu: %.300s\n' "${qemu}" >&2
}

# wait_inst <log> <fw-log> <pid> <deadline> <start>
# 返回 0 完成、2 命中安装失败标记、3 超时、4 固件判定介质不可引导。
# 固件判负要先于超时：此后内核根本没有机会写串口，再等下去只是空耗。
wait_inst()
{
    local log="$1" fwlog="$2" pid="$3" deadline="$4" start="$5" now
    while :; do
        grep -qE "${INST_ERR}" "${log}" 2>/dev/null && return 2
        fw_failed "${fwlog}" && return 4
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

# fw_failed <fw-log>
fw_failed()
{
    [ -s "$1" ] || return 1
    grep -qE "${FW_FAIL}" "$1" 2>/dev/null
}

install_run()
{
    local fw="$1" n="$2" dir="${OUT}/run-$1-$2" disk log fwlog rc start pid
    mkdir -p "${dir}" || return 1
    disk="${dir}/disk.qcow2"
    log="${dir}/install.log"
    fwlog="${dir}/firmware.log"
    # 判读只看日志内容、不看时间戳，因此上一轮的串口日志必须先删掉。
    # wait_inst() 首轮就会 grep INST_ERR，残留日志能让空跑直接判失败；
    # 末尾的 MARKER 断言同样会被残留日志满足，从而假通过。
    rm -f "${log}" "${fwlog}" "${dir}/qemu.log" || return 1
    qemu-img create -f qcow2 "${disk}" 40G \
        >"${dir}/qemu-img.log" 2>&1 ||
        { printf 'qemu-img create failed: run-%s-%s\n' \
              "${fw}" "${n}" >&2; return 1; }
    qemu_base
    fw_args "${fw}" "${dir}" || return 1
    dev_disk "${disk}" "${fw}"
    dev_media "${ISO}"
    dev_dbg "${fw}" "${dir}"
    # USB 形态下 U 盘属于硬盘类设备，SeaBIOS 只按 boot order 枚举被点名的
    # 类别；仍写 order=d 时整类硬盘被跳过，U 盘根本没有被尝试的机会。
    if [ "${MEDIA}" = usb ]; then
        QARGS+=(-boot order=cd)
    else
        QARGS+=(-boot order=d)
    fi
    QARGS+=(-netdev user,id=n0 -device virtio-net-pci,netdev=n0
            -serial "file:${log}")
    start=$(date +%s)
    PROG_AT=${PROGRESS_EVERY}
    "${QEMU}" "${QARGS[@]}" >/dev/null 2>"${dir}/qemu.log" &
    pid=$!
    wait_inst "${log}" "${fwlog}" "${pid}" \
        "$((start + INSTALL_TIMEOUT))" "${start}"
    rc=$?
    stop_qemu "${pid}"
    if [ "${rc}" -ne 0 ]; then
        case "${rc}" in
        2) printf 'install failure pattern in run-%s-%s/install.log: %.110s\n' \
               "${fw}" "${n}" "$(fail_hit "${log}")" >&2 ;;
        3) printf 'install timeout in run-%s-%s after %ss\n' \
               "${fw}" "${n}" "$(($(date +%s) - start))" >&2 ;;
        4) printf 'firmware rejected the media in run-%s-%s: %.110s\n' \
               "${fw}" "${n}" "$(log_tail "${fwlog}")" >&2 ;;
        *) printf 'install run %s-%s exited rc=%s\n' \
               "${fw}" "${n}" "${rc}" >&2 ;;
        esac
        fail_note "${fw}" "${log}" "${dir}/qemu.log" "${fwlog}" \
            "$(($(date +%s) - start))"
        return 1
    fi
    grep -q "${MARKER}" "${log}" 2>/dev/null ||
        { printf 'marker missing in run-%s-%s/install.log\n' "${fw}" "${n}" >&2
          fail_note "${fw}" "${log}" "${dir}/qemu.log" "${fwlog}" \
              "$(($(date +%s) - start))"
          return 1; }
}

probe_log()
{
    local m

    # 多个标记同时给出时结论取交集：桌面起来了但联机没就绪，仍然是
    # 「装完不能用」，不能在第一个标记出现时就收尾。
    for m in "${BOOT_MARKERS[@]}"; do
        grep -q "${m}" "$1" 2>/dev/null && continue
        grep -qE "${BOOT_FAIL}" "$1" 2>/dev/null && return 2
        return 1
    done
    return 0
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

# wait_marker <log> <fw-log> <pid> <deadline> <start>
# 返回 0 命中启动标记、1 超时或进程早退未达标记、2 命中引导失败标记、
# 3 固件判定磁盘不可引导。返回 3 与 wait_inst 同义：盘上没有可引导代码时
# guest 不会向 ttyS0 写字，再等满 --boot-timeout 也只是空转。
wait_marker()
{
    local log="$1" fwlog="$2" pid="$3" deadline="$4" start="$5" rc now
    while :; do
        probe_log "${log}"
        rc=$?
        [ "${rc}" -eq 0 ] && return 0
        [ "${rc}" -eq 2 ] && return 2
        fw_failed "${fwlog}" && return 3
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
    kill "$1" 2>/dev/null
    wait "$1" 2>/dev/null
}

# 九阶段契约（system/scripts/ui.sh 的 UI_STAGES）在串口日志里是否完整。
# 期望表从契约本身解析，不在验收脚本里另抄一份编号与代号：抄一份就会在
# 阶段增删时静默漂移，而这条断言存在的意义正是防漂移。序号与 ASCII 代号
# 是屏幕上的稳定部分，中文名只进 journal，因此只匹配前者。
#
# 0.0.4 的验收在只有 7 段的日志上通过，缺的正是首启判定与自检与取证——
# 机器照常进桌面，而「卡在哪一步」的现场证据少了两块。段行不齐与启动
# 失败不同，后者会自己冒出来，前者不会。
#
# 验收剖面按设计 mask 掉产品就绪单元（单一判定者原则），第 8 段因此不会
# 发射。期望集必须与本次启动的剖面一致：屏蔽清单从执行 mask 的夹具里读，
# 单元与阶段的归属从契约的 UI_STAGE_UNITS 里读，两处都是各自的事实源。
# 放行的只是「按设计不存在」的段，其余段照旧全量要求；屏蔽清单或归属任一
# 处改动都会自动反映到期望集，本脚本不持有第三份编号表。
stage_table()
{
    sed -n "s/^[[:space:]]*'\([0-9][0-9]*\)|.*|\([a-z][a-z-]*\)'$/\1 \2/p" \
        "${DISTRO_ROOT}/../system/scripts/ui.sh"
}

stage_own()
{
    sed -n "s/^[[:space:]]*'\([a-z][a-z-]*\)|\([^'|]*\)'$/\1 \2/p" \
        "${DISTRO_ROOT}/../system/scripts/ui.sh"
}

# 本次启动应出现的阶段行。被屏蔽单元负责的阶段整段剔除；未登记归属的
# 单元即便被屏蔽也不剔除，宁可判负也不静默缩短判据。
#
# 三张表按代号对齐一次即可得出结论，不需要在 shell 里维护两张关联数组：
# 段表与归属表 join 出「段 ↔ 生产者」，未登记归属的段由 -e 填哨兵 @，
# 它不可能出现在屏蔽清单里，因此原样保留；再按屏蔽清单整行剔除。
# 三张表各取各自的事实源，本函数不持有第四份编号表。
stage_want()
{
    local ks="${DISTRO_ROOT}/ci/ks/acceptance.part"

    [ "$(airy_profile)" -eq 1 ] || {
        stage_table
        return 0
    }
    [ -r "${ks}" ] || {
        printf 'acceptance fixture missing: %s\n' "${ks}" >&2
        return 1
    }
    LC_ALL=C join -a1 -e @ -o 1.1,1.2,2.2 -1 2 -2 1 \
        <(stage_table | LC_ALL=C sort -k2,2) \
        <(stage_own | LC_ALL=C sort -k1,1) |
        grep -vwF -f <(sed -n \
            's/^[[:space:]]*systemctl --root=\/ mask[[:space:]]\{1,\}//p' \
            "${ks}" | tr -s '[:space:]' '\n' | sed '/^$/d') |
        cut -d' ' -f1,2 | LC_ALL=C sort -n
}

stage_absent()
{
    local log="$1" total="$2" id code miss=""

    while read -r id code; do
        grep -qF "[ ${id}/${total} ] ${code}" "${log}" 2>/dev/null ||
            miss="${miss}${id}(${code}) "
    done
    printf '%s' "${miss}"
}

# 登录提示与 multi-user 并行拉起的两个观察者之间有毫秒级竞态，因此标记
# 命中后再给 STAGE_WAIT 秒收齐；行齐立即返回，不以固定等待拖慢正常启动。
# 缺行时把缺的序号与代号一并报出，下一次现场验收不必人工数段。
wait_stages()
{
    local log="$1" total want rows miss deadline

    total=$(stage_table | wc -l)
    if [ "${total}" -eq 0 ]; then
        printf 'stage table unreadable: %s\n' \
            "${DISTRO_ROOT}/../system/scripts/ui.sh" >&2
        return 1
    fi
    rows=$(stage_want) || return 1
    want=$(printf '%s\n' "${rows}" | wc -l)
    [ "${want}" -gt 0 ] || {
        printf 'stage set empty after profile mask\n' >&2
        return 1
    }
    [ "${want}" -eq "${total}" ] ||
        printf 'profile masks %s stage(s): %s of %s expected\n' \
            "$((total - want))" "${want}" "${total}" >&2
    deadline=$(( $(date +%s) + STAGE_WAIT ))
    while :; do
        miss=$(stage_absent "${log}" "${total}" <<<"${rows}")
        [ -z "${miss}" ] && return 0
        if [ "$(date +%s)" -ge "${deadline}" ]; then
            printf 'boot stages missing in %s: %s(of %s)\n' \
                "${log}" "${miss}" "${total}" >&2
            return 1
        fi
        sleep 1
    done
}

boot_run()
{
    local fw="$1" n="$2" dir="${OUT}/run-$1-$2"
    local disk="${dir}/disk.qcow2" log="${dir}/boot.log"
    local fwlog="${dir}/firmware.log"
    local pid start now code
    [ -f "${disk}" ] || {
        printf 'no disk for run-%s-%s\n' "${fw}" "${n}" >&2
        return 1
    }
    # 同 install_run：boot.log 若不轮转，wait_marker 首轮就能被上一轮的
    # 标记满足，空跑会被判为启动成功。
    rm -f "${log}" "${fwlog}" "${dir}/qemu-boot.log" || return 1
    qemu_base
    fw_args "${fw}" "${dir}" || return 1
    dev_disk "${disk}" "${fw}"
    dev_dbg "${fw}" "${dir}"
    QARGS+=(-boot order=c -serial "file:${log}")
    start=$(date +%s)
    PROG_AT=${PROGRESS_EVERY}
    "${QEMU}" "${QARGS[@]}" >/dev/null 2>"${dir}/qemu-boot.log" &
    pid=$!
    wait_marker "${log}" "${fwlog}" "${pid}" \
        "$((start + BOOT_TIMEOUT))" "${start}"
    code=$?
    stop_qemu "${pid}"
    note_units "${log}"
    now=$(date +%s)
    BOOT_S=$((now - start))
    case "${code}" in
    0) wait_stages "${log}" || {
           fail_note "${fw}" "${log}" "${dir}/qemu-boot.log" \
               "${fwlog}" "${BOOT_S}"
           return 1
       } ;;
    2) printf 'boot failure pattern in run-%s-%s/boot.log\n' "${fw}" "${n}" >&2
       fail_note "${fw}" "${log}" "${dir}/qemu-boot.log" "${fwlog}" "${BOOT_S}"
       return 1 ;;
    3) printf 'firmware found no bootable disk in run-%s-%s: %.110s\n' \
           "${fw}" "${n}" "$(log_tail "${fwlog}")" >&2
       fail_note "${fw}" "${log}" "${dir}/qemu-boot.log" "${fwlog}" "${BOOT_S}"
       return 1 ;;
    *) printf 'boot incomplete in run-%s-%s/boot.log after %ss\n' \
           "${fw}" "${n}" "${BOOT_S}" >&2
       fail_note "${fw}" "${log}" "${dir}/qemu-boot.log" "${fwlog}" "${BOOT_S}"
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
        printf 'media=%s\n' "${MEDIA}"
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
    local fw tools
    parse_args "$@"
    check_env
    OUT="$(out_guard install-test "${OUT}")" || exit $?
    QEMU="qemu-system-${ARCH}"
    tools=$(missing_tools)
    if [ -n "${tools}" ]; then
        printf 'TAP version 14\n1..0 # SKIP QEMU toolchain unavailable: %s\n' \
            "${tools}"
        exit "${SKIP}"
    fi
    accel_set
    legs_build
    printf 'TAP version 14\n1..%d\n' "$((RUNS * 2 * ${#LEGS[@]}))"
    printf '# AirymaxOS install test:'
    printf ' iso=%s arch=%s firmware=%s media=%s runs=%s accel=%s\n' \
        "$(basename "${ISO}")" "${ARCH}" "${FIRMWARE}" \
        "${MEDIA}" "${RUNS}" "${ACCEL}"
    for fw in "${LEGS[@]}"; do
        run_leg "${fw}"
    done
    manifest
    printf '# summary: pass=%d fail=%d\n' "${PASS}" "${FAIL}"
    [ "${FAIL}" -eq 0 ]
}

main "$@"
