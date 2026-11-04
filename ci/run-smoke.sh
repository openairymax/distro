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
#                       T18 与 T23 读取 /run、/usr/share、/boot、/sys、/etc 下
#                       的运行态标记、发行版标识与资产，单测在沙箱里用该前缀复核
#                       判定，装机现场保持默认值。T17 读实时块层，不经该前缀。
#   AIRYMAX_SMOKE_BUILD_ID  发布清单记录的构建来源指纹。给出时要求与本机
#                       BUILD_ID 逐字相同，把「装的是这一轮产出的镜像」变成
#                       可判定事实；缺省只校验机内两处一致。
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
#   T10 分辨率：每个 connected 输出处于 display_mode.sh 定义的策略模式
#   T11 EFI 品牌：ESP 内 airymaxos 目录是完整签名套件，BootOrder 首位为本产品
#   T12 免密提权：交付账户能以 NOPASSWD 完成一次非交互提权
#   T13 免密桌面：空闲锁屏关闭，交付账户在 nopasswdlogin 组内
#   T14 运行期软件源：已安装系统的每个启用段都指向可解析的基底镜像
#   T15 启动参数：/etc/default/grub 持有 rhgb quiet，os-prober 已关闭
#   T16 观测工具：airy-bench / airy-observe / airy-demo 随镜像交付且自检为 ok
#   T17 系统盘布局：/ 与 /data 各挂在一个分区上，且不是同一个分区
#   T18 构建来源：os-release 的 BUILD_ID 与 /etc/airymaxos-build 逐字相同，
#       字符集与长度符合驱动写入口径；给出期望值时还要求两者相同
#   T19–T21 固件：内核日志里没有「固件表无匹配」「微码 INIT 未运行」
#       「API 版本越界」三条失败签名
#   T22 运行期控制台：本次启动的命令行与默认文件同源，systemd-vconsole-setup
#       未失败
#   T23 系统完整性：失败单元、本次开机 err 日志与包集合对账三面全干净
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
START_WAIT="${AIRYMAX_SMOKE_WAIT:-30}"
HOSTNAME_WANT="${AIRYMAX_SMOKE_HOST:-airymax-pc}"
SYSROOT="${AIRYMAX_SMOKE_ROOT:-}"

PASS=0
FAIL=0

tap_ok() {
    printf 'ok %s - %s\n' "$1" "$2"
    PASS=$((PASS + 1))
}

tap_fail() {
    printf 'not ok %s - %s\n' "$1" "$2"
    if [ -n "${3:-}" ]; then
        printf '#   %s\n' "$3"
    fi
    FAIL=$((FAIL + 1))
}

probe() { # probe <编号> <名称> <探测函数>
    local id="$1" name="$2" out rc
    shift 2
    out="$("$@" 2>&1)"
    rc=$?
    if [ "${rc}" -eq 0 ]; then
        [ -n "${out}" ] && printf '#   %s\n' "${out}"
        tap_ok "${id}" "${name}"
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

seat_marker() { # seat_marker — 校验 xserver.log 的标记与 X 实况一致
    local log="${SYSROOT}/run/airymaxos/xserver.log" line drv conf argv out

    [ -r "${log}" ] || {
        echo "xserver marker missing: ${log}"
        return 1
    }
    line=$(sed -n 's/^AIRYMAX-XSERVER //p' "${log}" | tail -n 1)
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
t4_slice() {
    need systemctl || return $?
    local tasks
    expect "$(systemctl show "user@${UID}.service" -p Slice --value 2>/dev/null)" \
        airymax-desktop.slice "user@ service slice" || return 1
    expect "$(systemctl is-active airymax-desktop.slice 2>/dev/null)" \
        active "slice state" || return 1
    expect "$(slice_prop CPUWeight)" 50 "slice CPUWeight" || return 1
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
    local file="${SYSROOT}/etc/os-release" ver pretty dist
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
    # NAME 是给人读的完整名（按 0.0.4 口径含中文），只要求以同一短名起头：
    # 两处品牌面仍是同一个词根，底座名（openEuler）在此判失败。
    expect_prefix "$(os_rel NAME)" "${dist}" "os-release NAME" || return 1
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
        printf 'report=%s\n' "$("${script}" --report 2>&1 | tr '\n' ';')"
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
# 期望按剖面分：桌面剖面要 rhgb quiet，最小剖面不要——那会把无图形系统唯一
# 可用的串口日志藏进 splash。剖面按显示管理器是否在位判定。
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
    # 启动画面参数只属于桌面剖面：最小剖面不装图形，rhgb quiet 只会把唯一
    # 可用的串口日志藏起来。剖面按显示管理器是否在位判定，与配方里的差异
    # 同源；两个剖面共同要求的是控制台集合与菜单范围（D-30）。
    if [ -e "${SYSROOT}/usr/bin/lightdm" ]; then
        for tok in rhgb quiet; do
            case " ${line} " in
            *" ${tok} "*) continue ;;
            esac
            printf '%s: GRUB_CMDLINE_LINUX lacks %s\n' "${file}" "${tok}"
            return 1
        done
    fi
    cons_check "${line}" GRUB_CMDLINE_LINUX || return 1
    t15_brand_cfg || return 1
    grep -qxF 'GRUB_DISABLE_OS_PROBER=true' "${file}" || {
        echo "${file}: os-prober not disabled"
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

t21_fw_api() {
    fw_clean 'api flags index [0-9]+ larger' 'a firmware API mismatch'
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
    expect "${state}" active systemd-vconsole-setup
}

# T23 系统完整性：0.0.4 判据①要三个面同时干净——失败单元为 0、本次开机
# err 日志为 0、实际包集合与装机时写下的交付集合差为 0。三件事各自有独立
# 证据源，只看其中一件都会漏：单元失败但日志停在 info、日志刷错但没有单元
# 失败、包被悄悄换成旧版本，都是 0.0.3 里真实发生过的形态。
# 判定取 airy-observe system 的 state，不在这里二次解析 systemctl 与 rpm：
# 同一套判定只能有一份实现，否则门禁与现场工具迟早各说各话。
t23_inventory() {
    local out
    need airy-observe || return 1
    out=$(airy-observe system --manifest "${SYSROOT}/etc/airymaxos-packages" \
        2>&1) || {
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
    printf 'units=0 errors=0 packages=ok\n'
}

printf 'TAP version 14\n'
printf '1..23\n'
printf '# AirymaxOS distro smoke: target=%s date=%s\n' \
    "${TARGET}" "$(date -u '+%FT%TZ')"

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

printf '# summary: pass=%d fail=%d\n' "${PASS}" "${FAIL}"
[ "${FAIL}" -eq 0 ]
