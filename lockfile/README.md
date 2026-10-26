# lockfile — 包生态冻结点管理

> 本目录存放 AirymaxOS 镜像的 rpm lockfile：把"桌面随 Euler 包生态滚动"
> 从一句口号变成可评审的机制。**桌面滚动与内核基线（ADR-016）解耦**：
> 桌面/基础仓库升级 = 本目录 lockfile 单独 PR；内核换代走 ADR-016 三阶段。

## 冻结策略

| 项 | 规则 |
|---|---|
| 基础仓库 | openEuler 24.03 LTS（SP 分支随内核基线期间选定，不追随滚动版） |
| 冻结点标签 | `openEuler-24.03-LTS-SPx-YYYYMMDD`（例如 `openEuler-24.03-LTS-SP2-20260915`） |
| 冻结范围 | `airymax-workstation` 环境闭包（mandatory + default）在上游五个安装期仓库中的依赖闭包全量 EVR |
| 不在冻结范围 | `airymaxos-*` 由本仓库 `specs/` 构建、随 ISO 离线仓库分发，版本由源码决定 |
| 桌面组 | UKUI 4.x 组件随冻结点进入，不做"latest 追踪" |
| 升级节奏 | 例行每季度一次窗口；安全 CVE 可加急（单独 PR，走 CI 组合冒烟） |

## 升级流程（每次滚动）

1. 在发布工作区（**严禁在源码区内联网生成**）执行：`./gen-lockfile.sh <冻结点标签>`；
   脚本内部依次完成：闭包解析 → comps 覆盖校验 → 与既有冻结集 diff → 原子落盘；
2. 提交单独 PR：diff 必须全量人工评审（新增包 / 升级包 / 移除包三段确认）；
3. CI 跑组合冒烟矩阵（ci/README.md：桌面包组 × 内核 RPM 九项验收）；
4. 通过后合入，并在本 README 的冻结点记录表追加一行。

## 冻结点记录表

| 冻结点标签 | lockfile 文件 | 内核 RPM 基线 | 日期 | 备注 |
|---|---|---|---|---|
| （待首个冻结点） | `rpms.lock.yaml` | 6.6-airymax（待定） | — | 首次落地 |

## 文件说明

- `rpms.in.yaml` — **输入**。上游仓库地址与需冻结的包名，仓库集合与
  `--cost` 优先级逐条对齐 `kickstart/airymaxos-workstation.ks`，包清单对齐
  `comps/airymaxos-comps.xml` 的 `airymax-workstation` 环境闭包；
- `rpms.lock.yaml` — **输出**。`rpm-lockfile-prototype` 解析出的全量 EVR
  与校验和，只由 `gen-lockfile.sh` 写入，**不接受手工编造 EVR**；
- `gen-lockfile.sh` — 生成入口（包装 rpm-lockfile-prototype，必须在能访问
  冻结源仓库的环境执行）；
- `lock_check.py` — 离线校验器，只依赖标准库、不联网：
  `verify` 断言冻结集覆盖 comps 必装包，`diff` 输出增/升/删三段摘要。

运行期产品自有仓库定义在 `../repo/airymax-os.repo`，面向已装系统的 dnf
客户端，不参与冻结；安装期闭包只取 `rpms.in.yaml` 中声明的上游仓库。
