#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# gen-lockfile.sh — 在冻结环境生成 rpm lockfile
#
# 用法:
#   ./gen-lockfile.sh <冻结点标签>
#   例: ./gen-lockfile.sh openEuler-24.03-LTS-SP2-20260915
#
# 前置条件:
#   - 在发布工作区执行（严禁在 airymaxhub 源码区内构建/联网生成）
#   - 环境内可访问冻结源仓库（OS/update/EPOL/main/EPOL/update/main/
#     everything/airymax-os）
#   - 已安装: python3 + pip 包 rpm-lockfile-prototype（konflux 工具链）
#
# 产出:
#   覆写本目录 lockfile-openEuler-24.03-LTS-SP2.yaml 的 packages 段
# ===========================================================================
set -euo pipefail

SNAPSHOT="${1:?用法: gen-lockfile.sh <冻结点标签>，例如 openEuler-24.03-LTS-SP2-20260915}"
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${HERE}/lockfile-openEuler-24.03-LTS-SP2.yaml"

command -v rpm-lockfile-prototype >/dev/null 2>&1 || {
    echo "错误: 缺少 rpm-lockfile-prototype（pip install rpm-lockfile-prototype）" >&2
    exit 1
}

# 项目仓库定义（与运行期 /etc/yum.repos.d/airymaxos.repo 同源）
REPOFILE="${HERE}/../repo/airymax-os.repo"
[ -f "$REPOFILE" ] || {
    echo "错误: 缺少 ${REPOFILE}，先补齐仓库定义再生成" >&2
    exit 1
}

echo "[1/3] 冻结点标签: ${SNAPSHOT}"
echo "[2/3] 生成 lockfile（覆盖 ${OUT} 的 packages 段）..."
# rpm-lockfile-prototype 以 .repo 文件为内容源，解析 comps 组闭包并锁定 EVR
# 注意: 其调用方式随上游版本演进，此处保留显式命令便于评审 diff
(
    cd "$HERE"
    rpm-lockfile-prototype "$REPOFILE" \
        --outfile "lockfile-openEuler-24.03-LTS-SP2.yaml.tmp"
    # TODO: 校验生成结果包含 comps 三组 + environment 的全部必装包
    # TODO: 与上一冻结点 diff 并输出 增/升/删 三段摘要供 PR 评审
)

echo "[3/3] 回填元数据..."
{
    echo "# 冻结点: ${SNAPSHOT}"
    echo "# 生成器: gen-lockfile.sh（rpm-lockfile-prototype）"
    echo "# 生成时间: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "# 滚动流程: 见本目录 README.md（单独 PR + 全量评审 + CI 冒烟）"
    cat "lockfile-openEuler-24.03-LTS-SP2.yaml.tmp"
    rm -f "lockfile-openEuler-24.03-LTS-SP2.yaml.tmp"
} > "$OUT"

echo "完成: ${OUT}"
echo "下一步: 提交单独 PR，全量人工评审 diff，跑 ci/run-smoke.sh 组合冒烟"
