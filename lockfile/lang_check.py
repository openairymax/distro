#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# distro/lockfile/lang_check.py — 语言政策一致性校验器
#
# 判定逻辑只此一份；ci/gates/lang-lock.sh 只做参数校验与调用。
#
#   verify --root DIR [--allow-pending]
#
# 退出码: 0 通过；1 校验失败；3 未就绪（尚无已落地 Rust 组件）。
# ===========================================================================
"""Validate distro/lockfile/lang-policy.yaml against the tree."""

import argparse
import re
import sys
from pathlib import Path

import yaml

POLICY = "distro/lockfile/lang-policy.yaml"
BUILD_DEPS = "ci/container/build-packages.txt"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
CODE_SUFFIX = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}
FORBID = ("#if 0", "TODO: remove after switch")
EXC_KEYS = ("path", "language", "reason", "owner", "expires")


def bad(errs, msg):
    errs.append(msg)


def check_top(doc, errs):
    if doc.get("schema") != 1:
        bad(errs, "schema 必须为 1")
    pol = doc.get("policy") or {}
    if pol.get("default") != "rust":
        bad(errs, "policy.default 必须为 rust")
    if pol.get("kernel_rust") != "disabled":
        bad(errs, "policy.kernel_rust 必须为 disabled")
    if pol.get("boundary") != "process":
        bad(errs, "policy.boundary 必须为 process")
    if not SEMVER.match(str(pol.get("toolchain", ""))):
        bad(errs, "policy.toolchain 必须是 x.y.z")
    if not pol.get("pinning"):
        bad(errs, "policy.pinning 不得为空")


def pin_dir(root, comp):
    """锁与工具链的钉住处：workspace 成员随根，独立组件在自己的 path。"""
    ws = comp.get("workspace")
    return root / str(ws) if ws else root / str(comp.get("path", ""))


def check_comp(root, comp, errs, seen):
    cid = str(comp.get("id", ""))
    if not cid:
        bad(errs, "component 缺少 id")
    if cid in seen:
        bad(errs, f"component id 重复: {cid}")
    seen.add(cid)
    if comp.get("language") != "rust":
        bad(errs, f"{cid}: 自有组件 language 必须为 rust")
    if comp.get("layer") not in {"L0", "L1", "L2", "L3", "L4"}:
        bad(errs, f"{cid}: layer 非法")
    status = comp.get("status")
    if status not in {"planned", "present"}:
        bad(errs, f"{cid}: status 非法: {status}")
        return False
    path = root / str(comp.get("path", ""))
    has_cargo = (path / "Cargo.toml").is_file()
    if status == "planned":
        if has_cargo:
            bad(errs, f"{cid}: 已出现 Cargo.toml，status 必须改为 present")
        return False
    if not has_cargo:
        bad(errs, f"{cid}: present 但缺少 Cargo.toml")
        return False
    ws = comp.get("workspace")
    if ws and not (root / str(ws) / "Cargo.toml").is_file():
        bad(errs, f"{cid}: workspace 不是 Cargo 根: {ws}")
    for name in ("Cargo.lock", "rust-toolchain.toml"):
        if not (pin_dir(root, comp) / name).is_file():
            bad(errs, f"{cid}: present 但缺少 {name}")
    for f in path.rglob("*"):
        if f.is_file() and f.suffix in CODE_SUFFIX:
            bad(errs, f"{cid}: Rust 组件内出现 C 源文件 {f.relative_to(root)}")
    return True


def check_tool(root, comp, want, errs):
    path = pin_dir(root, comp) / "rust-toolchain.toml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if want not in text:
        bad(errs, f"{comp.get('id')}: rust-toolchain 未钉 {want}")


def check_upstream(root, item, errs):
    if not (root / str(item.get("path", ""))).exists():
        bad(errs, f"upstream_language 路径不存在: {item.get('path')}")
    if item.get("language") not in {"c", "cpp", "shell"}:
        bad(errs, f"upstream_language 语言非法: {item.get('language')}")


def check_legacy(root, item, errs):
    p = root / str(item.get("path", ""))
    if not p.is_file():
        bad(errs, f"legacy 文件不存在: {item.get('path')}")
    elif p.suffix not in CODE_SUFFIX:
        bad(errs, f"legacy 不是 C 源文件: {item.get('path')}")
    if not SEMVER.match(str(item.get("review_by", ""))):
        bad(errs, f"legacy 缺少 review_by: {item.get('path')}")


def check_exc(item, errs):
    for key in EXC_KEYS:
        if not item.get(key):
            bad(errs, f"exception 缺少 {key}: {item.get('path', '?')}")
    if not SEMVER.match(str(item.get("expires", ""))):
        bad(errs, f"exception expires 非法: {item.get('path', '?')}")


def has_rust_deps(root):
    f = root / BUILD_DEPS
    if not f.is_file():
        return False
    text = f.read_text(encoding="utf-8", errors="replace").lower()
    return "rust" in text and "cargo" in text


def verify(root, allow_pending):
    errs = []
    doc = yaml.safe_load((root / POLICY).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        print("FAIL 政策文件不是映射")
        return 1
    check_top(doc, errs)
    seen = set()
    present = 0
    comps = doc.get("components") or []
    for comp in comps:
        if check_comp(root, comp, errs, seen):
            present += 1
            check_tool(root, comp, str(doc["policy"]["toolchain"]), errs)
    for item in doc.get("upstream_language") or []:
        check_upstream(root, item, errs)
    for item in doc.get("legacy") or []:
        check_legacy(root, item, errs)
    for item in doc.get("exceptions") or []:
        check_exc(item, errs)
    if present and not has_rust_deps(root):
        bad(errs, f"{BUILD_DEPS} 缺少 rust/cargo，无法构建已落地组件")
    for e in errs:
        print(f"FAIL {e}")
    print(f"note: present={present} planned={len(comps) - present} "
          f"legacy={len(doc.get('legacy') or [])}")
    if errs:
        return 1
    if present == 0:
        return 0 if allow_pending else 3
    return 0


def main():
    ap = argparse.ArgumentParser(prog="lang_check.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--root", required=True)
    v.add_argument("--allow-pending", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not (root / POLICY).is_file():
        print(f"FAIL 缺少 {POLICY}")
        return 5
    return verify(root, args.allow_pending)


if __name__ == "__main__":
    sys.exit(main())
