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
# rhgb quiet 把本地屏幕交给 plymouth 启动画面，不再逐行滚动内核日志。
# quiet 只压到 loglevel 4：告警以上仍打印，全部消息照样进 journal 与
# ttyS0（安装验收依赖的 login: 哨兵来自 agetty，不受影响）。按 Esc 或
# 删掉这两个参数即可回到逐行日志，现场排障不需要重装。
bootloader --timeout=3 --append="console=tty0 console=ttyS0,115200 console=ttyAMA0,115200 rhgb quiet"
clearpart --all --initlabel
autopart --type=plain --fstype=ext4

# ---- 网络 ----
network --bootproto=dhcp --activate --hostname=airymaxos

# ---- 账户 ----
# OS-OPS-009：口令只以 SHA-512 crypt 哈希落盘，禁止明文。
# 交付口径（0.0.3 决策）：airymax 免密（本地座位自动登录 + SSH 空口令 +
# 控制台空口令），root 交付口令固定 00000000 且不再强制首登改密。安装没有
# 交互建号环节，账户必须在安装结束后即可登录，否则 UKUI 与控制台都无入口。
# 空口令由 %post 的 passwd -d 落地（见下），ssh 侧由 airymaxos-release
# 提供的 /etc/ssh/sshd_config.d/50-airymax-sshd.conf 放行。
rootpw --iscrypted $6$airy003root0x01$.lY1w9YA54iCwREQZCVZEoQ3xmCjcbkpWmWCrLciZeSNYA/T/6lkx4M2yFnhb13xBfbZLZQ64V01cSAkka1r30
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
# 启动画面（bootloader 行的 rhgb）：plymouth 只被桌面闭包间接依赖，
# 闭包一调整就会静默消失，rhgb 随即退化为黑屏。显式列出，让「有画面」
# 成为配方自身可判定的性质。
plymouth

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
# 两个收尾步骤都必须在目标根内执行，且顺序固定：
#   1. grub_args.sh 把 rhgb quiet 与 GRUB_DISABLE_OS_PROBER 写进
#      /etc/default/grub 并重建 grub.cfg。bootloader --append 只作用于
#      安装器本次生成的 grub.cfg，anaconda 不写 /etc/default/grub，此后
#      任何一次 grub2-mkconfig 都会丢掉启动参数（真机 B50 已复现）。
#   2. efi_brand.sh 把 ESP 复制到 /EFI/airymaxos 并把 NVRAM 首项指向它。
#      品牌副本是 grub.cfg 的拷贝，必须拿到第 1 步生成的新版本，故排在其后。
# 两者都要写 ESP（dosfs_t）与 /dev /proc /sys，这些在 chroot 段的默认视图里
# 都不可见；首启 systemd 单元又会被 SELinux 拒绝（init_t 在 dosfs_t 上
# create，见 distro/boot/efi_brand.sh 头部）。这里在安装器环境把 efivarfs、
# ESP 与 /dev /proc /sys 挂进目标根，再在目标根内执行：efibootmgr、
# findmnt、lsblk 因此都由被测系统提供，与真机环境一致，缺包会在装机时暴露
# 而不是被 skip 吞掉（验收 run 40587295652：安装器环境没有 efibootmgr，
# 旧实现走 skip，串口却仍报 OK）。
#
# 失败即终止安装（--erroronfail）：品牌与 BootOrder 是可验收的交付项，
# 静默降级只会把问题推迟到验收现场。脚本按「环境不适用」与「在范围内
# 失败」分码，BIOS 装机因此不会被误伤。
%post --nochroot --erroronfail --log=/mnt/sysroot/root/airymax-efi.log
set -eu
# 目标根的挂载点是安装器的实现细节（anaconda 各版本在 /mnt/sysroot 与
# /mnt/sysimage 之间变化），按可执行文件实际位置判定，不猜环境变量。
root=
for c in "${ANA_INSTALL_PATH-}" "${INSTALL_ROOT-}" /mnt/sysroot /mnt/sysimage; do
    [ -n "${c}" ] && [ -d "${c}/etc" ] || continue
    root=${c}
    break
done

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

