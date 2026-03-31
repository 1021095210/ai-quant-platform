from __future__ import annotations

import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class ModuleSplitDocumentTests(unittest.TestCase):
    def test_module_split_doc_exists_and_contains_core_modules(self) -> None:
        path = WORKSPACE_ROOT / "产品设计" / "AI量化交易平台_模块拆分与子代理分工.md"
        self.assertTrue(path.exists(), "模块拆分总稿不存在")

        content = path.read_text(encoding="utf-8")
        self.assertIn("# AI量化交易平台模块拆分与子代理分工总稿", content)
        self.assertIn("### 模块 1：用户工作台与项目组织模块", content)
        self.assertIn("### 模块 2：策略编排模块", content)
        self.assertIn("### 模块 3：指标与规则知识系统", content)
        self.assertIn("### 模块 4：回测执行与结果模块", content)
        self.assertIn("### 模块 5：交易复盘与建议回灌模块", content)
        self.assertIn("### 模块 6：平台底座与治理模块", content)
        self.assertIn("### 模块 7：数据库与数据资产模块", content)
        self.assertIn("K 线数据必须存储在云端共享行情库", content)
        self.assertIn("后续新数据只做增量追加", content)
        self.assertIn("交割单导入（CSV / XLSX / 图片 OCR）", content)
        self.assertIn("OCR 文本识别与结构化抽取", content)
