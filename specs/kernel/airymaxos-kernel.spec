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
#   - 文档使用 6.6.0，实际内核 Makefile 的稳定版更高，以工作树为准；
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
#   与 install-only 语义，core/modules/headers 三个子包同构声明 kernel-core
#   /kernel-modules/kernel-headers 身份，使 dnf 在解析这些依赖时命中本包并
#   替换上游对应包，避免同机出现两套内核树或两套 UAPI 头（后者会直接造成
#   /usr/include 文件冲突，使装机事务失败）。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

%global airy_version 0.0.4
%global airy_release 5
%global kernel_version 6.6.161
%global kernel_local -alk
%global kernel_release %{kernel_version}%{kernel_local}
# 固件闭包的 ABI 名。派生自 %%(kernel_version)，与 airymaxos-firmware 的
# %%(kernel_abi) 逐字一致，由 tools/tests/test_fw_contract.py 断言。
%global kernel_abi %{kernel_version}
%global ksrc %{_builddir}/airymaxos-kernel-%{kernel_version}
%global debug_package %{nil}

# rpm 在 %%install 收尾执行 __spec_install_post，其中的 brp-strip 按
# `file` 报出的「ELF ... not stripped」选件，内核模块同样命中：strip -g
# 重写 ELF 时把追加在文件尾的 PKCS#7、12 字节 module_signature 与魔数
# 一并丢弃。签名在 %%install 里由 Makefile.modinst 的 sign 步骤正确写入，
# 随即被这一步删掉，%%check 只看到「全部模块无签名尾部」——症状在
# %%check，根因在打包后处理，补签只会被同一步再删一次（0.0.3-7 的补签
# 分支因此无效）。内核自带 scripts/package/kernel.spec 同样覆盖该宏，
# 只保留 brp-compress。此处取 %%nil 一并跳过去符号与字节码编译：本包无
# .py/.a/man，模块在 modules_install 已按 INSTALL_MOD_STRIP=1 去过调试
# 信息，perf 与 bpftool 在 %%install 内显式 strip。
%global __spec_install_post %{nil}
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

# 打包后处理已整体关掉（见文件头 __spec_install_post），brp-strip 不再运行；
# __strip 的唯一消费者是 %%install 末尾对 airymax-perf 与 airymax-bpftool 的
# 显式去符号。工具变量仍随交叉前缀切换，使两种构建取同一个变量名而不是
# 各自写死 /usr/bin/strip。
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

# spec-lint: generated-source airymaxos-kernel-%{kernel_version}.tar.gz
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
# 固件闭包与内核 ABI 同源（FW-02）。此前固件只由基底仓库的 linux-firmware
# 提供，内核与固件的对应关系没有一处声明，固件滚动后谁都不红：BE200 缺
# gl-c0-fm-c0、regulatory.db 未装都到装机后读 dmesg 才发现。库内包
# airymaxos-firmware 提供这个名字，它同时 Requires 清单里的固件提供包，
# 于是“内核在、固件半套”在事务阶段就不成立。
Requires:       airymaxos-firmware-%{kernel_abi}
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
# 内核身份声明（M-15）的 headers 腿：glibc-devel 等上层包以
# "kernel-headers" 表达构建依赖，若本包不声明该身份，dnf 会把上游
# kernel-headers 一并纳入事务，两份 /usr/include/linux/* 直接文件冲突，
# anaconda 在事务阶段转入交互问句直至超时。声明身份并 Obsoletes 上游
# 包，与 core/modules 的做法保持一致，保证同机只有一套 UAPI 头。
Provides:       kernel-headers = %{kernel_version}
Obsoletes:      kernel-headers

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
# 内核身份三件套（D-12）：/boot 只有 vmlinuz 时，目标机上核对「跑的是不是
# 这个内核、配置是否与包一致」只剩 /proc/config.gz 一条路，缺符号表也没有
# crash/kdump 与 ftrace 的现场取证依据。发行版惯例是同名的 config-<release>
# 与 System.map-<release>，随 core 子包发布。
install -m 0644 %{ksrc}/.config \
    %{buildroot}/boot/config-%{kernel_release}
install -m 0644 %{ksrc}/System.map \
    %{buildroot}/boot/System.map-%{kernel_release}

