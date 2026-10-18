# lockfile — 包生态冻结点管理

> 本目录存放 AirymaxOS 镜像的 rpm lockfile：把"桌面随 Euler 包生态滚动"
> 从一句口号变成可评审的机制。**桌面滚动与内核基线（ADR-016）解耦**：
> 桌面/基础仓库升级 = 本目录 lockfile 单独 PR；内核换代走 ADR-016 三阶段。

## 冻结策略

| 项 | 规则 |
|---|---|
| 基础仓库 | openEuler 24.03 LTS（SP 分支随内核基线期间选定，不追随滚动版） |
| 冻结点标签 | `openEuler-24.03-LTS-SPx-YYYYMMDD`（例如 `openEuler-24.03-LTS-SP2-20260915`） |
| 冻结范围 | `OS` + `update` + `EPOL/main` + `EPOL/update/main` + `everything` 五个安装期仓库在冻结时刻的全量 EVR |
| 桌面组 | UKUI 4.x 组件随冻结点进入，不做"latest 追踪" |
| 升级节奏 | 例行每季度一次窗口；安全 CVE 可加急（单独 PR，走 CI 组合冒烟） |

## 升级流程（每次滚动）

1. 在发布工作区（**严禁在源码区内构建**）生成新冻结点 lockfile：
   `./gen-lockfile.sh <冻结点标签>`；
2. 提交单独 PR：diff 必须全量人工评审（新增包 / 升级包 / 移除包三段确认）；
3. CI 跑组合冒烟矩阵（ci/README.md：桌面包组 × 内核 RPM 四项验收）；
4. 通过后合入，并在本 README 的冻结点记录表追加一行。

## 冻结点记录表

| 冻结点标签 | lockfile 文件 | 内核 RPM 基线 | 日期 | 备注 |
|---|---|---|---|---|
| （待首个冻结点） | `lockfile-openEuler-24.03-LTS-SP2.yaml` | 6.6-airymax（待定） | — | 首次落地 |

## 文件说明

- `lockfile-openEuler-24.03-LTS-SP2.yaml` — 冻结点 lockfile 本体
  （`document: rpm-lockfile-2024` 格式；`packages: []` 为占位，
  由 `gen-lockfile.sh` 在冻结环境回填，**不接受手工编造 EVR**）；
- `gen-lockfile.sh` — lockfile 生成脚本（包装 rpm-lockfile-prototype 工具，
  必须在能访问冻结源仓库的环境执行）；
- `airymax-os.repo`（待补）— 本项目仓库定义，生成时与 Euler 仓库一并喂给
  生成器，保证 airymaxos-release / kernel 等本项目包也在冻结范围内。
