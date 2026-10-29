#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# airy_record.sh — 桌面会话原生录屏（安装为 /usr/bin/airy-record）
#
# 为什么要内置：AirymaxOS 的验收证据此前只有串口标记行与 journal，能证明
# 「单元起来了」，却证明不了「画面动起来了」。外部录屏依赖在目标机上临时
# 装工具、手抄 DISPLAY，既不可复现也不可审计。这里只依赖 ffmpeg 与 X11，
# 用同一个入口在任意机器上产出带校验和的成片。
#
# 采集链路：x11grab 直读 X server（不经过任何合成器私有接口，UKUI/Xorg 下
# 通用）；音频取 PulseAudio 默认 sink 的 monitor，而不是麦克风——要录的是
# 系统自己在放什么。sink 不存在时降级为无声录制，绝不静默生成一个空文件。
#
# 输出必须偶数宽高：libx264 的 yuv420p 对奇数尺寸直接拒绝，x11grab 在
# 奇数宽度屏幕上会给出奇数帧。统一过一次 pad 滤镜，比在每处调用点判断
# 尺寸更可靠。
#
# 全程可观测：-progress 写的是文件而不是 stderr，主进程每 2 秒解析一次并
# 输出 progress 行，屏幕不会在录制期间静止；结束行带 path/frames/size/
# sha256，可直接与宿主机比对。失败输出 fail reason=，退出码非零。
#
# --check 是能力自检：报告 ffmpeg 版本、x11grab 是否编入、能否找到会话、
# 当前分辨率与音频源，任一项缺失即 status=degraded 并以非零退出，避免
# 在自动化里把「装不了」误当成「录好了」。
#
# 依赖：ffmpeg、xrandr、pactl（可选）、loginctl。
# ===========================================================================

set -u

MARK=AIRYMAX-RECORD
PAD='pad=ceil(iw/2)*2:ceil(ih/2)*2'
DUR=10
FPS=15
SIZE=
AUDIO=auto
OUT=
CHECK=0
frames=0
pid=
self=$(readlink -f "$0" 2>/dev/null) || self=$0
case $self in
*/*) ;;
*) self=./$self ;;
esac
LIB=${self%/*}/session_env.sh

say() {
    printf '%s %s\n' "$MARK" "$*"
}

fail() {
    printf '%s fail reason=%s\n' "$MARK" "$1" >&2
    exit 1
}

usage() {
    cat <<'EOF'
用法: airy-record [选项]
  --duration N   录制秒数（默认 10）
  --fps N        帧率（默认 15）
  --size WxH     采集尺寸（默认取当前会话的分辨率）
  --audio        强制录系统声音，找不到音频源即失败
  --no-audio     只录画面
  --out PATH     输出文件（默认 ~/airymaxos-record-<时间>.mkv）
  --check        只做能力自检，不录制
  -h, --help     显示本帮助
EOF
}

valid_num() {
    case $1 in
    '' | *[!0-9]*) return 1 ;;
    esac
}

need_ffmpeg() {
    command -v ffmpeg >/dev/null 2>&1 || fail no-ffmpeg
}

# 当前连接显示器的模式：xrandr 里 "1920x1080+0+0" 这类字段就是活动模式。
screen_size() {
    command -v xrandr >/dev/null 2>&1 || return 1
    xrandr --query 2>/dev/null | awk '
        / connected/ {
            for (i = 1; i <= NF; i++)
                if ($i ~ /^[0-9]+x[0-9]+\+/) {
                    sub(/\+.*/, "", $i)
                    print $i
                    exit
                }
        }'
}

# monitor 源的名字恒为 <sink>.monitor；sink 名随硬件变化，不能写死。
audio_sink() {
    command -v pactl >/dev/null 2>&1 || return 1
    sink=$(pactl get-default-sink 2>/dev/null) || return 1
    [ -n "$sink" ] || return 1
    pactl list short sources 2>/dev/null |
        awk -v want="${sink}.monitor" '$2 == want { print $2; exit }'
}

x11grab_ready() {
    ffmpeg -hide_banner -devices 2>/dev/null |
        awk '$2 == "x11grab" { found = 1 } END { exit !found }'
}

