# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# AirymaxOS 0.0.4（x86_64）工作站安装 kickstart — UKUI 桌面
#
# 桌面决策（2026-09-15）：OS 侧系统桌面 = UKUI（openKylin/openEuler 线）；
#           0.0.4 取基底 24.03 LTS-SP3 EPOL/main 的 3.1 组件代
# 隔离铁律：agent 控制面唯一入口 = Gateway（JSON-RPC 2.0），桌面自带
#           AI 控制面（KylinBot / kylin-ai*）一律排除，见 desktop/README.md
#
# 仓库结构（构建期闭包收割，缺任一项 UKUI 依赖即无法解析）：
#   airymaxos-offline          — ISO 内离线仓库（内核 + distro 包），cost 最低
#   openEuler OS               — 基础仓库（驱动/图形栈/工具链）
#   openEuler update           — 基础仓库勘误
#   openEuler EPOL/main        — 扩展仓库（UKUI 组件、lightdm）
#   openEuler EPOL/update/main — 扩展仓库勘误
#   openEuler everything       — 桌面闭包补齐（qt5-qtgraphicaleffects、
#                                qt5-qtquickcontrols 等仅发布于此），
#                                cost 最高，只作兜底不覆盖主仓库版本
#
# 离线仓库由 scripts/build-desktop.sh 注入 ISO 根 /airymax，Anaconda 以
# file:// 直接读取；其 repodata 携带 comps 分组，@^airymax-workstation
# 才能解析。SP 分支以 lockfile 冻结点为准（当前模板按 SP3 书写）。
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
url --url=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/OS/$basearch/
repo --name=update     --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/update/$basearch/ --cost=100
repo --name=epol       --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/EPOL/main/$basearch/ --cost=100
repo --name=epol-update --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/EPOL/update/main/$basearch/ --cost=100
repo --name=everything --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/everything/$basearch/ --cost=2000
# 安装期仓库集合与运行期客户端配置（repo/airymax-os.repo）分属两层：
# 前者只求安装闭包可解析，后者是产品自有仓库（docs-linux/
# 190-distribution/01-rpm-packaging.md §5.2）。
# 安装介质挂载点为 /run/install/repo（scripts/build-desktop.sh 注入）
repo --name=airymaxos-offline --baseurl=file:///run/install/repo/airymax/Packages --cost=1

# ---- 引导与分区（UEFI + BIOS 双栈）----
# 两路控制台都要有：本地屏幕保留内核与 systemd 日志，串口留给无头验收与
# 故障恢复（install-test.sh 依赖 login: 哨兵）。只给串口时真机故障即黑屏，
# 现场无从取证；只给 tty0 时无头验收看不到任何输出。
#
# rhgb quiet 把本地屏幕交给 plymouth 启动画面，不再逐行滚动内核日志。
# quiet 只压到 loglevel 4：告警以上仍打印，全部消息照样进 journal 与
# ttyS0（安装验收依赖的 login: 哨兵来自 agetty，不受影响）。按 Esc 或
# 删掉这两个参数即可回到逐行日志，现场排障不需要重装。
#
# 顺序是语义：kernel 把 /dev/console 路由到命令行里最后一个 console=。
# 串口在前、tty0 在后，/dev/console 才是 VT；反过来（0.0.3 的写法）在
# 285H 上实测 /sys/class/tty/console/active = "tty0 ttyS0"，systemd-vconsole-setup
# 报 "Failed to lock /dev/console: Input/output error"，airymax-desktop-ready
# 因此每个启动周期都失败。安装器这一份只是首启用的副本，持久来源是
# boot/grub_args.sh 里的 consoles 常量，两处必须同序。
#
# console 集合按架构收敛（D-05）：本配方只产 x86_64，控制台就是 tty0 与
# 8250 串口 ttyS0。0.0.3 把 ARM64 的 ttyAMA0 一并写进命令行，内核在没有
# 该设备的机器上把 console= 注册成幽灵项，systemd-vconsole-setup 因此
# 失败；命令行的 console= 计数也从 2 变成 3。架构分支不允许留在这里——
# aarch64 由同目录的独立配方按自己的控制台集合产出。
#
# 菜单停留秒数与 boot/grub_args.sh 的 timeout 常量同源：安装器这一份只
# 覆盖首启，%post 会把它归一化为 1 秒。285H 冷启动实测 loader 段 3.78s，
# 其中 3s 是默认停留且不产出任何信息。两处不同步时，只要 grub2-mkconfig
# 再跑一次（内核升级、grub2 包升级）就回退到长停留。
bootloader --timeout=1 --append="console=ttyS0,115200 console=tty0 rhgb quiet"

