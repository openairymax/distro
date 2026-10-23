# desktop — UKUI 桌面集成策略

> 决策（2026-09-15）：OS 侧系统桌面 = **UKUI 4.x（openKylin/openEuler 线）**。
> 本目录是该决策在发行版组装层的落地资产；全部静态文件由
> `airymaxos-release` 的 `%install` 直接安装到最终路径，`%post` 只做运行期
> 动作，不复制文件。

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
- `70-airymax-ukui-policy.sh`：对已存在的同名单元走离线语义
  `systemctl --root=/ disable` + `mask`（不依赖 systemd 总线，不使用
  `--now`）。

openEuler 24.03 LTS-SP2 冻结点不含任何 `kylin-ai*` 包，脚本中的单元清单
是防御式约束：上游以后引入同名单元时屏蔽仍然生效。

### 3. 调度隔离：桌面低干扰

桌面会话整体放入 `airymax-desktop.slice`（CPUWeight=50 / IOWeight=50 /
TasksMax=40%），挂接点是 `user@.service` 的 drop-in
`/etc/systemd/system/user@.service.d/50-airymax-desktop.conf`，覆盖整个用户
会话（ukui-session、peony、桌面应用）。只做权重制隔离，不设
MemoryMax/MemoryHigh：桌面自身已有应用级内存管理，双重限额会在内存紧张
时放大回收冲突。

### 4. 图形路径：X11 起步，Wayland 二期

ukui-kwin 以 X11 模式起步（与 Tauri/webkit2gtk 最稳组合），
XWayland 兜底；ukui-kwin Wayland 会话作为二期验证项，冻结点
逐项验收后才允许默认切换。lightdm 1.30 的 seat 只声明默认的
`local`（X11），不写 `type=x`（非法值）。

### 5. 许可合规

UKUI 主许可证 GPLv3：集成进发行版即承担开源相应修改的义务。
本项目内不修改 UKUI 源码即可最小化触发面；一旦动 `ukui-patches/`，
修改必须开源。反 DRM 条款影响面由法务/合规评审后再扩（TODO 项）。

### 6. 滚动与内核解耦

桌面升级 = lockfile 单独 PR（全量 diff 评审 + CI 组合冒烟）；
内核换代 = ADR-016 三阶段。两条节奏互不牵连。

## 默认壁纸（决策 2026-10-12）

AirymaxOS 系统桌面默认壁纸 = `wallpaper/airymaxos-default.jpg`
（祁连实拍；来源 `.github/AirymaxOS/web/wallpaper/qilian_photo_from_zhenyi.jpg`，
3197×2399，sha256 `fee7f439834ac7dacfc75deaf80a1db1c4bc7459583248eecc87125d52a5ef18`）。

三处事实必须一致，由 `airymaxos-release` 一次安装完成：

1. 图像落到 `/usr/share/backgrounds/airymaxos/airymaxos-default.jpg`；
2. 壁纸选择器注册表 `wallpaper/airymaxos-default.xml` 安装到
   `/usr/share/ukui-background-properties/`：`ukui-control-center` 启动时
   扫描该目录全部 `*.xml` 重建 `~/.config/ukui/wallpaper.xml`，XML 必须
   保留 `<!DOCTYPE wallpapers SYSTEM "gnome-wp-list.dtd">`；
3. 系统默认背景由 `glib-2.0/schemas/99-airymaxos-default.gschema.override`
   覆盖 `org.mate.background` 的 `picture-filename`（schema 由
   `mate-desktop-libs` 提供，UKUI 桌面背景实际由 `peony-qt-desktop` 按该
   schema 绘制），`%post` 内 `glib-compile-schemas` 后对新会话生效。

不存在 `org.ukui.background` schema，也不使用
`/usr/share/gnome-background-properties/`（冻结点无此目录）。

## 输入法（决策 2026-10-18）

冻结点提供 fcitx 4.2.9.7（`fcitx`、`fcitx-libs`、`fcitx-libpinyin`、
`fcitx-configtool`、`fcitx-qt5`），不提供 fcitx5。落地两件事：