%{kmake} INSTALL_MOD_PATH=%{buildroot}/usr INSTALL_MOD_STRIP=1 \
    modules_install
# 此处不再补签。scripts/Makefile.modinst 在 CONFIG_MODULE_SIG_ALL=y 时已按
# install → strip → sign 的顺序调用 scripts/sign-file，签名随模块一同装入；
# 0.0.3-7 的补签分支依据 readelf -S 找 .module_sig 段，而真实签名是追加在
# 文件尾部的 PKCS#7 + module_signature + 魔数，该判据恒为假，补签反而会在已
# 签模块上再叠一份 PKCS#7。签名是否齐全由 %%check 按尾部结构判定。
# 曾被误判为「未签名」的第二个原因在打包后处理：brp-strip 会把这里的签名
# 整段剥掉，已在文件头以 __spec_install_post 关掉，补签在此处写什么都没有
# 意义——它同样逃不过那一步。
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
# 构建机 ELF 不随交叉包发布：目标机无法执行，单个工具就是数兆的载荷。
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
# 打包后处理已被关掉（见文件头 __spec_install_post 的说明），这两个二进制
# 的调试信息改为在此处去除：它们进 ISO 载荷，未去符号时单个 perf 就多出
# 数十兆。
%{__strip} -g %{buildroot}%{_bindir}/airymax-perf \
    %{buildroot}%{_bindir}/airymax-bpftool
%endif

ln -sfn /usr/src/kernels/%{kernel_release} \
    %{buildroot}/usr/lib/modules/%{kernel_release}/build
ln -sfn /usr/src/kernels/%{kernel_release} \
    %{buildroot}/usr/lib/modules/%{kernel_release}/source

%check
# 断言必须自带失败原因：grep/test 的静默失败在 CI 只呈现为一行
# "Bad exit status (%check)"，配合 log_tail 的截尾窗口，定位只能靠重跑。
# 两个辅助函数成功时零输出，失败时把判据写到 stderr 再退出，
# 不依赖 rpm 给 scriptlet 传的 -e。
assert_cfg()
{
    if ! grep -qxE "$1" %{ksrc}/.config; then
        printf 'check: config assertion failed: %s\n' "$1" >&2
        exit 1
    fi
}

assert_file()
{
    if [ ! -s "$1" ]; then
        printf 'check: missing or empty: %s\n' "$1" >&2
        exit 1
    fi
}

