#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# disk-select.sh — 安装期选盘、布局生成与选盘记录（被 kickstart 嵌入）
#
# 安装器没有「自动」盘名：clearpart --all 加 autopart 会把每一块可用磁盘
# 都纳入自动布局。B50（2026-10-30）因此把 ESP 与 /boot 放到可插拔 U 盘、
# 把根与 /home 放到 NVMe：拔盘即不可引导，且 --all 清空了全部接入磁盘
# （D-33）。选盘与布局必须收敛到一块内置盘，并逐项 --ondisk 钉住。
#
# 本文件是唯一实现：工作站与最小两个剖面、安装期与装成后的磁盘记录都从
# 这里取规则，任何一处都不再手抄一份。kickstart 以「# %airy-embed:
# disk-select.sh」标记在脚本段内嵌入选盘器，构建期由 tools/ks_embed.py
# 展开；源码区因此只有这一份规则文本。
#
# 调用约定：只定义函数，无顶层副作用，可同时嵌入 %pre 与 %post。
#   airy_pre  <ks-out> <record>   选盘，生成分区片段与选盘记录（%pre）
#   airy_keep                     把选盘记录落到目标根（%post --nochroot）
#
# 现场排障与测试用的注入点：
#   AIRY_FW          固件根目录（默认 /sys/firmware）
#   AIRY_MEDIUM_SRC  安装介质挂载点（默认 /run/install/repo）
#   AIRY_REC         选盘记录路径（默认 /tmp/airymax-disk.json）
#   AIRY_MIN_BYTES   可用容量下限，默认 32 GiB
#   AIRY_SPLIT_BYTES 拆分 /home 的容量门槛，默认 160 GiB
# ===========================================================================

# airy_mark <text> — 同时写标准输出与可用控制台。
#
# anaconda 把脚本段的标准输出收进 --log，串口上一片空白；无头验收只读串口，
# 因此关键结论必须显式写 /dev/console。内核按 console= 的注册顺序把
# /dev/console 路由到最后一个可用控制台：x86_64 为 ttyS0，aarch64 为 ttyAMA0。
airy_mark()
{
    local dev

    printf '%s\n' "$*"
    for dev in /dev/console /dev/ttyS0 /dev/ttyAMA0; do
        [ -w "${dev}" ] || continue
        printf '%s\n' "$*" >"${dev}" 2>/dev/null && return 0
    done
    return 0
}

# airy_fail <reason> [note] — 置失败标记并终止所在脚本段。
airy_fail()
{
    airy_mark "AIRYMAX-DISK-FAIL reason=$1${2:+ note=$2}"
    exit 1
}

# airy_fw — 打印 uefi 或 bios。
airy_fw()
{
    if [ -d "${AIRY_FW:-/sys/firmware}/efi" ]; then
        printf 'uefi\n'
    else
        printf 'bios\n'
    fi
}

