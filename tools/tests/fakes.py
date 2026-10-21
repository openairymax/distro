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

TOOLS = ("awk", "base64", "basename", "bash", "cat", "cmp", "cp", "date",
         "dirname", "find", "git", "grep", "head", "mkdir", "mv", "python3",
         "rm", "sed", "seq", "sha256sum", "sleep", "sort", "tail", "timeout",
         "tr", "uname")

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
    python3 - "$a" "$body" <<'PY'
import base64, sys
from pathlib import Path
root = Path(sys.argv[1])
if root.is_file():
    files = [(root.name, root)]
else:
    files = [(f"{root.name}/{p.relative_to(root)}", p)
             for p in sorted(root.rglob("*")) if p.is_file()]
with open(sys.argv[2], "ab") as out:
    for name, path in files:
        raw = path.read_bytes()
        out.write(f"=== /{name}\\n".encode())
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if text.endswith("\\n") and "=== " not in text \\
                 and not text.startswith("@@base64"):
            out.write(raw)
        else:
            out.write(b"@@base64\\n" + base64.encodebytes(raw))
PY
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

# 真实 createrepo_c 按 --general-compress-type 压缩 group 元数据，并在
# repomd.xml 里用 location 指向该文件。伪工具必须复刻这一布局，否则
# 「载荷 comps 是否仍带环境」这类断言测的不是真实产物。
# FAKE_CREATEREPO_MODE=noenv 模拟 comps 环境段被丢弃，用于验证门禁。
CREATEREPO = """\
#!/bin/sh
grp=""; repo=""; ct="gz"
while [ $# -gt 0 ]; do
    case "$1" in
    --groupfile) shift; grp=$1 ;;
    --general-compress-type) shift; ct=$1 ;;
    --general-compress-type=*) ct=${1#*=} ;;
    -*) ;;
    *) repo=$1 ;;
    esac
    shift
done
mode=${FAKE_CREATEREPO_MODE:-ok}
[ "$mode" = fail ] && exit 1
[ -n "$repo" ] && [ -d "$repo" ] || exit 2
if [ -n "$grp" ] && [ ! -f "$grp" ]; then
    exit 3
fi
mkdir -p "$repo/repodata"
href=""
if [ -n "$grp" ]; then
    cp "$grp" "$repo/repodata/comps.xml"
    if [ "$mode" = noenv ]; then
        python3 - "$repo/repodata/comps.xml" <<'PY'
import re, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    raw = fh.read()
raw = re.sub(r"(?s)<environment\\b.*?</environment>", "", raw)
with open(path, "w", encoding="utf-8") as fh:
    fh.write(raw)
PY
    fi
    href="repodata/comps.xml"
    if [ "$ct" = gz ]; then
        python3 - "$repo/repodata/comps.xml" <<'PY'
import gzip, sys
path = sys.argv[1]
with open(path, "rb") as fh:
    raw = fh.read()
with gzip.open(path + ".gz", "wb") as fh:
    fh.write(raw)
PY
        rm -f "$repo/repodata/comps.xml"
        href="repodata/comps.xml.gz"
    fi
fi
if [ -n "$href" ]; then
    printf '<repomd><data type="group"><location href="%s"/></data></repomd>\\n' \\
        "$href" > "$repo/repodata/repomd.xml"
else
    printf '<repomd/>\\n' > "$repo/repodata/repomd.xml"
fi
"""

# dnf 在闭包收割里承担两件事：解出安装事务，并把事务里的 RPM 落到
# --downloaddir。伪工具必须同时校验调用前提，否则 build-desktop 的顺序
# 一旦回退（例如收割早于 createrepo_c），测试仍会通过而装机现场才失败。
DNF = """\
#!/bin/sh
set -u
dl=""; root=""; repos=""; pkg=""; excl=""; specs=""
while [ $# -gt 0 ]; do
    case "$1" in
    --downloaddir=*) dl=${1#*=} ;;
    --downloaddir) shift; dl=$1 ;;
    --installroot=*) root=${1#*=} ;;
    --installroot) shift; root=$1 ;;
    --setopt=reposdir=*) repos=${1#--setopt=reposdir=} ;;
    --setopt=*) ;;
    --repofrompath=*) pkg=${1#*,} ;;
    --exclude=*) excl=${1#*=} ;;
    --exclude) shift; excl=$1 ;;
    --releasever|--forcearch) shift ;;
    -*) ;;
    *) specs="$specs $1" ;;
    esac
    shift
done
if [ -n "${FAKE_DNF_LOG:-}" ]; then
    printf 'dl=%s pkg=%s specs=%s excl=%s\\n' \\
        "$dl" "$pkg" "$specs" "$excl" >> "$FAKE_DNF_LOG"
fi
[ -n "$dl" ] && [ -n "$root" ] && [ -n "$pkg" ] || exit 4
[ -f "$pkg/repodata/repomd.xml" ] || {
    printf 'dnf: 本地仓库尚未索引: %s\\n' "$pkg" >&2; exit 6; }
[ -d "$repos" ] || { printf 'dnf: reposdir 缺失\\n' >&2; exit 7; }
cfg=""
for f in "$repos"/*.repo; do
    [ -f "$f" ] || continue
    cfg="$cfg$(cat "$f")"
done
case "$cfg" in
*airymaxos-offline*)
    printf 'dnf: 离线自引用仓库未剔除\\n' >&2; exit 8 ;;
esac
case "$cfg" in
*"[baseos]"*) ;;
*) printf 'dnf: 缺 baseos 仓库\\n' >&2; exit 9 ;;
esac
# 配方里的 @^环境 只在 anaconda 成立；dnf 命令行把它当组名 ^环境 求解。
# 伪工具必须复刻这一拒绝语义，否则收割器漏做环境展开时 L0 仍会全绿，
# 直到镜像 CI 才暴露。
case "$specs" in
*"@^"*)
    env=${specs#*@^}
    printf "dnf: Module or Group '^%s' is not available.\\n" "${env%% *}" >&2
    printf 'dnf: Nothing to do.\\n' >&2
    exit 14 ;;
esac
case " $specs " in
*" @airymax-desktop-core "*) ;;
*) printf 'dnf: 缺 @airymax-desktop-core 组\\n' >&2; exit 10 ;;
esac
case " $specs " in
*" @airymax-desktop "*) ;;
*) printf 'dnf: 缺 @airymax-desktop 组\\n' >&2; exit 15 ;;
esac
case "$specs" in
*"@core"*) ;;
*) printf 'dnf: 缺 @core 组\\n' >&2; exit 11 ;;
esac
case "$excl" in
*kernel*) ;;
*) printf 'dnf: 缺 kernel 排除项\\n' >&2; exit 12 ;;
esac
case "$excl" in
*kylin-ai*) ;;
*) printf 'dnf: 缺 kylin-ai 排除项\\n' >&2; exit 13 ;;
esac
case "${FAKE_DNF_MODE:-ok}" in
fail) printf 'dnf: 依赖解析失败\\n' >&2; exit 1 ;;
empty) exit 0 ;;
esac
for r in gstreamer1-plugins-good-1.20.3-6.oe2403sp2.x86_64.rpm \\
    ukui-clock-3.1.3-3.oe2403sp2.x86_64.rpm \\
    airymaxos-system-0.0.3-1.noarch.rpm; do
    printf 'rpm %s\\n' "$r" > "$dl/$r"
done
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
on { print }' > "$dest" || { rm -f "$body"; exit 3; }
rm -f "$body"
if [ "$(head -n 1 "$dest")" = "@@base64" ]; then
    tail -n +2 "$dest" | base64 -d > "${dest}.raw" || exit 4
    mv "${dest}.raw" "$dest"
fi
"""

