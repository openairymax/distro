# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# AirymaxOS 0.0.3（x86_64）工作站安装 kickstart — UKUI 桌面
#
# 桌面决策（2026-09-15）：OS 侧系统桌面 = UKUI 4.x（openKylin/openEuler 线）
# 隔离铁律：agent 控制面唯一入口 = Gateway（JSON-RPC 2.0），桌面自带
#           AI 控制面（KylinBot / kylin-ai*）一律排除，见 desktop/README.md
#
# 仓库结构（构建期闭包收割，缺任一项 UKUI 依赖即无法解析）：
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
#
# 本文件是构建期姿态：闭包收割需要上游仓库才能求解全部依赖。写入 ISO 的
# 安装期配方由 ks_spec.py install 投影得到——安装源改指载荷仓库、剔除全部
# 上游仓库，装机不触网。两份姿态同源，包清单不会漂移。
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
# tty0 在前，本地屏幕保留内核与 systemd 日志；串口留给无头验收与故障
# 恢复（install-test.sh 依赖 login: 哨兵）。只给串口时真机故障即黑屏，
# 现场无从取证。
bootloader --timeout=3 --append="console=tty0 console=ttyS0,115200 console=ttyAMA0,115200"
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

# ---- 包组 ----
# --nocore 关闭 anaconda 隐式追加的 @core（selection.core_group_enabled
# 默认 True）。载荷 comps 里没有上游 core 组，追加它会让安装器判定缺组，
# 转入「是否继续」交互问句，无头安装随即失败。基础用户空间改由
# airymax-core 组显式提供（comps/airymaxos-comps.xml），该组同时携带
# 安装器无条件需要的 grub2-tools 与 chrony；grub2 本体是架构相关的虚拟
# provide（x86_64 由 grub2-pc 提供），由 scripts/lib/closure.sh 按架构
# 随载荷收割。
%packages --nocore
# 基础用户空间；显式选择而不只靠环境携带，配方自身即可判定（C013）
@airymax-core
# 环境选择用 @^（pykickstart 环境语法）；@ 表示组
@^airymax-workstation
airymaxos-kernel
# 内核开发树（真机缺陷 D-09）：devel 子包提供 /usr/src/kernels/<release> 与
# /lib/modules/<release>/{build,source}，缺它则 dkms 与 out-of-tree 模块在
# 目标机上无法编译。Workstation 变体面向 agent 开发，必须自带该能力。
airymaxos-kernel-devel
# 系统编排单元与首启脚本（airymaxos-system）：随镜像落盘但不在此启用，
# 启用边界见 %post 注释
airymaxos-system

# 内核与发行版标识唯一：上游包组（@core 及其派生）携带 kernel、
# kernel-tools、openEuler-release 与 openEuler-latest-release，这些包与
# 本产品 airymaxos-kernel / airymaxos-release 争用同一组文件路径与虚拟
# 能力，不排除时 dnf 只能按求解顺序二选一，装机结果不可判定（K017 强制）。
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

# 失败必须可判读（DR-4）：标记带 reason=<断言名>，安装判定据此直接归因，
# 不必靠复现去猜是哪一条断言。
fail()
{
    trap - EXIT
    mark "AIRYMAX-INSTALL-FAIL reason=$1"
    exit 1
}

# 安装器的 chroot 内没有可用的 systemd 总线，单元文件类动词必须显式走
# --root 离线语义。判定不看命令退出码，而看落盘状态：不同 systemd 版本在
# chroot 内对 set-default 的退出码语义不一致，default.target 符号链接才是
# 唯一事实。
set_default()
{
    local want="$1"

    systemctl --root=/ set-default "${want}" ||
        mark "AIRYMAX-INSTALL-NOTE set-default rc=$?"
    [ "$(readlink -f /etc/systemd/system/default.target)" = \
        "/usr/lib/systemd/system/${want}" ] || fail default-target
}

# 账户状态只读 /etc/shadow 的哈希字段：安装器写口令走 chpasswd -e，哈希
# 原样落盘，锁定语义是前缀 !，禁用是 *。passwd -S 依赖 PAM 与本地化输出，
# 在 chroot 内的判读条件不如直接读文件确定。
acct_state()
{
    local pw

    pw=$(awk -F: -v n="$1" '$1 == n { print $2; exit }' /etc/shadow)
    case "${pw}" in
    '') printf 'missing' ;;
    '!'*) printf 'locked' ;;
    '*'*) printf 'nologin' ;;
    '$6$'*) printf 'sha512' ;;
    '$'*) printf 'hashed' ;;
    *) printf 'plain' ;;
    esac
}

# 断言与归因合一：失配时先打印状态分类（不含哈希），装机失败可直接判读。
acct_chk()
{
    local state

    state=$(acct_state "$1")
    [ "${state}" = sha512 ] && return 0
    mark "AIRYMAX-INSTALL-DIAG acct=$1 state=${state}"
    fail "$2"
}

