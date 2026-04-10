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
        self.assertIn("ClickHouse", text)
        self.assertIn("quant_ads / quant_dwd", text)
        self.assertIn("quant_ods", text)

        recommendation_text = recommendation.read_text(encoding="utf-8")
        self.assertIn("按预算给你的最优建议", recommendation_text)
        self.assertIn("Tushare Pro", recommendation_text)
        self.assertIn("SEC EDGAR", recommendation_text)
        self.assertIn("市场规则与制度资料", recommendation_text)
        self.assertIn("历史真值样本", recommendation_text)
        self.assertIn("默认优先读 `ADS / DWD`", recommendation_text)

        data_hub_text = data_hub.read_text(encoding="utf-8")
        self.assertIn("用户请求不直连上游数据源", data_hub_text)
        self.assertIn("平台统一拉取并保存", data_hub_text)
        self.assertIn("增量更新", data_hub_text)
        self.assertIn("优先读取内部数据仓库", data_hub_text)
        self.assertIn("用户侧默认优先读取 `ADS / DWD`", data_hub_text)
        self.assertIn("`ODS` 只保留给原始回查、补数、审计、问题排查和重新加工", data_hub_text)

        one_pager_text = one_pager.read_text(encoding="utf-8")
        self.assertIn("我们需要什么资源", one_pager_text)
        self.assertIn("这些资源怎么用", one_pager_text)
        self.assertIn("资源提供部门需要重点确认什么", one_pager_text)
        self.assertIn("平台默认优先读取 `ADS / DWD`", one_pager_text)

    def test_module_ai_design_folder_and_key_docs_exist(self):
        folder = ROOT / "产品设计" / "模块AI设计"
        readme = folder / "README.md"
        strategy_doc = folder / "策略工坊模块_AI设计.md"
        strategy_gap_doc = folder / "策略工坊模块_详细查缺补漏.md"
        replay_doc = folder / "交易复盘模块_AI设计.md"
        mentor_doc = folder / "金融导师模块_AI设计.md"
        assistant_doc = folder / "金融助手模块_AI设计.md"

        self.assertTrue(folder.exists())
        self.assertTrue(readme.exists())
        self.assertTrue(strategy_doc.exists())
        self.assertTrue(strategy_gap_doc.exists())
        self.assertTrue(replay_doc.exists())
        self.assertTrue(mentor_doc.exists())
        self.assertTrue(assistant_doc.exists())

        readme_text = readme.read_text(encoding="utf-8")
        self.assertIn("全平台哪些模块要接 AI", readme_text)
        self.assertIn("AI 负责理解、整理、生成候选结果", readme_text)
        self.assertIn("人工确认或拒答", readme_text)
        self.assertIn("策略工坊模块_详细查缺补漏", readme_text)

        strategy_text = strategy_doc.read_text(encoding="utf-8")
        self.assertIn("结构化真值层", strategy_text)
        self.assertIn("不能直接“自然语言 -> Python”", strategy_text)
        self.assertIn("混合周期边界必须由平台规则判断", strategy_text)

        strategy_gap_text = strategy_gap_doc.read_text(encoding="utf-8")
        self.assertIn("结构化理解确认卡", strategy_gap_text)
        self.assertIn("待补充问题 / 待确认项", strategy_gap_text)
        self.assertIn("不能直接“自然语言 -> Python”", strategy_gap_text)
        self.assertIn("可直接生成", strategy_gap_text)
        self.assertIn("拒绝输出", strategy_gap_text)

        replay_text = replay_doc.read_text(encoding="utf-8")
        self.assertIn("规则解析 + AI 混合解析 + 人工确认", replay_text)
        self.assertIn("真实成交记录必须经过结构化校验和人工确认", replay_text)

        mentor_text = mentor_doc.read_text(encoding="utf-8")
        self.assertIn("不能直接产出无证据的事实数据结论", mentor_text)

        assistant_text = assistant_doc.read_text(encoding="utf-8")
        self.assertIn("事实层必须来自平台数据中心", assistant_text)


if __name__ == "__main__":
    unittest.main()
