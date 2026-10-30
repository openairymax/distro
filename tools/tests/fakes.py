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

TOOLS = ("awk", "base64", "basename", "bash", "cat", "cmp", "cp", "cut",
         "date", "dd", "dirname", "find", "git", "grep", "head", "mkdir",
         "mv", "od", "python3", "readlink", "rm", "sed", "seq", "sha256sum",
         "sleep", "sort", "stat", "tail", "tee", "timeout", "tr", "truncate",
         "uname", "wc")

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
    printf 'default=1\\ntimeout 600\\n'
    printf 'label 0\\n'
    printf '  menu label ^Install openEuler 24.03-LTS-SP2\\n'
    printf '  append %s inst.stage2=hd:LABEL=%s quiet\\n' "$ksline" "$stage"
    printf 'label 1\\n'
    printf '  menu label Test this media & install openEuler 24.03-LTS-SP2\\n'
    printf '  append %s inst.stage2=hd:LABEL=%s rd.live.check quiet\\n' \\
        "$ksline" "$stage"
    printf '=== /EFI/BOOT/grub.cfg\\n'
    printf 'set default="1"\\nset timeout=60\\n'
    printf "menuentry 'Install openEuler 24.03-LTS-SP2' {\\n"
    printf '    linuxefi /vmlinuz %s inst.stage2=hd:LABEL=%s\\n' \\
        "$ksline" "$stage"
    printf '}\\n'
    printf "menuentry 'Test this media & install openEuler 24.03-LTS-SP2' {\\n"
    printf '    linuxefi /vmlinuz %s inst.stage2=hd:LABEL=%s rd.live.check\\n' \\
        "$ksline" "$stage"
    printf '}\\n'
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
python3 - "$out" "$body" "$p2" "$vol" <<'PY' || exit 5
import struct, sys
from pathlib import Path
body = Path(sys.argv[2]).read_bytes()
total = 17 + (len(body) + 2047) // 2048
pvd = bytearray(2048)
pvd[0] = 1
pvd[1:6] = b"CD001"
pvd[6] = 1
pvd[40:72] = sys.argv[4].encode()[:32].ljust(32, b" ")
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

# 真实 createrepo_c 按 --general-compress-type 压缩元数据，并在 repomd.xml
# 里用 location 指向该文件；repomd 带默认命名空间，伪工具必须连命名空间
# 一起复刻，否则「载荷 comps 是否仍带环境」这类断言测的不是真实产物。
# 真实工具同时按目录内的 RPM 生成 primary 元数据，包名来自文件名的 NVR；
# 载荷的 comps 成员校验读的正是它，因此伪工具也要生成。
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
python3 - "$repo" "$grp" "$ct" "$mode" <<'PY'
import gzip, re, sys
from pathlib import Path

repo = Path(sys.argv[1])
grp = sys.argv[2]
ct = sys.argv[3]
mode = sys.argv[4]
meta = []


def emit(kind, name, raw):
    (repo / "repodata" / name).write_bytes(
        gzip.compress(raw) if ct == "gz" else raw)
    meta.append(f'<data type="{kind}">'
                f'<location href="repodata/{name}"/></data>')


if grp:
    raw = Path(grp).read_bytes()
    if mode == "noenv":
        raw = re.sub(rb"(?s)<environment\\b.*?</environment>", b"", raw)
    emit("group", "comps.xml.gz" if ct == "gz" else "comps.xml", raw)

names = set()
for rpm in sorted(repo.glob("*.rpm")):
    bits = rpm.name[:-4].rsplit(".", 1)[0].split("-")
    if len(bits) >= 3:
        names.add("-".join(bits[:-2]))
if names:
    body = "<metadata>" + "".join(
        f'<package type="rpm"><name>{n}</name></package>'
        for n in sorted(names)) + "</metadata>"
    emit("primary", "primary.xml.gz" if ct == "gz" else "primary.xml",
         body.encode("utf-8"))

