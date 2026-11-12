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
# 摘要只证明「与清单一致」，不证明「包是完整的」。清单本身是上一轮写出的：
# 那一轮若把被截断的字节收进池，摘要就把损坏钉成了锚点，此后每一轮都
# 「核对通过」。而 dnf 对 --downloaddir 里已存在的同名文件不再校验，进程被
# 中断时会在最终文件名上留下截断的包；createrepo_c 只读包头，也照样把截断
# 包索引成合法仓库。因此可信的判据是两条：摘要防替换，包自校验
# （rpm -K --nosignature）防截断。二者缺一，坏字节就会一路抵达装机现场，
# 以「Payload SHA256 ALT digest: BAD」的形式停在 anaconda 的交互确认上。
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

# 包自校验：头部与载荷的摘要都要与包头里登记的相符。只读包头（rpm -qp）
# 判不出截断——截断包的包头完好，载荷却在后面；这一点在 285H 上实测过：
# 完整包 digests OK，截到 110000000 字节后 rc=1，而 -qp 仍能读出 NEVRA。
pc_sane()
{
    "${CL_RPM:-rpm}" -K --nosignature "$1" >/dev/null 2>&1
}

# 校验器是在场的前提：判不了就不该用池，宁可回落全量收割。
pc_ready()
{
    command -v "${CL_RPM:-rpm}" >/dev/null 2>&1
}

# 池里可能有清单根本不知道的文件：失败轮次回填过、或人工放过。它们同样会
# 被 createrepo_c 索引成「正确」，所以索引之前必须整池自校验一遍，坏的
# 删掉让 dnf 重新取。删的是字节，不是记录——下一轮仍按清单独自核对。
pc_sweep()
{
    local pool="$1" rpm bad=0
    [ -n "$pool" ] && [ -d "$pool" ] || return 0
    if ! pc_ready; then
        printf 'payload cache: 校验器缺失（%s），无法清扫\n' \
            "${CL_RPM:-rpm}" >&2
        return 1
    fi
    while IFS= read -r rpm; do
        pc_sane "$rpm" && continue
        rm -f "$rpm"
        printf 'payload cache: purge %s (digests bad)\n' "${rpm##*/}"
        bad=$((bad + 1))
    done < <(find "$pool" -maxdepth 1 -type f -name '*.rpm' 2>/dev/null)
    [ "$bad" -eq 0 ] || printf 'payload cache: purged %d\n' "$bad"
    return 0
}

pc_fallback()
{
    printf 'payload cache: unavailable %s — falling back to full harvest\n' "$1"
}

