#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# gen-lockfile.sh — 在冻结环境生成 rpms.lock.yaml
#
# 用法:
#   ./gen-lockfile.sh <冻结点标签>
#   例: ./gen-lockfile.sh openEuler-24.03-LTS-SP2-20260915
#
# 前置条件:
#   - 在发布工作区执行（严禁在 airymaxhub 源码区内联网生成）
#   - 已安装 rpm-lockfile-prototype（konflux 工具链，依赖 python3-dnf 与 rpm）
#   - 可访问 rpms.in.yaml 列出的上游仓库
#
# 步骤: 解析闭包 → comps 覆盖校验 → 与既有冻结集对比 → 原子落盘
# 输入 rpms.in.yaml 是唯一的仓库与包名来源；本脚本不重复声明任何仓库。
# ===========================================================================
set -euo pipefail

SNAPSHOT="${1:?用法: gen-lockfile.sh <冻结点标签>，例如 openEuler-24.03-LTS-SP2-20260915}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${HERE}")"
IN="${HERE}/rpms.in.yaml"
OUT="${HERE}/rpms.lock.yaml"
COMPS="${ROOT}/comps/airymaxos-comps.xml"
ENV_ID="airymax-workstation"

die() { echo "错误: $*" >&2; exit 1; }

command -v rpm-lockfile-prototype >/dev/null 2>&1 ||
    die "缺少 rpm-lockfile-prototype（pip install rpm-lockfile-prototype）"
[ -f "${IN}" ] || die "缺少输入 ${IN}"
[ -f "${COMPS}" ] || die "缺少 comps ${COMPS}"

BODY="$(mktemp "${OUT}.body.XXXXXX")"
FULL="$(mktemp "${OUT}.full.XXXXXX")"
trap 'rm -f "${BODY}" "${FULL}"' EXIT

echo "[1/4] 解析上游闭包: ${SNAPSHOT}"
( cd "${HERE}" && rpm-lockfile-prototype --outfile "${BODY}" rpms.in.yaml )

echo "[2/4] 校验 comps 必装包覆盖"
python3 "${HERE}/lock_check.py" verify \
    --comps "${COMPS}" --lock "${BODY}" --environment "${ENV_ID}"

echo "[3/4] 与既有冻结集对比"
if [ -f "${OUT}" ]; then
    python3 "${HERE}/lock_check.py" diff --old "${OUT}" --new "${BODY}"
else
    echo "无既有 ${OUT}，本次为首个冻结点"
fi

echo "[4/4] 写入 ${OUT}"
{
    echo "# 冻结点: ${SNAPSHOT}"
    echo "# 生成器: gen-lockfile.sh / rpm-lockfile-prototype"
    echo "# 生成时间: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "# 输入: rpms.in.yaml（改动输入后必须重新生成本文件）"
    echo "# 流程: 见 README.md（单独 PR + 全量 diff 评审 + CI 组合冒烟）"
    cat "${BODY}"
} > "${FULL}"
mv -f "${FULL}" "${OUT}"

echo "完成: ${OUT}"
