from __future__ import annotations

import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class ModuleImplementationDocumentTests(unittest.TestCase):
    def test_ocr_design_doc_exists(self) -> None:
        path = WORKSPACE_ROOT / "产品设计" / "AI量化交易平台_模块5_OCR识别链路设计.md"
        self.assertTrue(path.exists(), "模块 5 OCR 识别链路设计稿不存在")

        content = path.read_text(encoding="utf-8")
        self.assertIn("AI量化交易平台模块 5：OCR 识别链路设计稿", content)
        self.assertIn("raw rows -> fills -> trade records", content)
        self.assertIn("POST /api/v1/trade-images/uploads", content)

    def test_module_implementation_summary_exists(self) -> None:
        path = WORKSPACE_ROOT / "产品设计" / "AI量化交易平台_模块实施汇总稿.md"
        self.assertTrue(path.exists(), "模块实施汇总稿不存在")

        content = path.read_text(encoding="utf-8")
        self.assertIn("AI量化交易平台模块实施汇总稿", content)
        self.assertIn("模块 1：用户工作台与项目组织", content)
        self.assertIn("模块 7：数据库与数据资产", content)
        self.assertIn("trade-imports", content)
        self.assertIn("knowledge_snapshot_ref", content)


if __name__ == "__main__":
    unittest.main()
