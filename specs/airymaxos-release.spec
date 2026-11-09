# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-release — AirymaxOS 发行版标识与桌面集成包
#
# 职责：
#   1. 提供 /usr/lib/os-release 与 /etc/os-release 符号链接（VERSION_ID 唯一
#      事实源为仓库内 release/os-release）；并提供 /etc/airymaxos-release 与
#      /etc/system-release 符号链接（内容由同一事实源派生，见下）；以及登录
#      前后的两处品牌面 /etc/issue 与 /etc/motd.d/airymax；
#   2. 提供 /etc/yum.repos.d/airymaxos.repo（仓库列表 SSoT）；
#   3. 提供 /etc/rpm/macros.airymax（文件系统布局宏 SSoT）；
#   4. 部署桌面会话静态资产：lightdm 座位策略、座位 X server 启动封装、X11
#      会话输入法环境与分辨率自适应、输入法自启项、UKUI 壁纸注册表与背景
#      默认值、三张品牌默认壁纸、桌面调度 slice、user@.service 挂接及登录链就绪探针；
#   5. 部署登录与提权策略：sshd 允许交付账户的空口令登录，sudo 以
#      NOPASSWD 放开同一账户的非交互提权，桌面侧关闭空闲锁屏（空口令账户
#      被锁屏拦住只会制造口令框）；
#   6. 部署启动参数脚本 grub_args.sh：由安装配方 %%post --nochroot 调用
#      （distro/kickstart/airymaxos-workstation.ks），把 bootloader --append
#      的参数与菜单范围写进 /etc/default/grub 并重建 grub.cfg。--append 只
#      作用于安装器本次生成的那一份，anaconda 不写 /etc/default/grub，此后
#      每次 grub2-mkconfig 都会丢掉启动参数；
#   7. 部署 EFI 品牌化脚本 efi_brand.sh：同一安装段在 6 之后调用，把
#      anaconda 留下的 openEuler 引导项替换为置顶的 AirymaxOS 条目，并清掉
#      本机 ESP 上的同名残留条目，使固件菜单里不再出现上游名字；
#   8. %%post 只执行装配后才能确定的运行期动作：编译 glib schema、屏蔽桌面
#      自带 AI 控制面单元、收敛控制台字体、在运行中的系统上重载 systemd。
#   9. 声明默认启动画面主题：以 /usr/share/plymouth/themes/default.plymouth
#      符号链接指向 tribar。0.0.4 的启动路径用 plymouth.enable=0 关掉了
#      plymouth（见 grub_args.sh 头部），主题因此只是随镜像待命；日后 KMS
#      覆盖到位、去掉那个参数即生效。不改 /etc/plymouth/plymouthd.conf 与
#      plymouthd.defaults——两者都归 plymouth 包，同名文件被两个包同时持有
#      会让安装事务整体失败。
#  10. 部署网络全局策略 /etc/NetworkManager/conf.d/99-airymax.conf：桌面
#      形态的 DNS 管理与连通性探测口径，与镜像的包闭包成对断言。
#  11. 把控制台字体切到 16x32：8x16 在 2880x1800 的面板上把一屏铺成
#      360x112 个字形，开机阶段行事实上无法辨读（285H 实机）。字体文件由
#      kbd 提供，本包只改 /etc/vconsole.conf 的 FONT 一行；该路径归
#      systemd-udev，本包不能持有，理由见 %%post 注释。
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
# 该路径，内容从 os-release 派生，版本号不二次书写。
#
# 派生取的是 PRETTY_NAME 而不是 NAME：GRUB_DISTRIBUTOR 会进入引导菜单条目名
# 与 NVRAM 条目，是 ASCII-only 通道，而 NAME 按 0.0.4 命名口径含中文全名。
# PRETTY_NAME 的格式由 %%check 断言为「<ASCII 短名> <VERSION_ID>」，短名即
# 本包的 distributor 名，两处品牌面因此仍是同一事实源。
#
# 构建约束：全部 Source 为仓库内裸文件名，由构建流水线 staging 到
# _sourcedir 后 rpmbuild；配方只在安装期从这些文件派生目标路径与派生素
# 材，不下载、也不新增任何 Source。
# ===========================================================================

%global airy_version 0.0.4
%global airy_release 15
# 桌面版本随冻结点滚动，写在 /etc/airymaxos/desktop-version，供控制中心
# 「关于」页读取。控制中心自己不猜版本：缺文件即只显示桌面名。此宏与
# lockfile/ukui-components.yaml 的 ukui-control-center 版本由
# lockfile/ukui_check.py 校验相等，不允许各写一份。
%global ukui_desktop_version 3.1.2
# 基底版本是显式输入，与 distro/repo/airymax-os.repo 及 kickstart 的
# url/repo 行是三处同源表达。%%check 以本宏断言客户端配置，版本漂移在
# 构建期失败，而不是等到装机后 dnf 报「找不到仓库」。
%global oe_base openEuler-24.03-LTS-SP3
# 构建来源指纹由构建驱动以 airy_build_id 宏注入（scripts/lib/buildid.sh）。
# 缺省值 unset 是有意的：绕过驱动直接 rpmbuild 时，%%check 必须失败，而不是
# 把空 BUILD_ID 写进发行版标识——那样镜像看起来正常，却无法归因到某次构建。
%{!?airy_build_id:%global airy_build_id unset}
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
Source5:        qilian_photo_from_zhenyi.jpg
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
Source25:       grub_args.sh
Source26:       xserver.sh
Source27:       session_env.sh
Source28:       airy_record.sh
Source29:       airy_observe.sh
Source30:       airy_bench.py
Source31:       airy_demo.py
Source32:       airy_inspect.py
Source33:       motd
Source34:       99-airymax.conf
Source35:       clouds_moonlight_photo_from_lidecheng.jpg
Source36:       hangzhouxihu_photo_from_lidecheng.jpg
Source37:       airymax-update-notify.desktop
Source38:       network-wired-signal-excellent-symbolic.svg
Source39:       network-wireless-signal-excellent-error-symbolic.svg
Source40:       network-wireless-signal-low-secure-symbolic.svg
Source41:       50-airymax-kgaccel-env.conf
Source42:       90-airymax-touchpad.conf
Source43:       airymax-panel.conf
Source44:       airymax-audio-init.service
Source45:       audio_init.sh

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
# 录屏工具的执行依赖：ffmpeg 提供 x11grab 与 libx264，缺它 airy-record 只能
# 自检报 degraded。这里用弱依赖而不是 Requires——ffmpeg 在 EPOL 而非基线
# 仓库，硬依赖会让一次元数据缺失直接中止装机；有它就装上，没有也不阻断。
Recommends:     ffmpeg
# 桌面就绪探针（第 8 阶段）与 boot_state 的打印契约来自 airymaxos-system 的
# ui.sh。缺它探针会以 reason=ui-lib 硬失败——与其让每台机器在图形目标上
# 报一次无法归因的失败，不如在安装期就把两个包绑定。
Requires:       airymaxos-system >= %{version}

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

# 来源指纹替换仓库里的占位行：os-release 会被外部工具按键值解析，就地改写
# 比在 %%install 里重写整份文件更不容易漏掉后续新增字段。指纹字符集不含
# sed 替换侧的元字符（& 与 \ 与 |），宏值可直接放进替换段。
# /etc/airymaxos-build 是同一事实的第二份拷贝，供只读根分区或解析器不认
# os-release 的场景使用；两处逐字相等由 %%check 断言。
sed -i 's|^BUILD_ID=.*$|BUILD_ID="%{airy_build_id}"|' \
    %{buildroot}/usr/lib/os-release
printf 'BUILD_ID=%s\n' '%{airy_build_id}' \
    > %{buildroot}%{_sysconfdir}/airymaxos-build
chmod 0644 %{buildroot}%{_sysconfdir}/airymaxos-build

# 桌面版本是「关于」页「桌面」一栏的唯一输入。控制中心只读本文件、不猜
# 版本；缺文件时它回落为桌面名，界面上不会编造版本号。
install -d -m 0755 %{buildroot}%{_sysconfdir}/airymaxos
printf 'UKUI %s\n' '%{ukui_desktop_version}' \
    > %{buildroot}%{_sysconfdir}/airymaxos/desktop-version
chmod 0644 %{buildroot}%{_sysconfdir}/airymaxos/desktop-version

# 单行发行版标识与登录横幅同取 PRETTY_NAME，版本号只在 os-release 出现一次。
# system-release 格式遵循上游惯例 <distributor> release <版本>，其中 distributor
# 是 PRETTY_NAME 的首词（anaconda 的 sed 正是按 " release " 反切这个词），文件
# 以符号链接形式由 /etc/system-release 指向。distributor 必须 ASCII：它进入引导
# 菜单条目名与 NVRAM，取含中文的 NAME 会让菜单在非 UTF-8 控制台输出乱码。
airy_pretty=$(sed -n 's/^PRETTY_NAME="\(.*\)"$/\1/p' %{SOURCE0})
airy_vid=$(sed -n 's/^VERSION_ID="\(.*\)"$/\1/p' %{SOURCE0})
airy_dist=${airy_pretty%% *}
printf '%s release %s\n' "${airy_dist}" "${airy_vid}" \
    > %{buildroot}%{_sysconfdir}/airymaxos-release
ln -s airymaxos-release %{buildroot}%{_sysconfdir}/system-release

