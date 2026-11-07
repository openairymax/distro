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
#   6. 部署 /usr/bin/airy-rt-cap、airymax_rt Python 包、实时带宽与换页上限
#      两个单元及上限的重写定时器，启动期分配与人工排查共用同一份带宽判定
#      实现（X-01）；
#   7. 部署 /usr/bin/airy-power、airymax_power Python 包、电源档位单元
#      与周期重评定时器，启动期落档、周期复核与人工排查共用同一份判定；
#   8. 部署 /usr/bin/airy-probe 与 airymax_probe Python 包，十条追踪通道、
#      两条注入通道与三处静态计数的清点共用同一份证据实现（X-02）；
#   9. 部署 airymax_observe Python 包，供 airy-observe 的 hardware 与
#      firmware 两个子命令调用；整机硬件清点只读 sysfs，固件清点把模块
#      自报的期望文件名与本次开机日志对起来，缺失、无证据与在位三种结论
#      共用同一份判定（I-24）。命令本身归发行包，本包不再安装同名入口；
#  10. 部署 airy-rt-coexist 单元对，把桌面 slice 的运行时权重从基线
#      抬到保护档，使实时负载与桌面负载按 PSI 证据共存（X-05）；
#  11. 部署 /usr/lib/airymaxos/boot-set，声明开机必须启用的单元清单；
#  12. 部署 airy-boot-mount 单元与 boot_mount.sh，在数据分区之前报出根
#      是否只读、/boot 与 ESP 是否独立挂载，装机与引导修复的现场诊断
#      因此不依赖事后翻 fstab 与 mount 输出；
#  13. 部署 /usr/bin/airy-bright 与 airybright Python 包：屏幕与键盘背光
#      的调节入口。判定与写入分属 device/plan/policy，命令行只做分派，
#      因此在没有背光设备的机器上退 4 而不是报成功（I-25）；
#  14. 在 %%post/%%postun 内刷新 systemd 单元缓存，在 %%posttrans 内按
#      该清单启用并启动单元。
#
# 单元启用（systemctl enable）只有一条实现：读 /usr/lib/airymaxos/boot-set。
# 装机由 kickstart 按清单下启用位（镜像内无法启用未来会在目标机跑的单元），
# 已运行机器升级由 %%posttrans 按同一份清单补启用并启动（OS-OPS-010）。
# 两处各写一份清单必然漂移，症状是「某台机器治理静默缺席」——换页无上界、
# 电源与热治理不接管，从任何服务状态都看不出来。
#
# 随包落盘两份 preset：
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
# spec-lint: source-bundle ../../system/services/airymax_observe
# spec-lint: source-bundle ../../system/services/airybright

%global airy_version 0.0.4
%global airy_release 47
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
Source45:       airymax-agent.slice
Source46:       50-airymax-memory.conf
Source48:       airymax_observe-%{version}.tar.gz
Source49:       boot-set
Source50:       boot_set.sh
Source51:       airy-rt-memcap.service
Source52:       airy-rt-memcap.timer
Source53:       ui.sh
Source54:       stage_run.sh
Source55:       airy-boot-mount.service
Source56:       boot_mount.sh
Source57:       airy-bright
Source58:       airybright-%{version}.tar.gz
Source59:       boot_watch.sh
Source60:       airy-boot-watch.service
Source61:       airy-boot-watch.timer
Source62:       con.sh
Source63:       airymax-net-doctor.service
Source64:       net_doctor.sh

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
share one verdict implementation. The memory and swap ceiling is a unit
of its own rather than a post step of the bandwidth unit: it only needs
the slice directories, which exist at boot, while the bandwidth budget
needs the desktop slice, which only exists after login, so a partial
budget used to skip the ceiling entirely and leave swap unbounded. The
ceiling is also the one value systemd resets to infinity on reload, so a
timer rewrites it every minute and retries what a busy slice rejected at
boot. The
airy-rt-coexist unit pair raises
the desktop slice weight on a runtime property when the CPU pressure
crosses the threshold and leaves the static baseline alone, so a boot
without a daemon to explain it comes back at the baseline weight. The
airy-power command with its power and thermal package applies the
platform profile, CPU governor and energy preference on boot and on a
one-minute timer, so the verdict shown by hand is the verdict the boot
applied. The airy-probe command with its trace package reports the ten
agent tracepoints, the two injection channels and the three static
counters, so an acceptance run has one evidence source instead of three
ad hoc reads. The airy-observe command's hardware subcommand, backed by the
survey package, reports what the machine actually has: a class with no sysfs
node is absent, a device state is copied verbatim, and an rfkill switch left
off is blocked, with cpu, block and net mandatory and every other class
optional. Its firmware subcommand compares the file names the loaded modules
declare against this boot's kernel log and keeps three states apart, so a
driver that loaded without finding its blob is missing rather than ok and a
file with no log line is unknown rather than loaded. The airy-rt-lat command
measures wake-up latency from a FIFO periodic thread, so the real-time
acceptance gate runs on a machine that only installed this package. Units
are installed disabled; the installer enables them explicitly so that
server and desktop profiles can opt out without editing the payload.

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
    %{SOURCE30} %{SOURCE31} %{SOURCE32} %{SOURCE35} %{SOURCE51} %{SOURCE52} \
    %{SOURCE37} %{SOURCE38} %{SOURCE42} %{SOURCE43} %{SOURCE45} \
    %{SOURCE55} %{SOURCE60} %{SOURCE61} %{SOURCE63} \
    %{buildroot}%{_unitdir}/