1. `xinitrc.d/70-airymax-im.sh` 安装到 `/etc/X11/xinit/xinitrc.d/`。
   lightdm 的 `session-wrapper` 是 `/etc/X11/xinit/Xsession`，它 source
   `xinitrc-common` 后按文件名顺序执行该目录；编号必须大于 50，因为
   imsettings 的 `50-xinput.sh` 会先清空输入法变量并在 UKUI 不受支持时把
   `XIM` 置为 `none`。本脚本是该会话环境的唯一事实来源。
2. `autostart/airymax-input-method.desktop` 安装到 `/etc/xdg/autostart/`，
   由 ukui-session 的 XDG autostart 拉起 `fcitx`。fcitx 包只提供
   `NoDisplay=true` 的菜单项，不提供自启文件。

## 登录链就绪探针（决策 2026-10-18）

`airymax-desktop-ready.service`（`WantedBy=graphical.target`）在图形目标
达成后执行 `desktop_ready.sh`，把「桌面能进」转换为宿主机可判定的串口
标记。探针做两级校验：先静态确认 `/usr/share/xsessions/ukui.desktop`
存在且其 `Exec` 可解析可执行（与 lightdm 的 `user-session=ukui` 对应），
再要求 lightdm 单元 active，且 logind 中存在 Service 属 lightdm 家族
（greeter 走独立 PAM 服务，记为 lightdm-greeter）、Class=greeter、
Type=x11、State=active|online 的会话，才打印
`AIRYMAX-DESKTOP-READY`。会话定义缺失或不可执行时立即打印
`AIRYMAX-DESKTOP-FAIL reason=session` 并退出，不进行无效轮询；greeter
未在窗口内就绪则打印 `AIRYMAX-DESKTOP-FAIL unit=lightdm wait=<n>s`。
两种失败都以非零退出码结束，由镜像 CI 的启动段判定失败。

失败前探针会先输出若干 `AIRYMAX-DESKTOP-DIAG <类别> <内容>` 行，把归因
证据带到串口：`unit`（lightdm 的 ActiveState/SubState/Result/NRestarts/
MainPID）、`session`（每个 logind 会话判定用的 Service/Class/Type/State
四元组）、`journal`（该单元本次启动的 journal 尾部）、`file=lightdm`
（`/var/log/lightdm/lightdm.log`）、`file=greeter`（`seat0-greeter.log`）、
`file=xorg`（`x-0.log`）、`wchan`（主进程阻塞点）。诊断只是观测通道，
不参与判定、不改变退出码，每类证据默认最多 20 行（`AIRYMAX_DIAG_LINES`），
缺失的证据直接跳过。`AIRYMAX-DESKTOP-FAIL` 始终是最后一行。

探针只读系统状态，不写状态文件、不改配置，默认轮询 90s（2s 间隔），可用
`AIRYMAX_READY_WAIT` / `AIRYMAX_READY_POLL` 调整。minimal 剖面停留在
multi-user.target，不会触发该单元；workstation kickstart 显式 enable，
遵循 OS-OPS-010。该标记证明 greeter 已就绪，桌面会话内的进程与音频探测
仍由 `ci/run-smoke.sh` 承担。

## 失败单元记账（决策 2026-10-23）

「本次启动有没有单元失败、分别是哪几个」是产品探针与验收 ISO 串口上报
共同的问题，实现只放在 `boot_state.sh` 一处，两个观测点 source 同一个库：

- `boot_health`：干净启动打印 `AIRYMAX-BOOT-HEALTH failed=0`；
  存在失败单元打印 `AIRYMAX-BOOT-DEGRADED failed=<真实总数> units=<前 N 个>`，
  并返回非零；`systemctl` 不可用时打印 `failed=unknown` 而非谎报干净。