(repo / "repodata" / "repomd.xml").write_text(
    '<repomd xmlns="http://linux.duke.edu/metadata/repo">'
    + "".join(meta) + "</repomd>\\n", encoding="utf-8")
PY
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
    # install 是 dnf 的子命令，不是待求解的包名；伪工具若把它当规格，
    # 就会凭空落一个 install-1.0-1.noarch.rpm，让载荷多出幽灵成员。
    install|reinstall|upgrade) ;;
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
if [ -n "${FAKE_DNF_CFG:-}" ]; then
    printf '%s\\n' "$cfg" > "$FAKE_DNF_CFG"
fi
case "$cfg" in
*airymaxos-offline*)
    printf 'dnf: 离线自引用仓库未剔除\\n' >&2; exit 8 ;;
esac
# 离线重放按 NEVRA 逐个点名，不按组求解：配方组与 baseos 仓库都不参与，
# 载荷只来自 reposdir 里的 file:// 池。伪工具据此分流——规格里没有 @ 时
# 按 NEVRA 在池内找同名包落进 dl，找不到即解析失败（真实 dnf 同语义）。
case "$specs" in
*@*) ;;
*)
    python3 - "$dl" "$repos" "$specs" <<'PY'
import sys
from pathlib import Path

dl, repos, specs = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].split()
dirs = [Path(line[len("baseurl=file://"):])
        for cfg in repos.glob("*.repo")
        for line in cfg.read_text(encoding="utf-8").splitlines()
        if line.startswith("baseurl=file://")]
for spec in specs:
    for base in dirs:
        hit = base / (spec + ".rpm")
        if hit.is_file():
            (dl / hit.name).write_bytes(hit.read_bytes())
            break
    else:
        print("dnf: 无匹配的包: %s" % spec, file=sys.stderr)
        sys.exit(1)
PY
    exit $?
    ;;
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
case " $specs " in
*" @airymax-core "*) ;;
*) printf 'dnf: 缺 @airymax-core 组\\n' >&2; exit 11 ;;
esac
case "$excl" in
*kernel*) ;;
*) printf 'dnf: 缺 kernel 排除项\\n' >&2; exit 12 ;;
esac
case "$excl" in
*kylin-ai*) ;;
*) printf 'dnf: 缺 kylin-ai 排除项\\n' >&2; exit 13 ;;
esac
# FAKE_DNF_REJECT 让伪 dnf 拒绝地址里含指定子串的快照：收割端每个镜像根
# 单独求解一次，本钩子用来驱动「首根失败即换下一个根」这条路径。
if [ -n "${FAKE_DNF_REJECT:-}" ]; then
    case "$cfg" in
    *"${FAKE_DNF_REJECT}"*)
        printf 'dnf: 快照不可用: %s\\n' "${FAKE_DNF_REJECT}" >&2; exit 1 ;;
    esac
fi
case "${FAKE_DNF_MODE:-ok}" in
fail) printf 'dnf: 依赖解析失败\\n' >&2; exit 1 ;;
empty) exit 0 ;;
slow) sleep "${FAKE_DNF_SLEEP:-2}" ;;
hang)
    # 挂死：不落任何字节也不退出，复刻求解期镜像无响应、dnf 卡在连接的
    # 现场。收割端必须在静默上限到达时终止它并换根，不能等 step 超时。
    # exec 让 sh 自身变成 sleep，TERM 直达进程，测试里不留孤儿。
    exec sleep "${FAKE_DNF_SLEEP:-3600}" ;;
flaky)
    # 链路抖动：前 FAKE_DNF_FAILS 轮失败且不落任何 RPM，之后成功。
    # 用于验证收割的事务级重试，而不是每次失败都重启整份构建。
    st="${FAKE_DNF_STATE:?}"
    n=$(cat "$st" 2>/dev/null || echo 0)
    n=$((n + 1))
    printf '%s\\n' "$n" >"$st"
    [ "$n" -gt "${FAKE_DNF_FAILS:-1}" ] || exit 1 ;;