# ---- 分区作用域（真机缺陷 D-33）----
# 安装器没有「自动」盘名：clearpart --all + autopart 会把每一块可用磁盘都
# 纳入自动布局。B50（2026-10-30）因此把 ESP 与 /boot 放到可插拔 U 盘、把
# 系统与数据分区放到 NVMe：拔盘即不可引导，且 --all 清空了全部接入磁盘。
#
# 选盘、布局与选盘记录只有一份实现（kickstart/disk-select.sh），构建期由
# tools/ks_embed.py 展开进下面的脚本段，本文件不再手抄规则。anaconda 的
# preScriptPass 先独立跑一遍 %pre 再解析其余指令，正是为了「脚本生成被
# include 的片段」；片段把作用域收敛到一块内置盘，系统分区（/）与数据
# 分区（/data）各自独立挂载，%post 与布局语义不变。
%pre --erroronfail --log=/tmp/airymax-disk.log
set -eu
# %airy-embed: install-lib.sh
# %airy-embed: disk-select.sh
airy_pre /tmp/airymax-disk.ks /tmp/airymax-disk.json

# ---- 安装期固件入口（0.0.4 首烧无网根因）----
# 安装器 live 环境没有 airymaxos-firmware 包，%posttrans 那条链不会跑；
# SP3 的固件树把 Intel 无线放在 intel/iwlwifi/ 且只留 .ucode.zst，驱动
# 按裸名请求即逐条 error -2，收束于 "no suitable firmware found"。设备
# 因此根本不出现在 anaconda 的 Devices found 里，network --activate 无
# 从建立连接，装完首启零联网（B50 与 285H 两次复现）。
#
# 规则只有一份：此处嵌入 distro/firmware/fw-flat.sh 的正文，与目标机
# %posttrans 跑的是同一实现（构建期由 tools/ks_embed.py 展开，不复制）。
# 判据是驱动声明的请求名，不写厂商目录，ARM/RISC-V 的无线同路径受益。
#
# %airy-embed: fw-flat.sh
fw_rc=0
fw_flat_main apply /usr/lib/firmware --list /tmp/airymax-fw.list \
    --modules "/usr/lib/modules/$(uname -r)" \
    >/tmp/airymax-fw.log 2>&1 || fw_rc=$?
while IFS= read -r fw_line; do
    airy_out "AIRYMAX-FW ${fw_line}"
done </tmp/airymax-fw.log
[ "${fw_rc}" -eq 0 ] || airy_out "AIRYMAX-FW-FAIL rc=${fw_rc}"

# 入口必须在驱动 probe 之前可见。安装器内核在 anaconda 启动前已 udev
# 枚举过一轮，iwlwifi 那时以 error -2 收场；补完链接必须让设备重新
# probe，否则没人再读固件。判据是 PCI 设备类 0x028000（网络/无线），
# 覆盖 iwlwifi、ath11k、mt76、rtw88 与 ARM/RISC-V 的 PCIe 无线。
nw_hit=0
for nw_dir in /sys/bus/pci/devices/*; do
    nw_cls=$(cat "${nw_dir}/class" 2>/dev/null) || continue
    [ "${nw_cls}" = "0x028000" ] || continue
    nw_dev=${nw_dir##*/}
    nw_hit=$(( nw_hit + 1 ))
    [ -L "${nw_dir}/driver" ] || continue
    printf '%s\n' "${nw_dev}" >"${nw_dir}/driver/unbind" 2>/dev/null || :
    nw_rc=0
    printf '%s\n' "${nw_dev}" >/sys/bus/pci/drivers_probe 2>/dev/null ||
        nw_rc=$?
    airy_out "AIRYMAX-FW-REPROBE dev=${nw_dev} rc=${nw_rc}"
