# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# airymaxos-kernel — AirymaxOS 内核配方
#
# 职责：
#   1. 以仓库内 kernel/ 工作树为唯一源码事实源，按 70-build-system/
#      02-kconfig-system.md §7.1 的基线 + 片段合并方式生成 .config；
#   2. 产出可引导镜像、模块树、UAPI 头文件与外部模块开发树；
#   3. 在目标机安装期生成与内核版本严格对应的 initramfs。
#
# 配置基线（0.0.3-2 起）：
#   x86/arm64 取 openeuler_defconfig。此前用 defconfig（x86 即精简的
#   x86_64_defconfig），其中没有 NVMe/IGC，B50 这类 NVMe-only 机器装完
#   无法挂载根分区。openeuler_defconfig 是唯一在这两个架构上同时覆盖
#   NVMe、RTL8852BE（rtw89）与服务器网卡的完整基线。riscv64/loongarch64
#   无该文件，仍取各自架构自带基线。
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
# 引导镜像选择：
#   Kbuild 的可引导镜像随配置变化（arm64/riscv 可能是 Image.gz 或
#   vmlinuz.efi，loongarch 可能是 vmlinux.efi 或 vmlinuz.efi），硬编码单一
#   路径必然与配置漂移。本配方统一以 make -s image_name 取当前配置的可引导
#   镜像，安装为 /boot/vmlinuz-<release>。
#
# 交叉构建：
#   调用方以 --define "cross_prefix <前缀>" 传入交叉工具链前缀，配方在各
#   make 调用点条件展开为 CROSS_COMPILE；未定义该宏即原生构建。
#
# 交叉构建的发布边界：
#   Kbuild 的 hostprogs（scripts/ 下的 modpost、unifdef、asn1_compiler 等，
#   以及 objtool、resolve_btfids）由构建机的 HOSTCC 编译，架构与目标包不同。
#   它们装入 devel 树后既无法在目标机执行（Exec format error），又会让
#   brp-strip 以目标 binutils 解析失败。故交叉构建只发布与目标架构一致的
#   内容，这些可执行文件不装入；目标机执行 make modules_prepare 时从随包的
#   scripts/ 源码重建。原生构建不受影响，仍按惯例发布预编译工具。
#
# 工具子包：
#   perf 与 bpftool 需要目标架构的 sysroot，只有在目标架构与构建机一致时
#   才产出 airymaxos-kernel-tools；交叉构建跳过该子包，不产出空壳。
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
%global airy_release 2
%global kernel_version 6.6.157
%global kernel_local -alk
%global kernel_release %{kernel_version}%{kernel_local}
%global ksrc %{_builddir}/airymaxos-kernel-%{kernel_version}
%global debug_package %{nil}
%global native %(test "%{_target_cpu}" = "$(uname -m)" && echo 1 || echo 0)

%ifarch x86_64
%global karch x86
%global kdir x86
%global kbase openeuler_defconfig
%endif

%ifarch aarch64
%global karch arm64
%global kdir arm64
%global kbase openeuler_defconfig
%endif

%ifarch riscv64
%global karch riscv
%global kdir riscv
%global kbase defconfig
%endif

# loongarch 上游不提供 arch/loongarch/configs/defconfig，`make defconfig`
# 在该架构上必然失败，取唯一可用的通用基线 loongson3_defconfig。
%ifarch loongarch64
%global karch loongarch
%global kdir loongarch
%global kbase loongson3_defconfig
%endif

# 所有内核 make 调用统一走 kmake：架构与交叉前缀只在此处定义一次。
%global kenv ARCH=%{karch} %{?cross_prefix:CROSS_COMPILE=%{cross_prefix}}
%global kmake make -C %{ksrc} %{kenv}

# rpm 在 %%install 之后以 brp-strip 统一去符号，其可执行文件取自 __strip 与
# __objdump。交叉构建时这两项必须换成目标架构 binutils，否则主机的
# /usr/bin/strip 无法解析交叉产物，brp-strip 以非零退出中断打包。原生
# 构建不定义 cross_prefix，故保持 rpm 缺省值不变。
%if %{?cross_prefix:1}%{!?cross_prefix:0}
%global __strip %{cross_prefix}strip
%global __objdump %{cross_prefix}objdump
%endif

Name:           airymaxos-kernel
Version:        %{airy_version}
Release:        %{airy_release}%{?dist}
Summary:        AirymaxOS kernel with the airy security subsystem
License:        GPL-2.0-only OR AGPL-3.0-or-later
URL:            https://atomgit.com/openairymax/agent-linux
ExclusiveArch:  x86_64 aarch64 riscv64 loongarch64

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
# tools 子包只在本机架构构建：bpftool 的 skeleton 通过 clang 编译并以
# llvm-strip 瘦身，perf 依赖 libcap/libnuma/sdt/libdw。交叉构建不产出
# tools，故这些依赖随之只在原生构建时声明。
%if %{native}
BuildRequires:  clang
BuildRequires:  elfutils-devel
BuildRequires:  libcap-devel
BuildRequires:  llvm
BuildRequires:  numactl-devel
BuildRequires:  systemtap-sdt-devel
%endif
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

%if %{native}
%package tools
Summary:        AirymaxOS kernel performance and BPF tools

%description tools
Perf and bpftool built from the AirymaxOS kernel tree.
%endif

%prep
%setup -q -n airymaxos-kernel-%{kernel_version}
cp configs/defconfig-agent airymax-agent.fragment
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

