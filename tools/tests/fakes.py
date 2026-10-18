#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# fakes.py — PATH 沙箱中的伪工具
#
# 镜像工具、QEMU 与固件在开发机和 CI 中未必可用，而各驱动的退出码、
# 产物布局与校验语义属于对外契约。把伪工具集中在这里，避免多个测试
# 文件各自维护一份而出现语义漂移。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import shutil
from pathlib import Path

TOOLS = ("awk", "basename", "bash", "cat", "cmp", "cp", "date", "dirname",
         "find", "git", "grep", "mkdir", "mv", "python3", "rm", "sed", "seq",
         "sha256sum", "sleep", "sort", "timeout", "uname")

MKKSISO = """\
#!/bin/sh
n=0
vol=""; cmd=""; adds=""
while [ $# -gt 0 ]; do
    case "$1" in
    -V) shift; vol=$1 ;;
    -c) shift; cmd=$1 ;;
    -a) shift; adds="${adds} $1" ;;
    -*) ;;
    *) n=$((n + 1)); eval "p$n=\\$1" ;;
    esac
    shift
done
[ "${FAKE_MKKSISO_MODE:-ok}" = fail ] && exit 3
ks=$p1; out=$p3
[ -n "$ks" ] && [ -n "$out" ] || exit 4
stage=$vol
ksline="inst.ks=hd:LABEL=${vol}:/ks.cfg"
case "${FAKE_MKKSISO_MODE:-ok}" in
badlabel) stage=OLDVOLID ;;
nostage) ksline="" ;;
esac
{
    printf 'AIRYFAKE1\\n'
    printf 'CMDLINE=%s\\n' "$cmd"
    printf '=== /ks.cfg\\n'
    if [ "${FAKE_MKKSISO_MODE:-ok}" = badks ]; then
        printf 'lang zh_CN.UTF-8\\n'
    else
        cat "$ks"
    fi
    printf '=== /isolinux/isolinux.cfg\\n'
    printf 'append %s inst.stage2=hd:LABEL=%s quiet\\n' "$ksline" "$stage"
    printf '=== /EFI/BOOT/grub.cfg\\n'
    printf 'linuxefi /vmlinuz %s inst.stage2=hd:LABEL=%s\\n' \\
        "$ksline" "$stage"
} > "$out"
for a in $adds; do
    [ -e "$a" ] || continue
    if [ -d "$a" ]; then
        name=$(basename "$a")
        find "$a" -type f | sort | while IFS= read -r f; do
            rel=${f#"$a"/}
            printf '=== /%s/%s\\n' "$name" "$rel"
            cat "$f"
        done >> "$out"
    else
        printf '=== /%s\\n' "$(basename "$a")" >> "$out"
        cat "$a" >> "$out"
    fi
done
if [ -n "${FAKE_MKKSISO_LOG:-}" ]; then
    printf 'volid=%s cmd=%s\\n' "$vol" "$cmd" > "$FAKE_MKKSISO_LOG"
fi
"""

CREATEREPO = """\
#!/bin/sh
grp=""; repo=""
while [ $# -gt 0 ]; do
    case "$1" in
    --groupfile) shift; grp=$1 ;;
    -*) ;;
    *) repo=$1 ;;
    esac
    shift
done
[ "${FAKE_CREATEREPO_MODE:-ok}" = fail ] && exit 1
[ -n "$repo" ] && [ -d "$repo" ] || exit 2
if [ -n "$grp" ] && [ ! -f "$grp" ]; then
    exit 3
fi
mkdir -p "$repo/repodata"
printf 'repomd\\n' > "$repo/repodata/repomd.xml"
if [ -n "$grp" ]; then
    cp "$grp" "$repo/repodata/comps.xml"
    printf '<data type="group"/>\\n' >> "$repo/repodata/repomd.xml"
fi
"""

XORRISO = """\
#!/bin/sh
indev=""; path=""; dest=""
while [ $# -gt 0 ]; do
    case "$1" in
    -indev) shift; indev=$1 ;;
    -extract) shift; path=$1; shift; dest=$1 ;;
    esac
    shift
done
[ -n "$indev" ] && [ -n "$path" ] && [ -n "$dest" ] || exit 2
grep -qxF "=== ${path}" "$indev" || exit 1
awk -v p="$path" '$0 == "=== " p { on = 1; next }
on && /^=== / { exit }
on { print }' "$indev" > "$dest"
"""

IMPLANT = """\
#!/bin/sh
[ "${FAKE_IMPLANT_MODE:-ok}" = fail ] && exit 1
printf 'IMPLANTED\\n' > "$1.imp"
cat "$1" >> "$1.imp"
mv "$1.imp" "$1"
"""

GPG = """\
#!/bin/sh
out=""
while [ $# -gt 0 ]; do
    case "$1" in
    --output) shift; out=$1 ;;
    esac
    shift
done
[ -n "$out" ] || exit 1
printf 'signature\\n' > "$out"
"""

