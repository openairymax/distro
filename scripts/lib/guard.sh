#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# guard.sh — 载荷 scriptlet 兜底重打包（被 build-desktop.sh source）
#
# anaconda 把安装事务里任一条 scriptlet 的非零退出当作事务失败，随即弹出
# 致命错误并中止装机，不会因为「后续包还能继续装」而降级（run
# 40939234612：sound-theme-freedesktop 的 %post 调用 touch 时 coreutils
# 尚未落盘，退出 127，安装停在「按 ENTER 退出:」）。该 %post 只做
# `touch --no-create` 更新两个目录的 mtime，本身可省，却没有任何失败兜底；
# 而该包被 libcanberra 强依赖（rpm -q --whatrequires 实测），UKUI 闭包
# 需要 libcanberra，剔除它等于拆掉桌面，故只能在载荷侧修。
#
# 事务顺序由求解器给出，不保证依赖先装（同尺寸载荷的两轮 run 里 coreutils
# 分别落在 170 与 428 之后），因此不能靠「这次恰好先装 coreutils」过关。
# 上游修好要等 openEuler 重新打包，0.0.3 在载荷侧做一次最小重打包：取出
# 上游 RPM 的全部文件，沿用同一 Name/Version、release 追加 .airymax1，
# scriptlet 加 `|| :` 兜底，其余内容逐字节保留。dnf 按 NEVRA 取高者，
# 重打包版本因此取代上游包，安装期解析结果与原闭包一致；安装清单与仓库
# 索引都取自替换后的集合。
#
# 不做的事：不碰安装期判定集（scriptlet 兜底不是放宽判据，装机仍然拒绝
# 任何事务失败），不引入 mock 与上游 SRPM 的构建依赖，不用手写 RPM 头
# 改写。重打包只用 rpm-build、rpm2cpio 与 cpio（构建容器已具备），产物
# 可被 rpm -qp --scripts 直接复核。
#
# 调用约定：
#   guard_payload PKGDIR WORK
#     目标包存在于 PKGDIR 时替换为兜底版本，新文件名追加到调用方的
#     NAMES 数组、旧名移除；不存在时只报告并返回 0（闭包集合变了不应
#     在构建期硬失败，装机腿会照常判定）。
#   环境变量 PAYLOAD_GUARD 可覆盖目标包名，用于测试与后续同类兜底。
#
# 退出码：0 表示替换完成或无需替换；非 0 表示重打包失败，调用方据此拒绝
# 出镜像，不得带病产出介质。
# ===========================================================================

readonly GD_NAME="${PAYLOAD_GUARD:-sound-theme-freedesktop}"
readonly GD_TAG="airymax1"

gd_find()
{
    local dir="$1" name="$2" f
    for f in "${dir}/${name}"-[0-9]*.rpm; do
        [ -f "$f" ] || continue
        printf '%s\n' "$f"
        return 0
    done
    return 1
}

gd_meta()
{
    local rpm="$1" tag="$2"
    rpm -qp --qf "%{${tag}}\n" "$rpm" 2>/dev/null
}

gd_extract()
{
    local rpm="$1" tree="$2"
    mkdir -p "$tree"
    rpm2cpio "$rpm" | (cd "$tree" && cpio -idm --quiet)
}

# 只有常规文件与目录进 %files：ghost 与 missingok 在解包树里没有实体，
# 照抄会让 rpmbuild 在「文件不存在」处失败。
gd_files()
{
    local rpm="$1" list="$2"
    rpm -qp --qf '[%{FILENAMES}\t%{FILEFLAGS:fflags}\n]' "$rpm" |
        awk -F'\t' '$2 !~ /[gm]/ { print $1 }' >"$list"
    [ -s "$list" ]
}

