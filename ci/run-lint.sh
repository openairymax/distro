#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-lint.sh — distro 仓库静态门禁
#
# 用法: ci/run-lint.sh [--no-tests]
#
# 职责（六段，每段单独计时）：
#   1. syntax — bash -n 解析 ci/、lockfile/、scripts/、desktop/、tools/、boot/
#      与 kickstart/ 下的 shell 入口，以及 scripts/lib 下被 source 的 *.env
#      （判负证据集等共用数据）；kickstart/ 的共享脚本会被嵌入配方，
#      语法错误在构建期才暴露，故与入口同级校验；desktop/xinitrc.d 与
#      boot/ 额外用 sh -n 校验 POSIX 兼容（前者被 Xsession 以 /bin/sh
#      source，后者在 chroot 与 initramfs 内以 /bin/sh 执行）；
#   2. spec — 校验 specs/ 下所有 RPM 配方（tools/spec_lint.py，E001~E016）；
#   3. comps — 校验 comps/ 下包组定义（tools/comps_lint.py，C001~C011），
#      并在具备 xmllint 时按 comps/comps.dtd 做 DTD 校验；
#   4. ks — 校验 kickstart/ 下安装配方（tools/ks_lint.py，K001~K019），共享
#      脚本先展开再判定；
#   5. preset — 校验 presets/ 下 systemd 启用边界（tools/preset_lint.py，
#      P001~P008，含目录级「唯一 blanket 且字典序最后」约束）；
#   6. tests — 运行 tools/tests 下的规则回归测试。
#
# 分段计时不是装饰：这条门禁排在每一轮镜像组装之前，它的墙钟直接加在
# 流水线上。没有分段时只知道「静态门禁四分钟」，无法判断该优化八百余条
# 工具用例还是该优化配方校验，于是谁都不敢动（W-2）。实测六段里只有 tests
# 有量级（111 秒），其余五段合计不足两秒。
#
# 只依赖 python3 标准库，可在无 rpmbuild/mock 的机器上执行。CI 与本地提交
# 前共用同一入口，避免两套口径。
#
# --no-tests 跳过第六段。这段只做规则回归，判定对象是仓库内容本身，与
# 组装环境无关：同一个提交在 push 门禁（os-chk-verify）里已经全量跑过，
# 组装再跑一遍不增加任何判据，只让每轮固定开销多出一分半到两分钟——
# 而这一分半直接加在「assemble 稳态 ≤360 秒」的预算上（CI-16）。跳过时
# 仍打印 ``[timing] tests=skipped``，六行表的形状不变，读数不会被误当成 0。
#
# 退出码: 0 全部通过；2 参数错误；其他为对应检查器的失败码。
# ===========================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${HERE}")"

cd "${ROOT}"

run_tests=1
for arg in "$@"; do
    case "${arg}" in
        --no-tests) run_tests=0 ;;
        *)
            echo "未知参数: ${arg}（可用: --no-tests）" >&2
            exit 2
            ;;
    esac
done

now()
{
    printf '%s' "${EPOCHSECONDS:-$(date +%s)}"
}

# 段名与耗时逐行打印成 ``[timing] <段>=<秒>s``：固定前缀让日志可以被 grep
# 成一张表，也让以后想把某一段拆细的人有个稳定格式可依。
seg()
{
    local name="$1" t0
    t0="$(now)"
    "$2"
    printf '[timing] %s=%ss\n' "${name}" "$(( $(now) - t0 ))"
}

check_syntax()
{
    echo "== shell syntax =="
    while IFS= read -r script; do
        bash -n "${script}"
    done < <(find ci lockfile scripts desktop tools boot kickstart \
        -type f -name '*.sh' | sort)
    while IFS= read -r env; do
        bash -n "${env}"
    done < <(find scripts/lib -type f -name '*.env' | sort)
    local dir script
    for dir in desktop/xinitrc.d boot; do
        [ -d "${dir}" ] || continue
        while IFS= read -r script; do
            sh -n "${script}"
        done < <(find "${dir}" -type f -name '*.sh' | sort)
    done
}

check_spec()
{
    echo "== spec lint =="
    python3 tools/spec_lint.py
}

check_comps()
{
    echo "== comps lint =="
    python3 tools/comps_lint.py
    if command -v xmllint >/dev/null 2>&1; then
        while IFS= read -r comps; do
            xmllint --noout --nonet --valid "${comps}"
        done < <(find comps -type f -name '*.xml' | sort)
    else
        echo "xmllint unavailable: DTD validation deferred to image CI" >&2
    fi
}

check_ks()
{
    echo "== ks lint =="
    python3 tools/ks_lint.py
}

check_pre()
{
    echo "== preset lint =="
    python3 tools/preset_lint.py
}

# 只走标准库 unittest：此前的「装了 pytest 就用 pytest」会让同一批用例在
# 开发机与 runner 上跑成两套收集规则与两套失败格式，门禁结论不可比；用例
# 本身全部是 unittest.TestCase，没有一条依赖 pytest。
#
# 逐模块并行：852 条用例串行要四分多钟，而单个模块最长不过二十三秒，时间
# 全花在等被测脚本的子进程与轮询上；并行后这一段实测 111 秒，仍是六段里
# 唯一的量级项。
check_tests()
{
    echo "== tool tests =="
    python3 ci/par_tests.py
}

t_start="$(now)"
seg syntax check_syntax
seg spec check_spec
seg comps check_comps
seg ks check_ks
seg preset check_pre
if [ "${run_tests}" -eq 1 ]; then
    seg tests check_tests
else
    printf '[timing] tests=skipped\n'
fi
printf '[timing] total=%ss\n' "$(( $(now) - t_start ))"

echo "== lint passed =="