done
[ "${nw_hit}" -gt 0 ] || airy_out "AIRYMAX-FW-NOPCI no-wireless-pci"
udevadm settle --timeout=30 2>/dev/null || :
nmcli radio wifi on >/dev/null 2>&1 || :
nmcli -t -f DEVICE,TYPE device 2>/dev/null | while IFS= read -r nw_line; do
    airy_out "AIRYMAX-NET ${nw_line}"
done
%end
%include /tmp/airymax-disk.ks

# ---- 网络 ----
# 主机名由安装器按产品口径直接落盘：airymax-pc 是合法 RFC 1123 标签，
# anaconda 不会改写。0.0.3 的产品名 AIRYMAX_PC 含下划线，B50 实测被静默
# 改写成 airymaxos，才需要 %post 手工写入并在内核层回写；0.0.4 起那条
# 回写链整体删除，判据是 /etc/hostname、hostname 与 hostnamectl --static
# 三者一致（冒烟 T8）。
network --bootproto=dhcp --activate --hostname=airymax-pc

# ---- 账户 ----
# OS-OPS-009：口令只以 SHA-512 crypt 哈希落盘，禁止明文。
# 交付口径（0.0.4 决策）：amuser 免密（本地座位自动登录 + SSH 空口令 +
# 控制台空口令），root 交付口令固定 00000000 且不再强制首登改密。安装没有
# 交互建号环节，账户必须在安装结束后即可登录，否则 UKUI 与控制台都无入口。
# 空口令由 %post 的 passwd -d 落地（见下），ssh 侧由 airymaxos-release
# 提供的 /etc/ssh/sshd_config.d/50-airymax-sshd.conf 放行。
#
# 账户名取小写 amuser（0.0.4 决策）：0.0.3 交付的 Airymax 含大写，shadow-utils
# 接受它（B50 实测 useradd AirymaxTmp 返回 0），但大小写敏感文件系统与各基底
# 版本的 NAME_REGEX 策略并不一致，账户自身与家目录的大小写会在现场分叉。
# 小写名不依赖这两处策略，此处是账户名的唯一事实源，座位、sudo 唯一规则与
# 冒烟断言都从它派生。主机名与此无关：airymax-pc 是独立的小写合法标签，
# 由上面的 network 指令直接落盘。
rootpw --iscrypted $6$airy003root0x01$.lY1w9YA54iCwREQZCVZEoQ3xmCjcbkpWmWCrLciZeSNYA/T/6lkx4M2yFnhb13xBfbZLZQ64V01cSAkka1r30
user --name=amuser --groups=wheel --iscrypted --password=$6$airy003user0x01$s1JW7QjW0kiAW7B51kVB2hNsabAadz4G/h6yBDRvpWzwsV7NO7Kh3ChDjLtapHZ6HGl5WoqNKi.IAY7IT5yRc/

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
# 固件闭包与内核 ABI 同源（FW-02）：无线与显卡的固件随内核 ABI 走，配方
# 显式列出，镜像里缺它就在装机事务阶段失败而不是等到开机没网。
airymaxos-firmware
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
# %airy-embed: install-lib.sh
# %airy-embed: disk-select.sh
# 目标根的挂载点是安装器的实现细节（anaconda 各版本在 /mnt/sysroot 与
# /mnt/sysimage 之间变化），按可执行文件实际位置判定，不猜环境变量。
root=
for c in "${ANA_INSTALL_PATH-}" "${INSTALL_ROOT-}" /mnt/sysroot /mnt/sysimage; do
    [ -n "${c}" ] && [ -d "${c}/etc" ] || continue
    root=${c}
    break
done

[ -n "${root}" ] || {
    airy_out "AIRYMAX-EFI-FAIL no-install-root"
    exit 1
}

