from pathlib import Path
import unittest

from pptx import Presentation


ROOT = Path("/workspace/ai-quant-platform")
REPORT_DIR = ROOT / "产品设计" / "复盘总结"
ASSET_DIR = REPORT_DIR / "assets" / "weekly-2026-04-03"


class WeeklyReportArtifactsTests(unittest.TestCase):
    def test_weekly_report_markdown_exists(self):
        report = REPORT_DIR / "AI量化交易平台_本周工作汇报_2026-04-03.md"
        self.assertTrue(report.exists())
        content = report.read_text(encoding="utf-8")
        self.assertIn("AI量化交易平台本周工作汇报", content)
        self.assertIn("2026-03-30 至 2026-04-03", content)

    def test_weekly_report_screenshot_assets_exist(self):
        expected = {
            "home.png",
            "workspace.png",
            "strategy.png",
            "backtests.png",
            "replay.png",
            "mentor.png",
            "assistant.png",
            "admin.png",
        }
        existing = {path.name for path in ASSET_DIR.glob("*.png")}
        self.assertTrue(expected.issubset(existing))

    def test_weekly_report_ppt_exists_and_has_enough_slides(self):
        ppt = REPORT_DIR / "AI量化交易平台_本周工作汇报_2026-04-03.pptx"
        self.assertTrue(ppt.exists())
        prs = Presentation(str(ppt))
        self.assertGreaterEqual(len(prs.slides), 12)


if __name__ == "__main__":
    unittest.main()
