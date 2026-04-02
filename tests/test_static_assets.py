from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class StaticAssetTests(unittest.TestCase):
    def _assert_asset_has_valid_module_syntax(self, filename: str) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")

        asset_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / filename
        )
        completed = subprocess.run(
            [node, "--check", str(asset_path)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            0,
            completed.returncode,
            msg=completed.stderr or completed.stdout or f"{filename} syntax check failed",
        )

    def test_rules_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("rules.js")

    def test_admin_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("admin.js")

    def test_backtests_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("backtests.js")

    def test_replay_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("replay.js")

    def test_shared_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("shared.js")

    def test_rules_js_can_bootstrap_with_stubbed_dom(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")

        asset_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "rules.js"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            shared_path = (
                WORKSPACE_ROOT
                / "apps"
                / "api"
                / "src"
                / "quant_platform_api"
                / "static"
                / "shared.js"
            )
            rules_copy = temp_dir_path / "rules.js"
            shared_copy = temp_dir_path / "shared.js"
            rules_copy.write_text(
                asset_path.read_text(encoding="utf-8").replace(
                    'from "/assets/shared.js"',
                    'from "./shared.js"',
                ),
                encoding="utf-8",
            )
            shared_copy.write_text(shared_path.read_text(encoding="utf-8"), encoding="utf-8")
            script_path = Path(temp_dir) / "bootstrap-rules.mjs"
            script_path.write_text(
                f"""
import {{ pathToFileURL }} from 'node:url';

function createNode() {{
  return {{
    value: '',
    innerHTML: '',
    textContent: '',
    dataset: {{}},
    selectedOptions: [{{ dataset: {{}} }}],
    addEventListener() {{}},
    querySelector() {{ return createNode(); }},
    querySelectorAll() {{ return []; }},
    closest() {{ return createNode(); }},
    insertAdjacentHTML() {{}},
    remove() {{}},
  }};
}}

globalThis.document = {{
  querySelector() {{ return createNode(); }},
  querySelectorAll() {{ return []; }},
}};
globalThis.window = {{
  location: {{ href: '' }},
}};
globalThis.fetch = async (url) => ({{
  ok: true,
  json: async () => {{
    if (String(url).includes('/api/v1/rules/defaults')) {{
      return {{ data: {{ items: [] }} }};
    }}
    if (String(url).includes('/api/v1/rules/glossary')) {{
      return {{ data: {{ items: [] }} }};
    }}
    return {{ data: {{}} }};
  }},
}});

await import(pathToFileURL({str(rules_copy)!r}).href);
console.log('bootstrapped');
                """,
                encoding="utf-8",
            )
            completed = subprocess.run(
                [node, str(script_path)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(
            0,
            completed.returncode,
            msg=completed.stderr or completed.stdout or "rules.js bootstrap failed",
        )
        self.assertIn("bootstrapped", completed.stdout)

    def test_rules_js_renders_collapsible_group_markup(self) -> None:
        rules_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "rules.js"
        )
        source = rules_path.read_text(encoding="utf-8")

        self.assertIn('<details class="accordion-item rule-group-card"', source)
        self.assertIn('class="rule-group-summary"', source)
        self.assertIn('class="rule-group-title"', source)

    def test_backtests_js_contains_compare_workflow(self) -> None:
        backtests_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "backtests.js"
        )
        source = backtests_path.read_text(encoding="utf-8")

        self.assertIn('const compareSelection = new Set();', source)
        self.assertIn("/api/v1/backtests/compare?", source)
        self.assertIn("renderCompareTable", source)
        self.assertIn("formatSettlementPolicyLabel", source)
        self.assertIn("formatAdjustmentModeLabel", source)
        self.assertIn('class="history-meta-grid"', source)
        self.assertIn("结算与卖出", source)
        self.assertIn("价格口径", source)
        self.assertIn("数据快照", source)
        self.assertIn("T+1，当日买入后需次日才能卖出", source)
        self.assertIn("未设置价格口径", source)
        self.assertIn("syncHistoryViewportHeight", source)
        self.assertIn('data-delete-id="${item.backtest_run_id}"', source)
        self.assertIn('method: "DELETE"', source)
        self.assertIn("删除记录", source)

    def test_replay_assets_include_ready_state_and_clear_side_language(self) -> None:
        replay_js_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.js"
        )
        replay_html_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.html"
        )
        services_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "services.py"
        )

        replay_js_source = replay_js_path.read_text(encoding="utf-8")
        replay_html_source = replay_html_path.read_text(encoding="utf-8")
        services_source = services_path.read_text(encoding="utf-8")

        self.assertIn("syncReplayActionState", replay_js_source)
        self.assertIn("uploadScreenshotTrade", replay_js_source)
        self.assertIn("uploadManualTrades", replay_js_source)
        self.assertIn('classList.toggle("primary"', replay_js_source)
        self.assertIn('disabled>运行 AI 复盘</button>', replay_html_source)
        self.assertIn("成交截图", replay_html_source)
        self.assertIn("手动录入", replay_html_source)
        self.assertIn('return "做空交易" if side == "short" else "做多交易"', services_source)
        self.assertIn('f"{best_side_label}的累计盈亏和整体表现当前更优"', services_source)
        self.assertIn("def _build_single_side_suggestions(", services_source)


if __name__ == "__main__":
    unittest.main()
