# ostree — rpm-ostree 镜像配方与 compose 流程

> 本目录存放 rpm-ostree treefile 与 compose 操作流程。
> 镜像构建/compose 一律在**发布工作区**执行（严禁在 airymaxhub 源码区内构建）。

## ref 命名

`airymaxos/<主版本>/<架构>/<变体>`，与 ADR-016 版本基线锁定对齐：

| ref | 内核基线 | 阶段 |
|---|---|---|
| `airymaxos/1.0/x86_64/desktop` | Linux 6.6（1.x.x 锁定） | 当前 |
| `airymaxos/2.0/x86_64/desktop` | Linux 7.1（2.x.x 锁定） | ADR-016 二阶段 |

## compose 基本流程（发布工作区）

```bash
# 1) 准备：lockfile 冻结点已合入（lockfile/README.md 流程）
# 2) compose（unified core 模式）
rpm-ostree compose tree --unified-core \
    --repo=/srv/airymax-repo \
    ostree/airymaxos-workstation.treefile \
    --write-commitid-to /tmp/commitid
# 3) 组合冒烟：ci/run-smoke.sh 对 compose 产物跑四项验收
# 4) 发布： ostree pull 到分发端；升级端 rpm-ostree upgrade
```

## 与更新机制的对应关系

- **升级**：`rpm-ostree upgrade`（同 ref 前进，小版本节奏）；
- **换代**：`rpm-ostree rebase airymaxos/2.0/x86_64/desktop`（1.x→2.x），
  配合 handover 协议（状态外置 + kexec 四阶段）实现"不崩溃、状态不丢、
  秒级停机"——协议 ADR 待立项（见 distro 决策清单）；
- **回滚**：`rpm-ostree rollback`，ostree 原生 ≤30s。

## 注意事项

- treefile 中不硬编码内核参数与 SELinux 裁定（见 treefile 尾部 TODO）；
- `boot-location: new` 要求内核包支持 ostree 引导布局，kernel 叶子仓
  打包 spec 需配合验证（TODO：kernel 侧 spec 联调项）；
- UKUI 桌面组件全部经 lockfile 冻结点进入，treefile 不写 EVR。