esac
# 真实 dnf 的事务包含组内全部成员与配方显式安装的包，再加上不在组里的
# 依赖。伪工具按组元数据展开成员，并补上配方里的显式包（例如
# airymaxos-kernel-devel 这类非组成员），保证「载荷须含安装事务全量成员」
# 这条门禁在测试里真的被驱动；本地仓库里已有的 NEVRA 复用同一文件名，
# 与 dnf 选中同一份包一致，也让收割端按文件名去重。
python3 - "$dl" "$pkg" "$specs" <<'PY'
import gzip, sys
import xml.etree.ElementTree as ET
from pathlib import Path


def local(tag):
    return tag.rsplit("}", 1)[-1]


def rpm_name(path):
    bits = path.name[:-4].rsplit(".", 1)[0].split("-")
    return "-".join(bits[:-2]) if len(bits) >= 3 else path.name[:-4]


dl, pkg = Path(sys.argv[1]), Path(sys.argv[2])
href = ""
for data in ET.parse(pkg / "repodata" / "repomd.xml").getroot():
    if local(data.tag) != "data" or data.get("type") != "group":
        continue
    href = next((node.get("href") for node in data.iter()
                 if local(node.tag) == "location"), "")
blob = (pkg / href).read_bytes()
if blob[:2] == b"\\x1f\\x8b":
    blob = gzip.decompress(blob)
members = [n.text.strip() for n in ET.fromstring(blob).iter()
           if local(n.tag) == "packagereq" and (n.text or "").strip()]
members += [spec for spec in sys.argv[3].split() if not spec.startswith("@")]
have = {}
for rpm in pkg.glob("*.rpm"):
    have.setdefault(rpm_name(rpm), rpm.name)
for name in members:
    (dl / have.get(name, f"{name}-1.0-1.noarch.rpm")).write_text(
        f"rpm {name}\\n", encoding="utf-8")
