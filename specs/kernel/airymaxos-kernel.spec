# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-kernel — AirymaxOS 内核配方
#
# 职责：
#   1. 以仓库内 kernel/ 工作树为唯一源码事实源，按 70-build-system/
#      02-kconfig-system.md §7.1 三步法生成 .config；
#   2. 产出可引导镜像、模块树、UAPI 头文件与外部模块开发树；
#   3. 在目标机安装期生成与内核版本严格对应的 initramfs。
#
# 源码包：airymaxos-kernel-<kernel_version>.tar.gz 由 scripts/build-kernel.sh
# 从 kernel/ 工作树确定性导出（git archive | gzip -n），不在仓库内落盘，
# 故以 spec-lint 生成式源码声明豁免存在性检查。
#
# 与 190-distribution/01-rpm-packaging.md 的口径差异（已在 M-25 注记登记）：
#   - 文档 §3.1 的 Source1/Source2、patches/、services/ 在 kernel/ 中不存在，
#     本配方只消费真实存在的工作树内容；
#   - 文档使用 6.6.0，实际内核 Makefile 为 6.6.157，以工作树为准；
#   - 文档 §1.4 的 debuginfo 包与 §3.1/§3.5 的包矩阵冲突，本配方按后者
#     产出 core/modules/headers/devel/tools，不拆 debuginfo；
#   - initramfs 是安装期产物，任何子包都不拥有它，只由 %%post 生成并校验。
#
# 内核身份声明（M-15）：
#   AirymaxOS 是单内核发行版，二进制包名带 airymaxos- 前缀；而 Anaconda 在
#   bootloader 阶段按 "kernel" 这一包身份挑选要写入引导项的内核，上层包也
#   常以 kernel-headers/kernel-devel 表达构建依赖。故主包声明上游内核身份
#   与 install-only 语义，core/modules 子包同构声明，使 dnf 在解析 "kernel"
#   依赖时命中本包并替换上游内核，避免同机出现两套内核树。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

%global airy_version 0.0.3
%global airy_release 1
%global kernel_version 6.6.157
%global kernel_local -agentrt
%global kernel_release %{kernel_version}%{kernel_local}
%global ksrc %{_builddir}/airymaxos-kernel-%{kernel_version}
%global debug_package %{nil}

%ifarch x86_64
%global karch x86
%global kdir x86
%global kimage bzImage
%endif

%ifarch aarch64
%global karch arm64
%global kdir arm64
%global kimage Image
%endif

%ifarch riscv64
%global karch riscv
%global kdir riscv
%global kimage Image
%endif

Name:           airymaxos-kernel
Version:        %{airy_version}
Release:        %{airy_release}%{?dist}
Summary:        AirymaxOS kernel with the airy security subsystem
License:        GPL-2.0-only OR AGPL-3.0-or-later
URL:            https://atomgit.com/openairymax/agent-linux
ExclusiveArch:  x86_64 aarch64 riscv64

# spec-lint: generated-source airymaxos-kernel-6.6.157.tar.gz
Source0:        airymaxos-kernel-%{kernel_version}.tar.gz

BuildRequires:  bc
BuildRequires:  bison
BuildRequires:  elfutils-libelf-devel
BuildRequires:  flex
BuildRequires:  gcc
BuildRequires:  libtraceevent-devel
BuildRequires:  make
BuildRequires:  openssl-devel
BuildRequires:  python3-devel
BuildRequires:  rsync
BuildRequires:  zlib-devel
Requires:       airymaxos-kernel-core = %{version}-%{release}
Requires:       airymaxos-kernel-modules = %{version}-%{release}
Provides:       kernel = %{kernel_version}
Provides:       installonlypkg(kernel)
Obsoletes:      kernel

%description
AirymaxOS kernel package. It carries the upstream 6.6 longterm tree plus the
airy security subsystem, and it is the only kernel that AirymaxOS images
install.

%package core
Summary:        AirymaxOS kernel image
Requires(post): dracut
Provides:       kernel-core = %{kernel_version}
Provides:       kernel-uname-r = %{kernel_release}
Obsoletes:      kernel-core

%description core
Bootable kernel image for AirymaxOS. Installation generates the matching
initramfs and registers the image with kernel-install when available.

%package modules
Summary:        AirymaxOS kernel modules
Requires(post): kmod
Provides:       kernel-modules = %{kernel_version}
Obsoletes:      kernel-modules

%description modules
Loadable modules matching the AirymaxOS kernel image.

%package headers
Summary:        AirymaxOS kernel UAPI headers

%description headers
User space API headers exported by the AirymaxOS kernel.

%package devel
Summary:        AirymaxOS kernel development tree
Requires:       airymaxos-kernel-headers = %{version}-%{release}

%description devel
Headers, scripts and symbol maps needed to build external kernel modules
against the AirymaxOS kernel.

%package tools
Summary:        AirymaxOS kernel performance and BPF tools

%description tools
Perf and bpftool built from the AirymaxOS kernel tree.

%prep
%setup -q -n airymaxos-kernel-%{kernel_version}
cp arch/%{kdir}/configs/airy_defconfig airymax-local.fragment
printf 'CONFIG_LOCALVERSION="%{kernel_local}"\n' >> airymax-local.fragment

%build
cd %{ksrc}
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1468923400}"
export SOURCE_DATE_EPOCH
export KBUILD_BUILD_USER=airymax
export KBUILD_BUILD_HOST=build
export KBUILD_BUILD_TIMESTAMP
KBUILD_BUILD_TIMESTAMP="$(date -u -d "@${SOURCE_DATE_EPOCH}" \
    '+%%Y-%%m-%%d %%H:%%M:%%S')"
export KCFLAGS="-ffile-prefix-map=%{ksrc}=."

