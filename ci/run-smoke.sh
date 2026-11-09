#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-smoke.sh — distro 组合冒烟（TAP）
#
# 用法:
#   ./run-smoke.sh <被测镜像/系统标识>
#   在已登录的 UKUI X11 桌面会话内执行；探测只读系统状态，不改配置。
#
# 环境:
#   AIRYMAX_SMOKE_WAIT  守护进程就绪等待秒数（默认 30）
#   AIRYMAX_SMOKE_HOST  期望的主机名（默认 airymax-pc，即配方值）
#   AIRYMAX_SMOKE_ROOT  只读系统视图的根前缀（默认空，即真实 /）。T1、T5–T16、
#                       T18 与 T23、T25–T27 读取 /run、/usr/share、/boot、
#                       /sys、/etc、/usr/lib、/usr/bin 下的运行态标记、发行版
#                       标识、资产与随镜像交付的工具，单测在沙箱里用该前缀
#                       复核判定，装机现场保持默认值。
#                       T17 读实时块层，不经该前缀。
#   AIRYMAX_SMOKE_BUILD_ID  发布清单记录的构建来源指纹。给出时要求与本机
#                       BUILD_ID 逐字相同，把「装的是这一轮产出的镜像」变成
#                       可判定事实；缺省只校验机内两处一致。
#   AIRYMAX_SMOKE_BUDGET  外来 err 的棘轮预算；缺省读脚本同目录 err-budget 的
#                       foreign_max，读不到即为 0（最严），不因缺文件放行。
#
# 覆盖:
#   T1  UKUI X11 会话：loginctl 会话属性、ukui-session 进程、X server 可达
#   T2  ibus 输入法：守护进程、全局引擎、会话输入法变量
#   T3  PulseAudio 音频栈：pactl 与守护进程握手
#   T4  桌面隔离 slice：user@UID.service 归属与 slice 资源参数
#   T5  内置壁纸：背景键指向内置路径，图像 sha256 与发行资产一致
#   T6  内核归属：运行的内核是包内 ALK，/boot 三件套齐全、配置一致，模块
#       带签名且内核未被未签名模块污染
#   T7  LSM 注册表：airy 只登记一次，配套 lockdown LSM 在位
#   T8  主机名：/etc/hostname、hostname 与 hostnamectl --static 三处一致
#   T9  品牌：/etc/os-release 的命名不变式（PRETTY_NAME=短名+版本）与
#       /etc/issue 首行同源，ID/代号指向本产品
#   T10 分辨率：每个 connected 输出处于 display_mode.sh 定义的策略模式；
#       报告同附 X 后端自述（驱动与回退原因）与 DRM 卡数，单模式输出时
#       仍能分辨是哪条路径在跑
#   T11 EFI 品牌：ESP 内 airymaxos 目录是完整签名套件，BootOrder 首位为本产品
#   T12 免密提权：交付账户能以 NOPASSWD 完成一次非交互提权
#   T13 免密桌面：空闲锁屏关闭，交付账户在 nopasswdlogin 组内
#   T14 运行期软件源：已安装系统的每个启用段都指向可解析的基底镜像
#   T15 启动参数：/etc/default/grub 持有 loglevel=5 plymouth.enable=0，os-prober 已关闭
#   T16 观测工具：airy-bench / airy-observe / airy-demo 随镜像交付且自检为 ok
#   T17 系统盘布局：/ 与 /data 各挂在一个分区上，且不是同一个分区
#   T18 构建来源：os-release 的 BUILD_ID 与 /etc/airymaxos-build 逐字相同，
#       字符集与长度符合驱动写入口径；给出期望值时还要求两者相同
#   T19–T21 固件：内核日志里没有「固件表无匹配」「微码 INIT 未运行」
#       「API 版本越界」三条失败签名
#   T22 运行期控制台：本次启动的命令行与默认文件同源，systemd-vconsole-setup
#       未失败，控制台字体几何不低于 12x24（2880x1800 上的 8x16 不可读）
#   T23 系统完整性：失败单元、本次开机 err 日志（自有/固件/外来三层）与包集合
#       对账三面同时干净。固件层的 ACPICA 表缺陷只列明细、不进预算。
#   T24 桌面会话收敛：本轮冒烟全程核心进程 pid 不变，开机期没有崩溃重启；
#       判定为 churn 时同附内核段错误行（崩溃落点）与 coredumpctl 的死亡方式
#       （SIGSEGV/SIGABRT），把「崩了」推进到「怎么崩、崩在哪」
#   T25 桌面字体与图标：有字体声明 lang=zh-cn，当前图标主题与 hicolor 兜底
#       主题都能解析到 index.theme
#   T26 无线固件路径：内核按扁平名取固件，intel/iwlwifi/ 下每个文件在固件根
#       上都有同名条目；基底回到扁平布局时判据同样成立
#   T27 现场诊断工具：lsusb/lsof/pactl/airy-bright 随镜像交付
#   T28 网络前端闭包：kylin-nm 与控制中心三个网络模块同属一次安装，缺任一件
#       时面板网络图标与控制中心网络入口同时消失，而无线本身可用
#   T29 触控板：ACPI 有内建触控板节点时必须出现输入设备；无此硬件按能力
#       不适用通过。LPSS 的 PCI ID 缺项时总线不存在、日志无错，只能这样判
#   T30 托盘三件：网络/电量/音量各由一个托盘进程提供，且都由 autostart
#       拉起；包在而 autostart 缺时进程不自启，图标同样消失且无日志
#
# 判定语义:
#   0  — 全部通过
#   1  — 存在失败用例
# 探测工具由被测镜像自身提供（loginctl/pgrep/xdpyinfo 来自本项目的包组合），
# 缺失说明镜像不完整，按失败计；不以 SKIP 掩盖，因为这里没有“不支持的外
# 部测试机”这一情形。
#
# 本脚本自身由 XDG autostart 拉起，与 ibus、pulseaudio 的 autostart 条目
# 同阶段并发执行，守护进程此刻可能尚未就绪。因此这两项探测做有界等待：
# AIRYMAX_SMOKE_WAIT 秒内反复探测，超时仍不就绪即判失败（不放宽判定）。
# ===========================================================================
set -uo pipefail

TARGET="${1:?usage: run-smoke.sh <target-id>}"
WALLPAPER=/usr/share/backgrounds/airymaxos/qilian_photo_from_zhenyi.jpg
PAPER_DIR=/usr/share/backgrounds/airymaxos
PAPER_COUNT=3
PAPER_SHA=fee7f439834ac7dacfc75deaf80a1db1c4bc7459583248eecc87125d52a5ef18
BID_MAX=64
T23_SHOWN=8
START_WAIT="${AIRYMAX_SMOKE_WAIT:-30}"
HOSTNAME_WANT="${AIRYMAX_SMOKE_HOST:-airymax-pc}"
SYSROOT="${AIRYMAX_SMOKE_ROOT:-}"

# 外来 err 的棘轮预算：与脚本同目录的 err-budget，一行 foreign_max=N。
# 文件缺失或格式不合法一律按 0 处理——「读不到就放行」等于把棘轮拆掉，
# 而本项的失败面只需要一次静默放宽就会失去意义。
budget_max() {
    local file="${BASH_SOURCE[0]%/*}" num
    [ "${file}" = "${BASH_SOURCE[0]}" ] && file=.
    file="${file}/err-budget"
    num=$(sed -n 's/^foreign_max=//p' "${file}" 2>/dev/null | tail -n 1)
    case "${num}" in
    '' | *[!0-9]*) printf '0\n' ;;
    *) printf '%s\n' "${num}" ;;
    esac
}
ERR_BUDGET="${AIRYMAX_SMOKE_BUDGET:-$(budget_max)}"

# 判定者不把自己的结论当证据。上报单元（airymax-smoke-report.service）的失败
# 由本轮 TAP 判定驱动，产品就绪单元在验收 ISO 又被 mask，于是它一旦红过，
# 同一台机器上后续每一轮 T23 都会把这条旧结论再算一遍：285H 实测 11:34 的
# 失败让 11:59 及之后每轮都为红，真实根因（包漂移）被自指信号盖住。真实失败
# 单元仍由 AIRYMAX-BOOT-HEALTH 独立上报，排除它不丢证据。
readonly T23_EXCLUDE="airymax-smoke-report.service"

# TAP 与写出它的那次开机绑定，报告侧按同一 id 过滤：上一次开机的结论不能
# 用来判本次（详见 airymax-smoke-report.sh 的 fresh_tap）。
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)

PASS=0
FAIL=0

tap_ok() {
    printf 'ok %s - %s\n' "$1" "$2"
    PASS=$((PASS + 1))
}

# 诊断输出常是多行（airy-observe 首行是计数，其后每行一条 err 明细）。
# printf '#   %s\n' 只会给首行加注释前缀，其余行成为无前缀的裸文本，解析器
# 视为非法行——失败现场越复杂，越容易把 TAP 本身写坏。逐行加前缀。
note_lines() {
    local line
    while IFS= read -r line; do
        printf '#   %s\n' "${line}"
    done <<<"$1"
}

tap_fail() {
    printf 'not ok %s - %s\n' "$1" "$2"
    if [ -n "${3:-}" ]; then
        note_lines "$3"
    fi
    FAIL=$((FAIL + 1))
}

probe() { # probe <编号> <名称> <探测函数>
    local id="$1" name="$2" out rc
    shift 2
    out="$("$@" 2>&1)"
    rc=$?
    if [ "${rc}" -eq 0 ]; then
        tap_ok "${id}" "${name}"
        [ -n "${out}" ] && note_lines "${out}"
    else
        tap_fail "${id}" "${name}" "${out:-probe rc=${rc}}"
    fi
}

