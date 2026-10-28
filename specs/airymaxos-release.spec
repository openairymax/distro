# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-release — AirymaxOS 发行版标识与桌面集成包
#
# 职责：
#   1. 提供 /usr/lib/os-release 与 /etc/os-release 符号链接（VERSION_ID 唯一
#      事实源为仓库内 release/os-release）；并提供 /etc/airymaxos-release 与
#      /etc/system-release 符号链接（内容由同一事实源派生，见下）；
#   2. 提供 /etc/yum.repos.d/airymaxos.repo（仓库列表 SSoT）；
#   3. 提供 /etc/rpm/macros.airymax（文件系统布局宏 SSoT）；
#   4. 部署桌面会话静态资产：lightdm 座位策略、X11 会话输入法环境与分辨率
#      自适应、输入法自启项、UKUI 壁纸注册表与背景默认值、默认壁纸、桌面
#      调度 slice、user@.service 挂接及登录链就绪探针；
#   5. 部署登录与提权策略：sshd 允许交付账户的空口令登录，sudo 以
#      NOPASSWD 放开同一账户的非交互提权，桌面侧关闭空闲锁屏（空口令账户
#      被锁屏拦住只会制造口令框）；
#   6. 部署 EFI 品牌化脚本 efi_brand.sh：由安装配方的 %%post --nochroot
#      调用（distro/kickstart/airymaxos-workstation.ks），把 anaconda 留下的
#      openEuler 引导项替换为置顶的 AirymaxOS 条目；
#   7. %%post 只执行装配后才能确定的运行期动作：编译 glib schema、屏蔽桌面
#      自带 AI 控制面单元、在运行中的系统上重载 systemd。
#   8. 声明默认启动画面主题：以 /usr/share/plymouth/themes/default.plymouth
#      符号链接指向 tribar，kickstart 的 rhgb 因此有画面可显示。不改
#      /etc/plymouth/plymouthd.conf 与 plymouthd.defaults——两者都归
#      plymouth 包，同名文件被两个包同时持有会让安装事务整体失败。
#
# 静态资产一律由 %%install 直接落到最终路径，%%post 不复制文件，同一路径只有
# 一处事实来源。
#
# 与基础发行版的关系：openEuler 24.03 LTS 的 release 包同占 /etc/os-release，
# 因此本包以 system-release 虚拟能力接管该位置，并显式 Obsoletes 旧包。
#
# /etc/system-release 是引导配置生成的硬依赖，不是可选装饰：anaconda 安装
# 引导装载程序时以
#   GRUB_DISTRIBUTOR="$(sed 's, release .*$,,g' /etc/system-release)"
# 写入 /etc/default/grub，而 grub-mkconfig 以 set -e 运行并在开头 source
# 该文件。文件缺失时 sed 以非零退出，命令替换的失败在 set -e 下中止整个
# grub-mkconfig，anaconda 随即抛出 BootLoaderError 并停在交互问句上，无头
# 安装只能等到超时。上游 release 包被 Obsoletes 排除后，本包必须自己提供
# 该路径，内容从 os-release 的 NAME/VERSION 派生，版本号不二次书写。
#
# 构建约束：全部 Source 为仓库内裸文件名，由构建流水线 staging 到
# _sourcedir 后 rpmbuild；配方只在安装期从这些文件派生目标路径与派生素
# 材，不下载、也不新增任何 Source。
# ===========================================================================

%global airy_version 0.0.3
%global airy_release 14
%{!?_unitdir:%global _unitdir /usr/lib/systemd/system}

Name:           airymaxos-release
Version:        %{airy_version}
Release:        %{airy_release}%{?dist}
Summary:        AirymaxOS release identity, repositories and desktop policy
License:        AGPL-3.0-or-later
URL:            https://atomgit.com/openairymax/agent-linux
BuildArch:      noarch

