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
         "sha256sum", "sleep", "sort", "tail", "timeout", "tr", "uname")

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
body=$out.body
{
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
} > "$body"
for a in $adds; do
    [ -e "$a" ] || continue
    if [ -d "$a" ]; then
        name=$(basename "$a")
        find "$a" -type f | sort | while IFS= read -r f; do
            rel=${f#"$a"/}
            printf '=== /%s/%s\\n' "$name" "$rel"
            cat "$f"
        done >> "$body"
    else
        printf '=== /%s\\n' "$(basename "$a")" >> "$body"
        cat "$a" >> "$body"
    fi
done
python3 - "$out" "$body" "$p2" <<'PY' || exit 5
import struct, sys
from pathlib import Path
body = Path(sys.argv[2]).read_bytes()
total = 17 + (len(body) + 2047) // 2048
pvd = bytearray(2048)
pvd[0] = 1
pvd[1:6] = b"CD001"
pvd[6] = 1
pvd[80:84] = struct.pack("<I", total)
pvd[84:88] = struct.pack(">I", total)
src = Path(sys.argv[3])
if src.is_file():
    raw = src.read_bytes()
    off = 16 * 2048
    if len(raw) >= off + 2048 and raw[off:off + 6] == b"\\x01CD001":
        pvd[883:1395] = raw[off + 883:off + 1395]
img = b"\\0" * (16 * 2048) + bytes(pvd) + body
img += b"\\0" * (-len(img) % 2048)
Path(sys.argv[1]).write_bytes(img)
PY
rm -f "$body"
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
body=${TMPDIR:-/tmp}/xorriso.$$
python3 - "$indev" "$body" <<'PY'
import struct, sys
data = open(sys.argv[1], "rb").read()
vol = struct.unpack("<I", data[16 * 2048 + 80:16 * 2048 + 84])[0]
with open(sys.argv[2], "wb") as fh:
    fh.write(data[17 * 2048:vol * 2048])
PY
grep -qxF "=== ${path}" "$body" || { rm -f "$body"; exit 1; }
tr -d '\\000' < "$body" |
    awk -v p="$path" '$0 == "=== " p { on = 1; next }
on && /^=== / { exit }
on { print }' > "$dest"
rm -f "$body"
"""

IMPLANT = """\
#!/bin/sh
force=0; img=""
while [ $# -gt 0 ]; do
    case "$1" in
    --force|-f) force=1 ;;
    --supported-iso|-S) ;;
    -*) ;;
    *) img=$1 ;;
    esac
    shift
done
[ -n "$img" ] || exit 2
[ "${FAKE_IMPLANT_MODE:-ok}" = fail ] && exit 1
python3 - "$img" "$force" <<'PY'
import hashlib, struct, sys
from pathlib import Path
path = Path(sys.argv[1])
force = sys.argv[2] == "1"
data = bytearray(path.read_bytes())
off = 16 * 2048
if len(data) < off + 2048 or data[off:off + 6] != b"\\x01CD001":
    sys.stderr.write("ERROR: Could not find primary volume!\\n")
    sys.exit(1)
vol = struct.unpack("<I", data[off + 80:off + 84])[0] * 2048
app = data[off + 883:off + 1395]
if not force and any(b != 0x20 for b in app):
    sys.stderr.write(
        "ERROR: Application data has been used - not implanting md5sum!\\n")
    sys.exit(1)
end = vol - 15 * 2048
if end > len(data):
    sys.stderr.write("ERROR: ISO is truncated\\n")
    sys.exit(1)
digest = hashlib.md5(bytes(data[:end])).hexdigest().encode()
rec = b"ISO MD5SUM = " + digest + b";SKIPSECTORS = 15;RHLISOSTATUS=0;"
rec += b" " * (512 - len(rec))
data[off + 883:off + 1395] = rec
path.write_bytes(data)
PY
"""

CHECKISOMD5 = """\
#!/bin/sh
img=""
while [ $# -gt 0 ]; do
    case "$1" in
    --md5sumonly|-o|--verbose|-v|--gauge|-g) ;;
    -*) printf 'bad option %s: unknown option\\n' "$1" >&2; exit 1 ;;
    *) img=$1 ;;
    esac
    shift
done
[ -n "$img" ] || exit 2
[ "${FAKE_CHECK_MODE:-ok}" = fail ] && exit 1
python3 - "$img" <<'PY'
import hashlib, re, struct, sys
from pathlib import Path
data = Path(sys.argv[1]).read_bytes()
off = 16 * 2048
vol = struct.unpack("<I", data[off + 80:off + 84])[0] * 2048
app = data[off + 883:off + 1395].decode("latin-1")
found = re.search(r"ISO MD5SUM = ([0-9a-f]{32})", app)
if not found:
    sys.stderr.write("ERROR: No checksum found\\n")
    sys.exit(1)
digest = hashlib.md5(data[:vol - 15 * 2048]).hexdigest()
if found.group(1) != digest:
    sys.stderr.write("ERROR: Checksum mismatch\\n")
    sys.exit(1)