# /etc/issue 不被任何包持有（目标机 rpm -qf 无归属），本包直接提供：agetty
# 在登录提示前原样打印它，是控制台与串口上最先出现的品牌面。首行逐字等于
# PRETTY_NAME，与 /etc/os-release 的同一字段同值，验收只需比对两处字符串。
# \\r \\m \\l 是 agetty 转义（运行内核版本、机器架构、终端设备），必须原样
# 保留——写死字符串会让横幅与真实运行的内核脱钩，现场无法据此判断引导了哪
# 个内核。
printf '%s\nKernel \\r on an \\m (\\l)\n' "${airy_pretty}" \
    > %{buildroot}%{_sysconfdir}/issue

# 登录后横幅走 /etc/motd.d 而不是 /etc/motd：后者由 setup 包持有，两个包
# 同持一个路径会让安装事务整体失败（与 plymouthd.conf 同一条约束）。目标机
# 的 pam_motd 1.5.3 会按目录读取 /etc/motd.d 下的全部文件并拼接输出。
install -d -m 0755 %{buildroot}%{_sysconfdir}/motd.d
install -m 0644 %{SOURCE33} %{buildroot}%{_sysconfdir}/motd.d/airymax

install -d -m 0755 %{buildroot}%{_sysconfdir}/yum.repos.d
install -m 0644 %{SOURCE1} %{buildroot}%{_sysconfdir}/yum.repos.d/airymaxos.repo

install -d -m 0755 %{buildroot}%{_sysconfdir}/rpm
install -m 0644 %{SOURCE2} %{buildroot}%{_sysconfdir}/rpm/macros.airymax

install -d -m 0755 %{buildroot}%{_unitdir}
install -m 0644 %{SOURCE3} %{buildroot}%{_unitdir}/airymax-desktop.slice
install -m 0644 %{SOURCE13} \
    %{buildroot}%{_unitdir}/airymax-desktop-ready.service
install -m 0644 %{SOURCE44} \
    %{buildroot}%{_unitdir}/airymax-audio-init.service

install -d -m 0755 %{buildroot}/usr/lib/airymaxos/desktop
install -m 0755 %{SOURCE14} \
    %{buildroot}/usr/lib/airymaxos/desktop/desktop_ready.sh
install -m 0644 %{SOURCE15} \
    %{buildroot}/usr/lib/airymaxos/desktop/boot_state.sh
install -m 0755 %{SOURCE45} \
    %{buildroot}/usr/lib/airymaxos/desktop/audio_init.sh
install -m 0755 %{SOURCE17} \
    %{buildroot}/usr/lib/airymaxos/desktop/display_mode.sh
install -m 0755 %{SOURCE26} \
    %{buildroot}/usr/lib/airymaxos/desktop/xserver
install -m 0644 %{SOURCE27} \
    %{buildroot}/usr/lib/airymaxos/desktop/session_env.sh
install -m 0755 %{SOURCE28} \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_record.sh
install -m 0755 %{SOURCE29} \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_observe.sh
install -m 0755 %{SOURCE30} \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_bench.py
install -m 0755 %{SOURCE31} \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_demo.py
install -m 0755 %{SOURCE32} \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_inspect.py

# 录屏与观察点以子命令形式对外：实现留在库目录，入口只是符号链接，升级时
# 不需要在多处同步文件名，也不会出现 /usr/bin 与库目录两份实现。
install -d -m 0755 %{buildroot}%{_bindir}
ln -s ../lib/airymaxos/desktop/airy_record.sh %{buildroot}%{_bindir}/airy-record
ln -s ../lib/airymaxos/desktop/airy_observe.sh %{buildroot}%{_bindir}/airy-observe
ln -s ../lib/airymaxos/desktop/airy_bench.py %{buildroot}%{_bindir}/airy-bench
ln -s ../lib/airymaxos/desktop/airy_demo.py %{buildroot}%{_bindir}/airy-demo
ln -s ../lib/airymaxos/desktop/airy_inspect.py %{buildroot}%{_bindir}/airy-kernel
ln -s ../lib/airymaxos/desktop/airy_inspect.py %{buildroot}%{_bindir}/airy-os

install -d -m 0755 %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d
install -m 0644 %{SOURCE7} \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf

install -d -m 0755 %{buildroot}%{_sysconfdir}/ssh/sshd_config.d
install -m 0644 %{SOURCE16} \
    %{buildroot}%{_sysconfdir}/ssh/sshd_config.d/50-airymax-sshd.conf

# 网络全局策略：NetworkManager 按文件名字典序合并 conf.d，99 排在最后，
# 这里的键即生效值。目录可能由 NetworkManager 包提供，两个包同持一个目录
# 是允许的；目录本身也由本包声明，避免在未装该包的环境里留下悬空路径。
install -d -m 0755 %{buildroot}%{_sysconfdir}/NetworkManager/conf.d
install -m 0644 %{SOURCE34} \
    %{buildroot}%{_sysconfdir}/NetworkManager/conf.d/99-airymax.conf

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

# 触控板驱动归属与按下语义：70-synaptics.conf 随 ukui-settings-daemon 的硬依赖
# 进入闭包，且排在 40-libinput.conf 之后，会把每块触控板都交给不再维护的遗留
# 驱动。本文件以 Xorg 的 InputClass 覆盖顺序把已归 synaptics 的触控板改派
# libinput，再以第二段把 tapping/click 方法写进驱动层——libinput 的 Tapping
# 缺省关闭，等会话内的 settings-daemon 打开，登录界面前轻点无反应。根因与
# 285H 取证见文件头。目录属 xorg-x11-server，这里只落文件。
install -d -m 0755 %{buildroot}%{_sysconfdir}/X11/xorg.conf.d
install -m 0644 %{SOURCE42} \
    %{buildroot}%{_sysconfdir}/X11/xorg.conf.d/90-airymax-touchpad.conf

install -d -m 0755 %{buildroot}%{_sysconfdir}/grub.d
install -m 0755 %{SOURCE19} \
    %{buildroot}%{_sysconfdir}/grub.d/01_airymax_display

install -d -m 0755 %{buildroot}/usr/lib/airymaxos/boot
install -m 0755 %{SOURCE25} \
    %{buildroot}/usr/lib/airymaxos/boot/grub_args.sh
install -m 0755 %{SOURCE20} \
    %{buildroot}/usr/lib/airymaxos/boot/efi_brand.sh

install -d -m 0755 %{buildroot}%{_sysconfdir}/xdg/autostart
install -m 0644 %{SOURCE9} \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-input-method.desktop
install -m 0644 %{SOURCE24} \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-display.desktop
install -m 0644 %{SOURCE37} \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-update-notify.desktop

