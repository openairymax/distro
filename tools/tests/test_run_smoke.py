#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_run_smoke.py — ci/run-smoke.sh 契约回归测试
#
# 冒烟脚本必须在已登录的 UKUI 桌面会话内运行，CI 宿主机不具备该环境。
# 脚本对外契约是：TAP 计划、逐项探测的判定，以及“探测工具缺失即失败”
# 的退出码规则。这里用 PATH 沙箱提供伪 loginctl /
# pgrep / xdpyinfo / ibus / pactl / systemctl / gsettings /
# sha256sum / fc-list / uname / xrandr / findmnt / lsblk / dmesg /
# hostname / hostnamectl，并给
# T6–T18 与 T22、T25–T27 准备一份只读系统视图（AIRYMAX_SMOKE_ROOT），每个
# 用例只破坏一个前提，从而在无桌面环境下判定真实控制流。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import fakes

SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "run-smoke.sh"
DESKTOP = Path(__file__).resolve().parents[2] / "desktop"
SERVICES = Path(__file__).resolve().parents[3] / "system" / "services"
DISPLAY_MODE = DESKTOP / "display_mode.sh"
FLAT = Path(__file__).resolve().parents[2] / "firmware" / "fw-flat.sh"
BASH = shutil.which("bash") or "/bin/bash"

# T23 的交付包集合：装机 %post 写下的清单，也是沙箱 rpm 数据库的默认内容。
PACKAGES = ("airymaxos-desktop", "airymaxos-system", "kernel-alk")

# T24 的核心进程：名字是内核 comm 的 15 字节视角，不是 unit 名。
SESSION_PROCS = ("ukui-panel", "ukui-kwin_x11", "ukui-settings-d",
                 "peony-qt-deskto")

# T28 的网络前端闭包：控制中心的三个网络模块与面板的 statusnotifier
# 条目同由 kylin-nm 提供，缺一即图标整块消失。
NET_MODULES = ("libnetconnect.so", "libwlanconnect.so", "libmobilehotspot.so")
# T29 的 ACPI 路径后缀：内建触控板挂在 LPSS 的 I2C 控制器下。两条路径取自
# 285H 实测（ELAN06FA:00 -> \_SB_.PC00.I2C0.TPAD，PNP0C50:00 ->
# \_SB_.PC00.I2C4.TPD0），四种命名各有厂家在用的机型，探针按后缀统一判定。
TPAD_PATH = "\\_SB_.PC00.I2C0.TPAD"
TPD0_PATH = "\\_SB_.PC00.I2C4.TPD0"

# T30 的托盘三件：可执行名与 autostart 条目的 unit 名并不一一对应，音量那
# 件的 desktop 去掉了 -qt 后缀。按可执行名去推条目名必漏，故成对登记。
TRAY_PAIRS = (
    ("kylin-nm", "kylin-nm"),
    ("ukui-power-manager-tray", "ukui-power-manager-tray"),
    ("ukui-volume-control-applet-qt", "ukui-volume-control-applet"),
)

LEGACY = ("tauri", "webkitwebprocess", "fcitx5", "pipewire",
          "kylin-app-cgroupd")

# 用户态可见的发行版内核版本；T6 以 -alk 后缀区分产品内核与上游内核。
KREL = "6.6.157-alk"
LSM_LIST = "airy_lockdown,lockdown,capability,yama,airy,selinux"
# scripts/sign-file 的追加构型：正文 + PKCS#7 + struct module_signature +
# 魔数。id_type=2 即 PKCS#7，此时 signer_len/key_id_len 恒为 0、sig_len 为
# 32。未签名模块只有 ELF 正文。
SIG_MARKER = b"~Module signature appended~\n"
PLAIN_KO = b"\x7fELF\x02\x01\x01" + b"\x00" * 64
SIGNED_KO = (PLAIN_KO + b"\x30\x82" + b"\x2a" * 30
             + bytes([0, 4, 2, 0, 0, 0, 0, 0]) + (32).to_bytes(4, "big")
             + SIG_MARKER)
HOSTNAME = "airymax-pc"
# 构建来源指纹：同一版本号会随每次提交产出不同镜像，T18 要求 os-release 的
# BUILD_ID 与 /etc/airymaxos-build 逐字相同。
BUILD_ID = "r12345678-g0a1b2c3d4e5f"
# 品牌串全 ASCII：NAME 进 GRUB 菜单标题（unicode.pf2 无 CJK 字形），
# PRETTY_NAME 进 ISO 卷标与 /etc/issue；T9 判定的是不变式而非具体字符串。
OS_RELEASE = ('NAME="OpenAirymax"\n'
              'VERSION="0.0.4 (OpenAirymax)"\n'
              "ID=airymaxos\n"
              'VERSION_ID="0.0.4"\n'
              f'BUILD_ID="{BUILD_ID}"\n'
              'PRETTY_NAME="OpenAirymax 0.0.4"\n'
              'VERSION_CODENAME=openairymax\n')

# T14 的客户端源文件形态：多段、三镜像并列、末段关闭。
REPO = """\
[airymaxos-base]
name=AirymaxOS Base - $basearch
baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/OS/$basearch/ https://mirrors.tuna.tsinghua.edu.cn/openeuler/openEuler-24.03-LTS-SP3/OS/$basearch/
enabled=1
gpgcheck=0

[airymaxos-updates]
name=AirymaxOS Updates - $basearch
baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/update/$basearch/ https://mirrors.tuna.tsinghua.edu.cn/openeuler/openEuler-24.03-LTS-SP3/update/$basearch/
enabled=1
gpgcheck=0

[airymaxos-everything]
name=AirymaxOS Everything - $basearch
baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/everything/$basearch/
enabled=0
gpgcheck=0
"""

# T15 的引导默认文件形态：安装期由 grub_args.sh 补齐参数、摘掉旧画面参数、
# 关闭 os-prober，并把菜单停留时间归一到 1 秒。两个剖面（桌面/最小）在
# 参数集合上一致：0.0.4 不再用启动画面遮蔽阶段行。
GRUB_DEFAULTS = """\
GRUB_TIMEOUT=1
GRUB_DEFAULT=saved
GRUB_CMDLINE_LINUX="console=ttyS0,115200 console=tty0 loglevel=5 plymouth.enable=0"
GRUB_DISABLE_OS_PROBER=true
"""

# T22 的本次启动命令行：与默认文件同源才是收敛后的形态。
CMDLINE = ("BOOT_IMAGE=/vmlinuz-6.6.157-alk console=ttyS0,115200 "
           "console=tty0 loglevel=5 plymouth.enable=0\n")

# T17 的挂载视图与块层表：/ 与 /data 各占一个分区。挂载视图每行
# 「挂载点|源」（与 fakes.FINDMNT 一致），块层表格式由 fakes.LSBLK 定义
# （path|type|bytes|rm|tran|serial|model|mounts）。
MOUNTS = "/|/dev/sda1\n/data|/dev/sda2\n"
BLOCKS = ("/dev/sda|disk|268435456000|0|sata|||\n"
          "/dev/sda1|part|1073741824|0|sata|||\n"
          "/dev/sda2|part|267326668800|0|sata|||\n")

# T10 的两份 xrandr --query 拓扑：已在策略模式、以及无 EDID 的 4K 待下调。
TOPO_OK = ("Screen 0: minimum 8 x 8, current 1920 x 1080,"
           " maximum 32767 x 32767\n"
           "eDP-1 connected primary 1920x1080+0+0 (normal) 344mm x 194mm\n"
           "   1920x1080     60.00*+\n"
           "   1280x720      60.00\n")
TOPO_4K = ("Screen 0: minimum 8 x 8, current 3840 x 2160,"
           " maximum 32767 x 32767\n"
           "eDP-1 connected primary 3840x2160+0+0 (normal) 0mm x 0mm\n"
           "   3840x2160     60.00*+\n"
           "   1920x1080     60.00\n"
           "   1280x720      60.00\n")

# T1 的驱动标记与座位配置：xserver.sh 在 fbdev 回退时写同一路径的标记，
# 标记里的 conf 只有出现在 X 的 argv 中才算切换真的生效。
XCONF = "/run/airymaxos/xserver-fbdev.conf"
MARKER = f"driver=fbdev reason=no-kms fb=/dev/fb0 conf={XCONF}\n"


class RunSmokeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.sysroot = self.root / "sysroot"
        self.make_sysroot()
        self.install_display()
        self.mounts = self.root / "mounts"
        self.blocks = self.root / "blocks"
        self.write_mounts()
        self.write_blocks()
        self.marker = self.write_marker()
        self.xorg = self.start_xorg("-config", XCONF)

    def tearDown(self):
        self._tmp.cleanup()

    def make_sysroot(self):
        """构造 T6–T18 与 T22 读取的只读视图：/boot 三件套、LSM、产品标识、
        ESP、sudo 策略、锁屏策略、客户端源文件、引导默认文件、观测工具资产、
        构建来源指纹与本次启动的命令行。"""
        boot = self.sysroot / "boot"
        boot.mkdir(parents=True)
        (boot / f"vmlinuz-{KREL}").write_bytes(b"vmlinuz\n")
        self.write_boot("config", 'CONFIG_LOCALVERSION="-alk"\n'
                                  "CONFIG_SECURITY_AIRY=y\n")
        (boot / f"System.map-{KREL}").write_text(
            "ffffffff81000000 T start_kernel\n", encoding="utf-8")
        self.write_module()
        self.write_taint(0)
        self.write_lsm(LSM_LIST)
        self.write_product(HOSTNAME, OS_RELEASE)
        self.write_esp()
        self.write_sudoers()
        self.write_screensaver()
        self.write_repo()
        self.write_grub()
        self.write_cmdline()
        self.write_assets()
        self.write_build_id()
        self.write_manifest()
        self.write_desktop_assets()
        self.write_wifi_firmware()
        self.write_field_tools()
        self.write_net_front()
        self.write_tray()
        self.write_vconsole()

    def write_net_front(self, kylin=True, modules=NET_MODULES):
        """T28 的落点：面板与控制中心共用的网络前端闭包。判的是文件是否
        进镜像，因此只落可执行位与模块文件，不提供运行逻辑。"""
        bindir = self.sysroot / "usr" / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        link = bindir / "kylin-nm"
        if kylin:
            link.write_text("#!/bin/sh\n", encoding="utf-8")
            link.chmod(0o755)
        elif link.exists():
            link.unlink()
        moddir = self.sysroot / "usr" / "lib64" / "ukui-control-center"
        for name in NET_MODULES:
            path = moddir / name
            if name not in modules:
                if path.exists():
                    path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x7fELF")
        return bindir

    def write_tray(self, bins=None, units=None):
        """T30 的落点：托盘可执行文件与它们各自的 autostart 条目。两者任缺
        一件，图标都不出现——包在而条目缺时进程根本不启动，且没有任何日志。
        按 TRAY_PAIRS 全量对齐，未列入的形态会被删除，避免默认值残留。"""
        bins = [pair[0] for pair in TRAY_PAIRS] if bins is None else bins
        units = [pair[1] for pair in TRAY_PAIRS] if units is None else units
        bindir = self.sysroot / "usr" / "bin"
        unitdir = self.sysroot / "etc" / "xdg" / "autostart"
        bindir.mkdir(parents=True, exist_ok=True)
        unitdir.mkdir(parents=True, exist_ok=True)
        for binname, unit in TRAY_PAIRS:
            path = bindir / binname
            if binname in bins:
                path.write_text("#!/bin/sh\n", encoding="utf-8")
                path.chmod(0o755)
            elif path.exists():
                path.unlink()
            unit_path = unitdir / f"{unit}.desktop"
            if unit in units:
                unit_path.write_text("[Desktop Entry]\nType=Application\n",
                                     encoding="utf-8")
            elif unit_path.exists():
                unit_path.unlink()
        return bindir

    def write_acpi_touchpad(self, node="PNP0C50:00", path=TPAD_PATH):
        """T29 的落点：ACPI 命名空间里存在触控板节点，但输入子系统是否
        枚举出来是另一件事——两者之差正是 LPSS 控制器未绑定的形态。"""
        devices = self.sysroot / "sys" / "bus" / "acpi" / "devices"
        target = devices / node / "path"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{path}\n", encoding="utf-8")
        return target

    def write_input_devices(self, touchpad=True):
        """T29 的落点：/proc/bus/input/devices 的键值块。"""
        body = "I: Bus=0018 Vendor=04f3 Product=31b9 Version=0100\n"
        if touchpad:
            body += 'N: Name="ELAN0676:00 04F3:31B9 Touchpad"\n'
        else:
            body += 'N: Name="AT Translated Set 2 keyboard"\n'
        path = self.sysroot / "proc" / "bus" / "input" / "devices"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def write_xorg_log(self, driver, pad="ELAN0676:00 04F3:31B9 Touchpad"):
        """T29 第二段判据的落点：Xorg 只记录「谁在驱动这块板」。内核绑定
        正常而驱动归属错误时，X 日志是唯一能解释点击与手势失效的证据。"""
        log = self.sysroot / "var" / "log" / "Xorg.0.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            f"[    12.345] (II) Using input driver '{driver}' for '{pad}'\n",
            encoding="utf-8",
        )
        return log

    def write_field_tools(self):
        """T27 的落点：现场诊断工具在镜像内的落盘位置。判的是打包闭包，
        不是运行行为，因此只落可执行文件，不提供任何桩逻辑。"""
        bindir = self.sysroot / "usr" / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        for name in ("lsusb", "lsof", "pactl", "airy-bright"):
            tool = bindir / name
            tool.write_text("#!/bin/sh\n", encoding="utf-8")
            tool.chmod(0o755)

    def write_desktop_assets(self, theme="ukui", hicolor=True):
        """T25 的落点：图标主题目录。字体覆盖不落文件——那由 fc-list 伪实现
        按 FAKE_FC_LANG_ZH_CN 作答，判定问的是 fontconfig 解到了什么。"""
        base = self.sysroot / "usr" / "share" / "icons"
        names = (([theme] if theme else []) + (["hicolor"] if hicolor else []))
        for name in names:
            path = base / name / "index.theme"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"[Icon Theme]\nName={name}\n", encoding="utf-8")
        if not hicolor and (base / "hicolor").is_dir():
            shutil.rmtree(base / "hicolor")

    def write_wifi_firmware(self, name="iwlwifi-gl-c0-fm-c0-83.ucode",
                            flat=True, legacy=False):
        """T26 的落点：基底的新布局（intel/iwlwifi/）与固件根上的兼容链接。
        清单与自证日志是安装期 %posttrans 的产物，判据由随镜像交付的
        fw-flat.sh 复核；legacy 模拟基底回到扁平布局（清单为空、根上直接
        是文件）。"""
        fw = self.sysroot / "usr" / "lib" / "firmware"
        link = fw / name
        src = fw / "intel" / "iwlwifi"
        tool = self.sysroot / "usr" / "libexec" / "airymaxos" / "fw-flat.sh"
        tool.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FLAT, tool)
        tool.chmod(0o755)
        listf = (self.sysroot / "usr" / "share" / "airymaxos" / "firmware"
                 / "firmware-flat.list")
        listf.parent.mkdir(parents=True, exist_ok=True)
        fwlog = (self.sysroot / "var" / "log" / "airymaxos"
                 / "firmware-flat.log")
        fwlog.parent.mkdir(parents=True, exist_ok=True)
        if legacy:
            if src.is_dir():
                shutil.rmtree(src)
            if link.is_symlink() or link.exists():
                link.unlink()
            fw.mkdir(parents=True, exist_ok=True)
            link.write_bytes(b"\0")
            listf.write_text("", encoding="utf-8")
            fwlog.write_text("flat=0 miss=0 list=/tmp/x\n", encoding="utf-8")
            return link
        src.mkdir(parents=True, exist_ok=True)
        (src / name).write_bytes(b"\0")
        if link.is_symlink() or link.exists():
            link.unlink()
        if flat:
            link.symlink_to(f"intel/iwlwifi/{name}")
        listf.write_text(f"{name} intel/iwlwifi/{name}\n", encoding="utf-8")
        fwlog.write_text("2026-11-09T00:00:00Z fw-flat apply\n"
                         f"flat={1 if flat else 0} miss=0 list={listf}\n",
                         encoding="utf-8")
        return link

    def write_manifest(self, names=PACKAGES):
        """T23 的落点：装机时由 %post 写下的交付包集合。"""
        path = self.sysroot / "etc" / "airymaxos-packages"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{name}\n" for name in names),
                        encoding="utf-8")
        return path

    def write_vconsole(self, font="latarcyrheb-sun32", w=16, h=32,
                       psf2=True, write_font=True):
        """T22 的落点：/etc/vconsole.conf 的 FONT 与它指向的字体文件。
        判据读 PSF2 头的前 32 字节（偏移 24/28 为 height/width），沙箱只需
        复刻这段头。psf2=False 时写成 PSF1（magic 0x36），用于复现「换成
        大字号之前」的现场：文件在、路径对，字号却仍是固定的 8 列。"""
        conf = self.sysroot / "etc" / "vconsole.conf"
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(f'KEYMAP="us"\nFONT="{font}"\n', encoding="utf-8")
        fontdir = self.sysroot / "usr" / "lib" / "kbd" / "consolefonts"
        fontdir.mkdir(parents=True, exist_ok=True)
        path = fontdir / f"{font}.psfu"
        if not write_font:
            if path.exists():
                path.unlink()
            return conf
        head = bytearray(32)
        if psf2:
            head[0:4] = bytes((114, 181, 74, 134))
            head[8:12] = (32).to_bytes(4, "little")
            head[16:20] = (256).to_bytes(4, "little")
            head[20:24] = (h * w // 8).to_bytes(4, "little")
            head[24:28] = h.to_bytes(4, "little")
            head[28:32] = w.to_bytes(4, "little")
        else:
            head[0] = 0x36
        path = fontdir / f"{font}.psfu"
        path.write_bytes(bytes(head))
        return conf

    def write_cmdline(self, body=CMDLINE):
        """T22 的落点：安装器写入引导项后，内核实际拿到的命令行。"""
        path = self.sysroot / "proc" / "cmdline"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def write_build_id(self, value=BUILD_ID):
        """T18 的落点：发布包在 %install 里由同一个宏写出的一行式指纹。"""
        path = self.sysroot / "etc" / "airymaxos-build"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"BUILD_ID={value}\n", encoding="utf-8")
        return path

    def write_module(self, body=SIGNED_KO):
        """T6 签名判定的落点：签名是追加在 .ko 尾部的 PKCS#7、12 字节
        module_signature 与 28 字节魔数，不是 ELF 段。"""
        path = (self.sysroot / "usr" / "lib" / "modules" / KREL /
                "kernel" / "security" / "airy" / "airy.ko")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def write_taint(self, value):
        """运行内核的污染位：T6 用它区分「签名缺失」与「已加载未签名模块」。"""
        path = self.sysroot / "proc" / "sys" / "kernel" / "tainted"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{value}\n", encoding="utf-8")
        return path

    def write_grub(self, body=GRUB_DEFAULTS):
        """引导参数的落点：grub2-mkconfig 的唯一输入文件。"""
        path = self.sysroot / "etc" / "default" / "grub"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def write_assets(self):
        """T5/T16 读取的发行资产：三张壁纸按目录计数，其余只看存在性。"""
        for rel in ("usr/share/backgrounds/airymaxos/"
                    "qilian_photo_from_zhenyi.jpg",
                    "usr/share/backgrounds/airymaxos/"
                    "clouds_moonlight_photo_from_lidecheng.jpg",
                    "usr/share/backgrounds/airymaxos/"
                    "hangzhouxihu_photo_from_lidecheng.jpg",
                    "usr/share/glib-2.0/schemas/"
                    "99-airymaxos-default.gschema.override",
                    "usr/lib/airymaxos/desktop/desktop_ready.sh",
                    "usr/lib/airymaxos/desktop/airy_record.sh",
                    "usr/lib/airymaxos/desktop/airy_observe.sh",
                    "usr/lib/airymaxos/desktop/airy_bench.py",
                    "usr/lib/airymaxos/desktop/airy_demo.py"):
            path = self.sysroot / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def write_repo(self, body=REPO):
        """运行期源的落点：与 airymaxos-release 交付的文件同名。"""
        path = self.sysroot / "etc" / "yum.repos.d" / "airymaxos.repo"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def write_sudoers(self):
        """免密提权的落点：与 airymaxos-release 交付的文件同名同内容。"""
        path = self.sysroot / "etc" / "sudoers.d" / "90-airymax"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("amuser ALL=(ALL) NOPASSWD: ALL\n", encoding="utf-8")
        return path

    def write_screensaver(self):
        """免密桌面的落点：dconf 键文件，与 airymaxos-release 同名同内容。"""
        path = (self.sysroot / "etc" / "dconf" / "db" / "local.d" /
                "00-airymax-screensaver")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[org/ukui/screensaver]\n"
                        "idle-lock-enabled=false\n"
                        "lock-enabled=false\n"
                        "idle-activation-enabled=false\n"
                        "sleep-activation-enabled=false\n", encoding="utf-8")
        return path

    def write_esp(self):
        """EFI 品牌的落点：完整签名套件、品牌状态与品牌日志，以及安装期
        可见的 efivars 目录。状态文件与日志是 efi_brand.sh 真实产物。"""
        esp = self.sysroot / "boot" / "efi" / "EFI" / "airymaxos"
        esp.mkdir(parents=True)
        for name in ("shimx64.efi", "grubx64.efi"):
            (esp / name).write_bytes(b"efi\n")
        (esp / "BOOTX64.CSV").write_text(
            "shimx64.efi,airymaxos,,AirymaxOS\n", encoding="utf-8")
        self.write_boot_cfg(esp)
        state = self.sysroot / "var" / "lib" / "airymaxos" / "efi-brand"
        state.parent.mkdir(parents=True)
        state.write_text("entry=0001\nloader=\\EFI\\airymaxos\\shimx64.efi\n",
                         encoding="utf-8")
        self.write_brand_log("AIRYMAX-EFI-NOTE entry=0001 disk=/dev/sda"
                             " part=1 order=0001\n")
        (self.sysroot / "sys" / "firmware" / "efi").mkdir(
            parents=True, exist_ok=True)
        return esp

    def write_boot_cfg(self, esp, body="menuentry 'AirymaxOS' {\n}\n"):
        """ESP 的两份 grub.cfg：grub2-mkconfig 的生成件与品牌副本。真机上
        活动的是品牌副本（$prefix 即被加载的 grubx64.efi 所在目录）。"""
        brand = esp / "grub.cfg"
        brand.write_text(body, encoding="utf-8")
        gen = esp.parent / "openEuler" / "grub.cfg"
        gen.parent.mkdir(parents=True, exist_ok=True)
        gen.write_text(body, encoding="utf-8")
        return gen, brand

    def write_brand_log(self, body):
        """安装期品牌脚本在目标根内留下的日志，验收失败时读其末行归因。"""
        path = self.sysroot / "var" / "log" / "airymax" / "efi-brand.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def write_product(self, hostname, os_release):
        etc = self.sysroot / "etc"
        etc.mkdir(parents=True, exist_ok=True)
        (etc / "hostname").write_text(f"{hostname}\n", encoding="utf-8")
        self.write_osrel(os_release)

    def write_osrel(self, body):
        path = self.sysroot / "etc" / "os-release"
        path.write_text(body, encoding="utf-8")
        # /etc/issue 首行与 os-release 是同一事实源，这里复刻发行版包的派生
        # 规则；派生本身由 spec %check 断言，沙箱只保证两处默认一致。
        hit = re.search(r'^PRETTY_NAME="([^"]*)"', body, re.M)
        self.write_issue(hit.group(1) if hit else "")
        return path

    def write_issue(self, brand):
        path = self.sysroot / "etc" / "issue"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{brand}\nKernel \\r on an \\m (\\l)\n",
                        encoding="utf-8")
        return path

    def write_boot(self, kind, body):
        path = self.sysroot / "boot" / f"{kind}-{KREL}"
        path.write_text(body, encoding="utf-8")
        return path

    def write_lsm(self, body):
        path = self.sysroot / "sys" / "kernel" / "security" / "lsm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def install_display(self):
        """把策略脚本装进沙箱的 %{_prefix}/lib 路径，并给伪 xrandr 一份拓扑。"""
        dest = (self.sysroot / "usr" / "lib" / "airymaxos" / "desktop" /
                "display_mode.sh")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DISPLAY_MODE, dest)
        dest.chmod(0o755)
        self.topo = self.sysroot / "xrandr.topo"
        self.write_topo(TOPO_OK)
        return dest

    def write_topo(self, body):
        self.topo.write_text(body, encoding="utf-8")

    def write_mounts(self, body=MOUNTS):
        """T17 的挂载视图：伪 findmnt 按挂载点取源。"""
        self.mounts.write_text(body, encoding="utf-8")

    def write_blocks(self, body=BLOCKS):
        """T17 的块层表：伪 lsblk 给出设备类型与挂载点。"""
        self.blocks.write_text(body, encoding="utf-8")

    def write_marker(self, body=MARKER):
        """T1 的驱动标记：与 xserver.sh 写入的运行态文件同名同格式。"""
        path = self.sysroot / "run" / "airymaxos" / "xserver.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"AIRYMAX-XSERVER {body}", encoding="utf-8")
        return path

    def write_drm(self, status="connected", modes="1920x1080\n",
                  edid=b"\x00" * 128):
        """KMS 分支的连接器实况：状态、模式表与 EDID 缺一即不可用。"""
        out = self.sysroot / "sys" / "class" / "drm" / "card0-DP-1"
        out.mkdir(parents=True, exist_ok=True)
        (out / "status").write_text(f"{status}\n", encoding="utf-8")
        (out / "modes").write_text(modes, encoding="utf-8")
        (out / "edid").write_bytes(edid)
        return out

    def start_xorg(self, *argv):
        """按标记拉起真实 X server 进程。标记与 argv 是否一致只能由运行中
        的命令行证明，因此这里起一个同名、同参数的长驻进程，伪 pgrep 只
        回放它的 pid，证据仍取自 /proc。"""
        path = self.bin / "Xorg"
        if not path.exists():
            fakes.write(self.bin, "Xorg",
                        "#!/bin/sh\ntrap 'exit 0' TERM\nread -r _\n")
        proc = subprocess.Popen([str(path), *argv], stdin=subprocess.PIPE)
        self.addCleanup(self.stop_xorg, proc)
        return proc

    @staticmethod
    def stop_xorg(proc):
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=10)

    def tools(self, omit=()):
        fakes.link_tools(self.bin)
        fakes.smoke_tools(self.bin, omit)
        self.contest(omit)
        # T15 的期望与剖面无关：逐行日志是两个剖面共同的产品口径，显示
        # 管理器在不在都不改它。
        self.set_profile()

    def set_profile(self, desktop=True):
        path = self.sysroot / "usr" / "bin" / "lightdm"
        if not desktop:
            if path.exists():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n", encoding="utf-8")

    def contest(self, omit=()):
        """把真实的 airy-bench / airy-observe / airy-demo 放进 PATH：T16 判定
        的是这三个脚本自身的行为，用伪实现会掩盖自检逻辑的回归。"""
        for name, src in (("airy-bench", "airy_bench.py"),
                          ("airy-observe", "airy_observe.sh"),
                          ("airy-demo", "airy_demo.py")):
            if name in omit:
                continue
            dest = self.bin / name
            shutil.copy2(DESKTOP / src, dest)
            dest.chmod(0o755)

    def run_script(self, *args, **extra):
        env = {
            "PATH": str(self.bin),
            "HOME": str(self.root),
            "DISPLAY": ":0",
            "XDG_SESSION_ID": "2",
            "GTK_IM_MODULE": "ibus",
            "QT_IM_MODULE": "ibus",
            "XMODIFIERS": "@im=ibus",
            "FAKE_PROCS": "ukui-session-manager ibus-daemon",
            # T24 判的是 pid 本身：默认给一组固定 pid，等价于「桌面已收敛、
            # 本轮观测内没有重启」。要模拟 churn 的用例改用 FAKE_PIDS_BUMP。
            "FAKE_PIDS": " ".join(f"{name}={pid}" for name, pid in
                                  zip(SESSION_PROCS, range(100, 104))),
            "FAKE_X_PID": str(self.xorg.pid),
            "FAKE_XRANDR_TOPO": str(self.topo),
            "FAKE_FINDMNT_DB": str(self.mounts),
            "FAKE_LSBLK_DB": str(self.blocks),
            "FAKE_RPM_NAMES": " ".join(PACKAGES),
            "PYTHONPATH": str(SERVICES),
            "AIRYMAX_SMOKE_WAIT": "0",
            "AIRYMAX_SMOKE_ROOT": str(self.sysroot),
        }
        env.update(extra)
        return subprocess.run([BASH, str(SCRIPT), *args], env=env,
                              text=True, capture_output=True)

    def run_smoke(self, **extra):
        return self.run_script("airymaxos-0.0.4", **extra)

    def taps(self, res):
        return [line for line in res.stdout.splitlines()
                if line.startswith(("ok ", "not ok "))]

    def tap(self, res, num):
        for line in self.taps(res):
            parts = line.split()
            if parts[0] == "ok" and parts[1] == str(num):
                return line
            if parts[0] == "not" and parts[2] == str(num):
                return line
        self.fail(f"no TAP line for probe {num}")

    def summary(self, res):
        lines = [line for line in res.stdout.splitlines()
                 if line.startswith("# summary:")]
        self.assertEqual(len(lines), 1, res.stdout)
        fields = lines[0].split(": ", 1)[1].split()
        return {key: int(value) for key, value in
                (field.split("=", 1) for field in fields)}

    def planned(self, res):
        """TAP 计划数是各项计数的唯一来源，计划增长时不必逐处改断言。"""
        lines = [line for line in res.stdout.splitlines()
                 if re.fullmatch(r"1\.\.\d+", line)]
        self.assertEqual(len(lines), 1, res.stdout)
        return int(lines[0].split("..")[1])

    def assert_fail(self, res, num):
        line = self.tap(res, num)
        self.assertTrue(line.startswith("not ok"), line)

    def test_all_pass(self):
        self.tools()
        res = self.run_smoke()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.summary(res),
                         {"pass": self.planned(res), "fail": 0})
        self.assertNotIn("# SKIP", res.stdout)
        self.assertEqual(len(self.taps(res)), self.planned(res))
        for line in self.taps(res):
            self.assertTrue(line.startswith("ok"), line)

    def test_tap_plan(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("TAP version 14", res.stdout)
        self.assertEqual(len(self.taps(res)), self.planned(res), res.stdout)
        self.assertIn(
            "# AirymaxOS distro smoke: target=airymaxos-0.0.4", res.stdout)

    def test_requires_target(self):
        self.tools()
        res = self.run_script()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("usage: run-smoke.sh", res.stderr)

    def test_no_legacy_probes(self):
        text = SCRIPT.read_text(encoding="utf-8").lower()
        for token in LEGACY:
            self.assertNotIn(token, text)

    def test_display_unset(self):
        self.tools()
        res = self.run_smoke(DISPLAY="")
        self.assert_fail(res, 1)
        self.assertIn("DISPLAY unset", res.stdout)

    def test_session_id_unset(self):
        self.tools()
        res = self.run_smoke(XDG_SESSION_ID="")
        self.assert_fail(res, 1)
        self.assertIn("XDG_SESSION_ID unset", res.stdout)

    def test_x11_unreachable(self):
        self.tools()
        res = self.run_smoke(FAKE_XDPYINFO="fail")
        self.assert_fail(res, 1)
        self.assertIn("X11 unreachable: :0", res.stdout)

    def test_xserver_marker_missing(self):
        """没有标记就无法判断座位是否按显示能力选择过驱动。"""
        self.tools()
        self.marker.unlink()
        res = self.run_smoke()
        self.assert_fail(res, 1)
        self.assertIn("xserver marker missing", res.stdout)

    def test_xserver_fbdev_not_applied(self):
        """标记声称已切 fbdev，X 的 argv 却没有 -config：报告正常而屏黑。"""
        self.tools()
        bare = self.start_xorg()
        res = self.run_smoke(FAKE_X_PID=str(bare.pid))
        self.assert_fail(res, 1)
        self.assertIn(f"xserver is not using {XCONF}", res.stdout)

    def test_xserver_kms_ready(self):
        """真实驱动 + 已连接 + 模式 + EDID：kms 标记成立，未强加配置。"""
        self.tools()
        self.write_marker("driver=i915 kms=1\n")
        self.write_drm()
        bare = self.start_xorg()
        res = self.run_smoke(FAKE_X_PID=str(bare.pid))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_xserver_kms_without_edid(self):
        """驱动在、口已连、有模式，但 EDID 为空：模式求交仍会失败。"""
        self.tools()
        self.write_marker("driver=i915 kms=1\n")
        self.write_drm(edid=b"")
        bare = self.start_xorg()
        res = self.run_smoke(FAKE_X_PID=str(bare.pid))
        self.assert_fail(res, 1)
        self.assertIn("no ready output", res.stdout)

    def test_xserver_kms_forced_config(self):
        """kms 成立时仍强加 fbdev 配置，说明封装与实况已经脱节。"""
        self.tools()
        self.write_marker("driver=i915 kms=1\n")
        self.write_drm()
        res = self.run_smoke()
        self.assert_fail(res, 1)
        self.assertIn("kms i915 forced a config", res.stdout)

    def test_xserver_absent(self):
        """判为无显示却仍在跑 X：标记与座位状态互相矛盾。"""
        self.tools()
        self.write_marker("driver=none note=no-display\n")
        res = self.run_smoke()
        self.assert_fail(res, 1)
        self.assertIn("display reported as absent", res.stdout)

    def test_session_not_x11(self):
        self.tools()
        self.assert_fail(self.run_smoke(FAKE_TYPE="tty"), 1)

    def test_service_not_lightdm(self):
        self.tools()
        self.assert_fail(self.run_smoke(FAKE_SERVICE="sddm"), 1)

    def test_session_inactive(self):
        self.tools()
        self.assert_fail(self.run_smoke(FAKE_ACTIVE="no"), 1)

    def test_no_ukui_session(self):
        self.tools()
        res = self.run_smoke(FAKE_PROCS="ibus-daemon")
        self.assert_fail(res, 1)
        self.assertIn("ukui-session not running", res.stdout)

    def test_ibus_down(self):
        self.tools()
        res = self.run_smoke(FAKE_PROCS="ukui-session-manager")
        self.assert_fail(res, 2)
        self.assertIn("ibus-daemon not running", res.stdout)

    def test_ibus_unreachable(self):
        self.tools()
        res = self.run_smoke(FAKE_IBUS="fail")
        self.assert_fail(res, 2)
        self.assertIn("ibus engine unavailable", res.stdout)

    def test_ibus_engine_empty(self):
        self.tools()
        res = self.run_smoke(FAKE_IBUS_ENGINE="")
        self.assert_fail(res, 2)
        self.assertIn("ibus engine: empty", res.stdout)

    def test_im_variables(self):
        self.tools()
        for name in ("GTK_IM_MODULE", "QT_IM_MODULE", "XMODIFIERS"):
            with self.subTest(name=name):
                res = self.run_smoke(**{name: ""})
                self.assert_fail(res, 2)
                self.assertIn(name, res.stdout)

    def test_ibus_absent(self):
        self.tools(omit=("ibus",))
        res = self.run_smoke()
        self.assert_fail(res, 2)
        self.assertIn("ibus not installed", res.stdout)

    def test_pactl_unreachable(self):
        self.tools()
        res = self.run_smoke(FAKE_PACTL="fail")
        self.assert_fail(res, 3)
        self.assertIn("PulseAudio unreachable", res.stdout)

    def test_pactl_absent(self):
        self.tools(omit=("pactl",))
        res = self.run_smoke()
        self.assert_fail(res, 3)
        self.assertIn("pactl not installed", res.stdout)

    def test_audio_latency(self):
        self.tools()
        ready = self.root / "pactl.ready"
        fakes.write(self.bin, "pactl",
                    "#!/bin/sh\n[ -e '%s' ] || exit 1\n" % ready)
        timer = threading.Timer(1.5, ready.touch)
        timer.start()
        try:
            res = self.run_smoke(AIRYMAX_SMOKE_WAIT="15")
        finally:
            timer.cancel()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.summary(res),
                         {"pass": self.planned(res), "fail": 0})

    def test_slice_wrong(self):
        self.tools()
        res = self.run_smoke(FAKE_SLICE="user.slice")
        self.assert_fail(res, 4)
        self.assertIn("user@ service slice: user.slice", res.stdout)

    def test_slice_inactive(self):
        self.tools()
        res = self.run_smoke(FAKE_SLICE_ACTIVE="inactive")
        self.assert_fail(res, 4)
        self.assertIn("slice state: inactive", res.stdout)

    def test_slice_weights(self):
        self.tools()
        for name in ("FAKE_CPU", "FAKE_IO"):
            with self.subTest(name=name):
                self.assert_fail(self.run_smoke(**{name: "100"}), 4)

    def test_slice_weight_protected(self):
        """争用下 coexist 抬到 200 是 X-05 的合法取值，不能判负。"""
        self.tools()
        res = self.run_smoke(FAKE_CPU="200")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_slice_tasks_infinity(self):
        self.tools()
        res = self.run_smoke(FAKE_TASKS="infinity")
        self.assert_fail(res, 4)
        self.assertIn("slice TasksMax: infinity", res.stdout)

    def test_wallpaper_tool_absent(self):
        self.tools(omit=("gsettings",))
        res = self.run_smoke()
        self.assert_fail(res, 5)
        self.assertIn("gsettings not installed", res.stdout)

    def test_wallpaper_schema_missing(self):
        self.tools()
        res = self.run_smoke(FAKE_GSETTINGS="fail")
        self.assert_fail(res, 5)
        self.assertIn("No such schema 'org.mate.background'", res.stdout)

    def test_wallpaper_path_wrong(self):
        self.tools()
        res = self.run_smoke(FAKE_PAPER="/usr/share/backgrounds/gnome/adwaita.jpg")
        self.assert_fail(res, 5)
        self.assertIn("picture-filename", res.stdout)

    def test_wallpaper_unreadable(self):
        self.tools()
        res = self.run_smoke(FAKE_SHA256SUM="fail")
        self.assert_fail(res, 5)
        self.assertIn("wallpaper unreadable", res.stdout)

    def test_wallpaper_checksum(self):
        self.tools()
        res = self.run_smoke(FAKE_PAPER_SHA="0" * 64)
        self.assert_fail(res, 5)
        self.assertIn("wallpaper sha256", res.stdout)

    def test_probe_tool_absent_fails(self):
        self.tools(omit=("loginctl",))
        res = self.run_smoke()
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertEqual(self.summary(res),
                         {"pass": self.planned(res) - 1, "fail": 1})
        self.assert_fail(res, 1)
        self.assertIn("loginctl not installed", res.stdout)
        self.assertNotIn("# SKIP", res.stdout)

    def test_kernel_not_alk(self):
        self.tools()
        res = self.run_smoke(FAKE_KERNEL_RELEASE="6.6.0-1.oe2403")
        self.assert_fail(res, 6)
        self.assertIn("uname -r: 6.6.0-1.oe2403 (want *-alk)", res.stdout)

    def test_kernel_boot_files_missing(self):
        self.tools()
        (self.sysroot / "boot" / f"config-{KREL}").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 6)
        self.assertIn(f"/boot/config-{KREL} missing", res.stdout)

    def test_kernel_config_mismatch(self):
        self.tools()
        self.write_boot("config", 'CONFIG_LOCALVERSION=""\n'
                                  "CONFIG_SECURITY_AIRY=y\n")
        res = self.run_smoke()
        self.assert_fail(res, 6)
        self.assertIn(f"config-{KREL}: LOCALVERSION mismatch", res.stdout)

    def test_kernel_module_unsigned(self):
        self.tools()
        mod = self.write_module(PLAIN_KO)
        res = self.run_smoke()
        self.assert_fail(res, 6)
        self.assertIn(f"unsigned module: {mod}", res.stdout)
        self.assertIn("1/1 modules unsigned", res.stdout)

    def test_kernel_module_unsigned_among_signed(self):
        self.tools()
        bad = (self.sysroot / "usr" / "lib" / "modules" / KREL / "kernel" /
               "fs" / "ext4" / "ext4.ko")
        bad.parent.mkdir(parents=True)
        bad.write_bytes(PLAIN_KO)
        res = self.run_smoke()
        self.assert_fail(res, 6)
        self.assertIn(f"unsigned module: {bad}", res.stdout)
        self.assertIn("1/2 modules unsigned", res.stdout)

    def test_kernel_tainted_by_unsigned_module(self):
        self.tools()
        self.write_taint(8192)
        res = self.run_smoke()
        self.assert_fail(res, 6)
        self.assertIn("kernel tainted by unsigned module (tainted=8192)",
                      res.stdout)

    def test_kernel_taint_unreadable(self):
        # 污染位读不到不等于零：旧行为把缺失当 0 静默放行，掩盖了未签名模块。
        self.tools()
        (self.sysroot / "proc" / "sys" / "kernel" / "tainted").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 6)
        self.assertIn("tainted unreadable", res.stdout)

    def test_lsm_duplicate_airy(self):
        self.tools()
        # 补充钩子在 late_initcall 里以同名二次注册时，注册表会出现两个
        # airy；这不是两个模块，必须判失败。
        self.write_lsm("airy_lockdown,lockdown,capability,yama,airy,selinux,"
                       "airy")
        res = self.run_smoke()
        self.assert_fail(res, 7)
        self.assertIn("airy registered 2 time(s)", res.stdout)

    def test_lsm_lockdown_absent(self):
        self.tools()
        self.write_lsm("lockdown,capability,yama,airy,selinux")
        res = self.run_smoke()
        self.assert_fail(res, 7)
        self.assertIn("airy_lockdown absent", res.stdout)

    def test_lsm_registry_unreadable(self):
        self.tools()
        (self.sysroot / "sys" / "kernel" / "security" / "lsm").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 7)
        self.assertIn("lsm registry unreadable", res.stdout)

    def test_hostname_default(self):
        self.tools()
        # 安装器缺省名（localhost.localdomain）说明配方没写 hostname。
        self.write_product("localhost.localdomain", OS_RELEASE)
        res = self.run_smoke()
        self.assert_fail(res, 8)
        self.assertIn(f"hostname: localhost.localdomain (want {HOSTNAME})",
                      res.stdout)

    def test_hostname_runtime_diverges(self):
        self.tools()
        # 静态文件对、内核名不对：0.0.3 靠 sysctl.d 回写，任一环脱钩都会让
        # 现场同时看到两个名字，T8 必须分别报出分叉的那一环。
        fakes.write(self.bin, "hostname", "#!/bin/sh\nprintf 'airymaxos\\n'\n")
        res = self.run_smoke()
        self.assert_fail(res, 8)
        self.assertIn(f"kernel hostname: airymaxos (want {HOSTNAME})",
                      res.stdout)

    def test_hostname_absent(self):
        self.tools()
        (self.sysroot / "etc" / "hostname").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 8)
        self.assertIn("/etc/hostname unreadable", res.stdout)

    def test_brand_name_is_base(self):
        self.tools()
        # NAME 的词根必须与 PRETTY_NAME 的短名同源；底座名直接判失败，避免
        # 只改 os-release 一处就蒙过品牌面。
        self.write_osrel(OS_RELEASE.replace('NAME="OpenAirymax"',
                                            'NAME="openEuler"'))
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("os-release NAME: openEuler", res.stdout)

    def test_brand_name_not_ascii(self):
        self.tools()
        # NAME 被 grub 的 10_linux 原样写进菜单标题，而 unicode.pf2 没有 CJK
        # 字形，中文在引导菜单上整段不显示；该通道只收 ASCII。
        self.write_osrel(OS_RELEASE.replace('NAME="OpenAirymax"',
                                            'NAME="OpenAirymax 开源极境"'))
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("want ASCII", res.stdout)

    def test_brand_pretty_no_version(self):
        self.tools()
        # PRETTY_NAME 少了版本段就不满足「<短名> <VERSION_ID>」，引导菜单与
        # system-release 的派生会同时错位。
        self.write_osrel(OS_RELEASE.replace('PRETTY_NAME="OpenAirymax 0.0.4"',
                                            'PRETTY_NAME="OpenAirymax"'))
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("os-release PRETTY_NAME: OpenAirymax", res.stdout)

    def test_brand_pretty_not_ascii(self):
        self.tools()
        # 短名要进引导菜单、ISO 卷标与 NVRAM，全是非 UTF-8 通道；os-release
        # 的两个名字键都只收 ASCII。
        self.write_osrel(OS_RELEASE.replace('PRETTY_NAME="OpenAirymax 0.0.4"',
                                            'PRETTY_NAME="开源极境 0.0.4"'))
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("want '<brand> <version>'", res.stdout)

    def test_issue_brand_drift(self):
        self.tools()
        # /etc/issue 是登录前最先露出的品牌面，与 os-release 脱钩说明有两处
        # 事实源。
        self.write_issue("AirymaxOS 0.0.4")
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("issue 首行: AirymaxOS 0.0.4 (want OpenAirymax 0.0.4)",
                      res.stdout)

    def test_brand_version_not_semver(self):
        self.tools()
        self.write_osrel(OS_RELEASE.replace('VERSION_ID="0.0.4"',
                                            'VERSION_ID="rolling"'))
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("os-release VERSION_ID: rolling", res.stdout)

    def test_brand_absent(self):
        self.tools()
        (self.sysroot / "etc" / "os-release").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 9)
        self.assertIn("/etc/os-release unreadable", res.stdout)


    def test_display_off_policy(self):
        self.tools()
        # 无 EDID 的 4K 首选按阶梯收到 1920x1080，会话仍停在 3840x2160 即判失败。
        self.write_topo(TOPO_4K)
        res = self.run_smoke()
        self.assert_fail(res, 10)
        self.assertIn("eDP-1:3840x2160->1920x1080", res.stdout)

    def test_display_tool_absent(self):
        self.tools(omit=("xrandr",))
        res = self.run_smoke()
        self.assert_fail(res, 10)
        self.assertIn("xrandr not installed", res.stdout)

    def test_display_no_output(self):
        self.tools()
        self.write_topo("Screen 0: minimum 8 x 8, current 640 x 480,"
                        " maximum 32767 x 32767\n"
                        "DP-1 disconnected (normal) 0mm x 0mm\n")
        res = self.run_smoke()
        self.assert_fail(res, 10)
        self.assertIn("无 connected 输出", res.stdout)

    def test_display_script_absent(self):
        self.tools()
        (self.sysroot / "usr" / "lib" / "airymaxos" / "desktop" /
         "display_mode.sh").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 10)
        self.assertIn("display_mode.sh not installed", res.stdout)

    def test_display_report_carries_backend(self):
        """单模式输出下，报告仍须给出 X 后端与 DRM 卡数。

        验收镜像的桌面组件崩在 fbdev 上，journal 只说「dumped core」；
        唯一能区分「没有 KMS 设备」与「有设备但驱动没接管」的，是 X 的
        自述与卡节点数，故此两者必须随 T10 一起落进 TAP。
        """
        self.tools()
        res = self.run_smoke()
        self.assertIn("xserver=driver=fbdev reason=no-kms", res.stdout)
        self.assertIn(" drm=0", res.stdout)

    def test_efi_brand_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 11 - T11 efi boot brand", res.stdout)

    def test_efi_brand_missing_shim(self):
        self.tools()
        (self.sysroot / "boot" / "efi" / "EFI" / "airymaxos" /
         "shimx64.efi").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 11)
        self.assertIn("shimx64.efi missing", res.stdout)

    def test_efi_brand_missing_csv(self):
        self.tools()
        (self.sysroot / "boot" / "efi" / "EFI" / "airymaxos" /
         "BOOTX64.CSV").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 11)
        self.assertIn("BOOTX64.CSV missing", res.stdout)

    def test_efi_brand_missing_state(self):
        # 品牌脚本走 skip 时 ESP 里可能一套齐全却没有状态文件：那正是旧实现
        # 「静默成功」的形态，验收必须失败并给出日志末行
        self.tools()
        (self.sysroot / "var" / "lib" / "airymaxos" / "efi-brand").unlink()
        self.write_brand_log("AIRYMAX-EFI-NOTE fail: efibootmgr unavailable\n")
        res = self.run_smoke()
        self.assert_fail(res, 11)
        self.assertIn("efi-brand state missing", res.stdout)
        self.assertIn("state=absent", res.stdout)
        self.assertIn("log=AIRYMAX-EFI-NOTE fail: efibootmgr unavailable",
                      res.stdout)

    def test_efi_brand_non_efi(self):
        # 纯 BIOS 装机没有 NVRAM 条目可写，本项不适用，但仍要留痕
        self.tools()
        (self.sysroot / "sys" / "firmware" / "efi").rmdir()
        res = self.run_smoke()
        self.assertIn("ok 11 - T11 efi boot brand", res.stdout)
        self.assertIn("non-EFI target", res.stdout)

    def test_sudo_policy_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 12 - T12 passwordless elevation", res.stdout)
        self.assertIn("policy file ok (offline check)", res.stdout)

    def test_sudo_policy_missing(self):
        self.tools()
        (self.sysroot / "etc" / "sudoers.d" / "90-airymax").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 12)
        self.assertIn("90-airymax missing", res.stdout)

    def test_sudo_policy_line_absent(self):
        # 文件在但策略被改成要口令：只认有效规则行，不认文件名
        self.tools()
        self.write_sudoers().write_text(
            "amuser ALL=(ALL) ALL\n", encoding="utf-8")
        res = self.run_smoke()
        self.assert_fail(res, 12)
        self.assertIn("policy line absent", res.stdout)

    def test_screensaver_policy_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 13 - T13 passwordless desktop", res.stdout)
        self.assertIn("screensaver policy ok (offline check)", res.stdout)

    def test_screensaver_policy_missing(self):
        self.tools()
        self.write_screensaver().unlink()
        res = self.run_smoke()
        self.assert_fail(res, 13)
        self.assertIn("00-airymax-screensaver missing", res.stdout)

    def test_screensaver_lock_enabled(self):
        # 键文件在但锁屏仍开：空口令账户照样被口令框拦住，必须逐键判定
        self.tools()
        self.write_screensaver().write_text(
            "[org/ukui/screensaver]\n"
            "idle-lock-enabled=false\n"
            "lock-enabled=true\n", encoding="utf-8")
        res = self.run_smoke()
        self.assert_fail(res, 13)
        self.assertIn("lock-enabled not disabled", res.stdout)

    def test_repo_sources_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 14 - T14 installed dnf sources", res.stdout)
        self.assertIn("2 enabled section(s) on repo.openeuler.org", res.stdout)

    def test_repo_file_missing(self):
        # 只有 kickstart 的 url/repo 行、没有客户端文件：装得进去，装完无源
        self.tools()
        self.write_repo().unlink()
        res = self.run_smoke()
        self.assert_fail(res, 14)
        self.assertIn("airymaxos.repo unreadable", res.stdout)

    def test_repo_releasever(self):
        # $releasever 在产品系统里展开为 VERSION_ID，基底镜像路径随之失效
        self.tools()
        self.write_repo(REPO.replace("openEuler-24.03-LTS-SP3",
                                     "openEuler-$releasever"))
        res = self.run_smoke()
        self.assert_fail(res, 14)
        self.assertIn("$releasever does not name the base release", res.stdout)

    def test_repo_plain_http(self):
        self.tools()
        self.write_repo(REPO.replace("baseurl=https://",
                                     "baseurl=http://"))
        res = self.run_smoke()
        self.assert_fail(res, 14)
        self.assertIn("section airymaxos-base baseurl: http://", res.stdout)

    def test_repo_host_mixed(self):
        # 各段落在不同镜像上，说明基址被逐段手改过，必然有一段落伍
        self.tools()
        self.write_repo(REPO.replace(
            "baseurl=https://repo.openeuler.org/openEuler-24.03-LTS-SP3/update/",
            "baseurl=https://mirror.example.net/openEuler-24.03-LTS-SP3/update/"))
        res = self.run_smoke()
        self.assert_fail(res, 14)
        self.assertIn("section airymaxos-updates host: mirror.example.net"
                      " (want repo.openeuler.org)", res.stdout)

    def test_repo_no_enabled(self):
        self.tools()
        self.write_repo(REPO.replace("enabled=1", "enabled=0"))
        res = self.run_smoke()
        self.assert_fail(res, 14)
        self.assertIn("no enabled section", res.stdout)

    def test_boot_args_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 15 - T15 durable boot arguments", res.stdout)
        self.assertIn('args="console=ttyS0,115200 console=tty0 loglevel=5'
                      ' plymouth.enable=0"', res.stdout)

    def test_boot_args_console_order(self):
        # /dev/console 取最后一个 console=；tty0 必须在末位，否则
        # systemd-vconsole-setup 锁不住 VT（285H 实测）
        self.tools()
        self.write_grub(GRUB_DEFAULTS.replace(
            "console=ttyS0,115200 console=tty0",
            "console=tty0 console=ttyS0,115200"))
        res = self.run_smoke()
        self.assert_fail(res, 15)
        self.assertIn("primary console is console=ttyS0,115200, not tty0",
                      res.stdout)

    def test_boot_args_ghost_console(self):
        # 现场手工加进命令行的控制台会抢占 /dev/console，必须判失败
        self.tools()
        self.write_grub(GRUB_DEFAULTS.replace(
            "console=tty0", "console=ttyAMA0,115200 console=tty0"))
        res = self.run_smoke()
        self.assert_fail(res, 15)
        self.assertIn("carries a foreign console", res.stdout)

    def test_boot_args_brand_drift(self):
        # 品牌副本是活动配置：与生成件不一致时，改参数与内核升级在重启后
        # 都不生效（285H 实测，D-07）
        self.tools()
        esp = self.sysroot / "boot" / "efi" / "EFI" / "airymaxos"
        (esp / "grub.cfg").write_text("menuentry 'old' {\n}\n",
                                      encoding="utf-8")
        res = self.run_smoke()
        self.assert_fail(res, 15)
        self.assertIn("brand grub.cfg differs from the generated one",
                      res.stdout)

    def test_boot_args_no_loglevel(self):
        # 内核口压低到 warning 的现场：启动阶段行消失，卡住时屏幕静止
        self.tools()
        self.write_grub(GRUB_DEFAULTS.replace(" loglevel=5", ""))
        res = self.run_smoke()
        self.assert_fail(res, 15)
        self.assertIn("GRUB_CMDLINE_LINUX lacks loglevel=5", res.stdout)

    def test_boot_args_no_plymouth(self):
        # 未关 plymouth：oneshot 的写回单元无界等待即卡死 sysinit（285H）
        self.tools()
        self.write_grub(GRUB_DEFAULTS.replace(" plymouth.enable=0", ""))
        res = self.run_smoke()
        self.assert_fail(res, 15)
        self.assertIn("GRUB_CMDLINE_LINUX lacks plymouth.enable=0",
                      res.stdout)

    def test_boot_args_stale_splash(self):
        # 升级机器上旧画面参数仍在：启动画面重新遮蔽阶段行，等于没改
        self.tools()
        self.write_grub(GRUB_DEFAULTS.replace(
            "plymouth.enable=0", "plymouth.enable=0 rhgb quiet"))
        res = self.run_smoke()
        self.assert_fail(res, 15)
        self.assertIn("GRUB_CMDLINE_LINUX still carries rhgb", res.stdout)

    def test_boot_args_minimal_profile(self):
        # 最小剖面与桌面剖面在引导参数上一致：逐行日志不依赖图形栈，判定
        # 若只认桌面，最小装机要么被误判失败，要么反过来把阶段行藏起来
        # （D-30）。
        self.tools()
        self.set_profile(desktop=False)
        res = self.run_smoke()
        self.assertIn("ok 15 - T15 durable boot arguments", res.stdout)
        self.assertIn('args="console=ttyS0,115200 console=tty0 loglevel=5'
                      ' plymouth.enable=0"', res.stdout)

    def test_boot_args_prober_enabled(self):
        # os-prober 未关：同盘其他发行版的内核会并进本产品启动菜单
        self.tools()
        self.write_grub(GRUB_DEFAULTS.replace("GRUB_DISABLE_OS_PROBER=true",
                                              "#GRUB_DISABLE_OS_PROBER=true"))
        res = self.run_smoke()
        self.assert_fail(res, 15)
        self.assertIn("os-prober not disabled", res.stdout)

    def test_boot_args_timeout(self):
        # 停留时间未归一化：安装末期那一步没跑到，每次开机多等 3 秒
        self.tools()
        self.write_grub(GRUB_DEFAULTS.replace("GRUB_TIMEOUT=1",
                                              "GRUB_TIMEOUT=3"))
        res = self.run_smoke()
        self.assert_fail(res, 15)
        self.assertIn("menu timeout not normalized", res.stdout)

    def test_boot_args_file_absent(self):
        self.tools()
        self.write_grub().unlink()
        res = self.run_smoke()
        self.assert_fail(res, 15)
        self.assertIn("/etc/default/grub unreadable", res.stdout)

    def test_console_runtime_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 22 - T22 runtime console state", res.stdout)

    def test_console_runtime_ghost(self):
        # 默认文件收敛了，但引导项仍是旧的一串：现场手工加的控制台留在
        # 已写的 grub.cfg 里，只查默认文件会判过（HW-05）
        self.tools()
        self.write_cmdline(CMDLINE.replace(
            "console=tty0",
            "console=ttyAMA0,115200 console=tty0"))
        res = self.run_smoke()
        self.assert_fail(res, 22)
        self.assertIn("/proc/cmdline carries a foreign console", res.stdout)

    def test_console_runtime_vt_last(self):
        # VT 不在末位时 /dev/console 落到串口，VT 侧看不到任何启动输出
        self.tools()
        self.write_cmdline(CMDLINE.replace(
            "console=ttyS0,115200 console=tty0",
            "console=tty0 console=ttyS0,115200"))
        res = self.run_smoke()
        self.assert_fail(res, 22)
        self.assertIn("primary console is console=ttyS0,115200, not tty0",
                      res.stdout)

    def test_console_unit_failed(self):
        # 命令行正确但 VT 已被别处占住：单元以 failed 收场，桌面就绪门禁
        # 每个启动周期都会重演一次失败
        self.tools()
        res = self.run_smoke(FAKE_ACTIVE_STATE="failed")
        self.assert_fail(res, 22)
        self.assertIn("systemd-vconsole-setup: failed (want active)",
                      res.stdout)

    def test_console_font_psf1(self):
        # 285H 的原始现场：FONT 指向的文件存在、路径也对，但它是 PSF1，
        # 没有尺寸字段、固定 8 列，在 2880 宽的屏上仍是不可读的细条
        self.tools()
        self.write_vconsole(psf2=False)
        res = self.run_smoke()
        self.assert_fail(res, 22)
        self.assertIn("is not a PSF2 font", res.stdout)

    def test_console_font_too_small(self):
        # 换成 PSF2 也可能换小了：判据取几何而不是文件名，型号改小仍要拦
        self.tools()
        self.write_vconsole(w=8, h=16)
        res = self.run_smoke()
        self.assert_fail(res, 22)
        self.assertIn("is 8x16, below 12x24", res.stdout)

    def test_console_font_absent(self):
        # 配置写着字体名但镜像没带该文件：setfont 失败后 VT 回落到默认小字，
        # 日志里只有一行告警，控制台看起来「什么都没改」
        self.tools()
        self.write_vconsole(font="no-such-font", write_font=False)
        res = self.run_smoke()
        self.assert_fail(res, 22)
        self.assertIn("font no-such-font is absent from", res.stdout)

    def test_console_runtime_absent(self):
        # 读不到本次命令行即无从判定，按失败计而不是放行
        self.tools()
        self.write_cmdline().unlink()
        res = self.run_smoke()
        self.assert_fail(res, 22)
        self.assertIn("proc/cmdline unreadable", res.stdout)

    def test_inventory_ok(self):
        # 三个面同时干净：无失败单元、本次开机无 err、包集合与交付清单一致
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 23 - T23 system inventory", res.stdout)
        self.assertIn("state=ok units=0 errors=0 owned=0 foreign=0"
                      " firmware=0 unknown=0", res.stdout)
        self.assertIn("packages=ok", res.stdout)

    def test_inventory_failed_unit(self):
        # 单元失败但日志停在 info：只查日志的形态会漏
        self.tools()
        res = self.run_smoke(FAKE_FAILED_UNITS="airymax-desktop.service")
        self.assert_fail(res, 23)
        self.assertIn("state=failed", res.stdout)

    def test_inventory_ignores_harness_report(self):
        # 判定者不把自己的结论当证据：上报单元的失败是同一轮 TAP 结论的
        # 搬运，同一次开机的后续每一轮都会读到它，真实根因被自指信号盖住。
        self.tools()
        res = self.run_smoke(FAKE_FAILED_UNITS="airymax-smoke-report.service")
        self.assertTrue(self.tap(res, 23).startswith("ok"), res.stdout)
        self.assertIn("units=0", res.stdout)

    def test_tap_carries_boot_id(self):
        # TAP 与写出它的那次开机绑定，报告侧据此拒绝上一轮的旧结论
        self.tools()
        res = self.run_smoke()
        stamped = [line for line in res.stdout.splitlines()
                   if line.startswith("# boot=")]
        self.assertEqual(len(stamped), 1, res.stdout)
        self.assertNotEqual(stamped[0], "# boot=")

    def test_inventory_package_drift(self):
        # 装机后多装一个包：系统构成已变，交付集合不再是实际集合
        self.tools()
        res = self.run_smoke(
            FAKE_RPM_NAMES=" ".join(PACKAGES + ("extra-pkg",)))
        self.assert_fail(res, 23)
        self.assertIn("extra=1", res.stdout)

    def test_inventory_journal_err(self):
        # 日志刷错但没有单元失败：另一侧的证据必须独立成立。纯文本行拿不到
        # 归属单元，按未知层计，预算再宽也不放行。
        self.tools()
        log = self.root / "journal.log"
        log.write_text("amuser.service: Failed to start\n", encoding="utf-8")
        res = self.run_smoke(FAKE_JOURNAL_FILE=str(log), AIRYMAX_SMOKE_BUDGET="9")
        self.assert_fail(res, 23)
        self.assertIn("unknown=1", res.stdout)

    def journal(self, *records):
        """写一份 journald JSON 日志，供 T23 判归属与预算。"""
        log = self.root / "journal.log"
        log.write_text("".join(
            json.dumps(rec) + "\n" for rec in records), encoding="utf-8")
        return {"FAKE_JOURNAL_FILE": str(log)}

    def test_inventory_foreign_within_budget(self):
        # 基底自己刷的 err 在棘轮预算内：判据仍为通过，但计数必须如实打印，
        # 否则预算永远降不下来
        self.tools()
        res = self.run_smoke(
            AIRYMAX_SMOKE_BUDGET="1",
            **self.journal({"MESSAGE": "card busy",
                            "_SYSTEMD_UNIT": "cups.service"}))
        self.assertIn("ok 23 - T23 system inventory", res.stdout)
        self.assertIn("foreign=1 firmware=0 unknown=0 budget=1", res.stdout)

    def test_inventory_firmware_layer_free(self):
        # 主板 ACPI 表缺陷逐字重现、发行版改不了：单列固件层，不吃预算
        self.tools()
        res = self.run_smoke(
            AIRYMAX_SMOKE_BUDGET="0",
            **self.journal({"MESSAGE": "ACPI BIOS Error (bug): Failure "
                                       "creating named object",
                            "SYSLOG_IDENTIFIER": "kernel",
                            "_TRANSPORT": "kernel"}))
        self.assertIn("ok 23 - T23 system inventory", res.stdout)
        self.assertIn("firmware=1", res.stdout)

    def test_inventory_foreign_over_budget(self):
        # 同一条日志，预算收紧到 0 即失败：判定确实由预算驱动
        self.tools()
        res = self.run_smoke(
            AIRYMAX_SMOKE_BUDGET="0",
            **self.journal({"MESSAGE": "card busy",
                            "_SYSTEMD_UNIT": "cups.service"}))
        self.assert_fail(res, 23)
        self.assertIn("foreign=1", res.stdout)

    def test_inventory_owned_err(self):
        # 自有单元的 err 是本产品缺陷，预算再宽也不放过
        self.tools()
        res = self.run_smoke(
            AIRYMAX_SMOKE_BUDGET="9",
            **self.journal({"MESSAGE": "cannot bind socket",
                            "_SYSTEMD_UNIT": "airymax-desktop.service"}))
        self.assert_fail(res, 23)
        self.assertIn("owned=1", res.stdout)
        self.assertIn("[owned]", res.stdout)

    def test_session_steady(self):
        # 首尾 pid 逐字相同：本轮观测内没有组件被重新拉起
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 24 - T24 desktop session steady", res.stdout)

    def test_session_churn(self):
        # pid 变了就是被重新拉起过，与最终是否可用无关（2026-11-02 实测：
        # 开机 4.5–8.0 s 之间 panel 崩溃重启二十余次，桌面最终仍可用）
        self.tools()
        res = self.run_smoke(FAKE_PIDS_BUMP="ukui-panel=200")
        self.assert_fail(res, 24)
        self.assertIn("churn", res.stdout)

    def test_session_churn_reports_death(self):
        # churn 之后必须带出死法：本镜像的 systemd 未编入 elfutils，journal
        # 里既没有栈也没有信号，只有 coredumpctl 的 SIG 列能区分段错误与
        # abort，而这两者指向完全不同的根因方向
        self.tools()
        cores = self.root / "cores"
        cores.write_text(
            "TIME PID UID GID SIG COREFILE EXE\n"
            "Wed 2026-11-05 04:53:52 UTC 1108 1000 1000 11 present "
            "/usr/bin/ukui-panel\n", encoding="utf-8")
        res = self.run_smoke(FAKE_PIDS_BUMP="ukui-panel=200",
                             FAKE_CORE_LIST=str(cores))
        self.assert_fail(res, 24)
        self.assertIn("core: Wed 2026-11-05", res.stdout)

    def test_session_churn_reports_fault(self):
        # 死法之后还要「死在哪」：内核的段错误行带库名与库内偏移，是这台机器
        # 上唯一能把崩溃定位到具体组件的证据。同一现场在 ASLR 下每次的 ip/sp
        # 与库基址都不同，归一后必须收敛成一条，不能把诊断块刷满。
        self.tools()
        log = self.root / "fault.dmesg"
        log.write_text(
            "[  19.490000] ukui-panel[1634]: segfault at 0 ip 00007f1c2a3b4c5d "
            "sp 00007ffd1c2a3b4c5d error 4 in "
            "libQt5Core.so.5.15.2[7f1c2a000000+2f0000]\n"
            "[  19.490100] ukui-panel[1674]: segfault at 0 ip 00007f3e0a3b4c5d "
            "sp 00007ffe3a3b4c5d error 4 in "
            "libQt5Core.so.5.15.2[7f3e0a000000+2f0000]\n"
            "[  19.490200] ukui-kwin_x11[1703]: segfault at 8 "
            "ip 00007f0000000000 sp 00007fff00000000 error 6 in "
            "libkwin.so.5[7f0000000000+10000]\n"
            "[  19.490300] systemd[1]: Started Session 2 of User amuser.\n",
            encoding="utf-8")
        res = self.run_smoke(FAKE_PIDS_BUMP="ukui-panel=200",
                             FAKE_DMESG_FILE=str(log))
        self.assert_fail(res, 24)
        self.assertIn("kern: ukui-panel: segfault at 0 error 4 in "
                      "libQt5Core.so.5.15.2[+2f0000]", res.stdout)
        self.assertIn("kern: ukui-kwin_x11: segfault at 8 error 6 in "
                      "libkwin.so.5[+10000]", res.stdout)
        self.assertEqual(res.stdout.count("kern: "), 2, res.stdout)

    def test_session_proc_absent(self):
        # 核心进程不在：桌面残缺，不能因为「没有变化」而判过
        self.tools()
        res = self.run_smoke(FAKE_PIDS="")
        self.assert_fail(res, 24)
        self.assertIn("not running at end", res.stdout)

    def test_obs_tools_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 16 - T16 observer tools selfcheck", res.stdout)
        self.assertIn("bench=ok demo=ok observe=ok", res.stdout)
        for num in (19, 20, 21):
            self.assertTrue(self.tap(res, num).startswith("ok"), res.stdout)

    def fw_log(self, *lines):
        """写一份只含给定行内核日志，供三条固件判据各读一次。"""
        log = self.root / "dmesg.log"
        log.write_text("".join(f"[    2.100000] {line}\n" for line in lines),
                       encoding="utf-8")
        return {"FAKE_DMESG_FILE": str(log)}

    def test_fw_blob_missing(self):
        # 驱动仍加载成功、模块列表干净，只有内核日志留着「没找到固件」这一行
        self.tools()
        res = self.run_smoke(**self.fw_log(
            "iwlwifi 0000:00:14.3: no suitable firmware found"))
        self.assert_fail(res, 19)
        self.assertTrue(self.tap(res, 20).startswith("ok"), res.stdout)
        self.assertIn("no suitable firmware found", res.stdout)

    def test_fw_microcode_stale(self):
        # 微码 INIT 没跑起来时 CPU 仍可用，只有日志记着它退回了旧版本
        self.tools()
        res = self.run_smoke(**self.fw_log(
            "microcode: Failed to run INIT ucode: -5"))
        self.assert_fail(res, 20)
        self.assertIn("Failed to run INIT ucode", res.stdout)

    def test_fw_api_warn_load_ok(self):
        # 固件比内核新时驱动先告警再忽略不认识的标志组，随后照常载入：
        # 这是发行版常态，285H 的 BE200 即此形态，不得判负
        self.tools()
        res = self.run_smoke(**self.fw_log(
            "iwlwifi 0000:01:00.0: api flags index 2 larger than supported",
            "iwlwifi 0000:01:00.0: loaded firmware version 83.ec13314b.0 "
            "gl-c0-fm-c0-83.ucode op_mode iwlmvm"))
        self.assertTrue(self.tap(res, 21).startswith("ok"), res.stdout)
        self.assertIn("wireless firmware loaded: 83.ec13314b.0", res.stdout)

    def test_fw_api_device_without_load(self):
        # 设备枚举到了、告警也在，但始终没有 loaded firmware：无线不可用
        self.tools()
        res = self.run_smoke(**self.fw_log(
            "iwlwifi 0000:01:00.0: Detected crf-id 0x2001910, cnv-id 0x2001910",
            "iwlwifi 0000:01:00.0: api flags index 2 larger than supported"))
        self.assert_fail(res, 21)
        self.assertIn("wireless device without loaded firmware: 0000:01:00.0",
                      res.stdout)

    def test_fw_api_no_wireless(self):
        # 没有无线设备的机器（验收 QEMU）本项无事可判，按通过收场
        self.tools()
        res = self.run_smoke(**self.fw_log("loop: module loaded"))
        self.assertTrue(self.tap(res, 21).startswith("ok"), res.stdout)
        self.assertIn("no iwlwifi device", res.stdout)

    def test_fw_no_log(self):
        # 日志读不到时三条一起判负：没有证据不等于载入成功
        self.tools()
        res = self.run_smoke(FAKE_DMESG_FILE=str(self.root / "absent.log"))
        for num in (19, 20, 21):
            self.assert_fail(res, num)
        self.assertIn("kernel log unreadable", res.stdout)

    def test_fw_tool_absent(self):
        # 没有 dmesg 就无从判定，按工具缺失计，不静默放行
        self.tools(omit=("dmesg",))
        res = self.run_smoke()
        self.assert_fail(res, 19)
        self.assertIn("dmesg not installed", res.stdout)

    def test_desktop_assets_ok(self):
        # 判定看 fontconfig 解到了什么：沙箱给一族汉字字体即通过
        self.tools()
        res = self.run_smoke()
        self.assertIn("zh font: WenQuanYi Micro Hei", res.stdout)
        self.assertIn("icon theme: ukui", res.stdout)

    def test_desktop_no_cjk_font(self):
        # 只有西文字体的镜像：会话照常起来、西文正常，中文全是方框，
        # 0.0.4 首装现场即此形态
        self.tools()
        res = self.run_smoke(FAKE_FC_LANG_ZH_CN="0")
        self.assert_fail(res, 25)
        self.assertIn("no font declares lang=zh-cn", res.stdout)

    def test_desktop_no_hicolor(self):
        # 缺 hicolor 时 ukui 自己命名的图标还在，第三方 .desktop 全空白
        self.tools()
        self.write_desktop_assets(hicolor=False)
        res = self.run_smoke()
        self.assert_fail(res, 25)
        self.assertIn("hicolor fallback theme missing", res.stdout)

    def test_wifi_fw_flat_missing(self):
        # 新布局在、扁平名不在：内核逐文件报 error -2，网卡枚举正常但用不了
        self.tools()
        self.write_wifi_firmware(flat=False)
        res = self.run_smoke()
        self.assert_fail(res, 26)
        self.assertIn("iwlwifi-gl-c0-fm-c0-83.ucode", res.stdout)

    def test_wifi_fw_flat_layout(self):
        # 基底回到扁平布局时判据同样成立，不能把正常镜像判负
        self.tools()
        self.write_wifi_firmware(legacy=True)
        res = self.run_smoke()
        self.assertIn("iwlwifi flat files: 1", res.stdout)

    def test_wifi_fw_no_flat_list(self):
        # 安装期 %posttrans 没跑过（0.0.4 首装的实测形态）：入口是空的，清单
        # 也不存在。判负必须落在「清单缺失」这一句上，而不是逐条列 143 个
        # 未补入口的文件名——后者把判据与产物混在一起，现场无从定位。
        self.tools()
        self.write_wifi_firmware(flat=False)
        (self.sysroot / "usr" / "share" / "airymaxos" / "firmware"
         / "firmware-flat.list").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 26)
        self.assertIn("fail=no-list", res.stdout)

    def test_obs_bench_absent(self):
        # 观测工具没装进镜像：现场演示与故障定位都无从下手
        self.tools(omit=("airy-bench",))
        res = self.run_smoke()
        self.assert_fail(res, 16)
        self.assertIn("airy-bench not installed", res.stdout)

    def test_obs_demo_absent(self):
        # 渲染层缺失时 bench 与 observe 仍可用，但演示入口不可用
        self.tools(omit=("airy-demo",))
        res = self.run_smoke()
        self.assert_fail(res, 16)
        self.assertIn("airy-demo not installed", res.stdout)

    def test_obs_asset_absent(self):
        # 工具在、资产不在：observe 的静态自检必须给出 partial 而不是静默通过
        self.tools()
        (self.sysroot / "usr" / "lib" / "airymaxos" / "desktop" /
         "airy_bench.py").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 16)
        self.assertIn("status=partial", res.stdout)

    def test_field_tool_absent(self):
        # 现场排障入口没进镜像：首启网络异常时只能靠猜（0.0.4 台账 P-01）
        self.tools()
        (self.sysroot / "usr" / "bin" / "lsusb").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 27)
        self.assertIn("not in image: lsusb", res.stdout)

    def test_disk_layout_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 17 - T17 system disk layout", res.stdout)
        self.assertIn("/dev/sda1=part /dev/sda2=part partitions=2",
                      res.stdout)

    def test_data_unmounted(self):
        # 安装期没建数据分区：数据落在系统分区里，扩容只能整盘重建
        self.tools()
        self.write_mounts("/|/dev/sda1\n")
        res = self.run_smoke()
        self.assert_fail(res, 17)
        self.assertIn("/data not mounted", res.stdout)

    def test_data_on_root_partition(self):
        self.tools()
        self.write_mounts("/|/dev/sda1\n/data|/dev/sda1\n")
        res = self.run_smoke()
        self.assert_fail(res, 17)
        self.assertIn("/ and /data share /dev/sda1", res.stdout)

    def test_data_not_partition(self):
        # 数据落在 LVM/btrfs 子卷上：与系统共享同一块分区，判据要求 part
        self.tools()
        self.write_mounts("/|/dev/sda1\n"
                          "/data|/dev/mapper/airy-data\n")
        self.write_blocks(BLOCKS + "/dev/mapper/airy-data|lvm|"
                          "267000000000|0|||\n")
        res = self.run_smoke()
        self.assert_fail(res, 17)
        self.assertIn("TYPE /dev/mapper/airy-data: lvm", res.stdout)

    def test_findmnt_absent(self):
        self.tools(omit=("findmnt",))
        res = self.run_smoke()
        self.assert_fail(res, 17)
        self.assertIn("findmnt not installed", res.stdout)

    def test_lsblk_absent(self):
        self.tools(omit=("lsblk",))
        res = self.run_smoke()
        self.assert_fail(res, 17)
        self.assertIn("lsblk not installed", res.stdout)

    def test_net_front_ok(self):
        # 沙箱默认即闭包齐备的形态：三个控制中心模块与 kylin-nm 同时在位
        self.tools()
        res = self.run_smoke()
        self.assertTrue(self.tap(res, 28).startswith("ok"), res.stdout)
        self.assertIn("net front: kylin-nm + 3 ukcc modules", res.stdout)

    def test_net_front_no_kylin(self):
        # 面板按名等待 kylin-nm：面板自身正常、网络也通，但图标整块消失
        self.tools()
        self.write_net_front(kylin=False)
        res = self.run_smoke()
        self.assert_fail(res, 28)
        self.assertIn("not in image: kylin-nm", res.stdout)

    def test_net_front_no_module(self):
        # 包在、模块被拆掉：控制中心点「网络」即报模块加载失败
        self.tools()
        self.write_net_front(modules=("libnetconnect.so", "libwlanconnect.so"))
        res = self.run_smoke()
        self.assert_fail(res, 28)
        self.assertIn("libmobilehotspot.so", res.stdout)

    def test_touchpad_bound(self):
        # ACPI 有节点、输入子系统也枚举出来：I2C-HID 链路完整
        self.tools()
        self.write_acpi_touchpad()
        self.write_input_devices()
        res = self.run_smoke()
        self.assertTrue(self.tap(res, 29).startswith("ok"), res.stdout)
        self.assertIn("touchpad: input device present", res.stdout)

    def test_touchpad_synaptics_fails(self):
        # 内核绑定齐全、X 却被遗留驱动接管：I2C-HID 板拿不到压力，点击与
        # 手势整体失效。只看 /proc 的旧判据在这里会误判为通过（285H 实态）。
        self.tools()
        self.write_acpi_touchpad()
        self.write_input_devices()
        self.write_xorg_log("synaptics")
        res = self.run_smoke()
        self.assert_fail(res, 29)
        self.assertIn("X 驱动为 synaptics", res.stdout)

    def test_touchpad_libinput_passes(self):
        self.tools()
        self.write_acpi_touchpad()
        self.write_input_devices()
        self.write_xorg_log("libinput")
        res = self.run_smoke()
        self.assertTrue(self.tap(res, 29).startswith("ok"), res.stdout)
        self.assertIn("X 驱动 libinput", res.stdout)

    def test_touchpad_tpd0(self):
        # 另一族固件的命名（PNP0C50 挂 TPD0）：后缀不同但同属内建触控板，
        # 只认 TPAD 一种就会把这类机型误判成「无硬件」
        self.tools()
        self.write_acpi_touchpad(node="PNP0C50:00", path=TPD0_PATH)
        self.write_input_devices()
        res = self.run_smoke()
        self.assertTrue(self.tap(res, 29).startswith("ok"), res.stdout)
        self.assertIn("touchpad: input device present", res.stdout)

    def test_touchpad_unbound(self):
        # LPSS 缺 PCI ID 的实机形态：ACPI 节点在、输入子系统空白、
        # 内核日志无错误，只能靠两侧对照判定（0.0.4 台账 HW-02）
        self.tools()
        self.write_acpi_touchpad()
        self.write_input_devices(touchpad=False)
        res = self.run_smoke()
        self.assert_fail(res, 29)
        self.assertIn("ACPI 有触控板节点，输入子系统无设备", res.stdout)
        # 断点在第一段：没有任何 I2C 适配器，控制器没绑上
        self.assertIn("i2c 适配器 0 个，HID 设备 0 个", res.stdout)

    def test_touchpad_no_hid_client(self):
        # 断点在第二段：控制器绑上了，但 i2c-hid 没给触控板建客户端。
        # 与上一条的区别决定修法，输出必须能把两者分开。
        self.tools()
        self.write_acpi_touchpad()
        self.write_input_devices(touchpad=False)
        (self.sysroot / "sys" / "bus" / "i2c" / "devices" / "i2c-0").mkdir(
            parents=True
        )
        res = self.run_smoke()
        self.assert_fail(res, 29)
        self.assertIn("i2c 适配器 1 个，HID 设备 0 个", res.stdout)

    def test_touchpad_absent_hw(self):
        # 无内建触控板的机型按能力不适用通过，不记为掩盖
        self.tools()
        self.write_input_devices(touchpad=False)
        res = self.run_smoke()
        self.assertTrue(self.tap(res, 29).startswith("ok"), res.stdout)
        self.assertIn("no i2c-hid touchpad in ACPI", res.stdout)

    def test_tray_ok(self):
        # 三件齐备：网络、电量、音量三个托盘进程都在 autostart 里
        self.tools()
        res = self.run_smoke()
        self.assertTrue(self.tap(res, 30).startswith("ok"), res.stdout)
        self.assertIn("tray: nm, power, volume entry points present",
                      res.stdout)

    def test_tray_no_unit(self):
        # 包在、autostart 条目缺：进程不自启，图标消失且无日志可查，
        # 只能靠「可执行 + 条目」双件判定（0.0.4 台账 D-08 同族）
        self.tools()
        self.write_tray(units=("kylin-nm", "ukui-power-manager-tray"))
        res = self.run_smoke()
        self.assert_fail(res, 30)
        self.assertIn("ukui-volume-control-applet.desktop", res.stdout)

    def test_tray_no_bin(self):
        # 条目在、可执行缺：autostart 拉起即失败，面板无图标
        self.tools()
        self.write_tray(bins=("kylin-nm", "ukui-power-manager-tray"))
        res = self.run_smoke()
        self.assert_fail(res, 30)
        self.assertIn("ukui-volume-control-applet-qt", res.stdout)

    def test_build_id_ok(self):
        self.tools()
        res = self.run_smoke()
        self.assertIn("ok 18 - T18 build provenance", res.stdout)
        self.assertIn(f"build_id={BUILD_ID}", res.stdout)

    def test_build_id_unreadable(self):
        self.tools()
        (self.sysroot / "etc" / "airymaxos-build").unlink()
        res = self.run_smoke()
        self.assert_fail(res, 18)
        self.assertIn("/etc/airymaxos-build unreadable", res.stdout)

    def test_build_id_osrel_mismatch(self):
        # 两处标识由同一个宏写出，只改一处说明另一侧被单独替换或漏写。
        self.tools()
        self.write_osrel(OS_RELEASE.replace(
            f'BUILD_ID="{BUILD_ID}"', 'BUILD_ID="r99999999-gffffffffffff"'))
        res = self.run_smoke()
        self.assert_fail(res, 18)
        self.assertIn("os-release BUILD_ID: r99999999-gffffffffffff",
                      res.stdout)

    def test_build_id_charset(self):
        self.tools()
        self.write_build_id("r1/bad")
        res = self.run_smoke()
        self.assert_fail(res, 18)
        self.assertIn("(want [A-Za-z0-9._+-]+)", res.stdout)

    def test_build_id_empty(self):
        self.tools()
        self.write_build_id("")
        res = self.run_smoke()
        self.assert_fail(res, 18)
        self.assertIn("airymaxos-build: absent", res.stdout)

    def test_build_id_too_long(self):
        self.tools()
        self.write_build_id("a" * 65)
        res = self.run_smoke()
        self.assert_fail(res, 18)
        self.assertIn("build id length: 65 (want <=64)", res.stdout)

    def test_build_id_release_mismatch(self):
        # 清单记录的指纹与本机不同：装的是另一轮构建产出的镜像。
        self.tools()
        res = self.run_smoke(AIRYMAX_SMOKE_BUILD_ID="r99999999-gffffffffffff")
        self.assert_fail(res, 18)
        self.assertIn(f"release build id: {BUILD_ID}", res.stdout)


if __name__ == "__main__":
    unittest.main()
