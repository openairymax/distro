#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# run-image-ci.sh — 镜像 CI 编排入口
#
# 把 RPM 构建、内核构建、ISO 组装、ISO 完整性、装机验收串成一条可重复
# 门禁，任何一段失败即整体失败。各段产物保存在同一输出目录，清单位于
# image-ci-manifest.txt，避免在编排层复制子驱动的清单（SSoT）。
#
# 边界：run-smoke.sh 必须在已登录的桌面会话内运行，属于桌面验收
# （TV-02），不由本脚本从宿主机驱动；本脚本只负责安装/启动链。
# --acceptance 把冒烟夹具注入 B 轮验收 ISO，由镜像内会话自动执行，
# 宿主机仍只观测串口标记 AIRYMAX-SMOKE-PASS/FAIL。
#
# 退出码：0 全部通过；1 存在失败；5 参数不满足；6 产物目录不可用；
#         77 缺少 QEMU 工具链（装机段跳过）。
# ===========================================================================
set -uo pipefail

readonly EINVAL=5
readonly SKIP=77
readonly DISTRO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

# shellcheck source=../scripts/lib/outdir.sh
. "${DISTRO_ROOT}/scripts/lib/outdir.sh"
# shellcheck source=../scripts/lib/arch.sh
. "${DISTRO_ROOT}/scripts/lib/arch.sh"
# shellcheck source=../scripts/lib/iso.sh
. "${DISTRO_ROOT}/scripts/lib/iso.sh"
# shellcheck source=../scripts/lib/log.sh
. "${DISTRO_ROOT}/scripts/lib/log.sh"

OUT=""
ISO=""
ISO_BASE=""
ISO_SUM=""
KS=""
ARCH=""
PROFILE="minimal"
FIRMWARE="bios"
RUNS=3
JOBS=""
KERNEL=""
INSTALL_TIMEOUT=3600
BOOT_TIMEOUT=300
MAX_BOOT=""
SPEC_DIRS=()
SRC_DIRS=()
RPMS_DIRS=()
ADDS=()
SKIP_RPMS=0
SKIP_KERNEL=0
SKIP_ISO=0
SKIP_INSTALL=0
ACCEPTANCE=0

PASS=0
FAIL=0
ENV_SKIP=0
ROWS=()
TOTAL=0

usage()
{
    cat <<'EOF'
用法: ci/run-image-ci.sh --out DIR (--iso PATH | --iso-base PATH) [选项]

  --out DIR          产物根目录（必须在源码区之外，必填）
  --iso PATH         预构建 ISO；给出时跳过组装段
  --iso-base PATH    基础 ISO，供组装段注入 kickstart
  --ks FILE          kickstart，缺省随 --profile（minimal/desktop）
  --arch ARCH        x86_64 或 aarch64，缺省宿主架构
  --profile NAME     minimal 或 desktop，缺省 minimal
  --firmware FW      bios、uefi 或 both，缺省 bios
  --runs N           每种固件的安装轮次，缺省 3
  --spec-dir DIR     传给 build-rpms 的配方目录，可重复
  --src-dir DIR      传给 build-rpms 的源码搜索目录，可重复；缺省补
                     system/units 与 system/scripts（airymaxos-system）
  --rpms DIR         传给 build-desktop 的 RPM 目录，可重复；
                     跳过构建段时必须显式给出（两剖面共用）
  --add PATH         传给 build-iso 的附加文件或目录，可重复
  --acceptance       生成 desktop 验收 ISO：自动登录、会话内冒烟并输出
                     AIRYMAX-SMOKE-PASS；仅 desktop，与 --ks 互斥，
                     需 --iso-base 重新组装
  --kernel DIR       内核源码树，缺省 build-kernel 的默认值
  --jobs N           并行度，缺省由子驱动决定
  --install-timeout S  装机超时秒数，缺省 3600
  --boot-timeout S     启动硬超时秒数，缺省 300
  --max-boot S         启动墙钟上限秒数；缺省不传，交给 install-test.sh
                       按 boot marker 决定（login: 腿 30s，GUI 腿不设上限）
  --skip-rpms        跳过 RPM 构建段
  --skip-kernel      跳过内核构建段
  --skip-iso         跳过 ISO 组装段（需配合 --iso）
  --skip-install     跳过装机段
  -h, --help         显示本帮助

产物:
  DIR/rpms/                   build-rpms 产物与清单
  DIR/kernel/                 build-kernel 产物与清单
  DIR/iso/                    minimal 镜像产物与清单
  DIR/payload/                minimal 离线仓库与载荷清单
  DIR/desktop/                desktop 离线载荷与镜像产物
  DIR/acceptance/             验收 kickstart（仅 --acceptance）
  DIR/logs/                   各段日志与 install-test TAP
  DIR/image-ci-manifest.txt   五段结果与 ISO 摘要
EOF
}