install -m 0644 %{SOURCE0} %{SOURCE15} %{buildroot}%{_unitdir}/
install -d -m 0755 %{buildroot}%{_unitdir}/user.slice.d
install -m 0644 %{SOURCE46} \
    %{buildroot}%{_unitdir}/user.slice.d/50-airymax-memory.conf
install -d -m 0755 %{buildroot}/usr/lib/airymaxos/scripts
install -m 0755 %{SOURCE17} %{SOURCE18} %{SOURCE50} %{SOURCE53} \
    %{SOURCE54} %{SOURCE56} %{SOURCE59} %{SOURCE62} %{SOURCE64} \
    %{buildroot}/usr/lib/airymaxos/scripts/
install -d -m 0755 %{buildroot}%{_presetdir}
install -m 0644 %{SOURCE19} %{SOURCE20} %{buildroot}%{_presetdir}/
install -m 0644 %{SOURCE49} %{buildroot}/usr/lib/airymaxos/boot-set
install -d -m 0755 %{buildroot}%{_bindir}
install -m 0755 %{SOURCE21} %{buildroot}%{_bindir}/airy-disk
install -m 0755 %{SOURCE22} %{buildroot}%{_bindir}/airy-update
install -m 0755 %{SOURCE28} %{buildroot}%{_bindir}/airy-model
install -m 0755 %{SOURCE33} %{buildroot}%{_bindir}/airy-rt-cap
install -m 0755 %{SOURCE36} %{buildroot}%{_bindir}/airy-power
install -m 0755 %{SOURCE40} %{buildroot}%{_bindir}/airy-probe
install -m 0755 %{SOURCE57} %{buildroot}%{_bindir}/airy-bright
install -m 0755 airy-rt-lat %{buildroot}%{_bindir}/airy-rt-lat
install -d -m 0755 %{buildroot}%{python3_sitelib}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE25}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE26}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE29}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE34}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE39}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE41}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE48}
tar -C %{buildroot}%{python3_sitelib} -xzf %{SOURCE58}

%check
test -x %{buildroot}/usr/lib/airymaxos/scripts/firstboot.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/health_check.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/boot_set.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/ui.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/stage_run.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/boot_mount.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/boot_watch.sh
test -x %{buildroot}/usr/lib/airymaxos/scripts/net_doctor.sh
bash -n %{buildroot}/usr/lib/airymaxos/scripts/net_doctor.sh
bash -n %{buildroot}/usr/lib/airymaxos/scripts/boot_set.sh
bash -n %{buildroot}/usr/lib/airymaxos/scripts/ui.sh
bash -n %{buildroot}/usr/lib/airymaxos/scripts/stage_run.sh
bash -n %{buildroot}/usr/lib/airymaxos/scripts/boot_mount.sh
bash -n %{buildroot}/usr/lib/airymaxos/scripts/boot_watch.sh
bash -n %{buildroot}/usr/lib/airymaxos/scripts/con.sh
test "$(bash -c '. %{buildroot}/usr/lib/airymaxos/scripts/ui.sh; ui_total')" = 9
# 阶段行与卡点报告共用 con.sh 的通道判据；source 失败时 ui_total 仍能打印，
# 上面那条断言看不出缺失，故这里直接断言判据函数确实被引入。
test "$(bash -c '. %{buildroot}/usr/lib/airymaxos/scripts/ui.sh;
    declare -F con_sink >/dev/null && echo ok')" = ok
