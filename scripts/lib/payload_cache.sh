#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# payload_cache.sh — 候选池的校验、回填与漂移判定（被 closure.sh source）
#
# 候选池只提供字节，不提供事实：dnf 每轮仍按新鲜元数据求解，池只是让同一
# 份字节不必再走公网。因此池内每个文件在使用前都要与清单逐项核对
# sha256——池是跨轮、跨机器延续的可写目录，被截断、被替换或被人工改动的
# 文件只有摘要能发现。池里的文件一旦被 dnf 当作本地已有，损坏就会直接进
# 载荷，装机现场才以「缺依赖」的形式暴露。
#
# 三种「不一致」必须分开处理，混淆任何一种都会把错误带进产物：
#   * 池内文件与清单不符——缓存污染，删掉该文件让 dnf 重新下载，不是错误；
#   * 重新下载的文件与清单不符——同一输入树产出了不同字节，硬失败
#     （AIRY-PAYLOAD-DRIFT），不可复现的产物不得发布；
#   * 池或清单不可用——回落全量收割，并打印固定格式的一行。静默降级会让
#     人把这轮的快误当成常态，也会让「为什么还在走公网」无从归因。
#
# 回填用硬链接而不是复制：池与本轮下载目录通常同在一块盘上，硬链接省掉
# 数 GB 的写放大；跨文件系统时 ln 失败，退回复制并记 mode=copy，使日志
# 能回答「这一轮到底有没有多写一份盘」。
#
# 清单有两种书写格式，都在此处解析：闭包清单「sha256  文件名  NEVRA」是
# 钉住求解结果的那一份，NEVRA 供离线重放点名；载荷清单「rpm sha256
# 文件名」随 ISO 发布，供装机与验收复核。两者只差列序，解析一次即可。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

PC_SUM=()
PC_BASE=()
PC_NEV=()

# 解析清单到 PC_SUM/PC_BASE/PC_NEV。载荷清单没有 NEVRA 列，对应项留空；
# 调用方按空值跳过即可，不需要两套解析。
pc_read()
{
    local file="$1" a b c rest
    PC_SUM=()
    PC_BASE=()
    PC_NEV=()
    [ -r "$file" ] || return 1
    while read -r a b c rest; do
        case "$a" in
        rpm) PC_SUM+=("$b"); PC_BASE+=("$c"); PC_NEV+=("") ;;
        *) PC_SUM+=("$a"); PC_BASE+=("$b"); PC_NEV+=("$c") ;;
        esac
    done <"$file"
    # 空清单或只写了一半的清单会让上游「全部命中」，比缺失更危险，按不可
    # 用处理。
    [ "${#PC_BASE[@]}" -gt 0 ]
}

pc_verify()
{
    [ "$(sha256sum "$1" | cut -d' ' -f1)" = "$2" ]
}

pc_fallback()
{
    printf 'payload cache: unavailable %s — falling back to full harvest\n' "$1"
}

