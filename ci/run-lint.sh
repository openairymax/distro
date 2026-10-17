#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-lint.sh — distro 仓库静态门禁
#
# 职责：
#   1. bash -n 解析 ci/、lockfile/、scripts/ 下的 shell 入口；
#   2. 校验 specs/ 下所有 RPM 配方（tools/spec_lint.py，E001~E014）；
#   3. 校验 comps/ 下包组定义（tools/comps_lint.py，C001~C009），并在
#      具备 xmllint 时按 comps/comps.dtd 做 DTD 校验；
#   4. 运行 tools/tests 下的规则回归测试。
#
# 只依赖 python3 标准库，可在无 rpmbuild/mock 的机器上执行。CI 与本地提交
# 前共用同一入口，避免两套口径。
# ===========================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${HERE}")"

cd "${ROOT}"

echo "== shell syntax =="
while IFS= read -r script; do
    bash -n "${script}"
done < <(find ci lockfile scripts -type f -name '*.sh' | sort)

echo "== spec lint =="
python3 tools/spec_lint.py

echo "== comps lint =="
python3 tools/comps_lint.py
if command -v xmllint >/dev/null 2>&1; then
    while IFS= read -r comps; do
        xmllint --noout --nonet --valid "${comps}"
    done < <(find comps -type f -name '*.xml' | sort)
else
    echo "xmllint unavailable: DTD validation deferred to image CI" >&2
fi

echo "== tool tests =="
if python3 -c 'import pytest' >/dev/null 2>&1; then
    python3 -m pytest -q tools/tests
else
    python3 -m unittest discover -s tools/tests -p 'test_*.py'
fi

echo "== lint passed =="