Source0:        os-release
Source1:        airymax-os.repo
Source2:        macros.airymax
Source3:        airymax-desktop.slice
Source4:        70-airymax-ukui-policy.sh
Source5:        airymaxos-default.jpg
Source6:        LICENSE
Source7:        50-airymax.conf
Source8:        70-airymax-im.sh
Source9:        airymax-input-method.desktop
Source10:       airymaxos-default.xml
Source11:       99-airymaxos-default.gschema.override
Source12:       50-airymax-desktop.conf
Source13:       airymax-desktop-ready.service
Source14:       desktop_ready.sh
Source15:       boot_state.sh
Source16:       50-airymax-sshd.conf
Source17:       display_mode.sh
Source18:       60-airymax-display.sh
Source19:       01_airymax_display
Source20:       efi_brand.sh
Source21:       90-airymax-sudoers
Source22:       00-airymax-screensaver
Source23:       50-airymax-journald.conf
Source24:       airymax-display.desktop

Provides:       system-release
Provides:       system-release(releasever)
Obsoletes:      openEuler-release < 24.04
Requires:       systemd
# 锁屏策略以 dconf 系统库交付：键文件不编译就只是一份不生效的文本，锁屏
# 仍按上游默认值索要口令。dconf 属桌面闭包，这里显式声明以免闭包调整后
# 静默失去编译步骤。
Requires:       dconf
# 安装期品牌化靠 efibootmgr 写 NVRAM；它本就属引导闭包（scripts/lib/
# closure.sh CL_BOOT），这里显式声明，免得后续精简闭包时静默丢工具。
Requires:       efibootmgr

%description
AirymaxOS release identity package. It owns the distribution version
file, the dnf repository definitions and the shared RPM macros used by
every AirymaxOS package, and it ships the UKUI desktop session policy
assets applied at install time.

%prep
%setup -q -c -T

%build

%install
install -d -m 0755 %{buildroot}/usr/lib
install -m 0644 %{SOURCE0} %{buildroot}/usr/lib/os-release
install -d -m 0755 %{buildroot}%{_sysconfdir}
ln -s ../usr/lib/os-release %{buildroot}%{_sysconfdir}/os-release

# 单行发行版标识：NAME 与 VERSION 从 os-release 派生，格式遵循上游惯例
# （<发行版> release <版本>），/etc/system-release 以符号链接指向它。
airy_name=$(sed -n 's/^NAME="\(.*\)"$/\1/p' %{SOURCE0})
airy_ver=$(sed -n 's/^VERSION="\(.*\)"$/\1/p' %{SOURCE0})
printf '%s release %s\n' "${airy_name}" "${airy_ver}" \
    > %{buildroot}%{_sysconfdir}/airymaxos-release
ln -s airymaxos-release %{buildroot}%{_sysconfdir}/system-release

install -d -m 0755 %{buildroot}%{_sysconfdir}/yum.repos.d
install -m 0644 %{SOURCE1} %{buildroot}%{_sysconfdir}/yum.repos.d/airymaxos.repo

install -d -m 0755 %{buildroot}%{_sysconfdir}/rpm
install -m 0644 %{SOURCE2} %{buildroot}%{_sysconfdir}/rpm/macros.airymax

install -d -m 0755 %{buildroot}%{_unitdir}
install -m 0644 %{SOURCE3} %{buildroot}%{_unitdir}/airymax-desktop.slice
install -m 0644 %{SOURCE13} \
    %{buildroot}%{_unitdir}/airymax-desktop-ready.service

install -d -m 0755 %{buildroot}/usr/lib/airymaxos/desktop
install -m 0755 %{SOURCE14} \
    %{buildroot}/usr/lib/airymaxos/desktop/desktop_ready.sh
install -m 0644 %{SOURCE15} \
    %{buildroot}/usr/lib/airymaxos/desktop/boot_state.sh
install -m 0755 %{SOURCE17} \
    %{buildroot}/usr/lib/airymaxos/desktop/display_mode.sh