PY
"""

# 闭包池只收「摘要可校验」的包（rpm -K），清单又靠 rpm -qp 取 NEVRA。
# 宿主不必装 rpm：伪工具给 -K 放行，并把文件名去掉 .rpm 当作 NEVRA——
# 伪 RPM 的命名即 name-ver-rel.arch，与真实查询结果同形。
RPM = """\
#!/bin/sh
case "${1:-}" in
-K) exit 0 ;;
-qp)
    last=""
    for a in "$@"; do last=$a; done
    base=${last##*/}
    printf '%s\\n' "${base%.rpm}"
    exit 0 ;;
esac
exit 1
"""

XORRISO = """\
#!/bin/sh
[ "${FAKE_XORRISO_MODE:-ok}" = fail ] && exit 1
exec python3 - "$@" <<'PY'
import base64, os, re, struct, sys
from pathlib import Path

BLK = 2048
PVD = 16 * BLK
MARK = re.compile(rb"(?m)^=== (/[^\\r\\n]+)\\n")
B64 = b"@@base64\\n"


def load(iso):
    data = Path(iso).read_bytes()
    total = struct.unpack("<I", data[PVD + 80:PVD + 84])[0]
    return data, total


def parse(data, total):
    body = data[17 * BLK:total * BLK].rstrip(b"\\0")
    parts = MARK.split(body)
    return [(parts[i].decode(), parts[i + 1])
            for i in range(1, len(parts), 2)]


def dump(items):
    return b"".join(b"=== " + name.encode() + b"\\n" + blob
                    for name, blob in items)


def plain(blob):
    return base64.b64decode(blob[len(B64):]) if blob.startswith(B64) else blob


args = sys.argv[1:]
indev = outdev = extract = dest = None
maps = []
pos = 0
while pos < len(args):
    flag = args[pos]
    if flag == "-indev":
        indev = args[pos + 1]
        pos += 2
    elif flag == "-outdev":
        outdev = args[pos + 1]
        pos += 2
    elif flag == "-extract":
        extract, dest = args[pos + 1], args[pos + 2]
        pos += 3
    elif flag == "-map":
        maps.append((args[pos + 1], args[pos + 2]))
        pos += 3
    elif flag == "-boot_image":
        pos += 3
    elif flag == "-osirrox":
        pos += 2
    else:
        pos += 1

if not indev:
    sys.exit(2)
data, total = load(indev)
if extract:
    items = dict(parse(data, total))
    if extract not in items or not dest:
        sys.exit(1)
    Path(dest).write_bytes(plain(items[extract]))
    sys.exit(0)
if not outdev or not maps:
    sys.exit(2)
items = parse(data, total)
for src, name in maps:
    blob = Path(src).read_bytes()
    if not blob.endswith(b"\\n"):
        blob += b"\\n"
    items = [pair for pair in items if pair[0] != name]
    items.append((name, blob))
img = data[:PVD] + bytes(BLK) + dump(items)
img += b"\\0" * (-len(img) % BLK)
# 伪工具模拟「重建后短于源镜像」：只补尾部填充，载荷必须完好，
# 这样才与真实 xorriso 的行为一致，也才能验证上层补齐逻辑。
short = int(os.environ.get("FAKE_XORRISO_SHORT", "0"))
if short:
    want = len(data) - short * BLK
    if want > len(img):
        img += b"\\0" * (want - len(img))
total = len(img) // BLK
pvd = bytearray(data[PVD:PVD + BLK])
struct.pack_into("<I", pvd, 80, total)
struct.pack_into(">I", pvd, 84, total)
img = img[:PVD] + bytes(pvd) + img[PVD + BLK:]
Path(outdev).write_bytes(img)
PY
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
log=""; boot=""; nv=""; media=0
# 参数值（-boot 的 order、-serial 的路径等）由 case 分支的 shift 消费，
# 逐 token 记录只会留下开关名而丢掉取值。整份 argv 先落盘，测试才能断言
# 「固件按哪一类设备引导」这种取值级事实。
if [ -n "${FAKE_QEMU_LOG:-}" ]; then
    for a in "$@"; do printf '%s\\n' "$a" >> "$FAKE_QEMU_LOG"; done
fi
while [ $# -gt 0 ]; do
    case "$1" in
    -serial) shift; log=${1#file:} ;;
    -boot) shift; boot=$1 ;;
    # 安装腿与启动腿的分界是「有没有安装介质」，不是 -boot 的取值：
    # cdrom 形态是 order=d，usb 形态是 order=cd，后者同样属于安装腿。
    # aarch64 无 El Torito 直通，介质是挂在 virtio-scsi 上的 scsi-cd，
    # 同样属于安装腿，漏判会让该架构的用例落进启动腿分支。
    -cdrom|*usb-storage,*|*scsi-cd,*) media=1 ;;
    *vars.fd) nv=${1#*file=} ;;
    esac
    shift
done
[ -n "$log" ] || exit 0
if [ "$media" -eq 1 ]; then
    case "${FAKE_QEMU_INSTALL_MODE:-ok}" in
    fail) exit 1 ;;
    nomarker) printf 'installing\\n' > "$log"; exit 0 ;;
    postfail) printf 'AIRYMAX-INSTALL-FAIL rc=1\\n' > "$log"; exec sleep 60 ;;
    panic) printf 'Kernel panic - not syncing\\n' > "$log"; exec sleep 60 ;;
    # scriptlet 失败在 anaconda 里上升为事务错误：先报 scriptlet 行，随后
    # 打事务错误与致命菜单（run 40939234612）。判负应在第一行即成立。
    scriptlet) printf '正在配置 sound-theme-freedesktop.noarch\\n' > "$log"
        printf 'Error in POSTIN scriptlet in rpm package sound-theme-freedesktop\\n' \\
            >> "$log"
        printf 'An error occurred during the transaction: Error in POSTIN ' \\
            >> "$log"
        printf 'scriptlet in rpm package sound-theme-freedesktop\\n' >> "$log"
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
noisy) printf '[FAILED] Failed to start OpenSSH server daemon.\\n' > "$log"
    printf "See 'systemctl status sshd.service' for details.\\n" >> "$log"
    printf 'AirymaxOS login:\\n' >> "$log" ;;