die()
{
    printf 'run-image-ci: %s\n' "$*" >&2
    exit "${EINVAL}"
}

optarg()
{
    [ "$2" -ge 2 ] || die "$1 缺少参数"
}

need_num()
{
    case "$2" in
    ''|*[!0-9]*) die "$1 必须是非负整数: $2" ;;
    esac
}

parse_args()
{
    while [ $# -gt 0 ]; do
        case "$1" in
        --out) optarg "$1" "$#"; OUT="$2"; shift 2 ;;
        --iso) optarg "$1" "$#"; ISO="$2"; shift 2 ;;
        --iso-base) optarg "$1" "$#"; ISO_BASE="$2"; shift 2 ;;
        --ks) optarg "$1" "$#"; KS="$2"; shift 2 ;;
        --arch) optarg "$1" "$#"; ARCH="$2"; shift 2 ;;
        --profile) optarg "$1" "$#"; PROFILE="$2"; shift 2 ;;
        --firmware) optarg "$1" "$#"; FIRMWARE="$2"; shift 2 ;;
        --runs) optarg "$1" "$#"; need_num "$1" "$2"; RUNS="$2"; shift 2 ;;
        --spec-dir) optarg "$1" "$#"; SPEC_DIRS+=("$2"); shift 2 ;;
        --src-dir) optarg "$1" "$#"; SRC_DIRS+=("$2"); shift 2 ;;
        --rpms) optarg "$1" "$#"; RPMS_DIRS+=("$2"); shift 2 ;;
        --add) optarg "$1" "$#"; ADDS+=("$2"); shift 2 ;;
        --acceptance) ACCEPTANCE=1; shift ;;
        --kernel) optarg "$1" "$#"; KERNEL="$2"; shift 2 ;;
        --jobs) optarg "$1" "$#"; JOBS="$2"; shift 2 ;;
        --install-timeout)
            optarg "$1" "$#"; need_num "$1" "$2"; INSTALL_TIMEOUT="$2"; shift 2 ;;
        --boot-timeout)
            optarg "$1" "$#"; need_num "$1" "$2"; BOOT_TIMEOUT="$2"; shift 2 ;;
        --max-boot)
            optarg "$1" "$#"; need_num "$1" "$2"; MAX_BOOT="$2"; shift 2 ;;
        --skip-rpms) SKIP_RPMS=1; shift ;;
        --skip-kernel) SKIP_KERNEL=1; shift ;;
        --skip-iso) SKIP_ISO=1; shift ;;
        --skip-install) SKIP_INSTALL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "未知参数: $1" ;;
        esac
    done
}

