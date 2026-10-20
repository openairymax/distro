# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# AirymaxOS 0.0.3（x86_64）工作站安装 kickstart — UKUI 桌面
#
# 桌面决策（2026-09-15）：OS 侧系统桌面 = UKUI 4.x（openKylin/openEuler 线）
# 隔离铁律：agent 控制面唯一入口 = Gateway（JSON-RPC 2.0），桌面自带
#           AI 控制面（KylinBot / kylin-ai*）一律排除，见 desktop/README.md
#
# 仓库结构（安装期闭包，缺任一项 UKUI 依赖即无法解析）：
#   airymaxos-offline          — ISO 内离线仓库（内核 + distro 包），cost 最低
#   openEuler OS               — 基础仓库（驱动/图形栈/工具链）
#   openEuler update           — 基础仓库勘误
#   openEuler EPOL/main        — 扩展仓库（ukui、lightdm、ukui-greeter）
#   openEuler EPOL/update/main — 扩展仓库勘误
#   openEuler everything       — 桌面闭包补齐（qt5-qtgraphicaleffects、
#                                qt5-qtquickcontrols 等仅发布于此），
#                                cost 最高，只作兜底不覆盖主仓库版本
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
repo --name=update     --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/update/$basearch/ --cost=100
repo --name=epol       --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/EPOL/main/$basearch/ --cost=100
repo --name=epol-update --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/EPOL/update/main/$basearch/ --cost=100
repo --name=everything --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP2/everything/$basearch/ --cost=2000
# 安装期仓库集合与运行期客户端配置（repo/airymax-os.repo）分属两层：
# 前者只求安装闭包可解析，后者是产品自有仓库（docs-linux/
# 190-distribution/01-rpm-packaging.md §5.2）。
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
# OS-OPS-009：口令只以 SHA-512 crypt 哈希落盘，禁止明文。0.0.3 的无人值守
# 安装没有交互建号环节，账户必须在安装结束后即可登录，否则 UKUI 与控制台
# 都无入口。root 的初始口令在 %post 中置为过期，首次登录强制修改；airymax
# 保持可用，保证 lightdm/UKUI 能直接进入桌面。
rootpw --iscrypted $6$airy003root0x01$WF29rbJ84L5jwK05P.Rs/EfkAjDBZmOtti6K29tIzd30tv29YlnNvYiZHK0QzPl4RBKlSiUshySWmYzgN3ybT0
user --name=airymax --groups=wheel --iscrypted --password=$6$airy003user0x01$s1JW7QjW0kiAW7B51kVB2hNsabAadz4G/h6yBDRvpWzwsV7NO7Kh3ChDjLtapHZ6HGl5WoqNKi.IAY7IT5yRc/

# ---- 服务 ----
# OS-OPS-010：安装器显式 enable 需要的单元，包自身 %post 不 enable。
# airymax-desktop-ready 在 graphical.target 下校验 lightdm 与 greeter 会话，
# 作为镜像 CI「桌面能进」的宿主机可判定证据（验收④）；minimal 剖面停留在
# multi-user.target，不涉及该单元。
# --enabled 的值是逗号分隔列表；用空格分隔会让第二个单元成为位置参数，
# anaconda 在解析 kickstart 阶段即终止安装。
services --enabled=lightdm,airymax-desktop-ready

# ---- 包组 ----
%packages
# 环境选择用 @^（pykickstart 环境语法）；@ 表示组
@^airymax-workstation
airymaxos-kernel
# 系统编排单元与首启脚本（airymaxos-system）：随镜像落盘但不在此启用，
# 启用边界见 %post 注释
airymaxos-system

# 内核与发行版标识唯一：anaconda 无条件把 @core 追加进安装清单
# （pyanaconda get_installation_specs），openEuler 的 @core mandatory 含
# kernel、default 含 kernel-tools，并携带 openEuler-release 与
# openEuler-latest-release。这些包与本产品 airymaxos-kernel /
# airymaxos-release 争用同一组文件路径与虚拟能力，不排除时 dnf 只能按
# 求解顺序二选一，装机结果不可判定（K017 强制）。
-kernel
-kernel-tools
-openEuler-release
-openEuler-latest-release

# 桌面自带 AI 控制面排除（KylinBot 及其 MCP 桌面控制栈）：
# agent 入口唯一 = Gateway（JSON-RPC 2.0），防止桌面成为第二控制面。
# 通配排除；实际包名清单在首个冻结点核对后固化到 desktop/README.md
-kylin-ai*
%end

# ---- 安装后脚本 ----
%post --log=/root/airymax-post.log
set -eu

# anaconda 把 --log 指定的文件作为本段的标准输出，脚本输出不会经过串口；
# 无头验收（scripts/install-test.sh）只读串口日志，因此完成与失败标记必须
# 显式写 /dev/console。内核按 console= 的注册顺序把 /dev/console 路由到
# 最后一个可用控制台：x86_64 为 ttyS0，aarch64 为 ttyAMA0。
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

# 本段任一断言失败时补发失败标记，装机的失败判定不必等到超时。
trap 'rc=$?; [ "${rc}" -eq 0 ] || mark "AIRYMAX-INSTALL-FAIL rc=${rc}"' EXIT

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

# 4) 账户自检：没有可登录账户的安装介质不具备「OS 能运行」的前提
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

# 5) agentrt.target 的启用推迟到 daemon 二进制交付版本：
#    该 target 强依赖 12 个 /usr/sbin/*_d，0.0.3 尚未打包，提前 enable
#    会让每次冷启动进入 degraded，违背「OS 能正常运行」验收口径。
#    启用项与 airymaxos-services 同版本落地，届时此处补
#    `systemctl enable agentrt.target`（OS-OPS-010）。
systemctl daemon-reload

mark "AirymaxOS workstation install complete (baseline $(date -u +%Y%m%d))"
%end

# ---- 收尾 ----
# 显式状态命令让无人值守安装可判定结束；-no-reboot 下 QEMU 直接退出
reboot
