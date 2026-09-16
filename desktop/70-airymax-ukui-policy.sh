#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# 70-airymax-ukui-policy.sh — UKUI 桌面集成策略安装脚本
#
# 职责（对应 desktop/README.md 决策 2/3/4）：
#   1. 屏蔽桌面自带 AI 控制面（kylin-ai* 服务族）——agent 入口唯一 = Gateway
#   2. 写入输入法环境变量（fcitx5）
#   3. 确保 X11 会话为默认（Wayland 二期前不改默认）
#
# 部署：随 airymaxos-release 包安装到
#   /usr/share/airymax/distro/desktop/70-airymax-ukui-policy.sh
# 调用：kickstart %post 或 RPM %post（幂等，可重复执行）
# ===========================================================================
set -euo pipefail

echo "[airymax-ukui-policy] applying desktop integration policy..."

# ---------------------------------------------------------------------------
# 1) 屏蔽桌面 AI 控制面
#    通配 mask 由显式清单兜底：mask 需要具体 unit 名，此处先列 openKylin
#    常见名，TODO 首个冻结点按实际仓库包名修订清单（与 desktop/README.md
#    TODO 表联动）。
# ---------------------------------------------------------------------------
for unit in \
    kylin-ai-daemon.service \
    kylin-ai-plugin-manager.service \
    kylin-ai-vision.service \
    kylin-ai-assistant.service
do
    if systemctl list-unit-files "${unit}" >/dev/null 2>&1; then
        systemctl disable --now "${unit}" 2>/dev/null || true
        systemctl mask "${unit}" 2>/dev/null || true
        echo "[airymax-ukui-policy] masked: ${unit}"
    fi
done

# ---------------------------------------------------------------------------
# 2) 输入法环境（fcitx5；TODO 冻结点核对后与 comps 保持同步）
# ---------------------------------------------------------------------------
install -d -m 0755 /etc/profile.d
cat > /etc/profile.d/airymax-im.sh <<'EOF'
# AirymaxOS input method environment (fcitx5)
export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
export SDL_IM_MODULE=fcitx
export GLFW_IM_MODULE=ibus
EOF
chmod 0644 /etc/profile.d/airymax-im.sh
echo "[airymax-ukui-policy] input method env written: /etc/profile.d/airymax-im.sh"

# ---------------------------------------------------------------------------
# 3) 会话默认：graphical.target（X11 优先）
# ---------------------------------------------------------------------------
systemctl set-default graphical.target
echo "[airymax-ukui-policy] default target = graphical.target"

echo "[airymax-ukui-policy] done."