check_args()
{
    [ -n "${OUT}" ] || die "--out 必填"
    case "${ARCH}" in
    x86_64|aarch64) ;;
    *) die "不支持的架构: ${ARCH}" ;;
    esac
    case "${FIRMWARE}" in
    bios|uefi|both) ;;
    *) die "不支持的固件: ${FIRMWARE}" ;;
    esac
    case "${PROFILE}" in
    minimal|desktop) ;;
    *) die "不支持的镜像剖面: ${PROFILE}" ;;
    esac
    if [ "${ACCEPTANCE}" -eq 1 ]; then
        [ "${PROFILE}" = desktop ] || die "--acceptance 仅支持 desktop 剖面"
        [ -z "${KS}" ] || die "--acceptance 与 --ks 互斥"
        [ -z "${ISO}" ] ||
            die "--acceptance 需要 --iso-base 重新组装镜像"
    fi
    [ "${RUNS}" -ge 1 ] || die "--runs 必须大于 0"
    if [ -n "${ISO}" ]; then
        [ -f "${ISO}" ] || die "ISO 不存在: ${ISO}"
    fi
    if [ -n "${ISO_BASE}" ]; then
        [ -f "${ISO_BASE}" ] || die "基础 ISO 不存在: ${ISO_BASE}"
    fi
    if [ "${SKIP_ISO}" -eq 0 ] && [ -z "${ISO}" ] && [ -z "${ISO_BASE}" ]; then
        die "需要 --iso 或 --iso-base（或显式 --skip-iso）"
    fi
    if [ "${SKIP_INSTALL}" -eq 0 ] && [ -z "${ISO}" ] && [ -z "${ISO_BASE}" ]; then
        die "装机段需要可用 ISO"
    fi
    if [ "${SKIP_INSTALL}" -eq 0 ] && [ "${SKIP_ISO}" -eq 1 ] && [ -z "${ISO}" ]; then
        die "--skip-iso 且未给出 --iso 时无法执行装机段"
    fi
    if [ "${ARCH}" = aarch64 ] && [ "${FIRMWARE}" != uefi ]; then
        die "aarch64 仅支持 uefi 固件"
    fi
    if [ "${SKIP_ISO}" -eq 0 ] && [ -z "${ISO}" ] &&
        [ "${SKIP_RPMS}" -eq 1 ] && [ "${SKIP_KERNEL}" -eq 1 ] &&
        [ "${#RPMS_DIRS[@]}" -eq 0 ]; then
        die "组装 ISO 需 --rpms 目录，或启用 RPM/内核构建段"
    fi
    if [ -z "${KS}" ]; then
        if [ "${PROFILE}" = desktop ]; then
            KS="${DISTRO_ROOT}/kickstart/airymaxos-workstation.ks"
        else
            KS="${DISTRO_ROOT}/kickstart/airymaxos-minimal.ks"
        fi
    fi
    default_srcs
}

# airymaxos-system 的 Source 位于 distro 之外的 system/ 子树，distro 根内
# 索引不到；未显式给出 --src-dir 时按仓库布局补齐，避免装机时缺包。
default_srcs()
{
    local dir
    if [ "${#SRC_DIRS[@]}" -ne 0 ]; then
        return 0
    fi
    for dir in "${DISTRO_ROOT}/../system/units" \
        "${DISTRO_ROOT}/../system/scripts"; do
        if [ -d "${dir}" ]; then
            SRC_DIRS+=("${dir}")
        fi
    done
}

# 验收夹具不得进入产品配方：生成组合 kickstart 到构建目录，并随 ISO
# 注入会话内冒烟脚本。产品 ISO 与验收 ISO 的差异仅限本函数。
accept_ks()
{
    local out="${OUT}/acceptance/airymaxos-acceptance.ks"
    mkdir -p "${OUT}/acceptance" || die "无法创建验收产物目录"
    python3 "${DISTRO_ROOT}/tools/gen_accept_ks.py" \
        --base "${KS}" \
        --overlay "${DISTRO_ROOT}/ci/ks/acceptance.part" \
        --out "${out}" || die "无法生成验收 kickstart"
    KS="${out}"
    ADDS+=("${DISTRO_ROOT}/ci/run-smoke.sh")
    ADDS+=("${DISTRO_ROOT}/ci/fixture")
}

tap_ok()
{
    printf 'ok %s - %s\n' "$1" "$2"
    PASS=$((PASS + 1))
}

tap_skip()
{
    printf 'ok %s - %s # SKIP %s\n' "$1" "$2" "$3"
}

tap_fail()
{
    printf 'not ok %s - %s\n' "$1" "$2"
    [ -n "${3:-}" ] && printf '#   %s\n' "$3"
    FAIL=$((FAIL + 1))
}

rpm_args()
{
    local d
    RPM_ARGS=(--out "${OUT}/rpms" --arch "${ARCH}")
    for d in "${SPEC_DIRS[@]}"; do
        RPM_ARGS+=(--spec-dir "$d")
    done
    for d in "${SRC_DIRS[@]}"; do
        RPM_ARGS+=(--src-dir "$d")
    done
    if [ -n "${JOBS}" ]; then
        RPM_ARGS+=(--jobs "${JOBS}")
    fi
}

kern_args()
{
    KERN_ARGS=(--out "${OUT}/kernel" --arch "${ARCH}")
    if [ -n "${KERNEL}" ]; then
        KERN_ARGS+=(--kernel "${KERNEL}")
    fi
    if [ -n "${JOBS}" ]; then
        KERN_ARGS+=(--jobs "${JOBS}")
    fi
}