# airy_medium — 打印安装介质自身所在整盘名（不含 /dev/），未知时为空。
#
# 排除安装介质是硬要求：BMC 虚拟光驱与内置盘上的 ISO 都表现为 RM=0，不排除
# 就会把安装源自己格式化掉。
airy_medium()
{
    local src

    src=$(findmnt -no SOURCE "${AIRY_MEDIUM_SRC:-/run/install/repo}" \
        2>/dev/null) || src=
    case "${src}" in
    /dev/*) lsblk -dno PKNAME "${src}" 2>/dev/null || : ;;
    esac
}

# airy_scan <skip> — 按容量降序打印候选整盘：<name> <bytes> <bus>。
#
# 只收 TYPE=disk、RM=0、TRAN≠usb 且非介质盘的整盘，取容量最大者。lsblk 的
# 位置参数输出在 TRAN 为空（virtio、loop）时会错位，导致容量落到总线列、
# 容量列变空；--pairs 按键名取值，缺列即空，不受字段顺序影响。
airy_scan()
{
    local skip="${1:-}"

    lsblk -dnpo NAME,TYPE,RM,TRAN,SIZE --bytes --pairs 2>/dev/null |
        awk -v skip="${skip}" '
        {
            name = ""; type = ""; rm = ""; bus = ""; size = ""
            for (i = 1; i <= NF; i++) {
                eq = index($i, "=")
                if (eq == 0)
                    continue
                key = substr($i, 1, eq - 1)
                val = substr($i, eq + 1)
                gsub(/"/, "", val)
                if (key == "NAME")
                    name = val
                else if (key == "TYPE")
                    type = val
                else if (key == "RM")
                    rm = val
                else if (key == "TRAN")
                    bus = val
                else if (key == "SIZE")
                    size = val
            }
            if (type != "disk" || rm != "0" || bus == "usb")
                next
            if (skip != "" && name == "/dev/" skip)
                next
            if (size == "" || size + 0 <= 0)
                next
            print name, size, (bus == "" ? "-" : bus)
        }' | sort -k2,2nr -k1,1
}

# airy_layout <disk> <single|split> <uefi|bios> — 打印整份存储指令。
#
# 布局逐项 --ondisk 钉住，不用 autopart：autopart 的引导设备选取会跨盘寻找
# 既有 ESP、/boot 与 swap，ignoredisk --only-use 不约束这条路径。
#
# 磁盘标签固定为 GPT，两条固件腿用同一份布局；initlabel 的默认标签随固件与
# 容量漂移，布局一旦随环境变化，两条腿就不再是同一种装机。BIOS + GPT 必须
# 自带 1MB biosboot（类型 ef02）：GPT 没有 MBR 之后那段空隙可放 grub2-pc 的
# core.img，缺它时 anaconda 判存储配置无效并退回交互式主菜单，无头安装只能
# 空耗整轮超时（run 41144010592）。UEFI 从 ESP 引导，多一个 biosboot 是无用
# 分区，故只在 BIOS 腿生成。
airy_layout()
{
    local disk="$1" kind="$2" fw="$3" swap=8192 root=1 split=

    if [ "${kind}" = split ]; then
        swap=16384
        root=71680
        split=1
    fi
    printf 'ignoredisk --only-use=%s\n' "${disk}"
    printf 'clearpart --all --initlabel --disklabel=gpt --drives=%s\n' \
        "${disk}"
    if [ "${fw}" != uefi ]; then
        printf 'part biosboot --fstype=biosboot --size=1 --ondisk=%s\n' \
            "${disk}"
    fi
    printf 'part /boot/efi --fstype=efi --size=600 --ondisk=%s\n' "${disk}"
    printf 'part /boot --fstype=ext4 --size=1024 --ondisk=%s\n' "${disk}"
    printf 'part swap --size=%s --ondisk=%s\n' "${swap}" "${disk}"
    if [ -n "${split}" ]; then
        printf 'part / --fstype=ext4 --size=%s --ondisk=%s\n' \
            "${root}" "${disk}"
        printf 'part /home --fstype=ext4 --size=1024 --grow --ondisk=%s\n' \
            "${disk}"
    else
        printf 'part / --fstype=ext4 --size=1 --grow --ondisk=%s\n' "${disk}"
    fi
}

# airy_rec <out> <disk> <bytes> <bus> <fw> <layout> <medium> — 写选盘记录。
#
# 记录是装机后 `airy-disk status` 的比对基准：安装器选了哪块盘、多大、什么
# 总线、什么固件、哪种布局，都在这里落成一份可被程序读的 JSON。字段只用
# 安装期确实掌握的事实，schema 由本函数单独定义。
airy_rec()
{
    {
        printf '{"schema":1'
        printf ',"disk":"%s"' "$2"
        printf ',"bytes":%s' "$3"
        printf ',"bus":"%s"' "$4"
        printf ',"firmware":"%s"' "$5"
        printf ',"layout":"%s"' "$6"
        printf ',"medium":"%s"' "$7"
        printf '}\n'
    } >"$1"
}

# airy_pre <ks-out> <record> — 选盘并落盘分区片段与选盘记录。
#
# 容量下限挡住「只剩一块小盘」的现场：装完也放不下桌面闭包与图形栈，与其
# 装到一半失败，不如在分区之前就明确拒绝。容量充裕时把 /home 拆成独立
# 分区，避免用户数据与系统增长互相挤压。
airy_pre()
{
    local ks="$1" rec="$2" fw medium pick disk size bus kind line

    fw=$(airy_fw)
    medium=$(airy_medium)
    pick=$(airy_scan "${medium}" | head -n 1)
    [ -n "${pick}" ] || airy_fail no-internal-disk

    disk=${pick%% *}
    pick=${pick#* }
    size=${pick%% *}
    bus=${pick#* }
    disk=${disk#/dev/}

    [ "${size}" -ge "${AIRY_MIN_BYTES:-34359738368}" ] ||
        airy_fail too-small "bytes=${size}"
    kind=single
    [ "${size}" -lt "${AIRY_SPLIT_BYTES:-171798691840}" ] || kind=split

    airy_layout "${disk}" "${kind}" "${fw}" >"${ks}"
    airy_rec "${rec}" "${disk}" "${size}" "${bus}" "${fw}" "${kind}" "${medium}"
    line="AIRYMAX-DISK-OK disk=${disk} bytes=${size}"
    airy_mark "${line} bus=${bus} layout=${kind} fw=${fw}"
}

# airy_keep — 把选盘记录复制进目标根。
#
# %post --nochroot 的 /tmp 是安装器自己的 /tmp，记录会随安装器消失；装成后
# 的系统要读它，只能复制进目标根。目标根挂载点是安装器的实现细节
# （/mnt/sysroot 与 /mnt/sysimage 随版本变化），按可执行文件实际位置判定。
airy_keep()
{
    local src="${AIRY_REC:-/tmp/airymax-disk.json}" root=

    for root in "${ANA_INSTALL_PATH-}" "${INSTALL_ROOT-}" \
        /mnt/sysroot /mnt/sysimage; do
        if [ -n "${root}" ] && [ -d "${root}/etc" ]; then
            break
        fi
        root=
    done
    if [ -z "${root}" ]; then
        airy_mark "AIRYMAX-DISK-KEEP-FAIL reason=no-install-root"
        return 1
    fi
    if [ ! -s "${src}" ] || ! grep -q '"schema":1' "${src}"; then
        airy_mark "AIRYMAX-DISK-KEEP-FAIL reason=bad-record src=${src}"
        return 1
    fi
    if ! install -D -m 0644 "${src}" \
        "${root}/var/lib/airymaxos/install-disk.json"; then
        airy_mark "AIRYMAX-DISK-KEEP-FAIL reason=write"
        return 1
    fi
    airy_mark "AIRYMAX-DISK-KEEP-OK path=/var/lib/airymaxos/install-disk.json"
    return 0
}