need() { # need <命令> — 探测工具随镜像交付，缺失即失败
    command -v "$1" >/dev/null 2>&1 && return 0
    printf '%s not installed\n' "$1"
    return 1
}

expect() { # expect <实际值> <期望值> <字段>
    [ "$1" = "$2" ] && return 0
    printf '%s: %s (want %s)\n' "$3" "${1:-unknown}" "$2"
    return 1
}

expect_prefix() { # expect_prefix <实际值> <期望前缀> <字段>
    case "$1" in
    "$2"*) return 0 ;;
    esac
    printf '%s: %s (want %s*)\n' "$3" "${1:-unknown}" "$2"
    return 1
}

retry() { # retry <秒> <命令...> — 等待并发启动的守护进程，超时即失败
    local limit="$1" waited=0
    shift
    until "$@" >/dev/null 2>&1; do
        [ "${waited}" -ge "${limit}" ] && return 1
        sleep 1
        waited=$((waited + 1))
    done
}

session_prop() { # session_prop <loginctl 属性>
    loginctl show-session "${XDG_SESSION_ID}" -p "$1" --value 2>/dev/null || :
}

xorg_argv() { # xorg_argv — 正在运行的 X server 参数，无 Xorg 进程时返回非零
    local pid

    pid=$(pgrep -o -x Xorg) || return 1
    tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null
}

seat_state() { # seat_state — xserver.log 末条标记，去掉前缀；无文件为空串
    sed -n 's/^AIRYMAX-XSERVER //p' \
        "${SYSROOT}/run/airymaxos/xserver.log" 2>/dev/null | tail -n 1
}

drm_cards() { # drm_cards — /sys/class/drm 下的显卡数，0 即没有 KMS 设备
    local dev="${SYSROOT}/sys/class/drm" n=0 node

    for node in "${dev}"/card[0-9]*; do
        [ -e "${node}" ] || continue
        case "${node##*/}" in
        *-*) continue ;;
        esac
        n=$((n + 1))
    done
    printf '%s' "${n}"
}

seat_marker() { # seat_marker — 校验 xserver.log 的标记与 X 实况一致
    local log="${SYSROOT}/run/airymaxos/xserver.log" line drv conf argv out

    [ -r "${log}" ] || {
        echo "xserver marker missing: ${log}"
        return 1
    }
    line=$(seat_state)
    drv=${line#driver=}
    drv=${drv%% *}
    # 标记是决策时的自述，argv 才是 X 实际收到的选择。两者不一致时黑屏
    # 会伪装成「已按 KMS 启动」，因此这里以运行中进程的命令行为准。
    argv=$(xorg_argv || :)
    case "${drv}" in
    fbdev)
        conf=${line#*conf=}
        conf=${conf%% *}
        case " ${argv} " in
        *" -config ${conf} "*) return 0 ;;
        esac
        echo "xserver is not using ${conf}: ${line}"
        return 1
        ;;
    none)
        echo "display reported as absent while X runs: ${line}"
        return 1
        ;;
    "")
        echo "xserver marker has no driver: ${log}"
        return 1
        ;;
    esac
    case " ${argv} " in
    *" -config "*) echo "kms ${drv} forced a config: ${line}"; return 1 ;;
    esac
    # KMS 分支回查连接器实况：驱动名与标记都可能为真，而屏幕仍因缺 EDID
    # 或模式求交失败而黑屏。
    for out in "${SYSROOT}"/sys/class/drm/card*-*; do
        [ "$(cat "${out}/status" 2>/dev/null)" = connected ] || continue
        grep -q '[^[:space:]]' "${out}/modes" 2>/dev/null || continue
        [ -s "${out}/edid" ] || continue
        return 0
    done
    echo "marker claims kms ${drv} but no ready output: ${line}"
    return 1
}

slice_prop() { # slice_prop <systemd 属性>
    systemctl show airymax-desktop.slice -p "$1" --value 2>/dev/null || :
}

os_rel() { # os_rel <os-release 键> — 去掉赋值两侧的引号
    sed -n "s/^$1=//p" "${SYSROOT}/etc/os-release" | tr -d '"'
}

# T1: UKUI X11 会话（lightdm 会话 + 会话进程 + X server + 驱动标记）
t1_x11() {
    need loginctl || return $?
    need pgrep || return $?
    need xdpyinfo || return $?
    [ -n "${DISPLAY:-}" ] || { echo "DISPLAY unset"; return 1; }
    [ -n "${XDG_SESSION_ID:-}" ] || { echo "XDG_SESSION_ID unset"; return 1; }
    expect "$(session_prop Type)" x11 "session type" || return 1
    expect_prefix "$(session_prop Service)" lightdm "session service" ||
        return 1
    expect "$(session_prop Active)" yes "session active" || return 1
    pgrep -f ukui-session >/dev/null || {
        echo "ukui-session not running"
        return 1
    }
    xdpyinfo >/dev/null 2>&1 || {
        echo "X11 unreachable: ${DISPLAY}"
        return 1
    }
    seat_marker
}

ime_engine() { # ime_engine — 打印 ibus 全局引擎名，总线不可达时返回非零
    ibus engine 2>/dev/null
}

# T2: 输入法（ibus 守护进程、引擎可达与会话变量）
t2_ime() {
    need pgrep || return $?
    command -v ibus >/dev/null 2>&1 || {
        echo "ibus not installed"
        return 1
    }
    retry "${START_WAIT}" pgrep -x ibus-daemon || {
        echo "ibus-daemon not running"
        return 1
    }
    retry "${START_WAIT}" ime_engine || {
        echo "ibus engine unavailable"
        return 1
    }
    local engine
    engine="$(ime_engine)"
    [ -n "${engine}" ] || {
        echo "ibus engine: empty"
        return 1
    }
    expect "${GTK_IM_MODULE:-}" ibus "GTK_IM_MODULE" || return 1
    expect "${QT_IM_MODULE:-}" ibus "QT_IM_MODULE" || return 1
    expect "${XMODIFIERS:-}" "@im=ibus" "XMODIFIERS" || return 1
}

# T3: 音频栈（PulseAudio 客户端握手）
t3_audio() {
    command -v pactl >/dev/null 2>&1 || {
        echo "pactl not installed"
        return 1
    }
    retry "${START_WAIT}" pactl info || {
        echo "PulseAudio unreachable"
        return 1
    }
}

# T4: 桌面隔离 slice（会话归属与资源参数）
#
# CPUWeight 有两个合法取值：单元钉住的基线 50，与 coexist 在 CPU 争用下写
# 入的运行时提升 200（X-05）。这里断言的是「运行时只出现这两个值」——把
# 200 判负，等于让高负载下正确的保护行为变成开机失败。
t4_slice() {
    need systemctl || return $?
    local tasks weight
    expect "$(systemctl show "user@${UID}.service" -p Slice --value 2>/dev/null)" \
        airymax-desktop.slice "user@ service slice" || return 1
    expect "$(systemctl is-active airymax-desktop.slice 2>/dev/null)" \
        active "slice state" || return 1
    weight="$(slice_prop CPUWeight)"
    case " 50 200 " in
        *" ${weight} "*) ;;
        *)
            echo "slice CPUWeight: ${weight:-unknown} (want 50 or 200)"
            return 1
            ;;
    esac
    expect "$(slice_prop IOWeight)" 50 "slice IOWeight" || return 1
    tasks="$(slice_prop TasksMax)"
    [ -n "${tasks}" ] && [ "${tasks}" != infinity ] || {
        echo "slice TasksMax: ${tasks:-unknown}"
        return 1
    }
}

# T5: 内置壁纸（默认背景、集合大小与图像内容）
t5_wallpaper() {
    command -v gsettings >/dev/null 2>&1 || {
        echo "gsettings not installed"
        return 1
    }
    local path sum have
    path="$(gsettings get org.mate.background picture-filename 2>&1)" || {
        echo "org.mate.background picture-filename: ${path:-unavailable}"
        return 1
    }
    expect "${path//\'/}" "${WALLPAPER}" "picture-filename" || return 1
    # 集合多一件说明上游壁纸包漏进镜像，少一件说明注册表指向了不存在的
    # 文件；两种情况都只在桌面会话里表现为空背景，故按目录事实计数。
    # 目录与图像按 SYSROOT 取根：schema 里记的是安装路径，单测的沙箱视图
    # 在别处，两者只在真机上重合。
    have=$(find "${SYSROOT}${PAPER_DIR}" -maxdepth 1 -type f -name '*.jpg' \
        2>/dev/null | wc -l)
    expect "$((have))" "${PAPER_COUNT}" "wallpaper set size" || return 1
    sum="$(sha256sum "${SYSROOT}${WALLPAPER}" 2>&1)" || {
        echo "wallpaper unreadable: ${WALLPAPER}"
        return 1
    }
    expect "${sum%% *}" "${PAPER_SHA}" "wallpaper sha256" || return 1
}

