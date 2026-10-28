#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# iso_post.sh — ISO 后处理与产物契约校验（被构建驱动 source）
#
# mkksiso 只负责替换内核参数并追加快照，不负责产品契约；契约校验与
# 校验块注入必须在 ISO 落地之后独立完成。站点派生（注入站点 kickstart）
# 与主线构建共用同一套后处理，否则派生介质会漏掉校验块而让默认菜单的
# rd.live.check 误报介质损坏，或漏掉 isohybrid 对齐而让 USB 盘方式静默
# 不引导。
#
# 调用约定：所有函数显式接收参数，不读调用方全局变量；成功返回 0，
# 失败返回非零并已向 stderr 写出具体原因，由调用方决定退出码。诊断统一
# 以 iso-post: 开头，便于在 CI 日志中定位。
#
# 处理顺序不可调换：isohybrid 对齐会改写前 64 KiB 的分区表扇区，先注入
# 校验块会把改写后的字节算进旧摘要，rd.live.check 因而必然失败。
# ===========================================================================

ISO_POST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"

iso_post_log()
{
    printf 'iso-post: %s\n' "$*" >&2
}

# iso_xor <iso> <path> <dest> <log>
# xorriso 对已存在的目标返回 SORRY（rc=32）但内容完整，故以落地文件为准。
iso_xor()
{
    local iso="$1" path="$2" dest="$3" log="$4"
    rm -f "${dest}"
    xorriso -osirrox on -indev "${iso}" -extract "${path}" "${dest}" \
        >>"${log}" 2>&1 || true
    [ -s "${dest}" ]
}

# iso_volid <iso> — 从主卷描述符（LBA 16 偏移 40）取 32 字节卷标。
iso_volid()
{
    local iso="$1" value
    value="$(dd if="${iso}" bs=2048 skip=16 count=1 2>/dev/null |
        dd bs=1 skip=40 count=32 2>/dev/null |
        tr -d '\000' | sed 's/[[:space:]]*$//')" || return 1
    [ -n "${value}" ] || return 1
    printf '%s\n' "${value}"
}

# iso_cfg_check <cfg> <name> <volid>
iso_cfg_check()
{
    local cfg="$1" name="$2" volid="$3" arg
    if ! grep -Eq 'inst[.]ks=[^[:space:]]+' "${cfg}"; then
        iso_post_log "引导配置 ${name} 未注入 inst.ks"
        return 1
    fi
    if ! grep -Eq "(^|[^A-Za-z0-9_.-])LABEL=${volid}([^A-Za-z0-9_.-]|\$)" \
        "${cfg}"; then
        iso_post_log "引导配置 ${name} 未引用卷标 ${volid}"
        return 1
    fi
    while IFS= read -r arg; do
        case "${arg}" in
        *"LABEL=${volid}"*) ;;
        *)
            iso_post_log "${name} 的 ${arg} 与卷标 ${volid} 不一致"
            return 1
            ;;
        esac
    done < <(grep -Eo 'inst[.]stage2=[^[:space:]]+' "${cfg}" || true)
    return 0
}

# iso_post_ks <iso> <ks> <work>
iso_post_ks()
{
    local iso="$1" ks="$2" work="$3" got
    got="${work}/post/ks.cfg"
    mkdir -p "${work}/post"
    if ! iso_xor "${iso}" /ks.cfg "${got}" "${work}/logs/xorriso.log"; then
        iso_post_log "ISO 内缺少 /ks.cfg: ${iso}"
        return 1
    fi
    if ! cmp -s "${ks}" "${got}"; then
        iso_post_log "ISO 内 kickstart 与源文件不一致: ${ks}"
        return 1
    fi
    return 0
}