# 1) 桌面隔离与 UKUI 策略由 airymaxos-release 包 %post 完成
#    （airymax-desktop.slice + 70-airymax-ukui-policy.sh，幂等）
rpm -q airymaxos-release >/dev/null 2>&1 || fail release-pkg
#    system-release 是引导配置生成的输入（anaconda 由它派生
#    GRUB_DISTRIBUTOR，grub-mkconfig 在 set -e 下 source 该文件），缺失即
#    不可引导，必须在装机段结束前暴露。
[ -r /etc/system-release ] || fail system-release

# 2) 系统编排单元必须随镜像落盘（OS-OPS-010 的包级前提）
rpm -q airymaxos-system >/dev/null 2>&1 || fail system-pkg

# 3) 账户自检：没有可登录账户的安装介质不具备「OS 能运行」的前提
acct_chk root root-account
acct_chk airymax airymax-account
# root 只承担首次控制台接管：登录后强制修改初始口令
chage -d 0 root || fail root-expire

# 4) 图形目标为默认（UKUI 会话经 lightdm 拉起）
set_default graphical.target

# 5) 启用边界由本段确定性收口。presets/ 是默认关闭策略：自有单元显式
#    disable，99-airymax-default-disable.preset 以 `disable *` 兜底，避免
#    任何带 [Install] 的第三方单元在 %systemd_post 里被隐式拉起。因此
#    开机要跑的单元必须在这里显式启用，且以 is-enabled 落盘状态为唯一
#    事实（--root 离线语义，chroot 内无总线）。preset-all 先于 enable
#    执行：它把 90-airymax.preset 的策略投影到现有单元，再叠加本清单。
systemctl --root=/ preset-all >/dev/null 2>&1 ||
    mark "AIRYMAX-INSTALL-NOTE preset-all rc=$?"
boot_set="lightdm.service airymax-desktop-ready.service
NetworkManager.service chronyd.service firewalld.service sshd.service"
for unit in ${boot_set}; do
    systemctl --root=/ enable "${unit}" >/dev/null 2>&1 || :
    state=$(systemctl --root=/ is-enabled "${unit}" 2>/dev/null || true)
    [ "${state}" = enabled ] || {
        mark "AIRYMAX-INSTALL-DIAG unit=${unit} state=${state}"
        fail "enable-${unit}"
    }
done

# 6) agentrt.target 的启用推迟到 daemon 二进制交付版本：
#    该 target 强依赖 12 个 /usr/sbin/*_d，0.0.3 尚未打包，提前 enable
#    会让每次冷启动进入 degraded，违背「OS 能正常运行」验收口径。
#    启用项与 airymaxos-services 同版本落地，届时在 boot_set 中补
#    agentrt.target（OS-OPS-010）。

# 7) 引导菜单分辨率（真机缺陷 D-07）。grub2-efi-x64 在 openEuler 上是预
#    编译的 grubx64.efi，装机时不会把 unicode.pf2 放进 ESP；00_header 生成
#    的 gfxmode 段落以 loadfont 成功为前置条件，字体缺失时整段被跳过，
#    菜单与 efifb 停在固件默认（B50 实测 800x600）。字体落盘后同一份
#    grub.cfg 即生效，无需删除或改写上游脚本。
grub_dir=
for d in /boot/efi/EFI/*; do
    if [ -f "${d}/grub.cfg" ]; then
        grub_dir="${d}"
        break
    fi
done
[ -n "${grub_dir}" ] || fail efi-grub-dir

# 分辨率只做引导期一次选择：1.x 无 KMS，运行期改不了模式，因此把候选
# 列表写在 /etc/default/grub，以 auto 兜底不认识的固件。
sed -i '/^GRUB_GFXMODE=/d' /etc/default/grub
printf 'GRUB_GFXMODE=1920x1080x32,1680x1050x32,1600x900x32,1280x1024x32,1024x768x32,auto\n' \
    >>/etc/default/grub

if [ -f /usr/share/grub/unicode.pf2 ]; then
    install -d -m 0755 "${grub_dir}/fonts"
    install -m 0644 /usr/share/grub/unicode.pf2 "${grub_dir}/fonts/unicode.pf2" ||
        fail efi-grub-font
    # chroot 内 os-prober 可能因缺 /dev 而告警；菜单本身由 10_linux 生成，
    # 因此 grub2-mkconfig 的非零退出只记录，判定交给下面的事实断言。
    grub2-mkconfig -o "${grub_dir}/grub.cfg" >/dev/null 2>&1 ||
        mark "AIRYMAX-INSTALL-NOTE grub2-mkconfig rc=$?"
    grep -q 'set gfxmode=' "${grub_dir}/grub.cfg" || fail efi-gfxmode
else
    mark "AIRYMAX-INSTALL-NOTE grub-font-source-missing"
fi

mark "AirymaxOS workstation install complete (baseline $(date -u +%Y%m%d))"
%end

# ---- 收尾 ----
# 显式状态命令让无人值守安装可判定结束；-no-reboot 下 QEMU 直接退出
reboot