# T6: 内核归属（运行内核、/boot 三件套、配置与模块签名）
t6_kernel_identity() {
    local rel f ko total=0 bad=0 taint
    rel="$(uname -r)"
    # 发行版内核带 -alk 本地版本后缀，这是「跑的是不是自己的内核」最便宜的
    # 判别。上游 openEuler 内核为 6.6.0-*.oe*，不会被误判为通过。
    case "${rel}" in
    *-alk) : ;;
    *)
        echo "uname -r: ${rel} (want *-alk)"
        return 1
        ;;
    esac
    for f in "${SYSROOT}/boot/vmlinuz-${rel}" "${SYSROOT}/boot/config-${rel}" \
        "${SYSROOT}/boot/System.map-${rel}"; do
        [ -s "${f}" ] || {
            echo "${f} missing"
            return 1
        }
    done
    grep -qx 'CONFIG_LOCALVERSION="-alk"' "${SYSROOT}/boot/config-${rel}" || {
        echo "config-${rel}: LOCALVERSION mismatch"
        return 1
    }
    grep -qx 'CONFIG_SECURITY_AIRY=y' "${SYSROOT}/boot/config-${rel}" || {
        echo "config-${rel}: CONFIG_SECURITY_AIRY not set"
        return 1
    }
    grep -q ' start_kernel$' "${SYSROOT}/boot/System.map-${rel}" || {
        echo "System.map-${rel}: start_kernel absent"
        return 1
    }
    # 模块签名是追加在 .ko 尾部的 PKCS#7 + 12 字节 module_signature + 28
    # 字节魔数，不是 ELF 段；0.0.3-6 及更早按 .module_sig 段判签，对真实模块
    # 恒为假。全量比对尾部魔数：漏签的模块一被加载，内核就带上 8192
    # （TAINT_UNSIGNED_MODULE），打开 SIG_FORCE 后则直接被拒载。
    while IFS= read -r -d '' ko; do
        total=$((total + 1))
        if [ "$(tail -c 28 "${ko}")" != '~Module signature appended~' ]; then
            printf 'unsigned module: %s\n' "${ko}"
            bad=$((bad + 1))
        fi
    done < <(find "${SYSROOT}/usr/lib/modules/${rel}" -name '*.ko' \
        -print0 2>/dev/null)
    [ "${total}" -gt 0 ] || {
        echo "no module under /usr/lib/modules/${rel}"
        return 1
    }
    [ "${bad}" -eq 0 ] || {
        echo "${bad}/${total} modules unsigned"
        return 1
    }
    taint="$(cat "${SYSROOT}/proc/sys/kernel/tainted" 2>/dev/null)" || {
        echo "tainted unreadable: ${SYSROOT}/proc/sys/kernel/tainted"
        return 1
    }
    case "${taint}" in
    ''|*[!0-9]*)
        echo "tainted: not a decimal integer (${taint})"
        return 1
        ;;
    esac
    [ $((taint & 8192)) -eq 0 ] || {
        echo "kernel tainted by unsigned module (tainted=${taint})"
        return 1
    }
}

# T7: LSM 注册表（同名模块只能登记一次）
t7_lsm_registry() {
    local list seen
    list="$(cat "${SYSROOT}/sys/kernel/security/lsm" 2>&1)" || {
        echo "lsm registry unreadable: ${list}"
        return 1
    }
    # security_add_hooks() 顺带把模块名写进这张表，而 lsm_append() 只与
    # 末尾名字去重。补充钩子若在 late_initcall 里以同名二次注册，"airy"
    # 就会出现两次：这不是两个模块，而是同一个模块被登记了两遍。
    seen="$(printf '%s\n' "${list}" | tr ',' '\n' | grep -cx 'airy')"
    [ "${seen}" -eq 1 ] || {
        echo "airy registered ${seen} time(s): ${list}"
        return 1
    }
    # airy_lockdown 是独立命名的一层（只挂 locked_down），随产品内核交付。
    printf '%s\n' "${list}" | tr ',' '\n' | grep -qx 'airy_lockdown' || {
        echo "airy_lockdown absent: ${list}"
        return 1
    }
}

# T8: 主机名（三处读取必须同值：静态文件、内核名、hostnamectl 静态字段；
# 0.0.3 靠 sysctl.d 在内核层回写，任一环脱钩都会让现场看到两个名字）
t8_hostname() {
    local file="${SYSROOT}/etc/hostname" name kern stat
    [ -r "${file}" ] || {
        echo "${file} unreadable"
        return 1
    }
    name=$(cat "${file}")
    expect "${name}" "${HOSTNAME_WANT}" "hostname" || return 1
    kern=$(hostname) || {
        echo "hostname probe failed"
        return 1
    }
    expect "${kern}" "${HOSTNAME_WANT}" "kernel hostname" || return 1
    stat=$(hostnamectl --static) || {
        echo "hostnamectl probe failed"
        return 1
    }
    expect "${stat}" "${HOSTNAME_WANT}" "static hostname" || return 1
}

# T9: 品牌（os-release 是发行版身份的唯一载体，桌面与会话代理都读它）
t9_brand() {
    local file="${SYSROOT}/etc/os-release" ver pretty dist name
    [ -r "${file}" ] || {
        echo "${file} unreadable"
        return 1
    }
    expect "$(os_rel ID)" airymaxos "os-release ID" || return 1
    expect "$(os_rel VERSION_CODENAME)" openairymax "os-release codename" ||
        return 1
    ver="$(os_rel VERSION_ID)"
    case "${ver}" in
    [0-9]*.[0-9]*.[0-9]*) : ;;
    *)
        echo "os-release VERSION_ID: ${ver:-absent} (want X.Y.Z)"
        return 1
        ;;
    esac
    # 两层展示名的可执行不变式：PRETTY_NAME 必须逐字等于「<ASCII 短名> <版本
    # 号>」。逐字断言品牌串会把某一版的命名写死在探针里，命名调整即整条判定
    # 失效；断言不变式既锁住格式又随 os-release 一起演进。短名必须 ASCII——
    # 它同时是引导菜单条目名、ISO 卷标与 NVRAM 的通道。
    pretty="$(os_rel PRETTY_NAME)"
    dist="${pretty%% *}"
    case "${dist}" in
    ''|*[!A-Za-z0-9._-]*)
        echo "os-release PRETTY_NAME: ${pretty:-absent} (want '<brand> <version>')"
        return 1
        ;;
    esac
    expect "${dist} ${ver}" "${pretty}" "os-release PRETTY_NAME" || return 1
    # NAME 与 PRETTY_NAME 同一通道：openEuler 的 /etc/grub.d/10_linux 把
    # NAME 原样写进引导菜单标题，而 GRUB 只加载不含 CJK 字形的 unicode.pf2，
    # 非 ASCII 会整段不显示。故 NAME 必须是 ASCII 且以同一短名起头——底座名
    # （openEuler）在此判失败。
    name="$(os_rel NAME)"
    case "${name}" in
    ''|*[!A-Za-z0-9._\ -]*)
        echo "os-release NAME: ${name:-absent} (want ASCII '<brand>...')"
        return 1
        ;;
    esac
    expect_prefix "${name}" "${dist}" "os-release NAME" || return 1
    # 登录前的品牌面与 os-release 同一事实源：/etc/issue 首行逐字等于
    # PRETTY_NAME。文件缺失时 sed 给出空串，由 expect 报出差异。
    expect "$(sed -n 1p "${SYSROOT}/etc/issue")" "${pretty}" "issue 首行" ||
        return 1
}

# T10: 分辨率（会话输出必须处于策略模式，策略单点在 display_mode.sh）
t10_display() {
    local script="${SYSROOT}/usr/lib/airymaxos/desktop/display_mode.sh"
    local out rc
    need xrandr || return $?
    [ -x "${script}" ] || {
        echo "${script} not installed"
        return 1
    }
    # 会话内的收敛是并发的有界过程（xinitrc.d 钩子 + autostart 守护），本
    # 探测同样等待到同一个上界再判定，避免把「尚未收敛」误判成「策略失效」。
    if retry "${START_WAIT}" "${script}" --check; then
        # 通过不等于自适应生效：唯一模式的输出由驱动固定成单一模式，策略
        # 无从切换。--report 把每个输出的结论（policy / single-mode / drift）
        # 摊平进 TAP，验收才能区分「策略选对了」与「硬件只给一个模式」。
        # 后端自述与 DRM 卡数同属一件事的上游：同为单模式时，fbdev 与
        # modesetting 的运行期语义完全不同（前者没有 RandR 输出），桌面组件
        # 崩不崩、崩在哪一层只能靠这两项区分，故一并在本行给出。
        printf 'report=%s xserver=%s drm=%s\n' \
            "$("${script}" --report 2>&1 | tr '\n' ';')" \
            "$(seat_state)" "$(drm_cards)"
        return 0
    fi
    out=$("${script}" --check 2>&1)
    rc=$?
    # 诊断压成一行：TAP 只有首行带 "#   " 前缀，多行会被判定器丢掉。
    # 偏差与完整拓扑由 --check 自带；journal 补策略自身的切换结果，guard
    # 计数回答「守护进程是否还在窗口内」——三者合起来才能区分「选错」、
    # 「切不动」与「根本没人在守」。
    printf '%s | guard=%s log=%s\n' \
        "$(printf '%s' "${out}" | tr '\n' ';')" \
        "$(pgrep -fc 'display_mode\.sh --guard' 2>/dev/null || echo 0)" \
        "$(journalctl -t airymaxos-display -n 6 --no-pager -o short-iso \
            2>/dev/null | tr '\n' ';')"
    return "${rc}"
}

# ESP 以 fstab 的 umask=077 挂载为 drwx------ root root：交付账户读不到目录
# 项，`[ -f ]` 随之以 EACCES 静默为假，把权限问题报成「文件缺失」。探测因此
# 先看父目录是否可读，读不到就经 sudo -n 复核（T12 已证该路径可用）。
esp_ok() { # esp_ok <绝对路径> — 存在且非空
    if [ -r "$(dirname "$1")" ]; then
        [ -s "$1" ]
        return
    fi
    sudo -n test -s "$1" 2>/dev/null
}

