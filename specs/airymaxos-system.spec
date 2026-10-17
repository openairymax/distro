# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-system — AirymaxOS 系统编排包
#
# 职责：
#   1. 部署 agentrt.target 及其 12 个 daemon 单元、事件模板与
#      首启初始化/启动自检单元；
#   2. 部署 /usr/lib/airymaxos/scripts 下的运行时脚本；
#   3. 在 %post/%postun 内刷新 systemd 单元缓存。
#
# 单元启用（systemctl enable）由安装器在 kickstart 中显式完成，
# 本包只负责文件到位与缓存刷新（OS-OPS-010）。
#
# 构建约束：全部 Source 为仓库内裸露文件名，由构建流水线 staging 到
# _sourcedir 后 rpmbuild；配方本身不生成任何内容。
# ===========================================================================

# spec-lint: source-root ../../system/units
# spec-lint: source-root ../../system/scripts

%global airy_version 0.0.3
%global airy_release 1
%{!?_unitdir:%global _unitdir /usr/lib/systemd/system}

Name:           airymaxos-system
Version:        %{airy_version}
Release:        %{airy_release}%{?dist}
Summary:        AirymaxOS systemd units, targets and runtime scripts
License:        AGPL-3.0-or-later
URL:            https://atomgit.com/openairymax/agent-linux
BuildArch:      noarch

Source0:        agentrt.target
Source1:        agentrt-firstboot.service
Source2:        agentrt-health-check.service
Source3:        agentrt-gateway.service
Source4:        agentrt-sched.service
Source5:        agentrt-cogn.service
Source6:        agentrt-dev.service
Source7:        agentrt-net.service
Source8:        agentrt-mem.service
Source9:        agentrt-sec.service
Source10:       agentrt-audit.service
Source11:       agentrt-logger.service
Source12:       agentrt-macro-superv.service
Source13:       agentrt-vfs.service
Source14:       agentrt-config.service
Source15:       agentrt-dsl.target
Source16:       airy-incident@.service
Source17:       firstboot.sh
Source18:       health_check.sh

Requires:       bash
Requires:       procps-ng
Requires:       systemd
Requires(post): systemd
Requires(postun): systemd

%description
AirymaxOS system orchestration package. It owns the agentrt.target
aggregate, the twelve daemon units, the incident template, the first
boot initialization gate, the boot health self-test and the runtime
scripts they execute. Units are installed disabled; the installer
enables them explicitly so that server and desktop profiles can opt
out without editing the package payload.

%prep
%setup -q -c -T

%build

%install
install -d -m 0755 %{buildroot}%{_unitdir}
install -m 0644 %{_sourcedir}/*.service %{buildroot}%{_unitdir}/
install -m 0644 %{_sourcedir}/*.target %{buildroot}%{_unitdir}/
install -d -m 0755 %{buildroot}/usr/lib/airymaxos/scripts
install -m 0755 %{_sourcedir}/*.sh %{buildroot}/usr/lib/airymaxos/scripts/

%check
test -x %{buildroot}/usr/lib/airymaxos/scripts/firstboot.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/health_check.sh
test -f %{buildroot}%{_unitdir}/agentrt.target
test -f %{buildroot}%{_unitdir}/agentrt-firstboot.service
test -f %{buildroot}%{_unitdir}/airy-incident@.service
grep -qF 'Requires=sysinit.target ' %{buildroot}%{_unitdir}/agentrt.target
grep -qxF 'Before=agentrt.target multi-user.target' \
    %{buildroot}%{_unitdir}/agentrt-firstboot.service

%post
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || :
fi

%postun
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || :
fi

%files
%defattr(-, root, root, -)
%dir /usr/lib/airymaxos
%dir /usr/lib/airymaxos/scripts
/usr/lib/airymaxos/scripts/*.sh
%{_unitdir}/*.service
%{_unitdir}/*.target

%changelog
* Sat Oct 17 2026 Liren Wang <wangliren@spharx.cn> - 0.0.3-1
- Initial system orchestration package for AirymaxOS 0.0.3