test -x %{buildroot}%{_bindir}/airy-disk
test -x %{buildroot}%{_bindir}/airy-update
test -x %{buildroot}%{_bindir}/airy-model
test -x %{buildroot}%{_bindir}/airy-rt-cap
test -x %{buildroot}%{_bindir}/airy-power
test -x %{buildroot}%{_bindir}/airy-probe
test -x %{buildroot}%{_bindir}/airy-bright
test -x %{buildroot}%{_bindir}/airy-rt-lat
PYTHONPATH=%{buildroot}%{python3_sitelib} python3 -B -c '
import airydisk.cli
import airyupdate.cli
import airyllm.cli
import airymax_rt.cli
import airymax_power.cli
import airymax_probe.cli
import airymax_observe.cli
import airybright.cli'
PYTHONPATH=%{buildroot}%{python3_sitelib} python3 -B -m airymax_observe --help >/dev/null
test -f %{buildroot}%{_unitdir}/agentrt.target
test -f %{buildroot}%{_unitdir}/agentrt-firstboot.service
test -f %{buildroot}%{_unitdir}/airy-incident@.service
grep -qxF 'ConditionPathExists=/usr/sbin/airyctl' \
    %{buildroot}%{_unitdir}/airy-incident@.service
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
grep -qxF 'Slice=airymax-agent.slice' \
    %{buildroot}%{_unitdir}/airy-llm.service
test -f %{buildroot}%{_unitdir}/airymax-agent.slice
grep -qxF 'MemoryMax=90%' \
    %{buildroot}%{_unitdir}/airymax-agent.slice
grep -qxF 'MemorySwapMax=10%' \
    %{buildroot}%{_unitdir}/airymax-agent.slice
test -f %{buildroot}%{_unitdir}/user.slice.d/50-airymax-memory.conf
grep -qxF 'MemoryMax=85%' \
    %{buildroot}%{_unitdir}/user.slice.d/50-airymax-memory.conf
grep -qxF 'MemorySwapMax=15%' \
    %{buildroot}%{_unitdir}/user.slice.d/50-airymax-memory.conf
test -f %{buildroot}%{_unitdir}/airy-boot-mount.service
grep -qxF 'ExecStart=/usr/lib/airymaxos/scripts/stage_run.sh 基础挂载 3 root,boot,efi /usr/lib/airymaxos/scripts/boot_mount.sh' \
    %{buildroot}%{_unitdir}/airy-boot-mount.service
grep -qxF 'Before=airy-disk-mount.service agentrt.target multi-user.target' \
    %{buildroot}%{_unitdir}/airy-boot-mount.service
grep -qxF 'SuccessExitStatus=3' \
    %{buildroot}%{_unitdir}/airy-boot-mount.service
grep -qxF 'disable airy-boot-mount.service' \
    %{buildroot}%{_presetdir}/90-airymax.preset
test -f %{buildroot}%{_unitdir}/airy-boot-watch.service
grep -qxF 'ExecStart=/usr/lib/airymaxos/scripts/boot_watch.sh' \
    %{buildroot}%{_unitdir}/airy-boot-watch.service
test -f %{buildroot}%{_unitdir}/airy-boot-watch.timer
grep -qxF 'OnBootSec=60s' \
    %{buildroot}%{_unitdir}/airy-boot-watch.timer
grep -qxF 'Unit=airy-boot-watch.service' \
    %{buildroot}%{_unitdir}/airy-boot-watch.timer
grep -qxF 'disable airy-boot-watch.timer' \
    %{buildroot}%{_presetdir}/90-airymax.preset
test -f %{buildroot}%{_unitdir}/airymax-net-doctor.service
grep -qxF 'ExecStart=-/usr/lib/airymaxos/scripts/net_doctor.sh' \
    %{buildroot}%{_unitdir}/airymax-net-doctor.service
grep -qxF 'After=NetworkManager.service' \
    %{buildroot}%{_unitdir}/airymax-net-doctor.service
grep -qxF 'Before=graphical.target' \
    %{buildroot}%{_unitdir}/airymax-net-doctor.service
grep -qxF 'Type=oneshot' %{buildroot}%{_unitdir}/airymax-net-doctor.service
grep -qxF 'RemainAfterExit=yes' \
    %{buildroot}%{_unitdir}/airymax-net-doctor.service
grep -qxF 'RuntimeDirectory=airymaxos' \
    %{buildroot}%{_unitdir}/airymax-net-doctor.service
grep -qxF 'RuntimeDirectoryMode=0755' \
    %{buildroot}%{_unitdir}/airymax-net-doctor.service
grep -qxF 'disable airymax-net-doctor.service' \
    %{buildroot}%{_presetdir}/90-airymax.preset
test -f %{buildroot}%{_unitdir}/airy-disk-mount.service
grep -qxF 'ExecStart=/usr/lib/airymaxos/scripts/stage_run.sh 数据分区 4 - /usr/bin/airy-disk mount' \
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
grep -qxF 'ExecStart=/usr/lib/airymaxos/scripts/stage_run.sh 运行时带宽 3 state,applied /usr/bin/airy-rt-cap apply' \
    %{buildroot}%{_unitdir}/airy-rt-bandwidth.service
grep -qxF 'SuccessExitStatus=3' \
    %{buildroot}%{_unitdir}/airy-rt-bandwidth.service
