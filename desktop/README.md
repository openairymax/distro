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

权重之外还有一条实时带宽（决策 2026-10-28）：内核启用
`CONFIG_RT_GROUP_SCHED` 后，RT 预算按 cgroup 层级记账，新建组的
`cpu.rt_runtime_us` 为 0，而 0 表示「禁止」而不是「不限」——组内
`sched_setscheduler(SCHED_RR)` 一律 EPERM，rtkit-daemon 每次启动都退化为
非实时（真机 B50 的 `Failed to make ourselves RT`）。预算又不能给单个
slice 写满：子组之和不得超过父组，`system.slice` 占满后 `user.slice`
写入直接 EINVAL，会话侧同样拿不到 RT。因此由
`airymax-rt-budget.service` 在 `rtkit-daemon` 与显示管理器之前按 slice
均分总预算。systemd 在 cgroup v1 上按控制器按需建立单元 cgroup，cpu
层级里常常尚无 slice 目录，脚本因此先建目录再写入，并在每次写入后回读：
未生效的组计入 `missing`、`status` 从 `ok` 降级为 `partial`/`failed`，
不阻断启动，结论落一行 `AIRYMAX-RT-BUDGET` 标记。

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

## 分辨率自适应（决策 2026-10-27）

4K 面板在 X11 下会以首选模式 3840x2160 起会话，UKUI 面板与字号按物理
尺寸渲染，出现「字小到不可用」。冻结点不提供自动缩放，本发行版自行收敛
到「常用分辨率」。

`display_mode.sh` 是策略唯一事实来源，六个入口：

- 无参数：读取 `xrandr --query`，对不一致的输出执行 `--output <名>
  --mode <目标>`，全部一致时不做任何调用（幂等）；
- `--settle [秒]`：在预算内反复应用并复核，收敛即返回，预算耗尽返回 1；
- `--guard [秒] [间隔]`：在窗口内持续守护，偏差出现即纠正，窗口结束记录
  一行 `guard <秒>s drift=<次> fixed=<次> stuck=<次> state=<偏差|ok>`；
- `--check`：只判定不修改，全部输出已符合策略则 0，否则打印
  `分辨率未达策略: <输出>:<当前>-><目标>` 并返回 1；通过但存在唯一模式
  输出时按降级记账（journal + stderr 的 `单模式降级(single-mode)`），
  不把「拓扑无从切换」当成「自适应生效」；
- `--report`：逐输出打印 `<输出> <当前> <目标> <结论>`，结论为 `policy` /
  `single-mode` / `drift`，T10 用它把「策略选对了」与「硬件只给一个模式」
  分开写进 TAP；
- `--plan`：从 stdin 读拓扑文本、向 stdout 打印 `<输出> <当前> <目标>`，
  供单测与 `%check` 在无 X 环境下验证解析。

两个会话入口分工不同：`xinitrc.d` 钩子在会话早期做 `--settle 10`，只负责
把已经建立的拓扑拉回策略；autostart 条目做 `--guard 180`，因为
ukui-settings-daemon 的 xrandr 插件比 autostart 更晚落地，它按自己的记录
回写的模式出现在 `--settle` 返回之后。收敛即返回只对「先写者」有效，
桌面配置又没有可预置的系统级单写入点（kscreen 的 `monitors.xml` 按具体
显示器指纹绑定），所以会话就绪后的入口必须覆盖整个建立窗口。守护只记
偏差集合的变化，同一偏差反复纠正不会刷屏；窗口到期即退出，不常驻。

策略两条规则：单输出上限 `1920x1200`（含，1920x1200 面板原样保留）；
候选集 = 上限内的首选模式 ∪ 阶梯
`1920x1080 1600x900 1440x900 1366x768 1280x720 1024x768` 中该输出确实
广播的项，取其中最大者（同尺寸首选优先，隔行模式原样保留）；候选集为空
时回退首选模式，不猜。取最大而非首选优先，是因为无 EDID 的虚拟输出会把
首选模式报成 1280x800 而当前模式停在 5120x2160，首选优先会让桌面既不用
常用分辨率也没有可用性收益；真实面板的首选模式即其最大模式，两者等价。
逐 connected 输出独立决策，镜像与扩展桌面行为一致；无 connected 输出时
`--check` 判失败（说明 X 未起来，不是「已合规」）。

