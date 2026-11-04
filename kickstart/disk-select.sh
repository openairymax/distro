#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# disk-select.sh — 安装期选盘、布局生成与选盘记录（被 kickstart 嵌入）
#
# 安装器没有「自动」盘名：clearpart --all 加 autopart 会把每一块可用磁盘
# 都纳入自动布局。B50（2026-10-30）因此把 ESP 与 /boot 放到可插拔 U 盘、
# 把根与数据分区放到 NVMe：拔盘即不可引导，且 --all 清空了全部接入磁盘
# （D-33）。选盘与布局必须收敛到一块内置盘，并逐项 --ondisk 钉住。
#
# 系统分区（/）与数据分区（/data）独立挂载（DISK-01）：系统盘之外若还有
# 一块未被占用的内置盘，数据分区落在它上面；只有一块盘时同盘切分，系统
# 分区定容、数据分区增长。两条路径产出的指令形状相同，装机后 /data 可以
# 单独扩容而系统分区的 UUID 与 fsck 结果不变。
#
# 系统盘优先取未被占用的整盘：双系统现场更大的那块盘往往已有 Windows，
# 按容量直接选会把既有系统清掉；全部盘都被占用时才退回容量最大者，重装
# 本系统的现场因此仍然可用。
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
# 依赖：airy_out 与 airy_fail 由 install-lib.sh 提供，本文件必须由同一
# 脚本段先展开 install-lib.sh，否则调用点落到未定义函数。
#
# 现场排障与测试用的注入点：
#   AIRY_FW          固件根目录（默认 /sys/firmware）
#   AIRY_MEDIUM_SRC  安装介质挂载点（默认 /run/install/repo）
#   AIRY_REC         选盘记录路径（默认 /tmp/airymax-disk.json）
#   AIRY_MIN_BYTES   可用容量下限，默认 32 GiB
#   AIRY_SWAP_MIB    交换分区容量，默认 8192 MiB
#   AIRY_ROOT_MIB    同盘切分时系统分区期望容量，默认 20480 MiB
#   AIRY_DATA_MIB    同盘切分时数据分区保底容量，默认 10240 MiB
# ===========================================================================

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

# airy_busy <disk> — 该整盘是否已被占用（有分区、有文件系统或已挂载）。
#
# 数据分区不得落在已被占用的盘上：双系统现场的第二块盘就是 Windows 的
# NTFS 分区，清掉它等于毁掉用户既有系统。归属按盘名前缀还原（sda1、
# nvme0n1p1），不认控制器与盘符，新设备只要 lsblk 报出父子关系就落在
# 同一条判定里。
airy_busy()
{
    lsblk -npo NAME,TYPE,FSTYPE,MOUNTPOINT --pairs 2>/dev/null |
        awk -v disk="/dev/$1" '
        {
            name = ""; type = ""; fs = ""; mount = ""
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
                else if (key == "FSTYPE")
                    fs = val
                else if (key == "MOUNTPOINT")
                    mount = val
            }
            if (name == disk) {
                if (type == "disk" && fs != "")
                    busy = 1
                next
            }
            if (index(name, disk) != 1)
                next
            rest = substr(name, length(disk) + 1)
            if (rest ~ /^p?[0-9]+$/ || mount != "")
                busy = 1
        }
        END { exit(busy ? 0 : 1) }'
}

# airy_pick <skip> — 打印系统盘候选行：<name> <bytes> <bus>，无候选时为空。
#
# 双系统现场那块更大的盘往往已经有 Windows：按容量直接选盘会把用户的既有
# 系统清掉（D-33）。空盘优先让裸盘、多盘与双系统走同一条判定路径——都按
# 容量降序取第一块满足条件的整盘，只是条件不同；全部盘都被占用时才退回
# 容量最大者，重装本系统的现场因此仍然可用。
airy_pick()
{
    local skip="${1:-}" cand rest fallback=

    while read -r cand rest; do
        [ -n "${cand}" ] || continue
        fallback=${fallback:-"${cand} ${rest}"}
        if ! airy_busy "${cand#/dev/}"; then
            printf '%s %s\n' "${cand}" "${rest}"
            return 0
        fi
    done <<EOF
$(airy_scan "${skip}")
EOF
    printf '%s\n' "${fallback}"
}

