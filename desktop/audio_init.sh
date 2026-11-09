#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# audio_init.sh — 首次开机的声卡混音器初始化
#
# 为什么需要它：HDA 编解码器上电后功放停在索引 0，Master 即 0/87
# （-65 dB），Playback Switch 为 off；上游 /lib/alsa/init/hda 只白名单两台
# 旧笔记本，其余硬件走通用方法，而通用方法只由 `alsactl init` 显式调用。
# alsa-state.service 在 rdaemon 模式下只做恢复：状态文件不存在时它不动
# 混音器（285H 实测：移走 asound.state 后重启该单元，Master 仍是 30/off）。
# 于是首启的静音被写入 asound.state 固化，PulseAudio 再把硬件 0/off 读成
# 0% + muted 存进用户态 device-volumes，"开箱没声音"因此跨重启存在。
#
# 触发时机由 airymax-audio-init.service 的 ConditionPathExists 保证：状态
# 文件不存在才执行，即首启一次；此后用户音量由 alsa-state 保存与恢复，本
# 脚本不再介入，不会覆盖用户设置。跨架构：初始化完全走 alsa-utils 的通用
# 方法，不针对任何编解码器，ARM 与 RISC-V 同一条路径。
#
# 失败口径：没有声卡是正常（虚拟机、服务器档位），退出 0；有声卡但初始化
# 或落盘失败时，标记走 stderr 进 console 与 journal，并以 1 退出，使
# systemctl --failed 与九阶段记账都看得见。
#
# 部署：airymaxos-release 安装到 /usr/lib/airymaxos/desktop/。
# 依赖：bash、alsa-utils。
# ===========================================================================

CARD_ROOT="${AIRYMAX_CARD_ROOT:-/proc/asound}"
ALSACTL="${AIRYMAX_ALSACTL:-/usr/sbin/alsactl}"

say()
{
    printf 'AIRYMAX-AUDIO %s\n' "$*"
}

warn()
{
    printf 'AIRYMAX-AUDIO %s\n' "$*" >&2
}

# 声卡编号取自 /proc/asound 的 card* 目录：它与 alsactl 的卡号同一索引，
# 不解析 cards 文件里的自由文本（编解码器名含空格与引号）。
cards()
{
    local node

    for node in "${CARD_ROOT}"/card[0-9]*; do
        [ -d "${node}" ] || continue
        printf '%s\n' "${node##*/card}"
    done
}

# 退出码 99 是 alsa-utils 的「通用方法已生效」，与 0（编解码器专用初始化
# 文件命中）同为成功；把它当失败会让每台非白名单机器在首启就报错。
init_one()
{
    local idx=$1 rc=0

    "${ALSACTL}" init "${idx}" >/dev/null 2>&1 || rc=$?
    if [ "${rc}" -ne 0 ] && [ "${rc}" -ne 99 ]; then
        warn "card=${idx} action=init result=fail rc=${rc}"
        return 1
    fi
    say "card=${idx} action=init result=ok rc=${rc}"
}

main()
{
    local idx list n=0 bad=0

    list=$(cards)
    if [ -z "${list}" ]; then
        say 'result=absent cards=0'
        return 0
    fi
    for idx in ${list}; do
        n=$((n + 1))
        init_one "${idx}" || bad=1
    done
    if [ "${bad}" -ne 0 ]; then
        warn "result=failed cards=${n}"
        return 1
    fi
    if ! "${ALSACTL}" store >/dev/null 2>&1; then
        warn "result=failed cards=${n} action=store"
        return 1
    fi
    say "result=done cards=${n}"
}

main "$@"
