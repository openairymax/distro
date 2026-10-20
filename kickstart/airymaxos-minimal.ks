# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# AirymaxOS 0.0.3（x86_64）最小安装 kickstart — 无桌面基线
#
# 用途：装机与镜像流水线的可判定基线。最小系统只承担三件事——
#   1. 可引导（AirymaxOS 内核 + bootloader + 基础用户空间）；
#   2. 可远程接管（sshd + DHCP 网络）；
#   3. 可时间同步（chronyd），为后续 rpm-ostree/agent 层提供可信时钟。
#
# 与工作站 kickstart 的差异：不含 UKUI、lightdm、输入法与桌面组；
# 一切桌面能力由 airymaxos-workstation.ks 或首启 bootstrap 叠加。
#
# 内核口径（M-15）：安装期显式请求 airymaxos-kernel，绝不落到上游
# kernel 包；该包由 scripts/build-desktop.sh 注入的离线仓库提供。
# ===========================================================================

text

lang zh_CN.UTF-8
keyboard us
timezone Asia/Shanghai --utc

# ---- 仓库 ----
# 离线仓库由 scripts/build-desktop.sh 注入 ISO 根 /airymax，cost 最低，
# 保证 airymaxos-kernel 及其 core/modules 子包优先于上游同名能力解析。
url --url=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/OS/$basearch/
repo --name=airymaxos-offline --baseurl=file:///run/install/repo/airymax/Packages --cost=1
repo --name=update --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/update/$basearch/ --cost=100

# ---- 引导与分区（UEFI + BIOS 双栈）----
# 串口控制台保留给无头验收与故障恢复（install-test.sh 依赖 login: 哨兵）
bootloader --timeout=3 --append="console=ttyS0,115200 console=ttyAMA0,115200"
clearpart --all --initlabel
autopart --type=plain --fstype=ext4

# ---- 网络 ----
network --bootproto=dhcp --activate --hostname=airymaxos-min

# ---- 账户 ----
# OS-OPS-009：口令只以 SHA-512 crypt 哈希落盘，禁止明文。最小系统启用 sshd，
# 必须留下可远程接管的 wheel 账户，否则安装完成后无任何入口。root 的初始
# 口令在 %post 中置为过期，首次登录强制修改。
rootpw --iscrypted $6$airy003root0x01$WF29rbJ84L5jwK05P.Rs/EfkAjDBZmOtti6K29tIzd30tv29YlnNvYiZHK0QzPl4RBKlSiUshySWmYzgN3ybT0
user --name=airymax --groups=wheel --iscrypted --password=$6$airy003user0x01$s1JW7QjW0kiAW7B51kVB2hNsabAadz4G/h6yBDRvpWzwsV7NO7Kh3ChDjLtapHZ6HGl5WoqNKi.IAY7IT5yRc/

# ---- 服务与防火墙 ----
services --enabled=sshd,chronyd
firewall --enabled --service=ssh
firstboot --disable

# ---- 包组 ----
%packages
# @core 是基础用户空间的唯一来源（本产品不复述上游清单）；airymaxos-release
# 接管 system-release 与 /etc/os-release，补上被排除的上游标识包。
@core
airymaxos-kernel
airymaxos-release
dnf
openssh-server
NetworkManager
chronyd
sudo

# 内核与发行版标识唯一（与工作站剖面同口径）：@core 携带上游 kernel /
# kernel-tools 与两个 openEuler-release 包，必须显式排除（K017 强制）。
-kernel
-kernel-tools
-openEuler-release
-openEuler-latest-release
%end

# ---- 安装后脚本 ----
%post --log=/root/airymax-post.log
set -eu

# --log 把本段输出重定向到目标系统文件，串口看不到任何内容；无头验收
# （scripts/install-test.sh）读串口日志，故标记必须显式写 /dev/console。
mark()
{
    local dev
    printf '%s\n' "$*"
    for dev in /dev/console /dev/ttyS0 /dev/ttyAMA0; do
        [ -w "${dev}" ] || continue
        if printf '%s\n' "$*" >"${dev}" 2>/dev/null; then
            break
        fi
    done
    return 0
}

trap 'rc=$?; [ "${rc}" -eq 0 ] || mark "AIRYMAX-INSTALL-FAIL rc=${rc}"' EXIT

systemctl set-default multi-user.target
systemctl enable sshd chronyd

# 发行版标识：上游 release 包被排除后，system-release 由本包唯一提供
rpm -q airymaxos-release >/dev/null 2>&1 || {
    echo "ERROR: airymaxos-release is not installed" >&2
    exit 1
}
# system-release 缺失会让 anaconda 的 GRUB_DISTRIBUTOR 派生失败，grub-mkconfig
# 在 set -e 下中止，装机结果不可引导；在装机段结束前显式判负。
[ -r /etc/system-release ] || {
    echo "ERROR: /etc/system-release is missing" >&2
    exit 1
}

# 账户自检：没有可登录账户的安装介质不具备「OS 能运行」的前提
[ "$(passwd -S root | awk '{print $2}')" = "P" ] || {
    echo "ERROR: root account is not usable" >&2
    exit 1
}
[ "$(passwd -S airymax | awk '{print $2}')" = "P" ] || {
    echo "ERROR: airymax account is not usable" >&2
    exit 1
}
# root 只承担首次控制台接管：登录后强制修改初始口令
chage -d 0 root

mark "AirymaxOS minimal install complete (baseline $(date -u +%Y%m%d))"
%end

reboot