[ -n "${root}" ] || {
    mark "AIRYMAX-EFI-FAIL no-install-root"
    exit 1
}
# 固件只决定 ESP 品牌化，不决定启动参数：参数落在 /etc/default/grub，两条
# 腿写法相同。把整段按固件提前退出，非 EFI 装机就永远拿不到 rhgb quiet 与
# 关闭的 os-prober，装完第一次 grub2-mkconfig 即退回逐行滚日志——BIOS 腿
# 的冒烟 T15 正是这么失败的。
uefi=0
if [ -d /sys/firmware/efi ]; then
    uefi=1
else
    mark "AIRYMAX-EFI-SKIP non-EFI install"
fi

# 段内挂载的目录在退出时全部还回去；rbind 把宿主的 /dev /proc /sys 视图
# 覆盖到目标根，目标根原有内容在 umount -R 后自动恢复。
owned=
umount_all()
{
    local d
    for d in ${owned}; do
        umount -R "${d}" 2>/dev/null || :
    done
    owned=
}
trap umount_all EXIT

# efivars 与 ESP 都只在 anaconda 的引导装载程序阶段内是挂载的，装包与
# %post 之间会被卸载；这里各自按需挂回，不依赖安装器的挂载时序。
esp=${root}/boot/efi
if [ "${uefi}" -eq 1 ]; then
    mountpoint -q /sys/firmware/efi/efivars ||
        mount -t efivarfs efivarfs /sys/firmware/efi/efivars 2>/dev/null || :
    if ! mountpoint -q "${esp}"; then
        mkdir -p "${esp}"
        src=$(awk '$2 == "/boot/efi" { print $1; exit }' \
            "${root}/etc/fstab" 2>/dev/null) || src=
        if [ -n "${src}" ] && mount "${src}" "${esp}" 2>/dev/null; then
            owned="${owned} ${esp}"
        fi
    fi
fi
for d in /dev /proc /sys; do
    mountpoint -q "${root}${d}" && continue
    mount --rbind "${d}" "${root}${d}" || continue
    owned="${owned} ${root}${d}"
done

[ "${uefi}" -eq 0 ] || mountpoint -q "${esp}" || {
    mark "AIRYMAX-EFI-FAIL esp=${esp}"
    exit 1
}

# 日志落在目标根内：--log 指定的文件在安装器环境，装机结束即随安装器消失，
# 只有这里才是验收与事后归因都能读到的位置。
logdir=/var/log/airymax
install -d -m 0755 "${root}${logdir}"

# 两个收尾脚本的调用形状完全一致：chroot 进目标根、同一个 --esp、状态文件
# 落在 /var/lib/airymaxos/<name>、日志落到 /var/log/airymax/<name>.log、串口
# 标记 AIRYMAX-<tag>-OK/FAIL。抽成执行器，调用点只描述差异。
step()
{
    local script="$1" name="$2" tag="$3" log rc=0

    log="${root}${logdir}/${name}.log"
    if [ ! -x "${root}${script}" ]; then
        mark "AIRYMAX-${tag}-FAIL missing ${script}"
        exit 1
    fi
    chroot "${root}" "${script}" --esp /boot/efi \
        --state "/var/lib/airymaxos/${name}" >"${log}" 2>&1 || rc=$?
    while IFS= read -r line; do
        mark "${line}"
    done <"${log}"
    if [ "${rc}" -ne 0 ]; then
        mark "AIRYMAX-${tag}-FAIL rc=${rc} log=${logdir}/${name}.log"
        exit 1
    fi
    # 退出码 0 不足以证明落地：脚本在「已经是目标状态」时也返回 0，状态
    # 文件是唯一事实，缺它即视为未完成。
    [ -s "${root}/var/lib/airymaxos/${name}" ] || {
        mark "AIRYMAX-${tag}-FAIL state-absent log=${logdir}/${name}.log"
        exit 1
    }
    mark "AIRYMAX-${tag}-OK"
}

