# SPDX-License-Identifier: GPL-2.0-or-later
# ===========================================================================
# ukui-control-center.spec — AirymaxOS 的上游重建配方
#
# 本配方不新增源码：源码包取自 openEuler 24.03 LTS SP3 EPOL 的同名
# src.rpm，补丁序列与上游保持一致，只叠加一个下游补丁：
#
#   Patch300  关于页的「桌面」一栏改读 /etc/airymaxos/desktop-version
#
# 事实源：tarball 不入库，source-rpm 声明用官方 src.rpm 的摘要传递性钉住
# 成员内容；补丁随本目录入库，逐字节可复算。
#
# Release 保留上游 33 并追加 .airy1：33.oe2403sp3.airy1 高于
# 33.oe2403sp3，装回官方包不会因 EVR 相同而静默覆盖下游补丁。
#
# License 写 GPL-2.0-or-later：上游文件头声明 GPL-2+，SPDX 无此写法。
# ===========================================================================

# spec-lint: source-rpm ukui-control-center-3.1.2.tar.gz https://repo.openeuler.org/openEuler-24.03-LTS-SP3/EPOL/main/source/Packages/ukui-control-center-3.1.2-33.oe2403sp3.src.rpm d3beabf7de66330017c6ebbd55cd697ad9eecb67a1d6300e20b9b317bfc157ad

Name:           ukui-control-center
Version:        3.1.2
Release:        33%{?dist}.airy1
Summary:        utilities to configure the UKUI desktop
License:        GPL-2.0-or-later
URL:            http://www.ukui.org
Source0:        %{name}-%{version}.tar.gz
Patch01:        0001-fix-compile-error-of-ukui-control-center.patch
Patch02:        0001-modify-version-info-error.patch
Patch03:        0003-fix-power-missing-issue.patch
Patch05:        0005-Fix-the-problem-of-displaying-none-in-the-interface-version-information.patch
Patch07:        0007-modify-icon-theme-not-display.patch
Patch08:        ukui-control-center-3.0.4-fix-invalid-automatic-login.patch
Patch10:        0010-Fix-the-problem-of-scrambled-shortcut-keys.patch
Patch11:	0011-Fix-about-copyright-display-error.patch
Patch12:	0012-fix-add-group-failed-issue.patch
Patch13:        0013-Fix-terminal-garbled-characters-when-not-root-user-change-locale-language.patch
Patch14:        0014-fix-memorysize-of-aboutinfo.patch
Patch15:        fix-changeOtherUserPasswd-critical-vulnerabilities.patch
Patch16:        fix-createuser-critical-vulnerabilities.patch
Patch17:        ukui-control-center-3.1.2-fix-password-changes-for-this-user-and-for-other-use.patch
Patch18:	fix-ukui-control-center-3.1.2-activation-button-display-error.patch
Patch19:        disable-Time-to-sleep-of-kylin.patch
Patch20:        Turn-off-activation-button-hide-operation.patch
Patch21:        add-information-for-about.patch
Patch22:        cpuinfo-in-arm-system-is-null.patch
Patch23:        add-ukcc-setlang.patch
Patch24:        fix-changeusertype-error.patch
Patch25:        update-formats_loacle-and-language.patch
Patch26:        fix-cpuinfo-error-of-ukui-control-center-3.1.2.patch
Patch27:	ukui-control-center-3.1.2-repair-freelogin-autologin-not-available.patch
Patch28:	0001-fix-object-created-in-wrong-thread.patch

Patch200:       fix-build-error-of-libkscreen-qt5-5.27.6.patch
Patch201:       fix-build-error-of-clang.patch
Patch202:       fix-build-error-of-ddcutil-2.0.0.patch
Patch203:	fix-the-display-resolution-does-not-match-the-actual-resolution.patch
Patch300:       airymaxos-desktop-version.patch
BuildRequires: qt5-qtsvg-devel
BuildRequires: gsettings-qt-devel
BuildRequires: glib2-devel
BuildRequires: libmatekbd-devel
BuildRequires: qt5-qtx11extras-devel
BuildRequires: libxklavier-devel
BuildRequires: libkscreen-qt5-devel
BuildRequires: kf5-ki18n-devel
BuildRequires: kf5-kwindowsystem-devel
BuildRequires: kf5-kxmlgui-devel
BuildRequires: kf5-kglobalaccel-devel
BuildRequires: qt5-qtdeclarative-devel
BuildRequires: dconf-devel
BuildRequires: libmatemixer-devel
BuildRequires: libxml2-devel
BuildRequires: qt5-qtbase-devel
BuildRequires: libX11-devel
BuildRequires: libxkbfile-devel
BuildRequires: boost-devel
BuildRequires: qt5-qttools-devel
BuildRequires: libxcb-devel
BuildRequires: polkit-qt5-1-devel
BuildRequires: pulseaudio-libs-devel
BuildRequires: libpwquality-devel
BuildRequires: xorg-x11-server-devel
BuildRequires: upower-devel
BuildRequires: pam-devel
BuildRequires: ukui-interface
BuildRequires: mate-desktop-devel
BuildRequires: libddcutil-devel
BuildRequires: libkylin-chkname-devel
BuildRequires: cups-devel
#compile need  but control is not exist
BuildRequires: kf5-kguiaddons-devel