degraded) printf '[FAILED] Failed to start OpenSSH server daemon.\\n' > "$log"
    printf 'AIRYMAX-BOOT-DEGRADED failed=1 units=sshd.service\\n' >> "$log" ;;
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

# 冒烟 T6 用 uname -r 判定「跑的是不是产品内核」。真机上是唯一入口，
# 沙箱里必须能给出被破坏的版本号，否则这条判定无法被测试驱动。
UNAME = """\
#!/bin/sh
case "${1:-}" in
-r) printf '%s\\n' "${FAKE_KERNEL_RELEASE:-6.6.157-alk}" ;;
*)
    printf 'Linux\\n'
    ;;
esac
"""

SYSTEMCTL = """\
#!/bin/sh
cmd=""; unit=""; props=""; quiet=0; value=0
while [ $# -gt 0 ]; do
    case "$1" in
    show|is-active|list-units) cmd=$1 ;;
    -p) shift; props="$props $1" ;;
    --value) value=1 ;;
    -q|--quiet) quiet=1 ;;
    -*) ;;
    *) unit=$1 ;;
    esac
    shift
done
field()
{
    case "$1" in
    Slice) printf '%s\\n' "${FAKE_SLICE:-airymax-desktop.slice}" ;;
    CPUWeight) printf '%s\\n' "${FAKE_CPU:-50}" ;;
    IOWeight) printf '%s\\n' "${FAKE_IO:-50}" ;;
    TasksMax) printf '%s\\n' "${FAKE_TASKS:-40%}" ;;
    ActiveState) printf '%s\\n' "${FAKE_ACTIVE_STATE:-active}" ;;
    SubState) printf '%s\\n' "${FAKE_SUB_STATE:-running}" ;;
    Result) printf '%s\\n' "${FAKE_RESULT:-success}" ;;
    InvocationID) printf '%s\\n' "${FAKE_INVOCATION:-}" ;;
    NRestarts) printf '%s\\n' "${FAKE_NRESTARTS:-0}" ;;
    MainPID) printf '%s\\n' "${FAKE_MAIN_PID:-0}" ;;
    *) return 1 ;;
    esac
}
case "$cmd" in
list-units)
    # --failed 的输出只有失败单元；FAKE_FAILED_UNITS 以空格分隔给出清单，
    # 空清单对应干净启动。
    for unit in ${FAKE_FAILED_UNITS:-}; do
        printf '%s loaded failed failed %s\\n' "$unit" "$unit"
    done
    exit 0
    ;;
is-active)
    state=${FAKE_SLICE_ACTIVE:-active}
    [ "$unit" = lightdm.service ] && state=${FAKE_LIGHTDM:-active}
    [ "$quiet" -eq 1 ] || printf '%s\\n' "$state"
    [ "$state" = active ] && exit 0
    exit 3
    ;;
show)
    # systemd 按 -p 出现顺序逐个输出，--value 去掉属性名。多个 -p 累积，
    # 与真实语义一致。
    [ -n "$props" ] || exit 1
    for prop in $props; do
        val=$(field "$prop") || exit 1
        if [ "$value" -eq 1 ]; then
            printf '%s\\n' "$val"
        else
            printf '%s=%s\\n' "$prop" "$val"
        fi
    done
    ;;
*) exit 1 ;;
esac
"""

