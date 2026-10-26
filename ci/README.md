# ci — 组合冒烟矩阵

> 目标：每一次"桌面包组 × 内核 RPM"的冻结点滚动/内核指针推进，
> 都经过同一套可重复的九项最低验收。

## 冒烟矩阵

| # | 项 | 验收标准 | 对应决策 |
|---|---|---|---|
| T1 | UKUI X11 会话 | `loginctl` 会话 Type=x11、Service=lightdm、Active=yes；`ukui-session` 存活；`xdpyinfo` 可连 X server | R1-01/R1-03 会话链（E2-01 冒烟切片） |
| T2 | fcitx 4 中文输入 | fcitx 守护进程存活；`fcitx-remote` 可达（状态 0/1/2）；GTK/QT/XMODIFIERS 均指向 fcitx | 冻结点输入法基线（fcitx4） |
| T3 | PulseAudio 音频栈 | `pactl info` 握手成功（套接字激活的端到端路径） | 冻结点音频基线（无 PipeWire） |
| T4 | 桌面隔离 slice | `user@UID.service` 落入 `airymax-desktop.slice`；slice active；CPUWeight=50、IOWeight=50、TasksMax 有限 | R1-04 桌面低干扰 |
| T5 | 内置壁纸 | `org.mate.background picture-filename` 指向内置路径；图像 sha256 与发行资产一致（图像缺失或 schema 缺失均判失败） | 0.0.3 品牌桌面基线 |
| T6 | 内核归属 | `uname -r` 带 `-alk` 后缀；`/boot` 的 vmlinuz/config/System.map 齐全；`CONFIG_LOCALVERSION` 与 `CONFIG_SECURITY_AIRY` 一致 | 产品内核不可被上游内核顶替 |
| T7 | LSM 注册表 | `airy` 在 `/sys/kernel/security/lsm` 中只登记一次；`airy_lockdown` 在位 | 补充钩子不得重复注册 |
| T8 | 主机名 | `/etc/hostname` 为配方值（workstation 剖面 `airymaxos`），不是安装器缺省名 | 品牌身份随装机落地 |
| T9 | 发行版品牌 | `/etc/os-release` 的 `NAME=AirymaxOS`、`ID=airymaxos`、`PRETTY_NAME` 前缀与语义化 `VERSION_ID` 同时成立 | 发行版标识 SSoT 生效 |
| X1 | 内核仓反向门禁 | kernel CI 持续拒绝 Qt/X11/Wayland 头依赖与 KABI 白名单外变更（由 agent-linux CI 承担，此处仅交叉核对报告） | 双向不污染 |

## 矩阵维度

```
lockfile 冻结点（滚动触发） × 内核 RPM（6.6-airymax.n）
```

任一维度变化 → 全矩阵重跑；任一项失败 → 滚动 PR 不予合入。

## 执行方式

- `run-image-ci.sh` 是镜像主门禁：RPM 构建 → 内核构建 → ISO 组装 →
  ISO 完整性 → 装机验收五段串联，输出 TAP 14，一条命令给出可重复结论。
  用法 `ci/run-image-ci.sh --out DIR (--iso PATH | --iso-base PATH)`；
  `--arch` 切换架构，`--profile minimal|desktop` 选择镜像剖面（两剖面都经
  `build-desktop.sh` 组装离线仓库；minimal 产物在 `DIR/iso/` 与
  `DIR/payload/`，desktop 在 `DIR/desktop/`），`--rpms` 为离线仓库补充
  RPM 目录（跳过构建段时必须显式给出，两剖面通用），
  `--firmware bios|uefi|both` 选择固件腿，`--max-boot` 设定启动墙钟上限
  （缺省不传：login 腿按 30s 判定，桌面/验收标记腿不设上限，由
  `--boot-timeout` 兜底）。
  desktop 剖面把启动段标记切换为 `AIRYMAX-DESKTOP-READY`：该标记由
  `airymax-desktop-ready.service` 在 UKUI 会话定义可执行、lightdm 单元
  active 且存在 Service=lightdm、Class=greeter、Type=x11 的活动会话后
  输出；失败则打印 `AIRYMAX-DESKTOP-FAIL`，该串同时是 `install-test.sh`
  的内建启动失败模式，无需等满超时即可判定。该标记只证明会话定义与
  登录管理器/greeter 就绪，不替代桌面会话内的 `run-smoke.sh`。
  desktop 剖面加 `--acceptance` 时改为组装验收 ISO 并由会话内冒烟判定
  （B 轮，见下节）。
  任一段失败整体返回 1；参数不满足返回 5；
  缺 QEMU 工具链时装机段跳过并返回 77。各段清单留在其产物子目录，
  编排层只写 `image-ci-manifest.txt`，不复制子驱动清单（SSoT）。
