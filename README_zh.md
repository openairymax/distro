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

## 初始凭据

0.0.3 的交付口径是「开机即桌面」：`airymax` 免密，`root` 固定口令，
都不强制改密。两个 kickstart 仍以 OS-OPS-009 要求的 SHA-512 crypt 哈希
落盘，安装结束即可登录，不依赖尚不存在的首启建号流程：

| 账户 | 交付状态 | 登录边界 |
|------|----------|----------|
| `root` | 固定口令 `00000000` | 控制台/SSH 接管；不强制改密 |
| `airymax` | 空口令（免密） | `wheel`；lightdm 自动登录 + UKUI 桌面 |

空口令由 kickstart 的 `%post` 执行 `passwd -d airymax` 落地，`%post` 末尾
的账户断言把「root 为 sha512、airymax 为空口令」作为安装成功率的一部分。
SSH 侧由 `airymaxos-release` 安装
`/etc/ssh/sshd_config.d/50-airymax-sshd.conf`（`PermitEmptyPasswords yes`）
放行；本地座位由 `50-airymax.conf` 的 `autologin-user=airymax` 免密进入。
定制发行时在注入 ISO 前替换 kickstart 中的哈希，禁止写入明文。

## 仓库结构

```
distro/
├── release/
│   └── os-release                 # 发行版标识唯一事实源（VERSION_ID）
├── repo/
│   └── airymax-os.repo            # DNF 仓库定义（仅运行期客户端）
├── specs/
│   ├── macros.airymax             # FHS 布局宏（/etc/rpm/macros.airymax）
│   └── airymaxos-release.spec     # 发行版标识包
├── kickstart/
│   ├── airymaxos-minimal.ks       # 最小无人值守安装（多用户 + sshd + chrony）
│   └── airymaxos-workstation.ks   # 安装器 kickstart（UKUI 为默认桌面组）
├── comps/
│   ├── comps.dtd                  # Comps 1.0 DTD（本地 xmllint 结构校验）
│   └── airymaxos-comps.xml        # 包组定义：airymax-desktop* → UKUI 组件集
├── lockfile/
│   ├── README.md                  # 冻结策略 + 冻结点记录表
│   ├── rpms.in.yaml               # 冻结输入：上游仓库 + 包清单
│   ├── gen-lockfile.sh            # lockfile 生成脚本（仅发布工作区执行）
│   └── lock_check.py              # 冻结集离线校验与 diff（verify/diff）
├── ostree/
│   ├── README.md                  # rpm-ostree compose 流程
│   └── airymaxos-workstation.treefile
├── desktop/
│   ├── README.md                  # UKUI 集成策略（六条铁律 + 冻结点结论）
│   ├── airymax-desktop.slice      # 桌面低干扰 cgroup slice
│   ├── airymax-desktop-ready.service  # 图形登录链就绪探针
│   ├── desktop_ready.sh           # UKUI 会话定义与 lightdm/greeter 校验
│   ├── boot_state.sh              # 失败单元记账与有界取证（共享库）
│   ├── 70-airymax-ukui-policy.sh  # 安装后策略脚本（mask + 默认 target）
│   ├── lightdm/                   # lightdm 座位策略
│   ├── xinitrc.d/                 # X11 会话输入法环境
│   ├── autostart/                 # XDG 输入法自启项
│   ├── user@.service.d/           # 会话挂接到 airymax-desktop.slice
│   ├── wallpaper/                 # 默认壁纸与 UKUI 壁纸注册表
│   └── glib-2.0/schemas/          # org.mate.background 默认值覆盖
├── login/
│   └── 50-airymax-sshd.conf       # sshd drop-in：放行空口令
├── ukui-patches/
│   └── README.md                  # 零补丁策略（预留）
├── tools/
│   ├── lint_common.py             # 校验器共用的 Issue 类型与输出格式
│   ├── spec_lint.py               # RPM 配方静态校验器（E001-E014）
│   ├── comps_lint.py              # comps 语义校验器（C001-C010）
│   ├── ks_lint.py                 # kickstart 语义校验器（K001-K015）
│   └── tests/                     # 校验规则与构建驱动回归测试
├── scripts/
│   ├── lib/
│   │   ├── arch.sh                # 宿主架构归一（构建驱动共用）
│   │   ├── iso.sh                 # ISO 清单解析（构建驱动共用）
│   │   └── outdir.sh              # 产物目录边界守卫（构建驱动共用）
│   ├── build-desktop.sh           # 镜像介质组装：离线仓库 + mkksiso 注入
│   ├── build-iso.sh               # 无人值守安装 ISO 组装（mkksiso 注入）
│   ├── build-kernel.sh            # 内核确定性归档与 RPM 构建入口
│   ├── build-rpms.sh              # RPM 批量构建驱动（产物限于源码区之外）
│   └── install-test.sh            # 三连测装机回归（安装 → 冷启动 → 判定）
└── ci/
    ├── README.md                  # 组合冒烟矩阵（T1-T4 + X1）
    ├── run-image-ci.sh            # 镜像主门禁：五段编排（minimal/desktop）
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
- `tools/ks_lint.py` 校验 `kickstart/*.ks`（K001-K015）：必需命令、
  安装源唯一性、`https://`/`file://` 方案、存储命令冲突、账户口令必须
  为 `--iscrypted` SHA-512（禁止 `--lock` 与明文）、脚本节区 `set -eu`
  与 `%post --log`、结束命令唯一且位于末尾；离线仓库
  `airymaxos-offline` 必须挂载且 `--baseurl` 精确为
  `file:///run/install/repo/airymax/Packages`；内核包身份要求显式安装
  `airymaxos-kernel` 且不得请求上游 `kernel`/`kernel-*`；
- `tools/tests/` 保存上述规则与构建驱动契约的回归测试。

配方在提交时校验；真实 RPM 构建只在发布工作区执行，本仓内不构建。

`scripts/install-test.sh ISO OUT` 对镜像执行三连测：安装（`-boot order=d`
+ 串口日志）→ 校验 `install complete` 标记 → 冷启动（`-boot order=c`）→
校验无 `Kernel panic` 且出现冷启动标记。默认标记为 `login:`；
`--boot-marker` 可替换，desktop 剖面用 `AIRYMAX-DESKTOP-READY` 断言
UKUI 会话定义可执行、lightdm 与 greeter 会话真实就绪，验收剖面用
`AIRYMAX-SMOKE-PASS`。`AIRYMAX-DESKTOP-FAIL`、`AIRYMAX-SMOKE-FAIL` 与
装机期 `AIRYMAX-INSTALL-FAIL` 一律立即判失败，不等超时。装机失败标记带
`reason=<断言名>`（如 `system-release`、`root-account`），`%post` 的
`trap ... EXIT` 另补发 `rc=N`，失败因此可直接归因，不必复现猜测。
kickstart 的 `%post --log=` 把脚本输出写向目标系统文件，故标记由脚本
显式写 `/dev/console`（x86_64 路由到 ttyS0，aarch64 到 ttyAMA0），这是
串口可观测的前提；`%post` 运行在安装器的 chroot 内，没有可用的 systemd
总线，单元文件动词一律用 `systemctl --root=/` 离线语义，默认 target 由
各剖面 kickstart 唯一设定。虚拟显卡用 `virtio-gpu` 提供 DRM/KMS，因为内核基线只
启用 `DRM_VIRTIO_GPU`，缺省 std VGA 没有对应驱动。输出为 TAP 14；缺
QEMU 工具时输出 `1..0 # SKIP` 并退出 77，不以假通过掩盖环境缺口。

`scripts/build-rpms.sh --out DIR` 驱动批量构建：将所有 `Source`/`Patch`
归集到私有 `_topdir`，可选发布已签名 DNF 仓库
（`--repo --stream NAME --gpg-key KEYID`）。`DIR` 解析后必须位于源码区
之外，否则拒绝执行，从流程上杜绝构建污染检出区。退出码遵循
`190-distribution/01-rpm-packaging.md` §8。

`scripts/build-iso.sh --iso SRC --ks FILE --out DIR` 组装无人值守安装镜像：
以官方安装介质为底座，经 `mkksiso` 注入 kickstart 与串口控制台参数
（缺省 `console=tty0 console=ttyS0,115200`），重建卷标（缺省 `AIRYMAXOS`），产出
ISO、`.sha256` 与 `iso-manifest.txt`，`--gpg-key` 追加分离签名。构建后从
镜像内回读 `/ks.cfg` 与 BIOS/UEFI 引导配置：kickstart 必须逐字节一致，
引导配置必须含 `inst.ks=`，且所有 `inst.stage2=` 的卷标与最终卷标一致；
任一项不符即以 `AIRY_EIO` 失败，避免产出"能生成但不能装"的镜像。
`mkksiso` 需挂载源 ISO，实体机与 CI 均以 root 执行。产物目录边界与
`build-rpms.sh` 共用 `scripts/lib/outdir.sh`。

`scripts/build-desktop.sh --iso SRC --ks FILE --out DIR --rpms DIR` 组装
安装介质：把 RPM 目录递归汇集为自包含离线仓库（`createrepo_c
--groupfile comps/airymaxos-comps.xml`），缺省要求 `airymaxos-release`、
`airymaxos-system`、`airymaxos-kernel` 及其 `core`/`modules` 子包齐备，
否则拒绝出镜像；随后写出 `payload/airymax/payload-manifest.txt` 并委派
`build-iso.sh` 以 `--add` 注入 ISO 根 `/airymax`。minimal 与 desktop
两个剖面共用该驱动，安装期均不依赖现场网络：安装器据 kickstart 的
`repo --baseurl=file:///run/install/repo/airymax/Packages` 离线取包。
minimal 通过可重复的 `--require` 收窄必需包集合（仅内核三包），避免把
桌面发行版闭包强加给最小剖面。镜像产出后再从 ISO 回读载荷清单与
`repomd.xml`，与源文件逐字节比对。`ci/run-image-ci.sh` 两剖面均复用
这一路径，并共享五段 TAP 门禁。

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
