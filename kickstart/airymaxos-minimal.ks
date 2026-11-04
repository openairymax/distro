# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# AirymaxOS 0.0.4（x86_64）最小安装 kickstart — 无桌面基线
#
# 用途：装机与镜像流水线的可判定基线。最小系统承担三件事——
#   1. 可引导（AirymaxOS 内核 + bootloader + 基础用户空间）；
#   2. 可远程接管（sshd + DHCP 网络）；
#   3. 可时间同步（chronyd），为后续 rpm-ostree/agent 层提供可信时钟。
# 另随镜像落盘 airymaxos-system：编排单元按 preset 保持 disabled，但
# airy-disk 必须在场——装机后的 / 与 /data 布局只有它能取证（M-36）。
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
url --url=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/OS/$basearch/
repo --name=airymaxos-offline --baseurl=file:///run/install/repo/airymax/Packages --cost=1
repo --name=update --baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/update/$basearch/ --cost=100

# ---- 引导与分区（UEFI + BIOS 双栈）----
# 顺序是语义：kernel 把 /dev/console 路由到命令行里最后一个 console=。
# 串口在前、tty0 在后，/dev/console 才是 VT——反过来会让
# systemd-vconsole-setup 锁不住 /dev/console，桌面就绪门禁随之失败（285H
# 实测）。这里的 --append 只覆盖首次安装；%post 末尾由 grub_args.sh 把同一
# 集合写进 /etc/default/grub，后续每次重建才不丢参数（D-30）。工作站配方
# 同序。
#
# console 集合按架构收敛（D-05）：x86_64 为 tty0 + ttyS0，ARM64 的 ttyAMA0
# 不得出现在本配方——无该设备时 console= 注册成幽灵项并让
# systemd-vconsole-setup 失败。aarch64 配方各自持有自己的控制台集合。
bootloader --timeout=3 --append="console=ttyS0,115200 console=tty0"

# 选盘、布局与选盘记录只有一份实现（kickstart/disk-select.sh），构建期由
# tools/ks_embed.py 展开进下面的脚本段。clearpart --all 加 autopart 会把
# 每一块接入的磁盘都纳入布局，B50（2026-10-30）因此把 ESP 与 /boot 建到
# 可插拔 U 盘上（D-33）；改由 %pre 依现场选出唯一内置盘并逐项 --ondisk
# 钉住，两个剖面走同一条路径。
%pre --erroronfail --log=/tmp/airymax-disk.log
set -eu
# %airy-embed: install-lib.sh
# %airy-embed: disk-select.sh
airy_pre /tmp/airymax-disk.ks /tmp/airymax-disk.json
%end
%include /tmp/airymax-disk.ks

# ---- 网络 ----
network --bootproto=dhcp --activate --hostname=airymax-pc

# ---- 账户 ----
# OS-OPS-009：口令只以 SHA-512 crypt 哈希落盘，禁止明文。最小系统启用 sshd，
# 必须留下可远程接管的 wheel 账户，否则安装完成后无任何入口。
# 交付口径（0.0.4 决策）：amuser 免密（ssh 侧由 airymaxos-release 的
# /etc/ssh/sshd_config.d/50-airymax-sshd.conf 放行空口令），root 交付口令
# 固定 00000000 且不强制首登改密。账户名取小写，取值理由与唯一事实源见
# airymaxos-workstation.ks 账户段；主机名 airymax-pc 由上面的 network
# 指令直接落盘，与账户名无关。
rootpw --iscrypted $6$airy003root0x01$.lY1w9YA54iCwREQZCVZEoQ3xmCjcbkpWmWCrLciZeSNYA/T/6lkx4M2yFnhb13xBfbZLZQ64V01cSAkka1r30
user --name=amuser --groups=wheel --iscrypted --password=$6$airy003user0x01$s1JW7QjW0kiAW7B51kVB2hNsabAadz4G/h6yBDRvpWzwsV7NO7Kh3ChDjLtapHZ6HGl5WoqNKi.IAY7IT5yRc/

# ---- 服务与防火墙 ----
# 启用清单只有一份：随 airymaxos-system 落盘的 /usr/lib/airymaxos/boot-set，
# 由同包的 boot_set.sh 在 %post 内以 --root 离线语义落位。不用 anaconda 的
# services 指令另列一份：99-airymax-default-disable.preset 的 `disable *`
# 会在装包时把 sshd、NetworkManager 一并关掉，两处各写一份清单时新增一项
# 治理只在其中一处落地是必然发生的漂移。上面已声明 DHCP 引导，单元不启用
# 则装完无 DHCP、sshd 也就没有可达路径；airymax-update-check.timer 与电源
# 热治理同理，装完即静默失效且从服务状态上看不出来。
# 本剖面没有桌面，lightdm 与 airymax-desktop-ready 不在位，boot_set.sh 把
# 它们记为 state=absent 而不是失败——清单跨剖面共用，缺项是剖面的正常差异。
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
# 编排单元与磁盘工具（airymaxos-system）：与工作站剖面同一包，两个剖面
# 因此走同一条布局判读代码路径；单元启用边界由 preset 唯一决定，安装段
# 不启用任何 agentrt 单元。
airymaxos-system

