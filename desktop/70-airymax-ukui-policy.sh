#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# 70-airymax-ukui-policy.sh — UKUI 桌面运行期策略
#
# 只执行装配完成后才能确定的动作：屏蔽桌面自带 AI 控制面单元。静态资产
# （lightdm 座位、会话输入法环境、输入法自启、壁纸与背景默认值、slice
# drop-in）由 airymaxos-release 包直接安装到最终路径，本脚本不再复制，避免
# 同一路径出现两处事实来源。默认 target 由各剖面 kickstart 的 %post 唯一
# 设定（workstation → graphical.target，minimal → multi-user.target），
# 本脚本不介入，避免同一事实两处来源。
#
# 部署：airymaxos-release 包安装到 /usr/share/airymaxos/distro/desktop/。
# 调用：该包 %post。离线（安装器 chroot）与在线系统均可执行，幂等；
# 屏蔽属单元文件操作，一律走 --root 离线语义，不依赖 systemd 总线。
# ===========================================================================
set -euo pipefail

# openEuler 24.03 LTS-SP2 冻结点不含 kylin-ai 包族（kickstart 已用
# -kylin-ai* 排除）。清单保留为防御式约束：若上游以后引入同名单元，
# 屏蔽动作仍然生效，保证 agent 控制面唯一入口是 Gateway。
AIRY_AI_UNITS="kylin-ai-daemon.service
kylin-ai-plugin-manager.service
kylin-ai-vision.service
kylin-ai-assistant.service"

unit_exists()
{
    local unit="$1"
    local dir

    for dir in /etc/systemd/system /usr/lib/systemd/system; do
        if [ -e "${dir}/${unit}" ]; then
            return 0
        fi
    done
    return 1
}

for unit in ${AIRY_AI_UNITS}; do
    if ! unit_exists "${unit}"; then
        continue
    fi
    systemctl --root=/ disable "${unit}"
    systemctl --root=/ mask "${unit}"
    echo "[airymax-policy] masked ${unit}"
done