install -d -m 0755 %{buildroot}%{_sysconfdir}/systemd/system/user@.service.d
install -m 0644 %{SOURCE12} \
    %{buildroot}%{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf

# 平台主题变量是图形会话的属性，却经用户管理器环境被全部用户单元继承。
# 非 GUI 的 Qt 守护进程据此加载 ukui 平台主题插件，插件的字体回调随即对
# 不存在的 QApplication 调用 setFont 并崩溃（285H：kglobalaccel5 每周期
# 一次 SIGSEGV）。drop-in 只把该变量从这一个单元摘掉，不改插件、不改会话。
install -d -m 0755 \
    %{buildroot}%{_sysconfdir}/systemd/user/plasma-kglobalaccel.service.d
install -m 0644 %{SOURCE41} \
    %{buildroot}%{_sysconfdir}/systemd/user/plasma-kglobalaccel.service.d/50-airymax-kgaccel-env.conf

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

# 面板落点：ukui-panel 3.1 没有 quicklaunch 插件，首启动生成的 taskbar 组
# 只有一条空的 apps\size=0，于是面板上既没有文件管理器也没有浏览器，而
# 应用菜单之外没有任何可见入口（285H 实机：「桌面找不到浏览器」）。这里把
# 归一化后的面板配置装进 /etc/skel，新用户的家目录在装机器上创建时直接
# 带上两个钉住项与托盘白名单；装机器先装包后建用户，skel 复制发生在包就位
# 之后（/etc/skel/.bashrc 已如此落地）。
install -d -m 0755 %{buildroot}%{_sysconfdir}/skel/.config/ukui
install -m 0644 %{SOURCE43} \
    %{buildroot}%{_sysconfdir}/skel/.config/ukui/panel.conf

# 状态栏图标：kylin-nm 会按这三个标准名取图，ukui-themes 3.0.2 只提供带
# ukui- 前缀或换了词序的近似件。名字缺失时 Qt 不报错，只返回空图标，托盘
# 上留下一块透明区域，从日志里看不出任何异常。图形取自同一主题里已有的
# 三个权威版本，不另画一套。
airy_icons=%{buildroot}%{_datadir}/icons/hicolor/scalable/status
install -d -m 0755 "${airy_icons}"
install -m 0644 %{SOURCE38} \
    "${airy_icons}/network-wired-signal-excellent-symbolic.svg"
install -m 0644 %{SOURCE39} \
    "${airy_icons}/network-wireless-signal-excellent-error-symbolic.svg"
install -m 0644 %{SOURCE40} \
    "${airy_icons}/network-wireless-signal-low-secure-symbolic.svg"

# ukui-screensaver 3.1.1 在二进制里写死 QIcon::setThemeName("ukui-icon-theme-
# default")，这是 UKUI 4 的图标包名；24.03-LTS-SP3 的 ukui-themes 3.0.2
# 只装 ukui、ukui-classical、ukui-fashion。主题目录不存在时 Qt 静默失败，
# 锁屏右下角的网络、音量、电源三个图标全部消失。别名目录只是指向 ukui 的
# 符号链接，不复制任何图形，升级 ukui-themes 时自动跟随。
install -d -m 0755 %{buildroot}%{_datadir}/icons
ln -s ukui %{buildroot}%{_datadir}/icons/ukui-icon-theme-default

airy_bgs=%{buildroot}%{_datadir}/backgrounds/airymaxos
install -d -m 0755 "${airy_bgs}"
install -m 0644 %{SOURCE5} "${airy_bgs}/qilian_photo_from_zhenyi.jpg"
install -m 0644 %{SOURCE35} \
    "${airy_bgs}/clouds_moonlight_photo_from_lidecheng.jpg"
install -m 0644 %{SOURCE36} \
    "${airy_bgs}/hangzhouxihu_photo_from_lidecheng.jpg"

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
# 桌面版本被控制中心原样显示，格式固定为 "UKUI <版本>"。控制中心对不合格式
# 的内容回落为桌面名，构建期先挡住不合格内容，免得装机后只看到退化的界面。
LC_ALL=C grep -qxE 'UKUI [0-9][0-9A-Za-z._-]*' \
    %{buildroot}%{_sysconfdir}/airymaxos/desktop-version
# 命名两层模型在这里被锁定为可执行断言：PRETTY_NAME 的格式必须是
# 「<ASCII 短名> <VERSION_ID>」，短名即 distributor。ISO 卷标与 .treeinfo、
# 引导菜单条目名、/etc/system-release、/etc/issue 首行四处都从这一条派生，
# 格式一旦破坏，四处同时漂移且只在装机现场暴露，故构建期前置判定。
airy_osrel=%{buildroot}/usr/lib/os-release
airy_vid=$(sed -n 's/^VERSION_ID="\(.*\)"$/\1/p' "${airy_osrel}")
airy_pretty=$(sed -n 's/^PRETTY_NAME="\(.*\)"$/\1/p' "${airy_osrel}")
airy_dist=${airy_pretty%% *}
test "${airy_pretty}" = "${airy_dist} ${airy_vid}"
# 来源指纹：宏未注入即失败。缺省 unset 能通过安装（文件照样生成），但那样
# 发布清单与镜像对不上，且只有实机才发现，故在构建期判定。字符集不合法则
# sed 写出的是无法解析的 os-release；两处逐字相等是发布清单与运行期探针
# 共用的判据，任一侧漂移都会让 go/no-go 读错指纹。
test '%{airy_build_id}' != unset
airy_bid=$(sed -n 's/^BUILD_ID="\(.*\)"$/\1/p' "${airy_osrel}")
test -n "${airy_bid}"
printf '%s\n' "${airy_bid}" | LC_ALL=C grep -qxE '[A-Za-z0-9._+-]+'
grep -qxF "BUILD_ID=${airy_bid}" \
    %{buildroot}%{_sysconfdir}/airymaxos-build
test "$(stat -c %a %{buildroot}%{_sysconfdir}/airymaxos-build)" = 644
# distributor 是 ASCII-only 通道（引导菜单条目名与 NVRAM），含非 ASCII 字节即
# 判失败；NAME 允许中文全名，故只校验派生产物、不校验 NAME。
LC_ALL=C grep -qxE '[ -~]+' %{buildroot}%{_sysconfdir}/airymaxos-release
# system-release 的存在性与 anaconda 的解析结果一并断言：文件缺失或格式
# 不符都会让引导配置生成失败，必须在构建期而不是装机期暴露。
test -L %{buildroot}%{_sysconfdir}/system-release
test "$(readlink %{buildroot}%{_sysconfdir}/system-release)" = airymaxos-release
test "$(wc -l < %{buildroot}%{_sysconfdir}/airymaxos-release)" -eq 1
test "$(sed 's, release .*$,,g' \
    %{buildroot}%{_sysconfdir}/system-release)" = "${airy_dist}"
# 品牌面两处：登录提示前的 /etc/issue 首行逐字等于 PRETTY_NAME（与 os-release
# 同一事实源），第二行保留 agetty 转义（写死内核版本会让横幅与真实引导的内核
# 脱钩）；登录后的 /etc/motd.d/airymax 必须列全六个入口，且每个入口都是
# /usr/bin 下真实存在的符号链接——横幅里写了却装不出来的命令，比不写更糟。
airy_issue=%{buildroot}%{_sysconfdir}/issue
test "$(sed -n 1p "${airy_issue}")" = "${airy_pretty}"
grep -qxF 'Kernel \r on an \m (\l)' "${airy_issue}"
airy_motd=%{buildroot}%{_sysconfdir}/motd.d/airymax
for airy_cmd in airy-os airy-kernel airy-bench airy-observe airy-demo \
    airy-record; do
    grep -qF "  ${airy_cmd} " "${airy_motd}"
    test -L "%{buildroot}%{_bindir}/${airy_cmd}"
done
# 横幅同时给出不依赖 Airymax 代码的复核路径：判据落在标准工具的输出上，
# 任何一条被删掉都会让「换台机器也能验证」这句话失去依据。
for airy_std in 'uname -a' 'cat /etc/os-release' 'lscpu' 'free -h' 'ip -br addr' \
    'systemd-analyze' 'journalctl -b -p err'; do
    grep -qF "${airy_std}" "${airy_motd}"
done
# 客户端源配置：装机期的仓库闭包由 kickstart 的 url/repo 行声明，装完之后
# 的 dnf 只认本文件。0.0.3 发布前这里指向 repo.airymaxos.org（不存在的主
# 机）与 $releasever（展开为产品版本 0.0.3），于是安装器能装完、系统起来
# 却没有任何可解析的源。段集、版本串、镜像集三者都在构建期断言。
airy_repo=%{buildroot}%{_sysconfdir}/yum.repos.d/airymaxos.repo
for airy_sec in base updates epol epol-updates everything; do
    grep -qxF "[airymaxos-${airy_sec}]" "${airy_repo}"
done
if grep -qF '$releasever' "${airy_repo}"; then
    exit 1
fi
test "$(grep -cF "baseurl=https://repo.openeuler.org/%{oe_base}/" "${airy_repo}")" \
    -eq 5
test "$(grep -cF "https://mirrors.tuna.tsinghua.edu.cn/openeuler/%{oe_base}/" \
    "${airy_repo}")" -eq 5
test "$(grep -cF "https://mirrors.huaweicloud.com/openeuler/%{oe_base}/" \
    "${airy_repo}")" -eq 5
# SP3 的软件包与仓库元数据均无 PGP 签名，gpgcheck 若为 1 则 dnf 直接拒绝
# 每一个包；两者的取值必须与信任边界一致，而不是留待装机现场发现。
test "$(grep -c '^gpgcheck=0$' "${airy_repo}")" -eq 5
test "$(grep -c '^repo_gpgcheck=0$' "${airy_repo}")" -eq 5
test "$(grep -c '^enabled=1$' "${airy_repo}")" -eq 4
# everything 是可选扩展集合，默认关闭：日常升级只走与安装期同源的四段。
grep -A3 '^\[airymaxos-everything\]$' "${airy_repo}" | grep -qxF 'enabled=0'
grep -qF 'airymax_libdir' %{buildroot}%{_sysconfdir}/rpm/macros.airymax
grep -qF '/usr/lib/airymaxos' %{buildroot}%{_sysconfdir}/rpm/macros.airymax
grep -qxF 'CPUWeight=50' %{buildroot}%{_unitdir}/airymax-desktop.slice
grep -qxF 'WantedBy=graphical.target' \
    %{buildroot}%{_unitdir}/airymax-desktop-ready.service
bash -n %{buildroot}/usr/lib/airymaxos/desktop/desktop_ready.sh
bash -n %{buildroot}/usr/lib/airymaxos/desktop/boot_state.sh
# 首启音频初始化：条件取反写错（少了 !）会让每次启动都重设音量，把用户
# 调好的值抹掉，而这在服务状态里看不出来；触发点写错则单元永不执行，症状
# 仍是"开箱没声音"。两处都断言生效行本身。
grep -qxF 'ConditionPathExists=!/var/lib/alsa/asound.state' \
    %{buildroot}%{_unitdir}/airymax-audio-init.service
grep -qxF 'WantedBy=sound.target' \
    %{buildroot}%{_unitdir}/airymax-audio-init.service
grep -qxF 'After=alsa-state.service' \
    %{buildroot}%{_unitdir}/airymax-audio-init.service
