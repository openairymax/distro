#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# 70-airymax-ukui-policy.sh — UKUI 桌面集成策略安装脚本
#
# 职责（对应 desktop/README.md 决策 2/3/4 + 默认壁纸）：
#   1. 屏蔽桌面自带 AI 控制面（kylin-ai* 服务族）——agent 入口唯一 = Gateway
#   2. 写入输入法环境变量（fcitx5）
#   3. 确保 X11 会话为默认（Wayland 二期前不改默认）
#   4. 安装 AirymaxOS 默认壁纸并设为系统背景默认值
#
# 部署：随 airymaxos-release 包安装到
#   /usr/share/airymaxos/distro/desktop/70-airymax-ukui-policy.sh
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

# ---------------------------------------------------------------------------
# 4) 默认壁纸（AirymaxOS 品牌壁纸）
#    资产随 airymaxos-release 包落在本目录 wallpaper/ 下（distro/desktop/
#    wallpaper/airymaxos-default.jpg）。此处安装到发行版标准路径，注册到
#    系统壁纸选择器，并经 glib schema override 设为系统背景默认值。
#    TODO 首个冻结点核对 UKUI 4.x 背景 schema 名与键名（与 desktop/README.md
#    TODO 表联动）；下文先按 org.ukui.background 落地。
# ---------------------------------------------------------------------------
AIRY_WP_SRC="/usr/share/airymaxos/distro/desktop/wallpaper/airymaxos-default.jpg"
AIRY_WP_DIR="/usr/share/backgrounds/airymaxos"
AIRY_WP_DST="${AIRY_WP_DIR}/airymaxos-default.jpg"

if [ -f "${AIRY_WP_SRC}" ]; then
    install -d -m 0755 "${AIRY_WP_DIR}"
    install -m 0644 "${AIRY_WP_SRC}" "${AIRY_WP_DST}"

    # 4a) 注册到系统壁纸选择器（peony/UKUI 读取 gnome-background-properties）
    install -d -m 0755 /usr/share/gnome-background-properties
    cat > /usr/share/gnome-background-properties/airymaxos-wallpapers.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE wallpapers SYSTEM "gnome-wp-list.dtd">
<wallpapers>
  <wallpaper deleted="false">
    <name>AirymaxOS Default</name>
    <filename>/usr/share/backgrounds/airymaxos/airymaxos-default.jpg</filename>
    <options>zoom</options>
  </wallpaper>
</wallpapers>
EOF
    chmod 0644 /usr/share/gnome-background-properties/airymaxos-wallpapers.xml
    echo "[airymax-ukui-policy] wallpaper installed: ${AIRY_WP_DST}"

    # 4b) 设为系统背景默认值（glib schema override，compile 后新会话生效）
    install -d -m 0755 /usr/share/glib-2.0/schemas
    cat > /usr/share/glib-2.0/schemas/99-airymaxos-default.gschema.override <<'EOF'
[org.ukui.background]
picture-filename='/usr/share/backgrounds/airymaxos/airymaxos-default.jpg'
picture-options='zoom'
EOF
    chmod 0644 /usr/share/glib-2.0/schemas/99-airymaxos-default.gschema.override
    if command -v glib-compile-schemas >/dev/null 2>&1; then
        glib-compile-schemas /usr/share/glib-2.0/schemas || true
    fi
    echo "[airymax-ukui-policy] default background set via gschema override"
else
    echo "[airymax-ukui-policy] WARN: wallpaper asset not found: ${AIRY_WP_SRC}" >&2
fi

echo "[airymax-ukui-policy] done."
