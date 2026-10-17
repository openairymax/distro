#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-lint.sh — distro 仓库静态门禁
#
# 职责：
#   1. 校验 specs/ 下所有 RPM 配方（tools/spec_lint.py，E001~E014）；
#   2. 运行 tools/tests 下的规则回归测试。
#
# 只依赖 python3 标准库，可在无 rpmbuild/mock 的机器上执行。CI 与本地提交
# 前共用同一入口，避免两套口径。
# ===========================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${HERE}")"

cd "${ROOT}"

echo "== spec lint =="
python3 tools/spec_lint.py

echo "== tool tests =="
if python3 -c 'import pytest' >/dev/null 2>&1; then
    python3 -m pytest -q tools/tests
else
    python3 -m unittest discover -s tools/tests -p 'test_*.py'
fi

echo "== lint passed =="