bash -n %{buildroot}/usr/lib/airymaxos/desktop/audio_init.sh
test -x %{buildroot}/usr/lib/airymaxos/desktop/audio_init.sh
# 断言取调用点本身：脚本里是 `"${ALSACTL}" init` 与 `"${ALSACTL}" store`，
# 命令行中没有引号。此前写成 '" store"'（引号参与匹配）永不成立，把正确实现
# 判成红的，整轮组装停在 %%check（run 42578858068）。子命令两侧的空格是
# 唯一的可匹配锚点。
grep -qF ' init ' %{buildroot}/usr/lib/airymaxos/desktop/audio_init.sh
grep -qF ' store ' %{buildroot}/usr/lib/airymaxos/desktop/audio_init.sh
test -r %{buildroot}/usr/lib/airymaxos/desktop/boot_state.sh
# 录屏与观察点：实现是 POSIX sh，用 sh -n 断言而不是 bash -n，否则一份
# dash 下不可执行的脚本会被构建期放过。
sh -n %{buildroot}/usr/lib/airymaxos/desktop/session_env.sh
sh -n %{buildroot}/usr/lib/airymaxos/desktop/airy_record.sh
sh -n %{buildroot}/usr/lib/airymaxos/desktop/airy_observe.sh
# 两个标记前缀与偶数尺寸滤镜是验收侧解析的契约，改动即破坏对账。
grep -qxF 'MARK=AIRYMAX-RECORD' \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_record.sh
grep -qxF "PAD='pad=ceil(iw/2)*2:ceil(ih/2)*2'" \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_record.sh
grep -qxF 'MARK=AIRYMAX-OBSERVE' \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_observe.sh
# 静态报告在 buildroot 上真跑一次：资产路径、os-release 解析与 key=value
# 输出三者任何一处漂移都会让 os.id 行消失。
%{buildroot}/usr/lib/airymaxos/desktop/airy_observe.sh \
    --root %{buildroot} --static | grep -qxF 'AIRYMAX-OBSERVE os.id=airymaxos'
test -L %{buildroot}%{_bindir}/airy-record
test -L %{buildroot}%{_bindir}/airy-observe
# hardware 是转交给 airymax_observe 的子命令，本包不带那个模块；构建期能
# 断言的是入口把用法写清楚——装了 hardware 却不写进用法，等于没有这个入口。
%{buildroot}/usr/lib/airymaxos/desktop/airy_observe.sh --help |
    grep -qF 'airy-observe hardware'
# 基准脚本是 python3 而非 sh，语法断言改用 ast 解析（不产生 __pycache__），
# 再在 buildroot 上真跑一次 --check：管道与 socketpair 建不起来时这里失败，
# 而不是等到用户在机器上看到一串 traceback。
python3 -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_bench.py
%{buildroot}/usr/lib/airymaxos/desktop/airy_bench.py --check |
    grep -qxF 'AIRYMAX-BENCH status=ok'
test -L %{buildroot}%{_bindir}/airy-bench
# 展示入口只是渲染层：它必须能在 buildroot 上找到同目录的两个生产者并自检
# 通过，否则装机后 --check 会先在演示前失败。
python3 -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_demo.py
%{buildroot}/usr/lib/airymaxos/desktop/airy_demo.py --check |
    grep -qxF 'AIRYMAX-DEMO status=ok'
test -L %{buildroot}%{_bindir}/airy-demo
# 内核与整机取证：一份实现按 argv[0] 基名分派出两个入口，所以断言必须走
# %%{_bindir} 下的符号链接——直接跑实现文件只会得到用法错误。静态模式在
# buildroot 上真跑一次：没有 procfs 时 release 必须是 absent（缺项不省略
# 是本工具的契约），而 os.id 与免密账户必须能被同一条链读出。
python3 -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' \
    %{buildroot}/usr/lib/airymaxos/desktop/airy_inspect.py
test -L %{buildroot}%{_bindir}/airy-kernel
test -L %{buildroot}%{_bindir}/airy-os
%{buildroot}%{_bindir}/airy-kernel --root %{buildroot} |
    grep -qxF 'AIRYMAX-KERNEL kernel.release=absent'
%{buildroot}%{_bindir}/airy-os --root %{buildroot} |
    grep -qxF 'AIRYMAX-OS os.id=airymaxos'
%{buildroot}%{_bindir}/airy-os --root %{buildroot} |
    grep -qxF 'AIRYMAX-OS session.autologin=amuser'
# 类别集合必须同时覆盖 greeter 与 autologin：座位策略启用 autologin 时
# lightdm 不创建 greeter 会话，只认一类会让另一种镜像永远等不到就绪标记。
grep -qxF 'SESS_CLASSES="greeter user"' \
    %{buildroot}/usr/lib/airymaxos/desktop/desktop_ready.sh
bash -n %{buildroot}%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
grep -qxF 'user-session=ukui' \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
grep -qxF 'autologin-user=amuser' \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
grep -qxF 'PermitEmptyPasswords yes' \
    %{buildroot}%{_sysconfdir}/ssh/sshd_config.d/50-airymax-sshd.conf
# 网络策略：装机验收只看「首启 60s 内有路 DHCP 成功且网关可达」，而
# NM 的键写错不会让任何服务启动失败——它只表现为拿不到地址。两组键
# 逐字断言，段名也断言，避免键被并到别的段里静默失效。
airy_nm=%{buildroot}%{_sysconfdir}/NetworkManager/conf.d/99-airymax.conf
grep -qxF '[main]' "${airy_nm}"
grep -qxF 'dns=default' "${airy_nm}"
grep -qxF 'rc-manager=symlink' "${airy_nm}"
grep -qxF '[connectivity]' "${airy_nm}"
grep -qxF 'enabled=false' "${airy_nm}"
# 服务器档的键与上面的策略互斥：no-auto-default 会关掉插线自动 DHCP，
# ignore-carrier 会吞掉载波事件。只匹配生效行（不含注释），镜像里出现
# 其中任一键都说明依赖又被拉回。
for airy_key in no-auto-default ignore-carrier; do
    if grep -rsE "^[[:space:]]*${airy_key}[[:space:]]*=" \
        %{buildroot}%{_sysconfdir}/NetworkManager/conf.d; then
        exit 1
    fi
done
# 免密提权：sudo 会静默忽略模式不等于 0440 的 include 文件，所以权限与
# 内容要分别断言。有效规则必须恰好一条且为 airymax 的 NOPASSWD，防止
# 后续追加规则把「只放开一个账户」的收敛范围悄悄放宽。
test "$(stat -c %a %{buildroot}%{_sysconfdir}/sudoers.d/90-airymax)" = 440
airy_rule=$(grep -v '^#' %{buildroot}%{_sysconfdir}/sudoers.d/90-airymax |
    sed '/^$/d')
test "${airy_rule}" = 'amuser ALL=(ALL) NOPASSWD: ALL'
# 主机名不再经 sysctl.d 写回：0.0.4 起产品名是合法 RFC 1123 标签，安装器
# 直接落盘即可，/etc/hostname、hostname 与 hostnamectl --static 三处自然
# 一致。残留的内核层回写会让静态名与运行名分叉，这里断言它不再被打包。
! test -e %{buildroot}%{_sysconfdir}/sysctl.d/99-airymax-hostname.conf
# 锁屏策略：键名拼错或取值被改回 true 都不会让构建失败，只会在装机后以
# 「每五分钟一次口令框」或「唤醒后取不掉的锁屏」的形式出现，所以四个锁定
# 入口都要逐字断言。idle-activation-enabled 一关掉即不再拉起
# ukui-screensaver-dialog --session-idle，这是 0.0.4 的 285H 复验结论；
# sleep-activation-enabled 与另三个键独立判定，只关其中几个仍会在挂起唤醒
# 时锁屏。
airy_saver=%{buildroot}%{_sysconfdir}/dconf/db/local.d/00-airymax-screensaver
grep -qxF '[org/ukui/screensaver]' "${airy_saver}"
grep -qxF 'idle-activation-enabled=false' "${airy_saver}"
grep -qxF 'idle-lock-enabled=false' "${airy_saver}"
grep -qxF 'lock-enabled=false' "${airy_saver}"
grep -qxF 'sleep-activation-enabled=false' "${airy_saver}"
sh -n %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
sh -n %{buildroot}/usr/lib/airymaxos/desktop/display_mode.sh
sh -n %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh
# 触控板改派只有「先匹配 synaptics、再改派 libinput」同时成立才生效：少了
# MatchDriver 会连带把 evdev 触控板一起夺走，少了 Driver 则文件毫无作用，
# 两种错法都不会让构建失败，只在装机后表现为「触控板不能用」。逐行断言。
airy_tpad=%{buildroot}%{_sysconfdir}/X11/xorg.conf.d/90-airymax-touchpad.conf
grep -qxF '    MatchIsTouchpad "on"' "${airy_tpad}"
grep -qxF '    MatchDriver "synaptics"' "${airy_tpad}"
grep -qxF '    Driver "libinput"' "${airy_tpad}"
# 驱动归属与按下语义是两件事：改派成功只保证送到 libinput，Tapping 仍按
# libinput 缺省保持关闭，直到会话内的 settings-daemon 打开它。驱动层的默认
# 段因此也逐行断言——少了它，登录界面前轻点无反应，表现仍是「触控板不能用」。
grep -qxF '    Option "Tapping" "on"' "${airy_tpad}"
grep -qxF '    Option "TappingButtonMap" "lrm"' "${airy_tpad}"
grep -qxF '    Option "ClickMethod" "buttonareas"' "${airy_tpad}"
# 收敛入口有两个：早期钩子与会话就绪后的 autostart。任一处丢失都会退回
# 「一次性写入」，而那正是 T10 在验收基线上失败的形态，因此两处分别断言。
# autostart 必须是 --guard 而不是 --settle：settings-daemon 的回写晚于收敛
# 完成时刻，只有守护窗口能覆盖到它（验收轮 40610532780 的 T10 根因）。
grep -qF -- '--settle 10' \
    %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh
