#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# ===========================================================================
# test_head_lint.py — head_lint 规则回归测试
#
# 用例直接调用 head_lint.judge，把「文件内容」当参数传入而不是落盘：横幅
# 校验的全部输入就是前 DEPTH 行文本加一个期望版本，落盘只会让每个用例多出
# 临时目录与清理，不增加判据。用标准库 unittest 编写，可被 pytest 直接收集。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
# ===========================================================================

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import head_lint

GOOD = """\
#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# tool in one line
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.4
"""


def codes(text: str, want: str = "0.0.4") -> list[str]:
    return [i.code for i in head_lint.judge(want, text.splitlines())]


class HeadLintTest(unittest.TestCase):
    def test_good_banner_passes(self) -> None:
        self.assertEqual(codes(GOOD), [])

    def test_plain_file_without_banner_passes(self) -> None:
        self.assertEqual(codes("# just a comment\nx = 1\n"), [])

    def test_author_without_version_is_reported(self) -> None:
        text = "# Author: Liren Wang <wangliren@spharx.cn>\n"
        self.assertEqual(codes(text), ["H001"])

    def test_stale_version_is_reported(self) -> None:
        text = GOOD.replace("0.0.4", "0.0.3")
        self.assertEqual(codes(text), ["H002"])

    def test_version_beyond_banner_depth_is_ignored(self) -> None:
        text = GOOD + ("# filler\n" * 90) + "# Version: 0.0.1\n"
        self.assertEqual(codes(text), [])


if __name__ == "__main__":
    unittest.main()