# ESP 品牌目录对交付账户的可达方式，是 T11 归因的关键：readable 说明文件
# 真缺，sudo 说明只是权限，denied 说明连提权都不可用。
esp_state() {
    local dir="${SYSROOT}/boot/efi/EFI/airymaxos"
    [ -r "${dir}" ] && {
        printf 'readable'
        return 0
    }
    if sudo -n test -r "${dir}" 2>/dev/null; then
        printf 'sudo'
        return 0
    fi
    printf 'denied'
}

# 只读复核时 NVRAM 属于宿主，BootCurrent 无意义；在线时它与 BootOrder 首位
# 合起来才能区分「条目没置顶」与「置顶了但固件没选它」。
t11_boot() {
    [ -n "${SYSROOT}" ] && return 0
    efibootmgr 2>/dev/null | sed -n 's/^BootCurrent: *//p' | tr -d ' \n'
}

# T11 失败时的单行事实。TAP 只保留 probe 输出的第一行，诊断必须压成一行；
# 状态文件区分「没做」与「做了但没留痕」，品牌日志末行给出直接原因，esp
# 给出探测方式的归因，boot 给出固件实际选中的条目。
t11_facts() {
    local st="${SYSROOT}/var/lib/airymaxos/efi-brand"
    local lg="${SYSROOT}/var/log/airymax/efi-brand.log"
    local s=absent l=- b
    [ -s "${st}" ] && s=ok
    [ -s "${lg}" ] && l=$(tail -n 1 "${lg}" | tr -s '[:space:]' ' ' |
        cut -c1-96)
    b=$(t11_boot)
    printf ' state=%s log=%s esp=%s boot=%s' "${s}" "${l}" "$(esp_state)" \
        "${b:--}"
}

# T11: EFI 品牌（安装期品牌化把 NVRAM 首选项换成 AirymaxOS，ESP 内是一整套
# 已签名二级加载器；shim 只从自身目录取 grubx64.efi，缺一即不可引导）
t11_efi_brand() {
    local esp="${SYSROOT}/boot/efi/EFI/airymaxos" f out first
    if [ ! -d "${SYSROOT}/sys/firmware/efi" ]; then
        echo "non-EFI target: no NVRAM entry to brand"
        return 0
    fi
    for f in shimx64.efi grubx64.efi BOOTX64.CSV; do
        esp_ok "${esp}/${f}" && continue
        echo "${esp}/${f} missing$(t11_facts)"
        return 1
    done
    esp_ok "${SYSROOT}/var/lib/airymaxos/efi-brand" || {
        echo "efi-brand state missing$(t11_facts)"
        return 1
    }
    # 只读复核时 NVRAM 属于宿主而非被测系统，到此为止。
    [ -n "${SYSROOT}" ] && return 0
    need efibootmgr || return $?
    out=$(efibootmgr 2>/dev/null) || {
        echo "efibootmgr failed$(t11_facts)"
        return 1
    }
    first=$(printf '%s\n' "${out}" | sed -n 's/^BootOrder: *//p' |
        cut -d, -f1)
    printf '%s\n' "${out}" | grep -q "^Boot${first}\* AirymaxOS" || {
        echo "BootOrder head=${first}: $(printf '%s\n' "${out}" |
            grep "^Boot${first}")$(t11_facts)"
        return 1
    }
}

# T12: 免密提权（amuser 交付为空口令，而空口令在 sudo 的 PAM 栈里不是可用
# 的交互凭据；缺了 NOPASSWD，装机后没有任何非交互提权路径，从桌面上却看不出
# 异常。这里直接以交付账户身份试一次，不读配置文件）
t12_passwordless() {
    local f="${SYSROOT}/etc/sudoers.d/90-airymax"
    if [ -n "${SYSROOT}" ]; then
        [ -f "${f}" ] || {
            echo "${f} missing"
            return 1
        }
        grep -qxF 'amuser ALL=(ALL) NOPASSWD: ALL' "${f}" || {
            echo "policy line absent in ${f}"
            return 1
        }
        echo "policy file ok (offline check)"
        return 0
    fi
    need sudo || return $?
    sudo -n true 2>&1 || {
        echo "sudo -n refused: policy not in effect"
        return 1
    }
    echo "sudo -n ok without password"
}

# T13: 免密桌面（空口令账户一旦被空闲锁屏拦住，解锁框就成了口令墙：锁屏挡
# 不住任何人，只把「开机即桌面」变成「每五分钟输一次口令」。策略以 dconf
# 系统库交付，键文件在位但未 dconf update 时不会生效，所以这里必须读实际
# 键值，而不是看文件是否存在）
t13_passwordless_desktop() {
    local f="${SYSROOT}/etc/dconf/db/local.d/00-airymax-screensaver"
    if [ -n "${SYSROOT}" ]; then
        [ -f "${f}" ] || {
            echo "${f} missing"
            return 1
        }
        grep -qxF 'idle-lock-enabled=false' "${f}" || {
            echo "idle-lock-enabled not disabled in ${f}"
            return 1
        }
        grep -qxF 'lock-enabled=false' "${f}" || {
            echo "lock-enabled not disabled in ${f}"
            return 1
        }
        echo "screensaver policy ok (offline check)"
        return 0
    fi
    need dconf || return $?
    expect "$(dconf read /org/ukui/screensaver/lock-enabled 2>&1)" false \
        "lock-enabled" || return 1
    expect "$(dconf read /org/ukui/screensaver/idle-lock-enabled 2>&1)" false \
        "idle-lock-enabled" || return 1
    id -nG amuser 2>/dev/null | tr ' ' '\n' | grep -qxF nopasswdlogin || {
        echo "amuser not in nopasswdlogin"
        return 1
    }
}

# T14: 运行期软件源（安装期的仓库闭包写在 kickstart 里，装完之后 dnf 只认
# /etc/yum.repos.d：地址若带 $releasever，dnf 会把它展开成产品版本而不是基底
# 版本，路径不存在，系统装完就再没有可用的源。冷启动腿没有网络，镜像可达性
# 已由安装腿的 url 行证明，这里只断结构：有启用段、地址是基底镜像的绝对形式
# 而不是版本变量、各段落在同一台镜像上）
repo_rows() { # repo_rows <repo 文件> — 每个 baseurl 一行：段 <TAB> 启用 <TAB> 主址
    # 键次序在 ini 里无约束（enabled 通常写在 baseurl 之后），因此先按段收集，
    # 到 END 再按出现次序输出；缺 enabled 的段按 dnf 缺省为启用。
    awk '
        /^[[:space:]]*\[/ {
            sec = $0
            gsub(/[][[:space:]]/, "", sec)
            order[++n] = sec
            next
        }
        /^[[:space:]]*enabled[[:space:]]*=/ {
            sub(/^[^=]*=[[:space:]]*/, "")
            en[sec] = $0
            next
        }
        /^[[:space:]]*baseurl[[:space:]]*=/ {
            sub(/^[^=]*=[[:space:]]*/, "")
            split($0, url, /[[:space:]]+/)
            if (!(sec in addr))
                addr[sec] = url[1]
        }
        END {
            for (i = 1; i <= n; i++) {
                s = order[i]
                if (s in addr)
                    print s "\t" (s in en ? en[s] : 1) "\t" addr[s]
            }
        }
    ' "$1"
}

t14_repos() {
    local file="${SYSROOT}/etc/yum.repos.d/airymaxos.repo" rows
    local sec en url use=0 host0="" host
    [ -r "${file}" ] || {
        echo "${file} unreadable"
        return 1
    }
    grep -qF '$releasever' "${file}" && {
        echo "${file}: \$releasever does not name the base release"
        return 1
    }
    rows="$(repo_rows "${file}")" || {
        echo "${file}: unparsable"
        return 1
    }
    while IFS=$'\t' read -r sec en url; do
        [ "${en}" = 1 ] || continue
        use=$((use + 1))
        case "${url}" in
        https://*/openEuler-[0-9]*/*) : ;;
        *)
            printf 'section %s baseurl: %s\n' "${sec}" "${url:--}"
            return 1
            ;;
        esac
        host="${url#https://}"
        host="${host%%/*}"
        if [ -z "${host0}" ]; then
            host0="${host}"
        elif [ "${host}" != "${host0}" ]; then
            printf 'section %s host: %s (want %s)\n' "${sec}" "${host}" \
                "${host0}"
            return 1
        fi
    done <<<"${rows}"
    [ "${use}" -gt 0 ] || {
        echo "no enabled section in ${file}"
        return 1
    }
    printf '%s enabled section(s) on %s\n' "${use}" "${host0}"
}