install -d -m 0755 %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d
install -m 0644 %{SOURCE7} \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf

install -d -m 0755 %{buildroot}%{_sysconfdir}/ssh/sshd_config.d
install -m 0644 %{SOURCE16} \
    %{buildroot}%{_sysconfdir}/ssh/sshd_config.d/50-airymax-sshd.conf

# sudo 只接受模式 0440 的 include 文件，其余权限会被静默忽略；因此这里是
# 权限而不是内容的一部分。改名去掉 -sudoers 后缀，与 /etc/sudoers.d 内
# 「按文件名排序生效」的惯例一致。
install -d -m 0750 %{buildroot}%{_sysconfdir}/sudoers.d
install -m 0440 %{SOURCE21} \
    %{buildroot}%{_sysconfdir}/sudoers.d/90-airymax

# 锁屏策略与 sudo 策略是同一口径的两半：交付账户既能免密进桌面，就不能被
# 空闲锁屏拦住。目录由 dconf 包拥有，这里只落键文件。
install -d -m 0755 %{buildroot}%{_sysconfdir}/dconf/db/local.d
install -m 0644 %{SOURCE22} \
    %{buildroot}%{_sysconfdir}/dconf/db/local.d/00-airymax-screensaver

install -d -m 0755 %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d
install -m 0755 %{SOURCE8} \
    %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
install -m 0755 %{SOURCE18} \
    %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh

install -d -m 0755 %{buildroot}%{_sysconfdir}/grub.d
install -m 0755 %{SOURCE19} \
    %{buildroot}%{_sysconfdir}/grub.d/01_airymax_display

install -d -m 0755 %{buildroot}/usr/lib/airymaxos/boot
install -m 0755 %{SOURCE20} \
    %{buildroot}/usr/lib/airymaxos/boot/efi_brand.sh

install -d -m 0755 %{buildroot}%{_sysconfdir}/xdg/autostart
install -m 0644 %{SOURCE9} \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-input-method.desktop
install -m 0644 %{SOURCE24} \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-display.desktop