# 选盘记录要随系统留下：本段的 /tmp 属于安装器，装完即消失。记录由共享
# 选盘器写，这里只把它复制进目标根；装机后 airy-disk status 以它为比对
# 基准，缺记录即无从判断安装器当时选了哪块盘。
export ANA_INSTALL_PATH="${root}"
airy_keep || exit 1
# 固件只决定 ESP 品牌化，不决定启动参数：参数落在 /etc/default/grub，两条
# 腿写法相同。把整段按固件提前退出，非 EFI 装机就永远拿不到 rhgb quiet 与
# 关闭的 os-prober，装完第一次 grub2-mkconfig 即退回逐行滚日志——BIOS 腿
# 的冒烟 T15 正是这么失败的。
uefi=0
if [ -d /sys/firmware/efi ]; then
    uefi=1
else
    airy_out "AIRYMAX-EFI-SKIP non-EFI install"
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
    airy_out "AIRYMAX-EFI-FAIL esp=${esp}"
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
        airy_fail "${tag}" missing-script "script=${script}"
    fi
    chroot "${root}" "${script}" --esp /boot/efi \
        --state "/var/lib/airymaxos/${name}" >"${log}" 2>&1 || rc=$?
    while IFS= read -r line; do
        airy_out "${line}"
    done <"${log}"
    if [ "${rc}" -ne 0 ]; then
        airy_fail "${tag}" script-rc \
            "rc=${rc} log=${logdir}/${name}.log"
    fi
    # 退出码 0 不足以证明落地：脚本在「已经是目标状态」时也返回 0，状态
    # 文件是唯一事实，缺它即视为未完成。
    [ -s "${root}/var/lib/airymaxos/${name}" ] || {
        airy_fail "${tag}" state-absent \
            "log=${logdir}/${name}.log"
    }
    airy_out "AIRYMAX-${tag}-OK"
}

step /usr/lib/airymaxos/boot/grub_args.sh grub-args GRUB
[ "${uefi}" -eq 0 ] || step /usr/lib/airymaxos/boot/efi_brand.sh efi-brand EFI
%end

%post --log=/root/airymax-post.log
set -eu
# %airy-embed: install-lib.sh
# %airy-embed: rtc-sync.sh
airy_trap INSTALL

# 1) 桌面隔离与 UKUI 策略由 airymaxos-release 包 %post 完成
#    （airymax-desktop.slice + 70-airymax-ukui-policy.sh，幂等）
airy_step 1 10 release
rpm -q airymaxos-release >/dev/null 2>&1 || airy_fail INSTALL release-pkg
#    system-release 是引导配置生成的输入（anaconda 由它派生
#    GRUB_DISTRIBUTOR，grub-mkconfig 在 set -e 下 source 该文件），缺失即
#    不可引导，必须在装机段结束前暴露。
[ -r /etc/system-release ] || airy_fail INSTALL system-release

# 2) 系统编排单元必须随镜像落盘（OS-OPS-010 的包级前提）
airy_step 2 10 system
rpm -q airymaxos-system >/dev/null 2>&1 || airy_fail INSTALL system-pkg
#    布局判定入口（M-36）：包在盘上不等于命令可用，两个剖面同一判据
test -x /usr/bin/airy-disk || airy_fail INSTALL airy-disk
# 重启后 / 与 /data 挂不挂得上只取决于 fstab（DISK-01 判据②）：按 /dev/sdX
# 写的源在装机当场可用，扩容或插拔改号后 /data 开机即失挂，而系统照常
# 起来。chroot 内的挂载点仍是 /mnt/sysroot/...，拓扑判定必然误杀，所以这
# 里只判 fstab：源必须是 UUID/LABEL/PARTUUID，且 /data 不得 noauto。
persist=$(airy-disk persist 2>&1) || {
    airy_out "AIRYMAX-DISK-DIAG persist=${persist}"
    airy_fail INSTALL disk-fstab
}
airy_out "AIRYMAX-DISK-OK ${persist}"
#    交付包集合随镜像落盘（V-15）：0.0.4 的包对账以这份集合为基准，装机后
#    任何增删都体现为 missing 或 extra，而不是悄悄改变系统构成。
rpm -qa --qf '%{NAME}\n' | LC_ALL=C sort -u >/etc/airymaxos-packages ||
    airy_fail INSTALL pkg-manifest
