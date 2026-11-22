# SPDX-License-Identifier: GPL-2.0-or-later
# ===========================================================================
# ukui-settings-daemon.spec — AirymaxOS 的上游重建配方
#
# 本配方不新增源码：源码包取自 openEuler 24.03 LTS SP3 EPOL 的同名
# src.rpm，补丁序列与上游保持一致，只叠加一个下游补丁：
#
#   Patch300  夜览配置读取：校验 KWin 应答，只用可 marshalling 的值
#             构造 a{sv}，消除会话内进程级 abort
#
# 事实源：tarball 不入库，source-rpm 声明用官方 src.rpm 的摘要传递性钉住
# 成员内容；补丁随本目录入库，逐字节可复算。
#
# Release 必须写全基底的发行标记（9.oe2403sp3.airy2），不能用
# %{?dist}：构建容器不定义 dist 宏，该写法会折叠成 9.airy2，在 RPM 的
# EVR 比较里低于基底 9.oe2403sp3（'a' < 'o'），求解器会选上游未打补丁
# 的包，补丁静默丢失。写全后既高于基底，也不会与基底同 EVR。
#
# License 沿用上游 spec 的复合声明：源码树内 GPL-2.0-or-later、
# GPL-3.0-or-later 与 LGPL-2.0-or-later 按文件分别适用。
# ===========================================================================

# spec-lint: source-rpm ukui-settings-daemon-3.1.2.tar.gz https://repo.openeuler.org/openEuler-24.03-LTS-SP3/EPOL/main/source/Packages/ukui-settings-daemon-3.1.2-9.oe2403sp3.src.rpm 537bae0b0ae8b78c5ef545831078db2ea222eefebb6104aa4ea1ec86f0068583

Name:           ukui-settings-daemon
Version:        3.1.2
Release:        9.oe2403sp3.airy2
Summary:        daemon handling the UKUI session settings
License:        GPL-2.0-or-later and GPL-3.0-or-later and LGPL-2.0-or-later
URL:            http://www.ukui.org
Source0:        %{name}-%{version}.tar.gz
Patch1:         0001-modify-compile-error-of-ukui-settings-daemon.patch
Patch2:         Fix-the-failure-of-shortcut-key-to-open-terminal.patch
Patch4:         ukui-settings-daemon-3.1.2-kylin-fix-coredump.patch
Patch5:         session.patch
Patch6:         fix-ukui-settings-daemon-SIGSEGV.patch
Patch7:         fix-ukui-settings-daemon-SIGABRT.patch
Patch100:       ukui-settings-daemon-qt5.15-cxx17.patch
Patch300:       fix-color-abort-on-unusable-kwin-reply.patch
BuildRequires:  pkgconf-pkg-config
BuildRequires:  intltool
BuildRequires:  qtchooser
BuildRequires:  qt5-qtbase-devel
BuildRequires:  qt5-qttools-devel
BuildRequires:  gsettings-qt-devel
BuildRequires:  qt5-qtx11extras-devel
BuildRequires:  qt5-qtsensors-devel
BuildRequires:  kf5-kconfig-devel
BuildRequires:  qt5-qtsvg-devel
BuildRequires:  libxklavier-devel
BuildRequires:  libXtst-devel
BuildRequires:  mate-desktop-devel
BuildRequires:  gnome-desktop3-devel
BuildRequires:  libmatemixer-devel
BuildRequires:  libmatekbd-devel
BuildRequires:  pulseaudio-libs-devel
BuildRequires:  libwnck3-devel
BuildRequires:  libcanberra-devel
BuildRequires:  libwayland-client
BuildRequires:  libnotify-devel
BuildRequires:  geoclue2-devel
BuildRequires:  colord-devel
BuildRequires:  lcms2-devel
BuildRequires:  imlib2-devel
BuildRequires:  xorg-x11-server-devel
BuildRequires:  libgudev-devel
BuildRequires:  libxcb-devel
BuildRequires:  xcb-util-devel
BuildRequires:  libX11-devel
BuildRequires:  kf5-kwindowsystem-devel
BuildRequires:  libkscreen-qt5-devel
BuildRequires:  libxkbcommon-devel
BuildRequires:  kf5-kglobalaccel-devel
BuildRequires:  ukui-interface

