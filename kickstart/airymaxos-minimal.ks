# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# AirymaxOS 0.0.3（x86_64）最小安装 kickstart — 无桌面基线
#
# 用途：装机与镜像流水线的可判定基线。最小系统只承担三件事——
#   1. 可引导（kernel + bootloader + 基础用户空间）；
#   2. 可远程接管（sshd + DHCP 网络）；
#   3. 可时间同步（chronyd），为后续 rpm-ostree/agent 层提供可信时钟。
#
# 与工作站 kickstart 的差异：不含 UKUI、lightdm、输入法与桌面组；
# 一切桌面能力由 airymaxos-workstation.ks 或首启 bootstrap 叠加。
# ===========================================================================

text

lang zh_CN.UTF-8
keyboard us
timezone Asia/Shanghai --utc

# ---- 仓库 ----
url --url=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/OS/$basearch/
repo --name=update --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/update/$basearch/ --cost=100

# ---- 引导与分区（UEFI + BIOS 双栈）----
# 串口控制台保留给无头验收与故障恢复（install-test.sh 依赖 login: 哨兵）
bootloader --timeout=3 --append="console=ttyS0,115200 console=ttyAMA0,115200"
clearpart --all --initlabel
autopart --type=plain --fstype=ext4

# ---- 网络 ----
network --bootproto=dhcp --activate --hostname=airymaxos-min

# ---- 账户 ----
# 无人值守安装不留明文口令：root 锁定，运维经控制台或首启流程注入凭据
rootpw --lock

# ---- 服务与防火墙 ----
services --enabled=sshd,chronyd
firewall --enabled --service=ssh
firstboot --disable

# ---- 包组 ----
%packages --nobase
@core
kernel
dnf
openssh-server
NetworkManager
chronyd
sudo
%end

# ---- 安装后脚本 ----
%post --log=/root/airymax-post.log
set -eu

systemctl set-default multi-user.target
systemctl enable sshd chronyd

echo "AirymaxOS minimal install complete (baseline $(date -u +%Y%m%d))"
%end

reboot
