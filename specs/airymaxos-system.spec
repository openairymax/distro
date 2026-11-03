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
#   7. 部署 /usr/bin/airy-power、airymax_power Python 包、电源档位单元
#      与周期重评定时器，启动期落档、周期复核与人工排查共用同一份判定；
#   8. 部署 /usr/bin/airy-probe 与 airymax_probe Python 包，十条追踪通道、
#      两条注入通道与三处静态计数的清点共用同一份证据实现（X-02）；
#   9. 部署 airy-rt-coexist 单元对，把桌面 slice 的运行时权重从基线
#      抬到保护档，使实时负载与桌面负载按 PSI 证据共存（X-05）；
#  10. 在 %%post/%%postun 内刷新 systemd 单元缓存。
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
# spec-lint: source-bundle ../../system/services/airymax_power
# spec-lint: source-bundle ../../system/services/airymax_probe

%global airy_version 0.0.4
%global airy_release 17
%{!?_unitdir:%global _unitdir /usr/lib/systemd/system}
%{!?_presetdir:%global _presetdir /usr/lib/systemd/system-preset}

Name:           airymaxos-system
Version:        %{airy_version}
Release:        %{airy_release}%{?dist}
Summary:        AirymaxOS systemd units, targets and runtime scripts
License:        AGPL-3.0-or-later
URL:            https://atomgit.com/openairymax/agent-linux
ExclusiveArch:  x86_64 aarch64

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
Source36:       airy-power
Source37:       airy-power.service
Source38:       airy-power.timer
Source39:       airymax_power-%{version}.tar.gz
Source40:       airy-probe
Source41:       airymax_probe-%{version}.tar.gz
Source42:       airy-rt-coexist.service
Source43:       airy-rt-coexist.timer
Source44:       airy-rt-lat.c

BuildRequires:  gcc
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
share one verdict implementation. The airy-rt-coexist unit pair raises
the desktop slice weight on a runtime property when the CPU pressure
crosses the threshold and leaves the static baseline alone, so a boot
without a daemon to explain it comes back at the baseline weight. The
airy-power command with its power and thermal package applies the
platform profile, CPU governor and energy preference on boot and on a
one-minute timer, so the verdict shown by hand is the verdict the boot
applied. The airy-probe command with its trace package reports the ten
agent tracepoints, the two injection channels and the three static
counters, so an acceptance run has one evidence source instead of three
ad hoc reads. The airy-rt-lat command measures wake-up latency from a
FIFO periodic thread, so the real-time acceptance gate runs on a machine
that only installed this package. Units are installed disabled; the
installer enables them explicitly so that server and desktop profiles
can opt out without editing the package payload.

%prep
%setup -q -c -T
install -m 0644 %{SOURCE44} airy-rt-lat.c

%build
gcc %{optflags} -std=c11 -Wall -Wextra -Werror -o airy-rt-lat \
    airy-rt-lat.c -lpthread

%install
install -d -m 0755 %{buildroot}%{_unitdir}
install -m 0644 %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE4} %{SOURCE5} \
    %{SOURCE6} %{SOURCE7} %{SOURCE8} %{SOURCE9} %{SOURCE10} %{SOURCE11} \
    %{SOURCE12} %{SOURCE13} %{SOURCE14} %{SOURCE16} \
    %{SOURCE23} %{SOURCE24} %{SOURCE27} \
    %{SOURCE30} %{SOURCE31} %{SOURCE32} %{SOURCE35} \
    %{SOURCE37} %{SOURCE38} %{SOURCE42} %{SOURCE43} \
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
install -m 0755 %{SOURCE36} %{buildroot}%{_bindir}/airy-power
install -m 0755 %{SOURCE40} %{buildroot}%{_bindir}/airy-probe
install -m 0755 airy-rt-lat %{buildroot}%{_bindir}/airy-rt-lat
install -d -m 0755 %{buildroot}%{python3_sitelib}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE25}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE26}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE29}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE34}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE39}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE41}