# airy_data <medium> <system> — 打印数据盘（不含 /dev/），没有候选时为空。
#
# 候选与系统盘同源（airy_scan）：内置、非介质、容量降序。多盘现场取第一块
# 既非系统盘、又未被占用的整盘，即「数据分区优先落第二块盘」；单盘现场无
# 候选，由调用方转同盘切分。拓扑只改变候选集合，判定路径不变。
airy_data()
{
    local skip="$1" sys="$2" cand rest

    while read -r cand rest; do
        [ -n "${cand}" ] || continue
        cand=${cand#/dev/}
        if [ "${cand}" = "${sys}" ]; then
            continue
        fi
        if airy_busy "${cand}"; then
            continue
        fi
        printf '%s\n' "${cand}"
        return 0
    done <<EOF
$(airy_scan "${skip}")
EOF
    return 0
}

# airy_root_mib <bytes> — 同盘切分时系统分区的容量（MiB）。
#
# Windows 的系统盘/数据盘语义照搬到单盘：系统分区定容、数据分区增长，用户
# 数据不再与系统增长互相挤压。定容按盘容量折半并夹逼在 [AIRY_ROOT_MIB,
# 容量 − AIRY_DATA_MIB] 之间；小盘上夹逼区间为空时退回折半，让 /data 仍
# 拿得到可用空间，而不是把余量全部塞进系统分区。
airy_root_mib()
{
    local avail half lo hi

    avail=$(($1 / 1048576 - ${AIRY_SWAP_MIB:-8192} - 1625))
    [ "${avail}" -gt 0 ] || avail=1
    half=$((avail / 2))
    lo=${AIRY_ROOT_MIB:-20480}
    hi=$((avail - ${AIRY_DATA_MIB:-10240}))
    if [ "${hi}" -lt "${lo}" ]; then
        printf '%s\n' "${half}"
        return 0
    fi
    [ "${half}" -lt "${lo}" ] && half=${lo}
    [ "${half}" -gt "${hi}" ] && half=${hi}
    printf '%s\n' "${half}"
}

# airy_layout <system> <data|""> <uefi|bios> <bytes> — 打印整份存储指令。
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
#
# /data 恒为独立挂载：有数据盘时系统盘与数据盘各自增长；同盘时系统分区
# 定容、数据分区增长。数据分区只增不改，扩容它不会移动系统分区的起止扇区，
# 系统分区 UUID 与 fsck 结果因此保持不变（DISK-01 判据②）。
airy_layout()
{
    local sys="$1" data="$2" fw="$3" bytes="$4" drives="${1}"

    [ -n "${data}" ] && drives="${sys},${data}"
    printf 'ignoredisk --only-use=%s\n' "${drives}"
    printf 'clearpart --all --initlabel --disklabel=gpt --drives=%s\n' \
        "${drives}"
    if [ "${fw}" != uefi ]; then
        printf 'part biosboot --fstype=biosboot --size=1 --ondisk=%s\n' \
            "${sys}"
    fi
    printf 'part /boot/efi --fstype=efi --size=600 --ondisk=%s\n' "${sys}"
    printf 'part /boot --fstype=ext4 --size=1024 --ondisk=%s\n' "${sys}"
    printf 'part swap --size=%s --ondisk=%s\n' \
        "${AIRY_SWAP_MIB:-8192}" "${sys}"
    if [ -z "${data}" ]; then
        printf 'part / --fstype=ext4 --size=%s --ondisk=%s\n' \
            "$(airy_root_mib "${bytes}")" "${sys}"
        printf 'part /data --fstype=ext4 --size=%s --grow --ondisk=%s\n' \
            "${AIRY_DATA_MIB:-10240}" "${sys}"
    else
        printf 'part / --fstype=ext4 --size=1 --grow --ondisk=%s\n' "${sys}"
        printf 'part /data --fstype=ext4 --size=1 --grow --ondisk=%s\n' \
            "${data}"
    fi
}

# airy_rec <out> <disk> <bytes> <bus> <fw> <layout> <medium> <data> — 写选盘记录。
#
# 记录是装机后 `airy-disk status` 的比对基准：安装器选了哪块盘、多大、什么
# 总线、什么固件、哪种布局、数据分区落在哪块盘，都在这里落成一份可被程序
# 读的 JSON。字段只用安装期确实掌握的事实，schema 由本函数单独定义。
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
        printf ',"data":"%s"' "${8:-}"
        printf '}\n'
    } >"$1"
}

# airy_pre <ks-out> <record> — 选盘并落盘分区片段与选盘记录。
#
# 容量下限挡住「只剩一块小盘」的现场：装完也放不下桌面闭包与图形栈，与其
# 装到一半失败，不如在分区之前就明确拒绝。系统盘之外还有空闲内置盘时数据
# 分区落在那块盘上（dual），没有时同盘切分（single）；两条路径都保证
# /data 是独立挂载，装成后语义一致（DISK-01）。
airy_pre()
{
    local ks="$1" rec="$2" fw medium pick disk size bus data kind line

    fw=$(airy_fw)
    medium=$(airy_medium)
    pick=$(airy_pick "${medium}")
    [ -n "${pick}" ] || airy_fail DISK no-internal-disk

    disk=${pick%% *}
    pick=${pick#* }
    size=${pick%% *}
    bus=${pick#* }
    disk=${disk#/dev/}

    [ "${size}" -ge "${AIRY_MIN_BYTES:-34359738368}" ] ||
        airy_fail DISK too-small "bytes=${size}"
    data=$(airy_data "${medium}" "${disk}")
    kind=single
    if [ -n "${data}" ]; then
        kind=dual
    fi

    airy_layout "${disk}" "${data}" "${fw}" "${size}" >"${ks}"
    airy_rec "${rec}" "${disk}" "${size}" "${bus}" "${fw}" "${kind}" \
        "${medium}" "${data}"
    line="AIRYMAX-DISK-OK disk=${disk} bytes=${size}"
    airy_out "${line} bus=${bus} layout=${kind} fw=${fw} data=${data:--}"
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
        airy_out "AIRYMAX-DISK-KEEP-FAIL reason=no-install-root"
        return 1
    fi
    if [ ! -s "${src}" ] || ! grep -q '"schema":1' "${src}"; then
        airy_out "AIRYMAX-DISK-KEEP-FAIL reason=bad-record src=${src}"
        return 1
    fi
    if ! install -D -m 0644 "${src}" \
        "${root}/var/lib/airymaxos/install-disk.json"; then
        airy_out "AIRYMAX-DISK-KEEP-FAIL reason=write"
        return 1
    fi
    airy_out "AIRYMAX-DISK-KEEP-OK path=/var/lib/airymaxos/install-disk.json"
    return 0
}
