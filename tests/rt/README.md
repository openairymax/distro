# SPDX-License-Identifier: AGPL-3.0-or-later OR Apache-2.0

# tests/rt — 实时性基线与回归比较

本目录只做两件事：在目标机上把实时性基线记下来，以及在回归时判断是否劣化。
测量本身由 `ci/gates/rt-accept.sh` 完成，这里不重写 cyclictest 参数与阈值。

## 为什么基线与门禁分开

`rt-accept.sh` 回答「此刻是否达标」，用的是一条不随版本变化的固定阈值。
基线回答的是另一个问题：「同一台机器、同一个内核上，这一版是否比上一版
更差」。两个问题混在一个脚本里，改阈值就会同时改历史数据，回归判定失去
可比性。因此：

- 门禁：每条流水线跑，对固定阈值判定，`0/1/2` 三种退出码；
- 基线：换内核、换机型或首次验收时手工产一次，之后每次比较 `×1.2`；
- 比较：内核版本或能力等级不同即判 `incomparable`，不把换环境算成回归。

## 产出基线

在目标机上（需要 `airy-rt-cap` 与 `rt-tests`，root 权限有利于取到完整能力）：

```bash
tests/rt/baseline.py record --rounds 3 --duration 30 --out /tmp/rt-285h.json
```

三个要素同时写入：`kernel`（`/proc/sys/kernel/osrelease`）、`machine`
（DMI `product_name`）、`grade`（能力矩阵等级）。`max_us` 取多轮最大值——
取均值会把一次抖动抹平，而实时性验收关心的正是那一次抖动。数据落在
`--out` 指定的位置，不进源码树：机器实测记录属于内部取证材料，归档在
`docs-closed` 侧，不发往公开仓库。

## 回归比较

```bash
tests/rt/baseline.py check --baseline /path/rt-285h.json
```

不带 `--current` 时现场测一轮；也可以 `--current NEW.json` 只比较两份存档。
判定上限为 `基线 × --percent/100`，缺省 120 即 `×1.2`。用整数百分比而不是
浮点系数，避免 `40 × 1.2 = 48.00000000000001` 这类边界被浮点舍入翻面。

stdout 固定一行 JSON：

```json
{"baseline_us": 40, "current_us": 42, "grade": "ready",
 "kernel": "6.6.157-alk", "limit_us": 48, "percent": 120, "verdict": "pass"}
```

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 通过：当前最大延迟不超过基线 × 系数 |
| 1 | 不通过，或测量失败（缺依赖、门禁无输出、JSON 不完整） |
| 2 | 用法错误：参数非法、基线或当前数据不可读 |
| 3 | 不可比：内核版本或能力等级与基线不同，或基线缺少标识字段 |

`incomparable` 不是失败也不是通过：换内核后必须重新产基线，改判为通过会
掩盖真实退化，改判为失败会让每一次内核升级都变成红灯。