grep -qxF airymaxos-system /etc/airymaxos-packages ||
    airy_fail INSTALL pkg-manifest

# 3) 账户自检：没有可登录账户的安装介质不具备「OS 能运行」的前提
#    root 交付为固定口令（sha512 哈希），amuser 交付为空口令（empty）。
#    空口令只能完成登录，不能作为 sudo 的交互凭据，因此同一步还要确认
#    airymaxos-release 的 NOPASSWD 策略确实落盘：策略缺失时装机后没有
#    任何提权路径，而这一点在图形界面上看不出来。
airy_step 3 10 accounts
passwd -d amuser || airy_fail INSTALL airymax-unlock
acct_req root sha512 root-account
acct_req amuser empty airymax-account
sudoers=/etc/sudoers.d/90-airymax
[ -f "${sudoers}" ] || airy_fail INSTALL sudo-policy-missing
[ "$(stat -c %a "${sudoers}")" = 440 ] || airy_fail INSTALL sudo-policy-mode
grep -qxF 'amuser ALL=(ALL) NOPASSWD: ALL' "${sudoers}" ||
    airy_fail INSTALL sudo-policy-line
#    greeter 与锁屏的 PAM 栈第一条都是
#    pam_succeed_if.so user ingroup nopasswdlogin：账户不在该组时两者都会继续
#    走到 pam_unix 并弹出对话框。组由基础发行版预置，这里只补成员。
groupadd -f nopasswdlogin 2>/dev/null || :
usermod -aG nopasswdlogin amuser || airy_fail INSTALL airymax-group
id -nG amuser | tr ' ' '\n' | grep -qxF nopasswdlogin ||
    airy_fail INSTALL airymax-group
#    pulseaudio 首次启动先读 ~/.config/pulse/cookie，缺失时 authkey.c 先报
#    「Failed to open cookie file」再报「Failed to load authentication key」，
#    之后才现场生成，于是每台机器首启都留下四条告警（两个候选路径各两条）。
#    这是告警不是 err，不进 T23 计数，但真机首次开机就出现四条「密钥加载
#    失败」会掩盖真正的故障信号。cookie 只是本机 PA 守护进程与会话客户端
#    的共享密钥，装机时就地生成 256 字节随机值与 pulseaudio 自身的生成形态
#    一致，且不再经过失败路径。285H 实测：空 HOME 下起 PA 出四条告警，
#    预置 cookie 后为零。
#    目录级：GNU coreutils 的 install -d 只把 -o/-g/-m 作用于最后一个路径
#    分量，中间目录一律按 root:root 0755 建立（285H 上 coreutils 9.4 实测：
#    install -d -m 0700 -o amuser -g amuser /tmp/ip3/u/.config/pulse 得到
#    /tmp/ip3/u 与 /tmp/ip3/u/.config 皆为 root:root 0755）。0.0.4 首启
#    run 41972665005 的 T24 正是这样崩的：~/.config 属 root，uid 1000 的
#    会话写不了任何配置，goa-daemon 与 kglobalaccel5 报 Permission denied，
#    ukui-panel / ukui-kwin_x11 / ukui-settings-daemon 随即 core dump。
#    因此每一级显式建立，属主与模式都写死，不依赖 install 的中间目录语义。
home=/home/amuser
conf="${home}/.config"
pulse_dir="${conf}/pulse"
pulse_cookie="${pulse_dir}/cookie"
install -d -m 0755 -o amuser -g amuser "${conf}" ||
    airy_fail INSTALL config-dir
install -d -m 0700 -o amuser -g amuser "${pulse_dir}" ||
    airy_fail INSTALL pulse-cookie-dir
[ "$(stat -c %U:%G "${home}")" = amuser:amuser ] ||
    airy_fail INSTALL home-owner
[ "$(stat -c %U:%G "${conf}")" = amuser:amuser ] ||
    airy_fail INSTALL config-owner