install -d -m 0755 %{buildroot}%{_sysconfdir}/systemd/system/user@.service.d
install -m 0644 %{SOURCE12} \
    %{buildroot}%{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf

# 启动日志默认只活在当前一轮：openEuler 不预建 /var/log/journal，
# Storage=auto 因此退化为 volatile，重启即丢的证据让「上一次启动为什么
# 失败」只能靠复现去猜。drop-in 目录由 systemd 包拥有，这里只落策略文件。
install -d -m 0755 %{buildroot}%{_sysconfdir}/systemd/journald.conf.d
install -m 0644 %{SOURCE23} \
    %{buildroot}%{_sysconfdir}/systemd/journald.conf.d/50-airymax-journald.conf

# 启动画面：默认主题以 plymouth 自己的「default.plymouth 符号链接」声明。
# plymouthd 依次读 plymouthd.conf、plymouthd.defaults，主题不可用时才读这条
# 链接，最后回落 text；openEuler 的 defaults 指向 spinner，而它的包里没有
# spinner，链接因此是实际生效的那一处。dracut 的 plymouth-populate-initrd
# 走同一条链，主题随之进入 initramfs。父目录归 plymouth 包，这里只放链接。
install -d -m 0755 %{buildroot}%{_datadir}/plymouth/themes
ln -s tribar/tribar.plymouth \
    %{buildroot}%{_datadir}/plymouth/themes/default.plymouth

install -d -m 0755 %{buildroot}%{_datadir}/ukui-background-properties
install -m 0644 %{SOURCE10} \
    %{buildroot}%{_datadir}/ukui-background-properties/airymaxos-default.xml

install -d -m 0755 %{buildroot}%{_datadir}/glib-2.0/schemas
install -m 0644 %{SOURCE11} \
    %{buildroot}%{_datadir}/glib-2.0/schemas/99-airymaxos-default.gschema.override

install -d -m 0755 %{buildroot}%{_datadir}/backgrounds/airymaxos
install -m 0644 %{SOURCE5} \
    %{buildroot}%{_datadir}/backgrounds/airymaxos/airymaxos-default.jpg

install -d -m 0755 %{buildroot}%{_datadir}/airymaxos/distro/desktop
install -m 0755 %{SOURCE4} \
    %{buildroot}%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh

install -d -m 0755 %{buildroot}%{_datadir}/licenses/airymaxos-release
install -m 0644 %{SOURCE6} \
    %{buildroot}%{_datadir}/licenses/airymaxos-release/LICENSE

%check
grep -qxF 'ID=airymaxos' %{buildroot}/usr/lib/os-release
grep -qxF 'VERSION_ID="%{version}"' %{buildroot}/usr/lib/os-release
grep -qxF 'ID_LIKE="openeuler"' %{buildroot}/usr/lib/os-release
test -L %{buildroot}%{_sysconfdir}/os-release
# system-release 的存在性与 anaconda 的解析结果一并断言：文件缺失或格式
# 不符都会让引导配置生成失败，必须在构建期而不是装机期暴露。
want=$(sed -n 's/^NAME="\(.*\)"$/\1/p' %{SOURCE0})
test -L %{buildroot}%{_sysconfdir}/system-release
test "$(readlink %{buildroot}%{_sysconfdir}/system-release)" = airymaxos-release
test "$(wc -l < %{buildroot}%{_sysconfdir}/airymaxos-release)" -eq 1
test "$(sed 's, release .*$,,g' \
    %{buildroot}%{_sysconfdir}/system-release)" = "${want}"
grep -qxF '[airymaxos-base]' %{buildroot}%{_sysconfdir}/yum.repos.d/airymaxos.repo
grep -qF 'airymax_libdir' %{buildroot}%{_sysconfdir}/rpm/macros.airymax
grep -qF '/usr/lib/airymaxos' %{buildroot}%{_sysconfdir}/rpm/macros.airymax
grep -qxF 'CPUWeight=50' %{buildroot}%{_unitdir}/airymax-desktop.slice
grep -qxF 'WantedBy=graphical.target' \
    %{buildroot}%{_unitdir}/airymax-desktop-ready.service
bash -n %{buildroot}/usr/lib/airymaxos/desktop/desktop_ready.sh
bash -n %{buildroot}/usr/lib/airymaxos/desktop/boot_state.sh
test -r %{buildroot}/usr/lib/airymaxos/desktop/boot_state.sh
# 类别集合必须同时覆盖 greeter 与 autologin：座位策略启用 autologin 时
# lightdm 不创建 greeter 会话，只认一类会让另一种镜像永远等不到就绪标记。
grep -qxF 'SESS_CLASSES="greeter user"' \
    %{buildroot}/usr/lib/airymaxos/desktop/desktop_ready.sh
bash -n %{buildroot}%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
grep -qxF 'user-session=ukui' \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
grep -qxF 'autologin-user=airymax' \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
grep -qxF 'PermitEmptyPasswords yes' \
    %{buildroot}%{_sysconfdir}/ssh/sshd_config.d/50-airymax-sshd.conf
# 免密提权：sudo 会静默忽略模式不等于 0440 的 include 文件，所以权限与
# 内容要分别断言。有效规则必须恰好一条且为 airymax 的 NOPASSWD，防止
# 后续追加规则把「只放开一个账户」的收敛范围悄悄放宽。
test "$(stat -c %a %{buildroot}%{_sysconfdir}/sudoers.d/90-airymax)" = 440
airy_rule=$(grep -v '^#' %{buildroot}%{_sysconfdir}/sudoers.d/90-airymax |
    sed '/^$/d')
test "${airy_rule}" = 'airymax ALL=(ALL) NOPASSWD: ALL'
# 锁屏策略：键名拼错或取值被改回 true 都不会让构建失败，只会在装机后以
# 「每五分钟一次口令框」的形式出现，所以两个键都要逐字断言。
airy_saver=%{buildroot}%{_sysconfdir}/dconf/db/local.d/00-airymax-screensaver
grep -qxF '[org/ukui/screensaver]' "${airy_saver}"
grep -qxF 'idle-lock-enabled=false' "${airy_saver}"
grep -qxF 'lock-enabled=false' "${airy_saver}"
sh -n %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
sh -n %{buildroot}/usr/lib/airymaxos/desktop/display_mode.sh
sh -n %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh
# 收敛入口有两个：早期钩子与会话就绪后的 autostart。任一处丢失都会退回
# 「一次性写入」，而那正是 T10 在验收基线上失败的形态，因此两处分别断言。
# autostart 必须是 --guard 而不是 --settle：settings-daemon 的回写晚于收敛
# 完成时刻，只有守护窗口能覆盖到它（验收轮 40610532780 的 T10 根因）。
grep -qF -- '--settle 10' \
    %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh
grep -qxF 'Exec=/usr/lib/airymaxos/desktop/display_mode.sh --guard 180' \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-display.desktop
# 分辨率策略在构建期以合成拓扑跑一遍：首选 4K 必须被降到 1920x1080。
# awk 解析若随 xrandr 输出格式漂移而失效，这里而不是装机现场暴露。
airy_plan=$(printf 'Screen 0: minimum 8 x 8, current 3840 x 2160, maximum 32767 x 32767\neDP-1 connected primary 3840x2160+0+0 (normal) 344mm x 194mm\n   3840x2160     60.00*+\n   1920x1080     60.00\n' | %{buildroot}/usr/lib/airymaxos/desktop/display_mode.sh --plan)
test "${airy_plan}" = 'eDP-1 3840x2160 1920x1080'
# 引导期分辨率：这段必须无条件落 gfxmode 与 gfxterm。openEuler 的 00_header
# 把三行塞进 loadfont 成功的分支，字体缺失时整段静默跳过（D-28），所以这里
# 断言的是「我们输出的内容」，不是 cfg 里存在某条 gfxmode。
sh -n %{buildroot}%{_sysconfdir}/grub.d/01_airymax_display
airy_grub=$(%{buildroot}%{_sysconfdir}/grub.d/01_airymax_display)
printf '%s\n' "${airy_grub}" |
    grep -qxF '  set gfxmode=1920x1080,1680x1050,1600x900,1280x1024,1024x768,auto'
printf '%s\n' "${airy_grub}" | grep -qxF '  terminal_output gfxterm'
printf '%s\n' "${airy_grub}" | grep -qxF '  insmod gfxterm'
printf '%s\n' "${airy_grub}" | grep -qF 'grub_platform'
# EFI 品牌化：脚本只由安装配方的 %%post --nochroot 调用（目标根经 --esp /
# --state 传入），断言落在三项行为契约上——参数入口存在、目标目录在 ESP 内、
# 非 EFI 装机必须优雅跳过而不是失败。首启单元已被移除：systemd 以 init_t
# 运行，在 dosfs_t 上建文件被 SELinux 拒绝（验收 run 40574831975 的 AVC）。
sh -n %{buildroot}/usr/lib/airymaxos/boot/efi_brand.sh
grep -qxF '    --esp) esp=${2:?--esp 需要目录}; shift 2 ;;' \
    %{buildroot}/usr/lib/airymaxos/boot/efi_brand.sh
grep -qxF 'dst=${esp}/EFI/airymaxos' \
    %{buildroot}/usr/lib/airymaxos/boot/efi_brand.sh
grep -qxF '[ -d /sys/firmware/efi ] || skip "no efivarfs (BIOS boot)"' \
    %{buildroot}/usr/lib/airymaxos/boot/efi_brand.sh
grep -qF 'efibootmgr -o "${order}"' \
    %{buildroot}/usr/lib/airymaxos/boot/efi_brand.sh
grep -qxF 'Exec=/usr/bin/fcitx' \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-input-method.desktop
grep -qxF 'Slice=airymax-desktop.slice' \
    %{buildroot}%{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf
# 日志留存：取值写错不会让构建失败，只会在重启后表现为「没有上一次启动」，
# 因此断言的是生效行本身而不是文件存在。
grep -qxF '[Journal]' \
    %{buildroot}%{_sysconfdir}/systemd/journald.conf.d/50-airymax-journald.conf
grep -qxF 'Storage=persistent' \
    %{buildroot}%{_sysconfdir}/systemd/journald.conf.d/50-airymax-journald.conf
# 启动画面：链接名对但目标名拼错时链接悬空，plymouthd 静默回落 text，
# 观感问题不会出现在任何日志里，所以构建期断言链接本身与目标两段。
test -L %{buildroot}%{_datadir}/plymouth/themes/default.plymouth
test "$(readlink %{buildroot}%{_datadir}/plymouth/themes/default.plymouth)" = \
    'tribar/tribar.plymouth'
grep -qF '<!DOCTYPE wallpapers SYSTEM' \
    %{buildroot}%{_datadir}/ukui-background-properties/airymaxos-default.xml
grep -qF "picture-filename='" \
    %{buildroot}%{_datadir}/glib-2.0/schemas/99-airymaxos-default.gschema.override
test -s %{buildroot}%{_datadir}/backgrounds/airymaxos/airymaxos-default.jpg

%post
# schema 编译先于策略脚本：内置壁纸默认值（T5 验收项）不能被后续脚本的
# 失败连带跳过。
if [ -f %{_datadir}/glib-2.0/schemas/org.mate.background.gschema.xml ] &&
   command -v glib-compile-schemas >/dev/null 2>&1; then
    glib-compile-schemas %{_datadir}/glib-2.0/schemas
fi

# 键文件要编译进系统库才被 GSettings 读到；缺这一步时文件在位而策略不生效，
# 锁屏仍按上游默认值弹口令框，且从文件系统上看不出差别。
if command -v dconf >/dev/null 2>&1; then
    dconf update >/dev/null 2>&1 || :
fi

%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload >/dev/null 2>&1 || :
fi

%files
%defattr(-, root, root, -)
%{_sysconfdir}/os-release
/usr/lib/os-release
%{_sysconfdir}/airymaxos-release
%{_sysconfdir}/system-release
%config(noreplace) %{_sysconfdir}/yum.repos.d/airymaxos.repo
%config(noreplace) %{_sysconfdir}/rpm/macros.airymax
%config(noreplace) %{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
%config(noreplace) %{_sysconfdir}/ssh/sshd_config.d/50-airymax-sshd.conf
%dir %attr(0750, root, root) %{_sysconfdir}/sudoers.d
%config(noreplace) %attr(0440, root, root) %{_sysconfdir}/sudoers.d/90-airymax
%config(noreplace) %{_sysconfdir}/dconf/db/local.d/00-airymax-screensaver
%config(noreplace) %{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
%config(noreplace) %{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh
%config(noreplace) %{_sysconfdir}/grub.d/01_airymax_display
%config(noreplace) %{_sysconfdir}/xdg/autostart/airymax-input-method.desktop
%config(noreplace) %{_sysconfdir}/xdg/autostart/airymax-display.desktop
%config(noreplace) %{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf
%config(noreplace) %{_sysconfdir}/systemd/journald.conf.d/50-airymax-journald.conf
%{_unitdir}/airymax-desktop.slice
%{_unitdir}/airymax-desktop-ready.service
/usr/lib/airymaxos/desktop/desktop_ready.sh
/usr/lib/airymaxos/desktop/boot_state.sh
/usr/lib/airymaxos/desktop/display_mode.sh
/usr/lib/airymaxos/boot/efi_brand.sh
%{_datadir}/plymouth/themes/default.plymouth
%{_datadir}/ukui-background-properties/airymaxos-default.xml
%{_datadir}/glib-2.0/schemas/99-airymaxos-default.gschema.override
%{_datadir}/backgrounds/airymaxos/airymaxos-default.jpg
%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
%{_datadir}/licenses/airymaxos-release/LICENSE

%changelog
* Wed Oct 28 2026 SPHARX <dev@spharx.com> - 0.0.3-14
- Stop owning /etc/plymouth/plymouthd.conf. The plymouth package ships
  that path, and one file in two packages fails the whole install
  transaction with "conflicts between attempted installs" -- acceptance
  run 40639862403 lost both firmware legs to exactly that
- Declare the default theme the way plymouth itself expects, through the
  /usr/share/plymouth/themes/default.plymouth link. plymouthd reads
  plymouthd.conf, then plymouthd.defaults, then that link, then text;
  openEuler's defaults name spinner, which its package does not ship, so
  the link is what decides. plymouth-populate-initrd follows the same
  chain, so the theme also reaches the initramfs

* Wed Oct 28 2026 SPHARX <dev@spharx.com> - 0.0.3-13
- Boot behind a splash instead of scrolling kernel log: the kickstart
  bootloader line gains rhgb quiet, the workstation package list pins
  plymouth (it only arrived as a transitive dependency), and this package
  ships /etc/plymouth/plymouthd.conf with Theme=tribar and ShowDelay=0
- quiet only lowers console loglevel to 4, so warnings still print and
  every record still reaches journal and ttyS0; the login: sentinel the
  installer test waits for comes from agetty and is unaffected

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-12
- Guard the display policy for the whole session-start window instead of
  converging once: ukui's settings daemon writes its own snapshot back
  after --settle has already returned, so acceptance run 40610532780 saw
  "settled after 1s" yet T10 read Virtual-1 at 5120x2160
- Add --guard <seconds> [interval], which keeps correcting inside the
  window, logs one drift line per topology change and one summary line on
  exit; the XDG autostart entry now runs --guard 180 while the xinitrc.d
  hook keeps --settle 10

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-11
- Brand the ESP from the installer instead of first boot. The oneshot unit
  ran as init_t and was denied create on dosfs_t (AVC in acceptance run
  40574831975), so efi_brand.sh skipped by design and EFI/airymaxos never
  appeared -- no AirymaxOS entry, BootOrder still headed by openEuler
- Drop airymaxos-efi-brand.service and call the script from the kickstart
  %post --nochroot with --esp/--state, which also lets the same script
  repair a live system; a failed branding now aborts the install with an
  AIRYMAX-EFI-FAIL console marker instead of a silent skip

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-10
- Converge the display mode instead of writing it once: the xinitrc.d hook
  runs before the virtual output publishes a connected topology, and ukui's
  settings daemon re-applies the panel maximum after the session is up.
  Acceptance run 40574831975 failed T10 with Virtual-1 at 5120x2160 against
  a 1280x800 policy for exactly that reason
- Add --settle with a bounded budget plus journal diagnostics, and an XDG
  autostart entry that converges again once the session is ready

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-9
- Accept the autologin seat in the desktop ready probe: 50-airymax.conf
  enables autologin-user, so lightdm never creates a greeter session and
  the probe waited for a class that cannot exist. Every autologin image
  therefore reported AIRYMAX-DESKTOP-FAIL, which the host BOOT_FAIL rule
  treats as a boot failure -- the exact reason both firmwares failed
  cold-boot acceptance
- Match the service family (lightdm*), classes {greeter,user}, and
  states {active,online} instead of pinning greeter; probe only decides
  whether the session exists, run-smoke.sh T1 keeps deciding whether
  ukui-session is alive

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-8
- Ship /etc/systemd/journald.conf.d/50-airymax-journald.conf with
  Storage=persistent: openEuler ships neither /var/log/journal nor a
  journald drop-in directory, so Storage=auto degrades to volatile and
  every reboot erases the only record of what the previous boot did --
  exactly the evidence needed when a fresh install fails to reach the
  desktop. journald creates the directory and caps it at SystemMaxUse
  on its own, so no tmpfiles rule is involved
- %%check asserts the two effective lines: a mistyped value still
  produces a file, and only resurfaces after a reboot as "there was no
  previous boot"

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-7
- Ship a dconf system default that turns off idle locking: the delivery
  account is created with an empty password, so the lock screen protects
  nothing while popping a password prompt after five idle minutes, which
  turns "boot to desktop" into "type a password every five minutes".
  Only the two lock keys change; the screensaver itself and DPMS stay,
  and manual locking still works
- Require dconf explicitly: the key file does nothing until %%post
  compiles it into /etc/dconf/db/local, and %%check asserts both keys so
  a later edit cannot quietly re-enable locking

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-6
- Ship /etc/sudoers.d/90-airymax: the airymax account is delivered with
  an empty password, and an empty password cannot serve as the interactive
  credential sudo prompts for, so any non-interactive elevation (systemd
  units, remote administration) failed on a freshly installed system. The
  drop-in grants NOPASSWD to that one account only
- Mode is 0440 because sudo silently ignores include files with any other
  permission; %%check asserts the mode and that exactly one effective rule
  exists, so later edits cannot quietly widen the grant

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-5
- Ship efi_brand.sh and airymaxos-efi-brand.service: anaconda names the
  NVRAM entry after GRUB_DISTRIBUTOR (openEuler) and an entry label
  cannot be renamed, so first boot copies the signed second stage into
  EFI/airymaxos, creates an AirymaxOS entry and puts it at the head of
  BootOrder. Failures are journalled as AIRYMAX-EFI-NOTE and leave the
  state file unwritten, so the next boot retries instead of leaving a
  failed unit behind
- Require efibootmgr explicitly; it is already part of the boot closure,
  but a future closure trim must not silently drop it

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-4
- Ship /etc/grub.d/01_airymax_display: openEuler's 00_header puts
  gfxmode, load_video and gfxterm inside the loadfont branch, so a
  missing unicode.pf2 skips the whole block and the console stays at the
  firmware default (800x600 on the B50 test unit). The new fragment runs
  right after 00_header and sets gfxmode and gfxterm unconditionally on
  EFI; the ladder drops the x32 suffix because some GOP implementations
  reject every depth-qualified candidate and fall back to auto
- %check runs the fragment and asserts the exact lines it emits, so a
  silently skipped block fails the build instead of the installed system

* Tue Oct 27 2026 SPHARX <dev@spharx.com> - 0.0.3-3
- Ship display_mode.sh and its xinitrc.d hook: each connected output is
  capped at 1920x1200 and falls back to a common-resolution ladder, so a
  4K panel no longer lands in an unusable mode
- %check runs the policy against a synthetic topology, so xrandr output
  drift fails the build instead of the installed system

* Sun Oct 25 2026 SPHARX <dev@spharx.com> - 0.0.3-2
- Ship the 0.0.3 password policy: lightdm autologin for airymax and an
  sshd drop-in that permits empty passwords, so the shipped empty-password
  account can log in locally and over SSH (PAM already has pam_unix nullok)
- %check asserts both directives reach the buildroot, since a missing
  drop-in silently degrades to "no login" instead of failing the build

* Sun Oct 18 2026 SPHARX <dev@spharx.com> - 0.0.3-1
- Ship /etc/airymaxos-release and /etc/system-release derived from
  os-release, so anaconda can build GRUB_DISTRIBUTOR and grub-mkconfig
  does not abort under set -e when the file is missing
- Ship the UKUI session policy assets: lightdm seat, input method
  environment and autostart, wallpaper registry and background default,
  desktop slice and user@.service drop-in
- Add airymax-desktop-ready.service and its probe script so image CI can
  assert the lightdm greeter session is reachable after boot
