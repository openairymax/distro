# ci — 组合冒烟矩阵

> 目标：每一次"桌面包组 × 内核 RPM"的冻结点滚动/内核指针推进，
> 都经过同一套可重复的四项最低验收。

## 冒烟矩阵

| # | 项 | 验收标准 | 对应决策 |
|---|---|---|---|
| T1 | Tauri 桌面应用窗口 | products/desktop（Tauri/webkit2gtk）在 UKUI X11 会话内正常开窗渲染 | RT 侧 UI 不绑桌面环境 |
| T2 | 输入法 | fcitx5 在 ukui 终端/文本框内完成中文输入 | desktop 决策（冻结点核对项） |
| T3 | 音频栈 | PipeWire 播放到 dummy sink 成功，ukui 音量控件可用 | UKUI 4.x 依赖基线 |
| T4 | 分级冻结 | kylin-app-cgroupd 将后台 UKUI 应用置入冻结 cgroup（cgroup v2 freezer 状态可查） | 桌面低干扰 |
| X1 | 内核仓反向门禁 | kernel CI 持续拒绝 Qt/X11/Wayland 头依赖与 KABI 白名单外变更（由 agent-linux CI 承担，此处仅交叉核对报告） | 双向不污染 |

## 矩阵维度

```
lockfile 冻结点（滚动触发） × 内核 RPM（6.6-airymax.n）
```

任一维度变化 → 全矩阵重跑；任一项失败 → 滚动 PR 不予合入。

## 执行方式

- `run-smoke.sh` 在发布工作区对 compose/installer 产物执行（骨架见同目录
  脚本，测试机接入方式 TODO：首台 DevStation 测试机就位后回填）；
- 本目录只保存矩阵定义与脚本；测试用例实现归属 tests-linux 叶子仓（TODO：
  tests-linux 侧立项后建立引用关系，避免两仓重复维护）。