! grep -q '^ExecStartPost=' \
    %{buildroot}%{_unitdir}/airy-rt-bandwidth.service
grep -qxF 'Before=agentrt.target rtkit-daemon.service user@.service display-manager.service' \
    %{buildroot}%{_unitdir}/airy-rt-bandwidth.service
test -f %{buildroot}%{_unitdir}/airy-rt-memcap.service
grep -qxF 'ExecStart=/usr/lib/airymaxos/scripts/stage_run.sh 换页上限 3 layout,steps /usr/bin/airy-rt-cap memcap --apply' \
    %{buildroot}%{_unitdir}/airy-rt-memcap.service
grep -qxF 'SuccessExitStatus=3' \
    %{buildroot}%{_unitdir}/airy-rt-memcap.service
grep -qxF 'disable airy-rt-memcap.service' \
    %{buildroot}%{_presetdir}/90-airymax.preset
test -f %{buildroot}%{_unitdir}/airy-rt-memcap.timer
grep -qxF 'Unit=airy-rt-memcap.service' \
    %{buildroot}%{_unitdir}/airy-rt-memcap.timer
grep -qxF 'OnUnitInactiveSec=60s' \
    %{buildroot}%{_unitdir}/airy-rt-memcap.timer
grep -qxF 'disable airy-rt-memcap.timer' \
    %{buildroot}%{_presetdir}/90-airymax.preset
! grep -q '^RemainAfterExit=' \
    %{buildroot}%{_unitdir}/airy-rt-memcap.service
test -f %{buildroot}%{_unitdir}/airy-rt-coexist.service
grep -qxF 'ExecStart=/usr/lib/airymaxos/scripts/stage_run.sh 桌面RT共存 - mode,weight,current,applied /usr/bin/airy-rt-cap coexist --apply' \
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
grep -qxF 'ExecStart=/usr/lib/airymaxos/scripts/stage_run.sh 电源与热治理 3 landed,cap,severity,charge /usr/bin/airy-power apply' \
    %{buildroot}%{_unitdir}/airy-power.service
grep -qxF 'SuccessExitStatus=3' \
    %{buildroot}%{_unitdir}/airy-power.service
grep -qxF 'Before=agentrt.target display-manager.service' \
    %{buildroot}%{_unitdir}/airy-power.service
grep -qE '^RuntimeDirectory=([^ ]+ +)*airy-power( |$)' \
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
# 启用清单只断言格式与本包自有治理项：清单里的兄弟包单元（发行包的
# airymax-desktop-ready、上游的 lightdm 等）在本 buildroot 内不存在，
# 逐项存在性由源码级用例 tools/tests/test_boot_set.py 跨包核对。
test -s %{buildroot}/usr/lib/airymaxos/boot-set
! grep -q "$(printf '\r')" %{buildroot}/usr/lib/airymaxos/boot-set
! grep -q "$(printf '\t')" %{buildroot}/usr/lib/airymaxos/boot-set
! grep -Eqv '^([[:space:]]*(#|$)|[A-Za-z0-9@._-]+\.(service|timer|target|slice|socket|path))$' \
    %{buildroot}/usr/lib/airymaxos/boot-set
test -z "$(grep -Ev '^[[:space:]]*(#|$)' %{buildroot}/usr/lib/airymaxos/boot-set |
    sort | uniq -d)"
for unit in airy-rt-bandwidth.service airy-rt-memcap.service \
    airy-rt-memcap.timer airy-power.service airy-power.timer \
    airy-rt-coexist.service airy-rt-coexist.timer airy-disk-mount.service \
    airy-disk-health.timer airymax-update-check.timer \
    airy-boot-mount.service airy-boot-watch.timer \
    airymax-net-doctor.service; do
    grep -qxF "${unit}" %{buildroot}/usr/lib/airymaxos/boot-set || exit 1
done

%post
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || :
fi

%postun
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || :
fi

# 升级路径的启用点。preset 只表达默认关闭，装机由 kickstart 调同一个脚本
# 下启用位；已运行机器升级到本版本时没有任何组件碰 systemd，新治理单元
# 装完就是关的，症状是换页无上界、电源与热治理不接管而无人察觉。
# 脚本以 enable --now --no-block 落位，不把事务挂在一个正在启动的单元上；
# 失败不回滚，单元自身会留下 failed 状态供归因。管理员要关掉某项治理应
# mask 单元，enable 对 masked 无效。只有 systemd 在跑时才动作：镜像
# 合成的 chroot 与装机前的 %%posttrans 都不该改启用位。
%posttrans
if [ -d /run/systemd/system ] && [ -x /usr/lib/airymaxos/scripts/boot_set.sh ]; then
    /usr/lib/airymaxos/scripts/boot_set.sh || :
fi

