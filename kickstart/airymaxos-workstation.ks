# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# AirymaxOS 1.0（x86_64）工作站安装 kickstart — UKUI 桌面
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
# TODO: 替换为正式 URL；cost=10 使 kernel 等同名包优先解析自本项目仓库
repo --name=airymax-os --baseurl=https://repo.openairymax.org/airymaxos/1.0/x86_64/os/ --cost=10

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

# 2) 桌面 cgroup 降配：安装 airymax-desktop.slice（CPU/IO 权重 50，
#    与 agent 负载在调度面上隔离；详见 desktop/README.md）
# TODO: 该文件由 airymaxos-release 包部署到 /etc/systemd/system/ 后此步生效
if [ -f /usr/share/airymax/distro/desktop/airymax-desktop.slice ]; then
    install -m 0644 /usr/share/airymax/distro/desktop/airymax-desktop.slice \
        /etc/systemd/system/airymax-desktop.slice
    systemctl daemon-reload
fi

# 3) UKUI 策略脚本：屏蔽 kylin-ai* 服务、写入输入法环境变量
# TODO: 同上，随 airymaxos-release 包部署
if [ -x /usr/share/airymax/distro/desktop/70-airymax-ukui-policy.sh ]; then
    /usr/share/airymax/distro/desktop/70-airymax-ukui-policy.sh
fi

echo "AirymaxOS workstation install complete (baseline $(date -u +%Y%m%d))"
%end
