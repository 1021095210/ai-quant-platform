from __future__ import annotations

import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class FreezeDocumentTests(unittest.TestCase):
    def test_platform_contract_freeze_doc_exists(self) -> None:
        path = WORKSPACE_ROOT / "产品设计" / "AI量化交易平台_平台公共契约冻结稿.md"
        self.assertTrue(path.exists(), "平台公共契约冻结稿不存在")

        content = path.read_text(encoding="utf-8")
        self.assertIn("AI量化交易平台平台公共契约冻结稿", content)
        self.assertIn("tenant -> workspace -> environment -> resource", content)
        self.assertIn("Idempotency-Key", content)
        self.assertIn("config_revision", content)
        for state in [
            "pending",
            "queued",
            "running",
            "succeeded",
            "failed",
            "canceling",
            "canceled",
        ]:
            self.assertIn(state, content)

    def test_dual_database_freeze_doc_exists(self) -> None:
        path = WORKSPACE_ROOT / "产品设计" / "AI量化交易平台_数据库双层边界冻结稿.md"
        self.assertTrue(path.exists(), "数据库双层边界冻结稿不存在")

        content = path.read_text(encoding="utf-8")
        self.assertIn("AI量化交易平台数据库双层边界冻结稿", content)
        self.assertIn("业务数据库", content)
        self.assertIn("云端行情库", content)
        self.assertIn("首次全量入库", content)
        self.assertIn("后续增量同步", content)
        self.assertIn("data_snapshot_ref", content)
        self.assertIn("正式执行的唯一权威行情来源冻结为云端共享行情库", content)


if __name__ == "__main__":
    unittest.main()
