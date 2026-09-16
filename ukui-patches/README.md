# ukui-patches — UKUI 补丁策略（当前：零补丁）

> 原则：**当前为零补丁**。UKUI 组件原样消费 openEuler 冻结点 RPM。

## 何时允许出现补丁

仅当同时满足以下三条时，才在此目录新增补丁：

1. 冻结点仓库内的 UKUI 包存在阻断 AirymaxOS 集成的缺陷（且上游
   openKylin/openEuler 无现成修复或修复不可及）；
2. 已在 PR 中附上游 issue/commit 链接，证明"上游可修"路径已先尝试；
3. 补丁随**本目录**的 spec + patch 进入发行版构建，评审后合入。

## 硬规则

- 补丁物（spec + *.patch）**永不进入 kernel 叶子仓**；内核侧唯一合法
  出口是 [SC] UAPI 头（打包形态消费）；
- 一旦修改 UKUI 源码，触发 GPLv3 义务：修改必须开源（desktop/README.md
  决策 5），提交说明中注明 SPDX 与修改范围；
- 补丁必须钉在具体 EVR（与 lockfile 冻结点一致）；冻结点滚动时逐一
  rebase 并重跑 CI 组合冒烟，失效补丁及时删除。

## 目录约定

```
ukui-patches/
├── README.md            # 本文件
└── <package-name>/      # 每个被打补丁的包一个子目录
    ├── *.patch          # 补丁本体（quilt 序列）
    └── README.md        # 补丁目的 / 上游链接 / 适用 EVR
```