Requires: dconf
Requires: ukui-search
Requires: ukui-media
Requires: ukui-themes
#install need  but control is not exist
Requires: libkylin-chkname1
Requires: lightdm

Suggests: gsettings-desktop-schemas
Suggests: mate-common
Suggests: ukui-power-manager
Suggests: ukui-session-manager
Suggests: ukui-screensaver
Suggests: ukui-settings-daemon


%description
 The UKUI control center contains configuration applets for the UKUI desktop,
 allowing to set accessibility configuration, desktop fonts, keyboard
 and mouse properties, sound setup, desktop theme and background, user
 interface properties, screen resolution, and other UKUI parameters.

%package -n libukcc-devel
Summary:  libukcc
%description -n libukcc-devel
The UKUI control center contains configuration applets for the UKUI des allowing to set accessibility configuration, desktop fonts, keyboard and mouse properties, sound setup, desktop theme and background, user interface properties, screen resolution, and other UKUI parameters.

%prep
%autosetup -n %{name}-%{version} -p1

%build
%{qmake_qt5}
%{make_build}

%install
rm -rf $RPM_BUILD_ROOT
%{make_install} INSTALL_ROOT=%{buildroot}

mkdir -p %{buildroot}/etc/xdg/autostart/

%posttrans
set -e
glib-compile-schemas /usr/share/glib-2.0/schemas/ &> /dev/null ||:

systemctl enable ukui-group-manager.service
systemctl start  ukui-group-manager.service
#chown root:root /usr/bin/checkUserPwd
#chmod u+s /usr/bin/checkUserPwd

sed  -i "1iauth    sufficient      pam_succeed_if.so user ingroup nopasswdlogin"   /etc/pam.d/lightdm
groupadd nopasswdlogin &> /dev/null ||:

%postun
sed  -i "/auth    sufficient      pam_succeed_if.so user ingroup nopasswdlogin/d" /etc/pam.d/lightdm
systemctl disable ukui-group-manager.service
systemctl stop ukui-group-manager.service

%clean
rm -rf $RPM_BUILD_ROOT