%check
test -x %{buildroot}/usr/lib/airymaxos/scripts/firstboot.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/health_check.sh
test -x %{buildroot}%{_bindir}/airy-disk
test -x %{buildroot}%{_bindir}/airy-update
test -x %{buildroot}%{_bindir}/airy-model
test -x %{buildroot}%{_bindir}/airy-rt-cap
test -x %{buildroot}%{_bindir}/airy-power
test -x %{buildroot}%{_bindir}/airy-probe
test -x %{buildroot}%{_bindir}/airy-rt-lat
PYTHONPATH=%{buildroot}%{python3_sitelib} python3 -B -c '
import airydisk.cli
import airyupdate.cli
import airyllm.cli
import airymax_rt.cli
import airymax_power.cli
import airymax_probe.cli'
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
test -f %{buildroot}%{_unitdir}/airy-rt-coexist.service
grep -qxF 'ExecStart=/usr/bin/airy-rt-cap coexist --apply' \
    %{buildroot}%{_unitdir}/airy-rt-coexist.service
grep -qxF 'Before=display-manager.service' \
    %{buildroot}%{_unitdir}/airy-rt-coexist.service
test -f %{buildroot}%{_unitdir}/airy-rt-coexist.timer
grep -qxF 'OnUnitInactiveSec=60s' \
    %{buildroot}%{_unitdir}/airy-rt-coexist.timer
grep -qxF 'Unit=airy-rt-coexist.service' \
    %{buildroot}%{_unitdir}/airy-rt-coexist.timer
grep -qxF 'disable airy-rt-coexist.service' \
    %{buildroot}%{_presetdir}/90-airymax.preset
grep -qxF 'disable airy-rt-coexist.timer' \
    %{buildroot}%{_presetdir}/90-airymax.preset
test -f %{buildroot}%{_unitdir}/airy-power.service
grep -qxF 'ExecStart=/usr/bin/airy-power apply' \
    %{buildroot}%{_unitdir}/airy-power.service
grep -qxF 'SuccessExitStatus=3' \
    %{buildroot}%{_unitdir}/airy-power.service
grep -qxF 'Before=agentrt.target display-manager.service' \
    %{buildroot}%{_unitdir}/airy-power.service
grep -qxF 'RuntimeDirectory=airy-power' \
    %{buildroot}%{_unitdir}/airy-power.service
test -f %{buildroot}%{_unitdir}/airy-power.timer
grep -qxF 'OnUnitInactiveSec=60s' \
    %{buildroot}%{_unitdir}/airy-power.timer
grep -qxF 'Unit=airy-power.service' \
    %{buildroot}%{_unitdir}/airy-power.timer
grep -qxF 'disable airy-power.service' \
    %{buildroot}%{_presetdir}/90-airymax.preset
grep -qxF 'disable airy-power.timer' \
    %{buildroot}%{_presetdir}/90-airymax.preset
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
%{_bindir}/airy-power
%{_bindir}/airy-probe
%{_bindir}/airy-rt-lat
%{python3_sitelib}/airydisk
%{python3_sitelib}/airyllm
%{python3_sitelib}/airyupdate
%{python3_sitelib}/airymax_rt
%{python3_sitelib}/airymax_power
%{python3_sitelib}/airymax_probe

%changelog
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-17
- Cap cpuidle depth against the real-time budget: on AC below the hot
  zone, disable idle states whose exit latency exceeds 1000us, and
  restore the firmware default on battery or when the package is already
  hot. The 285H measured 1048us on C3_ACPI, which alone pushed wakeup
  latency past the soft real-time limit
* Tue Nov 03 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-16
- Trigger the load notice from the same strain verdict the profile uses,
  so a machine that is only swapping still gets one broadcast instead of
  raising the energy preference in silence
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-15
- Copy airy-rt-lat.c into the build tree before compiling, so
  find-debuginfo can attribute the object back to a source file and
  openEuler's debugsource subpackage is not left with an empty file
  list, which failed the install phase on the 285H build host
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-14
- Fold whole-machine load into the power policy: PSI some avg10 when
  available, loadavg and meminfo otherwise, with swap usage scored on
  its own because the 285H stalled with 14G still available