grep -qxF 'Exec=/usr/lib/airymaxos/desktop/display_mode.sh --guard 180' \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-display.desktop
# 分辨率策略在构建期以合成拓扑跑一遍，钉住 EDID 判定的两个方向：
# 无 EDID（0mm x 0mm）时 4K 首选按阶梯收到 1920x1080；有 EDID 时首选
# 模式原样保留，不写死任何机型上限（G-02）。awk 解析若随 xrandr 输出
# 格式漂移而失效，这里而不是装机现场暴露。
airy_plan=$(printf 'Screen 0: minimum 8 x 8, current 3840 x 2160, maximum 32767 x 32767\neDP-1 connected primary 3840x2160+0+0 (normal) 0mm x 0mm\n   3840x2160     60.00*+\n   1920x1080     60.00\n' | %{buildroot}/usr/lib/airymaxos/desktop/display_mode.sh --plan)
test "${airy_plan}" = 'eDP-1 3840x2160 1920x1080'
airy_native=$(printf 'Screen 0: minimum 8 x 8, current 2880 x 1800, maximum 32767 x 32767\neDP-1 connected primary 2880x1800+0+0 (normal) 301mm x 188mm\n   2880x1800     60.00*+\n   1920x1080     60.00\n' | %{buildroot}/usr/lib/airymaxos/desktop/display_mode.sh --plan)
test "${airy_native}" = 'eDP-1 2880x1800 2880x1800'
# 机型绑定常数是 G-02 的收口判据：脚本里出现 CAP_W=/CAP_H= 即回到了
# 「按 285H 定上限」的老路，必须在构建期失败。
! grep -qE 'CAP_[WH]=' %{buildroot}/usr/lib/airymaxos/desktop/display_mode.sh
# 引导期分辨率：这段必须无条件落 gfxmode 与 gfxterm。openEuler 的 00_header
# 把三行塞进 loadfont 成功的分支，字体缺失时整段静默跳过（D-28），所以这里
# 断言的是「我们输出的内容」，不是 cfg 里存在某条 gfxmode。
sh -n %{buildroot}%{_sysconfdir}/grub.d/01_airymax_display
airy_grub=$(%{buildroot}%{_sysconfdir}/grub.d/01_airymax_display)
printf '%s\n' "${airy_grub}" |
    grep -qxF '  set gfxmode=2880x1800,2560x1600,2240x1400,1920x1200,1920x1080,1680x1050,1600x900,1280x1024,1024x768,auto'
# gfxpayload 与 gfxmode 是一对：前者缺失时内核不沿用 GOP 模式，
# simpledrm 的 fb0 落在低分辨率，gfxmode 选得再高也白选。
printf '%s\n' "${airy_grub}" | grep -qxF '  set gfxpayload=keep'
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
# 启动参数持久化：bootloader --append 只进安装器本次生成的 grub.cfg，不进
# /etc/default/grub，此后每次 grub2-mkconfig 都会把 append 的内容丢掉（真机
# B50 的 /proc/cmdline 已复现）。控制台顺序同理：/dev/console 落在命令行里
# 最后一个 console= 上，旧顺序把 VT 让给了串口，systemd-vconsole-setup 在
# 285H 上因此每个启动周期失败。这里用 --no-regen 在临时文件上跑一遍改写，
# 断言「补参数、去重、覆盖注释行、控制台按序重放、摘掉旧画面参数、菜单停留
# 时间归一化、幂等、check 通过」。夹具里的 GRUB_TIMEOUT 取安装器的默认值，
# 命令行里的 quiet 是升级机器上必然还留着的旧画面参数，改写的目的是证明两
# 者都会收敛到脚本常量，而不是复述常量本身。
sh -n %{buildroot}/usr/lib/airymaxos/boot/grub_args.sh
airy_args=%{buildroot}/usr/lib/airymaxos/boot/grub_args.sh
airy_tmp=$(mktemp -d)
printf 'GRUB_TIMEOUT=3\nGRUB_CMDLINE_LINUX="console=tty0 quiet"\n#GRUB_DISABLE_OS_PROBER=true\n' \
    >"${airy_tmp}/grub"
"${airy_args}" --defaults "${airy_tmp}/grub" --no-regen >/dev/null
grep -qxF 'GRUB_TIMEOUT=1' "${airy_tmp}/grub"
grep -qxF 'GRUB_CMDLINE_LINUX="console=ttyS0,115200 console=tty0 loglevel=5 plymouth.enable=0"' \
    "${airy_tmp}/grub"
grep -qxF 'GRUB_DISABLE_OS_PROBER=true' "${airy_tmp}/grub"
airy_sum=$(sha256sum <"${airy_tmp}/grub")
"${airy_args}" --defaults "${airy_tmp}/grub" --no-regen >/dev/null
test "$(sha256sum <"${airy_tmp}/grub")" = "${airy_sum}"
"${airy_args}" --defaults "${airy_tmp}/grub" --check >/dev/null
# 字体落位：gfxmode 段落的前提是 $prefix/fonts/unicode.pf2，而 $prefix 由
# grubx64.efi 内嵌、指向发行版目录，不是品牌副本目录。B50 上字体进了
# never-loaded 的那份配置旁边，cfg 断言全绿、屏幕仍是 800x600（D-31）。
# 断言字体落在 --cfg 同目录，缺失时只降级不中止。
install -d "${airy_tmp}/efi/EFI/vendor"
printf 'menuentry v {}\n' >"${airy_tmp}/efi/EFI/vendor/grub.cfg"
printf 'pf2\n' >"${airy_tmp}/font.pf2"
printf '#!/bin/sh\nprintf "menuentry x {}\\n" >"$2"\n' >"${airy_tmp}/mk"
chmod 0755 "${airy_tmp}/mk"
"${airy_args}" --defaults "${airy_tmp}/grub" --state "${airy_tmp}/st/args" \
    --cfg "${airy_tmp}/efi/EFI/vendor/grub.cfg" \
    --font "${airy_tmp}/font.pf2" --mkconfig "${airy_tmp}/mk" >/dev/null
test "$(cat "${airy_tmp}/efi/EFI/vendor/fonts/unicode.pf2")" = pf2
"${airy_args}" --defaults "${airy_tmp}/grub" --state "${airy_tmp}/st/args" \
    --cfg "${airy_tmp}/efi/EFI/vendor/grub.cfg" \
    --font "${airy_tmp}/absent.pf2" --mkconfig "${airy_tmp}/mk" >/dev/null
