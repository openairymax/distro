#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-lint.sh — distro 仓库静态门禁
#
# 职责：
#   1. bash -n 解析 ci/、lockfile/、scripts/、desktop/、tools/、boot/ 下的
#      shell 入口，以及 scripts/lib 下被 source 的 *.env（判负证据集等共用
#      数据）；desktop/xinitrc.d 与 boot/ 额外用 sh -n 校验 POSIX 兼容
#      （前者被 Xsession 以 /bin/sh source，后者在 chroot 与 initramfs 内
#      以 /bin/sh 执行）；
#   2. 校验 specs/ 下所有 RPM 配方（tools/spec_lint.py，E001~E016）；
#   3. 校验 comps/ 下包组定义（tools/comps_lint.py，C001~C011），并在
#      具备 xmllint 时按 comps/comps.dtd 做 DTD 校验；
#   4. 校验 kickstart/ 下安装配方（tools/ks_lint.py，K001~K017）；
#   5. 校验 presets/ 下 systemd 启用边界（tools/preset_lint.py，P001~P008，含
#      目录级「唯一 blanket 且字典序最后」约束）；
#   6. 运行 tools/tests 下的规则回归测试。
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
done < <(find ci lockfile scripts desktop tools boot -type f -name '*.sh' |
    sort)
while IFS= read -r env; do
    bash -n "${env}"
done < <(find scripts/lib -type f -name '*.env' | sort)
for dir in desktop/xinitrc.d boot; do
    [ -d "${dir}" ] || continue
    while IFS= read -r script; do
        sh -n "${script}"
    done < <(find "${dir}" -type f -name '*.sh' | sort)
done

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

echo "== ks lint =="
python3 tools/ks_lint.py

echo "== preset lint =="
python3 tools/preset_lint.py

# 只走标准库 unittest：此前的「装了 pytest 就用 pytest」会让同一批用例在
# 开发机与 runner 上跑成两套收集规则与两套失败格式，门禁结论不可比；用例
# 本身全部是 unittest.TestCase，没有一条依赖 pytest。
#
# 逐模块并行：626 条用例串行要四分多钟，而单个模块最长不过二十三秒，时间
# 全花在等被测脚本的子进程与轮询上。门禁是本仓库唯一排在镜像组装之前的
# 步骤，它的墙钟直接加在每一轮流水线上。
echo "== tool tests =="
python3 ci/par_tests.py

echo "== lint passed =="