step /usr/lib/airymaxos/boot/grub_args.sh grub-args GRUB
[ "${uefi}" -eq 0 ] || step /usr/lib/airymaxos/boot/efi_brand.sh efi-brand EFI
%end

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
# 原样落盘，锁定语义是前缀 !，禁用是 *。空口令与「账户不存在」在 $2 上都是
# 空串，awk 因此对存在的账户打印 @empty 哨兵，避免把免密账户误判为缺失。
# passwd -S 依赖 PAM 与本地化输出，在 chroot 内的判读条件不如直接读文件确定。
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
#    root 交付为固定口令（sha512 哈希），airymax 交付为空口令（empty）。
#    空口令只能完成登录，不能作为 sudo 的交互凭据，因此同一步还要确认
#    airymaxos-release 的 NOPASSWD 策略确实落盘：策略缺失时装机后没有
#    任何提权路径，而这一点在图形界面上看不出来。
passwd -d airymax || fail airymax-unlock
acct_req root sha512 root-account
acct_req airymax empty airymax-account
sudoers=/etc/sudoers.d/90-airymax
[ -f "${sudoers}" ] || fail sudo-policy-missing
[ "$(stat -c %a "${sudoers}")" = 440 ] || fail sudo-policy-mode
grep -qxF 'airymax ALL=(ALL) NOPASSWD: ALL' "${sudoers}" || fail sudo-policy-line
#    greeter 与锁屏的 PAM 栈第一条都是
#    pam_succeed_if.so user ingroup nopasswdlogin：账户不在该组时两者都会继续
#    走到 pam_unix 并弹出对话框。组由基础发行版预置，这里只补成员。
groupadd -f nopasswdlogin 2>/dev/null || :
usermod -aG nopasswdlogin airymax || fail airymax-group
id -nG airymax | tr ' ' '\n' | grep -qxF nopasswdlogin ||
    fail airymax-group
#    空口令账户配空闲锁屏只会制造口令框：锁屏策略必须与免密登录同口径落盘。
saver=/etc/dconf/db/local.d/00-airymax-screensaver
[ -f "${saver}" ] || fail screensaver-policy-missing
grep -qxF 'lock-enabled=false' "${saver}" || fail screensaver-lock-off
#    启动日志默认只活在本次启动：openEuler 不预建 /var/log/journal，而
#    Storage=auto 在目录缺失时退化为 volatile，重启后「上一次启动到底做到
#    哪一步」再无证据可查。断言生效行而非文件存在，取值写错同样要拦下。
jconf=/etc/systemd/journald.conf.d/50-airymax-journald.conf
[ -f "${jconf}" ] || fail journald-persist-missing
grep -qxF 'Storage=persistent' "${jconf}" || fail journald-persist-value

# 4) 图形目标为默认（UKUI 会话经 lightdm 拉起）
set_default graphical.target
#    座位策略必须随包落盘：lightdm 在 conf.d 缺全部文件时仍会启动，只是退
#    回「列出用户 + 要口令」的默认行为，从服务状态上看不出差别，所以这里
#    按文件内容断言，而不是只认 lightdm.service 起没起。
seat=/etc/lightdm/lightdm.conf.d/50-airymax.conf
[ -f "${seat}" ] || fail lightdm-seat-missing
grep -qxF 'autologin-user=airymax' "${seat}" || fail lightdm-autologin

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

# 6) EFI 品牌化已在上面 %post --nochroot 段完成：anaconda 用
#    GRUB_DISTRIBUTOR 命名 NVRAM 条目，装机后菜单与 BootOrder 都是
#    openEuler，故由 efi_brand.sh 新建 AirymaxOS 条目并置顶。该脚本不进
#    boot_set：它写 ESP 与 NVRAM，chroot 内不可见，首启又会被 SELinux
#    拦下，装机段是唯一可行时机。

# 7) agentrt.target 的启用推迟到 daemon 二进制交付版本：
#    该 target 强依赖 12 个 /usr/sbin/*_d，0.0.3 尚未打包，提前 enable
#    会让每次冷启动进入 degraded，违背「OS 能正常运行」验收口径。
#    启用项与 airymaxos-services 同版本落地，届时在 boot_set 中补
#    agentrt.target（OS-OPS-010）。

