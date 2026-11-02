#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0
# ===========================================================================
# lineyaml.py — lockfile 台账共用的行式 YAML 子集解析
#
# 台账只用到四种结构：顶层标量、缩进列表、缩进映射、缩进记录列表。引入
# PyYAML 会把门禁依赖从标准库扩到第三方包，而台账写法受本文件约束，用不到
# 一般 YAML 的锚点、多行标量与流式集合。四种结构由同一状态机覆盖，新增
# 台账不必再抄一份解析器。
#
# 语义：值一律取去掉首尾空白的字符串；空行与 `#` 起首的行跳过；没有子块的
# 键记为空串。键值只按首个冒号切分，值里可以继续出现冒号——镜像 URL 与
# NVRA 都带冒号。
# ===========================================================================

from pathlib import Path


def _put(dat, sect, empty):
    """初始化顶层键的子块；已有同型子块时原样返回。"""
    if not isinstance(dat.get(sect), type(empty)):
        dat[sect] = empty
    return dat[sect]


def load(path):
    """解析台账，返回 {顶层键: 字符串 | 字典 | 列表}。"""
    dat, sect, cur = {}, "", None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            key, _, val = line.partition(":")
            sect, cur = key.strip(), None
            dat[sect] = val.strip()
            continue
        body = line.strip()
        if body.startswith("- "):
            cur = None
            item = body[2:].strip()
            key, sep, val = item.partition(":")
            if sep:
                cur = {key.strip(): val.strip()}
                _put(dat, sect, []).append(cur)
            else:
                _put(dat, sect, []).append(item)
            continue
        key, _, val = body.partition(":")
        if cur is not None:
            cur[key.strip()] = val.strip()
        else:
            _put(dat, sect, {})[key.strip()] = val.strip()
    return dat