# 内核与发行版标识唯一（与工作站剖面同口径）：上游包组携带上游 kernel /
# kernel-tools 与两个 openEuler-release 包，必须显式排除（K017 强制）。
-kernel
-kernel-tools
-openEuler-release
-openEuler-latest-release
%end

# ---- 安装后脚本 ----
# 选盘记录随系统留下：%pre 的 /tmp 属于安装器，装完即消失，装机后
# airy-disk status 要以它作为比对基准。本段在目标根就绪后复制记录，缺失或
# 写失败即判负，不留「装完但无从核对」的状态。
%post --nochroot --erroronfail --log=/mnt/sysroot/root/airymax-disk.log
set -eu
# %airy-embed: install-lib.sh
# %airy-embed: disk-select.sh
airy_keep
%end

%post --log=/root/airymax-post.log
set -eu
# %airy-embed: install-lib.sh
# %airy-embed: rtc-sync.sh
airy_trap INSTALL

# sshd、chronyd、NetworkManager 与治理单元的启用由 boot_set.sh 唯一承担
# （服务清单 SSoT，见上文「服务与防火墙」段）。
# 发行版标识：上游 release 包被排除后，system-release 由本包唯一提供
airy_step 1 8 release
rpm -q airymaxos-release >/dev/null 2>&1 ||
    airy_fail INSTALL release-pkg
# system-release 缺失会让 anaconda 的 GRUB_DISTRIBUTOR 派生失败，grub-mkconfig
# 在 set -e 下中止，装机结果不可引导；在装机段结束前显式判负。
[ -r /etc/system-release ] || airy_fail INSTALL system-release
# 编排单元随镜像落盘（OS-OPS-010 的包级前提）
airy_step 2 8 system
rpm -q airymaxos-system >/dev/null 2>&1 ||
    airy_fail INSTALL system-pkg
# 布局判定入口（M-36）：缺它则装机后 / 与 /data 的布局无从取证
test -x /usr/bin/airy-disk || airy_fail INSTALL airy-disk
# 重启后 / 与 /data 挂不挂得上只取决于 fstab（DISK-01 判据②）：按 /dev/sdX
# 写的源在装机当场可用，扩容或插拔改号后 /data 开机即失挂，而系统照常
# 起来。chroot 内的挂载点仍是 /mnt/sysroot/...，拓扑判定必然误杀，所以这
# 里只判 fstab：源必须是 UUID/LABEL/PARTUUID，且 /data 不得 noauto。
airy_step 3 8 disk
persist=$(airy-disk persist 2>&1) || {
    airy_out "AIRYMAX-DISK-DIAG persist=${persist}"
    airy_fail INSTALL disk-fstab
}
airy_out "AIRYMAX-DISK-OK ${persist}"

# 账户自检：没有可登录账户的安装介质不具备「OS 能运行」的前提
# root 交付为固定口令（sha512 哈希），amuser 交付为空口令（empty）。
airy_step 4 8 accounts
passwd -d amuser || airy_fail INSTALL airymax-unlock
acct_req root sha512 root-account
acct_req amuser empty airymax-account

airy_step 5 8 target
set_default multi-user.target

# 启用边界：清单与动作都由 airymaxos-system 提供（boot_set.sh --root 离线
# 语义）。本段跑在目标根里，systemd 总线不可用，故不看命令行退出码，脚本
# 内按 is-enabled 回读判据；每项一行打到串口，缺项即可归因。
airy_step 6 8 boot-set
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

# 引导参数不能只留在 bootloader --append 里（D-30）：那一行只进安装器本次
# 生成的 grub.cfg，/etc/default/grub 仍是空的。此后任何一次 grub2-mkconfig
# （内核升级、grub2 包升级）都会把 console= 一并丢掉，装好的机器重启即失去
# 串口日志，而无头验收只剩一个「起不来」。
#
# 本剖面没有图形启动，--append 传空串：只收敛控制台集合与菜单范围，不给
# 系统加 rhgb quiet——那会把最小系统唯一可用的串口日志藏进 splash。
airy_step 7 8 grub
grub_args=/usr/lib/airymaxos/boot/grub_args.sh
[ -x "${grub_args}" ] || airy_fail INSTALL grub-args-tool
grub_rc=0
"${grub_args}" --append '' >/tmp/airymax-grub.log 2>&1 || grub_rc=$?
while IFS= read -r line; do
    airy_out "AIRYMAX-GRUB ${line}"
done </tmp/airymax-grub.log
[ "${grub_rc}" -eq 0 ] || airy_fail INSTALL grub-args

# 8) RTC 写入（D-34）：限时、只告警，不在关键路径上。停在
#    "update rtc with system clock" 时，串口最后一行就是
#    AIRYMAX-RTC-BEGIN，耗时与回读偏差记在随后的三行里。
airy_step 8 8 rtc
airy_rtc_sync

airy_out "AirymaxOS minimal install complete (baseline $(date -u +%Y%m%d))"
%end

reboot
