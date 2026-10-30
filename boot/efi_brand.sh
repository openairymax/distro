#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# efi_brand.sh — 在 ESP 内建立 AirymaxOS 引导项并置顶
#
# 调用者：安装配方的 %post --nochroot（airymaxos-workstation.ks）。该段先把
#         efivarfs、ESP 与 /dev /proc /sys 挂进目标根，再在 chroot 内调用本
#         脚本，因此 efibootmgr / findmnt / lsblk 都由被测系统提供——安装器
#         自带的环境里没有这些工具，早期版本直接调用时走进了 skip 分支。
#         三个时机只有安装期可行：默认视图的 chroot 段看不到 ESP 与 NVRAM；
#         首启单元被 SELinux 拦下——systemd 以 init_t 运行，在 dosfs_t 上
#         建文件被拒（验收 run 40574831975 的 AVC：denied { create } for
#         comm="efi_brand.sh" scontext=system_u:system_r:init_t:s0
#         tcontext=...:dosfs_t tclass=file permissive=0）。
#
# 为什么需要这一步：anaconda 用 /etc/system-release 派生 GRUB_DISTRIBUTOR，
# 装机后 NVRAM 条目叫 "openEuler"，固件菜单与 BootOrder 都是上游名字；
# 条目标签不能改名，只能新建再置顶，因此要独立一条 AirymaxOS 引导项。
#
# 为什么搬整套而非只放 shim：shim 只从自己所在目录取 grubx64.efi，签名链
# 也在同一目录内闭合，EFI/airymaxos 必须是完整的一套二级加载器。grubx64
# 内嵌 prefix 仍指向 /EFI/openEuler，所以真正生效的菜单配置不变；同目录的
# grub.cfg 只是品牌一致性副本，老化的风险仅限装饰。
#
# 退出码：0 = 完成，或本机不在可改写范围（非 EFI 固件、此前已品牌化）；
#         1 = 在可改写范围内但失败（含 ESP 未挂载、缺 efibootmgr）。调用者
#         据此中止安装：静默跳过只会把「品牌归属」推迟到验收现场，而那时
#         已无从归因。
# ===========================================================================

esp=/boot/efi
label=AirymaxOS
state=/var/lib/airymaxos/efi-brand
loader='\EFI\airymaxos\shimx64.efi'

note()
{
    printf 'AIRYMAX-EFI-NOTE %s\n' "$*"
}

skip()
{
    note "skip: $*"
    exit 0
}

fail()
{
    note "fail: $*"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
    --esp) esp=${2:?--esp 需要目录}; shift 2 ;;
    --state) state=${2:?--state 需要文件}; shift 2 ;;
    *) printf 'usage: %s [--esp DIR] [--state FILE]\n' "$0" >&2; exit 2 ;;
    esac
done
dst=${esp}/EFI/airymaxos

# 只有非 EFI 装机与重复调用不在本脚本能改写的范围内。ESP 未挂载与缺
# efibootmgr 属于环境缺陷（配方已把 ESP 挂好，包闭包已声明对 efibootmgr 的
# 依赖），必须显式失败：跳过只会让「品牌没做」等到验收现场才暴露。
[ -d /sys/firmware/efi ] || skip "no efivarfs (BIOS boot)"
[ -d ${esp}/EFI ] || fail "no ESP at ${esp}"
command -v efibootmgr >/dev/null 2>&1 || fail "efibootmgr unavailable"
[ -e ${state} ] && skip "already branded (${state})"

# 按目录找已签名的 shim，排除目标目录自身。
src=
for d in ${esp}/EFI/*; do
    [ -d "${d}" ] || continue
    [ "${d}" = "${dst}" ] && continue
    [ -f "${d}/shimx64.efi" ] || continue
    src=${d}
    break
done
[ -n "${src}" ] || fail "no signed shim under ${esp}/EFI"

install -d -m 0755 "${dst}" || fail "create ${dst} failed"
for f in shimx64.efi grubx64.efi mmx64.efi fbx64.efi grub.cfg grubenv; do
    [ -f "${src}/${f}" ] || continue
    install -m 0644 "${src}/${f}" "${dst}/${f}" || fail "copy ${f} failed"
done
printf 'shimx64.efi,airymaxos,,%s\n' "${label}" >"${dst}/BOOTX64.CSV" ||
    fail "write BOOTX64.CSV failed"

dev=$(findmnt -no SOURCE --target "${esp}" 2>/dev/null) || dev=
[ -n "${dev}" ] && dev=$(readlink -f "${dev}" 2>/dev/null)
[ -n "${dev}" ] || fail "ESP source unresolved (${esp})"
disk=/dev/$(lsblk -no PKNAME "${dev}" 2>/dev/null) || disk=
part=
[ -r "/sys/class/block/${dev##*/}/partition" ] &&
    part=$(cat "/sys/class/block/${dev##*/}/partition")