# isomd5sum 把校验和写在 PVD 应用数据区，而该区域落在被校验的区间内。
# 真实工具在计算摘要前先把整个应用数据区抹成空格，写入之后再放入记录，
# 因此「植入」与「复核」对同一镜像得到相同摘要。伪工具必须复刻这一抹平
# 语义，否则记录区一旦落入校验区间（验收夹具使镜像变大时即会发生），
# 两边摘要必然不同。
ISOMD5_LIB = r'''import hashlib, re, struct, sys
from pathlib import Path

SECTOR = 2048
SKIP = 15
APP_OFF = 883
APP_LEN = 512


def load(path):
    data = bytearray(Path(path).read_bytes())
    pvd = 16 * SECTOR
    if len(data) < pvd + SECTOR or bytes(data[pvd:pvd + 6]) != b"\x01CD001":
        sys.stderr.write("ERROR: Could not find primary volume!\n")
        sys.exit(1)
    vol = struct.unpack("<I", data[pvd + 80:pvd + 84])[0] * SECTOR
    return data, pvd, vol


def blank(data, pvd):
    data[pvd + APP_OFF:pvd + APP_OFF + APP_LEN] = b" " * APP_LEN


def digest(data, vol):
    end = vol - SKIP * SECTOR
    if end > len(data):
        sys.stderr.write("ERROR: ISO is truncated\n")
        sys.exit(1)
    return hashlib.md5(bytes(data[:end])).hexdigest()
'''

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
""" + ISOMD5_LIB + r"""data, pvd, vol = load(sys.argv[1])
if sys.argv[2] != "1" and bytes(data[pvd + APP_OFF:pvd + APP_OFF + APP_LEN]) \
        != b" " * APP_LEN:
    sys.stderr.write(
        "ERROR: Application data has been used - not implanting md5sum!\n")
    sys.exit(1)
blank(data, pvd)
hexsum = digest(data, vol).encode()
rec = b"ISO MD5SUM = " + hexsum + b";SKIPSECTORS = 15;RHLISOSTATUS=0;"
rec += b" " * (APP_LEN - len(rec))
data[pvd + APP_OFF:pvd + APP_OFF + APP_LEN] = rec
Path(sys.argv[1]).write_bytes(data)
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
""" + ISOMD5_LIB + r"""data, pvd, vol = load(sys.argv[1])
found = re.search(r"ISO MD5SUM = ([0-9a-f]{32})",
                  data[pvd + APP_OFF:pvd + APP_OFF + APP_LEN]
                  .decode("latin-1"))
if not found:
    sys.stderr.write("ERROR: No checksum found\n")
    sys.exit(1)
blank(data, pvd)
if found.group(1) != digest(data, vol):
    sys.stderr.write("ERROR: Checksum mismatch\n")
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
    bootloader) printf '安装引导装载程序时发生以下错误。系统将无法引导。\\n' \\
            > "$log"
        printf 'failed to write boot loader configuration\\n' >> "$log"
        printf "请回答 'yes' 或 'no': " >> "$log"; exec sleep 60 ;;
    payload) printf '安装负载时出现以下错误。这是个致命错误，安装将中止。\\n' \\
            > "$log"
        printf 'Failed to download the following packages:\\n' >> "$log"
        printf 'ukui-clock-3.1.3-3.oe2403sp2.x86_64: ' >> "$log"
        printf 'Cannot download, all mirrors were already tried without ' \\
            >> "$log"
        printf 'success\\n按 ENTER 退出:\\n' >> "$log"; exec sleep 60 ;;
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
    write(bin_dir, "dnf", DNF)


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