# T15 启动参数：bootloader --append 只进安装器写的那份 grub.cfg，
# /etc/default/grub 才是此后每次 grub2-mkconfig 的输入。缺参数的表现是
# 「装完有启动画面、升级一次又逐行滚日志」，所以在默认文件上判定；同时
# 断言 os-prober 已关闭，否则同盘其他发行版的内核会并进本产品菜单。
#
# 期望按剖面不再分叉：0.0.4 起启动路径上没有 plymouth，两个剖面都要求
# plymouth.enable=0 与 loglevel=5，并把 rhgb/quiet 判为未收敛。桌面剖面过去
# 独有的 rhgb quiet 正是把启动信息藏起来的那条路径——285H 卡在 plymouth 的
# oneshot 单元上时，屏幕既没有进展也没有原因。
#
# 控制台顺序一并判定：/dev/console 落在命令行里最后一个 console= 上。
# 285H 现场的 "tty0 ttyS0" 让 VT 让位给串口，systemd-vconsole-setup 锁不住
# /dev/console，桌面就绪门禁每个启动周期失败——这条只在默认文件上才看得
# 出来，装完当天不重启不会暴露。
#
# cons_check <命令行> <来源> —— 控制台集合的判定只有这一处：默认文件与运行期
# 命令行必须是同一套，否则「装完当天正常、重启后失声」会被两个口径各自放过。
cons_check() {
    local cons
    cons=$(printf '%s\n' "$1" | tr ' ' '\n' | grep '^console=' |
        tr '\n' ' ') || {
        printf '%s lacks console=\n' "$2"
        return 1
    }
    cons=${cons% }
    case " ${cons} " in
    *" console=ttyS0,115200 "*) ;;
    *)
        printf '%s lacks the serial console\n' "$2"
        return 1
        ;;
    esac
    [ "${cons##* }" = "console=tty0" ] || {
        printf '%s: primary console is %s, not tty0\n' \
            "$2" "${cons##* }"
        return 1
    }
    [ "$(printf '%s\n' "${cons}" | wc -w)" -eq 2 ] || {
        printf '%s carries a foreign console\n' "$2"
        return 1
    }
}

t15_boot_args() {
    local file="${SYSROOT}/etc/default/grub" line tok
    [ -r "${file}" ] || {
        echo "${file} unreadable"
        return 1
    }
    line=$(sed -n 's/^GRUB_CMDLINE_LINUX="\(.*\)"$/\1/p' "${file}" |
        head -n 1)
    # 逐行日志是产品口径，不随剖面变化：两个剖面都要 plymouth.enable=0 与
    # loglevel=5，任何一处缺失都说明安装末期的 grub_args.sh 没跑到。
    for tok in loglevel=5 plymouth.enable=0; do
        case " ${line} " in
        *" ${tok} "*) continue ;;
        esac
        printf '%s: GRUB_CMDLINE_LINUX lacks %s\n' "${file}" "${tok}"
        return 1
    done
    # 旧画面参数留在文件里等于没改：grub_args.sh 收敛时摘掉，这里兜住回归。
    for tok in rhgb quiet; do
        case " ${line} " in
        *" ${tok} "*)
            printf '%s: GRUB_CMDLINE_LINUX still carries %s\n' \
                "${file}" "${tok}"
            return 1
            ;;
        esac
    done
    cons_check "${line}" GRUB_CMDLINE_LINUX || return 1
    t15_brand_cfg || return 1
    grep -qxF 'GRUB_DISABLE_OS_PROBER=true' "${file}" || {
        echo "${file}: os-prober not disabled"
        return 1
    }
    # 停留时间是 loader 段的主要构成（285H 分段 3.78s 里 3s 在此），安装
    # 末期由 grub_args.sh 归一化；未归一化说明那一步没跑到，按未收敛处理。
    grep -qxF 'GRUB_TIMEOUT=1' "${file}" || {
        echo "${file}: menu timeout not normalized"
        return 1
    }
    printf 'args="%s"\n' "${line}"
}

# 引导期读的是品牌副本：EFI 下 grub 的 $prefix 取自被加载的 grubx64.efi
# 所在目录，NVRAM 指向 \EFI\airymaxos。生成件与副本不一致时，改参数与内核
# 升级在下一次重启都不生效（285H 取证，D-07）。生成件不在场即非 EFI 装机，
# 不判定。
t15_brand_cfg() {
    local gen="${SYSROOT}/boot/efi/EFI/openEuler/grub.cfg"
    local brand="${SYSROOT}/boot/efi/EFI/airymaxos/grub.cfg"
    [ -f "${gen}" ] || return 0
    [ -f "${brand}" ] || {
        echo "brand grub.cfg absent"
        return 1
    }
    cmp -s "${gen}" "${brand}" || {
        echo "brand grub.cfg differs from the generated one"
        return 1
    }
}

# T16 观测工具：airy-bench、airy-observe 与 airy-demo 随发行包装进 /usr/bin。
# 三者都是现场演示与故障定位的入口，装机后跑不起来等于没装。这里只断言它们
# 在装机系统内可直接执行且自检为 ok：bench 与 demo 取 --check（demo 只清点
# 对端与终端，不重复度量），observe 取 --static --root（只读文件，不依赖活动
# 会话）。观测数值随机器的负载波动，不进判定；判定只看工具自身给的 status。
t16_obs_tools() {
    local out
    need airy-bench || return 1
    need airy-observe || return 1
    need airy-demo || return 1
    out=$(airy-bench --check 2>&1) || {
        printf '%s\n' "${out}"
        return 1
    }
    case " ${out} " in
    *" status=ok "*) ;;
    *)
        printf 'airy-bench status!=ok\n'
        return 1
        ;;
    esac
    out=$(airy-demo --check 2>&1) || {
        printf '%s\n' "${out}"
        return 1
    }
    case " ${out} " in
    *" status=ok "*) ;;
    *)
        printf 'airy-demo status!=ok\n'
        return 1
        ;;
    esac
    out=$(airy-observe --static --root "${SYSROOT:-/}" 2>&1) || {
        printf '%s\n' "${out}"
        return 1
    }
    printf 'bench=ok demo=ok observe=ok\n'
}

# T17 系统盘布局：安装器把系统与数据放在两个独立分区上，数据分区才能单独
# 扩容、单独重建而不动系统分区。判据取实际挂载源（findmnt）与设备类型
# （lsblk），不读安装期写的计划文件：计划与落地不一致正是要抓的回归。
# btrfs 子卷在 findmnt 里表现为 `/dev/sda2[/@data]`，与系统同一分区，不能
# 当作独立数据分区，因此还要求挂载源本身是 part。
t17_disk_layout() {
    local root data rtype dtype parts
    need findmnt || return $?
    need lsblk || return $?
    root="$(findmnt -n -o SOURCE / 2>&1)" || {
        echo "findmnt /: ${root:-no source}"
        return 1
    }
    data="$(findmnt -n -o SOURCE /data 2>&1)" || {
        echo "/data not mounted: ${data:-no source}"
        return 1
    }
    [ "${root}" != "${data}" ] || {
        printf '/ and /data share %s\n' "${root}"
        return 1
    }
    rtype="$(lsblk -n -o TYPE "${root}" 2>&1)" || {
        printf 'lsblk %s: %s\n' "${root}" "${rtype:-no type}"
        return 1
    }
    dtype="$(lsblk -n -o TYPE "${data}" 2>&1)" || {
        printf 'lsblk %s: %s\n' "${data}" "${dtype:-no type}"
        return 1
    }
    expect "${rtype}" part "TYPE ${root}" || return 1
    expect "${dtype}" part "TYPE ${data}" || return 1
    parts="$(lsblk -n -o TYPE 2>/dev/null | grep -cx part)" || parts=0
    [ "${parts}" -ge 2 ] || {
        echo "lsblk partitions: ${parts} (want >=2)"
        return 1
    }
    printf '%s=part %s=part partitions=%s\n' "${root}" "${data}" "${parts}"
}

# T18 构建来源：镜像文件名在下载、改名、经 U 盘传递之后不再可追溯，构建号
# 是回查「这份系统由哪次构建产出」的唯一机内线索。两处标识由同一个宏写入，
# 不同即说明有一侧被单独替换或漏写；字符集与长度按驱动写入口径判定，避免
# 把空串或带引号的畸形值当成有效指纹。
t18_build_id() {
    local file="${SYSROOT}/etc/airymaxos-build" id
    [ -r "${file}" ] || {
        echo "${file} unreadable"
        return 1
    }
    id="$(sed -n 's/^BUILD_ID=//p' "${file}" | head -n 1)"
    case "${id}" in
    ''|*[!A-Za-z0-9._+-]*)
        echo "airymaxos-build: ${id:-absent} (want [A-Za-z0-9._+-]+)"
        return 1
        ;;
    esac
    [ "${#id}" -le "${BID_MAX}" ] || {
        echo "build id length: ${#id} (want <=${BID_MAX})"
        return 1
    }
    expect "$(os_rel BUILD_ID)" "${id}" "os-release BUILD_ID" || return 1
    if [ -n "${AIRYMAX_SMOKE_BUILD_ID:-}" ]; then
        expect "${id}" "${AIRYMAX_SMOKE_BUILD_ID}" "release build id" ||
            return 1
    fi
    printf 'build_id=%s\n' "${id}"
}

# T19–T21 固件三条判据。判据只能来自内核日志：驱动没找到固件时不会留下任何
# 文件，期望文件名只存在于模块自报（modinfo）里，两者唯一的交集是本次开机的
# 载入记录。三条签名各占一项，而不是合成一项：它们对应三种不同的现场处置
# （补固件包、更新微码、对齐 API 版本），合成一项就把「哪一类」退回到人工读
# 日志。三条都以「驱动仍然加载成功」收场，模块列表与 sysfs 都看不出，只看
# 模块表会全部判过；日志读不到时同样判负，因为「没有证据」不等于「载入成功」。
fw_clean() { # fw_clean <失败签名> <现象>
    local log hit
    need dmesg || return 1
    log=$(dmesg 2>/dev/null) || {
        printf 'kernel log unreadable: cannot rule out %s\n' "$2"
        return 1
    }
    hit=$(printf '%s\n' "${log}" | grep -Ei "$1")
    [ -z "${hit}" ] || {
        printf '%s\n' "${hit}"
        return 1
    }
}

t19_fw_blob() {
    fw_clean 'no suitable firmware found' 'a driver without its blob'
}

