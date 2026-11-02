# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-system — AirymaxOS 系统编排包
#
# 职责：
#   1. 部署 agentrt.target 及其 12 个 daemon 单元、事件模板、首启初始化、
#      启动自检，以及数据分区挂载与健康检查单元；
#   2. 部署 /usr/lib/airymaxos/scripts 下的运行时脚本；
#   3. 部署 /usr/bin/airy-disk 与 airydisk Python 包，装机、升级与
#      门禁因此共用同一份磁盘判定实现（DISK-01）；
#   4. 部署 /usr/bin/airy-update、airyupdate Python 包与每日检查定时器，
#      升级通道与装机共用同一份版本身份实现（V-14）；
#   5. 部署 /usr/bin/airy-model、airyllm Python 包与推理服务单元，模型
#      资产通道、状态查询与启动判定共用同一份运行层实现（K-20/K-21）；
#   6. 部署 /usr/bin/airy-rt-cap、airymax_rt Python 包与实时带宽单元，
#      启动期分配与人工排查共用同一份带宽判定实现（X-01）；
#   7. 在 %%post/%%postun 内刷新 systemd 单元缓存。
#
# 单元启用（systemctl enable）由安装器在 kickstart 中显式完成，
# 本包只负责文件到位与缓存刷新（OS-OPS-010）。随包落盘两份 preset：
# 90-airymax.preset 把自有栈钉在 disabled，防止 systemctl preset-all 的
# 默认 enable 语义提前拉起尚未交付二进制的单元；99-airymax-default-disable.preset
# 补齐上游 openEuler-release 被 Obsoletes 接管后丢失的「默认关闭」兜底，
# 避免第三方单元按未命中即 enable 的语义被拉起。
#
# 构建约束：单元、脚本与入口脚本为仓库内裸露文件名，由构建流水线 staging
# 到 _sourcedir 后 rpmbuild；三个 Python 包以整目录归档交付，归档由驱动按
# `<目录名>-<Version>.tar.gz` 现场生成，配方本身不生成任何内容。
#
# 同批构建的配方共用一个 _sourcedir，故每个文件都按 SOURCE 编号逐个落盘，
# 不用通配符：airymaxos-release 也往同一目录暂存 .sh 与 .service，通配会
# 把别的包的文件收进本包，安装时表现为两个包同持一条路径。
# ===========================================================================

# spec-lint: source-root ../../system/units
# spec-lint: source-root ../../system/scripts
# spec-lint: source-root ../../system/bin
# spec-lint: source-bundle ../../system/services/airydisk
# spec-lint: source-bundle ../../system/services/airyllm
# spec-lint: source-bundle ../../system/services/airyupdate
# spec-lint: source-bundle ../../system/services/airymax_rt

%global airy_version 0.0.4
%global airy_release 5
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
Source22:       airy-update
Source23:       airymax-update-check.service
Source24:       airymax-update-check.timer
Source25:       airydisk-%{version}.tar.gz
Source26:       airyupdate-%{version}.tar.gz
Source27:       airy-llm.service
Source28:       airy-model
Source29:       airyllm-%{version}.tar.gz
Source30:       airy-disk-mount.service
Source31:       airy-disk-health.service
Source32:       airy-disk-health.timer
Source33:       airy-rt-cap
Source34:       airymax_rt-%{version}.tar.gz
Source35:       airy-rt-bandwidth.service

BuildRequires:  python3-devel
Requires:       bash
Requires:       dnf
Requires:       procps-ng
Requires:       python3
Requires:       rpm
Requires:       systemd
Requires(post): systemd
Requires(postun): systemd

%description
AirymaxOS system orchestration package. It owns the agentrt.target
aggregate, the twelve daemon units, the incident template, the first
boot initialization gate, the boot health self-test, the data
partition mount and health units with their daily timer, the runtime
scripts they execute, the airy-disk command with its Python package,
and the airy-model command with the local model runtime package and
service unit. The airy-rt-cap command with its RT bandwidth package
and the boot unit that applies the budget before the audio daemons
share one verdict implementation. Units are installed disabled; the
installer enables them explicitly so that server and desktop profiles
can opt out without editing the package payload.

%prep
%setup -q -c -T

%build

%install
install -d -m 0755 %{buildroot}%{_unitdir}
install -m 0644 %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE4} %{SOURCE5} \
    %{SOURCE6} %{SOURCE7} %{SOURCE8} %{SOURCE9} %{SOURCE10} %{SOURCE11} \
    %{SOURCE12} %{SOURCE13} %{SOURCE14} %{SOURCE16} \
    %{SOURCE23} %{SOURCE24} %{SOURCE27} \
    %{SOURCE30} %{SOURCE31} %{SOURCE32} %{SOURCE35} \
    %{buildroot}%{_unitdir}/
install -m 0644 %{SOURCE0} %{SOURCE15} %{buildroot}%{_unitdir}/
install -d -m 0755 %{buildroot}/usr/lib/airymaxos/scripts
install -m 0755 %{SOURCE17} %{SOURCE18} \
    %{buildroot}/usr/lib/airymaxos/scripts/
