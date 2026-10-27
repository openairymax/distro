# airy-flash — AirymaxOS 安装介质烧录

`airy-flash.sh` 把 `ghcr.io/openairymax/airymaxos-iso:vX.Y.Z` 的混合 ISO
写到整盘，并在写完后立刻回读比对。它是 0.0.3 烧录方案的唯一实现，
也是「可复现烧录」取证链的产出者。

## 1. 为什么不做 GUI

介质写入是一条不可撤销的顺序写，图形工具把它包成黑盒：用户看不到
目标盘是哪一个、看不到守卫为什么放行、失败后也拿不到可供复盘的字节
级证据。本工具反过来做三件事：

- 写前把**判定依据**逐条打印（设备路径、型号、序列号、字节数、
  是否可移除、挂载点、镜像 CD001/55AA/摘要）；
- 写前把**拒绝条件**做成硬守卫，命中即退出，不做「确认后强行继续」；
- 写后落一份**固定字段的记录文件**，把这次烧录锚定到具体镜像摘要与
  具体物理盘序列号。

因此不提供 GUI。需要图形界面时，用文件管理器看记录文件即可。

## 2. 三重核对

镜像从 registry 到介质要过三道独立校验，任何一道失败都不进入下一步：

```
oras pull ghcr.io/openairymax/airymaxos-iso:v0.0.3 -o out/
sha256sum -c out/airymaxos-0.0.3-x86_64.iso.sha256   # ① 内容：registry 自证
sudo ./airy-flash.sh check --iso out/…iso            # ② 结构：PVD + MBR
sudo ./airy-flash.sh write --iso out/…iso --target /dev/sdb
                                                     # ③ 落盘：写完即证
```

- ① 内容：`oras pull` 按 digest 取 layer，本地 `sha256sum -c` 再复核。
- ② 结构：ISO 9660 PVD（偏移 32769 处 `CD001`）+ MBR 引导签名（偏移
  510 处 `55AA`）。缺 PVD 装不上，缺 55AA 开不了 BIOS 机。
- ③ 落盘：写入后 `head -c <iso_bytes> <dev> | sha256sum` 与镜像摘要
  逐字比对。**结论不依赖 dd 的退出码**——介质吞写缓存时 dd 照样返回 0。

## 3. 子命令

| 子命令 | 作用 | 需要 root |
|--------|------|-----------|
| `check --iso PATH [--expect SHA]` | 校验结构与摘要；缺省读同名 `.sha256` | 否 |
| `plan` | 列出候选盘并标注 `ready` / `refused` / `fixed` 及依据 | 否 |
| `write --iso PATH --target DEV [--dry-run]` | 守卫 + 写入 + 回读，落记录文件 | 是 |
| `verify --iso PATH --target DEV` | 只回读比对 | 否 |

`--dry-run` 把校验与守卫跑完就停，不进 `confirm`、不要求 root，适合
在发布前预演目标机上的判定结果。

### 3.1 输出结构

输出按「段」组织，每段一个判定对象，段内固定两列（`key` 与 `value`，
键宽 11 列对齐），段末固定一行 `verdict`：

```
== candidates ==
  idx  device         size       bus   rm  model
  #1   /dev/sda       931.51 GiB sata  0   Samsung SSD 870 EVO
       refused   系统盘（承载 /dev/sda2）
  #2   /dev/sdb       28.67 GiB  usb   1   Ultra Fit
       ready     可写入
  verdict     ok (ready 1 / fixed 0 / refused 1)
```

约定三条：

- 段名固定为 `image` / `candidates` / `target` / `write` / `verify`，
  同一个子命令的段落顺序固定，便于 `awk` 取字段与人工扫读对照；
- 段内其余行只陈述事实、不下结论；只要该段做了判定，最后一行就是
  `verdict`，取值 `ok …` 或 `fail …`。
- 整个子命令成功时，末尾再打一行 `airy-flash: pass`；失败一律走
  `stderr` 并以非 0 退出码结束，不出现「看起来成功但退出码非 0」的
  组合。

`candidates` 段的 `size` 与其他段一样取 `blockdev --getsize64` 再换算，
与 `target` 段的 `bytes` 同源；`lsblk` 自带的 `28.7G` 只在 `blockdev`
不可用时回退使用。

## 4. 守卫