%files
%{_sysconfdir}/dbus-1/system.d/*
/lib/systemd/system/*
%{_bindir}/*
%{_datadir}/applications/*
%{_datadir}/dbus-1/system-services/*
%{_datadir}/dbus-1/services/*
%{_datadir}/glib-2.0/schemas/*
%{_datadir}/kylin-user-guide/data/*
%{_datadir}/locale/zh_CN/LC_MESSAGES/*
%{_datadir}/polkit-1/actions/*
%{_datadir}/ukui/faces/*
%{_datadir}/ukui-control-center/shell/res/*
%{_libdir}/ukui-control-center/*
%{_datadir}/lightdm/lightdm.conf.d/95-SeatDefaults.conf

%files -n libukcc-devel
%{_includedir}/ukcc/interface/*.h
%{_includedir}/ukcc/widgets/*.h
%{_libdir}/libukcc*


%changelog
* Sun Nov 09 2026 Liren Wang <wangliren@spharx.cn> - 3.1.2-33.airy1
- Add Patch300: desktop row reads /etc/airymaxos/desktop-version

* Thu Aug 15 2024 huayadong <huayadong@kylinos.cn> - 3.1.2-33
- Type:bugfix
- ID  :NA
- SUG :NA
- DESC:Patch203:fix-the-display-resolution-does-not-match-the-actual-resolution.patch

* Tue Jun 25 2024 houhongxun <houhongxun@kylinos.cn> - 3.1.2-32
- fix wrong usage of qthread

* Tue May 28 2024 peijiankang <peijiankang@kylinos.cn> - 3.1.2-31
- Type:bugfix
- ID  :NA
- SUG :NA
- DESC:add ukui-control-center-3.1.2-repair-freelogin-autologin-not-available.patch

* Fri May 10 2024 peijiankang <peijiankang@kylinos.cn> - 3.1.2-30
- Type:bugfix
- ID  :NA
- SUG :NA
- DESC:add fix-cpuinfo-error-of-ukui-control-center-3.1.2.patch

* Mon Jan 29 2024 peijiankang <peijiankang@kylinos.cn> - 3.1.2-29
- Type:bugfix
- ID  :NA
- SUG :NA
- DESC:add fix-build-error-of-ddcutil-2.0.0.patch

* Mon Sep 25 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-28
- Type:bugfix
- ID  :NA
- SUG :NA
- DESC:add update-formats_loacle-and-language.patch

* Fri Sep 15 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-27
- Type:bugfix
- ID:NA
- SUG:NA
- DESC: add add-information-for-about.patch cpuinfo-in-arm-system-is-null.patch add-ukcc-setlang.patch fix-changeusertype-error.patch

* Fri Sep 08 2023 yoo <sunyuechi@iscas.ac.cn> - 3.1.2-26
- Type:bugfix
- ID:NA
- SUG:NA
- DESC: fix clang build error

* Thu Sep 07 2023 douyan <douyan@kylinos.cn> - 3.1.2-25
- Type:Bugfix
- ID:NA
- SUG:NA
- DESC: add Turn-off-activation-button-hide-operation.patch

* Wed Aug 30 2023 huayadong <huayadong@kylinos.cn> - 3.1.2-24
- Type:bugfix
- ID:#I7WGWQ
- SUG:NA
- DESC:fix Abnormal information during installation and uninstallation

* Fri Aug 18 2023 douyan <douyan@kylinos.cn> - 3.1.2-23
- Type:bugfix
- ID:NA
- SUG:NA
- DESC: rebuild

* Wed Aug 16 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-22
- Type:bugfix
- ID:NA
- SUG:NA
- DESC: add fix-build-error-of-libkscreen-qt5-5.27.6.patch

* Sun Jun 18 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-21
- Type:bugfix
- ID:NA
- SUG:NA
- DESC: add disable-Time-to-sleep-of-kylin.patch

* Sat Jun 17 2023 huayadong <huayadong@kylinos.cn> - 3.1.2-20
- remove Requires: kylin-nm ukui-bluetooth

* Wed Jun 14 2023 huayadong <huayadong@kylinos.cn> - 3.1.2-19
- add patch:fix-ukui-control-center-3.1.2-activation-button-display-error.patch 

* Fri Jun 09 2023 huayadong <huayadong@kylinos.cn> - 3.1.2-18
- fix password changes for this user and for other use

* Fri May 26 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-17
- sync from upstream 3.1.2+2023-0403

* Mon May 22 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-16
- fix createuser critical vulnerabilities

* Mon May 22 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-15
- fix changeOtherUserPasswd critical vulnerabilities

* Thu Mar 30 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-14
- fix memorysize of aboutinfo

* Fri Mar 17 2023 tanyulong <tanyulong@kylinos.cn> - 3.1.2-13
- Fix terminal garbled characters when not root user change locale language 

* Wed Mar 01 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-12
- add build debuginfo and debugsource

* Wed Mar 01 2023 tanyulong <tanyulong@kylinos.cn> - 3.1.2-11
- fix add group failed issue

* Mon Feb 27 2023 tanyulong <tanyulong@kylinos.cn> - 3.1.2-10
- Fix about copyright display error

* Tue Feb 7 2023 douyan <douyan@kylinos.cn> - 3.1.2-9
- change power default setting

* Mon Jan 9 2023 peijiankang <peijiankang@kylinos.cn> - 3.1.2-8
- add patch10: 0010-Fix-the-problem-of-scrambled-shortcut-keys.patch

* Fri Dec 30 2022 huayadong <huayadong@kylinos.cn> - 3.1.2-7
- Fix invalid automatic login, fix invalid password free login

* Thu Dec 29 2022 peijiankang <peijiankang@kylinos.cn> - 3.1.2-6
- modify icon theme not display

* Fri Dec 23 2022 peijiankang <peijiankang@kylinos.cn> - 3.1.2-5
- add patch5: 0005-Fix-the-problem-of-displaying-none-in-the-interface-version-information.patch

* Thu Dec 15 2022 peijiankang <peijiankang@kylinos.cn> - 3.1.2-4
- fix power missing issue

* Fri Dec 9 2022 peijiankang <peijiankang@kylinos.cn> - 3.1.2-3
- add libkylin-chkname1 Requires to fix useradd error

* Fri Dec 9 2022 peijiankang <peijiankang@kylinos.cn> - 3.1.2-2
- modify version-info error

* Mon Dec 5 2022 peijiankang <peijiankang@kylinos.cn> - 3.1.2-1
- update version to 3.1.2

* Mon Aug 08 2022 tanyulong <tanyulong@kylinos.cn> - 3.0.1-29
- update and modify translations

* Thu Aug 04 2022 tanyulong <tanyulong@kylinos.cn> - 3.0.1-28
- fix and update translation

* Fri Jul 29 2022 tanyulong <tanyulong@kylinos.cn> - 3.0.1-27
- modify displayed size after the installation and download of system update completed

* Thu Jul 28 2022 tanyulong <tanyulong@kylinos.cn> - 3.0.1-26
- add dependency ddcutil to make HDMI brightness adjustment available

* Tue Jun 28 2022 peijiankang <peijiankang@kylinos.cn> - 3.0.1-25
- update about.png for openEuler

* Fri Apr 29 2022 huayadong <huayadong@kylinos.cn> - 3.0.1-24
- Modify the icon displayed on the tray

* Tue Apr 19 2022 pei-jiankang <peijiankang@kylinos.cn> - 3.0.1-23
- modify ukui-control-center install error

* Fri Mar 25 2022 huayadong <huayadong@kylinos.cn> - 3.0.1-22
- The shortcut keys of the same function are combined together

* Thu Oct 28 2021 tanyulong <tanyulong@kylinos.cn> - 3.0.1-21
- fix net sort wifi strength

* Tue Oct 19 2021 peijiankang <peijiankang@kylinos.cn> - 3.0.1-20
- add 0014-modify-the-error-of-ukui-control-center-open.patch

* Thu Sep 16 2021 douyan <douyan@kylinos.cn> - 3.0.1-19
- add fix_user_passwd_valid_issue.patch

* Sat Sep 11 2021 peijiankang <peijiankang@kylinos.cn> - 3.0.1-18
- add 0013-cpuinfo-in-arm-system-is-null.patch

* Mon Sep 6 2021 douyan <douyan@kylinos.cn> - 3.0.1-17
- add fix_user_passwd_valid_time_setting_failed_issue.patch

* Thu Sep 2 2021 douyan <douyan@kylinos.cn> - 3.0.1-16
- fix add group failed issue

* Wed Sep 1 2021 douyan <douyan@kylinos.cn> - 3.0.1-15
- fix arm verion root user open ukui-control-center crash issue

* Thu Jul 29 2021 tanyulong <tanyulong@kylinos.cn> - 3.0.1-14
- solve compile build error

* Fri Jul 16 2021 tanyulong<tanyulong@kylinos.cn> - 3.0.1-13
- fix failed to view remote desktop

* Tue Jul 13 2021 tanyulong<tanyulong@kylinos.cn> - 3.0.1-12
- window add title icon

* Mon Jul 12 2021 tanyulong<tanyulong@kylinos.cn> - 3.0.1-11
- power add sleep function

* Mon Jul 12 2021 tanyulong<tanyulong@kylinos.cn> - 3.0.1-10
- Added translation using Weblate Tibetan add bo_CN.ts file

* Mon Jul 12 2021 tanyulong<tanyulong@kylinos.cn> - 3.0.1-9
- fix layout optimization

* Fri Jul 09 2021 tanyulong<tanyulong@kylinos.cn> - 3.0.1-8
- fix redeclaration of QStringList usergroupList

* Fri Jul 09 2021 tanyulong<tanyulong@kylinos.cn> - 3.0.1-7
- fix vnc crashed

* Thu Jul 08 2021 tanyulong<tanyulong@kylinos.cn> - 3.0.1-6
- fix-Group-members-are-not-displayed

* Thu Jul 08 2021 tanyulong<tanyulong@kylinos.cn> - 3.0.1-5
- add-judgment-when-Bluetooth-does-not-exist.patch

* Thu Jan 21 2021 lvhan <lvhan@kylinos.cn> - 3.0.1-4
- fix-blueman-tray-and-groupadd-autologin

* Thu Dec 3 2020 lvhan <lvhan@kylinos.cn> - 3.0.1-3
- fix dialog pop twice after modifying resolution
- fix effects mode not available

* Mon Nov 30 2020 lvhan <lvhan@kylinos.cn> - 3.0.1-2
- fix autologin nopasswdlogin failed
- fix system overview failed

* Thu Jul 9 2020 douyan <douyan@kylinos.cn> - 3.0.1-1
- update to upstream version 3.0.0-1+1031

* Thu Jul 9 2020 douyan <douyan@kylinos.cn> - 2.0.3-1
- Init package for openEuler
