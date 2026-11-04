# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-firmware — 与内核 ABI 同源的固件闭包（FW-02）
#
# 为什么要有这个包：0.0.3 的固件直接由基底仓库的 linux-firmware 提供，内核
# 与固件之间的对应关系没有任何一处声明。于是「内核不动、固件滚版本」这类
# 漂移只能靠人记得同时看两端；BE200 缺 gl-c0-fm-c0、regulatory.db 未装，
# 都是装机后读 dmesg 才暴露。
#
# 本包把这条关系写成 rpm 依赖，使求解只有两种结果：
#   · 固件与内核 ABI 对齐，并被依赖闭包点名带进事务；
#   · 构建期就失败。
# 不存在「内核在、固件半套」的中间态——这正是 FW-02 要拦的形态。闭包求解
# 另在 distro/scripts/lib/closure.sh 的 cl_scope（作用域白名单）里逐包点名，
# 配方排除项与播种跳过项都裁不掉它。
#
# 三件事各有唯一事实源，互不手抄：
#   ① ABI：内核配方 %%(kernel_version)，本文件 %%(kernel_abi) 与之逐字一致，
#      由 distro/tools/tests/test_fw_contract.py 断言，漂移即红；
#   ② 提供包：distro/firmware/fw-manifest.txt 第一列。本文件 Requires 逐条
#      对应，同一测试按集合对账，清单加一行而不加 Requires 同样判红；
#   ③ 清单本体：随包落盘 /usr/share/airymaxos/firmware/fw-manifest.txt，装机
#      后 `ci/gates/fw-closure.sh --root /` 与出厂前用同一份数据，这是验收
#      里「清单随 ISO 发布并能回读」的那一半。
#
# 本包不含固件文件本体：固件仍由基底仓库的包提供，重复打包会让同一路径被
# 两个包持有，dnf 事务直接失败。本包只承载「哪个 ABI、哪些固件提供包」。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

%global airy_version 0.0.4
%global airy_release 1
# 内核 ABI。抬基线时只改这里与内核配方的 %%(kernel_version) 两处，同源断言
# 保证两者不会各自漂移（tools/tests/test_fw_contract.py 的 abi 用例）。
%global kernel_abi 6.6.161

Name:           airymaxos-firmware
Version:        %{airy_version}
Release:        %{airy_release}%{?dist}
Summary:        Firmware closure bound to the AirymaxOS kernel ABI
License:        AGPL-3.0-or-later
URL:            https://atomgit.com/openairymax/agent-linux
Source0:        fw-manifest.txt
BuildArch:      noarch
# 清单第一列的包逐条显式声明；集合对账在构建前的 spec 门禁里做，而不是在
# 解析期读文件——解析期读源文件会让 spec-lint 与 rpmlint 在缺 _sourcedir
# 的机器上无法解析，判定面反而缩小。
Requires:       linux-firmware
Requires:       wireless-regdb
# 内核按 ABI 点名本包；Provides 用同一宏展开，两边天然对齐。
Provides:       airymaxos-firmware-%{kernel_abi} = %{version}-%{release}

%description
Firmware closure of the AirymaxOS kernel ABI. It carries the firmware
manifest that the closure gate reads, and it binds the firmware provider
packages to one kernel ABI so that the two cannot drift apart silently.

%prep
%setup -q -c -T

%build

%install
install -d -m 0755 %{buildroot}%{_datadir}/airymaxos/firmware
install -m 0644 %{SOURCE0} \
    %{buildroot}%{_datadir}/airymaxos/firmware/fw-manifest.txt
# ABI 标记与 Provides 同源：装机后不必解包 rpm 就能读出「这台机器的固件
# 闭包对应哪个内核」。fw-closure.sh --root 用它核对镜像与清单是否同代。
printf '%s\n' '%{kernel_abi}' \
    > %{buildroot}%{_datadir}/airymaxos/firmware/kernel-abi
chmod 0644 %{buildroot}%{_datadir}/airymaxos/firmware/kernel-abi

%check
# 清单是判定面唯一的输入，格式错会让门禁静默少判，故在这里逐行验形：
# 三段式、类别只允许小写与连字符、路径必须落在 /usr/lib/firmware 下。
manifest=%{buildroot}%{_datadir}/airymaxos/firmware/fw-manifest.txt
test -s "${manifest}"
rows=0
while IFS= read -r line; do
    case "${line}" in
    ''|'#'*) continue ;;
    esac
    set -- ${line}
    [ "$#" -eq 3 ] || {
        echo "清单行不是三段式: ${line}" >&2
        exit 1
    }
    case "$2" in
    *[!a-z0-9-]*|'')
        echo "器件类别非法: ${line}" >&2
        exit 1
        ;;
    esac
    case "$3" in
    /usr/lib/firmware/*) ;;
    *)
        echo "固件路径不在 /usr/lib/firmware 下: ${line}" >&2
        exit 1
        ;;
    esac
    rows=$(( rows + 1 ))
done <"${manifest}"
[ "${rows}" -gt 0 ] || {
    echo "清单没有任何数据行" >&2
    exit 1
}
# ABI 标记与 Provides 必须逐字一致，否则内核点名的名字与包提供的名字分叉。
test "$(cat %{buildroot}%{_datadir}/airymaxos/firmware/kernel-abi)" = \
    '%{kernel_abi}'

%files
%defattr(-, root, root, -)
%dir %{_datadir}/airymaxos/firmware
%{_datadir}/airymaxos/firmware/fw-manifest.txt
%{_datadir}/airymaxos/firmware/kernel-abi

%changelog
* Wed Nov 04 2026 SPHARX <dev@spharx.com> - 0.0.4-1
- Ship the firmware closure of the kernel ABI: the package Provides
  airymaxos-firmware-<abi> and the kernel Requires that name, so a
  firmware set can no longer be half-installed next to a kernel
- Carry fw-manifest.txt inside the image so the closure gate can read
  the same manifest after install instead of only before release
