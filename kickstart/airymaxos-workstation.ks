# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# AirymaxOS 0.0.3（x86_64）工作站安装 kickstart — UKUI 桌面
#
# 桌面决策（2026-09-15）：OS 侧系统桌面 = UKUI 4.x（openKylin/openEuler 线）
# 隔离铁律：agent 控制面唯一入口 = Gateway（JSON-RPC 2.0），桌面自带
#           AI 控制面（KylinBot / kylin-ai*）一律排除，见 desktop/README.md
#
# 仓库结构：
#   airymax-os   — 本项目仓库（内核 RPM + distro comps + 系统层包），cost 最低
#   openEuler OS — 基础仓库（驱动/图形栈/工具链）
#   openEuler EPOL — 扩展仓库
#
# TODO（首个冻结点落地时）：
#   - 确认 airymax-os 仓库正式 URL 与签名 GPG key
#   - SP 分支以 lockfile 冻结点为准（当前模板按 SP2 书写）
# ===========================================================================

# 安装界面用 text 以适配自动化；交互安装调试时可改为 graphical
text

lang zh_CN.UTF-8
keyboard us
timezone Asia/Shanghai --utc

# ---- 仓库 ----
url --url=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/OS/x86_64/
repo --name=update --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/update/x86_64/ --cost=100
repo --name=epol   --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/EPOL/main/x86_64/ --cost=100
# 仓库 URL / 段名与 repo/airymax-os.repo 保持同一口径
# （docs-linux/190-distribution/01-rpm-packaging.md §5.2）
# TODO: 离线 compose 由镜像流水线以本地仓库覆盖该 URL
repo --name=airymaxos-base --baseurl=https://repo.airymaxos.org/0.0.3/BaseOS/x86_64/ --cost=10

# ---- 引导与分区（UEFI + BIOS 双栈）----
bootloader --timeout=3
clearpart --all --initlabel
autopart --type=plain --fstype=ext4

# ---- 网络 ----
network --bootproto=dhcp --activate --hostname=airymaxos

# ---- 账户 ----
# root 口令锁定；普通用户口令由安装界面/首启流程设置
rootpw --lock
user --name=airymax --groups=wheel --comment="AirymaxOS user"

# ---- 服务 ----
services --enabled=lightdm

# ---- 包组 ----
%packages
@airymax-workstation
kernel

# 桌面自带 AI 控制面排除（KylinBot 及其 MCP 桌面控制栈）：
# agent 入口唯一 = Gateway（JSON-RPC 2.0），防止桌面成为第二控制面。
# 通配排除；实际包名清单在首个冻结点核对后固化到 desktop/README.md
-kylin-ai*
%end

# ---- 安装后脚本 ----
%post --log=/root/airymax-post.log
set -eu

# 1) 图形目标为默认（UKUI 会话经 lightdm 拉起）
systemctl set-default graphical.target

# 2) 桌面隔离与 UKUI 策略由 airymaxos-release 包 %post 完成
#    （airymax-desktop.slice + 70-airymax-ukui-policy.sh，幂等）
rpm -q airymaxos-release >/dev/null 2>&1 || {
    echo "ERROR: airymaxos-release is not installed" >&2
    exit 1
}
systemctl daemon-reload

echo "AirymaxOS workstation install complete (baseline $(date -u +%Y%m%d))"
%end