t20_fw_microcode() {
    fw_clean 'failed to run init ucode' 'stale CPU microcode'
}

# T21 判的是「无线设备有没有真的拿到固件」，不是「固件有没有比内核新」。
# 驱动遇到自己不认识的 API 标志组时先打一条 IWL_WARN、再忽略该组继续载入
# （iwl-drv.c 的 iwl_set_ucode_api_flags 越界即 return），随发行版固件比
# 内核新而来的告警因此是常态：2026-11-06 的 285H 在告警之后
# loaded firmware version 83.ec13314b.0、PNVM 与 PHC 全部就绪、无线可用。
# 以告警为签名会把常态判成缺陷，让本项长期为红。改判正证据：内核枚举到的
# 每个 iwlwifi 设备都必须有一行 loaded firmware version —— 设备在而固件没
# 载入时，无论日志用哪句话解释（载入失败、根本没有可用的 blob、模块被退
# 回旧版本），这台机器的无线能力都不可用。
t21_fw_api() {
    local log devs bdf miss= ver=

    need dmesg || return 1
    log=$(dmesg 2>/dev/null) || {
        printf 'kernel log unreadable: cannot rule out an unloaded wireless firmware\n'
        return 1
    }
    devs=$(printf '%s\n' "${log}" \
        | sed -n 's/^.*iwlwifi \([0-9a-f:.]*\): .*/\1/p' \
        | sort -u)
    [ -n "${devs}" ] || {
        echo "no iwlwifi device"
        return 0
    }
    for bdf in ${devs}; do
        if printf '%s\n' "${log}" \
            | grep -q "iwlwifi ${bdf}: loaded firmware version"; then
            continue
        fi
        miss="${miss} ${bdf}"
    done
    [ -z "${miss}" ] || {
        printf 'wireless device without loaded firmware:%s\n' "${miss}"
        return 1
    }
    ver=$(printf '%s\n' "${log}" \
        | sed -n 's/^.*iwlwifi [0-9a-f:.]*: loaded firmware version \([^ ]*\).*/\1/p' \
        | head -n 1)
    printf 'wireless firmware loaded: %s\n' "${ver}"
}

# 控制台字体的判据取几何，不取名字：同一个名字在不同 kbd 包里可以换尺寸，
# 只比对字符串时字体改小仍会通过，而那正是 285H 的现场——九行阶段行已全为
# ASCII，字号却还是 8x16。PSF2 头在偏移 24/28 给出真实 height/width；PSF1
# 没有尺寸字段（固定 8 列），在任何 2880 宽容量的屏幕上都不足，因此这里要求
# PSF2，指过去也判失败。
t22_font_geom() {
    local conf="$1" font file hdr h w
    local -a head=()

    [ -r "${conf}" ] || {
        printf '%s unreadable\n' "${conf}"
        return 1
    }
    font=$(sed -n 's/^[[:space:]]*FONT="\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
        "${conf}" | tail -n 1)
    [ -n "${font}" ] || {
        printf '%s carries no FONT\n' "${conf}"
        return 1
    }
    for file in "${SYSROOT}/usr/lib/kbd/consolefonts/${font}.psfu.gz" \
                "${SYSROOT}/usr/lib/kbd/consolefonts/${font}.psf.gz" \
                "${SYSROOT}/usr/lib/kbd/consolefonts/${font}.psfu" \
                "${SYSROOT}/usr/lib/kbd/consolefonts/${font}.psf"; do
        [ -r "${file}" ] && break
        file=
    done
    [ -n "${file}" ] || {
        printf 'font %s is absent from %s\n' "${font}" \
            "${SYSROOT}/usr/lib/kbd/consolefonts"
        return 1
    }
    # od 每 16 字节换一行，先用 tr 摊平再交给 read：read 只吃一行，分行时
    # 数组会只有 16 个元素，几何字段永远读不到。
    case "${file}" in
    *.gz) hdr=$(zcat "${file}" 2>/dev/null | od -An -tu1 -N32 | tr -s ' \n' ' ') ;;
    *) hdr=$(od -An -tu1 -N32 "${file}" 2>/dev/null | tr -s ' \n' ' ') ;;
    esac
    read -r -a head <<<"${hdr}"
    if [ "${#head[@]}" -ne 32 ] || [ "${head[0]}" -ne 114 ] ||
        [ "${head[1]}" -ne 181 ]; then
        printf '%s is not a PSF2 font\n' "${file}"
        return 1
    fi
    h=$(( head[24] + head[25] * 256 + head[26] * 65536 + head[27] * 16777216 ))
    w=$(( head[28] + head[29] * 256 + head[30] * 65536 + head[31] * 16777216 ))
    [ "${w}" -ge 12 ] && [ "${h}" -ge 24 ] || {
        printf 'console font %s is %sx%s, below 12x24\n' "${font}" "${w}" "${h}"
        return 1
    }
    printf 'console font %s: %sx%s\n' "${font}" "${w}" "${h}"
}

# T22 运行期控制台：默认文件只说明「下一次 grub2-mkconfig 会写出什么」，而
# HW-05 的现场是已启动的内核带着三处 console=（含 ttyAMA0），
# systemd-vconsole-setup 锁不住 /dev/console 而每轮启动失败。只查默认文件时，
# 「装完当天正常、重启后失声」会一直躲过冒烟。判据取本次启动的命令行与单元
# 状态：前者证明默认文件真的被应用，后者证明 VT 拿到了 /dev/console，两者
# 缺一都不能说明台面上的机器已经收敛。
t22_console_state() {
    local file="${SYSROOT}/proc/cmdline" line state
    need systemctl || return 1
    [ -r "${file}" ] || {
        echo "${file} unreadable"
        return 1
    }
    line=$(tr -d '\n' <"${file}")
    cons_check "${line}" /proc/cmdline || return 1
    state=$(systemctl show systemd-vconsole-setup.service -p ActiveState \
        --value 2>/dev/null)
    expect "${state}" active systemd-vconsole-setup || return 1
    t22_font_geom "${SYSROOT}/etc/vconsole.conf"
}

# T23 系统完整性：0.0.4 判据①要三个面同时干净——失败单元为 0、本次开机
# err 日志在分层口径内、实际包集合与装机时写下的交付集合差为 0。三件事各自
# 有独立证据源，只看其中一件都会漏：单元失败但日志停在 info、日志刷错但没有
# 单元失败、包被悄悄换成旧版本，都是 0.0.3 里真实发生过的形态。
#
# err 不能一刀切。基底与上游组件本身就会周期性打印 err（rtkit 拿不到实时
# 优先级、ACPI 表重复、LDAP 插件找不到 schema），在真机上消除不掉；一律判
# 失败只会让本项长期为红，失去信号价值。判定因此在 airy-observe system 内部
# 分层：产品自有单元（airymax-、airy- 前缀）的 err 必须为 0；外来条目按内容
# 去重后与 err-budget 的棘轮预算比较，超出即失败，预算随版本单调下降至 0。
#
# 判定取 airy-observe system 的 state，不在这里二次解析 systemctl 与 rpm：
# 同一套判定只能有一份实现，否则门禁与现场工具迟早各说各话。预算同样不写死
# 在脚本里，由同目录的版本化文件给出。
t23_inventory() {
    local out
    need airy-observe || return 1
    out=$(airy-observe system --manifest "${SYSROOT}/etc/airymaxos-packages" \
        --budget "${ERR_BUDGET}" --exclude "${T23_EXCLUDE}" 2>&1) || {
        printf '%s\n' "${out}"
        return 1
    }
    case " ${out} " in
    *" state=ok "*) ;;
    *)
        printf '%s\n' "${out}"
        return 1
        ;;
    esac
    # 状态干净不等于没发生过 err：外来条目在预算之内时 state 仍是 ok。
    # 只留首行计数，「foreign=2」就永远说不清是哪两条，err-budget 的棘轮
    # 只能靠猜着收紧。首行之后补上本轮 err 明细（上限 8 行，超出以一行
    # 告知剩余条数），计数与明细对得上，棘轮才有可依据的证据。
    printf '%s\n' "${out}" | head -n 1
    printf '%s\n' "${out}" | awk -v max="${T23_SHOWN}" '
        /^error / { n++; if (n <= max) print; next }
        END { if (n > max) printf "... %d more error rows\n", n - max }'
}

# T24 桌面会话收敛：T23 只回答「到现在为止有没有 err」，答不了「本轮观测里
# 组件有没有再被重新拉起」。2026-11-02 验收镜像实测：开机 4.5–8.0 s 之间
# ukui-panel 与 ukui-settings-daemon 崩溃重启二十余次，8 s 后自行停止，桌面
# 最终可用——只看单元与最终状态，这种「先乱后稳」会被全部漏掉，而它正是
# 用户看到桌面短暂闪烁、任务栏图标丢失的直接原因。
#
# 判据取本轮冒烟的首尾快照：pid 非空且逐字相同。pid 变化即进程被重新拉起，
# 无论中间隔了几秒。采样点选在冒烟首尾而不是额外 sleep，是因为覆盖窗口越长
# 越能抓住 churn，且不额外增加运行时长。
# comm 由内核按 15 字节截断（ukui-settings-daemon 实际是 ukui-settings-d，
# peony-qt-desktop 是 peony-qt-deskto），名称以 285H 实测的 /proc 名为准。
SESSION_PROCS="ukui-panel ukui-kwin_x11 ukui-settings-d peony-qt-deskto"

