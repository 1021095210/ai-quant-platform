from pathlib import Path
import unittest


ROOT = Path("/workspace/ai-quant-platform")


class ProductManagerDeliveryDocsTests(unittest.TestCase):
    def test_pm_delivery_folder_and_core_docs_exist(self):
        folder = ROOT / "产品设计" / "产品经理交付"
        archive = folder / "归档材料"
        replay = folder / "专项方案" / "交易复盘与优化"
        readme = folder / "README.md"
        prd = folder / "AI量化交易平台_PRD_v1.0.md"
        rules = folder / "AI量化交易平台_功能清单与业务规则.md"
        roadmap = folder / "AI量化交易平台_版本路线图与里程碑.md"
        pending = folder / "AI量化交易平台_待确认事项清单.md"
        module_matrix = folder / "AI量化交易平台_模块级产品与研发总表.md"
        platform_schedule = folder / "AI量化交易平台_全平台开发排期与验收清单.md"
        intro = archive / "AI量化交易平台_产品立项简介.md"
        personas = archive / "AI量化交易平台_用户画像.md"
        analytics = archive / "AI量化交易平台_埋点方案_v1.0.md"
        business = archive / "AI量化交易平台_商业价值与资源申请.md"
        communication = archive / "AI量化交易平台_沟通口径_老板设计开发测试.md"
        replay_optimization = replay / "AI量化交易平台_交易复盘与优化详细方案.md"
        replay_mock = replay / "AI量化交易平台_交易复盘与优化输出原型.html"
        replay_engineering = replay / "AI量化交易平台_交易复盘与优化研发拆解.md"
        replay_schedule = replay / "AI量化交易平台_交易复盘与优化开发排期与验收清单.md"
        replay_algorithm = replay / "AI量化交易平台_交易复盘与优化算法与数据口径.md"

        for path in (
            folder,
            archive,
            replay,
            readme,
            intro,
            prd,
            personas,
            rules,
            analytics,
            roadmap,
            business,
            pending,
            communication,
            replay_optimization,
            replay_mock,
            replay_engineering,
            replay_schedule,
            replay_algorithm,
            module_matrix,
            platform_schedule,
        ):
            self.assertTrue(path.exists(), f"missing: {path}")

    def test_pm_delivery_docs_contain_company_facing_sections(self):
        folder = ROOT / "产品设计" / "产品经理交付"
        archive = folder / "归档材料"
        replay = folder / "专项方案" / "交易复盘与优化"

        intro_text = (archive / "AI量化交易平台_产品立项简介.md").read_text(encoding="utf-8")
        self.assertIn("产品一句话", intro_text)
        self.assertIn("目标用户", intro_text)
        self.assertIn("适合给公司看的结论", intro_text)

        prd_text = (folder / "AI量化交易平台_PRD_v1.0.md").read_text(encoding="utf-8")
        self.assertIn("核心流程", prd_text)
        self.assertIn("功能优先级", prd_text)
        self.assertIn("关键依赖", prd_text)
        self.assertIn("当前阶段成功指标", prd_text)
        self.assertIn("用户 7 日留存", prd_text)
        self.assertIn("第一差异点", prd_text)

        personas_text = (archive / "AI量化交易平台_用户画像.md").read_text(encoding="utf-8")
        self.assertIn("新手股民", personas_text)
        self.assertIn("有交易经验但不会编程的个人交易者", personas_text)
        self.assertIn("有一定研究能力的高级用户", personas_text)

        rules_text = (folder / "AI量化交易平台_功能清单与业务规则.md").read_text(encoding="utf-8")
        self.assertIn("当前主路径", rules_text)
        self.assertIn("金融导师", rules_text)
        self.assertIn("成交复盘是平台核心差异化功能", rules_text)

        analytics_text = (archive / "AI量化交易平台_埋点方案_v1.0.md").read_text(encoding="utf-8")
        self.assertIn("当前主指标", analytics_text)
        self.assertIn("用户 7 日留存", analytics_text)
        self.assertIn("核心埋点事件", analytics_text)

        roadmap_text = (folder / "AI量化交易平台_版本路线图与里程碑.md").read_text(encoding="utf-8")
        self.assertIn("当前阶段", roadmap_text)
        self.assertIn("下一阶段", roadmap_text)
        self.assertIn("里程碑", roadmap_text)

        business_text = (archive / "AI量化交易平台_商业价值与资源申请.md").read_text(encoding="utf-8")
        self.assertIn("为什么公司值得继续支持这个项目", business_text)
        self.assertIn("建议公司提供的资源", business_text)

        pending_text = (folder / "AI量化交易平台_待确认事项清单.md").read_text(encoding="utf-8")
        self.assertIn("产品定位待确认", pending_text)
        self.assertIn("建议你优先向公司确认的三件事", pending_text)

        communication_text = (archive / "AI量化交易平台_沟通口径_老板设计开发测试.md").read_text(encoding="utf-8")
        self.assertIn("和老板讲什么", communication_text)
        self.assertIn("和设计讲什么", communication_text)
        self.assertIn("和开发讲什么", communication_text)
        self.assertIn("和测试讲什么", communication_text)

        replay_text = (replay / "AI量化交易平台_交易复盘与优化详细方案.md").read_text(encoding="utf-8")
        self.assertIn("交易复盘与优化", replay_text)
        self.assertIn("指定指标复盘", replay_text)
        self.assertIn("自动复盘", replay_text)
        self.assertIn("市场环境复盘", replay_text)
        self.assertIn("夏普最大", replay_text)
        self.assertIn("默认选中“夏普最大”", replay_text)
        self.assertIn("PE / PB", replay_text)
        self.assertIn("结构化规则草案", replay_text)
        self.assertIn("收益曲线", replay_text)
        self.assertIn("成交买卖记录", replay_text)
        self.assertIn("默认展示 Top 5", replay_text)
        self.assertIn("买入价", replay_text)
        self.assertIn("卖出价", replay_text)
        self.assertIn("持仓时长", replay_text)
        self.assertIn("盈亏比例", replay_text)

        replay_mock_text = (replay / "AI量化交易平台_交易复盘与优化输出原型.html").read_text(encoding="utf-8")
        self.assertIn("交易复盘与优化输出原型", replay_mock_text)
        self.assertIn("旧参数 vs 新参数", replay_mock_text)
        self.assertIn("指标条件替换", replay_mock_text)
        self.assertIn("收益曲线", replay_mock_text)
        self.assertIn("成交买卖记录", replay_mock_text)
        self.assertIn("当前只看：夏普最大", replay_mock_text)
        self.assertIn("trade-scroll", replay_mock_text)
        self.assertIn("买入价", replay_mock_text)
        self.assertIn("卖出价", replay_mock_text)
        self.assertIn("持仓时长", replay_mock_text)
        self.assertIn("盈亏比例", replay_mock_text)

        replay_engineering_text = (replay / "AI量化交易平台_交易复盘与优化研发拆解.md").read_text(encoding="utf-8")
        self.assertIn("输入与数据层", replay_engineering_text)
        self.assertIn("特征提取层", replay_engineering_text)
        self.assertIn("优化计算层", replay_engineering_text)
        self.assertIn("输出展示层", replay_engineering_text)
        self.assertIn("额度与计费层", replay_engineering_text)
        self.assertIn("当前最值得先做的研发任务", replay_engineering_text)

        replay_schedule_text = (replay / "AI量化交易平台_交易复盘与优化开发排期与验收清单.md").read_text(encoding="utf-8")
        self.assertIn("Phase 1", replay_schedule_text)
        self.assertIn("Phase 2", replay_schedule_text)
        self.assertIn("Phase 3", replay_schedule_text)
        self.assertIn("任务优先级清单", replay_schedule_text)
        self.assertIn("测试排期", replay_schedule_text)
        self.assertIn("当前建议的实际起手顺序", replay_schedule_text)

        replay_algorithm_text = (replay / "AI量化交易平台_交易复盘与优化算法与数据口径.md").read_text(encoding="utf-8")
        self.assertIn("数据源口径", replay_algorithm_text)
        self.assertIn("A 股主数据优先级", replay_algorithm_text)
        self.assertIn("统一交易记录口径", replay_algorithm_text)
        self.assertIn("价格与复权口径", replay_algorithm_text)
        self.assertIn("显著性排序口径", replay_algorithm_text)
        self.assertIn("拒绝输出强结论的情况", replay_algorithm_text)

        module_matrix_text = (folder / "AI量化交易平台_模块级产品与研发总表.md").read_text(encoding="utf-8")
        self.assertIn("用户工作台", module_matrix_text)
        self.assertIn("管理员工作台", module_matrix_text)
        self.assertIn("交易复盘与优化", module_matrix_text)
        self.assertIn("金融导师", module_matrix_text)
        self.assertIn("金融助手", module_matrix_text)
        self.assertIn("平台数据中心", module_matrix_text)

        platform_schedule_text = (folder / "AI量化交易平台_全平台开发排期与验收清单.md").read_text(encoding="utf-8")
        self.assertIn("可信研究主链路", platform_schedule_text)
        self.assertIn("体验增强与双角色完善", platform_schedule_text)
        self.assertIn("商业化与治理完善", platform_schedule_text)
        self.assertIn("模块优先级矩阵", platform_schedule_text)
        self.assertIn("当前给公司的建议", platform_schedule_text)


if __name__ == "__main__":
    unittest.main()