install -d -m 0755 %{buildroot}%{_presetdir}
install -m 0644 %{SOURCE19} %{SOURCE20} %{buildroot}%{_presetdir}/
install -d -m 0755 %{buildroot}%{_bindir}
install -m 0755 %{SOURCE21} %{buildroot}%{_bindir}/airy-disk
install -m 0755 %{SOURCE22} %{buildroot}%{_bindir}/airy-update
install -m 0755 %{SOURCE28} %{buildroot}%{_bindir}/airy-model
install -m 0755 %{SOURCE33} %{buildroot}%{_bindir}/airy-rt-cap
install -d -m 0755 %{buildroot}%{python3_sitelib}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE25}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE26}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE29}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE34}

%check
test -x %{buildroot}/usr/lib/airymaxos/scripts/firstboot.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/health_check.sh
test -x %{buildroot}%{_bindir}/airy-disk
test -x %{buildroot}%{_bindir}/airy-update
test -x %{buildroot}%{_bindir}/airy-model
test -x %{buildroot}%{_bindir}/airy-rt-cap
PYTHONPATH=%{buildroot}%{python3_sitelib} python3 -B -c \
    'import airydisk.cli, airyupdate.cli, airyllm.cli, airymax_rt.cli'
test -f %{buildroot}%{_unitdir}/agentrt.target
test -f %{buildroot}%{_unitdir}/agentrt-firstboot.service
test -f %{buildroot}%{_unitdir}/airy-incident@.service
test -f %{buildroot}%{_unitdir}/airymax-update-check.timer
grep -qxF 'OnCalendar=daily' \
    %{buildroot}%{_unitdir}/airymax-update-check.timer
grep -qxF 'SuccessExitStatus=10' \
    %{buildroot}%{_unitdir}/airymax-update-check.service
test -f %{buildroot}%{_unitdir}/airy-llm.service
grep -qxF 'ExecStart=/usr/bin/airy-model serve' \
    %{buildroot}%{_unitdir}/airy-llm.service
grep -qxF 'StateDirectory=airy-llm' \
    %{buildroot}%{_unitdir}/airy-llm.service
grep -qxF 'ConditionPathExists=/var/lib/airy-llm/manifest.json' \
    %{buildroot}%{_unitdir}/airy-llm.service
test -f %{buildroot}%{_unitdir}/airy-disk-mount.service
grep -qxF 'ExecStart=/usr/bin/airy-disk mount' \
    %{buildroot}%{_unitdir}/airy-disk-mount.service
grep -qxF 'Before=agentrt.target multi-user.target' \
    %{buildroot}%{_unitdir}/airy-disk-mount.service
test -f %{buildroot}%{_unitdir}/airy-disk-health.service
grep -qxF 'ConditionPathIsMountPoint=/data' \
    %{buildroot}%{_unitdir}/airy-disk-health.service
test -f %{buildroot}%{_unitdir}/airy-disk-health.timer
grep -qxF 'OnCalendar=daily' \
    %{buildroot}%{_unitdir}/airy-disk-health.timer
test -f %{buildroot}%{_unitdir}/airy-rt-bandwidth.service
grep -qxF 'ExecStart=/usr/bin/airy-rt-cap apply' \
    %{buildroot}%{_unitdir}/airy-rt-bandwidth.service
grep -qxF 'Before=agentrt.target rtkit-daemon.service display-manager.service' \
    %{buildroot}%{_unitdir}/airy-rt-bandwidth.service
grep -qxF 'disable airy-rt-bandwidth.service' \
    %{buildroot}%{_presetdir}/90-airymax.preset
grep -qxF 'disable airy-disk-mount.service' \
    %{buildroot}%{_presetdir}/90-airymax.preset
grep -qxF 'disable airy-disk-health.timer' \
    %{buildroot}%{_presetdir}/90-airymax.preset
grep -qxF 'disable airy-llm.service' \
    %{buildroot}%{_presetdir}/90-airymax.preset
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
%{_unitdir}/*.timer
%{_presetdir}/90-airymax.preset
%{_presetdir}/99-airymax-default-disable.preset
%{_bindir}/airy-disk
%{_bindir}/airy-update
%{_bindir}/airy-model
%{_bindir}/airy-rt-cap
%{python3_sitelib}/airydisk
%{python3_sitelib}/airyllm
%{python3_sitelib}/airyupdate
%{python3_sitelib}/airymax_rt

%changelog
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-5
- Ship airy-rt-cap, the airymax_rt package and airy-rt-bandwidth.service
  so the RT budget is applied before rtkit-daemon starts; the desktop
  release package carried a shell copy of the same policy, which the
  boot unit could not report on
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-4
- Ship airy-disk-mount.service and the airy-disk-health pair so an
  installed system restores /data before agentrt.target starts and
  reports capacity or read-only faults instead of failing silently
- Pin both to disabled: whether a data partition exists, and when
  capacity alerts are wanted, is an install-time decision; the
  kickstart enables them on the boot list
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-3
- Ship airy-model, the airyllm runtime package and airy-llm.service,
  so the local inference endpoint exists on installed systems; the
  unit was pinned to disabled by the preset yet no package delivered
  it, leaving the service unstartable after imaging
- The command line carries the offline asset channel, the status and
  verify queries with the 0/10/1 exit contract, and the serve path
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-2
- Ship airy-update with the airyupdate package and the daily check
  timer, so upgrades and imaging share one identity implementation
- Deliver both Python packages as whole-directory archives: per-file
  sources collide on the shared _sourcedir because the modules have
  the same names
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-1
- Product version bump to 0.0.4; package content unchanged in this
  commit, 0.0.4 work items land on top of it
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