- `run-lint.sh` 是提交前静态门禁：shell 语法、配方/comps/kickstart 三类
  语义校验与工具回归测试（Python 标准库，无 `rpmbuild`/`mock` 依赖）；
- `run-smoke.sh` 必须在已登录的 UKUI 桌面会话内以该桌面用户运行
  （TV-02 桌面验收），不由宿主机驱动；探测只读系统状态，不改配置。
  `loginctl`/`pgrep`/`xdpyinfo`/`fcitx-remote`/`pactl`/`gsettings`/
  `sha256sum` 随镜像交付，缺失即判失败：被测系统就是产品镜像本身，
  工具缺失说明包组合不完整，没有“外部测试机不支持”这一豁免，因此
  runner 不产生 TAP SKIP。
  镜像 CI 只覆盖安装与启动链，不替代桌面冒烟。
  测试机接入：0.0.3 由 GitHub Actions runner 承载安装与冷启动验收
  （`image-ci.yml` 的 `accept` job），不依赖独立测试机；`/dev/kvm` 可用时
  放开权限使用 KVM，缺失时回退 TCG。物理机双固件复验列为 P2，首台
  DevStation 就位后在 tests-linux 立项并回填接入方式；
- `../scripts/install-test.sh --iso ISO --out DIR` 承担装机验收：QEMU
  跨架构、双固件、可配置轮次，每轮安装后冷启动并校验串口日志与启动墙钟；
  `--boot-marker` 可替换冷启动的判定标记（desktop 剖面用它断言桌面登录链
  就绪），输出 TAP 14，缺 QEMU 时退出 77；
- `../scripts/build-iso.sh --iso SRC --ks FILE --out DIR` 在发布工作区
  组装被测镜像（`mkksiso` 注入 kickstart，需 root）；产物落在源码区之外，
  构建后自校验 `/ks.cfg` 与引导配置，校验失败即拒绝交付；
- 本目录只保存矩阵定义与脚本；测试用例实现归属 tests-linux 叶子仓（TODO：
  tests-linux 侧立项后建立引用关系，避免两仓重复维护）。

## 验收 ISO（B 轮）

产品 ISO 只证明 greeter 就绪，不能证明 UKUI 已登录。B 轮以同一 netinst
基线重新组装验收 ISO，并在真实会话内跑完整 TAP：

```bash
ci/run-image-ci.sh --out /out --iso-base /path/netinst.iso \
    --profile desktop --firmware bios --runs 1 --acceptance
```

`--acceptance` 仅支持 desktop，与 `--ks` 互斥，且必须提供 `--iso-base`：

1. `tools/gen_accept_ks.py` 把 `ci/ks/acceptance.part` 插入产品配方最后
   一个顶层 stop 命令之前，结果写 `OUT/acceptance/airymaxos-acceptance.ks`；
   源码区配方不被修改，重复叠加会被拒绝；
2. `--add` 注入 `run-smoke.sh` 与 `fixture/`，`%post --nochroot` 从安装
   介质复制到 `/usr/lib/airymaxos/ci/`；
3. autologin 进入 UKUI 后由 XDG autostart 运行
   `airymax-smoke-run.sh`，TAP 原子写入 `/var/log/airymax/smoke.tap`；
4. `airymax-smoke-report.service` 轮询 TAP，先以 `AIRYMAX-TAP|` 前缀把 TAP
   原文逐行转发到串口，再以 `AIRYMAX-BOOT-CHAIN|` 前缀转发
   `systemd-analyze critical-chain` 前 24 行（NFR-P-005 服务级门限的实测
   来源），最后输出 `AIRYMAX-SMOKE-PASS` 或 `AIRYMAX-SMOKE-FAIL`。

关键链只在此处采集：验收安装 `%post` 已 mask `airymax-desktop-ready.service`，
同一观测点不设第二个判定者，`osaccrt_bootchain` 据此对账 `boot.service`。

判定要求计划为 `1..9`、九条 `ok`、无 `not ok`/`Bail out!`/`# SKIP`、
`# summary` 的 `fail=0`。会话内 runner 上限 180s，
report 轮询上限 240s；由于转发先于结论标记，宿主机命中
`AIRYMAX-SMOKE-PASS` 时 TAP 全文已在串口，`image-ci.yml` 的
"Extract smoke TAP" 步骤据此还原 `smoke-<fw>-<n>.tap`
（验收发行方案 §9.3 的 L3 归档证据）。`AIRYMAX-SMOKE-FAIL` 已进入
`install-test.sh` 的
`BOOT_FAIL`，失败时无需等满超时。夹具只存在于验收 ISO，产品配方与产品
ISO 不受影响；验收配方另在 `OUT/acceptance/` 留存，manifest 记
`acceptance=1`。