media_args()
{
    local a
    MEDIA_ARGS=(--iso "${ISO_BASE}" --ks "${KS}" --arch "${ARCH}")
    if [ "${PROFILE}" = desktop ]; then
        MEDIA_ARGS+=(--out "${OUT}/desktop")
    else
        MEDIA_ARGS+=(--out "${OUT}" --require airymaxos-kernel \
            --require airymaxos-kernel-core \
            --require airymaxos-kernel-modules)
    fi
    for a in "${RPMS_DIRS[@]}"; do
        MEDIA_ARGS+=(--rpms "$a")
    done
    if [ "${SKIP_RPMS}" -eq 0 ]; then
        MEDIA_ARGS+=(--rpms "${OUT}/rpms/RPMS")
    fi
    if [ "${SKIP_KERNEL}" -eq 0 ]; then
        MEDIA_ARGS+=(--rpms "${OUT}/kernel/RPMS")
    fi
    for a in "${ADDS[@]}"; do
        MEDIA_ARGS+=(--add "$a")
    done
}

iso_build()
{
    media_args
    "${DISTRO_ROOT}/scripts/build-desktop.sh" "${MEDIA_ARGS[@]}"
}

stage_rpm()
{
    if [ "${SKIP_RPMS}" -eq 1 ]; then
        tap_skip 1 "rpm build" "requested"
        ROWS+=("rpm=skip")
        return 0
    fi
    rpm_args
    if "${DISTRO_ROOT}/scripts/build-rpms.sh" "${RPM_ARGS[@]}" \
        >"${LOGS}/build-rpms.log" 2>&1; then
        tap_ok 1 "rpm build"
        ROWS+=("rpm=pass")
    else
        log_tail "${LOGS}/build-rpms.log" 12 '#   '
        tap_fail 1 "rpm build" "see ${LOGS}/build-rpms.log"
        ROWS+=("rpm=fail")
    fi
}

stage_kern()
{
    if [ "${SKIP_KERNEL}" -eq 1 ]; then
        tap_skip 2 "kernel build" "requested"
        ROWS+=("kernel=skip")
        return 0
    fi
    kern_args
    if "${DISTRO_ROOT}/scripts/build-kernel.sh" "${KERN_ARGS[@]}" \
        >"${LOGS}/build-kernel.log" 2>&1; then
        tap_ok 2 "kernel build"
        ROWS+=("kernel=pass")
    else
        log_tail "${LOGS}/build-kernel.log" 12 '#   '
        tap_fail 2 "kernel build" "see ${LOGS}/build-kernel.log"
        ROWS+=("kernel=fail")
    fi
}

iso_locate()
{
    local dir="$1" name
    name="$(iso_name "${dir}")" || return 1
    ISO="${dir}/${name}"
    [ -f "${ISO}" ] || return 1
}

stage_iso()
{
    local dir log="${LOGS}/build-desktop.log"
    if [ "${SKIP_ISO}" -eq 1 ] || [ -n "${ISO}" ]; then
        tap_skip 3 "iso assembly" "prebuilt"
        ROWS+=("iso=skip")
        return 0
    fi
    if [ "${PROFILE}" = desktop ]; then
        dir="${OUT}/desktop/iso"
    else
        dir="${OUT}/iso"
    fi
    if iso_build >"${log}" 2>&1 && iso_locate "${dir}"; then
        tap_ok 3 "iso assembly"
        ROWS+=("iso=pass")
    else
        log_tail "${log}" 12 '#   '
        tap_fail 3 "iso assembly" "see ${log}"
        ROWS+=("iso=fail")
    fi
}

sum_ok()
{
    local want name got rest
    [ -f "${ISO}.sha256" ] ||
        { printf 'missing %s.sha256\n' "${ISO}" >&2; return 1; }
    read -r want name <"${ISO}.sha256"
    read -r got rest <<<"$(sha256sum "${ISO}")"
    [ "${want}" = "${got}" ] ||
        { printf 'sha256 mismatch\n' >&2; return 1; }
    [ "${name}" = "$(basename "${ISO}")" ] ||
        { printf 'sha256 filename mismatch\n' >&2; return 1; }
}

stage_sum()
{
    if [ "${SKIP_INSTALL}" -eq 1 ]; then
        tap_skip 4 "iso checksum" "install skipped"
        ROWS+=("checksum=skip")
        return 0
    fi
    if sum_ok; then
        tap_ok 4 "iso checksum"
        ROWS+=("checksum=pass")
    else
        tap_fail 4 "iso checksum" "see ${ISO}.sha256"
        ROWS+=("checksum=fail")
    fi
}