JOURNALCTL = """\
#!/bin/sh
unit=""; n=""; file=""
while [ $# -gt 0 ]; do
    case "$1" in
    -u) shift; unit="$1" ;;
    -n) shift; n="$1" ;;
    -o) shift ;;
    esac
    shift
done
if [ -n "${FAKE_JOURNAL_DIR:-}" ] && [ -n "$unit" ]; then
    file="${FAKE_JOURNAL_DIR}/${unit}"
else
    file="${FAKE_JOURNAL_FILE:-}"
fi
[ -n "$file" ] || exit 0
[ -r "$file" ] || exit 0
if [ -n "$n" ]; then
    tail -n "$n" "$file"
else
    cat "$file"
fi
"""

ANALYZE = """\
#!/bin/sh
[ -n "${FAKE_CHAIN_FILE:-}" ] || exit 1
[ -r "${FAKE_CHAIN_FILE}" ] || exit 1
cat "${FAKE_CHAIN_FILE}"
"""

XRANDR = """\
#!/bin/sh
case "$1" in
--query)
    [ -n "${FAKE_XRANDR_TOPO:-}" ] || exit 1
    [ -r "${FAKE_XRANDR_TOPO}" ] || exit 1
    cat "${FAKE_XRANDR_TOPO}"
    ;;
--output)
    [ -n "${FAKE_XRANDR_LOG:-}" ] || exit 1
    printf '%s\\n' "$*" >> "${FAKE_XRANDR_LOG}"
    ;;
*) exit 1 ;;
esac
"""


# 块层内省全部走 lsblk/blockdev/findmnt：真机上它们是 sysfs 的读取者，
# 沙箱里用一张表复刻同一输出面。表由 FAKE_LSBLK_DB 指向，每行八列：
#   path|type|bytes|rm|tran|serial|model|mounts（挂载点以逗号分隔）
# 这样「分区不可写」「已挂载不可写」「系统盘不可写」「容量不足」四条
# 守卫都能在没有 root、没有真实磁盘的机器上被驱动，而被写入的目标仍是
# 普通文件，dd/head/sha256sum 走真实 I/O，回读比对是真比对。
LSBLK = """\
#!/bin/sh
db=${FAKE_LSBLK_DB:-}
[ -n "$db" ] && [ -r "$db" ] || {
    printf 'lsblk: cannot open block database\\n' >&2
    exit 1
}
pairs=0; disks=0; fields=""; dev=""
while [ $# -gt 0 ]; do
    case "$1" in
    --*) ;;
    -*)
        rest=${1#-}
        while [ -n "$rest" ]; do
            c=${rest%"${rest#?}"}
            rest=${rest#?}
            case "$c" in
            d) disks=1 ;;
            P) pairs=1 ;;
            o)
                if [ -n "$rest" ]; then
                    fields=$rest; rest=""
                else
                    shift; fields=${1:-}
                fi
                ;;
            esac
        done
        ;;
    *) dev=$1 ;;
    esac
    shift
done
[ -n "$fields" ] || {
    printf 'lsblk: -o 必填\\n' >&2
    exit 1
}
awk -F'|' -v pairs="$pairs" -v disks="$disks" -v fields="$fields" \\
    -v dev="$dev" '
function human(b,   u, i) {
    split("B K M G T", u, " ")
    i = 1
    while (b >= 1024 && i < 5) {
        b /= 1024
        i++
    }
    return (i == 1 ? sprintf("%d", b) : sprintf("%.1f", b)) u[i]
}
function val(k) {
    if (k == "PATH") return $1
    if (k == "TYPE") return $2
    if (k == "SIZE") return human($3)
    if (k == "RM") return $4
    if (k == "TRAN") return $5
    if (k == "SERIAL") return $6
    if (k == "MODEL") return $7
    return ""
}
function emit(where,   i, s) {
    s = ""
    for (i = 1; i <= n; i++)
        s = s (i > 1 ? " " : "") f[i] "=" q \\
            (f[i] == "MOUNTPOINT" ? where : val(f[i])) q
    print s
}
BEGIN {
    q = "\\""
    n = split(fields, f, ",")
    for (i = 1; i <= n; i++)
        if (f[i] == "MOUNTPOINT")
            hasmp = 1
}
$1 == "" { next }
dev != "" && $1 != dev { next }
# -d 是「不展开子设备」。显式给了设备时，lsblk 只打印该设备本身，
# 分区查询（TYPE=part）必须能出结果；未给设备时才收敛到整盘。
disks == 1 && dev == "" && $2 != "disk" { next }
{
    if (!pairs) {
        line = ""
        for (i = 1; i <= n; i++) {
            v = f[i] == "MOUNTPOINT" ? $8 : val(f[i])
            sub(/,.*/, "", v)
            line = line (i > 1 ? " " : "") v
        }
        print line
        next
    }
    if (!hasmp) {
        emit("")
        next
    }
    m = split($8, box, ",")
    if (m == 0) {
        emit("")
        next
    }
    for (j = 1; j <= m; j++)
        emit(box[j])
}' "$db"
"""