失败诊断：`--check`/`--settle` 的偏差行后附 `topo=` 压平的完整拓扑；
`apply`/`settle` 每次 `--output --mode` 失败时把 xrandr stderr 折成一行写进
`journal -t airymaxos-display`（`--guard` 只在汇总里计 `stuck`，不逐次写，
否则整个窗口会把 journal 刷满）。两者合起来才能区分「策略选错」与「驱动
拒绝切换」——只留偏差值时这两种根因在验收日志里完全同形。

钩子是 `xinitrc.d/60-airymax-display.sh`：同样大于 50（排在 imsettings 的
`50-xinput.sh` 之后），只调用策略脚本、不复制策略常量；脚本或 xrandr
缺失时静默返回，不阻断会话。策略脚本以 POSIX sh 编写，因为它会被
`/bin/sh` source 的会话链间接执行，禁止 bash 专有语法。

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

## 观测、录屏与基准（决策 2026-10-29）

此前验收证据只有串口标记与 journal：能证明「单元起来了」，证明不了「画面
动起来了」；而要临时装录屏工具、手抄 `DISPLAY` 的做法既不可复现也不可
审计。四个资产把观测、取证与量化收进发行版自身：

- `session_env.sh`：会话发现共享库，只被 source，加载期不做任何探测。
  发现顺序为「现成 `DISPLAY` + 可读 `XAUTHORITY`」→「logind 中 `Type=x11`
  且有 `Display` 的会话，从其 Leader 进程 `/proc/<pid>/environ` 取会话真实
  `XAUTHORITY`」→「`/tmp/.X11-unix/X*` 配可读 xauthority」。失败时不修改
  环境变量，由调用方决定降级还是放弃——半配置的 `DISPLAY` 只会把
  「没有会话」变成 `Cannot open display` 的假象。
- `airy_record.sh`（`/usr/bin/airy-record`）：x11grab 直读 X server，音频取
  默认 sink 的 `monitor`（录系统在放什么，不是麦克风）；sink 不存在时降级
  为无声录制，不静默生成空文件。libx264 的 yuv420p 拒绝奇数宽高，统一过
  一次 `pad=ceil(iw/2)*2:ceil(ih/2)*2`。`-progress` 写文件、主进程每 2 秒
  解析并输出 `progress` 行，录制期间屏幕不静止；结束行带
  `path/frames/size/seconds/sha256`，可与宿主机对账。`--tty [-- 命令...]`
  改走 util-linux `script(1)`，留下 timing 与终端文本两份可 `scriptreplay`
  原速回放的证据：画面证明「看到了什么」，终端证明「跑了什么」，两者不互
  相替代。长选项 `--log-timing/--log-out` 是刻意的——`-t` 在 util-linux
  2.41 起是废弃别名，不再接受分离参数。
- `airy_observe.sh`（`/usr/bin/airy-observe`）：把既有事实按固定
  `key=value` 逐行摊开，每个字段只读一个权威来源（os-release、rpm 数据库、
  systemd、procfs、xrandr），不推断不缓存。字段缺失写 `absent` 而不省略该
  行，取值含空格时整体加双引号（`os.pretty="AirymaxOS 0.0.3 (OpenAirymax)"`）；
  末三行固定 `mode`、`fields`、`status` 并以 `status=ok` 作为退出码，CI 与
  人工读同一份报告。`--static --root` 只读文件，供打包自检在 buildroot 上
  核对品牌与资产，不要求构建机有 X server 或 systemd。