inst_args()
{
    INST_ARGS=(--iso "${ISO}" --out "${OUT}/install" --arch "${ARCH}"
               --firmware "${FIRMWARE}" --runs "${RUNS}"
               --install-timeout "${INSTALL_TIMEOUT}"
               --boot-timeout "${BOOT_TIMEOUT}")
    [ -n "${MAX_BOOT}" ] && INST_ARGS+=(--max-boot "${MAX_BOOT}")
    if [ "${ACCEPTANCE}" -eq 1 ]; then
        INST_ARGS+=(--boot-marker AIRYMAX-SMOKE-PASS)
    elif [ "${PROFILE}" = desktop ]; then
        INST_ARGS+=(--boot-marker AIRYMAX-DESKTOP-READY)
    fi
}

stage_inst()
{
    local rc
    if [ "${SKIP_INSTALL}" -eq 1 ]; then
        tap_skip 5 "install test" "requested"
        ROWS+=("install=skip")
        return 0
    fi
    inst_args
    "${DISTRO_ROOT}/scripts/install-test.sh" "${INST_ARGS[@]}" \
        >"${LOGS}/install-test.log" 2>&1
    rc=$?
    case "${rc}" in
    0) tap_ok 5 "install test"; ROWS+=("install=pass") ;;
    77) tap_skip 5 "install test" "QEMU toolchain unavailable"
        ROWS+=("install=skip"); ENV_SKIP=1 ;;
    *) log_tail "${LOGS}/install-test.log" 12 '#   '
       tap_fail 5 "install test" "see ${LOGS}/install-test.log"
       ROWS+=("install=fail") ;;
    esac
}

sde_get()
{
    if [ -n "${SOURCE_DATE_EPOCH:-}" ]; then
        printf '%s' "${SOURCE_DATE_EPOCH}"
        return 0
    fi
    git -C "${DISTRO_ROOT}" log -1 --pretty=%ct 2>/dev/null || true
}

manifest()
{
    local row sde
    sde="$(sde_get)"
    {
        printf '# AirymaxOS image CI manifest\n'
        printf 'arch=%s\nprofile=%s\nfirmware=%s\nruns=%s\nmax_boot=%s\n' \
            "${ARCH}" "${PROFILE}" "${FIRMWARE}" "${RUNS}" "${MAX_BOOT:-auto}"
        printf 'acceptance=%s\n' "${ACCEPTANCE}"
        printf 'source_date_epoch=%s\n' "${sde:-unset}"
        for row in "${ROWS[@]}"; do
            printf 'stage %s\n' "${row}"
        done
        if [ -n "${ISO}" ] && [ -f "${ISO}" ]; then
            printf 'iso %s %s\n' "${ISO_SUM}" "$(basename "${ISO}")"
        fi
        if [ "${FAIL}" -eq 0 ]; then
            printf 'result=pass\n'
        else
            printf 'result=fail\n'
        fi
    } >"${OUT}/image-ci-manifest.txt"
}

main()
{
    local sde
    parse_args "$@"
    if [ -z "${ARCH}" ]; then
        ARCH="$(host_arch)"
    fi
    check_args
    OUT="$(out_guard run-image-ci "${OUT}")" || exit $?
    LOGS="${OUT}/logs"
    mkdir -p "${LOGS}" || die "无法创建日志目录: ${LOGS}"
    if [ "${ACCEPTANCE}" -eq 1 ]; then
        accept_ks
    fi
    sde="$(sde_get)"
    if [ -n "${sde}" ]; then
        SOURCE_DATE_EPOCH="${sde}"
        export SOURCE_DATE_EPOCH
    fi
    printf 'TAP version 14\n1..5\n'
    printf '# AirymaxOS image CI: arch=%s profile=%s firmware=%s\n' \
        "${ARCH}" "${PROFILE}" "${FIRMWARE}"
    stage_rpm
    stage_kern
    stage_iso
    stage_sum
    ISO_SUM=""
    if [ -n "${ISO}" ] && [ -f "${ISO}" ]; then
        read -r ISO_SUM _ <<<"$(sha256sum "${ISO}")"
    fi
    stage_inst
    manifest
    printf '# summary: pass=%d fail=%d\n' "${PASS}" "${FAIL}"
    if [ "${FAIL}" -gt 0 ]; then
        return 1
    fi
    [ "${ENV_SKIP}" -eq 0 ] || return "${SKIP}"
    return 0
}

main "$@"