BLOCKDEV = """\
#!/bin/sh
[ "${1:-}" = --getsize64 ] || exit 1
db=${FAKE_LSBLK_DB:-}
[ -n "$db" ] && [ -r "$db" ] || exit 1
awk -F'|' -v d="${2:-}" '
$1 == d { print $3; found = 1; exit }
END { exit(found ? 0 : 1) }' "$db"
"""

FINDMNT = """\
#!/bin/sh
[ -n "${FAKE_FINDMNT_ROOT:-}" ] || exit 1
printf '%s\\n' "$FAKE_FINDMNT_ROOT"
"""

ID = """\
#!/bin/sh
printf '%s\\n' "${FAKE_UID:-0}"
"""

# 只吞写入：把 of=<目标> 改指到临时文件后交给真实 dd。劣质介质返回
# 成功却没落下数据，回读比对必须独立于 dd 的退出码，否则「写完即证」
# 会退化成对 dd 的信任。读路径（iso_pvd/iso_mbr 读镜像头）原样透传，
# 且落点仍是普通文件，conv=fsync 得以照常生效（/dev/null 上 fsync
# 会返回 EINVAL，反而掩盖了真实路径）。
DD_SWALLOW = """\
#!/bin/sh
real=/usr/bin/dd
[ -x "$real" ] || real=/bin/dd
[ -x "$real" ] || exit 127
sink=""
n=$#; i=0
while [ "$i" -lt "$n" ]; do
    i=$((i + 1))
    a=$1; shift
    case "$a" in
    of=*) sink=1; continue ;;
    esac
    set -- "$@" "$a"
done
if [ -n "$sink" ]; then
    sink="${TMPDIR:-${HOME:-/tmp}}/dd-swallowed.bin"
    set -- "$@" "of=${sink}"
fi
exec "$real" "$@"
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
    write(bin_dir, "rpm", RPM)


def qemu_tools(bin_dir, arch="x86_64", qemu=True):
    write(bin_dir, "qemu-img", QEMU_IMG)
    if qemu:
        write(bin_dir, f"qemu-system-{arch}", QEMU)


def smoke_tools(bin_dir, omit=()):
    table = (("loginctl", LOGINCTL), ("pgrep", PGREP),
             ("xdpyinfo", XDPYINFO), ("fcitx-remote", FCITX_REMOTE),
             ("pactl", PACTL), ("systemctl", SYSTEMCTL),
             ("gsettings", GSETTINGS), ("sha256sum", SHA256SUM),
             ("uname", UNAME), ("xrandr", XRANDR))
    for name, body in table:
        if name not in omit:
            write(bin_dir, name, body)


def report_tools(bin_dir):
    write(bin_dir, "systemd-analyze", ANALYZE)
    write(bin_dir, "systemctl", SYSTEMCTL)
    write(bin_dir, "journalctl", JOURNALCTL)


def flash_tools(bin_dir):
    write(bin_dir, "lsblk", LSBLK)
    write(bin_dir, "blockdev", BLOCKDEV)
    write(bin_dir, "findmnt", FINDMNT)
    write(bin_dir, "id", ID)
