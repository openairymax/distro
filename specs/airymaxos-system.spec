# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-system — AirymaxOS 系统编排包
#
# 职责：
#   1. 部署 agentrt.target 及其 12 个 daemon 单元、事件模板与
#      首启初始化/启动自检单元；
#   2. 部署 /usr/lib/airymaxos/scripts 下的运行时脚本；
#   3. 部署 /usr/bin/airy-disk 与 airydisk Python 包，装机、升级与
#      门禁因此共用同一份磁盘判定实现（DISK-01）；
#   4. 在 %%post/%%postun 内刷新 systemd 单元缓存。
#
# 单元启用（systemctl enable）由安装器在 kickstart 中显式完成，
# 本包只负责文件到位与缓存刷新（OS-OPS-010）。随包落盘两份 preset：
# 90-airymax.preset 把自有栈钉在 disabled，防止 systemctl preset-all 的
# 默认 enable 语义提前拉起尚未交付二进制的单元；99-airymax-default-disable.preset
# 补齐上游 openEuler-release 被 Obsoletes 接管后丢失的「默认关闭」兜底，
# 避免第三方单元按未命中即 enable 的语义被拉起。
#
# 构建约束：全部 Source 为仓库内裸露文件名，由构建流水线 staging 到
# _sourcedir 后 rpmbuild；配方本身不生成任何内容。
#
# 同批构建的配方共用一个 _sourcedir，故每个文件都按 SOURCE 编号逐个落盘，
# 不用通配符：airymaxos-release 也往同一目录暂存 .sh 与 .service，通配会
# 把别的包的文件收进本包，安装时表现为两个包同持一条路径。
# ===========================================================================

# spec-lint: source-root ../../system/units
# spec-lint: source-root ../../system/scripts
# spec-lint: source-root ../../system/bin
# spec-lint: source-root ../../system/services/airydisk

%global airy_version 0.0.3
%global airy_release 3
%{!?_unitdir:%global _unitdir /usr/lib/systemd/system}
%{!?_presetdir:%global _presetdir /usr/lib/systemd/system-preset}

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
Source19:       90-airymax.preset
Source20:       99-airymax-default-disable.preset
Source21:       airy-disk
Source22:       __init__.py
Source23:       cli.py
Source24:       fstab.py
Source25:       layout.py
Source26:       model.py
Source27:       ops.py
Source28:       probe.py
Source29:       record.py
Source30:       runner.py

BuildRequires:  python3-devel
Requires:       bash
Requires:       procps-ng
Requires:       python3
Requires:       systemd
Requires(post): systemd
Requires(postun): systemd

%description
AirymaxOS system orchestration package. It owns the agentrt.target
aggregate, the twelve daemon units, the incident template, the first
boot initialization gate, the boot health self-test, the runtime
scripts they execute, and the airy-disk command with its Python
package. Units are installed disabled; the installer enables them
explicitly so that server and desktop profiles can opt out without
editing the package payload.

%prep
%setup -q -c -T

%build

%install
install -d -m 0755 %{buildroot}%{_unitdir}
install -m 0644 %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE4} %{SOURCE5} \
    %{SOURCE6} %{SOURCE7} %{SOURCE8} %{SOURCE9} %{SOURCE10} %{SOURCE11} \
    %{SOURCE12} %{SOURCE13} %{SOURCE14} %{SOURCE16} \
    %{buildroot}%{_unitdir}/
install -m 0644 %{SOURCE0} %{SOURCE15} %{buildroot}%{_unitdir}/
install -d -m 0755 %{buildroot}/usr/lib/airymaxos/scripts
install -m 0755 %{SOURCE17} %{SOURCE18} \
    %{buildroot}/usr/lib/airymaxos/scripts/
install -d -m 0755 %{buildroot}%{_presetdir}
install -m 0644 %{SOURCE19} %{SOURCE20} %{buildroot}%{_presetdir}/
install -d -m 0755 %{buildroot}%{_bindir}
install -m 0755 %{SOURCE21} %{buildroot}%{_bindir}/airy-disk
install -d -m 0755 %{buildroot}%{python3_sitelib}/airydisk
install -m 0644 %{SOURCE22} %{SOURCE23} %{SOURCE24} %{SOURCE25} \
    %{SOURCE26} %{SOURCE27} %{SOURCE28} %{SOURCE29} %{SOURCE30} \
    %{buildroot}%{python3_sitelib}/airydisk/

%check
test -x %{buildroot}/usr/lib/airymaxos/scripts/firstboot.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/health_check.sh
test -x %{buildroot}%{_bindir}/airy-disk
PYTHONPATH=%{buildroot}%{python3_sitelib} python3 -B -c \
    'import airydisk.cli'
test -f %{buildroot}%{_unitdir}/agentrt.target
test -f %{buildroot}%{_unitdir}/agentrt-firstboot.service
test -f %{buildroot}%{_unitdir}/airy-incident@.service
grep -qF 'Requires=sysinit.target ' %{buildroot}%{_unitdir}/agentrt.target
grep -qxF 'Before=agentrt.target multi-user.target' \
    %{buildroot}%{_unitdir}/agentrt-firstboot.service
test -f %{buildroot}%{_presetdir}/90-airymax.preset
grep -qxF 'disable agentrt.target' \
    %{buildroot}%{_presetdir}/90-airymax.preset
grep -qxF 'disable agentrt-*.service' \
    %{buildroot}%{_presetdir}/90-airymax.preset
test -f %{buildroot}%{_presetdir}/99-airymax-default-disable.preset
grep -qxF 'disable *' \
    %{buildroot}%{_presetdir}/99-airymax-default-disable.preset

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
%{_presetdir}/90-airymax.preset
%{_presetdir}/99-airymax-default-disable.preset
%{_bindir}/airy-disk
%{python3_sitelib}/airydisk

%changelog
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.3-3
- Ship airy-disk and the airydisk Python package so the installer and
  the running system judge disk layout with one implementation
- Install sources by number instead of glob: sibling packages stage
  their own .sh and .service files into the shared _sourcedir
* Wed Oct 21 2026 Liren Wang <wangliren@spharx.cn> - 0.0.3-2
- Ship 99-airymax-default-disable.preset to restore the default-off
  policy lost when airymaxos-release obsoletes openEuler-release
* Sat Oct 17 2026 Liren Wang <wangliren@spharx.cn> - 0.0.3-1
- Initial system orchestration package for AirymaxOS 0.0.3
- Pin agentrt units to disabled via systemd preset