assert_cfg 'CONFIG_SECURITY=y'
assert_cfg 'CONFIG_SECURITY_AIRY=y'
assert_cfg 'CONFIG_AIRY_SYSCALL=y'
assert_cfg 'CONFIG_AIRY_COREKERN=y'
assert_cfg 'CONFIG_AIRY_LOG=y'
assert_cfg 'CONFIG_AIRY_IPC=y'
assert_cfg 'CONFIG_AIRY_AGENT_TRACING=y'
assert_cfg 'CONFIG_AIRY_CAP_TABLE_SIZE=1024'
assert_cfg 'CONFIG_IO_URING=y'
assert_cfg 'CONFIG_USER_NS=y'
assert_cfg 'CONFIG_LOCALVERSION="%{kernel_local}"'
# 非特权 BPF 门禁（T23）：x86 的 spectre_v2_select_mitigation() 在 eIBRS
# 生效且 unprivileged_ebpf_enabled() 为真时打印一条 Spectre V2 告警。该行
# 在 0.06 s 由内核自己发出，早于任何 sysctl.d，运行期写 sysctl 消除不掉；
# 只能由编译期默认值决定（=y 使初值为 2，永久关闭）。非特权 BPF 本身就是
# 可利用的攻击面，关闭是加固而不是掩盖。基线若把这一项改回 not set，必须
# 在此处中断打包，而不是留到装机后的启动日志里。
assert_cfg 'CONFIG_BPF_UNPRIV_DEFAULT_OFF=y'
# 实时带宽门禁（T23）：RT_GROUP_SCHED=y 时 systemd 把叶子单元的
# cpu.rt_runtime_us 置 0，rtkit-daemon 连自己的 canary/watchdog 线程都提不到
# SCHED_RR，每次开机刷二十余条 err 日志，桌面音频也拿不到实时优先级。
# 该项回退必须在打包阶段中断，而不是留到装机后的启动日志里。
assert_cfg '# CONFIG_RT_GROUP_SCHED is not set'
# 完整性内建密钥门禁（T23）：产品不发布 /etc/keys/x509_ima.der 与
# x509_evm.der，打开 LOAD_X509 只会让内核在 ima_init()/evm_init() 各打印
# 一条 "integrity: Unable to open file"。密钥链到位前这两项必须关闭。
assert_cfg '# CONFIG_IMA_LOAD_X509 is not set'
assert_cfg '# CONFIG_EVM_LOAD_X509 is not set'
# 引导期驱动门禁（OP-P0-01）：B50 为 NVMe-only 存储，缺 NVMe 时装载后的
# 系统无法挂载根分区；I226-V 有线走 igc，RTL8852BE 无线走 rtw89_8852be。
# 基线回退（如误改回 defconfig）必须在此处中断打包，而不是留到装机现场。
%ifarch x86_64
assert_cfg '^CONFIG_BLK_DEV_NVME=[ym]$'
assert_cfg '^CONFIG_IGC=[ym]$'
assert_cfg '^CONFIG_RTW89_8852BE=[ym]$'
# 显示通路门禁（真机缺陷 D-06/D-08）：没有 i915/xe 时，simpledrm 是唯一
# 能提供 /dev/dri 的驱动，merge_config 若因依赖不满足把这两项丢掉，
# 装机后桌面会退到 efifb 且无法再被发现。
# CONFIG_DRM 也要守：DRM_SIMPLEDRM 是 tristate 且 depends on DRM，base
# defconfig 里 DRM=m 时 =y 会被静默压成 =m，simpledrm 又因缺 modalias
# 无法被 udev 加载，等于整条显示通路失效。
assert_cfg 'CONFIG_DRM=y'
assert_cfg 'CONFIG_SYSFB_SIMPLEFB=y'
assert_cfg 'CONFIG_DRM_SIMPLEDRM=y'
%endif
assert_file %{buildroot}/boot/vmlinuz-%{kernel_release}
assert_file %{buildroot}/boot/config-%{kernel_release}
assert_file %{buildroot}/boot/System.map-%{kernel_release}
assert_file %{ksrc}/System.map
if ! readelf -h %{ksrc}/vmlinux >/dev/null 2>&1; then
    printf 'check: unreadable ELF: %s\n' %{ksrc}/vmlinux >&2
    exit 1
fi
# 模块签名门禁：签名不是 ELF 段。scripts/sign-file 把 PKCS#7、12 字节
# module_signature 与魔数 "~Module signature appended~\n" 依次追加在 .ko
# 尾部，kernel/module/signing.c 的 module_sig_check() 按同一顺序读取；以
# readelf -S 找 .module_sig 段的判据对真实模块恒为假，缺一个就中断打包。
# 签名缺失只在装机后以 taint 8192 显形，打开 SIG_FORCE 后则表现为全部模块
# 拒载。结构自洽与运行期污染位由 ci/gates/module-signature.sh 在镜像树上
# 复核，两处判据同源。
if grep -qx 'CONFIG_MODULE_SIG_ALL=y' %{ksrc}/.config; then
    unsigned=0
    total=0
    # 按行读取而非 -print0 + read -d ''，也不用进程替换：scriptlet 由
    # /bin/sh 执行（rpm 默认，构建机上即 dash），这些是 bash 扩展，
    # dash 直接语法错误。kbuild 生成的模块路径只含 [A-Za-z0-9_./+-]，
    # 无换行，按行不丢不重；find 先写临时文件，循环重定向进当前 shell，
    # 计数器在循环之后仍然可用（管道会把计数器丢在子 shell 里）。
    kolist="$(mktemp)"
    find %{buildroot}/usr/lib/modules/%{kernel_release} \
        -name '*.ko' > "${kolist}"
    while IFS= read -r ko; do
        total=$((total + 1))
        # tr 先去掉二进制字节里的 NUL 再进命令替换：未签名的模块尾部是
        # 任意字节，直接替换会让 bash 对每个模块打一行「ignored null byte」，
        # 两千余条告警把「哪几个模块没签」埋掉。去掉 NUL 不影响判定——魔数
        # 本身不含 NUL。
        if [ "$(tail -c 28 "${ko}" | tr -d '\000')" \
            != '~Module signature appended~' ]; then
            unsigned=$((unsigned + 1))
            if [ "${unsigned}" -le 3 ]; then
                echo "unsigned module: ${ko}"
            fi
        fi
    done < "${kolist}"
    rm -f "${kolist}"
    echo "module signatures: $((total - unsigned))/${total} signed"
    if [ "${total}" -le 0 ]; then
        printf 'check: no modules under %s\n' \
            %{buildroot}/usr/lib/modules/%{kernel_release} >&2
        exit 1
    fi
    if [ "${unsigned}" -ne 0 ]; then
        printf 'check: %s of %s modules unsigned\n' \
            "${unsigned}" "${total}" >&2
        exit 1
    fi