%files
%defattr(-, root, root, -)
%dir /usr/lib/airymaxos
%dir /usr/lib/airymaxos/scripts
/usr/lib/airymaxos/scripts/*.sh
/usr/lib/airymaxos/boot-set
%{_unitdir}/*.service
%{_unitdir}/*.slice
%dir %{_unitdir}/user.slice.d
%{_unitdir}/user.slice.d/*.conf
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
%{_bindir}/airy-bright
%{_bindir}/airy-rt-lat
%{python3_sitelib}/airydisk
%{python3_sitelib}/airyllm
%{python3_sitelib}/airyupdate
%{python3_sitelib}/airymax_rt
%{python3_sitelib}/airymax_power
%{python3_sitelib}/airymax_probe
%{python3_sitelib}/airymax_observe
%{python3_sitelib}/airybright

%changelog
* Thu Nov 05 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-47
- Fix the boot watch going silent on serial. It skipped the serial write
  whenever ttyS0 appeared in the active console list, but /dev/console
  goes to the console registered last on the command line, and the
  product command line is "console=ttyS0,115200 console=tty0": every
  userspace line, the stuck report included, was written to the local VT
  while the serial side stayed empty (run 41925092075 lost the whole
  report this way). The serial node is now always written first and the
  console only when it does not resolve to the same sink, each write
  bounded so a wedged console layer cannot hang the observer.
- Forward journald console output to the serial device in the acceptance
  image. The default sink is /dev/console, so the unit shutdown lines and
  the desktop session messages stopped at 3.9 seconds in that run, and
  nothing explained why the graphical target was never reached.
- Add an acceptance-only liveness heartbeat writing one line every thirty
  seconds straight to the serial device: uptime, pending jobs, the
  /dev/dri node count, and the states of graphical.target and lightdm.
  The report unit is ordered after graphical.target, so a boot that never
  reaches it produces no evidence at all; the heartbeat runs from
  timers.target and survives exactly that case.

* Wed Nov 04 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-46
- Ship a boot watch that reports where a boot stopped. The nine stages
  print as they run, so a machine that hangs after the last stage it
  reached shows a screen that looks finished: no failure line, no unit
  name, nothing to attach a report to. The watch is driven by a timer
  rather than pulled in by a target, because a target that is never
  reached cannot start the unit that would describe why.
- It judges progress by the queued job table, not by elapsed time: two
  identical reads forty seconds apart mean no unit advanced, while a
  slow boot still changes the table on every read and stays silent. A
  healthy boot prints nothing at all.
- The observer must not become a new failure. It always exits zero, so
  it never lands in the failed-unit list that the acceptance criteria
  count; it folds stderr into stdout, so none of its own lines reach
  the error bucket of the journal; and it writes to the console and the
  serial port both, since either one alone can be the channel that is
  cut.

* Wed Nov 04 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-45
- Ship the airy-bright command and its airybright package. The backlight
  entry existed in the source tree and passed its gate, but no spec
  installed it, so the installed image had no way to change brightness.
  The command refuses with a distinct exit code when the machine has no
  backlight node instead of reporting success.

* Wed Nov 04 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-44
- Add the firmware subcommand to airy-observe. A driver that loads without
  finding its blob leaves nothing behind on disk, and the expected file
  names live only in the module's own metadata, so the only common ground
  is this boot's kernel log. The command reads the expected names from
  modinfo, the actual ones from the log, and reports loaded, missing or
  unknown per file. Unknown is a separate verdict on purpose: a file with
  no log line proves nothing, and folding it into loaded would report a
  silent failure as a success.
- Keep the three known failure signatures as warnings of their own. They
  end with the module loaded, so the module list and sysfs both look
  healthy; only the log still carries the line. Deduplicating them needs
  the timestamp stripped first, since the same message repeats with a
  different uptime and would otherwise be counted twice.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-43
- Add the base mount stage, the first of the nine boot stages. The stage
  reads /proc/self/mountinfo and reports whether the root is writable and
  whether /boot and the ESP are independently mounted, so a live image that
  silently wrote into a directory on the root instead of the ESP is visible
  at boot rather than after a reboot with no new boot entry.
- A read-only root is reported as a note, not a failure: rescue and recovery
  boots mount the root read-only on purpose and the machine still comes up.
  The consequences surface at the first stage that writes.
- The unit is ordered before the data partition unit so a mount failure can
  be attributed to the root or to the disk, not to both.
- Install the unit, the script, the preset entry and the boot-set entry, and
  pin the exact ExecStart in %check. Also refresh the five ExecStart
  assertions that still expected the pre-runner form and therefore could
  never have matched after the runner migration.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-42
- Route five boot-time units through one stage runner. The stage line used to
  be assembled by a per-tool script, so changing the verdict ladder or the key
  order meant editing several near-identical copies, and the copy that was
  missed printed a differently shaped line on that machine.
- The runner takes the stage name, the exit codes that mean "note" and the
  keys to lift from the tool's first line, so a unit file now states its own
  stage contract while wording, numbering and column width stay in ui.sh.
- Wire the data partition, runtime bandwidth, swap ceiling, power and desktop
  coexistence stages through it; the swap ceiling, power and coexistence units
  are timer-driven and now print once per boot instead of once a minute.
- Take the stage number from the table instead of the caller: a script that
  repeated "step N of M" could disagree with the table after a reorder.
* Tue Nov 03 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-37
- Join the only continuous actuator this machine has to the guard. On 285H
  every cooling device is firmware-managed, so governors and EPP are the
  discrete knobs and intel_pstate max_perf_pct plus no_turbo are the only
  continuous ones; a thermal squeeze needs a continuous shrink, not another
  governor step.
- The four-rung ladder (50/70/90/100 percent, turbo off below 90) takes the
  worst of thermal margin, throttle growth and whole-machine load. Battery
  and weak-supply shift one rung down; an unknown supply does not, because
  treating "cannot read" as battery capped an idle 285H at 50 percent.
- Tightening lands at once, relaxing needs three consecutive relaxed rounds
  recorded in /run/airy-power/ceiling. The 285H run showed full load tighten
  100 to 90 within one cycle and recovery after exactly three rounds, with
  the firmware throttle count untouched the whole time.
* Tue Nov 03 2026 Decheng Li <lidecheng@spharx.cn> - 0.0.4-36
- Keep the restart policy from fighting the admission verdict. 75 is a
  decision, not a malfunction: restarting it five seconds later meets the
  same memory and only adds another start attempt inside the window that is
  already short of memory. 78 is the same kind of answer for missing assets.
- RestartPreventExitStatus=75 78 stops the unit at the verdict. OnFailure
  still records the event, so the refusal stays visible without a retry loop
  and the start limit is no longer what has to catch it.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-35
- Put the admission verdict on the launch path. The check existed but nothing
  called it, so a service unit could still start an instance the machine could
  not hold and let the restart policy turn "does not fit" into "starts, thrashes,
  starts again". airy-model serve now derives the resident size from the same
  manifest read it uses for its arguments and asks the one admit implementation
  before exec.
- The size is the asset bytes plus a 2GiB engine floor, measured on 285H where
  a 27B single-slot instance held 18.5G resident against roughly 16.5G of
  weights. Concurrency above that is not guessed; the slice ceiling stays the
  backstop. A refusal exits 75 and prints need, free and short, which keeps it
  apart from the 78 used for missing assets.
- An unreadable meminfo passes with one recorded line instead of blocking: a
  machine that cannot read its own memory should not be left unable to start a
  model, and a real overshoot is still bounded by the swap ceiling.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-34
- Refuse a new inference instance that does not fit instead of letting the
  machine run past its physical memory. The memory and swap ceilings only
  decide which instance dies first; on 285H three instances still added up to
  29.5G on a 30G machine with 11G swapped, and two of fifteen coexistence
  rounds went over the soft budget with 463,721 pages written out in the same
  window while no direct-reclaim counter moved.
- airy-rt-cap admit compares the requested size with MemAvailable minus the
  reserve, where the reserve is the physical total minus the agent-side
  ceiling read from the same slice units memcap uses. A request that does not
  fit exits 3 and reports its shortfall; nothing already running is evicted.
  Missing --need exits 2, an unreadable meminfo reports unknown.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-33
- Stop reporting a never-provisioned data partition as a failure. mount.judge()
  folded "this system has no data partition at all" and "the data partition
  exists but its fstab row is gone" into one no-entry verdict. Only the second
  is a fault. 285H is an anaconda install from the 0.0.3 line: / plus /home,
  no /data row, no install-disk.json. Every boot therefore left a red
  airy-disk-mount, which dragged airymax-desktop-ready red with it and fired
  airy-incident@ noise over a machine that had nothing to fix.
- Split the verdict by the install-time disk record: the record is written by
  %pre and copied by %post --nochroot, both under set -eu, so its presence
  proves the system was provisioned with the 0.0.4 layout and the row must be
  there. Present and missing row stays no-entry (exit 3); absent gives the new
  unset verdict (exit 4), which the unit accepts via SuccessExitStatus=4 --
  the same stance airy-disk-health already takes with ConditionPathIsMountPoint.
- The gap stays visible instead of becoming a fault: mount unset prints that
  /data lands on the root filesystem, and airy-disk status still reports the
  install record as absent.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-32
- Gate the failure handler on the payload it drives. Every OnFailure= in
  this package points at airy-incident@, which execs /usr/sbin/airyctl as
  the airy account. Neither exists in a 0.0.4 image: airyctl and the
  account belong to the agentrt payload, which is not part of this
  package yet. 285H showed the consequence: a data-disk mount failure
  started the handler, the handler failed with 217/USER, and boot
  readiness then counted two failed units instead of one. The template
  now carries ConditionPathExists=/usr/sbin/airyctl, so an absent
  payload is a skip rather than a second failure; the original unit
  stays visible in systemctl --failed. The unit contract test rejects
  removal of the condition.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-31
- Cap an overcommitted slice instead of leaving it uncapped. The guard
  refused to write whenever current usage exceeded the target, which on
  285H is permanent: the declared ceiling is 32583151616 bytes while
  user.slice already carries 43597242368 bytes of memsw, fifteen of them
  swapped out. Swapped pages do not shrink under reclaim, so every round
  reported tight and the machine kept no ceiling at all exactly when it
  needed one, which is the state that ends in a whole-machine reclaim
  stall. apply now writes max(target, usage + 5% of the declared ceiling)
  and reports held. Three invariants keep a configuration step from
  becoming an incident: the written value is never below current usage,
  so no reclaim fires at apply time; the limit only tightens, never
  raises, so repeated rounds cannot grow the ceiling; and once usage
  falls below the target minus the headroom the next round writes the
  declared target, so held converges to applied. Inspect still reports
  tight because the limit is not at target, and both states exit 3 so no
  gate reads a partial landing as success.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-30
- Re-apply the swap ceiling on a timer. The write itself succeeds, but
  systemd on cgroup v1 does not manage memory.memsw.limit_in_bytes and
  rewrites it to infinity on every daemon-reload; systemctl enable runs
  a reload internally, so the boot write survived only until the next
  enable, install or update. 285H measured both sides: applying the
  ceiling then running daemon-reload put the file back to
  9223372036854771712, while rewriting memory.limit_in_bytes by hand
  left the ceiling untouched, which pins the reset on systemd rather
  than the kernel. airy-rt-memcap.timer now rewrites it every 60s and
  also retries the slices the boot run had to skip because their usage
  already exceeded the target, which is exactly the state a machine
  reaches under a long local-model task. The service drops
  RemainAfterExit so the timer has an inactive moment to schedule from.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-29
- Give the swap ceiling a unit of its own. It used to run from
  ExecStartPost of airy-rt-bandwidth.service, and ExecStartPost only runs
  when ExecStart succeeds: on 285H the bandwidth apply reported three of
  four slices and exited 3 because airymax-desktop.slice only exists once
  someone logs in, so the ceiling was skipped and memory.memsw
  .limit_in_bytes stayed at infinity while the unit merely said the
  budget was partially applied. The two are separate concerns with
  separate failure domains: the ceiling needs nothing but the slice
  directories, the budget needs the desktop slice. airy-rt-memcap.service
  now applies the ceiling on its own and is listed in boot-set, and both
  units declare SuccessExitStatus=3 because a partial result at boot is
  the normal outcome rather than a start failure -- the acceptance gate
  reads the exit code directly and never infers from unit state.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-28
- Enable the boot units on the upgrade path, not only in the image. 0.0.4
  added the RT bandwidth, power and thermal, desktop coexistence, data
  disk and update units, but all of them are pinned disabled by the
  presets and only the kickstart post script ever enabled them, so a
  machine that upgraded instead of being reinstalled ran the release
  with the swap ceiling unwritten and no thermal policy: on 285H
  memory.memsw.limit_in_bytes stayed at infinity, and no journal line
  existed for airy-rt-bandwidth.service since its install, although
  systemctl reported MemorySwapMax=10% all along. The list of units to
  enable is now one file, /usr/lib/airymaxos/boot-set, shipped here and
  read by both consumers: the kickstart for the image and %posttrans for
  a running system, which enables and starts each entry when systemd is
  up. Enablement is idempotent, a masked unit stays masked, --no-block
  keeps the transaction from waiting on a start, and a failure is left
  as a failed unit rather than rolled back so it can be attributed.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-27
- Stop shipping a second airy-observe. release 25 installed a /usr/bin
  airy-observe for the hardware survey while the release package already
  owns that name for the identity and section report, so installing system
  25 next to release 0.0.4-4 failed on a file conflict that no single
  package upgrade could resolve. The survey is a subcommand of the one
  command, not a second command: this package now installs only the
  airymax_observe module with a __main__ entry, and airy-observe hardware
  dispatches to it. The check runs python3 -m airymax_observe --help in
  the build root so the module entry is exercised before install.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-26
- Record whole-machine stalls from the one clock that keeps moving while
  everything is stopped: the periodic check expects to wake 60 seconds
  after the last pass but wakes 200 seconds after it, and the 110 seconds
  it overshot the 90 second budget by are a lower bound on the stall.
  CLOCK_BOOTTIME is used so a suspend counts the same as a freeze, the 30
  second slack covers the timer accuracy and the run itself, and the
  evidence lands in /run so a reboot clears it. Nothing is written to the
  machine in response: the stall is already over and any write at that
  moment is a second disturbance. This exists because the 285H stalls
  left no trace at all, not even a journal line, since every process able
  to write one was waiting too.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-25
- Ship airy-observe and the airymax_observe package so one command answers
  what the machine actually has. The survey reads sysfs only: a class with
  no node is absent, a device state is copied verbatim (online, operstate,
  temp, status), and an rfkill switch left off is blocked. cpu, block and
  net are mandatory, every other class is optional so ARM and RISC-V boards
  do not fail the gate for lacking a TPM. The first run on 285H found that
  x86 has no /sys/class/cpu, that DRM connectors sit next to the card node,
  and that two rfkill entries can share the same type, so the CPU class
  reads devices/system/cpu/cpu*, only cardN counts as a GPU, and the node
  name is kept apart from the device label.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-24
- Report the cooling devices instead of pretending to drive them. The four
  Fan objects on 285H are ACPI PNP0C0B devices whose firmware never
  implemented \_TZ.FNCL: a write of 1 to cur_state returns ENODEV, leaves
  an ACPI error in dmesg and makes the node unreadable afterwards, while
  the fans keep turning exactly as the EC wants. airy-power now lists every
  cooling device with its class, limit and current state, keeps unreadable
  ones visible, and never opens cur_state for writing; heat is shed through
  platform_profile, governor/EPP and idle depth, which are the interfaces
  the platform does implement. The name ordering helper also parses the
  trailing digits of a name rather than the tail after the last
  underscore, so thermal_zone2 precedes thermal_zone10.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-23
- Align the memory ceilings to the page size. A field apply on the target
  machine wrote 29324840140 to memory.limit_in_bytes and read back
  29324836864, because the kernel rounds the limit down to a page
  boundary; the executor took that for a failed write and reported
  absent while the ceiling was in place. The target is now floored at
  conversion, so the declaration, the written value and the read-back
  agree, and each half of the memsw sum is floored before they are added.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-22
- Enforce the memsw ceiling that systemd leaves unwritten. On the hybrid
  hierarchy a transient service reports MemorySwapMax=314572800 through
  systemctl show while memory.memsw.limit_in_bytes stays infinity, so the
  declarations from 0.0.4-21 bounded nothing on the swap side. The RT
  package now reads those same declarations, converts the percentages
  against MemTotal and writes the memsw limit directly, reading it back
  because cgroupfs clamps silently. airy-rt-bandwidth.service runs it as
  an ExecStartPost so both ceilings exist before a login session can
  allocate, and a target below the current charge is refused instead of
  being turned into an OOM event on a running model.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-21
- Bound the swap side of both memory ceilings. A hard MemoryMax alone does
  not reject the pages above it; they are swapped out, and on 285H the
  session scope was charged 13.8G of a 16G swap while the machine spent
  its time between eviction and refault. memsw accounting is available on
  the 6.6 target kernel (memory.memsw.limit_in_bytes is writable and the
  per-group swap counter is non-zero), so MemorySwapMax states the
  page-out ceiling: 10% on airymax-agent.slice and 15% in the session
  pool, putting memory plus swap at one physical memory and keeping the
  resident share at 90% and 85% respectively.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-20
- Bound the session pool with a user.slice drop-in: AirymaxRT execs its
  local model runtime from a login session, so the airymax-agent.slice
  ceiling never applied to the three instances that reached 29.5G of 30G
  physical memory. user.slice is the common parent of every session scope,
  so a hard 85% MemoryMax there covers any spawn path and keeps 15% for
  the kernel, system.slice and writeback. Only MemoryMax is declared, for
  the same cgroup v1 hybrid reason as the agent slice.
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-19
- Bound model and agent workloads in airymax-agent.slice: on 285H three
  inference instances reached 29.5G of 30G physical memory and pushed the
  whole machine into direct reclaim, stalling desktop and SSH. MemoryMax
  at 90% keeps one tenth of RAM for the kernel and the interactive path,
  so oversubscription fails the workload instead of the machine; the
  percentage scales with the host. MemoryHigh and MemorySwapMax are
  deliberately absent: the target image runs the hybrid cgroup v1
  hierarchy where systemd does not write soft limits and memsw accounting
  needs swapaccount=1, so those directives would only look enforced
* Tue Nov 03 2026 Liren Wang <wangliren@spharx.cn> - 0.0.4-18
- Fall back to per-core load average when PSI is unavailable: the 285H
  kernel has no PSI, so the coexistence policy sat at the baseline weight
  on the only machine we can validate. Use a separate threshold for the
  fallback because load average counts uninterruptible sleep, and report
  which signal produced the verdict
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
