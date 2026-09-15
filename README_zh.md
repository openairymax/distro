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
├── kickstart/        # 安装器 kickstart（UKUI 为默认桌面组）
├── comps/            # 包组定义（airymax-desktop → UKUI 组件集）
├── lockfile/         # rpm lockfile：openEuler 24.03 SP 冻结点 + UKUI 钉版
├── ostree/           # rpm-ostree 镜像配方（对应更新机制）
├── desktop/          # UKUI 集成策略：禁用 KylinBot、cgroup slice 隔离、
│                     # X11 优先会话、agent 入口仅经 Gateway
├── ukui-patches/     # （预留）UKUI 的 spec + 补丁，如确有需要
└── ci/               # 组合冒烟矩阵：桌面包组 × 内核 RPM
```

## 内核隔离边界（硬规则）

本仓**消费**内核产物，绝不向内核仓渗透。依赖方向单向：

- `distro` → 消费：内核 RPM 版本钉扎、`[SC]` UAPI 头（打包形态）；
- `kernel` → 对 `distro` 无感知：内核叶子仓永不出现 spec/comps/
  kickstart/lockfile 文件；
- 若确需给 UKUI 打补丁，spec + 补丁放 `ukui-patches/`——内核仓不动；
- 镜像构建发生在源码区**之外**（发布工作区），本仓内严禁构建；
  本仓只保存配方与配置。

## 分支策略

本叶子仓与其他 agent-linux 叶子仓一致，在 **`develop/hubs-01`** 分支上
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