if [ ! -s "${pulse_cookie}" ]; then
    head -c 256 /dev/urandom >"${pulse_cookie}" ||
        airy_fail INSTALL pulse-cookie-write
fi
chown amuser:amuser "${pulse_cookie}" || airy_fail INSTALL pulse-cookie-owner
chmod 0600 "${pulse_cookie}" || airy_fail INSTALL pulse-cookie-mode
[ "$(stat -c %s "${pulse_cookie}")" = 256 ] ||
    airy_fail INSTALL pulse-cookie-size
#    空口令账户配空闲锁屏只会制造口令框：锁屏策略必须与免密登录同口径落盘。
saver=/etc/dconf/db/local.d/00-airymax-screensaver
[ -f "${saver}" ] || airy_fail INSTALL screensaver-policy-missing
grep -qxF 'lock-enabled=false' "${saver}" ||
    airy_fail INSTALL screensaver-lock-off
#    策略文件在盘上不等于策略生效：系统库只有被 /etc/dconf/profile/user 的
#    system-db:local 引用、并由 dconf update 编译进 /etc/dconf/db/local 才
#    会进入每个会话。0.0.3 只交付了 local.d 源文件，profile 与编译产物都
#    靠基底包偶然提供，285H 上锁屏照常弹出。三个条件在这里一并收口。
#    这两处不能由自有包交付：/etc/dconf/profile/user 与 /etc/pam.d/* 均为
#    基底包所有，双属主会让 RPM 安装事务整体失败（plymouthd.conf 已踩过）。
profile=/etc/dconf/profile/user
mkdir -p /etc/dconf/profile
if [ ! -f "${profile}" ]; then
    printf 'user-db:user\nsystem-db:local\n' >"${profile}" ||
        airy_fail INSTALL screensaver-profile-write
elif ! grep -qxF 'system-db:local' "${profile}"; then
    printf 'system-db:local\n' >>"${profile}" ||
        airy_fail INSTALL screensaver-profile-write
fi
grep -qxF 'system-db:local' "${profile}" ||
    airy_fail INSTALL screensaver-profile-value
dconf update >/dev/null 2>&1 || airy_fail INSTALL screensaver-dconf-update
grep -qa 'lock-enabled' /etc/dconf/db/local ||
    airy_fail INSTALL screensaver-db-compiled

#    锁屏解锁失败的第二条根因：ukui-screensaver-checkpass 为 0755 root:root
#    时，PAM 的 account 阶段读不了 /etc/shadow，日志为
#    pam_unix(ukui-screensaver-qt:account): setuid failed: Operation not
#    permitted。补 setuid 位；同一 PAM 栈首行的 nopasswdlogin 直通（与
#    greeter 同口径）在文件缺这一行时补上，两处都做才不依赖单一前提。
checkpass=$(command -v ukui-screensaver-checkpass 2>/dev/null || true)
[ -n "${checkpass}" ] ||
    checkpass=/usr/lib/ukui-screensaver/ukui-screensaver-checkpass
if [ -x "${checkpass}" ]; then
    chmod 4755 "${checkpass}" || airy_fail INSTALL screensaver-checkpass-mode
    [ "$(stat -c %a "${checkpass}")" = 4755 ] ||
        airy_fail INSTALL screensaver-checkpass-mode
fi
for pam in /etc/pam.d/ukui-screensaver /etc/pam.d/ukui-screensaver-qt; do
    [ -f "${pam}" ] || continue
    grep -q 'pam_succeed_if.so user ingroup nopasswdlogin' "${pam}" && continue
    printf 'auth\tsufficient\tpam_succeed_if.so user ingroup nopasswdlogin\n' \
        >"${pam}.airy-new"
    cat "${pam}" >>"${pam}.airy-new" && mv "${pam}.airy-new" "${pam}" ||
        airy_fail INSTALL screensaver-pam-write
    grep -q 'pam_succeed_if.so user ingroup nopasswdlogin' "${pam}" ||
        airy_fail INSTALL screensaver-pam-value