[ -b "${disk}" ] && [ -n "${part}" ] ||
    fail "ESP geometry unknown (dev=${dev})"

# 同标签旧条目先删：重装后 NVRAM 里可能残留 AirymaxOS，efibootmgr 会自动
# 追加序号（AirymaxOS0），BootOrder 于是指向旧路径。
for e in $(efibootmgr 2>/dev/null | awk -v l="${label}" '{
    id = $1
    sub(/^Boot/, "", id)
    gsub(/\*/, "", id)
    if (length(id) == 4 && $2 == l) print id
}'); do
    efibootmgr -b "${e}" -B >/dev/null 2>&1
done

efibootmgr -c -d "${disk}" -p "${part}" -L "${label}" -l "${loader}" \
    >/dev/null 2>&1 || fail "efibootmgr -c failed (disk=${disk} part=${part})"
new=$(efibootmgr 2>/dev/null | awk -v l="${label}" '{
    id = $1
    sub(/^Boot/, "", id)
    gsub(/\*/, "", id)
    if (length(id) == 4 && $2 == l) print id
}' | head -n 1)
[ -n "${new}" ] || fail "brand entry not present after -c"

order=$(efibootmgr 2>/dev/null | sed -n 's/^BootOrder: *//p')
rest=$(printf '%s\n' "${order}" | tr ',' '\n' | grep -vx "${new}" |
    grep -v '^$' | paste -sd, -)
if [ -n "${rest}" ]; then
    order=${new},${rest}
else
    order=${new}
fi
efibootmgr -o "${order}" >/dev/null 2>&1 || fail "set BootOrder failed"

first=$(efibootmgr 2>/dev/null | sed -n 's/^BootOrder: //p' | cut -d, -f1)
[ "${first}" = "${new}" ] || fail "BootOrder head=${first} want=${new}"

# anaconda 自己建的那条 "openEuler" 条目仍留在 NVRAM 里，固件菜单因此同时
# 列出两个名字，其中一个指向本机 ESP 上的上游目录。品牌化交付项要求菜单里
# 看不到上游名字，所以在 AirymaxOS 条目确认置顶之后清理，顺序不能颠倒：
# 先删后建，中途失败会让机器彻底没有可引导项。
#
# 两条判据都只读 efibootmgr -v 的实际内容，不按序号猜（序号在多次安装之间
# 不稳定）：一是路径为 \EFI\openEuler\ 且 HD() 的设备签名等于本机 ESP 的
# PARTUUID——只清自己的盘，接入的其它磁盘上的引导项不动；二是只有 VenHw()
# 而没有任何 .efi 路径的同名条目，这类空壳不带磁盘身份、选中即失败，是安装
# 器留下的死条目。
partuuid=$(lsblk -no PARTUUID "${dev}" 2>/dev/null) || partuuid=
pruned=0
for e in $(efibootmgr -v 2>/dev/null | awk \
    -v self="${new}" -v uuid="${partuuid}" '
    $2 == "openEuler" {
        id = $1
        sub(/^Boot/, "", id)
        gsub(/\*/, "", id)
        if (length(id) != 4 || id == self) next
        if ($0 ~ /\\EFI\\openEuler\\/) {
            if (uuid != "" && index($0, uuid) > 0) print id
            next
        }
        if ($0 !~ /\.efi/) print id
    }'); do
    efibootmgr -b "${e}" -B >/dev/null 2>&1 || :
    pruned=$((pruned + 1))
done

install -d -m 0755 "${state%/*}" || fail "create ${state%/*} failed"
printf 'entry=%s\nloader=%s\npruned=%s\n' "${new}" "${loader}" "${pruned}" \
    >"${state}" || fail "write ${state} failed"
note "entry=${new} disk=${disk} part=${part} order=${order} pruned=${pruned}"