fi
%if %{native}
assert_file %{ksrc}/tools/perf/perf
assert_file %{ksrc}/tools/bpf/bpftool/bpftool
%endif

%post core
if command -v kernel-install >/dev/null 2>&1; then
    kernel-install add %{kernel_release} /boot/vmlinuz-%{kernel_release} || :
fi
# 早期 udevd 在装载规则时就解析 GROUP=，组不在库里即丢弃整条赋值并留一行
# "Unknown group"（50-udev-default.rules 的 sgx 即此，285H 与 run
# 41951370779 都在 initramfs 阶段留下这两行）。dracut 的组库是目标根
# /etc/group 按 sysusers 名单过滤出的副本，而组由 sysusers.d 定义、首启才
# 落到 /etc/group；内核 %%post 在事务内生成 initramfs，此时目标根还没有这些
# 组，于是每次开机都在最早期报一次。生成前先把 sysusers.d 落一份，initramfs
# 与最终系统因此共用同一份组数据库。
if command -v systemd-sysusers >/dev/null 2>&1; then
    systemd-sysusers --root=/ || :
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
/boot/config-%{kernel_release}
/boot/System.map-%{kernel_release}

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
* Thu Nov 05 2026 SPHARX <dev@spharx.com> - 0.0.4-5
- kernel：生成 initramfs 前先执行 systemd-sysusers --root=/。dracut 的
  inst_rule_group_owner 只按 udev 规则里的 GROUP= 从目标根 /etc/group 抄行
  进 initramfs，组在目标根缺失时整条赋值被丢弃，早期 udevd 每次开机留一行
  "Unknown group 'sgx', ignoring."（50-udev-default.rules:63/64）。组由
  sysusers.d 定义、首启才落到 /etc/group，而 %post 在事务内生成 initramfs，
  此时目标根尚无这些组；先落一份 sysusers，initramfs 与最终系统共用同一份
  组数据库。285H 的日志把这两行定位在 initramfs 阶段（15:22:39.93 报，
  15:22:40.67 才 switch root），run 41951370779 的验收镜像同样带着这一对
  行
* Tue Nov 03 2026 SPHARX <dev@spharx.com> - 0.0.4-4
- kernel：覆盖 __spec_install_post，阻止 brp-strip 在 %%install 收尾去掉
  模块尾部签名。0.0.4-2 认定「MODULE_SIG_ALL=y 时签名随模块装入」本身
  没错，但签名之后 rpm 还会对 buildroot 里所有「ELF 且未去符号」的文件
  跑 strip -g，.ko 在其选件范围内，追加在文件尾的 PKCS#7 与魔数被整段
  丢弃，于是 %%check 的尾部判据在每一轮都报全部模块未签名（run
  41643135179）。内核自带 scripts/package/kernel.spec 同样以该宏去掉
  brp-strip，本次沿用。perf 与 bpftool 改为在 %%install 内显式 strip，
  避免关掉后处理后退回未去符号的大二进制
* Tue Nov 03 2026 SPHARX <dev@spharx.com> - 0.0.4-3
- kernel：内核基线随 kernel/ 工作树推进到 6.6.161-alk，%%global
  kernel_version 同步，源码归档名仍由该宏派生。此前工作树已并入上游
  6.6.161，配方停在 6.6.157，build-kernel 的版本漂移检查在镜像组装阶段
  才失败；生成式源码声明也改为引用 %%{kernel_version}，此后抬基线只动
  这一行
