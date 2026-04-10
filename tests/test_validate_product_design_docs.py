from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tools.validate_product_design_docs import collect_missing_sections, format_report


class ValidateProductDesignDocsTests(unittest.TestCase):
    def test_workspace_documents_pass_validation(self) -> None:
        missing = collect_missing_sections(WORKSPACE_ROOT)
        self.assertEqual({}, missing)

    def test_specific_quant_docs_are_tracked_by_validator(self) -> None:
        missing = collect_missing_sections(
            WORKSPACE_ROOT,
            requirements={
                "产品设计/AI量化交易平台_选题说明.md": ("# AI 量化交易平台选题说明",),
                "产品设计/AI量化交易平台_设计文档.md": ("# AI 量化交易平台设计文档",),
                "产品设计/AI量化交易平台_验收演示脚本.md": ("# AI 量化交易平台验收演示脚本",),
            },
        )
        self.assertEqual({}, missing)

    def test_extended_quant_docs_are_tracked_by_validator(self) -> None:
        missing = collect_missing_sections(
            WORKSPACE_ROOT,
            requirements={
                "产品设计/AI量化交易平台_页面与交互设计.md": ("# AI 量化交易平台页面与交互设计",),
                "产品设计/AI量化交易平台_API详细设计.md": (
                    "# AI 量化交易平台 API 详细设计",
                    "### 长任务与异步约定",
                    "### `GET /api/v1/backtests/runs/{backtest_run_id}`",
                ),
                "产品设计/AI量化交易平台_数据库设计.sql": (
                    "CREATE TABLE users",
                    "CREATE TABLE trade_fills",
                    "dataset_snapshot_ref VARCHAR(120) NOT NULL",
                ),
            },
        )
        self.assertEqual({}, missing)

    def test_submission_docs_are_tracked_by_validator(self) -> None:
        missing = collect_missing_sections(
            WORKSPACE_ROOT,
            requirements={
                "产品设计/AI量化交易平台_周一提交版.md": (
                    "# AI 量化交易平台周一提交版",
                    "### 3.6 平台化目标与工程边界",
                    "### 4.5 平台化补充：回测可信度与异步约定",
                    "## 9. 环境搭建",
                ),
                "产品设计/AI量化交易平台_环境搭建.md": (
                    "# AI 量化交易平台环境搭建说明",
                    "## 数据治理与安全边界",
                    "## 环境搭建验收标准",
                ),
            },
        )
        self.assertEqual({}, missing)

    def test_data_model_doc_is_tracked_by_validator(self) -> None:
        missing = collect_missing_sections(
            WORKSPACE_ROOT,
            requirements={
                "产品设计/AI量化交易平台_数据模型设计.md": (
                    "# AI 量化交易平台数据模型设计",
                    "## 表设计",
                    "## 可追溯性与版本字段",
                    "## 数据模型验收标准",
                ),
            },
        )
        self.assertEqual({}, missing)

    def test_visual_and_ai_design_docs_are_tracked_by_validator(self) -> None:
        missing = collect_missing_sections(
            WORKSPACE_ROOT,
            requirements={
                "产品设计/AI量化交易平台_架构与流程图.md": (
                    "# AI 量化交易平台架构与流程图",
                    "## 6. 业务流程图",
                ),
                "产品设计/AI量化交易平台_AI协作设计记录.md": (
                    "# AI 量化交易平台 AI 协作设计记录",
                    "## 本次 AI 协作的结论",
                ),
                "产品设计/AI量化交易平台_页面原型.html": (
                    "<title>AI量化交易平台低保真原型</title>",
                    "AI 复盘建议",
                ),
            },
        )
        self.assertEqual({}, missing)

    def test_group_submission_doc_is_tracked_by_validator(self) -> None:
        missing = collect_missing_sections(
            WORKSPACE_ROOT,
            requirements={
                "产品设计/AI量化交易平台_群提交版.md": (
                    "# 选题 + 设计文档 + 环境搭建",
                    "## 环境搭建",
                    "## 五日开发计划",
                    "## 选题自问清单",
                ),
            },
        )
        self.assertEqual({}, missing)

    def test_missing_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            missing = collect_missing_sections(
                base_dir,
                requirements={"产品设计/不存在.md": ("# 标题",)},
            )
            self.assertEqual(
                {"产品设计/不存在.md": ["<missing file>"]},
                missing,
            )

    def test_missing_section_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            doc_path = base_dir / "产品设计/样例.md"
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text("# 标题\n\n## 已有章节\n", encoding="utf-8")

            missing = collect_missing_sections(
                base_dir,
                requirements={"产品设计/样例.md": ("# 标题", "## 缺失章节")},
            )
            self.assertEqual(
                {"产品设计/样例.md": ["## 缺失章节"]},
                missing,
            )

    def test_report_is_human_readable(self) -> None:
        report = format_report({"产品设计/样例.md": ["## 缺失章节"]})
        self.assertIn("产品设计/样例.md", report)
        self.assertIn("## 缺失章节", report)


if __name__ == "__main__":
    unittest.main()