PY
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
    postfail) printf 'AIRYMAX-INSTALL-FAIL rc=1\\n' > "$log"; exec sleep 60 ;;
    panic) printf 'Kernel panic - not syncing\\n' > "$log"; exec sleep 60 ;;
    scriptlet) printf '正在配置 firewalld.noarch\\n' > "$log"
        printf 'Error in POSTTRANS scriptlet in rpm package firewalld\\n' \\
            >> "$log"
        printf '按 ENTER 退出:\\n' >> "$log"; exec sleep 60 ;;
    hang) printf '正在配置 firewalld.noarch\\n' > "$log"; exec sleep 60 ;;
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
ok) printf 'AirymaxOS login:\\nAIRYMAX-DESKTOP-READY unit=lightdm ' > "$log"
    printf 'class=greeter type=x11\\n' >> "$log" ;;
login-only) printf 'AirymaxOS login:\\n' > "$log" ;;
desktop-fail) printf 'AirymaxOS login:\\nAIRYMAX-DESKTOP-FAIL reason=session ' > "$log"
    printf 'path=/usr/share/xsessions/ukui.desktop\\n' >> "$log" ;;
smoke-pass) printf 'AirymaxOS login:\\nAIRYMAX-SMOKE-PASS ' > "$log"
    printf 'tap=/var/log/airymax/smoke.tap\\n' >> "$log" ;;
smoke-fail) printf 'AirymaxOS login:\\nAIRYMAX-SMOKE-FAIL reason=tap ' > "$log"
    printf 'tap=/var/log/airymax/smoke.tap\\n' >> "$log" ;;
panic) printf 'Kernel panic - not syncing\\n' > "$log" ;;
failed) printf '[FAILED] Failed to start airy.service\\n' > "$log" ;;
nomarker) printf 'booting\\n' > "$log" ;;
slow) sleep 2; printf 'login:\\n' > "$log" ;;
desktop-slow) sleep 2
    printf 'AirymaxOS login:\\nAIRYMAX-DESKTOP-READY unit=lightdm\\n' > "$log" ;;
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
cmd=""; prop=""
while [ $# -gt 0 ]; do
    case "$1" in
    list-sessions|show-session) cmd=$1 ;;
    -p) shift; prop=$1 ;;
    -*) ;;
    esac
    shift
done
if [ "$cmd" = list-sessions ]; then
    [ "${FAKE_SESSIONS_ON:-1}" = 0 ] && exit 0
    printf '%s\\n' "${FAKE_SESSIONS:-1 1000 airymax seat0}"
    exit 0
fi
case "$prop" in
Type) printf '%s\\n' "${FAKE_TYPE:-x11}" ;;
Service) printf '%s\\n' "${FAKE_SERVICE:-lightdm}" ;;
Class) printf '%s\\n' "${FAKE_CLASS:-greeter}" ;;
State) printf '%s\\n' "${FAKE_STATE:-active}" ;;
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

GSETTINGS = """\
#!/bin/sh
[ "${FAKE_GSETTINGS:-ok}" = ok ] || {
    printf "No such schema 'org.mate.background'\\n" >&2
    exit 1
}
printf "'%s'\\n" \\
    "${FAKE_PAPER:-/usr/share/backgrounds/airymaxos/airymaxos-default.jpg}"
"""

SHA256SUM = """\
#!/bin/sh
[ "${FAKE_SHA256SUM:-ok}" = ok ] || exit 1
printf '%s  %s\\n' \\
    "${FAKE_PAPER_SHA:-fee7f439834ac7dacfc75deaf80a1db1c4bc7459583248eecc87125d52a5ef18}" \\
    "$1"
"""

SYSTEMCTL = """\
#!/bin/sh
cmd=""; unit=""; prop=""; quiet=0
while [ $# -gt 0 ]; do
    case "$1" in
    show|is-active) cmd=$1 ;;
    -p) shift; prop=$1 ;;
    -q|--quiet) quiet=1 ;;
    -*) ;;
    *) unit=$1 ;;
    esac
    shift
done
case "$cmd" in
is-active)
    state=${FAKE_SLICE_ACTIVE:-active}
    [ "$unit" = lightdm.service ] && state=${FAKE_LIGHTDM:-active}
    [ "$quiet" -eq 1 ] || printf '%s\\n' "$state"
    [ "$state" = active ] && exit 0
    exit 3
    ;;
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
    if path.is_symlink() or path.exists():
        path.unlink()
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def iso_tools(bin_dir):
    write(bin_dir, "mkksiso", MKKSISO)
    write(bin_dir, "xorriso", XORRISO)
    write(bin_dir, "implantisomd5", IMPLANT)
    write(bin_dir, "checkisomd5", CHECKISOMD5)


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
             ("pactl", PACTL), ("systemctl", SYSTEMCTL),
             ("gsettings", GSETTINGS), ("sha256sum", SHA256SUM))
    for name, body in table:
        if name not in omit:
            write(bin_dir, name, body)
