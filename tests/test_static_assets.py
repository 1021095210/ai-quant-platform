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

    def test_strategy_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("strategy.js")

    def test_indicators_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("indicators.js")

    def test_mentor_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("mentor.js")

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

    def test_mentor_js_can_bootstrap_with_stubbed_dom_and_load_topics(self) -> None:
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
            / "mentor.js"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            mentor_copy = temp_dir_path / "mentor.js"
            mentor_copy.write_text(
                asset_path
                .read_text(encoding="utf-8")
                .replace('from "/assets/shared.js?v=20260402b"', 'from "./shared.js"')
                .replace('from "/assets/shared.js?v=20260402c"', 'from "./shared.js"'),
                encoding="utf-8",
            )
            (temp_dir_path / "shared.js").write_text(
                """
export function activateNav() {}
export async function api(url) {
  if (String(url).includes('/api/v1/mentor/topics')) {
    return {
      data: {
        items: [
          {
            title: '先理解回测结果',
            prompt: '回测结果里我应该先看什么？',
            summary: '先看净值、回撤和成交假设。',
          },
        ],
      },
    };
  }
  return { data: {} };
}
export function setStatus() {}
                """,
                encoding="utf-8",
            )
            script_path = temp_dir_path / "bootstrap-mentor.mjs"
            script_path.write_text(
                f"""
import {{ pathToFileURL }} from 'node:url';

const nodes = new Map();

function createNode(selector = '') {{
  return {{
    selector,
    value: '',
    innerHTML: '',
    textContent: '',
    className: '',
    disabled: false,
    dataset: {{}},
    addEventListener() {{}},
    focus() {{}},
    querySelectorAll() {{ return []; }},
  }};
}}

globalThis.document = {{
  querySelector(selector) {{
    if (!nodes.has(selector)) {{
      nodes.set(selector, createNode(selector));
    }}
    return nodes.get(selector);
  }},
  querySelectorAll() {{ return []; }},
}};
globalThis.window = {{
  location: {{ href: '' }},
  addEventListener() {{}},
}};

await import(pathToFileURL({str(mentor_copy)!r}).href);
await new Promise((resolve) => setTimeout(resolve, 0));

const topicNode = nodes.get('#mentor-topic-list');
if (!topicNode || !String(topicNode.innerHTML).includes('先理解回测结果')) {{
  throw new Error('mentor topics did not render');
}}
console.log('mentor-bootstrapped');
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
            msg=completed.stderr or completed.stdout or "mentor.js bootstrap failed",
        )
        self.assertIn("mentor-bootstrapped", completed.stdout)

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

    def test_strategy_and_indicator_assets_use_progressive_action_states(self) -> None:
        strategy_html_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "strategy.html"
        )
        strategy_js_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "strategy.js"
        )
        indicators_html_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "indicators.html"
        )
        indicators_js_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "indicators.js"
        )

        strategy_html = strategy_html_path.read_text(encoding="utf-8")
        strategy_js = strategy_js_path.read_text(encoding="utf-8")
        indicators_html = indicators_html_path.read_text(encoding="utf-8")
        indicators_js = indicators_js_path.read_text(encoding="utf-8")

        self.assertIn('id="project-version-label"', strategy_html)
        self.assertIn('id="save-project-btn" class="btn disabled" disabled', strategy_html)
        self.assertIn('id="go-backtests-link" class="btn disabled"', strategy_html)
        self.assertIn("syncStrategyActionState", strategy_js)
        self.assertIn('version_label: nodes.versionLabel.value', strategy_js)
        self.assertIn('id="save-custom-indicator-btn" class="btn disabled" disabled', indicators_html)
        self.assertIn("syncIndicatorActionState", indicators_js)

    def test_replay_and_rules_assets_use_progressive_action_states(self) -> None:
        replay_html_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.html"
        )
        replay_js_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.js"
        )
        rules_html_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "rules.html"
        )
        rules_js_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "rules.js"
        )

        replay_html = replay_html_path.read_text(encoding="utf-8")
        replay_js = replay_js_path.read_text(encoding="utf-8")
        rules_html = rules_html_path.read_text(encoding="utf-8")
        rules_js = rules_js_path.read_text(encoding="utf-8")

        self.assertIn('id="upload-trades-btn" class="btn disabled" disabled', replay_html)
        self.assertIn('id="add-manual-trade-btn" class="btn disabled"', replay_html)
        self.assertIn("syncReplayActionState", replay_js)
        self.assertIn("const csvReady =", replay_js)
        self.assertIn("const screenshotReady =", replay_js)
        self.assertIn("const manualUploadReady =", replay_js)
        self.assertIn('id="save-default-rules-btn" class="btn disabled" disabled', rules_html)
        self.assertIn('id="save-glossary-btn" class="btn disabled" disabled', rules_html)
        self.assertIn("syncRulesActionState", rules_js)
        self.assertIn("markDefaultRulesDirty", rules_js)

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
        self.assertIn("SOURCE_MODE_INTROS", replay_js_source)
        self.assertIn("sourceModeIntro", replay_js_source)
        self.assertIn("uploadScreenshotTrade", replay_js_source)
        self.assertIn("uploadManualTrades", replay_js_source)
        self.assertIn('classList.toggle("primary"', replay_js_source)
        self.assertIn('disabled>运行 AI 复盘</button>', replay_html_source)
        self.assertIn("成交截图", replay_html_source)
        self.assertIn("手动录入", replay_html_source)
        self.assertIn('id="source-mode-intro"', replay_html_source)
        self.assertIn('id="source-panel-screenshot" class="source-panel" hidden', replay_html_source)
        self.assertIn('id="source-panel-manual" class="source-panel" hidden', replay_html_source)
        self.assertIn("或直接粘贴 CSV", replay_html_source)
        self.assertIn('return "做空交易" if side == "short" else "做多交易"', services_source)
        self.assertIn('f"{best_side_label}的累计盈亏和整体表现当前更优"', services_source)
        self.assertIn("def _build_single_side_suggestions(", services_source)

    def test_mentor_assets_expose_topic_cards_and_structured_answer_sections(self) -> None:
        mentor_html_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "mentor.html"
        )
        mentor_js_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "mentor.js"
        )

        mentor_html = mentor_html_path.read_text(encoding="utf-8")
        mentor_js = mentor_js_path.read_text(encoding="utf-8")

        self.assertIn("金融导师", mentor_html)
        self.assertIn('id="mentor-topic-list"', mentor_html)
        self.assertIn('id="mentor-ask-btn" class="btn disabled" disabled', mentor_html)
        self.assertIn('id="mentor-followup-btn" class="btn disabled" disabled', mentor_html)
        self.assertIn("/api/v1/mentor/topics", mentor_js)
        self.assertIn("/api/v1/mentor/ask", mentor_js)
        self.assertIn("renderTopics", mentor_js)
        self.assertIn("conversation_history", mentor_js)
        self.assertIn("renderConversation", mentor_js)
        self.assertIn("导师判断", mentor_html)
        self.assertIn("建议下一步", mentor_html)
        self.assertIn("继续追问导师", mentor_html)
        self.assertIn('/assets/mentor.js?v=', mentor_html)
        self.assertIn('from "/assets/shared.js?v=', mentor_js)

    def test_admin_and_shared_assets_include_error_logging_hooks(self) -> None:
        admin_html_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "admin.html"
        )
        admin_js_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "admin.js"
        )
        shared_js_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "shared.js"
        )

        admin_html = admin_html_path.read_text(encoding="utf-8")
        admin_js = admin_js_path.read_text(encoding="utf-8")
        shared_js = shared_js_path.read_text(encoding="utf-8")

        self.assertIn("用户报错与应用日志", admin_html)
        self.assertIn('id="admin-app-logs"', admin_html)
        self.assertIn("renderAppLogs", admin_js)
        self.assertIn("/api/v1/admin/app-logs", admin_js)
        self.assertIn("reportClientError", shared_js)
        self.assertIn("/api/v1/client-errors", shared_js)


if __name__ == "__main__":
    unittest.main()
