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

    def test_reliability_reference_folder_and_resource_checklist_exist(self):
        folder = ROOT / "产品设计" / "实战落地参考"
        readme = folder / "README.md"
        checklist = folder / "AI量化交易平台_实战落地资源清单与验收标准.md"
        recommendation = folder / "AI量化交易平台_资源源选型建议_2026-04-07.md"
        data_hub = folder / "AI量化交易平台_数据中心与增量同步设计.md"
        one_pager = folder / "AI量化交易平台_资源部门单页说明.md"

        self.assertTrue(folder.exists())
        self.assertTrue(readme.exists())
        self.assertTrue(checklist.exists())
        self.assertTrue(recommendation.exists())
        self.assertTrue(data_hub.exists())
        self.assertTrue(one_pager.exists())

        text = checklist.read_text(encoding="utf-8")
        self.assertIn("必须提供的资源", text)
        self.assertIn("验收标准", text)
        self.assertIn("已提供资源登记", text)

        recommendation_text = recommendation.read_text(encoding="utf-8")
        self.assertIn("按预算给你的最优建议", recommendation_text)
        self.assertIn("Tushare Pro", recommendation_text)
        self.assertIn("SEC EDGAR", recommendation_text)
        self.assertIn("市场规则与制度资料", recommendation_text)
        self.assertIn("历史真值样本", recommendation_text)

        data_hub_text = data_hub.read_text(encoding="utf-8")
        self.assertIn("用户请求不直连上游数据源", data_hub_text)
        self.assertIn("平台统一拉取并保存", data_hub_text)
        self.assertIn("增量更新", data_hub_text)

        one_pager_text = one_pager.read_text(encoding="utf-8")
        self.assertIn("我们需要什么资源", one_pager_text)
        self.assertIn("这些资源怎么用", one_pager_text)
        self.assertIn("资源提供部门需要重点确认什么", one_pager_text)


if __name__ == "__main__":
    unittest.main()
