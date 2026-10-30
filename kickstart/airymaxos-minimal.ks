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
#
# 本文件是构建期姿态：闭包收割需要上游仓库才能求解全部依赖。写入 ISO 的
# 安装期配方由 ks_spec.py install 投影得到——安装源改指载荷仓库、剔除全部
# 上游仓库，装机不触网。
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
# tty0 在前，本地屏幕保留内核与 systemd 日志；串口留给无头验收与故障
# 恢复（install-test.sh 依赖 login: 哨兵）。只给串口时真机故障即黑屏，
# 现场无从取证。
bootloader --timeout=3 --append="console=tty0 console=ttyS0,115200 console=ttyAMA0,115200"
clearpart --all --initlabel
autopart --type=plain --fstype=ext4

# ---- 网络 ----
network --bootproto=dhcp --activate --hostname=AIRYMAX_PC

# ---- 账户 ----
# OS-OPS-009：口令只以 SHA-512 crypt 哈希落盘，禁止明文。最小系统启用 sshd，
# 必须留下可远程接管的 wheel 账户，否则安装完成后无任何入口。
# 交付口径（0.0.3 决策）：Airymax 免密（ssh 侧由 airymaxos-release 的
# /etc/ssh/sshd_config.d/50-airymax-sshd.conf 放行空口令），root 交付口令
# 固定 00000000 且不强制首登改密。账户名与主机名的大小写是产品口径
# （Airymax / AIRYMAX_PC），取值理由见 airymaxos-workstation.ks 账户段。
rootpw --iscrypted $6$airy003root0x01$.lY1w9YA54iCwREQZCVZEoQ3xmCjcbkpWmWCrLciZeSNYA/T/6lkx4M2yFnhb13xBfbZLZQ64V01cSAkka1r30
user --name=Airymax --groups=wheel --iscrypted --password=$6$airy003user0x01$s1JW7QjW0kiAW7B51kVB2hNsabAadz4G/h6yBDRvpWzwsV7NO7Kh3ChDjLtapHZ6HGl5WoqNKi.IAY7IT5yRc/

# ---- 服务与防火墙 ----
services --enabled=sshd,chronyd
firewall --enabled --service=ssh
firstboot --disable

# ---- 包组 ----
# --nocore 关闭 anaconda 隐式追加的 @core：载荷 comps 不定义上游 core 组，
# 追加它会让安装器判定缺组并转入交互问句。基础用户空间（含 sshd、
# NetworkManager、chrony 与引导器）由 airymax-core 组显式提供；
# airymaxos-release 接管 system-release 与 /etc/os-release。
%packages --nocore
@airymax-core
airymaxos-kernel
airymaxos-release

# 内核与发行版标识唯一（与工作站剖面同口径）：上游包组携带上游 kernel /
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

# 失败必须可判读（DR-4）：标记带 reason=<断言名>，安装判定据此直接归因。
fail()
{
    trap - EXIT
    mark "AIRYMAX-INSTALL-FAIL reason=$1"
    exit 1
}

# 安装器的 chroot 内没有可用的 systemd 总线，单元文件类动词必须显式走
# --root 离线语义；判定看落盘状态，不看命令退出码。
set_default()
{
    local want="$1"

    systemctl --root=/ set-default "${want}" ||
        mark "AIRYMAX-INSTALL-NOTE set-default rc=$?"
    [ "$(readlink -f /etc/systemd/system/default.target)" = \
        "/usr/lib/systemd/system/${want}" ] || fail default-target
}

# 账户状态只读 /etc/shadow 的哈希字段：安装器写口令走 chpasswd -e，哈希原样
# 落盘，锁定语义是前缀 !，禁用是 *。空口令与「账户不存在」在 $2 上都是空串，
# awk 因此对存在的账户打印 @empty 哨兵，避免把免密账户误判为缺失。
# 与 workstation 剖面共用同一判读方式：passwd -S 依赖 PAM 与本地化输出，
# 在 chroot 内的判读条件不如直接读文件确定。
acct_state()
{
    local pw

    pw=$(awk -F: -v n="$1" \
        '$1 == n { print ($2 == "" ? "@empty" : $2); exit }' /etc/shadow)
    case "${pw}" in
    '') printf 'missing' ;;
    '@empty') printf 'empty' ;;
    '!'*) printf 'locked' ;;
    '*'*) printf 'nologin' ;;
    '$6$'*) printf 'sha512' ;;
    '$'*) printf 'hashed' ;;
    *) printf 'plain' ;;
    esac
}

# 断言与归因合一：失配时先打印状态分类（不含哈希），装机失败可直接判读。
acct_req()
{
    local state

    state=$(acct_state "$1")
    [ "${state}" = "$2" ] && return 0
    mark "AIRYMAX-INSTALL-DIAG acct=$1 state=${state} want=$2"
    fail "$3"
}

# sshd 与 chronyd 的启用由 services 指令唯一承担（服务清单 SSoT）。
# 发行版标识：上游 release 包被排除后，system-release 由本包唯一提供
rpm -q airymaxos-release >/dev/null 2>&1 || fail release-pkg
# system-release 缺失会让 anaconda 的 GRUB_DISTRIBUTOR 派生失败，grub-mkconfig
# 在 set -e 下中止，装机结果不可引导；在装机段结束前显式判负。
[ -r /etc/system-release ] || fail system-release

# 账户自检：没有可登录账户的安装介质不具备「OS 能运行」的前提
# root 交付为固定口令（sha512 哈希），Airymax 交付为空口令（empty）。
passwd -d Airymax || fail airymax-unlock
acct_req root sha512 root-account
acct_req Airymax empty airymax-account

set_default multi-user.target

mark "AirymaxOS minimal install complete (baseline $(date -u +%Y%m%d))"
%end

reboot