done
#    启动日志默认只活在本次启动：openEuler 不预建 /var/log/journal，而
#    Storage=auto 在目录缺失时退化为 volatile，重启后「上一次启动到底做到
#    哪一步」再无证据可查。断言生效行而非文件存在，取值写错同样要拦下。
jconf=/etc/systemd/journald.conf.d/50-airymax-journald.conf
[ -f "${jconf}" ] || airy_fail INSTALL journald-persist-missing
grep -qxF 'Storage=persistent' "${jconf}" ||
    airy_fail INSTALL journald-persist-value

# 4) 图形目标为默认（UKUI 会话经 lightdm 拉起）
airy_step 4 10 target
set_default graphical.target
#    座位策略必须随包落盘：lightdm 在 conf.d 缺全部文件时仍会启动，只是退
#    回「列出用户 + 要口令」的默认行为，从服务状态上看不出差别，所以这里
#    按文件内容断言，而不是只认 lightdm.service 起没起。
seat=/etc/lightdm/lightdm.conf.d/50-airymax.conf
[ -f "${seat}" ] || airy_fail INSTALL lightdm-seat-missing
grep -qxF 'autologin-user=amuser' "${seat}" ||
    airy_fail INSTALL lightdm-autologin

# 5) 启用边界由本段确定性收口。presets/ 是默认关闭策略：自有单元显式
#    disable，99-airymax-default-disable.preset 以 `disable *` 兜底，避免
#    任何带 [Install] 的第三方单元在 %systemd_post 里被隐式拉起。因此
#    开机要跑的单元必须显式启用，且以 is-enabled 落盘状态为唯一事实
#    （--root 离线语义，chroot 内无总线）。preset-all 先于启用执行：
#    它把 90-airymax.preset 的策略投影到现有单元，再叠加清单。
#    清单与动作都只有一份：清单是随包落盘的 /usr/lib/airymaxos/boot-set，
#    动作是同一包里的 boot_set.sh，升级路径的 %posttrans 调用同一个脚本。
#    装机段不再另写清单与循环——两处各写一份时，新增一项治理只在其中一处
#    落地是必然发生的漂移，症状是某台机器治理静默缺席，从任何服务状态都
#    看不出来。每项为何收录见 boot-set 的头注释。
airy_step 5 10 units
boot_tool=/usr/lib/airymaxos/scripts/boot_set.sh
[ -x "${boot_tool}" ] || airy_fail INSTALL boot-set-tool
systemctl --root=/ preset-all >/dev/null 2>&1 ||
    airy_out "AIRYMAX-INSTALL-NOTE preset-all rc=$?"
boot_rc=0
"${boot_tool}" --root=/ >/tmp/airymax-boot-set.log 2>&1 || boot_rc=$?
while IFS= read -r line; do
    airy_out "AIRYMAX-BOOT-SET ${line}"
done </tmp/airymax-boot-set.log
[ "${boot_rc}" -eq 0 ] || airy_fail INSTALL boot-set-enable

# 6) EFI 品牌化已在上面 %post --nochroot 段完成：anaconda 用
#    GRUB_DISTRIBUTOR 命名 NVRAM 条目，装机后菜单与 BootOrder 都是
#    openEuler，故由 efi_brand.sh 新建 AirymaxOS 条目并置顶。该脚本不进
#    boot_set：它写 ESP 与 NVRAM，chroot 内不可见，首启又会被 SELinux
#    拦下，装机段是唯一可行时机。
airy_step 6 10 brand

