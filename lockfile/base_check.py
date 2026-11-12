#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# base_check.py — openEuler 基底选型与消费面的离线校验
#
# 只依赖标准库，不联网。base.yaml 是基底选型的唯一事实源；本校验器先按
# 规则复算选型（只取大 SP、EOL 覆盖收口日、合格候选里 GA 最晚、内核仍在
# 6.6 线），再断言仓库地址、冻结输入、安装配方、构建宏与台账都指向同一个
# SP——任一处落伍都会让装机闭包与冻结集分叉，而 dnf 只会在装机现场报
# 「找不到仓库」。
#
#   verify --root DIR
#
# 判据（由 ci/gates/base-eol.sh 调用）：
#   1. schema：日期可解析，policy 为只取大 SP 且 eol-covers 等于 deadline；
#   2. 候选表逐项可解析，内核线与选定值一致；
#   3. 选定项是大 SP、EOL 覆盖 deadline，且是合格候选里 GA 最晚的一个；
#   4. repo 五段、mirrors、冻结输入、kickstart、%oe_base 与 UKUI 台账不含
#      第二个基底串，非注释行不出现 $releasever。
# ===========================================================================

import argparse
import datetime
import re
import sys
from pathlib import Path

import lineyaml

SP = re.compile(r"^openEuler-(\d+)\.(\d+)-LTS-SP(\d+)$")
TOKEN = re.compile(r"openEuler[- ](\d+\.\d+)[- ]LTS[- ]SP(\d+)")
KINDS = ("large", "small")
SECS = ("base", "updates", "epol", "epol-updates", "everything")
HOSTS = ("repo.openeuler.org", "mirrors.tuna.tsinghua.edu.cn",
         "mirrors.huaweicloud.com")
FIRST = "https://repo.openeuler.org/"
KERNEL = "6.6"
ARCH = "x86_64"


def say(msg):
    print(msg)


def bad(out, code, msg):
    out.append("%s: %s" % (code, msg))


def day(text):
    """解析 YYYY-MM-DD；不可解析返回 None。"""
    try:
        return datetime.date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def check_schema(dat, out):
    """校验台账骨架，返回选定的基底名。"""
    dl = day(dat.get("deadline", ""))
    if dl is None:
        bad(out, "schema/deadline", dat.get("deadline", ""))
    sel = dat.get("selected", "")
    if not SP.match(sel):
        bad(out, "schema/selected", sel)
    if dat.get("arch") != ARCH:
        bad(out, "schema/arch", dat.get("arch", ""))
    if dat.get("kernel_line") != KERNEL:
        bad(out, "schema/kernel", dat.get("kernel_line", ""))
    pol = dat.get("policy", {})
    if pol.get("kind") != "large-sp-only":
        bad(out, "schema/policy", "kind=%s" % pol.get("kind", ""))
    if day(pol.get("eol-covers", "")) != dl:
        bad(out, "schema/policy",
            "eol-covers=%s != deadline" % pol.get("eol-covers", ""))
    return sel


def check_cands(dat, out):
    """校验候选表，返回 {名称: 记录}。"""
    cands, seen, line = {}, set(), dat.get("kernel_line", "")
    for rec in dat.get("candidates", []):
        name = rec.get("name", "")
        if not SP.match(name) or name in seen:
            bad(out, "cands/name", name)
            continue
        seen.add(name)
        if rec.get("kind") not in KINDS:
            bad(out, "cands/kind", "%s kind=%s"
                % (name, rec.get("kind", "")))
        for key in ("ga", "eol"):
            if day(rec.get(key, "")) is None:
                bad(out, "cands/date", "%s %s=%s"
                    % (name, key, rec.get(key, "")))
        if rec.get("kernel") != line:
            bad(out, "cands/kernel", "%s kernel=%s"
                % (name, rec.get("kernel", "")))
        cands[name] = rec
    return cands


def pick_day(text):
    """日期原文；缺失或不可解析按最小日期算，必然落在任何合格线之外。"""
    return day(text) or datetime.date.min


def pick_ok(rec, dl):
    """合格候选：大 SP，且 EOL 严格越过收口日。"""
    return rec.get("kind") == "large" and pick_day(rec.get("eol", "")) > dl


def pick_newest(cands, dl):
    """合格候选里 GA 最晚的名字；一个合格候选都没有时为空串。"""
    good = [n for n, r in cands.items() if pick_ok(r, dl)]
    if not good:
        return ""
    return max(good, key=lambda n: pick_day(cands[n].get("ga", "")))


def pick_own(sel, rec, dl, raw, out):
    """选定项自身的判据：大 SP、EOL 覆盖收口日；raw 只用于回显原文。"""
    if rec.get("kind") != "large":
        bad(out, "base/small-sp", "%s 是小 SP" % sel)
    if pick_day(rec.get("eol", "")) <= dl:
        bad(out, "base/eol", "%s EOL %s 不覆盖 %s"
            % (sel, rec.get("eol", ""), raw))


def check_pick(sel, cands, deadline, out):
    """复算选型：大 SP、覆盖收口日、合格候选里 GA 最晚。"""
    rec = cands.get(sel)
    if rec is None:
        bad(out, "base/unknown", "%s 不在候选表" % sel)
        return
    dl = pick_day(deadline)
    pick_own(sel, rec, dl, deadline, out)
    newest = pick_newest(cands, dl)
    if newest and sel != newest:
        bad(out, "base/not-newest", "%s 不是合格候选里 GA 最晚的 %s"
            % (sel, newest))


def read_lines(path, out):
    """读取文本行；缺失或不可读时记一条失败并返回 None。"""
    try:
        return Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        bad(out, "file/missing", str(path))
        return None