- `airy_bench.py`（`/usr/bin/airy-bench`）：把「IPC 快、并发强」变成可复算
  的数字。三段原语（pipe、AF_UNIX stream、AF_UNIX dgram）各做一次丢弃前
  1000 次预热采样的往返，报 `rtt_p50_us` / `rtt_p99_us` / `rate`；另有
  64 KiB 管道搬运吞吐与 N 进程各自往返的聚合速率及相对单进程的 `scale`。
  分位取自逐次采样排序、速率取自实测总耗时，不外推不取整。数字含解释器
  开销，`host` 行以 `lang=python3` 显式标明，跨机器比较必须带上该行。
  `--check` 只自检原语可用性不测速，作为打包期断言；`scale` 显著低于核数
  说明瓶颈在调度或缓存行，这正是要观测的东西。
- `airy_demo.py`（`/usr/bin/airy-demo`）：终端内的能力总览，纯渲染层——
  身份字段来自 `airy-observe`，延迟与标度来自 `airy-bench`，自己不产生任何
  新数字，屏幕上每一行都能被那两条命令单独复算。段标题先于数据打印，数字
  随到达即出现；并发段另按 1/2/4/8 逐级三次取中位画条，避免单次调度抖动
  被读成能力。非 TTY 或 `NO_COLOR` 时去色，`--check` 只清点对端与终端，
  不重复度量，末行固定 `status=ok|degraded`。

四个入口在 `/usr/bin` 下是到 `/usr/lib/airymaxos/desktop/` 的相对符号链接，
升级时不会出现两份实现。ffmpeg 在 EPOL 而非基线仓库，故声明为
`Recommends: ffmpeg` 而不是硬 `Requires`：有它就装，没有也不阻断装机，
此时 `airy-record --check` 给出 `check status=degraded` 并以非零退出，而不是
把「装不了」误当「录好了」。

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
- `airymax-rt-budget.service` → `/usr/lib/systemd/system/`
  （`rtkit-daemon` 之前分配 cgroup v1 的 RT 带宽预算）
- `rt_budget.sh` → `/usr/lib/airymaxos/desktop/`
  （按 slice 切分 `cpu.rt_runtime_us`，输出 `AIRYMAX-RT-BUDGET`）
- `desktop_ready.sh` → `/usr/lib/airymaxos/desktop/`
  （探针实现：UKUI 会话定义与 lightdm/greeter 会话校验）
- `boot_state.sh` → `/usr/lib/airymaxos/desktop/`
  （共享库：失败单元记账与有界取证，探针与验收上报共用）
- `display_mode.sh` → `/usr/lib/airymaxos/desktop/`
  （分辨率策略：`--check` / `--report` / `--plan` / 默认应用）
- `session_env.sh` → `/usr/lib/airymaxos/desktop/`
  （共享库：X11 会话的 `DISPLAY` / `XAUTHORITY` 发现）
- `airy_record.sh` → `/usr/lib/airymaxos/desktop/`，
  `/usr/bin/airy-record` 为相对符号链接（x11grab 录屏，输出可对账成片）
- `airy_observe.sh` → `/usr/lib/airymaxos/desktop/`，
  `/usr/bin/airy-observe` 为相对符号链接（固定 `key=value` 观察点报告）
- `airy_bench.py` → `/usr/lib/airymaxos/desktop/`，
  `/usr/bin/airy-bench` 为相对符号链接（IPC 延迟分位与并发标度实测）
- `airy_demo.py` → `/usr/lib/airymaxos/desktop/`，
  `/usr/bin/airy-demo` 为相对符号链接（终端能力总览，只渲染不度量）
- `70-airymax-ukui-policy.sh` → `/usr/share/airymaxos/distro/desktop/`
  （`%post` 调用：屏蔽 AI 控制面单元）
- `lightdm/50-airymax.conf` → `/etc/lightdm/lightdm.conf.d/`
- `xinitrc.d/70-airymax-im.sh` → `/etc/X11/xinit/xinitrc.d/`
- `xinitrc.d/60-airymax-display.sh` → `/etc/X11/xinit/xinitrc.d/`
  （会话启动时应用分辨率策略）
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
