# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-release — AirymaxOS 发行版标识包
#
# 职责：
#   1. 提供 /usr/lib/os-release 与 /etc/os-release 符号链接（VERSION_ID 唯一
#      事实源为仓库内 release/os-release）；
#   2. 提供 /etc/yum.repos.d/airymaxos.repo（仓库列表 SSoT）；
#   3. 提供 /etc/rpm/macros.airymax（文件系统布局宏 SSoT）；
#   4. 部署桌面隔离单元与 UKUI 集成策略脚本，并在 %post 内应用。
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
Summary:        AirymaxOS release identity, repositories and RPM macros
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

Provides:       system-release
Provides:       system-release(releasever)
Obsoletes:      openEuler-release < 24.04

%description
AirymaxOS release identity package. It owns the distribution version
file, the dnf repository definitions and the shared RPM macros used by
every AirymaxOS package, and it applies the desktop integration policy
at install time.

%prep
%setup -q -c -T

%build

%install
install -d -m 0755 %{buildroot}/usr/lib
install -m 0644 %{SOURCE0} %{buildroot}/usr/lib/os-release
install -d -m 0755 %{buildroot}/etc
ln -s ../usr/lib/os-release %{buildroot}/etc/os-release

install -d -m 0755 %{buildroot}/etc/yum.repos.d
install -m 0644 %{SOURCE1} %{buildroot}/etc/yum.repos.d/airymaxos.repo

install -d -m 0755 %{buildroot}/etc/rpm
install -m 0644 %{SOURCE2} %{buildroot}/etc/rpm/macros.airymax

install -d -m 0755 %{buildroot}%{_unitdir}
install -m 0644 %{SOURCE3} %{buildroot}%{_unitdir}/airymax-desktop.slice

install -d -m 0755 %{buildroot}/usr/share/airymaxos/distro/desktop/wallpaper
install -m 0755 %{SOURCE4} \
    %{buildroot}/usr/share/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
install -m 0644 %{SOURCE3} \
    %{buildroot}/usr/share/airymaxos/distro/desktop/airymax-desktop.slice
install -m 0644 %{SOURCE5} \
    %{buildroot}/usr/share/airymaxos/distro/desktop/wallpaper/airymaxos-default.jpg

install -d -m 0755 %{buildroot}/usr/share/licenses/airymaxos-release
install -m 0644 %{SOURCE6} \
    %{buildroot}/usr/share/licenses/airymaxos-release/LICENSE

%check
grep -qxF 'ID=airymaxos' %{buildroot}/usr/lib/os-release
grep -qxF 'VERSION_ID="%{version}"' %{buildroot}/usr/lib/os-release
grep -qxF 'ID_LIKE="openeuler"' %{buildroot}/usr/lib/os-release
grep -qxF '[airymaxos-base]' %{buildroot}/etc/yum.repos.d/airymaxos.repo
grep -qF 'airymax_libdir' %{buildroot}/etc/rpm/macros.airymax
grep -qF '/usr/lib/airymaxos' %{buildroot}/etc/rpm/macros.airymax
test -L %{buildroot}/etc/os-release
test -x %{buildroot}/usr/share/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
test -s %{buildroot}/usr/share/airymaxos/distro/desktop/wallpaper/airymaxos-default.jpg

%post
if [ -x /usr/share/airymaxos/distro/desktop/70-airymax-ukui-policy.sh ]; then
    /usr/share/airymaxos/distro/desktop/70-airymax-ukui-policy.sh || exit 1
fi
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || :
fi

%files
%defattr(-, root, root, -)
/etc/os-release
/usr/lib/os-release
%config(noreplace) /etc/yum.repos.d/airymaxos.repo
%config(noreplace) /etc/rpm/macros.airymax
%{_unitdir}/airymax-desktop.slice
/usr/share/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
/usr/share/airymaxos/distro/desktop/airymax-desktop.slice
/usr/share/airymaxos/distro/desktop/wallpaper/airymaxos-default.jpg
/usr/share/licenses/airymaxos-release/LICENSE

%changelog
* Sat Oct 17 2026 SPHARX <dev@spharx.com> - 0.0.3-1
- Initial release package for AirymaxOS 0.0.3
