#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_ks_embed.py — 共享安装脚本展开与标记审计的回归测试
#
# 展开产物要能直接交给 anaconda，审计要能拦住「%pre 生成存储片段却手抄
# 第二份选盘规则」的回退形态（D-33 的成因）。两条路径共用同一份段解析，
# 用例逐一破坏前提：标记位置、共享脚本本身，以及生成 include 的 %pre。
# 选盘器依赖 install-lib.sh，同一段里 lib 必须先于 disk-select.sh 展开，
# 顺序错误同样要被审计拦下。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ks_embed

TOOL = Path(ks_embed.__file__)
SHARED = "#!/usr/bin/env bash\necho airy\n"
CORE = "#!/usr/bin/env bash\necho core\n"
CORE_MARK = "# %airy-embed: install-lib.sh\n"
MARK = "# %airy-embed: disk-select.sh\n"
PRE = """\
%pre --erroronfail --log=/tmp/pre.log
set -eu
# %airy-embed: install-lib.sh
# %airy-embed: disk-select.sh
airy_pre /tmp/disk.ks /tmp/disk.json
%end
%include /tmp/disk.ks
reboot
"""


class EmbedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # base 模拟 distro/kickstart：ALT_DIR 解析的是它的兄弟目录，因此这里
        # 必须先有一层父目录，否则「同目录兜底」与「兄弟目录」无从区分。
        self.base = Path(self._tmp.name) / "kickstart"
        self.base.mkdir()
        self.write("disk-select.sh", SHARED)
        self.write("install-lib.sh", CORE)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        (self.base / name).write_text(text, encoding="utf-8")

    def full(self):
        return PRE.replace(CORE_MARK, CORE).replace(MARK, SHARED)

    def test_expand_inserts_body(self):
        out = ks_embed.expand(PRE, self.base)
        self.assertIn(SHARED, out)
        self.assertIn(CORE, out)
        self.assertNotIn(ks_embed.MARK, out)
        self.assertIn("%include /tmp/disk.ks\nreboot\n", out)

    def test_expand_keeps_rest(self):
        self.assertEqual(ks_embed.expand(PRE, self.base), self.full())

    def test_expand_adds_newline(self):
        self.write("disk-select.sh", "echo airy")
        out = ks_embed.expand(PRE, self.base)
        self.assertIn("echo airy\nairy_pre", out)

    def test_marker_outside_section(self):
        with self.assertRaises(ks_embed.EmbedError) as ctx:
            ks_embed.expand(MARK + PRE, self.base)
        self.assertEqual(ctx.exception.line, 1)

    def test_unknown_script(self):
        text = PRE.replace("disk-select.sh", "bogus.sh")
        with self.assertRaises(ks_embed.EmbedError):
            ks_embed.expand(text, self.base)

    def test_missing_script(self):
        (self.base / "disk-select.sh").unlink()
        with self.assertRaises(ks_embed.EmbedError):
            ks_embed.expand(PRE, self.base)

    def test_nested_marker(self):
        self.write("disk-select.sh", MARK + SHARED)
        with self.assertRaises(ks_embed.EmbedError):
            ks_embed.expand(PRE, self.base)

    def test_audit_clean(self):
        self.assertEqual(ks_embed.audit(PRE), [])

    def test_audit_marker_outside(self):
        self.assertEqual(ks_embed.audit(MARK + PRE),
                         [(1, "嵌入标记不在脚本段内")])

    def test_audit_unmarked_include(self):
        text = PRE.replace(MARK, "set -eu\n")
        issues = ks_embed.audit(text)
        self.assertEqual([line for line, _ in issues], [1])
        self.assertIn("未嵌入选盘器", issues[0][1])

    def test_audit_include_not_generated(self):
        text = PRE.replace(MARK, "set -eu\n").replace(
            "%include /tmp/disk.ks\n", "")
        self.assertEqual(ks_embed.audit(text), [])

    def test_audit_requires_lib_first(self):
        text = PRE.replace(CORE_MARK, "")
        issues = ks_embed.audit(text)
        self.assertEqual(len(issues), 1)
        line, msg = issues[0]
        self.assertEqual(line, 3)
        self.assertIn("%pre", msg)
        self.assertIn("install-lib.sh", msg)

    def test_audit_rtc_after_lib(self):
        # 依赖 install-lib 的不止选盘器：RTC 写入同样只调 airy_out，因此
        # 顺序规则按「依赖 lib 的脚本」统一执行，不按脚本名逐个开洞。
        post = ("%post\nset -eu\n# %airy-embed: install-lib.sh\n"
                "# %airy-embed: rtc-sync.sh\nairy_rtc_sync\n%end\n")
        self.assertEqual(ks_embed.audit(post), [])
        issues = ks_embed.audit(post.replace(CORE_MARK, ""))
        self.assertEqual(len(issues), 1)
        self.assertIn("rtc-sync.sh", issues[0][1])
        self.assertIn("install-lib.sh", issues[0][1])

    def test_expand_rtc(self):
        self.write("rtc-sync.sh", SHARED)
        out = ks_embed.expand(
            "%post\n# %airy-embed: rtc-sync.sh\nairy_rtc_sync\n%end\n",
            self.base)
        self.assertIn(SHARED, out)
        self.assertIn("airy_rtc_sync\n", out)

    # 数据文件不执行：裸表正文落进脚本段会被 sh 当命令，展开必须折成
    # here-doc。判据有两条——产物能被 sh 解析，且正文逐字落进文件。
    def test_expand_data_heredoc(self):
        table = "# 注释行\niwlwifi-bz-* 本版不支持\n"
        self.write("fw-exempt.txt", table)
        out = ks_embed.expand(
            "%pre\n# %airy-embed: fw-exempt.txt\n%end\n", self.base)
        self.assertIn('airy_fw_exempt="${TMPDIR:-/tmp}/airymax-fw-exempt.txt"',
                      out)
        self.assertIn("<<'AIRYMAX_DATA_EOF'\n" + table, out)
        res = subprocess.run(["sh", "-n"], input=out, capture_output=True,
                             text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_expand_data_alt_dir(self):
        # 台账与 fw-flat.sh 同在 distro/firmware，不在 kickstart 目录里：
        # 嵌入器要按 ALT_DIR 找到它，而不是要求复制一份到 kickstart。
        (self.base.parent / "firmware").mkdir()
        (self.base.parent / "firmware" / "fw-exempt.txt").write_text(
            "iwlwifi-ma-* 本版不支持\n", encoding="utf-8")
        out = ks_embed.expand(
            "%pre\n# %airy-embed: fw-exempt.txt\n%end\n", self.base)
        self.assertIn("iwlwifi-ma-* 本版不支持\n", out)

    def test_expand_data_rejects_terminator(self):
        self.write("fw-exempt.txt", "airymax_data_eof\nAIRYMAX_DATA_EOF\n")
        with self.assertRaises(ks_embed.EmbedError):
            ks_embed.expand(
                "%pre\n# %airy-embed: fw-exempt.txt\n%end\n", self.base)

    def test_cli_ok(self):
        src = self.base / "in.ks"
        dst = self.base / "out" / "ks.cfg"
        src.write_text(PRE, encoding="utf-8")
        res = subprocess.run([sys.executable, str(TOOL), str(src), str(dst)],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(SHARED, dst.read_text(encoding="utf-8"))

    def test_cli_include_dir(self):
        src = self.base / "src" / "in.ks"
        dst = self.base / "out" / "ks.cfg"
        src.parent.mkdir()
        src.write_text(PRE, encoding="utf-8")
        res = subprocess.run(
            [sys.executable, str(TOOL), "--include-dir", str(self.base),
             str(src), str(dst)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(SHARED, dst.read_text(encoding="utf-8"))

    def test_cli_reject(self):
        src = self.base / "in.ks"
        dst = self.base / "out" / "ks.cfg"
        src.write_text(MARK + PRE, encoding="utf-8")
        res = subprocess.run([sys.executable, str(TOOL), str(src), str(dst)],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 5)
        self.assertIn("ks_embed:", res.stderr)
        self.assertFalse(dst.exists())


if __name__ == "__main__":
    sys.exit(unittest.main())