QEMU = """\
#!/bin/sh
log=""; boot=""; nv=""
while [ $# -gt 0 ]; do
    [ -n "${FAKE_QEMU_LOG:-}" ] && printf '%s\\n' "$1" >> "$FAKE_QEMU_LOG"
    case "$1" in
    -serial) shift; log=${1#file:} ;;
    -boot) shift; boot=$1 ;;
    *vars.fd) nv=${1#*file=} ;;
    esac
    shift
done
[ -n "$log" ] || exit 0
if [ "$boot" = "order=d" ]; then
    case "${FAKE_QEMU_INSTALL_MODE:-ok}" in
    fail) exit 1 ;;
    nomarker) printf 'installing\\n' > "$log"; exit 0 ;;
    esac
    printf 'install complete\\n' > "$log"
    [ -n "$nv" ] && printf 'BOOTENTRY\\n' >> "$nv"
    exit 0
fi
if [ -n "$nv" ] && ! grep -q BOOTENTRY "$nv"; then
    printf 'nvram lost\\n' > "$log"
    exit 1
fi
case "${FAKE_QEMU_BOOT_MODE:-ok}" in
ok) printf 'AirymaxOS login:\\n' > "$log" ;;
panic) printf 'Kernel panic - not syncing\\n' > "$log" ;;
failed) printf '[FAILED] Failed to start airy.service\\n' > "$log" ;;
nomarker) printf 'booting\\n' > "$log" ;;
slow) sleep 2; printf 'login:\\n' > "$log" ;;
hang) printf 'booting\\n' > "$log"; exec sleep 60 ;;
esac
exit 0
"""

QEMU_IMG = """\
#!/bin/sh
[ "${FAKE_QEMU_IMG_MODE:-ok}" = fail ] && exit 1
disk=""
while [ $# -gt 0 ]; do
    case "$1" in
    create|-f|qcow2|[0-9]*G) ;;
    *) disk=$1 ;;
    esac
    shift
done
[ -n "$disk" ] || exit 1
printf 'qcow2\\n' > "$disk"
"""

LOGINCTL = """\
#!/bin/sh
prop=""
while [ $# -gt 0 ]; do
    case "$1" in
    -p) shift; prop=$1 ;;
    esac
    shift
done
case "$prop" in
Type) printf '%s\\n' "${FAKE_TYPE:-x11}" ;;
Service) printf '%s\\n' "${FAKE_SERVICE:-lightdm}" ;;
Active) printf '%s\\n' "${FAKE_ACTIVE:-yes}" ;;
*) exit 1 ;;
esac
"""

PGREP = """\
#!/bin/sh
mode=""; pat=""
while [ $# -gt 0 ]; do
    case "$1" in
    -x|-f) mode=$1 ;;
    -*) ;;
    *) pat=$1; break ;;
    esac
    shift
done
[ -n "$pat" ] || exit 1
case " ${FAKE_PROCS:-} " in
*" ${pat} "*) exit 0 ;;
esac
[ "$mode" = "-f" ] || exit 1
case "${FAKE_PROCS:-}" in
*"${pat}"*) exit 0 ;;
esac
exit 1
"""

XDPYINFO = """\
#!/bin/sh
case "${FAKE_XDPYINFO:-ok}" in
ok) printf 'name of display: %s\\n' "${DISPLAY:-:0}" ;;
*)
    printf 'xdpyinfo: unable to open display "%s"\\n' "${DISPLAY:-}" >&2
    exit 1
    ;;
esac
"""

FCITX_REMOTE = """\
#!/bin/sh
[ "${FAKE_FCITX_REMOTE:-ok}" = ok ] || {
    printf 'fcitx-remote: cannot connect to fcitx\\n' >&2
    exit 1
}
printf '%s\\n' "${FAKE_FCITX_STATE:-2}"
"""

PACTL = """\
#!/bin/sh
[ "${FAKE_PACTL:-ok}" = ok ] || {
    printf 'Connection failure: Connection refused\\n' >&2
    exit 1
}
printf 'Server Name: pulseaudio\\n'
"""

SYSTEMCTL = """\
#!/bin/sh
cmd=""; unit=""; prop=""
while [ $# -gt 0 ]; do
    case "$1" in
    show|is-active) cmd=$1 ;;
    -p) shift; prop=$1 ;;
    -*) ;;
    *) unit=$1 ;;
    esac
    shift
done
case "$cmd" in
is-active) printf '%s\\n' "${FAKE_SLICE_ACTIVE:-active}" ;;
show)
    case "$prop" in
    Slice) printf '%s\\n' "${FAKE_SLICE:-airymax-desktop.slice}" ;;
    CPUWeight) printf '%s\\n' "${FAKE_CPU:-50}" ;;
    IOWeight) printf '%s\\n' "${FAKE_IO:-50}" ;;
    TasksMax) printf '%s\\n' "${FAKE_TASKS:-40%}" ;;
    *) exit 1 ;;
    esac
    ;;
*) exit 1 ;;
esac
"""


def link_tools(bin_dir):
    for name in TOOLS:
        src = shutil.which(name)
        if src:
            (bin_dir / name).symlink_to(src)


def write(bin_dir, name, body):
    path = Path(bin_dir) / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def iso_tools(bin_dir):
    write(bin_dir, "mkksiso", MKKSISO)
    write(bin_dir, "xorriso", XORRISO)
    write(bin_dir, "implantisomd5", IMPLANT)


def desk_tools(bin_dir):
    iso_tools(bin_dir)
    write(bin_dir, "createrepo_c", CREATEREPO)


def qemu_tools(bin_dir, arch="x86_64", qemu=True):
    write(bin_dir, "qemu-img", QEMU_IMG)
    if qemu:
        write(bin_dir, f"qemu-system-{arch}", QEMU)


def smoke_tools(bin_dir, omit=()):
    table = (("loginctl", LOGINCTL), ("pgrep", PGREP),
             ("xdpyinfo", XDPYINFO), ("fcitx-remote", FCITX_REMOTE),
             ("pactl", PACTL), ("systemctl", SYSTEMCTL))
    for name, body in table:
        if name not in omit:
            write(bin_dir, name, body)
