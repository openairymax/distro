# desktop — UKUI 桌面集成策略

> 决策（2026-09-15）：OS 侧系统桌面 = **UKUI 4.x（openKylin/openEuler 线）**。
> 本目录是该决策在发行版组装层的落地策略文件与部署物。

## 六条集成铁律

### 1. RPM 化，不 vendor

UKUI 全组件（ukui-session / ukui-kwin / peony / ukui-framework …）以 RPM
形态随 openEuler 冻结点（lockfile/）进入镜像。禁止以 submodule、vendor
源码、二进制拷贝等任何方式进入本仓或 kernel 叶子仓。确需打补丁时走
`ukui-patches/`（spec + patch，评审后经发行版仓构建）。

### 2. agent 入口唯一 = Gateway

agent 控制面唯一入口是 Gateway（JSON-RPC 2.0 + SSE）。UKUI 自带的
KylinBot 及其 MCP 桌面控制栈（`kylin-ai*` 包族）**排除 + 屏蔽**，防止
桌面成为第二套 agent 控制面、破坏 capability 安全穹顶。落点：

- kickstart `%packages`：`-kylin-ai*` 通配排除；
- `70-airymax-ukui-policy.sh`：`systemctl disable --now` + mask 兜底；
- 包名清单在首个冻结点核对后固化于此（TODO 表，见下）。

### 3. 调度隔离：桌面低干扰

桌面会话整体放入 `airymax-desktop.slice`（CPUWeight=50 / IOWeight=50），
与 agent 负载在 sched_tac 调度面上隔离；UKUI 自带的分级冻结
（kylin-app-cgroupd，cgroup v2）保留，服务于桌面自身后台应用。

### 4. 图形路径：X11 起步，Wayland 二期

ukui-kwin 以 X11 模式起步（与 Tauri/webkit2gtk 最稳组合），
XWayland 兜底；ukui-kwin Wayland 会话作为二期验证项，冻结点
逐项验收后才允许默认切换。

### 5. 许可合规

UKUI 主许可证 GPLv3：集成进发行版即承担开源相应修改的义务。
本项目内不修改 UKUI 源码即可最小化触发面；一旦动 `ukui-patches/`，
修改必须开源。反 DRM 条款影响面由法务/合规评审后再扩（TODO 项）。

### 6. 滚动与内核解耦

桌面升级 = lockfile 单独 PR（全量 diff 评审 + CI 组合冒烟）；
内核换代 = ADR-016 三阶段。两条节奏互不牵连。

## 冻结点核对 TODO 表（首个冻结点落地时填写）

| 项 | 模板假设 | 实际包名/结论 | 状态 |
|---|---|---|---|
| 分级冻结 | kylin-app-cgroupd | 待核对（openEuler 包名可能不同） | TODO |
| 输入法 | fcitx5 + chinese-addons | 待核对 | TODO |
| 终端 | ukui-terminal | 待核对（qterminal 备选） | TODO |
| 登录管理器 | lightdm | 待核对（ukui-greeter/sddm 备选） | TODO |
| kylin-ai* 排除清单 | 通配 `-kylin-ai*` | 待冻结点列出显式清单 | TODO |
| SELinux 与纯 C LSM 叠加 | 暂保持 targeted | 待 security 叶子仓裁定 | TODO |

## 文件说明

- `airymax-desktop.slice` — 桌面低干扰 slice 单元（随 airymaxos-release
  包部署到 `/etc/systemd/system/`）；
- `70-airymax-ukui-policy.sh` — 安装后策略脚本（屏蔽 AI 控制面、写输入法
  环境变量；随 airymaxos-release 包部署到
  `/usr/share/airymax/distro/desktop/`，kickstart %post 调用）。