# 求解前核对池：与清单不符的文件立即删除，使本轮从上游重取真实字节。
#
# 摘要相符的条目还要过一遍包自校验：相符只说明「与清单同字节」，而清单可能
# 正是上一轮把坏字节钉成的锚点。证伪的条目同时从内存清单里剔除，否则本轮
# 的漂移判定会继续拿它当基准，把重新下载的正确字节判成 AIRY-PAYLOAD-DRIFT。
pc_seed()
{
    local pool="$1" lock="$2" base sum i hit=0 total bad=0
    local -a sum2=() base2=() nev2=()
    if ! pc_read "$lock"; then
        pc_fallback "清单缺失或为空（${lock:-未配置}）"
        return 1
    fi
    if [ -z "$pool" ] || [ ! -d "$pool" ]; then
        pc_fallback "候选池缺失（${pool:-未配置}）"
        return 1
    fi
    if ! pc_ready; then
        pc_fallback "校验器缺失（${CL_RPM:-rpm}）"
        return 1
    fi
    total=${#PC_BASE[@]}
    for i in "${!PC_BASE[@]}"; do
        base="${PC_BASE[$i]}"
        sum="${PC_SUM[$i]}"
        if [ -f "${pool}/${base}" ] && ! pc_sane "${pool}/${base}"; then
            rm -f "${pool}/${base}"
            bad=$((bad + 1))
            printf 'payload cache: discard %s (digests bad)\n' "$base"
            continue
        fi
        sum2+=("$sum")
        base2+=("$base")
        nev2+=("${PC_NEV[$i]}")
        [ -f "${pool}/${base}" ] || continue
        if pc_verify "${pool}/${base}" "$sum"; then
            hit=$((hit + 1))
            continue
        fi
        rm -f "${pool}/${base}"
        bad=$((bad + 1))
        printf 'payload cache: discard %s (sha256 mismatch)\n' "$base"
    done
    if [ "${#base2[@]}" -gt 0 ]; then
        PC_SUM=("${sum2[@]}")
        PC_BASE=("${base2[@]}")
        PC_NEV=("${nev2[@]}")
    else
        PC_SUM=()
        PC_BASE=()
        PC_NEV=()
    fi
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

# pc_take POOL RPM SKIP —— 吸收单个包，返回 0 表示计入本轮。已在池中、
# 空文件、命中跳过清单、摘要不合格都按未吸收处理，不打印汇总。
# 硬链接失败退回复制，并把 PC_MODE 置为 copy 供汇总行说明本次方式。
pc_take()
{
    local pool="$1" rpm="$2" skip="$3" base

    base="${rpm##*/}"
    [ -f "${pool}/${base}" ] && return 1
    [ -s "$rpm" ] || return 1
    if [ -n "$skip" ]; then
        # shellcheck disable=SC2254  # 跳过项是 glob，按 glob 匹配才是本意
        case "$base" in
        $skip) return 1 ;;
        esac
    fi
    if ! pc_sane "$rpm"; then
        printf 'payload cache: skip %s (digests bad)\n' "$base" >&2
        return 1
    fi
    ln "$rpm" "${pool}/${base}" 2>/dev/null && return 0
    cp -p "$rpm" "${pool}/${base}" || return 1
    PC_MODE=copy
    return 0
}

# 通过审计的事务才回填：池的可信集合只扩大，不引入未经校验的字节。
#
# 回填前逐包自校验，这是本文件曾经判断错误的地方。原先假定「dnf 只在整包
# 校验通过后才用最终文件名」，因此把 dl 里出现的最终名一律当成已校验字节。
# 实测不是这样：dnf 对 --downloaddir 里已存在的同名文件跳过校验，进程被
# 中断（cl_watch 判挂死后 kill）时就在最终名上留下截断包。失败分支会在
# 重试前调用本函数，于是截断包被吸收进池、被索引成合法仓库、被下一轮当作
# 命中收进载荷，装机时 anaconda 报 Payload SHA256 ALT digest: BAD（run
# 42421987850 三条腿同一处失败，firefox 153.6.0）。
#
# 自建包（SKIP 里的名字空间）不回填：池缓存的是上游交付的字节，本仓产物
# 的唯一事实源是当轮的载荷目录。让旧构建留在池里，下一轮就以更低 cost 提供
# 同名同 EVR 的旧字节，源码改了而发行号没动时，镜像会静默装上上一版的包
# （run 41792595223 的解算记录：airymaxos-release 0.0.4-7 取自 airymax-pool）。
pc_absorb()
{
    local pool="$1" dl="$2" skip="${3:-}" rpm kept=0

    [ -n "$pool" ] && [ -d "$dl" ] || return 0
    mkdir -p "$pool" || {
        printf 'payload cache: 无法写入 %s，本轮不回填\n' "$pool" >&2
        return 0
    }
    if ! pc_ready; then
        printf 'payload cache: 校验器缺失（%s），本轮不回填\n' \
            "${CL_RPM:-rpm}" >&2
        return 0
    fi
    PC_MODE='link'
    while IFS= read -r rpm; do
        pc_take "$pool" "$rpm" "$skip" || continue
        kept=$((kept + 1))
    done < <(find "$dl" -maxdepth 1 -type f -name '*.rpm' 2>/dev/null)
    [ "$kept" -gt 0 ] || return 0
    printf 'payload cache: absorb %d (mode=%s)\n' "$kept" "$PC_MODE"
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
