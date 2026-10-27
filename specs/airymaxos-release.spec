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
#   5. %%post 只执行装配后才能确定的运行期动作：编译 glib schema、屏蔽桌面
#      自带 AI 控制面单元、在运行中的系统上重载 systemd。
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
%global airy_release 4
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

Provides:       system-release
Provides:       system-release(releasever)
Obsoletes:      openEuler-release < 24.04
Requires:       systemd

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

install -d -m 0755 %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d
install -m 0755 %{SOURCE8} \
    %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
install -m 0755 %{SOURCE18} \
    %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh

install -d -m 0755 %{buildroot}%{_sysconfdir}/grub.d
install -m 0755 %{SOURCE19} \
    %{buildroot}%{_sysconfdir}/grub.d/01_airymax_display

install -d -m 0755 %{buildroot}%{_sysconfdir}/xdg/autostart
install -m 0644 %{SOURCE9} \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-input-method.desktop

install -d -m 0755 %{buildroot}%{_sysconfdir}/systemd/system/user@.service.d
install -m 0644 %{SOURCE12} \
    %{buildroot}%{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf

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
bash -n %{buildroot}%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
grep -qxF 'user-session=ukui' \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
grep -qxF 'autologin-user=airymax' \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
grep -qxF 'PermitEmptyPasswords yes' \
    %{buildroot}%{_sysconfdir}/ssh/sshd_config.d/50-airymax-sshd.conf
sh -n %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
sh -n %{buildroot}/usr/lib/airymaxos/desktop/display_mode.sh
sh -n %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh
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
grep -qxF 'Exec=/usr/bin/fcitx' \
    %{buildroot}%{_sysconfdir}/xdg/autostart/airymax-input-method.desktop
grep -qxF 'Slice=airymax-desktop.slice' \
    %{buildroot}%{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf
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
%config(noreplace) %{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
%config(noreplace) %{_sysconfdir}/X11/xinit/xinitrc.d/60-airymax-display.sh
%config(noreplace) %{_sysconfdir}/grub.d/01_airymax_display
%config(noreplace) %{_sysconfdir}/xdg/autostart/airymax-input-method.desktop
%config(noreplace) %{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf
%{_unitdir}/airymax-desktop.slice
%{_unitdir}/airymax-desktop-ready.service
/usr/lib/airymaxos/desktop/desktop_ready.sh
/usr/lib/airymaxos/desktop/boot_state.sh
/usr/lib/airymaxos/desktop/display_mode.sh
%{_datadir}/ukui-background-properties/airymaxos-default.xml
%{_datadir}/glib-2.0/schemas/99-airymaxos-default.gschema.override
%{_datadir}/backgrounds/airymaxos/airymaxos-default.jpg
%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
%{_datadir}/licenses/airymaxos-release/LICENSE

%changelog
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
