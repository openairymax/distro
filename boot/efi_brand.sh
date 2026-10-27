#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# efi_brand.sh — 在 ESP 内建立 AirymaxOS 引导项并置顶
#
# 调用者：airymaxos-efi-brand.service（首次启动跑一次，成功后由状态文件
#         短路）。不在安装期 chroot 里调用：anaconda 的 efivarfs 可写性
#         取决于宿主，静默失败会让品牌落空，而首启一定有 /sys/firmware/efi。
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
# 失败策略：NVRAM 写入受固件实现影响，出错时记一条 AIRYMAX-EFI-NOTE 并
# 退出 0，不写状态文件（下次启动重试），也不让 systemd 留下 failed 单元。
# ===========================================================================

esp=/boot/efi
label=AirymaxOS
state=/var/lib/airymaxos/efi-brand
dst=${esp}/EFI/airymaxos
loader='\EFI\airymaxos\shimx64.efi'

note()
{
    printf 'AIRYMAX-EFI-NOTE %s\n' "$*"
}

# 非 EFI 装机、ESP 未挂载、缺 efibootmgr：都不在本脚本能改写的范围内。
[ -d /sys/firmware/efi ] || exit 0
[ -d ${esp}/EFI ] || exit 0
command -v efibootmgr >/dev/null 2>&1 || exit 0
[ -e ${state} ] && exit 0

# 按目录找已签名的 shim，排除目标目录自身。
src=
for d in ${esp}/EFI/*; do
    [ -d "${d}" ] || continue
    [ "${d}" = "${dst}" ] && continue
    [ -f "${d}/shimx64.efi" ] || continue
    src=${d}
    break
done
if [ -z "${src}" ]; then
    note "no signed shim under ${esp}/EFI"
    exit 0
fi

install -d -m 0755 "${dst}" || {
    note "create ${dst} failed"
    exit 0
}
for f in shimx64.efi grubx64.efi mmx64.efi fbx64.efi grub.cfg grubenv; do
    [ -f "${src}/${f}" ] || continue
    install -m 0644 "${src}/${f}" "${dst}/${f}" || {
        note "copy ${f} failed"
        exit 0
    }
done
printf 'shimx64.efi,airymaxos,,%s\n' "${label}" >"${dst}/BOOTX64.CSV" || {
    note "write BOOTX64.CSV failed"
    exit 0
}

dev=$(findmnt -no SOURCE --target "${esp}" 2>/dev/null) || dev=
[ -n "${dev}" ] && dev=$(readlink -f "${dev}" 2>/dev/null)
if [ -z "${dev}" ]; then
    note "ESP source unresolved"
    exit 0
fi
disk=/dev/$(lsblk -no PKNAME "${dev}" 2>/dev/null) || disk=
part=
[ -r "/sys/class/block/${dev##*/}/partition" ] &&
    part=$(cat "/sys/class/block/${dev##*/}/partition")
if [ ! -b "${disk}" ] || [ -z "${part}" ]; then
    note "ESP geometry unknown (dev=${dev})"
    exit 0
fi

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
    >/dev/null 2>&1 || {
    note "efibootmgr -c failed (disk=${disk} part=${part})"
    exit 0
}
new=$(efibootmgr 2>/dev/null | awk -v l="${label}" '{
    id = $1
    sub(/^Boot/, "", id)
    gsub(/\*/, "", id)
    if (length(id) == 4 && $2 == l) print id
}' | head -n 1)
if [ -z "${new}" ]; then
    note "brand entry not present after -c"
    exit 0
fi

order=$(efibootmgr 2>/dev/null | sed -n 's/^BootOrder: *//p')
rest=$(printf '%s\n' "${order}" | tr ',' '\n' | grep -vx "${new}" |
    grep -v '^$' | paste -sd, -)
if [ -n "${rest}" ]; then
    order=${new},${rest}
else
    order=${new}
fi
efibootmgr -o "${order}" >/dev/null 2>&1 || {
    note "set BootOrder failed"
    exit 0
}

first=$(efibootmgr 2>/dev/null | sed -n 's/^BootOrder: //p' | cut -d, -f1)
if [ "${first}" != "${new}" ]; then
    note "BootOrder head=${first} want=${new}"
    exit 0
fi

install -d -m 0755 "${state%/*}"
printf 'entry=%s\nloader=%s\n' "${new}" "${loader}" >"${state}"
