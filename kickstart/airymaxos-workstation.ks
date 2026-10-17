# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# AirymaxOS 0.0.3（x86_64）工作站安装 kickstart — UKUI 桌面
#
# 桌面决策（2026-09-15）：OS 侧系统桌面 = UKUI 4.x（openKylin/openEuler 线）
# 隔离铁律：agent 控制面唯一入口 = Gateway（JSON-RPC 2.0），桌面自带
#           AI 控制面（KylinBot / kylin-ai*）一律排除，见 desktop/README.md
#
# 仓库结构：
#   airymaxos-offline — ISO 内离线仓库（内核 + distro 包 + UKUI 闭包），cost 最低
#   openEuler OS      — 基础仓库（驱动/图形栈/工具链）
#   openEuler EPOL    — 扩展仓库
#
# 离线仓库由 scripts/build-desktop.sh 注入 ISO 根 /airymax，Anaconda 以
# file:// 直接读取；其 repodata 携带 comps 分组，@^airymax-workstation
# 才能解析。SP 分支以 lockfile 冻结点为准（当前模板按 SP2 书写）。
# ===========================================================================

# 安装界面用 text 以适配自动化；交互安装调试时可改为 graphical
text

lang zh_CN.UTF-8
keyboard us
timezone Asia/Shanghai --utc

# ---- 仓库 ----
url --url=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/OS/$basearch/
repo --name=update --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/update/$basearch/ --cost=100
repo --name=epol   --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/EPOL/main/$basearch/ --cost=100
# 仓库 URL / 段名与 repo/airymax-os.repo 保持同一口径
# （docs-linux/190-distribution/01-rpm-packaging.md §5.2）；
# 安装介质挂载点为 /run/install/repo（scripts/build-desktop.sh 注入）
repo --name=airymaxos-offline --baseurl=file:///run/install/repo/airymax/Packages --cost=1

# ---- 引导与分区（UEFI + BIOS 双栈）----
# 串口控制台保留给无头验收与故障恢复（install-test.sh 依赖 login: 哨兵）
bootloader --timeout=3 --append="console=ttyS0,115200 console=ttyAMA0,115200"
clearpart --all --initlabel
autopart --type=plain --fstype=ext4

# ---- 网络 ----
network --bootproto=dhcp --activate --hostname=airymaxos

# ---- 账户 ----
# 无人值守安装不留明文口令：root 锁定，user 同样锁定（口令由首启流程设置）
rootpw --lock
user --name=airymax --groups=wheel --lock --comment="AirymaxOS user"

# ---- 服务 ----
services --enabled=lightdm

# ---- 包组 ----
%packages
# 环境选择用 @^（pykickstart 环境语法）；@ 表示组
@^airymax-workstation
airymaxos-kernel
# 系统编排单元与首启脚本（airymaxos-system）：随镜像落盘但不在此启用，
# 启用边界见 %post 注释
airymaxos-system

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

# 3) 系统编排单元必须随镜像落盘（OS-OPS-010 的包级前提）
rpm -q airymaxos-system >/dev/null 2>&1 || {
    echo "ERROR: airymaxos-system is not installed" >&2
    exit 1
}

# 4) agentrt.target 的启用推迟到 daemon 二进制交付版本：
#    该 target 强依赖 12 个 /usr/sbin/*_d，0.0.3 尚未打包，提前 enable
#    会让每次冷启动进入 degraded，违背「OS 能正常运行」验收口径。
#    启用项与 airymaxos-services 同版本落地，届时此处补
#    `systemctl enable agentrt.target`（OS-OPS-010）。
systemctl daemon-reload

echo "AirymaxOS workstation install complete (baseline $(date -u +%Y%m%d))"
%end

# ---- 收尾 ----
# 显式状态命令让无人值守安装可判定结束；-no-reboot 下 QEMU 直接退出
reboot