%{kmake} %{kbase}
sh scripts/kconfig/merge_config.sh -m .config airymax-agent.fragment
sh scripts/kconfig/merge_config.sh -m .config airymax-local.fragment
%{kmake} olddefconfig
%{kmake} %{?_smp_mflags} all modules
%if %{native}
make -C tools/perf %{?_smp_mflags}
make -C tools/bpf/bpftool %{?_smp_mflags}
%endif

%install
img="$(%{kmake} -s image_name)"
install -d -m 0755 %{buildroot}/boot
install -m 0755 "%{ksrc}/${img}" %{buildroot}/boot/vmlinuz-%{kernel_release}

%{kmake} INSTALL_MOD_PATH=%{buildroot}/usr INSTALL_MOD_STRIP=1 \
    modules_install
rm -f %{buildroot}/usr/lib/modules/%{kernel_release}/build \
      %{buildroot}/usr/lib/modules/%{kernel_release}/source

%{kmake} INSTALL_HDR_PATH=%{buildroot}/usr headers_install
rm -f %{buildroot}/usr/.install

ksrc_devel=%{buildroot}/usr/src/kernels/%{kernel_release}
install -d -m 0755 "$ksrc_devel"
for file in Makefile .config System.map Module.symvers; do
    install -m 0644 "%{ksrc}/${file}" "$ksrc_devel/${file}"
done
cp -a %{ksrc}/include "$ksrc_devel/include"
cp -a %{ksrc}/scripts "$ksrc_devel/scripts"
%if !%{native}
# 构建机 ELF 不随交叉包发布：目标机无法执行，且会让 brp-strip 失败。
find "$ksrc_devel/scripts" -type f -perm -u+x |
while IFS= read -r prog; do
    if [ "$(od -An -tx1 -N4 "$prog" | tr -d ' \n')" = 7f454c46 ]; then
        rm -f "$prog"
    fi
done
%endif
install -d -m 0755 "$ksrc_devel/arch/%{kdir}"
cp -a %{ksrc}/arch/%{kdir}/include "$ksrc_devel/arch/%{kdir}/include"
install -m 0644 %{ksrc}/arch/%{kdir}/Makefile \
    "$ksrc_devel/arch/%{kdir}/Makefile"
%if %{native}
for tool in tools/objtool/objtool tools/bpf/resolve_btfids/resolve_btfids; do
    if [ -x "%{ksrc}/${tool}" ]; then
        install -D -m 0755 "%{ksrc}/${tool}" "$ksrc_devel/${tool}"
    fi
done
%endif
find "$ksrc_devel" -type f \( -name '*.o' -o -name '*.o.*' \
    -o -name '*.ko' -o -name '*.cmd' -o -name '*.a' -o -name '*.mod' \
    -o -name '*.mod.*' \) -delete

%if %{native}
install -d -m 0755 %{buildroot}%{_bindir}
install -m 0755 %{ksrc}/tools/perf/perf \
    %{buildroot}%{_bindir}/airymax-perf
install -m 0755 %{ksrc}/tools/bpf/bpftool/bpftool \
    %{buildroot}%{_bindir}/airymax-bpftool
%endif

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
grep -qx 'CONFIG_USER_NS=y' %{ksrc}/.config
grep -qx 'CONFIG_LOCALVERSION="%{kernel_local}"' %{ksrc}/.config
# 引导期驱动门禁（OP-P0-01）：B50 为 NVMe-only 存储，缺 NVMe 时装载后的
# 系统无法挂载根分区；I226-V 有线走 igc，RTL8852BE 无线走 rtw89_8852be。
# 基线回退（如误改回 defconfig）必须在此处中断打包，而不是留到装机现场。
%ifarch x86_64
grep -qE '^CONFIG_BLK_DEV_NVME=[ym]$' %{ksrc}/.config
grep -qE '^CONFIG_IGC=[ym]$' %{ksrc}/.config
grep -qE '^CONFIG_RTW89_8852BE=[ym]$' %{ksrc}/.config
# 显示通路门禁（真机缺陷 D-06/D-08）：没有 i915/xe 时，simpledrm 是唯一
# 能提供 /dev/dri 的驱动，merge_config 若因依赖不满足把这两项丢掉，
# 装机后桌面会退到 efifb 且无法再被发现。
grep -qx 'CONFIG_SYSFB_SIMPLEFB=y' %{ksrc}/.config
grep -qx 'CONFIG_DRM_SIMPLEDRM=y' %{ksrc}/.config
%endif
test -s %{buildroot}/boot/vmlinuz-%{kernel_release}
test -s %{ksrc}/System.map
readelf -h %{ksrc}/vmlinux >/dev/null
%if %{native}
test -s %{ksrc}/tools/perf/perf
test -s %{ksrc}/tools/bpf/bpftool/bpftool
%endif

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

%if %{native}
%files tools
%{_bindir}/airymax-perf
%{_bindir}/airymax-bpftool
%endif

%changelog
* Sat Oct 24 2026 SPHARX <dev@spharx.com> - 0.0.3-2
- x86/arm64 内核基线由 defconfig 改为 openeuler_defconfig，恢复 NVMe、
  igc、rtw89 支持；NVMe 内建于 vmlinuz，并在 %%check 中加驱动门禁
* Sat Oct 17 2026 SPHARX <dev@spharx.com> - 0.0.3-1
- Initial kernel package for AirymaxOS 0.0.3