* Mon Nov 02 2026 SPHARX <dev@spharx.com> - 0.0.4-2
- kernel：删掉 modules_install 之后的补签分支，%%check 的模块签名判据改按
  文件尾部结构。签名是追加在 .ko 尾部的 PKCS#7 + 12 字节
  module_signature + 28 字节魔数，不是 ELF 段；0.0.3-7 以 readelf -S 找
  .module_sig 段，对真实模块恒为假，使 %%check 必然失败、补签分支必然触发
  并在已签模块上再叠一份 PKCS#7。MODULE_SIG_ALL=y 时 Makefile.modinst 已在
  strip 之后签名，补签没有存在前提
* Mon Nov 02 2026 SPHARX <dev@spharx.com> - 0.0.4-1
- 产品版本抬到 0.0.4，内核基线不变（仍为 6.6.157-alk），本包无内容变化；
  版本号随发行版整体走，装机侧 airy-kernel 与 os-release 的 VERSION_ID
  才能同属一个发行版，不必再靠 Release 号推断镜像批次
* Sat Oct 31 2026 SPHARX <dev@spharx.com> - 0.0.3-7
- kernel：modules_install 之后补一次签名检测，漏签就地对已安装模块执行
  modules_sign，%%check 增加全量 .module_sig 门禁。0.0.3 装机实测模块只带
  .modinfo/.BTF，内核被标 TAINT_UNSIGNED_MODULE（8192）；签名是判断模块
  是否本发行版产出的唯一凭据，缺失后打开 SIG_FORCE 会拒载全部模块
* Mon Oct 26 2026 SPHARX <dev@spharx.com> - 0.0.3-6
- security/airy：AIRY_KUNIT 依赖收紧为 KUNIT=y。该符号是 bool，会把测试
  目标直接链入 vmlinux；原先 depends on KUNIT 在 KUNIT=m 时仍成立，
  allmodconfig 遂把测试目标建入 vmlinux 而 KUnit 核心留在 kunit.ko，
  vmlinux 链接因 kunit_* 未定义引用失败
- kernel/corekern/memory：删除未被调用且无原型的 airy_mem_tier_of() 及其
  从未被读取的分层表 airy_mem_tier_shift[]；clang -Werror 下该内部声明
  不可省略。分配路径走 GFP_KERNEL 从不咨询层级，故连同 Kbuild 项移除
* Sun Oct 25 2026 SPHARX <dev@spharx.com> - 0.0.3-5
- security/airy：补充钩子改由 airy_init() 与核心钩子表相邻注册，修复
  /sys/kernel/security/lsm 中 "airy" 被登记两次的问题。security_add_hooks()
  会把模块名追加进 LSM 注册表，而 lsm_append() 只与末尾名字去重；原先在
  superv 的 late_initcall 里以同名二次注册时 "airy" 已不是末尾项，注册表
  出现重复项。distro 冒烟新增 T7 断言该表内 airy 恰好一次、airy_lockdown
  在位
* Sun Oct 25 2026 SPHARX <dev@spharx.com> - 0.0.3-4
- core 子包补齐内核身份三件套：/boot/config-<release> 与
  /boot/System.map-<release> 与此前的 vmlinuz-<release> 同置。/boot 只有
  镜像时，目标机无法在本地核对「配置是否与包一致」，缺符号表也没有
  crash/kdump 与 ftrace 的取证依据；distro 冒烟新增 T6 断言三者齐全、
  运行内核带 -alk 后缀且 CONFIG_SECURITY_AIRY=y
* Sun Oct 25 2026 SPHARX <dev@spharx.com> - 0.0.3-3
- headers 子包补齐内核身份声明（Provides/Obsoletes: kernel-headers）。
  缺此声明时 glibc-devel 的 kernel-headers 依赖会把上游包拉进同一事务，
  与 airymaxos-kernel-headers 发生 /usr/include 文件冲突，装机事务失败
* Sat Oct 24 2026 SPHARX <dev@spharx.com> - 0.0.3-2
- x86/arm64 内核基线由 defconfig 改为 openeuler_defconfig，恢复 NVMe、
  igc、rtw89 支持；NVMe 内建于 vmlinuz，并在 %%check 中加驱动门禁
* Sat Oct 17 2026 SPHARX <dev@spharx.com> - 0.0.3-1
- Initial kernel package for AirymaxOS 0.0.3