def live(lines):
    """去掉空行与整行注释。"""
    return [ln for ln in lines
            if ln.strip() and not ln.lstrip().startswith("#")]


def repo_secs(txt):
    """仓库段名，按出现顺序。"""
    return [ln.strip()[1:-1] for ln in txt if ln.startswith("[")]


def repo_urls(txt):
    """每行 baseurl 的右值，一行可能含多个地址。"""
    return [ln.split("=", 1)[1] for ln in txt if ln.startswith("baseurl=")]


def repo_row(base, row, out):
    """核对一行 baseurl：每段地址指向同一基底，且三家镜像都得在。"""
    for url in row.split():
        if "/%s/" % base not in url:
            bad(out, "repo/baseurl", url)
        if not any(host in url for host in HOSTS):
            bad(out, "repo/host", url)
    for host in HOSTS:
        if host not in row:
            bad(out, "repo/host", "%s 缺 %s" % (row.split()[0], host))


def check_repo(path, base, out):
    lines = read_lines(path, out)
    if lines is None:
        return
    txt = live(lines)
    secs = repo_secs(txt)
    if secs != ["airymaxos-" + s for s in SECS]:
        bad(out, "repo/section", ",".join(secs))
    urls = repo_urls(txt)
    if len(urls) != len(SECS):
        bad(out, "repo/count", "%d != %d" % (len(urls), len(SECS)))
    for row in urls:
        repo_row(base, row, out)
    if any("$releasever" in ln for ln in txt):
        bad(out, "repo/releasever", "baseurl 不得使用 $releasever")


def check_mirrors(path, base, out):
    lines = read_lines(path, out)
    if lines is None:
        return
    roots = [ln.strip() for ln in live(lines)]
    for root in roots:
        if not root.endswith("/" + base):
            bad(out, "mirrors/root", root)
    if roots and roots[0] != FIRST + base:
        bad(out, "mirrors/first", roots[0])


def check_seeds(path, base, out):
    lines = read_lines(path, out)
    if lines is None:
        return
    urls = [ln.split("baseurl:", 1)[1].strip() for ln in live(lines)
            if "baseurl:" in ln]
    if len(urls) != len(SECS):
        bad(out, "seeds/count", "%d != %d" % (len(urls), len(SECS)))
    for url in urls:
        if "/%s/" % base not in url:
            bad(out, "seeds/baseurl", url)


def check_spec(path, base, out):
    lines = read_lines(path, out)
    if lines is None:
        return
    got = [ln.split()[2] for ln in lines if ln.startswith("%global oe_base ")]
    if got != [base]:
        bad(out, "spec/base", ",".join(got) or "missing")
    for ln in lines:
        if ln.startswith("%changelog"):
            break
        for hit in TOKEN.finditer(ln):
            if "openEuler-%s-LTS-SP%s" % (hit.group(1), hit.group(2)) != base:
                bad(out, "spec/token", hit.group(0))


def check_ukui(path, base, out):
    lines = read_lines(path, out)
    if lines is None:
        return
    got = [ln.split(":", 1)[1].strip() for ln in live(lines)
           if ln.startswith("base:")]
    if got != [base]:
        bad(out, "ukui/base", ",".join(got) or "missing")


def check_ks(paths, base, out):
    for path in paths:
        lines = read_lines(path, out)
        if lines is None:
            continue
        for ln in live(lines):
            if "repo.openeuler.org/openEuler-" in ln and \
                    "/%s/" % base not in ln:
                bad(out, "ks/base", ln.strip())


def check_tokens(paths, base, out):
    for path in paths:
        lines = read_lines(path, out)
        if lines is None:
            continue
        for ln in live(lines):
            for hit in TOKEN.finditer(ln):
                if "openEuler-%s-LTS-SP%s" % (hit.group(1),
                                              hit.group(2)) != base:
                    bad(out, "token/drift", "%s: %s"
                        % (Path(path).name, hit.group(0)))


def notes(root):
    """与基底绑定的说明面：注释与文档同样不能落后。"""
    dist = root / "distro"
    return [dist / "comps/airymaxos-comps.xml",
            dist / "ostree/airymaxos-workstation.treefile",
            dist / "desktop/README.md",
            dist / "desktop/70-airymax-ukui-policy.sh",
            dist / "tools/cfg_brand.py"]


def main():
    ap = argparse.ArgumentParser(description="openEuler 基底选型离线校验")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ver = sub.add_parser("verify")
    ver.add_argument("--root", required=True)
    args = ap.parse_args()

    root = Path(args.root)
    path = root / "distro/lockfile/base.yaml"
    if not path.is_file():
        sys.stderr.write("schema/base-missing: %s\n" % path)
        return 1
    dat = lineyaml.load(path)
    out = []
    base = check_schema(dat, out)
    check_pick(base, check_cands(dat, out), dat.get("deadline", ""), out)
    check_repo(root / "distro/repo/airymax-os.repo", base, out)
    check_mirrors(root / "distro/repo/mirrors.list", base, out)
    check_seeds(root / "distro/lockfile/rpms.in.yaml", base, out)
    check_spec(root / "distro/specs/airymaxos-release.spec", base, out)
    check_ukui(root / "distro/lockfile/ukui-components.yaml", base, out)
    check_ks([root / "distro/kickstart/airymaxos-workstation.ks",
              root / "distro/kickstart/airymaxos-minimal.ks"], base, out)
    check_tokens(notes(root), base, out)
    for line in out:
        sys.stderr.write("%s\n" % line)
    if out:
        sys.stderr.write("base-eol: %d 项失败\n" % len(out))
        return 1
    say("基底 %s 覆盖收口日到 %s" % (base, dat.get("deadline", "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