# 求解前核对池：与清单不符的文件立即删除，使本轮从上游重取真实字节。
pc_seed()
{
    local pool="$1" lock="$2" base sum i hit=0 total bad=0
    if ! pc_read "$lock"; then
        pc_fallback "清单缺失或为空（${lock:-未配置}）"
        return 1
    fi
    if [ -z "$pool" ] || [ ! -d "$pool" ]; then
        pc_fallback "候选池缺失（${pool:-未配置}）"
        return 1
    fi
    total=${#PC_BASE[@]}
    for i in "${!PC_BASE[@]}"; do
        base="${PC_BASE[$i]}"
        sum="${PC_SUM[$i]}"
        [ -f "${pool}/${base}" ] || continue
        if pc_verify "${pool}/${base}" "$sum"; then
            hit=$((hit + 1))
            continue
        fi
        rm -f "${pool}/${base}"
        bad=$((bad + 1))
        printf 'payload cache: discard %s (sha256 mismatch)\n' "$base"
    done
    printf 'payload cache: pool %d/%d verified\n' "$hit" "$total"
    [ "$bad" -eq 0 ]
}

# 本轮实际没走公网的比例：同名同字节才算命中。只比名字会把「池里有旧
# 快照的同名包」也算成命中，读数虚高，掩盖真正需要优化的那一段。
pc_stat()
{
    local pool="$1" dl="$2" rpm base n=0 hit=0
    [ -n "$pool" ] && [ -d "$dl" ] || return 0
    while IFS= read -r rpm; do
        n=$((n + 1))
        base="${rpm##*/}"
        [ -f "${pool}/${base}" ] || continue
        cmp -s "$rpm" "${pool}/${base}" || continue
        hit=$((hit + 1))
    done < <(find "$dl" -maxdepth 1 -type f -name '*.rpm' 2>/dev/null)
    [ "$n" -gt 0 ] || return 0
    printf 'payload cache: hit %d/%d\n' "$hit" "$n"
}

# 通过审计的事务才回填：池的可信集合只扩大，不引入未经校验的字节。
# 这里不再逐包 rpm -K：dnf 在整包校验通过前只用临时名，dl 里出现的最终名
# 已经是它按 repodata 校验过的字节；池的可信度由下一轮的 pc_seed 与清单
# 复核闭环，不需要在回填时再读一遍整包。
#
# 自建包（SKIP 里的名字空间）不回填：池缓存的是上游交付的字节，本仓产物
# 的唯一事实源是当轮的载荷目录。让旧构建留在池里，下一轮就以更低 cost 提供
# 同名同 EVR 的旧字节，源码改了而发行号没动时，镜像会静默装上上一版的包
# （run 41792595223 的解算记录：airymaxos-release 0.0.4-7 取自 airymax-pool）。
pc_absorb()
{
    local pool="$1" dl="$2" skip="${3:-}" rpm base kept=0 mode=link
    [ -n "$pool" ] && [ -d "$dl" ] || return 0
    mkdir -p "$pool" || {
        printf 'payload cache: 无法写入 %s，本轮不回填\n' "$pool" >&2
        return 0
    }
    while IFS= read -r rpm; do
        base="${rpm##*/}"
        [ -f "${pool}/${base}" ] && continue
        [ -s "$rpm" ] || continue
        if [ -n "$skip" ]; then
            # shellcheck disable=SC2254  # 跳过项是 glob，按 glob 匹配才是本意
            case "$base" in
            $skip) continue ;;
            esac
        fi
        if ln "$rpm" "${pool}/${base}" 2>/dev/null; then
            kept=$((kept + 1))
            continue
        fi
        cp -p "$rpm" "${pool}/${base}" || continue
        mode=copy
        kept=$((kept + 1))
    done < <(find "$dl" -maxdepth 1 -type f -name '*.rpm' 2>/dev/null)
    [ "$kept" -gt 0 ] || return 0
    printf 'payload cache: absorb %d (mode=%s)\n' "$kept" "$mode"
}

# 本轮下载与清单逐包比对。自建包（载荷目录里已有同名文件）不参与：它们的
# 字节由本仓的构建产生，跨轮不同是常态，判据只针对上游交付的字节。
pc_drift()
{
    local lock="$1" dl="$2" self="$3" base sum got i bad=0
    [ -n "$lock" ] && [ -d "$dl" ] || return 0
    [ "${#PC_BASE[@]}" -gt 0 ] || return 0
    for i in "${!PC_BASE[@]}"; do
        base="${PC_BASE[$i]}"
        sum="${PC_SUM[$i]}"
        [ -f "${dl}/${base}" ] || continue
        [ -n "$self" ] && [ -f "${self}/${base}" ] && continue
        got="$(sha256sum "${dl}/${base}" | cut -d' ' -f1)"
        [ "$got" = "$sum" ] && continue
        printf 'AIRY-PAYLOAD-DRIFT %s\n' "$base" >&2
        printf 'payload cache: drift %s (manifest %s, round %s)\n' \
            "$base" "$sum" "$got" >&2
        bad=$((bad + 1))
    done
    [ "$bad" -eq 0 ]
}