| 守卫 | 判定依据 | 退出码 |
|------|----------|--------|
| 目标必须是块设备 | `lsblk -dnro TYPE` 有输出 | 3 |
| 目标必须是整盘 | `TYPE` 为 `disk`，分区为 `part` | 3 |
| 目标及其分区未挂载 | `lsblk -nrPo PATH,MOUNTPOINT` 聚合 | 3 |
| 目标不是系统盘 | 与 `findmnt -nro SOURCE /` 同盘（含 `sdaN` / `nvme0n1pN`） | 3 |
| 非 USB 需显式放行 | `RM=1` 或 `TRAN=usb`，否则要求 `--allow-fixed` | 3 |
| 容量不小于镜像 | `blockdev --getsize64` 与镜像字节数 | 3 |
| 非交互需显式确认 | 无 `--yes` 且 `stdin` 不是 tty | 3 |
| 写入需 root | `id -u` 为 0 | 5 |
| 记录目录在源码区外 | `scripts/lib/outdir.sh` 的 `out_guard` | 5 |

设备身份一律以 `lsblk`（sysfs / udev）为准，不用 `test -b`：分区同样是
块设备，只有 sysfs 的 `TYPE` 能区分整盘与分区。

## 5. 退出码

| 码 | 含义 |
|----|------|
| 0 | 通过 |
| 2 | 用法错误（参数缺失、未知子命令） |
| 3 | 守卫拒绝（目标不合格或未确认） |
| 4 | 校验不符（镜像结构 / 摘要 / 回读） |
| 5 | 环境不满足（非 root、缺工具、记录目录越界） |
| 6 | 读写失败（dd 报错、记录文件写不出） |

## 6. 记录文件

写入结束（无论成败）都在 `--out` 目录落一份
`flash-<dev>-<UTC 时间戳>.txt`：

| 字段 | 含义 |
|------|------|
| `tool` / `utc` | 工具名与版本、UTC 时间 |
| `image` / `image_bytes` / `image_sha256` | 镜像标识 |
| `target` / `target_bytes` / `target_model` / `target_serial` | 物理盘标识 |
| `target_removable` | `yes` / `no`，是否 USB |
| `write_seconds` | 写入耗时 |
| `verify` / `result` | `pass` / `fail`，回读结论 |
| `write_log` | dd 进度日志文件名 |

`target_serial` 是这条记录的价值所在：同型号 U 盘可以有很多支，序列号
唯一。事后追「这台机器当时用的是哪支盘、写的是哪个摘要」只需这两行。

## 7. 回归测试

块层内省经伪 `lsblk` / `blockdev` / `findmnt` / `id` 注入，写入目标由
普通文件承载，而 `dd` / `head` / `sha256sum` 走真实 I/O——回读比对是
真读真比，不是对桩返回值的断言。

```
cd distro
python3 -m unittest discover -s tools/tests -p 'test_airy_flash.py' -v
```

26 个用例覆盖每个守卫的两侧（该拒绝的拒绝、该放行的放行）、镜像结构
的四种残缺、`--dry-run` 免 root、记录目录越界，以及「dd 成功但没落下
数据」时仍然判 fail 并落记录。

## 8. 实机示例（B50）

```
# 0) 预演：看目标机怎么判定
./airy-flash.sh plan

# 1) 取件与内容核对
oras pull ghcr.io/openairymax/airymaxos-iso:v0.0.3 -o /srv/iso
cd /srv/iso && sha256sum -c airymaxos-0.0.3-x86_64.iso.sha256

# 2) 结构与守卫预演（不需要 root）
./airy-flash.sh check --iso /srv/iso/airymaxos-0.0.3-x86_64.iso
sudo ./airy-flash.sh write --iso /srv/iso/airymaxos-0.0.3-x86_64.iso \
    --target /dev/sdb --dry-run

# 3) 正式写入 + 回读，记录落 /var/log/airymax
sudo ./airy-flash.sh write --iso /srv/iso/airymaxos-0.0.3-x86_64.iso \
    --target /dev/sdb --out /var/log/airymax

# 4) 换机复验（可选，只读）
sudo ./airy-flash.sh verify --iso /srv/iso/airymaxos-0.0.3-x86_64.iso \
    --target /dev/sdb
```

第 3 步的 `--out` 必须落在源码区之外，否则 `out_guard` 直接以 5 退出。