# churn 只说明进程被重新拉起过，说明不了它是怎么死的。本镜像的 systemd 未
# 编入 elfutils，journal 里只有「dumped core」，既没有栈也没有信号；而
# coredumpctl list 的 SIG 列取自 journal 字段、不经栈解析，是这台机器上唯一
# 可靠的死亡方式证据（SIGSEGV 与 SIGABRT 指向完全不同的根因方向）。读系统
# 日志需要特权，用 T12 已证实的免密提权；取不到就安静跳过——诊断能力不足
# 不能反过来改变判定。
core_trace() {
    local out
    command -v coredumpctl >/dev/null 2>&1 || return 0
    if ! out=$(coredumpctl list --no-pager 2>/dev/null); then
        command -v sudo >/dev/null 2>&1 || return 0
        out=$(sudo -n coredumpctl list --no-pager 2>/dev/null) || return 0
    fi
    # 首行是列名；只取最近六条，现场要的是「最近的死法」而不是全量账本。
    # 账本为空时不能落下一行空的 core:，否则诊断块里会出现没有内容的字段。
    out=$(printf '%s\n' "${out}" | grep -v '^TIME' | tail -n 6)
    [ -z "${out}" ] && return 0
    printf '%s\n' "${out}" | sed 's/^/core: /'
}

# 死法之外还要「死在哪」。内核在进程死于信号时一定打印一行段错误记录，带
# 出错地址与 ip 落在哪个库的哪个偏移（in LIB[base+off]），这条消息由内核
# 直接写 ring buffer，不经 systemd 的 ELF 解析，所以 elfutils 缺编不影响它。
# 2026-11-05 验收里 boot.log 一条 segfault 都没有，是因为 quiet 把
# console_loglevel 压到 4，而该消息属 level 4——证据一直在，只是没上串口。
#
# ASLR 每次开机更换基址，同一处崩溃的 ip/sp/库基址每次不同；去重前先抹掉这三
# 个易变字段，只留进程名、出错地址、错误码与「库内偏移」，否则二十余条同一现场
# 的记录会把诊断块占满。arm64 的措辞与 x86 不同（unhandled ... fault），一并收。
# dmesg 不可读时安静跳过：诊断能力不足不能反过来改变判定。
kern_trace() {
    local log
    log=$(dmesg 2>/dev/null) || return 0
    printf '%s\n' "${log}" \
        | grep -Ei 'segfault at|traps:|unhandled .*fault|fatal signal' \
        | sed -E -e 's/^\[[^]]*\] //' -e 's/\[[0-9]+\]:/:/' \
                 -e 's/ (ip|sp) [0-9a-f]+//g' -e 's/\[[0-9a-f]+\+/[+/' \
        | awk '!seen[$0]++' | tail -n 6 | sed 's/^/kern: /'
}

proc_pid() { # proc_pid <comm> — 取第一个同名进程的 pid，无进程则空
    pgrep -x "$1" 2>/dev/null | head -n 1
}

# 死法之外还需要「死之前说了什么」。本镜像的会话日志不在 journal 里：
# lightdm 写自己的文件，X 服务器写 Xorg 日志，会话内进程的 stderr 落
# ~/.xsession-errors。2026-11-05 的验收里 ukui-panel 在 journal 中一句输出
# 都没有，只剩一条 SIGSEGV——没有这三份文件，根因只能靠猜。
#
# 每份只取末尾若干行：串口带宽有限，诊断块淹没开机日志就等于没有诊断。
_sess_tail() { # _sess_tail <文件> — 末尾 25 行，缺文件或不可读则静默
    local out
    [ -f "$1" ] || return 0
    out=$(tail -n 25 -- "$1" 2>/dev/null)
    if [ -z "${out}" ] && command -v sudo >/dev/null 2>&1; then
        out=$(sudo -n tail -n 25 -- "$1" 2>/dev/null) || return 0
    fi
    [ -z "${out}" ] && return 0
    printf '%s\n' "${out}" | sed "s|^|sess: ${1##*/}: |"
}

sess_trace() {
    local f
    for f in /var/log/lightdm/lightdm.log /home/amuser/.xsession-errors; do
        _sess_tail "${f}"
    done
    # X 服务器的日志名带序号，取最新的一份：序号取决于还有哪些旧日志存活。
    f=$(ls -t /var/log/Xorg.*.log 2>/dev/null | head -n 1)
    [ -n "${f}" ] && _sess_tail "${f}"
    return 0
}

session_snap() { # session_snap — 核心进程 pid 快照，缺失记为 absent
    local name pid out=""
    for name in ${SESSION_PROCS}; do
        pid=$(proc_pid "${name}")
        out="${out}${out:+ }${name}=${pid:-absent}"
    done
    printf '%s\n' "${out}"
}

t24_session() {
    local now
    need pgrep || return 1
    now=$(session_snap)
    case "${now}" in
    *absent*)
        printf 'not running at end: %s\n' "${now}"
        kern_trace
        core_trace
        sess_trace
        return 1
        ;;
    esac
    [ "${now}" = "${SESSION_AT_START}" ] && {
        printf 'stable %s\n' "${now}"
        return 0
    }
    printf 'churn: start %s\n' "${SESSION_AT_START}"
    printf 'churn: end   %s\n' "${now}"
    kern_trace
    core_trace
    sess_trace
    return 1
}

# T25 桌面字体与图标：会话能起来不等于桌面能用。0.0.4 首装现场的文本全是
# 方框、面板与开始菜单图标空白，而当时的 TAP 全绿——包组只声明了会话与
# 主题，没有任何字体包，也没有图标兜底主题；字体缺失由 fontconfig 按 lang
# 静默回退（回退到同样不含汉字的西文字体），图标缺失由 Qt 静默画成空白，
# 两者都不会让会话启动失败，因此只能在装完之后按解析结果判。
#
# 判据取「解析到了什么」而不是「装了哪些包」：包在而没有字体声明 lang、
# 主题名指向不存在的目录，都是同样的坏桌面；字体来自哪个包并不重要。
# hicolor 必须单独断言：ukui 主题只覆盖自己命名的图标，第三方 .desktop 的
# 图标全部落在 hicolor 上，缺它时开始菜单与任务栏照样是空白格。
t25_desktop_assets() {
    local fam theme file

    need fc-list || return 1
    fam=$(fc-list :lang=zh-cn family 2>/dev/null | head -n 1) || {
        echo "fc-list failed"
        return 1
    }
    [ -n "${fam}" ] || {
        echo "no font declares lang=zh-cn"
        return 1
    }
    need gsettings || return 1
    theme=$(gsettings get org.ukui.style icon-theme-name 2>/dev/null) || {
        echo "org.ukui.style icon-theme-name unavailable"
        return 1
    }
    theme=${theme//\'/}
    file="${SYSROOT}/usr/share/icons/${theme}/index.theme"
    [ -s "${file}" ] || {
        echo "icon theme '${theme}' has no index.theme"
        return 1
    }
    file="${SYSROOT}/usr/share/icons/hicolor/index.theme"
    [ -s "${file}" ] || {
        echo "hicolor fallback theme missing"
        return 1
    }
    printf 'zh font: %s\nicon theme: %s\n' "${fam}" "${theme}"
}

# T26 无线固件路径：内核的 iwlwifi 只按扁平文件名取固件（modinfo -F
# firmware 列出的都是 iwlwifi-<家族>-<版本>.ucode），而 SP3 的 linux-firmware
# 已按上游新布局把 Intel Wi-Fi 固件移入 intel/iwlwifi/，顶层不留兼容链接。
# 驱动加载时逐个文件报 error -2，最后以 no suitable firmware found 收场：
# lspci 有卡、rfkill 全开、NetworkManager 却报「未发现 Wi-Fi 设备」。T19 判
# 的是内核日志，而验收跑在 QEMU 里没有 Intel 网卡，驱动根本不加载，这条缺陷
# 因此一路全绿到真机才发作。
#
# 判据与 W-N1 的 SSoT 同源：安装期 %posttrans 由 fw-flat.sh 把驱动请求名补成
# 固件根上的入口，清单 firmware-flat.list 每行「入口名 树内相对路径」。这里调
# 随镜像交付的同一个脚本 check 复核清单，测试与产品不各写一套。旧实现要求
# intel/iwlwifi/ 下每个文件在根上都有同名条目，比契约更严：该目录里只有被驱动
# 请求的那部分是内核会去取的，其余是更高 API 的现成资源，判据因此永远为负。
#
# 清单缺失说明 %posttrans 没在目标系统跑过（0.0.4 首装即此形态），失败行同时
# 带出安装期自证日志的最后一行；清单为空说明基底本身就是扁平布局，此时要求
# 根上有 iwlwifi-*.ucode。
t26_wifi_fw_layout() {
    local root="${SYSROOT}/usr/lib/firmware" out f n=0
    local tool="${SYSROOT}/usr/libexec/airymaxos/fw-flat.sh"
    local list="${SYSROOT}/usr/share/airymaxos/firmware/firmware-flat.list"
    local fwlog="${SYSROOT}/var/log/airymaxos/firmware-flat.log"

    [ -x "${tool}" ] || {
        echo "fw-flat.sh missing: ${tool}"
        return 1
    }
    if ! out=$("${tool}" check "${root}" --list "${list}" 2>&1); then
        printf '%s\n' "${out}"
        [ -r "${fwlog}" ] && tail -n 1 "${fwlog}"
        return 1
    fi
    printf '%s\n' "${out}"
    case "${out}" in
    rows=0*)
        for f in "${root}"/iwlwifi-*.ucode; do
            [ -e "${f}" ] || continue
            n=$((n + 1))
        done
        [ "${n}" -gt 0 ] || {
            echo "no iwlwifi firmware in image"
            return 1
        }
        printf 'iwlwifi flat files: %s\n' "${n}"
        ;;
    esac
}