# iso_post_cfg <iso> <volid> <work>
iso_post_cfg()
{
    local iso="$1" volid="$2" work="$3"
    local cfg path dest found=0
    mkdir -p "${work}/post"
    for cfg in isolinux/isolinux.cfg EFI/BOOT/grub.cfg; do
        path="/${cfg}"
        dest="${work}/post/cfg.$(basename "${cfg}")"
        if iso_xor "${iso}" "${path}" "${dest}" \
            "${work}/logs/xorriso.log"; then
            found=1
            iso_cfg_check "${dest}" "${cfg}" "${volid}" || return 1
        fi
    done
    if [ "${found}" -ne 1 ]; then
        iso_post_log "ISO 内未找到 BIOS/UEFI 引导配置: ${iso}"
        return 1
    fi
    return 0
}

# iso_post_hybrid <iso> <work>
iso_post_hybrid()
{
    local iso="$1" work="$2" rc=0 log="${work}/logs/isohybrid.log"
    python3 "${ISO_POST_ROOT}/tools/isohybrid_sync.py" --check "${iso}" \
        >"${log}" 2>&1 || rc=$?
    case "${rc}" in
    0) return 0 ;;
    77)
        iso_post_log "跳过 isohybrid 一致性检查（非 El Torito 镜像）"
        return 0
        ;;
    esac
    sed 's/^/  /' "${log}" >&2
    iso_post_log "isohybrid 三元不一致，USB 盘方式将无法引导: ${iso}"
    return 1
}

# iso_post_fix <iso> <work>
# 重新打包会把 El Torito 条目的逻辑块号前移，而 MBR/GPT 仍是旧扇区号；
# 派生路径必须先按 El Torito 真值改写分区表，再走一致性判定。
iso_post_fix()
{
    local iso="$1" work="$2" rc=0 log="${work}/logs/isohybrid.log"
    python3 "${ISO_POST_ROOT}/tools/isohybrid_sync.py" --sync "${iso}" \
        >"${log}" 2>&1 || rc=$?
    case "${rc}" in
    0) return 0 ;;
    77)
        iso_post_log "跳过 isohybrid 对齐（非 El Torito 镜像）"
        return 0
        ;;
    esac
    sed 's/^/  /' "${log}" >&2
    iso_post_log "isohybrid 对齐失败: ${iso}"
    return 1
}

# iso_post_md5 <iso> <work>
iso_post_md5()
{
    local iso="$1" work="$2"
    # mkksiso 沿用底座 PVD 的应用数据区，其中仍是底座镜像的校验记录；
    # 该记录对新镜像已失效，必须覆盖，否则 implantisomd5 拒绝写入。
    if ! implantisomd5 --force "${iso}" \
        >"${work}/logs/implantisomd5.log" 2>&1; then
        iso_post_log "implantisomd5 失败（日志 ${work}/logs/implantisomd5.log）"
        return 1
    fi
    if ! checkisomd5 --md5sumonly "${iso}" \
        >"${work}/logs/checkisomd5.log" 2>&1; then
        iso_post_log "checkisomd5 复核失败（日志 ${work}/logs/checkisomd5.log）"
        return 1
    fi
    return 0
}

# iso_post <iso> <ks> <volid> <work> [--no-md5] [--fix]
iso_post()
{
    local iso="$1" ks="$2" volid="$3" work="$4"
    shift 4
    local got opt md5=1 fix=0
    for opt in "$@"; do
        case "${opt}" in
        --no-md5) md5=0 ;;
        --fix) fix=1 ;;
        '') ;;
        *)
            iso_post_log "未知选项: ${opt}"
            return 1
            ;;
        esac
    done
    mkdir -p "${work}/logs" "${work}/post"
    got="$(iso_volid "${iso}")" || {
        iso_post_log "无法读取卷标: ${iso}"
        return 1
    }
    if [ "${got}" != "${volid}" ]; then
        iso_post_log "卷标不符：期望 ${volid}，实际 ${got}"
        return 1
    fi
    iso_post_ks "${iso}" "${ks}" "${work}" || return 1
    iso_post_cfg "${iso}" "${volid}" "${work}" || return 1
    if [ "${fix}" -eq 1 ]; then
        iso_post_fix "${iso}" "${work}" || return 1
    fi
    iso_post_hybrid "${iso}" "${work}" || return 1
    if [ "${md5}" -eq 1 ]; then
        iso_post_md5 "${iso}" "${work}" || return 1
    fi
    return 0
}