gd_spec()
{
    local rpm="$1" tree="$2" list="$3" spec="$4"
    local name ver rel lic sum arch
    name="$(gd_meta "$rpm" NAME)" || return 1
    ver="$(gd_meta "$rpm" VERSION)" || return 1
    rel="$(gd_meta "$rpm" RELEASE)" || return 1
    lic="$(gd_meta "$rpm" LICENSE)" || return 1
    sum="$(gd_meta "$rpm" SUMMARY)" || return 1
    arch="$(gd_meta "$rpm" ARCH)" || return 1
    : >"$spec"
    {
        printf 'Name: %s\n' "$name"
        printf 'Version: %s\n' "$ver"
        printf 'Release: %s.%s\n' "$rel" "$GD_TAG"
        printf 'Summary: %s\n' "$sum"
        printf 'License: %s\n' "$lic"
        printf 'BuildArch: %s\n' "$arch"
        printf 'AutoReqProv: no\n'
        printf 'Requires: coreutils\n\n'
        printf '%%description\n'
        printf '%s（载荷兜底重打包：上游 scriptlet 缺失败兜底，见\n' "$sum"
        printf 'distro/scripts/lib/guard.sh；内容与上游同版本一致）\n\n'
        printf '%%prep\n%%build\n%%install\n'
        printf 'mkdir -p %%{buildroot}\n'
        printf 'cp -a %s/. %%{buildroot}/\n\n' "$tree"
        printf '%%files -f %s\n\n' "$list"
        # 目录 mtime 只影响图标/声音缓存的失效判断，失败不应连累事务。
        printf '%%post\n'
        printf 'touch --no-create /usr/share/sounds/freedesktop'
        printf ' /usr/share/sounds || :\n\n'
        printf '%%postun\n'
        printf 'touch --no-create /usr/share/sounds/freedesktop'
        printf ' /usr/share/sounds || :\n'
    } >>"$spec"
}

gd_build()
{
    local work="$1" spec="$2"
    mkdir -p "${work}/rpmbuild"
    rpmbuild -bb --quiet \
        --define "_topdir ${work}/rpmbuild" \
        --define "_sourcedir ${work}" \
        --define "_rpmdir ${work}/out" \
        --define "_build_id_links none" \
        --define "debug_package %{nil}" \
        "$spec" >"${work}/rpmbuild.log" 2>&1
}

gd_names()
{
    local old="$1" new="$2" n
    local -a keep=()
    for n in "${NAMES[@]}"; do
        [ "$n" = "$old" ] && continue
        keep+=("$n")
    done
    keep+=("$new")
    NAMES=("${keep[@]}")
}

gd_verify()
{
    local old="$1" new="$2" a b
    rpm -qp --scripts "$new" | grep -q '|| :' || {
        printf 'guard: 重打包后 scriptlet 仍无兜底: %s\n' "$new" >&2
        return 1
    }
    a="$(rpm -qp --qf '[%{FILENAMES}\n]' "$old" | sort | sha256sum)"
    b="$(rpm -qp --qf '[%{FILENAMES}\n]' "$new" | sort | sha256sum)"
    if [ "$a" != "$b" ]; then
        printf 'guard: 重打包改变了文件集合: %s\n' "$new" >&2
        return 1
    fi
    printf '载荷兜底: %s -> %s\n' "$(basename "$old")" "$(basename "$new")"
}

guard_payload()
{
    local pkg="$1" work="$2"
    local src tree list spec out new
    src="$(gd_find "$pkg" "$GD_NAME")" || {
        printf '载荷兜底: 未发现 %s，跳过\n' "$GD_NAME"
        return 0
    }
    need rpmbuild
    need rpm2cpio
    need cpio
    work="${work}/guard"
    rm -rf "$work"
    tree="${work}/tree"
    list="${work}/files.list"
    spec="${work}/${GD_NAME}.spec"
    gd_extract "$src" "$tree" || return 1
    gd_files "$src" "$list" || return 1
    gd_spec "$src" "$tree" "$list" "$spec" || return 1
    gd_build "$work" "$spec" || return 1
    out="$(find "${work}/out" -type f -name "${GD_NAME}-*.rpm" | sort | head -n1)"
    if [ -z "$out" ]; then
        printf 'guard: 重打包未产出 RPM（日志 %s/rpmbuild.log）\n' "$work" >&2
        return 1
    fi
    gd_verify "$src" "$out" || return 1
    new="$(basename "$out")"
    rm -f "$src"
    cp -p "$out" "${pkg}/${new}"
    gd_names "$(basename "$src")" "$new"
}
