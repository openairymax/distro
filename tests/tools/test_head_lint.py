#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2025-2026 SPHARX Ltd.
# ===========================================================================
# test_head_lint.py — head_lint 规则回归测试
#
# 用例直接调用 head_lint.judge，把「文件内容」当参数传入而不是落盘：横幅
# 校验的全部输入就是前 DEPTH 行文本加一个期望版本，落盘只会让每个用例多出
# 临时目录与清理，不增加判据。用标准库 unittest 编写，可被 pytest 直接收集。
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.5
# ===========================================================================

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import head_lint

GOOD = """\
#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# tool in one line
#
# Author: Liren Wang <wangliren@spharx.cn>
# Version: 0.0.5
"""

# 期望版本取自夹具，而不是在这里另写一份字面量：夹具横幅会随发布版本一起
# 被抬，两份字面量必然分叉，而分叉后测试仍然自洽——它比的是自己那一份。
def banner_ver(text: str) -> str:
    return re.search(r"^# Version: (\S+)$", text, re.MULTILINE).group(1)


def codes(text: str, want: str | None = None) -> list[str]:
    return [i.code for i in head_lint.judge(want or banner_ver(GOOD),
                                            text.splitlines())]


class HeadLintTest(unittest.TestCase):
    def test_good_banner_passes(self) -> None:
        self.assertEqual(codes(GOOD), [])

    def test_plain_file_without_banner_passes(self) -> None:
        self.assertEqual(codes("# just a comment\nx = 1\n"), [])

    def test_author_without_version_is_reported(self) -> None:
        text = "# Author: Liren Wang <wangliren@spharx.cn>\n"
        self.assertEqual(codes(text), ["H001"])

    def test_stale_version_is_reported(self) -> None:
        text = GOOD.replace(f"# Version: {banner_ver(GOOD)}",
                            "# Version: 9.9.9")
        self.assertEqual(codes(text), ["H002"])

    def test_version_beyond_banner_depth_is_ignored(self) -> None:
        text = GOOD + ("# filler\n" * 90) + "# Version: 0.0.1\n"
        self.assertEqual(codes(text), [])


if __name__ == "__main__":
    unittest.main()
