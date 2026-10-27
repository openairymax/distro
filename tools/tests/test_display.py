#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_display.py — 分辨率策略（display_mode.sh）行为回归
#
# 策略是会话显示的唯一事实来源，这里用合成拓扑把它的三条规则钉死：
# 首选模式在上限内即采用、否则取常用分辨率阶梯中该输出确实广播的最大项、
# 阶梯全不匹配时回退首选。--plan 从 stdin 读拓扑，因此策略判定本身不需要
# X server；--check 与默认入口再经伪 xrandr 验证退出码与调用面。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.3
# ===========================================================================

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import fakes

BASE = Path(__file__).resolve().parents[2]
POLICY = BASE / "desktop" / "display_mode.sh"
HOOK = BASE / "desktop" / "xinitrc.d" / "60-airymax-display.sh"
SH = shutil.which("sh") or "/bin/sh"

SCREEN = ("Screen 0: minimum 8 x 8, current {0} x {1},"
          " maximum 32767 x 32767")

# 有状态伪 xrandr：--output 会把拓扑回改，收敛因此是被真实驱动的行为，
# 而不是脚本自说自话。FAKE_XRANDR_COLD 指向计数文件，前 FAKE_XRANDR_MIN
# 次 --query 只回 Screen 行，复刻会话早期 connected 拓扑尚未建立的时序。
XRANDR_STATEFUL = """\
#!/bin/sh
case "$1" in
--query)
    [ -n "${FAKE_XRANDR_TOPO:-}" ] || exit 1
    [ -r "${FAKE_XRANDR_TOPO}" ] || exit 1
    cold=${FAKE_XRANDR_COLD:-}
    if [ -n "$cold" ]; then
        n=$(cat "$cold" 2>/dev/null || printf '0')
        if [ "$n" -lt "${FAKE_XRANDR_MIN:-1}" ]; then
            printf '%s\\n' "$((n + 1))" > "$cold"
            head -n 1 "$FAKE_XRANDR_TOPO"
            exit 0
        fi
    fi
    cat "${FAKE_XRANDR_TOPO}"
    ;;
--output)
    [ -n "${FAKE_XRANDR_LOG:-}" ] || exit 1
    printf '%s\\n' "$*" >> "${FAKE_XRANDR_LOG}"
    out=$2; mode=""
    shift 2
    while [ $# -gt 0 ]; do
        case "$1" in
        --mode) shift; mode=$1 ;;
        esac
        shift
    done
    [ -n "$mode" ] && [ -r "${FAKE_XRANDR_TOPO:-}" ] || exit 0
    awk -v out="$out" -v mode="$mode" '
    /^[^ \\t]/ {
        inblk = ($1 == out)
        if (inblk)
            for (i = 2; i <= NF; i++)
                if ($i ~ /^[0-9]+x[0-9]+[a-zA-Z]*\\+/) {
                    $i = mode "+0+0"
                    break
                }
        print
        next
    }
    inblk && $1 ~ /^[0-9]+x[0-9]+[a-zA-Z]*$/ {
        gsub(/\\*/, "")
        if ($1 == mode)
            $0 = $0 "*"
    }
    { print }
    ' "$FAKE_XRANDR_TOPO" > "$FAKE_XRANDR_TOPO.new" &&
        mv "$FAKE_XRANDR_TOPO.new" "$FAKE_XRANDR_TOPO"
    ;;
*) exit 1 ;;
esac
"""


def topo(*lines):
    return "".join(f"{line}\n" for line in lines)


def screen(width=1920, height=1080):
    return SCREEN.format(width, height)


class DisplayModeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fakes.link_tools(self.bin)
        fakes.write(self.bin, "xrandr", XRANDR_STATEFUL)
        self.bare = self.root / "bare"
        self.bare.mkdir()
        fakes.link_tools(self.bare)
        self.topo = self.root / "xrandr.topo"
        self.log = self.root / "xrandr.log"
        self.cold = self.root / "xrandr.cold"

    def tearDown(self):
        self._tmp.cleanup()

    def run_policy(self, *args, stdin=None, path=None, env=None):
        base = {
            "PATH": str(path or self.bin),
            "HOME": str(self.root),
            "FAKE_XRANDR_TOPO": str(self.topo),
            "FAKE_XRANDR_LOG": str(self.log),
        }
        base.update(env or {})
        return subprocess.run([SH, str(POLICY), *args], input=stdin,
                              env=base, text=True, capture_output=True)

    def plan(self, body):
        self.topo.write_text(body, encoding="utf-8")
        res = self.run_policy("--plan", stdin=body)
        self.assertEqual(res.returncode, 0, res.stderr)
        return [line.split() for line in res.stdout.splitlines() if line]

    def calls(self):
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_syntax_is_posix(self):
        for path in (POLICY, HOOK):
            with self.subTest(path=path.name):
                res = subprocess.run([SH, "-n", str(path)], text=True,
                                     capture_output=True)
                self.assertEqual(res.returncode, 0, res.stderr)

    def test_4k_falls_back_to_1080p(self):
        rows = self.plan(topo(
            screen(3840, 2160),
            "eDP-1 connected primary 3840x2160+0+0 (normal) 344mm x 194mm",
            "   3840x2160     60.00*+  48.00",
            "   2560x1440     59.95",
            "   1920x1080     60.00",
            "   1280x720      60.00"))
        self.assertEqual(rows, [["eDP-1", "3840x2160", "1920x1080"]])

    def test_native_within_cap_kept(self):
        rows = self.plan(topo(
            screen(),
            "eDP-1 connected primary 1920x1080+0+0 (normal) 344mm x 194mm",
            "   1920x1080     60.00*+",
            "   1280x720      60.00"))
        self.assertEqual(rows, [["eDP-1", "1920x1080", "1920x1080"]])

    def test_small_panel_kept(self):
        rows = self.plan(topo(
            screen(1366, 768),
            "LVDS-1 connected 1366x768+0+0 (normal) 0mm x 0mm",
            "   1366x768      59.79*+",
            "   1024x768      60.00"))
        self.assertEqual(rows, [["LVDS-1", "1366x768", "1366x768"]])

    def test_cap_is_inclusive(self):
        rows = self.plan(topo(
            screen(1920, 1200),
            "DP-1 connected 1920x1200+0+0 (normal) 0mm x 0mm",
            "   1920x1200     59.95*+",
            "   1920x1080     60.00"))
        self.assertEqual(rows, [["DP-1", "1920x1200", "1920x1200"]])

    def test_width_over_cap_uses_ladder(self):
        rows = self.plan(topo(
            screen(2560, 1600),
            "DP-2 connected 2560x1600+0+0 (normal) 0mm x 0mm",
            "   2560x1600     59.97*+",
            "   1920x1080     60.00",
            "   1600x900      60.00"))
        self.assertEqual(rows, [["DP-2", "2560x1600", "1920x1080"]])

    def test_ladder_absent_keeps_preferred(self):
        rows = self.plan(topo(
            screen(2880, 1800),
            "DP-2 connected 2880x1800+0+0 (normal) 0mm x 0mm",
            "   2880x1800     59.99*+",
            "   1680x1050     60.00",
            "   1280x800      60.00"))
        self.assertEqual(rows, [["DP-2", "2880x1800", "2880x1800"]])

    def test_interlaced_counts_as_height(self):
        rows = self.plan(topo(
            screen(1920, 1080),
            "HDMI-1 connected 1920x1080+0+0 (normal) 0mm x 0mm",
            "   1920x1080i    60.00*+",
            "   1280x720      60.00"))
        self.assertEqual(rows, [["HDMI-1", "1920x1080i", "1920x1080i"]])

    def test_outputs_decided_independently(self):
        rows = self.plan(topo(
            screen(3840, 1080),
            "HDMI-1 connected primary 1920x1080+0+0 (normal) 0mm x 0mm",
            "   1920x1080     60.00*+",
            "   1280x720      60.00",
            "VGA-1 connected 1366x768+1920+0 (normal) 0mm x 0mm",
            "   1920x1080     60.00 +",
            "   1366x768      59.79*",
            "DP-1 disconnected (normal) 0mm x 0mm",
            "   3840x2160     60.00 +"))
        self.assertEqual(rows, [["HDMI-1", "1920x1080", "1920x1080"],
                                ["VGA-1", "1366x768", "1920x1080"]])

    def test_no_connected_output(self):
        self.assertEqual(self.plan(topo(
            screen(640, 480),
            "DP-1 disconnected (normal) 0mm x 0mm")), [])

    def test_check_passes_on_policy(self):
        self.topo.write_text(topo(
            screen(),
            "eDP-1 connected primary 1920x1080+0+0 (normal) 0mm x 0mm",
            "   1920x1080     60.00*+"), encoding="utf-8")
        res = self.run_policy("--check")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(res.stdout, "")

    def test_check_reports_mismatch(self):
        self.topo.write_text(topo(
            screen(3840, 2160),
            "eDP-1 connected primary 3840x2160+0+0 (normal) 0mm x 0mm",
            "   3840x2160     60.00*+",
            "   1920x1080     60.00"), encoding="utf-8")
        res = self.run_policy("--check")
        self.assertEqual(res.returncode, 1)
        self.assertIn("eDP-1:3840x2160->1920x1080", res.stderr)

    def test_check_rejects_empty_topology(self):
        self.topo.write_text(topo(
            screen(640, 480),
            "DP-1 disconnected (normal) 0mm x 0mm"), encoding="utf-8")
        res = self.run_policy("--check")
        self.assertEqual(res.returncode, 1)
        self.assertIn("无 connected 输出", res.stderr)

    def test_check_requires_xrandr(self):
        res = self.run_policy("--check", path=self.bare)
        self.assertEqual(res.returncode, 1)
        self.assertIn("缺少 xrandr", res.stderr)

    def test_apply_only_touches_mismatch(self):
        self.topo.write_text(topo(
            screen(3840, 1080),
            "HDMI-1 connected primary 1920x1080+0+0 (normal) 0mm x 0mm",
            "   1920x1080     60.00*+",
            "VGA-1 connected 1366x768+1920+0 (normal) 0mm x 0mm",
            "   1920x1080     60.00 +",
            "   1366x768      59.79*"), encoding="utf-8")
        res = self.run_policy()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.calls(), ["--output VGA-1 --mode 1920x1080"])

    def test_apply_is_idempotent(self):
        self.topo.write_text(topo(
            screen(),
            "eDP-1 connected primary 1920x1080+0+0 (normal) 0mm x 0mm",
            "   1920x1080     60.00*+"), encoding="utf-8")
        res = self.run_policy()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.calls(), [])

    def test_hook_is_inert_without_policy(self):
        # 会话钩子被 sh source；策略脚本不在 %{_prefix}/lib 时必须静默返回，
        # 且不得污染调用方 shell 的 set -e 语义。
        res = subprocess.run([SH, "-ec", f". {HOOK}; echo sourced"],
                             text=True, capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "sourced")

    def test_settle_waits_for_connected_output(self):
        # 会话早期 xrandr 只有 Screen 行，单次 apply 会静默落空；--settle 必须
        # 在拓扑就绪后纠正一次并收敛，而不是把落空当成功。
        self.topo.write_text(topo(
            screen(5120, 2160),
            "Virtual-1 connected primary 5120x2160+0+0 (normal) 0mm x 0mm",
            "   5120x2160     60.00*+",
            "   1920x1080     60.00",
            "   1280x800      60.00"), encoding="utf-8")
        env = {"FAKE_XRANDR_COLD": str(self.cold), "FAKE_XRANDR_MIN": "1"}
        res = self.run_policy("--settle", "5", env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.calls(),
                         ["--output Virtual-1 --mode 1920x1080"])
        res = self.run_policy("--check", env=env)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_settle_budget_exhausted(self):
        # 写入被接受但拓扑不变（驱动拒绝或异步失败）：预算耗尽必须失败，
        # 并把最后一次偏差交给调用方，不能无限重试。
        fakes.write(self.bin, "xrandr", fakes.XRANDR)
        self.topo.write_text(topo(
            screen(3840, 2160),
            "eDP-1 connected primary 3840x2160+0+0 (normal) 0mm x 0mm",
            "   3840x2160     60.00*+",
            "   1920x1080     60.00"), encoding="utf-8")
        res = self.run_policy("--settle", "1")
        self.assertEqual(res.returncode, 1)
        self.assertIn("收敛失败", res.stderr)
        self.assertIn("eDP-1:3840x2160->1920x1080", res.stderr)

    def test_convergence_entries_bounded(self):
        # 两个收敛入口都必须带预算：无预算的入口在拓扑缺席时会挂死会话。
        self.assertIn("--settle 10", HOOK.read_text(encoding="utf-8"))
        auto = BASE / "desktop" / "autostart" / "airymax-display.desktop"
        self.assertIn("--settle 30", auto.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