check_report() {
    status=ok
    ver=$(ffmpeg -version 2>/dev/null |
        sed -n '1s/^ffmpeg version \([^ ]*\).*/\1/p')
    say "check ffmpeg=${ver:-absent}"
    [ -n "$ver" ] || status=degraded
    if x11grab_ready; then
        say 'check x11grab=present'
    else
        say 'check x11grab=absent'
        status=degraded
    fi
    if airy_session_env; then
        say "check session=${DISPLAY}"
        say "check xauthority=${XAUTHORITY}"
        size=$(screen_size) || size=absent
        say "check display=${size}"
        [ "$size" != absent ] || status=degraded
    else
        say 'check session=absent'
        status=degraded
    fi
    src=$(audio_sink) || src=none
    say "check audio=${src}"
    say "check status=${status}"
    [ "$status" = ok ]
}

# 进度文件是行的集合，每次只取最后一次出现的键：ffmpeg 追加写，末尾最新。
tick() {
    us=$(sed -n 's/^out_time_us=//p' "$prog" 2>/dev/null | tail -n 1)
    [ -n "$us" ] ||
        us=$(sed -n 's/^out_time_ms=//p' "$prog" 2>/dev/null | tail -n 1)
    [ -n "$us" ] || us=0
    frames=$(sed -n 's/^frame=//p' "$prog" 2>/dev/null | tail -n 1)
    [ -n "$frames" ] || frames=0
    sz=$(sed -n 's/^total_size=//p' "$prog" 2>/dev/null | tail -n 1)
    [ -n "$sz" ] || sz=0
    say "progress elapsed=$((us / 1000000))s frames=${frames} size=${sz}"
}

abort() {
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    say "stop path=${OUT} aborted=1"
    exit 130
}

record() {
    prog=$(mktemp) || fail no-tmp
    err=${prog}.err
    trap 'rm -f "$prog" "$err"' EXIT
    set -- -hide_banner -nostdin -loglevel error -y \
        -f x11grab -framerate "$FPS" -video_size "$SIZE" -i "${DISPLAY}.0"
    if [ -n "${sink}" ]; then
        set -- "$@" -f pulse -i "${sink}"
    fi
    set -- "$@" -t "$DUR" -vf "$PAD" -c:v libx264 -preset veryfast -crf 23 \
        -pix_fmt yuv420p -progress "$prog" -nostats -f matroska "$OUT"
    say "start path=${OUT} size=${SIZE} fps=${FPS} duration=${DUR} audio=${sink:-none}"
    ffmpeg "$@" >/dev/null 2>"$err" &
    pid=$!
    trap 'abort' INT TERM
    while kill -0 "$pid" 2>/dev/null; do
        sleep 2
        tick
    done
    wait "$pid"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        reason=$(tail -n 1 "$err" 2>/dev/null)
        fail "ffmpeg-rc=${rc} ${reason:-no-detail}"
    fi
    bytes=$(wc -c <"$OUT")
    sum=$(sha256sum "$OUT" | cut -d' ' -f1)
    say "stop path=${OUT} frames=${frames} size=${bytes} seconds=${DUR} sha256=${sum}"
}

main() {
    [ -r "$LIB" ] || fail no-session-lib
    # shellcheck source=session_env.sh
    . "$LIB"
    # 自检不预先要求 ffmpeg：缺它正是要报告出来的结论（status=degraded），
    # 在进入报告前就退出会让调用方拿不到任何一行证据。
    if [ "$CHECK" -eq 1 ]; then
        check_report
        return
    fi
    need_ffmpeg
    airy_session_env || fail no-session
    [ -n "$SIZE" ] || SIZE=$(screen_size) || fail no-size
    sink=
    [ "$AUDIO" = off ] || sink=$(audio_sink) || sink=
    [ "$AUDIO" = forced ] && [ -z "$sink" ] && fail no-audio-source
    [ -n "$OUT" ] || OUT=${HOME}/airymaxos-record-$(date +%Y%m%d-%H%M%S).mkv
    record
}

while [ $# -gt 0 ]; do
    case $1 in
    --duration)
        valid_num "${2:-}" || fail "bad-duration=${2:-}"
        DUR=$2
        shift 2
        ;;
    --fps)
        valid_num "${2:-}" || fail "bad-fps=${2:-}"
        FPS=$2
        shift 2
        ;;
    --size)
        SIZE=${2:-}
        [ -n "$SIZE" ] || fail bad-size
        shift 2
        ;;
    --audio)
        AUDIO=forced
        shift
        ;;
    --no-audio)
        AUDIO=off
        shift
        ;;
    --out)
        OUT=${2:-}
        [ -n "$OUT" ] || fail bad-out
        shift 2
        ;;
    --check)
        CHECK=1
        shift
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        fail "unknown-arg=$1"
        ;;
    esac
done

main
