# ukui-control-center — 下游重建

## 目的

控制中心「关于」页的「桌面」一栏无法表达桌面版本：

- 上游 `setupDesktopComponent()` 先解析 `XDG_CURRENT_DESKTOP`，随后无条件
  执行 `mDesktopLabel_2->setText("UKUI")`，解析结果被覆盖，任何版本号都
  到不了界面；
- 该字符串不是 `tr()` 文案，无法用翻译或配置覆盖，只能重建二进制。

AirymaxOS 的口径是「桌面」显示 `UKUI <版本号>`（0.0.4 任务方案 N-05，
用户裁定选项 A）。版本号由 `airymaxos-release` 交付的受控文件
`/etc/airymaxos/desktop-version` 提供，控制中心只负责读取；文件缺失或
格式不符时回落为 `UKUI`，不猜版本。

## 上游与适用 EVR

| 项 | 值 |
|----|----|
| 上游 src.rpm | `https://repo.openeuler.org/openEuler-24.03-LTS-SP3/EPOL/main/source/Packages/ukui-control-center-3.1.2-33.oe2403sp3.src.rpm` |
| src.rpm SHA-256 | `d3beabf7de66330017c6ebbd55cd697ad9eecb67a1d6300e20b9b317bfc157ad` |
| 上游 EVR | `3.1.2-33.oe2403sp3` |
| 本目录 EVR | `3.1.2-33.oe2403sp3.airy1` |
| 语言 | GPL-2.0-or-later（上游文件头为 GPL-2+） |

tarball 不入库：配方用 `source-rpm` 声明官方 src.rpm 的摘要，构建驱动
下载、校验后从中取出 `ukui-control-center-3.1.2.tar.gz`。摘要钉住整份
src.rpm，成员内容随之被传递固定。

## 补丁序列

`Patch01`~`Patch28`、`Patch200`~`Patch203` 是 openEuler EPOL 官方补丁，
逐字节取自上述 src.rpm，顺序与官方 spec 一致，不为下游改写。

`Patch300`（`airymaxos-desktop-version.patch`）是唯一的下游补丁：

- 删除被覆盖的死代码（`XDG_CURRENT_DESKTOP` 解析）；
- 改为读取 `/etc/airymaxos/desktop-version`，缺失时回落 `UKUI`。

## 版本号来源

`/etc/airymaxos/desktop-version` 由 `specs/airymaxos-release.spec` 安装，
内容形如 `UKUI 3.1.2`。`airymaxos-release` 的 `%check` 断言格式；
`lockfile/ukui-components.yaml` 与 `airymaxos-release.spec` 的
`ukui_desktop_version` 宏由 `lockfile/ukui_check.py` 做一致性校验——
版本号只有一个事实源，改动必须同时通过两处门禁。

## 维护

冻结点滚动时：

1. 更新本目录 spec 的 `Version`/`Release` 与 `source-rpm` 摘要；
2. 逐个 rebase 上游补丁，失败的补丁随新 src.rpm 一并替换，不保留死补丁；
3. 复跑 `distro/ci/run-image-ci.sh` 的 RPM 段与装机冒烟。