# 7) agentrt.target 的启用推迟到 daemon 二进制交付版本：
#    该 target 强依赖 12 个 /usr/sbin/*_d，0.0.3 尚未打包，提前 enable
#    会让每次冷启动进入 degraded，违背「OS 能正常运行」验收口径。
#    启用项与 airymaxos-services 同版本落地，届时在 boot_set 中补
#    agentrt.target（OS-OPS-010）。
airy_step 7 10 agent

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
airy_step 8 10 grub
grub_args=/var/lib/airymaxos/grub-args
grub_cfg=$(awk -F= '$1 == "cfg" { print substr($0, 5); exit }' "${grub_args}")
[ -s "${grub_cfg}" ] || airy_fail INSTALL grub-cfg-missing
grub_dir=${grub_cfg%/*}

# 分辨率只做引导期一次选择：1.x 无 KMS，运行期改不了模式，因此把候选
# 列表写在 /etc/default/grub，以 auto 兜底不认识的固件。候选不写位深：
# 部分 GOP 实现拒绝全部带位深的候选后退回 auto，反而更低。
# 高分档前置（2880x1800 / 2560x1600 / 2240x1400）：GOP 取第一个固件支持
# 的模式，0.0.3 从 1920x1080 起选，285H 面板原生 2880x1800 从未被使用，
# 桌面因此停在 1920x1080。新候选串与 01_airymax_display 逐字一致。
sed -i '/^GRUB_GFXMODE=/d' /etc/default/grub
printf 'GRUB_GFXMODE=2880x1800,2560x1600,2240x1400,1920x1200,1920x1080,1680x1050,1600x900,1280x1024,1024x768,auto\n' \
    >>/etc/default/grub

# 内核必须沿用 grub 已设好的 GOP 模式（gfxpayload）。缺这一项时 10_linux
# 按默认值切回低分辨率，simpledrm/efifb 拿到的 fb0 就不是上面选中的模式，
# X 侧 xrandr 只有唯一模式可报，display_mode.sh 的阶梯全部落空。
sed -i '/^GRUB_GFXPAYLOAD_LINUX=/d' /etc/default/grub
printf 'GRUB_GFXPAYLOAD_LINUX=keep\n' >>/etc/default/grub

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
    airy_out "AIRYMAX-INSTALL-NOTE grub-font-absent"

# 01_airymax_display 排在 00_header 之后，负责无条件请求 gfxmode 与 gfxterm，
# 不依赖 00_header 里那个 loadfont 判定——那段判定在字体缺失时会静默跳过。
[ -x /etc/grub.d/01_airymax_display ] ||
    airy_fail INSTALL grub-display-fragment

# chroot 内 os-prober 可能因缺 /dev 而告警；菜单本身由 10_linux 生成，
# 因此 grub2-mkconfig 的非零退出只记录，判定交给下面的事实断言。
grub2-mkconfig -o "${grub_cfg}" >/dev/null 2>&1 ||
    airy_out "AIRYMAX-INSTALL-NOTE grub2-mkconfig rc=$?"
# 断言我们那段确实进了 cfg，而不是「cfg 里存在某条 gfxmode」：后者可能
# 只是 00_header 的条件分支，缺字体时整段消失，旧断言于是假绿。
grep -qxF '  set gfxmode=2880x1800,2560x1600,2240x1400,1920x1200,1920x1080,1680x1050,1600x900,1280x1024,1024x768,auto' \
    "${grub_cfg}" || airy_fail INSTALL grub-gfxmode
# gfxpayload 与 gfxmode 必须成对生效：只有前者正确时 fb0 才是所选模式。
grep -qxF '  set gfxpayload=keep' "${grub_cfg}" ||
    airy_fail INSTALL grub-gfxpayload
grep -qF '  terminal_output gfxterm' "${grub_cfg}" ||
    airy_fail INSTALL grub-gfxterm

# 9) 主机名：安装器已按 network --hostname 落盘，这里只做读回校验。0.0.4
#    的产品名是合法 RFC 1123 标签，不存在被改写的路径；静态名与运行期名
#    的一致性由冒烟 T8 在真实系统上判定。
airy_step 9 10 hostname
[ "$(cat /etc/hostname)" = airymax-pc ] || airy_fail INSTALL hostname-value

# 10) RTC 写入（D-34）：限时、只告警，不在关键路径上。停在
#     "update rtc with system clock" 时，串口最后一行就是
#     AIRYMAX-RTC-BEGIN，耗时与回读偏差记在随后的三行里。
airy_step 10 10 rtc
airy_rtc_sync

airy_out "AirymaxOS workstation install complete (baseline $(date -u +%Y%m%d))"
%end

# ---- 收尾 ----
# 显式状态命令让无人值守安装可判定结束；-no-reboot 下 QEMU 直接退出
reboot