- Keep the AC profile at balanced instead of low-power while load is
  high and raise the energy preference to balance_performance, so the
  run queue drains instead of growing under a long local model task
- Broadcast one warning when reclaim pressure turns hot, and reset it
  after the pressure falls so a later episode is not muted
- Share the one-shot notice path between the low battery duty and the
  pressure warning instead of keeping two copies of the same logic
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-13
- Ship airy-rt-lat, a FIFO periodic wake-up latency probe, so an
  installed machine produces the real-time baseline without rt-tests
- The acceptance gate depended on cyclictest, which neither the mirror
  nor the image carries, so the baseline could not be produced at all
- Refuse to print numbers when SCHED_FIFO cannot be acquired: an
  unprivileged run measures scheduler unfairness, not RT capability
- The package now builds one binary, so it is architecture specific
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-12
- Ship the airy-rt-coexist unit pair and the coexist subcommand so the
  desktop slice weight follows the CPU pressure instead of a fixed value
- The RT budget constrains SCHED_FIFO only; desktop stalls under an agent
  load come from the CFS side, which no existing unit observed
- Write the weight as a runtime property and keep the static slice at the
  baseline, so a boot without the timer reflects the declared policy
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-11
- Broadcast a warning at 10% charge and request a controlled poweroff at
  5%, so a machine that cannot be recharged shuts down cleanly instead of
  losing power with no shutdown record
- Restrict the action to battery and weak-adapter sources, and skip it
  when the charge cannot be read, so charging and unknown machines are
  never interrupted
- Record the action level under /run to broadcast once per level, and
  keep it out of the read-only status path so verification never shuts a
  machine down
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-10
- Add the real-time capability matrix to airy-rt-cap: probe eight
  conditions (PREEMPT_RT, RT budget, cgroup accounting, SCHED_DEADLINE,
  threaded IRQs, CPU isolation, cpufreq governor, clocksource) and grade
  the machine as ready, soft or none
- Distinguish "not supported" from "not readable" for every probe, so a
  denied or missing node is never reported as a kernel without support
- Reuse the RT bandwidth cgroup detection in the matrix instead of a
  second layout check, keeping one verdict for one machine
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-9
- Report tracefs nodes as denied instead of raising when the probe runs
  without root: the event directories are 0700 and stat throws EACCES,
  which used to abort status with a traceback
- Advise sudo when any event is denied, so the reader does not conclude
  that the kernel lacks the tracepoints and go looking for another one
- Fold the three-way directory check into one helper shared by event
  discovery, tracefs selection and the sampling window
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-8
- Treat an adapter that is online while the battery still discharges as
  a weak source and fall to the cool profile, so a load above the
  adapter's capacity no longer drains the battery to a brownout
- Pace the guard by the throttle counter's growth rate: 285H reported
  48 C next to tens of thousands of throttles, and temperature alone
  cannot see the power limit that causes them
- Give the oneshot a preserved runtime directory: the guard's sample
  lives in /run and ProtectSystem=strict denies every other write path
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-7
- Ship airy-probe and the airymax_probe package so acceptance reads the
  ten agent tracepoints, the two injection channels and the three
  static counters through one implementation
- The ten tracepoints shipped in 0.0.3 had no reader; every check was
  an ad hoc tracefs read and no run left a recomputable verdict
- The probe only reads or attempts an empty write, and reports the
  errno for each channel, so the deferred injection interface is
  recorded as evidence instead of being guessed at
* Mon Nov 02 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-6
- Ship airy-power, the airymax_power package, airy-power.service and
  airy-power.timer so the platform profile, CPU governor and energy
  preference follow the power source and the thermal headroom
- The 285H stopped with firmware defaults of performance everywhere and
  a thermal zone whose critical trip sits at 80 C; without this unit
  the machine throttles thousands of times in under an hour
- The timer re-evaluates every minute, so a change of power source or a
  rising zone is corrected without waiting for the next boot
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