make ARCH=%{karch} defconfig
sh scripts/kconfig/merge_config.sh -m .config airymax-local.fragment
make ARCH=%{karch} olddefconfig
make ARCH=%{karch} %{?_smp_mflags} %{kimage} modules
make -C tools/perf %{?_smp_mflags}
make -C tools/bpf/bpftool %{?_smp_mflags}

%install
install -d -m 0755 %{buildroot}/boot
install -m 0755 %{ksrc}/arch/%{kdir}/boot/%{kimage} \
    %{buildroot}/boot/vmlinuz-%{kernel_release}

make -C %{ksrc} ARCH=%{karch} INSTALL_MOD_PATH=%{buildroot}/usr \
    INSTALL_MOD_STRIP=1 modules_install
rm -f %{buildroot}/usr/lib/modules/%{kernel_release}/build \
      %{buildroot}/usr/lib/modules/%{kernel_release}/source

make -C %{ksrc} ARCH=%{karch} INSTALL_HDR_PATH=%{buildroot}/usr \
    headers_install
rm -f %{buildroot}/usr/.install

ksrc_devel=%{buildroot}/usr/src/kernels/%{kernel_release}
install -d -m 0755 "$ksrc_devel"
for file in Makefile .config System.map Module.symvers; do
    install -m 0644 "%{ksrc}/${file}" "$ksrc_devel/${file}"
done
cp -a %{ksrc}/include "$ksrc_devel/include"
cp -a %{ksrc}/scripts "$ksrc_devel/scripts"
install -d -m 0755 "$ksrc_devel/arch/%{kdir}"
cp -a %{ksrc}/arch/%{kdir}/include "$ksrc_devel/arch/%{kdir}/include"
install -m 0644 %{ksrc}/arch/%{kdir}/Makefile \
    "$ksrc_devel/arch/%{kdir}/Makefile"
for tool in tools/objtool/objtool tools/bpf/resolve_btfids/resolve_btfids; do
    if [ -x "%{ksrc}/${tool}" ]; then
        install -D -m 0755 "%{ksrc}/${tool}" "$ksrc_devel/${tool}"
    fi
done
find "$ksrc_devel" -type f \( -name '*.o' -o -name '*.o.*' \
    -o -name '*.ko' -o -name '*.cmd' -o -name '*.a' -o -name '*.mod' \
    -o -name '*.mod.*' \) -delete

install -d -m 0755 %{buildroot}%{_bindir}
install -m 0755 %{ksrc}/tools/perf/perf \
    %{buildroot}%{_bindir}/airymax-perf
install -m 0755 %{ksrc}/tools/bpf/bpftool/bpftool \
    %{buildroot}%{_bindir}/airymax-bpftool

ln -sfn /usr/src/kernels/%{kernel_release} \
    %{buildroot}/usr/lib/modules/%{kernel_release}/build
ln -sfn /usr/src/kernels/%{kernel_release} \
    %{buildroot}/usr/lib/modules/%{kernel_release}/source

%check
grep -qx 'CONFIG_SECURITY=y' %{ksrc}/.config
grep -qx 'CONFIG_SECURITY_AIRY=y' %{ksrc}/.config
grep -qx 'CONFIG_AIRY_SYSCALL=y' %{ksrc}/.config
grep -qx 'CONFIG_AIRY_COREKERN=y' %{ksrc}/.config
grep -qx 'CONFIG_AIRY_LOG=y' %{ksrc}/.config
grep -qx 'CONFIG_AIRY_IPC=y' %{ksrc}/.config
grep -qx 'CONFIG_AIRY_AGENT_TRACING=y' %{ksrc}/.config
grep -qx 'CONFIG_AIRY_CAP_TABLE_SIZE=1024' %{ksrc}/.config
grep -qx 'CONFIG_IO_URING=y' %{ksrc}/.config
grep -qx 'CONFIG_LOCALVERSION="%{kernel_local}"' %{ksrc}/.config
test -s %{buildroot}/boot/vmlinuz-%{kernel_release}
test -s %{ksrc}/System.map
readelf -h %{ksrc}/vmlinux >/dev/null
test -s %{ksrc}/tools/perf/perf
test -s %{ksrc}/tools/bpf/bpftool/bpftool

%post core
if command -v kernel-install >/dev/null 2>&1; then
    kernel-install add %{kernel_release} /boot/vmlinuz-%{kernel_release} || :
fi
if [ ! -s /boot/initramfs-%{kernel_release}.img ]; then
    dracut --force /boot/initramfs-%{kernel_release}.img %{kernel_release}
fi
if [ ! -s /boot/initramfs-%{kernel_release}.img ]; then
    echo "airymaxos-kernel: initramfs generation failed" >&2
    exit 1
fi

%preun core
if [ "$1" -eq 0 ]; then
    if command -v kernel-install >/dev/null 2>&1; then
        kernel-install remove %{kernel_release} || :
    fi
    rm -f /boot/initramfs-%{kernel_release}.img
fi

%post modules
depmod -a %{kernel_release}

%files
%license COPYING

%files core
/boot/vmlinuz-%{kernel_release}

%files modules
%exclude /usr/lib/modules/%{kernel_release}/build
%exclude /usr/lib/modules/%{kernel_release}/source
/usr/lib/modules/%{kernel_release}/

%files headers
%{_includedir}/*

%files devel
/usr/src/kernels/%{kernel_release}/
/usr/lib/modules/%{kernel_release}/build
/usr/lib/modules/%{kernel_release}/source

%files tools
%{_bindir}/airymax-perf
%{_bindir}/airymax-bpftool

%changelog
* Sat Oct 17 2026 SPHARX <dev@spharx.com> - 0.0.3-1
- Initial kernel package for AirymaxOS 0.0.3
