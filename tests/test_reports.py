from __future__ import annotations

import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class ReportDocumentTests(unittest.TestCase):
    def test_ai_quant_formal_retrospective_exists_and_has_core_sections(self) -> None:
        report_path = WORKSPACE_ROOT / "产品设计" / "AI量化交易平台_正式复盘报告.md"

        self.assertTrue(report_path.exists(), "正式复盘报告文件不存在")

        content = report_path.read_text(encoding="utf-8")
        self.assertIn("# AI量化交易平台阶段性复盘报告", content)
        self.assertIn("## 一、项目阶段性完成情况", content)
        self.assertIn("## 二、本次会议带来的主要收获与反思", content)
        self.assertIn("## 四、下一阶段优化方向", content)
        self.assertIn("## 五、明日工作计划", content)
