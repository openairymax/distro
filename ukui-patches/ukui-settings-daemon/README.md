# ukui-settings-daemon — 下游重建

## 目的

会话启动早期，`ukui-settings-daemon` 可能整体 abort，systemd 重启后会话里
出现第二个实例，进程管理器与桌面会话探针随之判负（TAP 的 T23 系统清单、
T24 桌面会话稳定）。崩溃日志的唯一特征是 Qt 与 libdbus 对 `a{sv}` 的报错：

```
QDBusArgument: read from a write-only object          （连续四条）
QDBusMarshaller: cannot add a null QDBusVariant
Array or variant type requires that type variant be written,
but end_dict_entry was written.
The overall signature expected here was 'a{sv}' and we are on byte 3 of that signature.
```

## 根因

`plugins/color/color-manager.cpp` 的 `ReadKwinColorTempConfig()`：

1. 调用会话总线 `org.ukui.KWin /ColorCorrect nightColorInfo`，但**不校验应答**
   ——KWin 尚未注册该接口、或调用失败时，`arguments()` 为空；
2. 取参用 `arguments().at(0).value<QDBusArgument>().asVariant().value<QDBusArgument>()`
   二次提取，得到的是**写态** `QDBusArgument`；用它做 `beginArray()`/`>>`
   只会打印 "read from a write-only object"，读出的 `ColorInfo` 全为无效值；
3. 无效值被塞进 `QVariantMap`，随后 `setNightColorConfig(mNightConfig)` 把
   空 `QDBusVariant` 写进 `a{sv}`；libdbus 在签名字节校验处直接
   `_dbus_abort()`（默认 `DBUS_FATAL_WARNINGS` 生效），进程收到 SIGABRT。

崩溃时机取决于 KWin 的注册时序，因此同一镜像在不同架构/不同启动顺序下
表现不同：x86_64 腿在 KWin 已就绪时走上正常路径，aarch64 腿在 KWin 未就绪
时触发。

## 修复

`Patch300`（`fix-color-abort-on-unusable-kwin-reply.patch`）：

- 调用后校验 `ReplyMessage` 且 `arguments()` 非空，否则保持本地夜览配置并
  返回，不写 `HAD_READ_KWIN`（下次启动重试）；
- 用 `qvariant_cast<QDBusArgument>()` 一次取出读态参数；
- 逐条过滤 `out` 无效的选项，全部无效时同样提前返回；
- 先落到局部 `QHash`，校验 KWin 必须给出的六个键，缺键时同样提前返回——
  `mNightConfig` 的 `operator[]` 读会在缺键处插入空 `QVariant`，这是同一条
  abort 路径的第二个入口；
- 校验通过后才赋值给 `mNightConfig`，后续读取改用 `value()`，不再隐式插键；
- 只把有效值写进 `a{sv}`，保证 marshalling 的每个 variant 都可写。

修复不改变夜览语义：KWin 可用时行为与上游一致，KWin 不可用时退化为本地
配置，而不是杀进程。

## 上游与适用 EVR

| 项 | 值 |
|----|----|
| 上游 src.rpm | `https://repo.openeuler.org/openEuler-24.03-LTS-SP3/EPOL/main/source/Packages/ukui-settings-daemon-3.1.2-9.oe2403sp3.src.rpm` |
| src.rpm SHA-256 | `537bae0b0ae8b78c5ef545831078db2ea222eefebb6104aa4ea1ec86f0068583` |
| 上游 EVR | `3.1.2-9.oe2403sp3` |
| 本目录 EVR | `3.1.2-9.oe2403sp3.airy1` |

tarball 不入库：配方用 `source-rpm` 声明官方 src.rpm 的摘要，构建驱动
下载、校验后从中取出 `ukui-settings-daemon-3.1.2.tar.gz`。

## 补丁序列

`Patch1`、`Patch2`、`Patch4`~`Patch7`、`Patch100` 是 openEuler EPOL 官方
补丁，逐字节取自上述 src.rpm，顺序与官方 spec 一致，不为下游改写。

`Patch300` 是唯一的下游补丁。官方 src.rpm 的 7 个补丁逐条核对，无一涉及
`plugins/color/color-manager.cpp`；SP3 冻结点上没有现成修复可用，故只能
在本目录重建。

## 维护

冻结点滚动时：

1. 更新本目录 spec 的 `Version`/`Release` 与 `source-rpm` 摘要；
2. 逐个 rebase 上游补丁与 `Patch300`，失效补丁随新 src.rpm 替换，不保留死补丁；
3. 复跑 `distro/ci/run-image-ci.sh` 的 RPM 段与装机冒烟，确认 T23/T24 全绿。