rm -rf "${airy_tmp}"
grep -qxF 'Exec=/usr/bin/ibus-daemon -drx' \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-input-method.desktop
# 提醒条目必须直接调用子命令：外面再包一层脚本会吞掉 notify-send 的失败，
# 让「没有桌面会话」既无通知也无日志。去重由 check 写的状态承担，故这里
# 断言的是入口本身，而不是条目里的参数。
grep -qxF 'Exec=/usr/bin/airy-update notify' \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-update-notify.desktop
grep -qxF 'Slice=airymax-desktop.slice' \
    %{buildroot}%{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf
# 平台主题变量必须以 UnsetEnvironment 摘除，而不是赋空值：空值仍会被 Qt
# 当成「指定了插件名」而去找名为空的插件，失败路径与缺失相同但日志更难读。
grep -qxF '[Service]' \
    %{buildroot}%{_sysconfdir}/systemd/user/plasma-kglobalaccel.service.d/50-airymax-kgaccel-env.conf
grep -qxF 'UnsetEnvironment=QT_QPA_PLATFORMTHEME' \
    %{buildroot}%{_sysconfdir}/systemd/user/plasma-kglobalaccel.service.d/50-airymax-kgaccel-env.conf
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
# 内置壁纸集合恰为三张（R1-15）：多一张是上游壁纸漏进镜像，少一张是
# 注册表指向了不存在的文件，两种都在装机后才表现为空背景，故在构建期
# 直接数目录内容，而不是逐条断言三件存在。
airy_papers=%{buildroot}%{_datadir}/backgrounds/airymaxos
test "$(find "${airy_papers}" -maxdepth 1 -type f -name '*.jpg' | wc -l)" -eq 3
# 图标两处契约：GTK 侧键值与 Qt 侧主题名都必须解析到实际存在的目录。写错
# 任何一处都只在图形会话里表现为空白图标，文件系统与日志都看不出异常。
grep -qxF "icon-theme='ukui'" \
    %{buildroot}%{_datadir}/glib-2.0/schemas/99-airymaxos-default.gschema.override
# 默认输入法：preload-engines 为空时 ibus 只加载系统 XKB 布局，libpinyin
# 引擎虽然装进镜像却不在会话里，桌面表现就是「没有输入法」。登录后的当前
# 引擎取列表首位，因此这里断言的是两行的字面值，不是文件存在。
grep -qxF "preload-engines=['libpinyin','xkb:us::eng']" \
    %{buildroot}%{_datadir}/glib-2.0/schemas/99-airymaxos-default.gschema.override
grep -qxF "engines-order=['libpinyin','xkb:us::eng']" \
    %{buildroot}%{_datadir}/glib-2.0/schemas/99-airymaxos-default.gschema.override
test -L %{buildroot}%{_datadir}/icons/ukui-icon-theme-default
test "$(readlink %{buildroot}%{_datadir}/icons/ukui-icon-theme-default)" = ukui
airy_st=%{buildroot}%{_datadir}/icons/hicolor/scalable/status
for airy_svg in network-wired-signal-excellent-symbolic.svg \
                network-wireless-signal-excellent-error-symbolic.svg \
                network-wireless-signal-low-secure-symbolic.svg; do
    test -s "${airy_st}/${airy_svg}"
done

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

# 图标写进 hicolor 后必须重建 GTK 图标缓存：缓存里没有新条目时 GTK 与 Qt
# （Qt 也读同一份 cache）都判定图标不存在，而缓存不会因为目录里出现新文件
# 自动失效——这是图标装对了却仍然不显示的唯一原因。
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor >/dev/null 2>&1 || :
fi

%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh

# 控制台字体。默认的 latarcyrheb-sun16 是 8x16；在 285H 的 2880x1800 面板上
# 一屏是 360x112 个约 0.8x1.7 mm 的字形，九行阶段行即使全是 ASCII 也读不出
# 来（2026-11-09 实机）。同一 kbd 字体集里的 latarcyrheb-sun32 是 16x32，
# 切过去得到 180x56，不需要改内核配置，也不影响桌面：X 跑在 fbdev 上用自己的
# 分辨率与 Xft 字号。
#
# 只能在这里改。%%{_sysconfdir}/vconsole.conf 归 systemd-udev 包，本包再持有
# 同一路径会让安装事务整体失败（与 /etc/motd、plymouthd.conf 同一条约束）；
# vconsole.conf.d 的 drop-in 要 systemd 256，基线是 255。因此按行替换 FONT，
# 其余键（KEYMAP 等本包并不拥有的口径）原样保留。字体文件缺席时一个字节都不
# 写：指向不存在的字体只会让控制台黑屏，比小字更糟。
airy_font=latarcyrheb-sun32
airy_fonts=%{_prefix}/lib/kbd/consolefonts
if [ -f "${airy_fonts}/${airy_font}.psfu.gz" ]; then
    if grep -q '^[[:space:]]*FONT=' %{_sysconfdir}/vconsole.conf 2>/dev/null; then
        sed -i "s|^[[:space:]]*FONT=.*|FONT=\"${airy_font}\"|" \
            %{_sysconfdir}/vconsole.conf || :
    else
        printf 'FONT="%s"\n' "${airy_font}" >>%{_sysconfdir}/vconsole.conf || :
    fi
fi

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload >/dev/null 2>&1 || :
fi

%files
%defattr(-, root, root, -)
%{_sysconfdir}/os-release
/usr/lib/os-release
%{_sysconfdir}/airymaxos-build
%dir %{_sysconfdir}/airymaxos
%{_sysconfdir}/airymaxos/desktop-version
%{_sysconfdir}/airymaxos-release
%{_sysconfdir}/system-release
%config(noreplace) %{_sysconfdir}/issue
%config(noreplace) %{_sysconfdir}/motd.d/airymax
%config(noreplace) %{_sysconfdir}/yum.repos.d/airymaxos.repo
%config(noreplace) %{_sysconfdir}/rpm/macros.airymax
%config(noreplace) %{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
%config(noreplace) %{_sysconfdir}/ssh/sshd_config.d/50-airymax-sshd.conf
%dir %attr(0750, root, root) %{_sysconfdir}/sudoers.d
%config(noreplace) %attr(0440, root, root) %{_sysconfdir}/sudoers.d/90-airymax
%dir %{_sysconfdir}/NetworkManager/conf.d
%config(noreplace) %{_sysconfdir}/NetworkManager/conf.d/99-airymax.conf
%config(noreplace) %{_sysconfdir}/dconf/db/local.d/00-airymax-screensaver
%dir %{_sysconfdir}/skel/.config
%dir %{_sysconfdir}/skel/.config/ukui
%config(noreplace) %{_sysconfdir}/skel/.config/ukui/panel.conf
%config(noreplace) %{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
%config(noreplace) %{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh
%config(noreplace) %{_sysconfdir}/X11/xorg.conf.d/90-airymax-touchpad.conf
%config(noreplace) %{_sysconfdir}/grub.d/01_airymax_display
%config(noreplace) %{_sysconfdir}/xdg/autostart/airymax-input-method.desktop
%config(noreplace) %{_sysconfdir}/xdg/autostart/airymax-display.desktop
%config(noreplace) %{_sysconfdir}/xdg/autostart/airymax-update-notify.desktop
%config(noreplace) %{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf
%config(noreplace) %{_sysconfdir}/systemd/user/plasma-kglobalaccel.service.d/50-airymax-kgaccel-env.conf
%config(noreplace) %{_sysconfdir}/systemd/journald.conf.d/50-airymax-journald.conf
%{_unitdir}/airymax-desktop.slice
%{_unitdir}/airymax-desktop-ready.service
%{_unitdir}/airymax-audio-init.service
/usr/lib/airymaxos/desktop/desktop_ready.sh
/usr/lib/airymaxos/desktop/audio_init.sh
/usr/lib/airymaxos/desktop/boot_state.sh
/usr/lib/airymaxos/desktop/display_mode.sh
/usr/lib/airymaxos/desktop/xserver
/usr/lib/airymaxos/desktop/session_env.sh
/usr/lib/airymaxos/desktop/airy_record.sh
/usr/lib/airymaxos/desktop/airy_observe.sh
/usr/lib/airymaxos/desktop/airy_bench.py
/usr/lib/airymaxos/desktop/airy_demo.py
/usr/lib/airymaxos/desktop/airy_inspect.py
%{_bindir}/airy-record
%{_bindir}/airy-observe
%{_bindir}/airy-bench
%{_bindir}/airy-demo
%{_bindir}/airy-kernel
%{_bindir}/airy-os
/usr/lib/airymaxos/boot/efi_brand.sh
/usr/lib/airymaxos/boot/grub_args.sh
%{_datadir}/plymouth/themes/default.plymouth
%{_datadir}/ukui-background-properties/airymaxos-default.xml
%{_datadir}/glib-2.0/schemas/99-airymaxos-default.gschema.override
%{_datadir}/backgrounds/airymaxos/qilian_photo_from_zhenyi.jpg
%{_datadir}/backgrounds/airymaxos/clouds_moonlight_photo_from_lidecheng.jpg
%{_datadir}/backgrounds/airymaxos/hangzhouxihu_photo_from_lidecheng.jpg
%{_datadir}/icons/ukui-icon-theme-default
%{_datadir}/icons/hicolor/scalable/status/network-wired-signal-excellent-symbolic.svg
%{_datadir}/icons/hicolor/scalable/status/network-wireless-signal-excellent-error-symbolic.svg
%{_datadir}/icons/hicolor/scalable/status/network-wireless-signal-low-secure-symbolic.svg
%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
%{_datadir}/licenses/airymaxos-release/LICENSE

%changelog
* Mon Nov 09 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-15
- Stop the idle path from covering the desktop. 0.0.4-13 closed
  idle-lock-enabled and lock-enabled, but org.ukui.screensaver
  idle-activation-enabled was still true, and UKUI 3.1 does not show a
  neutral picture for it: it launches ukui-screensaver-dialog
  --session-idle, a screen shaped like the login prompt with the account
  name and a login button. The 285H reproduced it every five idle
  minutes; the dialog does not verify a password once the lock keys are
  false, but it still takes the whole session until the user acts, which
  reads as "the system locked itself again". Setting
  idle-activation-enabled=false stops the dialog from being spawned at
  all; verified on the machine by killing the dialog and observing that
  no --session-idle process returned. DPMS blanking by ukui-power-manager
  is untouched, manual locking still works, and %check now asserts all
  four keys.
* Mon Nov 09 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-14
- Move the virtual console to a 16x32 font. The image ships
  latarcyrheb-sun16 (8x16), and on the 285H's 2880x1800 panel that lays
  the screen out as 360x112 cells of roughly 0.8x1.7 mm each, so the nine
  boot stage lines stay unreadable in practice even now that ui.sh emits
  ASCII on that channel. latarcyrheb-sun32 belongs to the same kbd font
  set and gives 180x56 with no kernel change; the desktop is unaffected
  because X runs on fbdev at its own resolution with Xft sizes.
- /etc/vconsole.conf belongs to systemd-udev, so this package cannot own
  it without breaking the install transaction, and vconsole.conf.d needs
  systemd 256 while the base carries 255. %post therefore replaces the
  FONT line only: KEYMAP and every key this package does not own survive,
  and nothing is written when the font file is absent, because a font
  that is not there blanks the console instead of enlarging it.
* Mon Nov 09 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-13
- Close the last lock entry that a suspend reaches. The 285H was reported as
  "stuck at boot" after the lid was closed and reopened; the screen was the
  ukui screensaver unlock prompt, and the empty-password delivery account has
  no password to type. The compiled system db already carried
  lock-enabled=false and idle-lock-enabled=false, so the idle path was closed,
  but org.ukui.screensaver sleep-activation-enabled was still true and its
  description is precisely "lock the screen when the system goes sleep"; the
  three keys are evaluated independently. Set it false in the same policy
  source, and extend the %check line assertions to all three so a later edit
  cannot reopen one of them silently. The screensaver picture and DPMS stance
  are unchanged, and manual locking still works through
  ukui-screensaver-command -l.

* Mon Nov 09 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-12
- Initialize the mixer once on first boot so a fresh install is not silent.
  On the 285H the HDA codec powers up with Master at index 0 of 87 (-65.25 dB)
  and Master/Speaker Playback Switch off. Upstream /lib/alsa/init/hda only
  covers two old laptops and exits with the generic path; the generic method
  runs only through an explicit `alsactl init`, and alsa-state.service in
  rdaemon mode restores but never initializes (measured: with
  /var/lib/alsa/asound.state moved aside, restarting the unit left the mixer
  at 30/off). The silent state is then written back by the daemon at shutdown
  and imported by PulseAudio as 0% volume plus mute in its per-device store,
  so the machine stays silent across reboots while every unit reports success.
  airymax-audio-init.service runs at sound.target, gated by
  ConditionPathExists=!/var/lib/alsa/asound.state, so it touches the mixer
  exactly once; afterwards the user volume is owned by alsa-state.
  `alsactl init` exits 99 when the generic method applies, which is success
  and must not be logged as a failure. No codec-specific table is added, so
  ARM and RISC-V take the same path.

* Mon Nov 09 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-11
- Give touchpads usable click semantics before a session applies them. The
  driver reassignment in 90-airymax-touchpad.conf only decides who drives the
  device; libinput still reports Tapping Enabled Default = 0 on the 285H, and
  the value is only raised once ukui-settings-daemon reads
  org.ukui.peripherals-touchpad inside a session. At the greeter, on the first
  login before the daemon settles, and after the daemon restarts, a light tap
  does nothing, which reads as "the touchpad does not work". A second
  InputClass sets Tapping, TappingButtonMap=lrm, TappingDrag,
  ClickMethod=buttonareas, ScrollMethod=twofinger, NaturalScrolling=off and
  DisableWhileTyping=on at driver level with the same values the desktop
  stores, so the control centre still owns the setting and nothing changes
  once the session applies it. The build now asserts the three defaults that
  carry the click experience.

* Sun Nov 08 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-10
- Give every touchpad to libinput. xorg-x11-drv-synaptics-legacy reaches the
  closure as a hard dependency of ukui-settings-daemon, and its 70-synaptics.conf
  "touchpad catchall" sorts after 40-libinput.conf, so the legacy driver claimed
  every touchpad. On the 285H I2C-HID clickpad (ELAN06FA:00 04F3:3293) it logs
  "invalid pressure range" and "does not report pressure, will use touch data",
  leaving taps and gestures unusable while the kernel binding is intact, which
  is why T29 stayed green.
- A product-owned InputClass at /etc/X11/xorg.conf.d/90-airymax-touchpad.conf
  matches the touchpads already assigned to synaptics and reassigns them to
  libinput, the same mechanism 71-libinput-overrides-wacom.conf uses. Only the
  driver assignment changes: ukui-settings-daemon libmouse.so already speaks
  libinput for tapping, scrolling and disable-while-typing, and no package
  dependency or upstream source is touched. The spec now asserts the three
  matching lines at build time.

* Sat Nov 07 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-9
- Keep the UKUI Qt platform theme out of non-GUI Qt daemons. ukui-session
  writes QT_QPA_PLATFORMTHEME=ukui when it starts the session, and the
  variable ends up in the systemd user manager environment, so every user
  unit inherits it. plasma-kglobalaccel then loads
  libqt5-ukui-platformtheme.so, whose QGSettings font callback calls
  QApplication::setFont on a process that only has a QCoreApplication and
  dereferences a null instance. On the 285H this produced one SIGSEGV per
  start cycle with exactly that frame in the core dump.
- A user-unit drop-in unsets the variable for that unit only: the plugin is
  never loaded there, so the callback cannot fire. GUI applications are
  started by the session itself and keep the themed look. The plugin defect
  remains with upstream qt5-ukui-platformtheme 3.1.4 and is tracked for
  0.0.5 through the ukui-patches policy.
* Sat Nov 07 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-8
- Restore the status-bar icons missing from the graphical session. Two
  independent causes: ukui-screensaver 3.1.1 hardcodes the UKUI 4 theme name
  ukui-icon-theme-default while 24.03-LTS-SP3 only ships ukui, so the lock
  screen's network, volume and power icons resolved to nothing; and the GTK
  icon theme inherited from org.mate.interface still pointed at menta, which
  the closure does not carry, leaving every GTK application on hicolor.
- Ship an alias theme directory linking to ukui, point the GTK key at ukui,
  and rebuild the hicolor cache in %post. Qt and GTK both treat icons absent
  from that cache as missing even when the files are on disk, and the cache
  never invalidates on its own.
- Provide the three standard names kylin-nm requests but the theme never
  shipped: network-wired-signal-excellent, network-wireless-signal-excellent-
  error and network-wireless-signal-low-secure, derived from the existing
  graphics of the same theme.
* Tue Nov 03 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-6
- Stop counting every SSH connection as a password failure. With
  PermitEmptyPasswords yes, sshd probes PAM with an empty password before it
  looks at the method the client offered; for an account that does have a
  password that probe fails and pam_faillock records it, while pam_unix is
  sufficient so the success path never reaches pam_faillock authsucc to
  reset the tally. root was locked out on 285H after a few key-only logins.
- PasswordAuthentication is now off in the global scope and turned back on
  inside Match User amuser. The delivery account keeps its passwordless
  entry, and accounts that do have a password never enter password
  authentication at all. Verified on 285H with a test sshd: four key logins,
  no mm_auth_password in the log, no new faillock record.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-5
- Give the hardware survey a home inside the one observe command. The
  system package had started installing a second /usr/bin/airy-observe,
  so the two packages could not be installed together: rpm reported a file
  conflict on every machine that had both, and neither package could be
  upgraded alone to fix it. airy-observe now dispatches its hardware
  subcommand to the airymax_observe module and keeps the name to itself;
  when the module is missing it reports reason=no-hw-package and exits 2
  instead of printing a traceback the caller would take for a report. The
  help text names the subcommand, and the check asserts that line is there.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-4
- Sync the brand grub.cfg after every regeneration. On EFI the grub prefix
  is the directory of the loaded grubx64.efi, so the firmware entry under
  \EFI\airymaxos\ makes that copy the active configuration while
  grub2-mkconfig only writes EFI/openEuler. A marker written into both
  files and read back from /proc/cmdline after a reboot on 285H proved it.
  Without the sync, a changed command line or a new kernel kept booting
  the old entry. grub_args.sh now derives the brand directory from the
  generated config when --esp is absent, copies with install -m 700, and
  also places unicode.pf2 beside the brand copy, where loadfont actually
  looks. efi_brand.sh carries fonts and shimx64.hash into the branded
  directory for the same reason, and T15 fails when the two configs drift.
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-3
- Route /dev/console back to the VT: grub_args.sh now owns the console set
  and replays it serial-first, tty0-last. kernel binds /dev/console to the
  last console= on the command line, so the old tty0-first order left a
  headless machine locking /dev/console through ttyS0; on 285H that made
  systemd-vconsole-setup fail on every boot and took the desktop-ready
  gate with it. Rewriting drops consoles added by hand on site (the
  ARM64 ttyAMA0 on x86_64) instead of carrying them forward, and
  --append now refuses a console= argument rather than silently ordering
  it after tty0.
- Match the installer recipe to the same order so the first boot uses it
  too, and let the T15 smoke check fail on either a wrong primary console
  or a foreign console in /etc/default/grub.
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-2
- Move the RT budget out of this package: airymaxos-system now ships
  airy-rt-cap, the airymax_rt package and airy-rt-bandwidth.service,
  which apply the same policy from one implementation instead of a
  shell copy that only this package could update
* Mon Nov 02 2026 SPHARX <dev@spharx.com> - 0.0.4-1
- Adopt the two-layer display-name model: NAME is the human-readable full
  name (may carry Chinese), PRETTY_NAME is the ASCII brand plus VERSION_ID
  and becomes the only source of /etc/system-release, /etc/issue and the
  ISO / boot-menu product name. Deriving those ASCII channels from NAME
  made build-iso refuse to assemble the image as soon as NAME stopped
  being ASCII, and would have put mojibake in the grub menu on non-UTF-8
  consoles. %check now asserts the PRETTY_NAME format invariant, the
  distributor parsed out of system-release and the issue first line,
  rather than a literal brand string
- Rename the machine name to airymax-pc and drop the sysctl.d kernel
  write-back: AIRYMAX_PC carried an underscore, which systemd strips per
  RFC 1123, so the package shipped a drop-in rewriting kernel.hostname
  after sysinit and the static and runtime names disagreed by design.
  The installer now writes a legal RFC 1123 label, so /etc/hostname,
  hostname and hostnamectl --static agree without a second mechanism.
  %check asserts the drop-in is no longer shipped
- Rename the delivery account from Airymax to amuser: the mixed-case
  name was accepted by shadow-utils, but case-sensitive filesystems and
  per-base NAME_REGEX policies disagree, so the account and its home
  directory could diverge on a shipped image. The lowercase name needs
  no policy override. The seat, the single sudo rule, the smoke checks
  and the site suffix move with it, and %check pins the same account
  name in all of them
- Restrict the built-in wallpaper set to the three brand defaults named in
  lockfile/ukui-wallpapers.yaml and stop shipping the derived
  airymaxos-default.jpg alias: the registry, the default background and
  the files on disk were three separate lists, so a change to one of them
  silently left the other two pointing at a missing file. The registry
  now lists exactly the three, the schema override selects one of them,
  and %check counts the directory instead of asserting three separate
  paths, which also catches an upstream wallpaper package leaking in
- Version bump to 0.0.4
* Mon Nov 02 2026 SPHARX <dev@spharx.com> - 0.0.3-27
- Ship /etc/NetworkManager/conf.d/99-airymax.conf: the desktop policy
  states dns=default with rc-manager=symlink (no plugin is installed,
  and a missing plugin leaves resolv.conf unwritten while the lease
  still succeeds) and disables connectivity probing (isolated install
  networks are reported as limited and trigger reconnect churn)
- Drop NetworkManager-config-server from the core group: its
  no-auto-default and ignore-carrier keys disable automatic wired DHCP
  and swallow carrier events, so a freshly plugged cable never becomes
  a default connection. %check rejects either key in the build root
* Fri Oct 30 2026 SPHARX <dev@spharx.com> - 0.0.3-26
- List the stock Linux cross-checks in /etc/motd.d/airymax next to the
  six Airymax entry points: uname, os-release, lscpu, free, lsblk, ip,
  systemd-analyze and journalctl. A reviewer can re-derive every number
  without running any Airymax code, and %check asserts that the list
  cannot be trimmed silently
* Fri Oct 30 2026 SPHARX <dev@spharx.com> - 0.0.3-25
- Ship /etc/issue as AirymaxOS: no package owns that path on the target,
  so the pre-login banner kept the generic upstream template. Kernel
  release, machine and tty stay agetty escapes, so the banner cannot
  drift from the kernel that actually booted
- Ship the terminal entry points as /etc/motd.d/airymax rather than
  /etc/motd: setup owns the latter and a second owner would break the
  install transaction, while pam_motd 1.5.3 already reads the drop-in
  directory. Each named command is also asserted to exist as a symlink
* Fri Oct 30 2026 SPHARX <dev@spharx.com> - 0.0.3-24
- Fix the delivery account name to Airymax and the machine name to
  AIRYMAX_PC across kickstart, seat policy, sudo policy, site suffix and
  smoke checks: the three assets disagreeing was the root cause of a
  desktop that never auto-logged in on a renamed account
- Ship /etc/sysctl.d/99-airymax-hostname.conf: systemd strips the
  underscore from /etc/hostname per RFC 1123, so the runtime name is
  written back at the kernel level after sysinit
- Keep the smoke host expectation aligned with the recipe, so a hostname
  drift fails the acceptance run instead of the field
* Thu Oct 29 2026 SPHARX <dev@spharx.com> - 0.0.3-23
- Ship airy-demo, a terminal-only overview that renders identity and IPC
  capability from airy-observe and airy-bench. It computes nothing itself:
  every number on screen is recomputable by those two commands, so the
  report does not depend on the renderer being trusted
- Draw the three round-trip primitives against a shared baseline and add
  a 1/2/4/8-process sweep (median of three runs per level) so scaling is
  visible as a curve rather than a single point
- airy-record grows --tty: util-linux script(1) captures the terminal
  byte stream plus timings into .log and .timing, replayable with
  scriptreplay. No X server and no ffmpeg required; uses --log-timing
  because -t no longer accepts a separate argument on util-linux 2.41
* Thu Oct 29 2026 SPHARX <dev@spharx.com> - 0.0.3-22
- Ship airy-bench: three kernel IPC primitives (pipe, AF_UNIX stream,
  AF_UNIX datagram) measured as warm-up-discarded round-trip latency
  percentiles, plus 64 KiB bulk pipe throughput and a multi-process
  concurrency scale factor. Every claim about IPC speed now carries a
  number produced on the same machine by the same code, and the tool
  can be replayed by a third party
- Report lang=python3 on the host line: the interpreter adds a GIL
  hand-off and an object allocation per round trip, so the p50 is the
  application-visible cost rather than the bare system call cost;
  cross-machine comparison is only valid with that line in context
- Percentiles come from a sorted per-sample array, rates from the
  measured span, no extrapolation and no smoothing. --check exercises
  each primitive 200 times without timing and is asserted at build
  time, so a container without socketpair support fails the package
  build instead of the user's first run
* Thu Oct 29 2026 SPHARX <dev@spharx.com> - 0.0.3-21
- Ship two first-party observation tools: airy-record captures the X11
  session with x11grab and the default sink monitor, prints a progress
  line every two seconds while recording and ends with path, frames,
  size and sha256; airy-observe reports the release identity, brand
  assets, kernel package ownership and desktop chain as key=value lines
- Resolve DISPLAY and XAUTHORITY through logind in a shared library
  instead of asking the caller to supply them: over SSH or from a unit
  there is no DISPLAY, and a stale XAUTHORITY only shows up as an
  unrelated "cannot open display" from every consumer
- Both tools are POSIX sh and self-check without a session (--check,
  --static), so packaging asserts them at build time instead of on the
  installed machine; ffmpeg stays a weak dependency because it lives in
  EPOL and a hard Requires would abort an install on a metadata gap
* Thu Oct 29 2026 SPHARX <dev@spharx.com> - 0.0.3-20
- Create the slice cgroups before writing the RT budget: systemd on
  cgroup v1 creates unit cgroups per controller on demand, so a slice
  whose units never enabled the cpu controller has no directory in the
  cpu hierarchy yet. The previous run skipped every group that did not
  exist, finished successfully and reported ok with applied=0 — the
  reference machine therefore still logged "Failed to make ourselves
  RT" on every boot after the 0.0.3-19 fix, while the same script run
  by hand on the live system applied three of four groups
- Read every value back and stop reporting a run as success: a group
  that cannot be created, written or accepted by the kernel now counts
  as missing, and status degrades from ok to partial (some groups) or
  failed (none). A budget that silently did nothing is worse than a
  budget that admits it did nothing
- Print wanted= and missing=[...] alongside applied= so the boot log
  says which slices were left out instead of only how many worked
* Wed Oct 28 2026 SPHARX <dev@spharx.com> - 0.0.3-19
- Allocate RT bandwidth per slice at boot: with CONFIG_RT_GROUP_SCHED a
  new cgroup gets cpu.rt_runtime_us=0, and 0 means "forbidden" rather
  than "unlimited", so every sched_setscheduler(SCHED_RR) inside it
  fails with EPERM and rtkit-daemon logged "Failed to make ourselves
  RT" on every start while still reporting the daemon as running
- Split the total budget instead of handing it to one slice: the budget
  is hierarchical and children may not exceed the parent, so filling
  system.slice made user.slice writes fail with EINVAL and SSH sessions
  could never raise RT either (measured on the reference machine)
- Order the unit before rtkit-daemon and the display manager, and keep
  it non-fatal: a missing budget degrades audio latency, while failing
  the boot would turn that into "no desktop"
* Wed Oct 28 2026 SPHARX <dev@spharx.com> - 0.0.3-18
- Place unicode.pf2 next to the grub.cfg that is actually loaded: the
  gfxmode stanza only exists when loadfont succeeds, and loadfont reads
  $prefix/fonts, where $prefix is baked into grubx64.efi and points at
  the base distribution's ESP directory, not at the branded copy, so the
  reference machine stayed at 800x600 with a correct-looking config
- Resolve that path from /etc/grub2-efi.cfg instead of globbing EFI/*,
  and let the installer read the result from the grub_args.sh state file:
  the old glob picked a config file grub never loads, so both the font
  and the regenerated menu landed where they had no effect
- Degrade with a note when no font source exists: a missing font is a
  cosmetic and resolution defect, never a reason to abort an install
* Wed Oct 28 2026 SPHARX <dev@spharx.com> - 0.0.3-17
- Start the seat through a distribution wrapper and fall back to fbdev
  when the only DRM device is simpledrm: X 1.20 picks vesa when no
  driver claims the card, vesa refuses to run next to a synthetic
  framebuffer, and modesetting does not take simpledrm over either, so
  lightdm died on every start on the reference machine and the desktop
  never appeared
- Decide by driver name in sysfs rather than by hardware, so machines
  with a real KMS driver (i915, amdgpu, virtio_gpu, nouveau) keep X's
  automatic choice and need no per-machine tuning
- Log one AIRYMAX-XSERVER line with the chosen path: without it the only
  evidence of the decision is an X log nobody reads until the desktop
  fails
* Wed Oct 28 2026 SPHARX <dev@spharx.com> - 0.0.3-16
- Ship grub_args.sh and call it from the installer before efi_brand.sh:
  bootloader --append only reaches the grub.cfg anaconda writes, never
  /etc/default/grub, so every later grub2-mkconfig dropped rhgb quiet and
  the boot went back to scrolling kernel log lines (/proc/cmdline on the
  reference machine had neither parameter)
- Set GRUB_DISABLE_OS_PROBER=true there as well: with os-prober enabled
  the same disk's other distributions land in this product's boot menu
  (19 entries, two of them foreign kernels); other systems stay reachable
  through the firmware boot menu
- Keep the previous grub.cfg when regeneration fails and report it as a
  skip: being able to boot outranks a tidy menu, and the old config still
  carries the installer's --append parameters
* Wed Oct 28 2026 SPHARX <dev@spharx.com> - 0.0.3-15
- Point the installed system at repositories that exist. Every baseurl
  named repo.airymaxos.org, a host that does not resolve, and the paths
  were built from $releasever, which expands to the product version
  0.0.3 rather than the base release: the installer completed, then dnf
  had no repository it could reach
- Mirror the kickstart repository set one to one (base, updates, epol,
  epol-updates, everything) and list three mirrors per section, since a
  single upstream host going down must not leave the system unable to
  upgrade. everything stays disabled by default
- Drop gpgcheck and repo_gpgcheck to 0: openEuler 24.03 LTS SP2 ships
  packages and metadata without a PGP signature (SIGPGP reads (none)),
  so a nonzero check rejects every package. Integrity rests on HTTPS
  until the own base and keyring land in 0.1.x
- Make the base release an explicit input (%oe_base) and assert the
  section set, the version string, the three mirrors and the flag values
  in %check, so drift fails the build instead of the install

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