# 8) 引导菜单分辨率（真机缺陷 D-07）。openEuler 用预编译的 grubx64.efi，
#    装机不把 unicode.pf2 放进 ESP；00_header 生成的 gfxmode 段落以
#    loadfont 成功为前置条件，字体缺失时整段被跳过，菜单与 efifb 停在固件
#    默认（B50 实测 800x600）。字体落位与无条件 gfxmode 已由上一段的
#    grub_args.sh 完成：它按生效配置所在目录放字体（那里就是 grubx64.efi
#    内嵌的 prefix），并由 01_airymax_display 无条件重设 gfxmode 与 gfxterm，
#    efifb 继承 grub 设好的 GOP 模式，X 才有可用的 fbdev 分辨率。
#
#    生效配置不在这里重新推断，直接读 grub_args.sh 的状态文件：它跟随
#    /etc/grub2-efi.cfg、/etc/grub2.cfg 找到 grub 真正加载的那份（UEFI 在
#    ESP 的发行版目录，BIOS 在 /boot/grub2，两腿都由发行版自己声明）。
#    0.0.3 装机曾按 /boot/grub2 是否存在再 glob EFI/* 取名，字体与重建都
#    落进从未被加载的品牌副本，而 grubx64.efi 内嵌 prefix 指向别的目录，
#    串口与 cfg 断言全绿、屏幕仍是 800x600（D-31）。
grub_args=/var/lib/airymaxos/grub-args
grub_cfg=$(awk -F= '$1 == "cfg" { print substr($0, 5); exit }' "${grub_args}")
[ -s "${grub_cfg}" ] || fail grub-cfg-missing
grub_dir=${grub_cfg%/*}

# 分辨率只做引导期一次选择：1.x 无 KMS，运行期改不了模式，因此把候选
# 列表写在 /etc/default/grub，以 auto 兜底不认识的固件。候选不写位深：
# 部分 GOP 实现拒绝全部带位深的候选后退回 auto，反而更低。
sed -i '/^GRUB_GFXMODE=/d' /etc/default/grub
printf 'GRUB_GFXMODE=1920x1080,1680x1050,1600x900,1280x1024,1024x768,auto\n' \
    >>/etc/default/grub

# 输出终端必须含 gfxterm，否则 00_header 不生成 gfxmode 段落，上面的字体
# 与 GFXMODE 都无从生效（D-28）。openEuler 的 grub2-mkconfig 在 212-217
# 行有发行版补丁：只要旧变量 GRUB_TERMINAL 非空，就用它无条件覆盖
# GRUB_TERMINAL_INPUT/OUTPUT。anaconda 写下的 GRUB_TERMINAL="serial
# console" 因此会冲掉这里设的 GRUB_TERMINAL_OUTPUT，cfg 里依旧没有
# gfxmode（已用 chroot sh -x 复现：OUTPUT 被改回 "serial console"）。
# 唯一有效做法是改旧变量本身：mkconfig 会据此推出 INPUT="serial console"、
# OUTPUT="console serial gfxterm"，与 B50 宿主可用配置一致。
sed -i '/^GRUB_TERMINAL=/d;/^GRUB_TERMINAL_OUTPUT=/d' /etc/default/grub
printf 'GRUB_TERMINAL="console serial gfxterm"\n' >>/etc/default/grub

# 字体已由 grub_args.sh 放进 ${grub_dir}/fonts。这里只核验事实：缺字体时
# gfxterm 初始化失败、GOP 模式不会切换，屏幕仍停在固件默认；但它不至于让
# 装机失败（X 侧还有 fbdev 兜底），故只 note。
[ -f "${grub_dir}/fonts/unicode.pf2" ] ||
    mark "AIRYMAX-INSTALL-NOTE grub-font-absent"

# 01_airymax_display 排在 00_header 之后，负责无条件请求 gfxmode 与 gfxterm，
# 不依赖 00_header 里那个 loadfont 判定——那段判定在字体缺失时会静默跳过。
[ -x /etc/grub.d/01_airymax_display ] || fail grub-display-fragment

# chroot 内 os-prober 可能因缺 /dev 而告警；菜单本身由 10_linux 生成，
# 因此 grub2-mkconfig 的非零退出只记录，判定交给下面的事实断言。
grub2-mkconfig -o "${grub_cfg}" >/dev/null 2>&1 ||
    mark "AIRYMAX-INSTALL-NOTE grub2-mkconfig rc=$?"
# 断言我们那段确实进了 cfg，而不是「cfg 里存在某条 gfxmode」：后者可能
# 只是 00_header 的条件分支，缺字体时整段消失，旧断言于是假绿。
grep -qxF '  set gfxmode=1920x1080,1680x1050,1600x900,1280x1024,1024x768,auto' \
    "${grub_cfg}" || fail grub-gfxmode
grep -qF '  terminal_output gfxterm' "${grub_cfg}" || fail grub-gfxterm

mark "AirymaxOS workstation install complete (baseline $(date -u +%Y%m%d))"
%end

# ---- 收尾 ----
# 显式状态命令让无人值守安装可判定结束；-no-reboot 下 QEMU 直接退出
reboot