# 现场诊断工具闭包（0.0.4 台账 P-01）：0.0.3 在 B50 与 285H 首启后网络不通，
# 现场既没有 lsusb 枚举 USB 网卡、也没有 lsof 查 socket 归属，只能靠猜。
# 四个入口按本镜像实际技术栈选取，不照抄通用清单：
#   lsusb       ← usbutils（基底 OS 仓）；USB 网卡与无线 dongle 是否被枚举
#   lsof        ← lsof（基底 OS 仓）；NetworkManager/dhclient 的 socket 归属
#   pactl       ← pulseaudio（本镜像音频栈，comps 显式声明）
#   airy-bright ← airymaxos-system（背光；基底五仓均无 brightnessctl，以
#                 filelists 实测为证，本产品自带的调节入口即闭包）
t27_field_tools() {
    local tool miss=

    for tool in lsusb lsof pactl airy-bright; do
        [ -x "${SYSROOT}/usr/bin/${tool}" ] || miss="${miss} ${tool}"
    done
    [ -z "${miss}" ] || {
        printf 'not in image:%s\n' "${miss}"
        return 1
    }
    printf 'field tools: lsusb lsof pactl airy-bright\n'
}

# 网络前端闭包（0.0.4 台账 D-08）：面板的 statusnotifier 白名单按名等待
# kylin-nm，控制中心的网络模块也由同一包提供。两者同时缺席时右下角网络
# 图标整块消失、控制中心没有网络入口，而无线本身仍然可用——只看 nmcli
# 或网络连通性会漏判，所以这里按文件判闭包。
t28_net_front() {
    local bin="${SYSROOT}/usr/bin/kylin-nm" mod
    local miss=""

    [ -x "${bin}" ] || miss=" kylin-nm"
    for mod in libnetconnect.so libwlanconnect.so libmobilehotspot.so; do
        [ -f "${SYSROOT}/usr/lib64/ukui-control-center/${mod}" ] ||
            miss="${miss} ${mod}"
    done
    [ -z "${miss}" ] || {
        printf 'not in image:%s\n' "${miss}"
        return 1
    }
    printf 'net front: kylin-nm + 3 ukcc modules\n'
}

# 计数一类 sysfs 设备，目录缺失按 0：诊断只陈述观测到的数量。
cnt_of() {
    local -a hit=()

    shopt -s nullglob
    hit=("$1"/$2)
    shopt -u nullglob
    printf '%s\n' "${#hit[@]}"
}

# 触控板的第二段判据：内核绑定不等于桌面可用。闭包里的遗留 synaptics
# 驱动（ukui-settings-daemon 的硬依赖）在 Xorg 里排在 libinput 之后，会把
# 每块触控板接走；它面对 I2C-HID 触控板拿不到压力，点击与手势全失效，
# 而 /proc/bus/input/devices 一切正常（285H 实测）。所以有 X 日志时再按
# 「谁在驱动这块板」判一次：synaptics 命中即失败，libinput 命中才通过。
t29_driver_owner() {
    local dev="$1" log="${SYSROOT}/var/log/Xorg.0.log" pad

    pad="$(sed -n 's/^N: Name="\(.*[Tt]ouchpad.*\)"$/\1/p' "${dev}" | head -1)"
    if [ ! -r "${log}" ]; then
        printf 'touchpad: input device present (X 未启动，驱动归属未判)\n'
        return 0
    fi
    if [ -n "${pad}" ] &&
        grep -qF "Using input driver 'synaptics' for '${pad}'" "${log}"; then
        printf 'touchpad: 内核已绑定，但 X 驱动为 synaptics（%s）\n' "${pad}"
        printf '%s\n' '  遗留驱动不认 I2C-HID 的压力与指宽，点击与手势会整体失效'
        printf '%s\n' '  应由 /etc/X11/xorg.conf.d/90-airymax-touchpad.conf 改派 libinput'
        return 1
    fi
    if [ -n "${pad}" ] &&
        grep -qF "'libinput' for '${pad}'" "${log}"; then
        printf 'touchpad: input device present, X 驱动 libinput\n'
        return 0
    fi
    printf 'touchpad: input device present, X 日志未见触控板驱动记录（%s）\n' \
        "${pad:-未解析到设备名}"
    return 1
}

# 触控板（0.0.4 台账 HW-02）：内建触控板挂在 ACPI 的 I2C 控制器下，由
# intel-lpss 建总线、i2c-hid 枚举。LPSS 的 PCI ID 缺项时总线根本不存在，
# 触控板无声消失，日志里也没有错误——只能按「ACPI 有硬件、输入子系统
# 无设备」判定。无此硬件的机型按能力不适用通过，不记为掩盖。
t29_touchpad() {
    local path hit=0 dev="${SYSROOT}/proc/bus/input/devices"
    local i2c hid

    for path in "${SYSROOT}"/sys/bus/acpi/devices/*/path; do
        [ -r "${path}" ] || continue
        case "$(cat "${path}")" in
        *.TPAD | *.TPD0 | *.TPD1) hit=1 ;;
        esac
    done
    if [ "${hit}" -eq 0 ]; then
        printf 'no i2c-hid touchpad in ACPI\n'
        return 0
    fi
    if grep -qi touchpad "${dev}" 2>/dev/null; then
        t29_driver_owner "${dev}"
        return
    fi
    # 失败时把链路三段的数量一并给出：0 个适配器是控制器没绑上，有适配器
    # 无 HID 设备是 i2c-hid 客户端没实例化，有 HID 设备无输入是 hid 驱动没接。
    # 三种断点对应三套修法，只报「无设备」等于让人重跑一遍同样的猜测。
    i2c="$(cnt_of "${SYSROOT}/sys/bus/i2c/devices" 'i2c-*')"
    hid="$(cnt_of "${SYSROOT}/sys/bus/hid/devices" '*')"
    printf 'ACPI 有触控板节点，输入子系统无设备（i2c 适配器 %s 个，HID 设备 %s 个）\n' \
        "${i2c}" "${hid}"
    return 1
}

# 托盘三件（0.0.4 台账 D-08 的同族）：右下角的网络、电量、音量各由一个
# 托盘进程提供，进程由 autostart 条目拉起。包在而 autostart 缺时进程不自启，
# 图标消失且没有任何日志——因此按「可执行 + autostart」双件判定。
t30_tray() {
    local pair bin unit
    local miss=""

    for pair in \
        kylin-nm:kylin-nm \
        ukui-power-manager-tray:ukui-power-manager-tray \
        ukui-volume-control-applet-qt:ukui-volume-control-applet; do
        bin="${pair%%:*}"
        unit="${pair##*:}"
        [ -x "${SYSROOT}/usr/bin/${bin}" ] || miss="${miss} ${bin}"
        [ -r "${SYSROOT}/etc/xdg/autostart/${unit}.desktop" ] ||
            miss="${miss} ${unit}.desktop"
    done
    [ -z "${miss}" ] || {
        printf 'not in image:%s\n' "${miss}"
        return 1
    }
    printf 'tray: nm, power, volume entry points present\n'
}

printf 'TAP version 14\n'
printf '1..30\n'
printf '# AirymaxOS distro smoke: target=%s date=%s\n' \
    "${TARGET}" "$(date -u '+%FT%TZ')"
printf '# ownership: budget=%s\n' "${ERR_BUDGET}"
printf '# boot=%s\n' "${BOOT_ID}"

# T24 的首快照必须在任何探测之前取：探测本身会起子进程、耗时数秒，晚取就会
# 把「开机期 churn」错当成本轮观测内的稳定，判据也就失去意义。
SESSION_AT_START=$(session_snap)

probe 1 "T1 ukui x11 session" t1_x11
probe 2 "T2 ibus input method" t2_ime
probe 3 "T3 pulseaudio stack" t3_audio
probe 4 "T4 desktop slice" t4_slice
probe 5 "T5 built-in wallpaper" t5_wallpaper
probe 6 "T6 kernel identity" t6_kernel_identity
probe 7 "T7 lsm registry" t7_lsm_registry
probe 8 "T8 product hostname" t8_hostname
probe 9 "T9 release brand" t9_brand
probe 10 "T10 display mode policy" t10_display
probe 11 "T11 efi boot brand" t11_efi_brand
probe 12 "T12 passwordless elevation" t12_passwordless
probe 13 "T13 passwordless desktop" t13_passwordless_desktop
probe 14 "T14 installed dnf sources" t14_repos
probe 15 "T15 durable boot arguments" t15_boot_args
probe 16 "T16 observer tools selfcheck" t16_obs_tools
probe 17 "T17 system disk layout" t17_disk_layout
probe 18 "T18 build provenance" t18_build_id
probe 19 "T19 firmware blob present" t19_fw_blob
probe 20 "T20 cpu microcode loaded" t20_fw_microcode
probe 21 "T21 firmware api match" t21_fw_api
probe 22 "T22 runtime console state" t22_console_state
probe 23 "T23 system inventory" t23_inventory
probe 24 "T24 desktop session steady" t24_session
probe 25 "T25 desktop fonts and icons" t25_desktop_assets
probe 26 "T26 wireless firmware layout" t26_wifi_fw_layout
probe 27 "T27 field diagnostic tools" t27_field_tools
probe 28 "T28 network front closure" t28_net_front
probe 29 "T29 builtin touchpad" t29_touchpad
probe 30 "T30 tray entry points" t30_tray

printf '# summary: pass=%d fail=%d\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ]