- `AIRYMAX-UNIT-STATE|<unit>|ActiveState=… Result=… NRestarts=… MainPID=…`
  与 `AIRYMAX-UNIT-JOURNAL|<unit>|<journal 原文>` 是逐单元取证，只在
  DEGRADED 时输出。每单元最多 12 行（`AIRYMAX_UNIT_LOG`），最多覆盖
  8 个单元（`AIRYMAX_UNIT_LIST`）；`units=` 是被取证子集，`failed=` 是
  真实总数，两者不混用。

这两类标记是纯观测通道，不进 `verdict.env` 的判负集；判定只认
`AIRYMAX-BOOT-HEALTH` / `AIRYMAX-BOOT-DEGRADED`。记账不落盘——systemd
已是唯一事实源，再写状态文件只会制造第二个事实源。库缺失按硬失败处理
（`reason=boot-state`），不回退到无取证的路径。

## 冻结点核对结论（openEuler 24.03 LTS-SP2）

| 项 | 模板假设 | 实际结论 | 状态 |
|---|---|---|---|
| 桌面套件 | UKUI 4.x | EPOL `ukui 2.0.2-20`、`ukui-kwin 1.0.5-8`、`peony 3.10.0-8` | 已核实 |
| 登录管理器 | lightdm | `lightdm 1.30.0-14` + `ukui-greeter 3.1.2-12` | 已核实 |
| 会话管理 | ukui-session | `ukui-session-manager 3.1.0-7`，提供 `ukui.desktop` | 已核实 |
| 分级冻结 | kylin-app-cgroupd | 冻结点无此包；`airymax-desktop.slice` 只做权重制隔离 | 已收敛 |
| 输入法 | fcitx5 + chinese-addons | 冻结点只有 fcitx 4.2.9.7；按 fcitx4 落地 | 已收敛 |
| 终端 | ukui-terminal | 冻结点无此包；EPOL 提供 `mate-terminal 1.28.1-1` | 已核实 |
| kylin-ai* 排除清单 | 通配 `-kylin-ai*` | 冻结点无该包族；kickstart 与策略脚本保留防御 | 已收敛 |
| 默认壁纸背景 schema | `org.ukui.background` | 实为 `org.mate.background`（`mate-desktop-libs 1.28.2-1`） | 已收敛 |
| SELinux 与纯 C LSM 叠加 | 暂保持 targeted | 待 security 叶子仓裁定 | TODO |

## 文件说明

静态资产（源路径 → 安装路径，均由 `airymaxos-release` 打包）：

- `airymax-desktop.slice` → `/usr/lib/systemd/system/`
- `airymax-desktop-ready.service` → `/usr/lib/systemd/system/`
  （`graphical.target` 下拉起登录链探针）
- `desktop_ready.sh` → `/usr/lib/airymaxos/desktop/`
  （探针实现：UKUI 会话定义与 lightdm/greeter 会话校验）
- `boot_state.sh` → `/usr/lib/airymaxos/desktop/`
  （共享库：失败单元记账与有界取证，探针与验收上报共用）
- `70-airymax-ukui-policy.sh` → `/usr/share/airymaxos/distro/desktop/`
  （`%post` 调用：屏蔽 AI 控制面单元）
- `lightdm/50-airymax.conf` → `/etc/lightdm/lightdm.conf.d/`
- `xinitrc.d/70-airymax-im.sh` → `/etc/X11/xinit/xinitrc.d/`
- `autostart/airymax-input-method.desktop` → `/etc/xdg/autostart/`
- `user@.service.d/50-airymax-desktop.conf` →
  `/etc/systemd/system/user@.service.d/`
- `wallpaper/airymaxos-default.xml` →
  `/usr/share/ukui-background-properties/`
- `wallpaper/airymaxos-default.jpg` →
  `/usr/share/backgrounds/airymaxos/`
- `glib-2.0/schemas/99-airymaxos-default.gschema.override` →
  `/usr/share/glib-2.0/schemas/`

回归测试：`tools/tests/test_desktop.py` 校验源文件与配方、运行时路径三者
一致，并防止已证伪的旧机制（profile.d、gnome-background-properties、
`org.ukui.background`、`--now`）回流。
