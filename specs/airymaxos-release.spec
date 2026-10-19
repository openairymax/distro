# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-release — AirymaxOS 发行版标识与桌面集成包
#
# 职责：
#   1. 提供 /usr/lib/os-release 与 /etc/os-release 符号链接（VERSION_ID 唯一
#      事实源为仓库内 release/os-release）；
#   2. 提供 /etc/yum.repos.d/airymaxos.repo（仓库列表 SSoT）；
#   3. 提供 /etc/rpm/macros.airymax（文件系统布局宏 SSoT）；
#   4. 部署桌面会话静态资产：lightdm 座位策略、X11 会话输入法环境、输入法
#      自启项、UKUI 壁纸注册表与背景默认值、默认壁纸、桌面调度 slice、
#      user@.service 挂接及登录链就绪探针；
#   5. %%post 只执行装配后才能确定的运行期动作：屏蔽桌面自带 AI 控制面单元、
#      固定默认 target、编译 glib schema、重载 systemd。
#
# 静态资产一律由 %%install 直接落到最终路径，%%post 不复制文件，同一路径只有
# 一处事实来源。
#
# 与基础发行版的关系：openEuler 24.03 LTS 的 release 包同占 /etc/os-release，
# 因此本包以 system-release 虚拟能力接管该位置，并显式 Obsoletes 旧包。
#
# 构建约束：全部 Source 为仓库内裸文件名，由构建流水线 staging 到
# _sourcedir 后 rpmbuild；配方本身不生成任何内容。
# ===========================================================================

%global airy_version 0.0.3
%global airy_release 1
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

install -d -m 0755 %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d
install -m 0644 %{SOURCE7} \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf

install -d -m 0755 %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d
install -m 0755 %{SOURCE8} \
    %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh

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
grep -qxF '[airymaxos-base]' %{buildroot}%{_sysconfdir}/yum.repos.d/airymaxos.repo
grep -qF 'airymax_libdir' %{buildroot}%{_sysconfdir}/rpm/macros.airymax
grep -qF '/usr/lib/airymaxos' %{buildroot}%{_sysconfdir}/rpm/macros.airymax
grep -qxF 'CPUWeight=50' %{buildroot}%{_unitdir}/airymax-desktop.slice
grep -qxF 'WantedBy=graphical.target' \
    %{buildroot}%{_unitdir}/airymax-desktop-ready.service
bash -n %{buildroot}/usr/lib/airymaxos/desktop/desktop_ready.sh
bash -n %{buildroot}%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
grep -qxF 'user-session=ukui' \
    %{buildroot}%{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
sh -n %{buildroot}%{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
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
%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh

if [ -f %{_datadir}/glib-2.0/schemas/org.mate.background.gschema.xml ] &&
   command -v glib-compile-schemas >/dev/null 2>&1; then
    glib-compile-schemas %{_datadir}/glib-2.0/schemas
fi

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload >/dev/null 2>&1 || :
fi

%files
%defattr(-, root, root, -)
%{_sysconfdir}/os-release
/usr/lib/os-release
%config(noreplace) %{_sysconfdir}/yum.repos.d/airymaxos.repo
%config(noreplace) %{_sysconfdir}/rpm/macros.airymax
%config(noreplace) %{_sysconfdir}/lightdm/lightdm.conf.d/50-airymax.conf
%config(noreplace) %{_sysconfdir}/X11/xinit/xinitrc.d/70-airymax-im.sh
%config(noreplace) %{_sysconfdir}/xdg/autostart/airymax-input-method.desktop
%config(noreplace) %{_sysconfdir}/systemd/system/user@.service.d/50-airymax-desktop.conf
%{_unitdir}/airymax-desktop.slice
%{_unitdir}/airymax-desktop-ready.service
/usr/lib/airymaxos/desktop/desktop_ready.sh
%{_datadir}/ukui-background-properties/airymaxos-default.xml
%{_datadir}/glib-2.0/schemas/99-airymaxos-default.gschema.override
%{_datadir}/backgrounds/airymaxos/airymaxos-default.jpg
%{_datadir}/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
%{_datadir}/licenses/airymaxos-release/LICENSE

%changelog
* Sun Oct 18 2026 SPHARX <dev@spharx.com> - 0.0.3-1
- Ship the UKUI session policy assets: lightdm seat, input method
  environment and autostart, wallpaper registry and background default,
  desktop slice and user@.service drop-in
- Add airymax-desktop-ready.service and its probe script so image CI can
  assert the lightdm greeter session is reachable after boot
