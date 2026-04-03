from pathlib import Path
import unittest


ROOT = Path("/workspace/ai-quant-platform")


class ProcessReferenceDocsTests(unittest.TestCase):
    def test_process_reference_folder_and_summary_exist(self):
        folder = ROOT / "产品设计" / "开发流程参考"
        readme = folder / "README.md"
        summary = folder / "AI量化交易平台_开发流程总结_2026-04-03.md"

        self.assertTrue(folder.exists())
        self.assertTrue(readme.exists())
        self.assertTrue(summary.exists())

        text = summary.read_text(encoding="utf-8")
        self.assertIn("标准开发顺序", text)
        self.assertIn("固定检查清单", text)
        self.assertIn("主接力文档", text)


if __name__ == "__main__":
    unittest.main()
