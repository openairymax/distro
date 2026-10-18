# ci — 组合冒烟矩阵

> 目标：每一次"桌面包组 × 内核 RPM"的冻结点滚动/内核指针推进，
> 都经过同一套可重复的四项最低验收。

## 冒烟矩阵

| # | 项 | 验收标准 | 对应决策 |
|---|---|---|---|
| T1 | UKUI X11 会话 | `loginctl` 会话 Type=x11、Service=lightdm、Active=yes；`ukui-session` 存活；`xdpyinfo` 可连 X server | R1-01/R1-03 会话链（E2-01 冒烟切片） |
| T2 | fcitx 4 中文输入 | fcitx 守护进程存活；`fcitx-remote` 可达（状态 0/1/2）；GTK/QT/XMODIFIERS 均指向 fcitx | 冻结点输入法基线（fcitx4） |
| T3 | PulseAudio 音频栈 | `pactl info` 握手成功（套接字激活的端到端路径） | 冻结点音频基线（无 PipeWire） |
| T4 | 桌面隔离 slice | `user@UID.service` 落入 `airymax-desktop.slice`；slice active；CPUWeight=50、IOWeight=50、TasksMax 有限 | R1-04 桌面低干扰 |
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
  `--arch` 切换架构，`--profile minimal|desktop` 选择镜像剖面（desktop 走
  `build-desktop.sh` 离线仓库组装，产物在 `DIR/desktop/`），`--rpms` 为
  桌面剖面补充 RPM 目录（跳过构建段时必须显式给出），
  `--firmware bios|uefi|both` 选择固件腿，`--max-boot` 设定启动墙钟上限。
  任一段失败整体返回 1；参数不满足返回 5；
  缺 QEMU 工具链时装机段跳过并返回 77。各段清单留在其产物子目录，
  编排层只写 `image-ci-manifest.txt`，不复制子驱动清单（SSoT）。
- `run-lint.sh` 是提交前静态门禁：shell 语法、配方/comps/kickstart 三类
  语义校验与工具回归测试（Python 标准库，无 `rpmbuild`/`mock` 依赖）；
- `run-smoke.sh` 必须在已登录的 UKUI 桌面会话内以该桌面用户运行
  （TV-02 桌面验收），不由宿主机驱动；探测只读系统状态，不改配置。
  `loginctl`/`pgrep`/`xdpyinfo` 属探测工具，缺失时该用例记 77 跳过；
  `fcitx-remote`/`pactl` 属被测特性的一部分，缺失即失败而非跳过。
  镜像 CI 只覆盖安装与启动链，不替代桌面冒烟。
  测试机接入方式 TODO：首台 DevStation 测试机就位后回填；
- `../scripts/install-test.sh --iso ISO --out DIR` 承担装机验收：QEMU
  跨架构、双固件、可配置轮次，每轮安装后冷启动并校验串口日志与启动墙钟；
  输出 TAP 14，缺 QEMU 时退出 77；
- `../scripts/build-iso.sh --iso SRC --ks FILE --out DIR` 在发布工作区
  组装被测镜像（`mkksiso` 注入 kickstart，需 root）；产物落在源码区之外，
  构建后自校验 `/ks.cfg` 与引导配置，校验失败即拒绝交付；
- 本目录只保存矩阵定义与脚本；测试用例实现归属 tests-linux 叶子仓（TODO：
  tests-linux 侧立项后建立引用关系，避免两仓重复维护）。