Requires:       mate-desktop-libs ukui-settings-daemon-common colord imwheel ukui-polkit xorg-x11-server-utils xorg-x11-drv-synaptics-legacy glib2-devel
%description
 This package contains the daemon which is responsible for setting the
 various parameters of a UKUI session and the applications that run
 under it. It handles the following kinds of settings:
 .
  * Keyboard: layout, accessibility options, shortcuts, media keys
  * Clipboard management
  * Theming: background, icons, GTK+ applications
  * Cleanup of unused files
  * Mouse: cursors, speed, accessibility options
  * Startup of other daemons: screensaver, sound daemon
  * Typing break
 .
 It also sets various application settings through X resources and
 freedesktop.org XSETTINGS.

%package common
Summary:        daemon handling the UKUI session settings (common files)

%description common
 This package contains the daemon which is responsible for setting the
 various parameters of a UKUI session and the applications that run
 under it. It handles the following kinds of settings:
 .
  * Keyboard: layout, accessibility options, shortcuts, media keys
  * Clipboard management
  * Theming: background, icons, GTK+ applications
  * Cleanup of unused files
  * Mouse: cursors, speed, accessibility options
  * Startup of other daemons: screensaver, sound daemon
  * Typing break
 .
 It also sets various application settings through X resources and
 freedesktop.org XSETTINGS.
 .
 This package contains the architecture independent files.

%prep
%autosetup -n %{name}-%{version} -p1

%build
%{qmake_qt5}
%{make_build}

%install
rm -rf %{buildroot}
make INSTALL_ROOT=%{buildroot} install
mkdir -p %{buildroot}/usr/share/man/man1
mkdir -p %{buildroot}/usr/share/man/man2

gzip -c %{_builddir}/%{name}-%{version}/man/touchpad-state.1 > %{buildroot}/usr/share/man/man1/touchpad-state.1.gz
gzip -c %{_builddir}/%{name}-%{version}/man/ukui-settings-daemon.1 > %{buildroot}/usr/share/man/man1/ukui-settings-daemon.1.gz
gzip -c %{_builddir}/%{name}-%{version}/man/usd-locate-pointer.1 > %{buildroot}/usr/share/man/man1/usd-locate-pointer.1.gz

%clean
rm -rf %{buildroot}

%post
set -e &> /dev/null || :
glib-compile-schemas /usr/share/glib-2.0/schemas/ &> /dev/null || :

%files
%doc debian/changelog debian/copyright
%{_sysconfdir}/*
%{_prefix}/%{_lib}/ukui-settings-daemon/
%{_datadir}/dbus-1/*
/lib/udev/rules.d/01-touchpad-state-onmouse.rules
/usr/bin/authoritydbus
/usr/bin/touchpad-state
/usr/bin/ukui-settings-daemon
/usr/bin/ukydisplayswitch
/usr/bin/usd-locate-pointer

%files common
%doc debian/changelog debian/copyright
%{_datadir}/glib-2.0/
%{_datadir}/locale/
%{_datadir}/ukui-settings-daemon/
%{_datadir}/man/*

%changelog
* Sat Nov 22 2026 Liren Wang <wangliren@spharx.cn> - 3.1.2-9.oe2403sp3.airy2
- Patch300: log KWin reply signature and per-key variant types

* Sat Nov 21 2026 Liren Wang <wangliren@spharx.cn> - 3.1.2-9.oe2403sp3.airy1
- Add Patch300: validate KWin night-color reply before marshalling a{sv}

* Wed Aug 16 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-9
- Type:bugfix
- ID:NA
- SUG:NA
- DESC: add fix-build-error-of-libkscreen-qt5-5.27.6.patch

* Fri Jul 21 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-8
- Type:bugfix
- ID:NA
- SUG:NA
- DESC:add Patch7:fix-ukui-settings-daemon-SIGABRT.patch

* Tue Jul 18 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-7
- Type:bugfix
- ID:NA
- SUG:NA
- DESC:add Patch6:fix-ukui-settings-daemon-SIGSEGV.patch

* Tue Jul 11 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-6
- Type:bugfix
- ID:NA
- SUG:NA
- DESC:add Patch5:session.patch

* Mon Jul 10 2023 huayadong <huayadong@kylinos.cn> - 3.1.2-5
- Type:bugfix
- ID:NA
- SUG:NA
- DESC:add Patch4:ukui-settings-daemon-3.1.2-kylin-fix-coredump.patch

* Sun Jun 25 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-4
- Type:bugfix
- ID:NA
- SUG:NA
- DESC: add Fix-the-failure-of-shortcut-key-to-open-terminal.patch
