**语言：** [English](README.md) | 简体中文

# AirymaxOS 发行版组装层（AirymaxOS Distro）

[![Version](https://img.shields.io/badge/version-0.1.0-5a6b7e)](https://atomgit.com/openairymax/distro)
[![License](https://img.shields.io/badge/license-AGPL--3.0+Apache--2.0-4a90d9)](LICENSE)

> [agent-linux（AirymaxOS）](https://atomgit.com/openairymax/agent-linux)
> （智能体操作系统工程）的叶子仓之一。本仓承载 **OS 镜像组装层**：
> 将 AirymaxOS 内核 RPM 与 openEuler 基础仓库组装为可安装、可启动的发行版。

---

## 概述

**distro** 负责组装 AirymaxOS 发行版镜像，钉扎并组合以下内容：

- 来自 [`kernel`](https://atomgit.com/openairymax/kernel) 叶子仓构建的
  AirymaxOS 内核 RPM（Linux 6.6 基线，ALK）；
- openEuler 24.03 LTS 基础仓库（硬件驱动层、用户态图形栈、工具链），
  原样复用 Euler 验证过的包；
- **UKUI 4.x 桌面**（openKylin / openEuler 线）作为默认系统桌面，
  以 RPM 形式消费——禁止以源码 vendor 方式引入；
- 其余 agent-linux 叶子仓的系统层组件。

## 仓库结构

```
distro/
├── release/
│   └── os-release                 # 发行版标识唯一事实源（VERSION_ID）
├── repo/
│   └── airymax-os.repo            # DNF 仓库定义（运行期 + lockfile 输入）
├── specs/
│   ├── macros.airymax             # FHS 布局宏（/etc/rpm/macros.airymax）
│   └── airymaxos-release.spec     # 发行版标识包
├── kickstart/
│   └── airymaxos-workstation.ks   # 安装器 kickstart（UKUI 为默认桌面组）
├── comps/
│   ├── comps.dtd                  # Comps 1.0 DTD（本地 xmllint 结构校验）
│   └── airymaxos-comps.xml        # 包组定义：airymax-desktop* → UKUI 组件集
├── lockfile/
│   ├── README.md                  # 冻结策略 + 冻结点记录表
│   ├── gen-lockfile.sh            # lockfile 生成脚本（仅发布工作区执行）
│   └── lockfile-openEuler-24.03-LTS-SP2.yaml
├── ostree/
│   ├── README.md                  # rpm-ostree compose 流程
│   └── airymaxos-workstation.treefile
├── desktop/
│   ├── README.md                  # UKUI 集成策略（六条铁律）
│   ├── airymax-desktop.slice      # 桌面低干扰 cgroup slice
│   └── 70-airymax-ukui-policy.sh  # 安装后策略脚本
├── ukui-patches/
│   └── README.md                  # 零补丁策略（预留）
├── tools/
│   ├── spec_lint.py               # RPM 配方静态校验器（E001-E014）
│   ├── comps_lint.py              # comps 语义校验器（C001-C009）
│   └── tests/                     # 校验规则与构建驱动回归测试
├── scripts/
│   └── build-rpms.sh              # RPM 批量构建驱动（产物限于源码区之外）
└── ci/
    ├── README.md                  # 组合冒烟矩阵（T1-T4 + X1）
    ├── run-lint.sh                # 静态门禁：shell 语法 + 配方校验 + 测试
    └── run-smoke.sh               # 冒烟执行脚本（TAP 输出）
```

## 静态门禁

`ci/run-lint.sh` 是静态检查的唯一入口，只依赖 Python 3 标准库
（无需 `rpmbuild`/`mock`）：

- `bash -n` 解析 `ci/`、`lockfile/`、`scripts/` 下全部 shell 入口；
- `tools/spec_lint.py` 校验 `specs/` 下全部配方（标签集合、
  `airymaxos-` 前缀、`%{?dist}` Release、SPDX 许可证、section 集合、
  源文件存在性、changelog 格式、版本与 `release/os-release` 一致）；
- `tools/comps_lint.py` 校验 `comps/*.xml`（DOCTYPE、组/环境标识、
  包名与重复项、布尔字段、环境到组的引用），并交叉校验 `kickstart/*.ks`
  的包组选择（含 `@^环境` 语法）；具备 `xmllint` 时追加按
  `comps/comps.dtd` 的 DTD 结构校验；
- `tools/tests/` 保存上述规则与构建驱动契约的回归测试。

配方在提交时校验；真实 RPM 构建只在发布工作区执行，本仓内不构建。

`scripts/build-rpms.sh --out DIR` 驱动批量构建：将所有 `Source`/`Patch`
归集到私有 `_topdir`，可选发布已签名 DNF 仓库
（`--repo --stream NAME --gpg-key KEYID`）。`DIR` 解析后必须位于源码区
之外，否则拒绝执行，从流程上杜绝构建污染检出区。退出码遵循
`190-distribution/01-rpm-packaging.md` §8。

## 内核隔离边界（硬规则）

本仓**消费**内核产物，绝不向内核仓渗透。依赖方向单向：

- `distro` → 消费：内核 RPM 版本钉扎、`[SC]` UAPI 头（打包形态）；
- `kernel` → 对 `distro` 无感知：内核叶子仓永不出现 spec/comps/
  kickstart/lockfile 文件；
- 若确需给 UKUI 打补丁，spec + 补丁放 `ukui-patches/`——内核仓不动；
- 镜像构建发生在源码区**之外**（发布工作区），本仓内严禁构建；
  本仓只保存配方与配置。

## 分支策略

本叶子仓与其他 agent-linux 叶子仓一致，在 **`dev/hubs-01`** 分支上
开发。聚合管理仓 `agent-linux` 保持在 `main` 分支。

## 上下游依赖

### 上游

- **kernel** — 内核镜像与模块（以 RPM 产物形态消费）
- **services / system / cloudnative** — 待打包的系统层组件
- **openEuler 24.03 LTS** — 基础仓库（驱动、桌面栈、工具链）
- **openKylin / openEuler UKUI 4.x** — 系统桌面包组

### 下游

- 终端用户 — 通过产出的安装器 / 镜像安装 AirymaxOS
- 更新机制 — 基线换代时的 rpm-ostree rebase 载荷

## 许可证

采用 **AGPL-3.0-or-later OR Apache-2.0** 双许可证（SPDX：
`AGPL-3.0-or-later OR Apache-2.0`）。完整文本见 [LICENSE](LICENSE)。

Copyright (c) 2025-2026 SPHARX Ltd. All Rights Reserved.
