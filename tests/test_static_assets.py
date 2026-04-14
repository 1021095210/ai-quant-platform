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

    def test_replay_assets_include_manual_text_parse_flow(self) -> None:
        replay_html = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.html"
        ).read_text(encoding="utf-8")
        replay_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.js"
        ).read_text(encoding="utf-8")

        self.assertIn('id="trade-manual-smart-text"', replay_html)
        self.assertIn('id="parse-manual-text-btn"', replay_html)
        self.assertIn('id="trade-manual-entry-price"', replay_html)
        self.assertIn('id="trade-manual-exit-price"', replay_html)
        self.assertIn('id="trade-manual-quantity"', replay_html)
        self.assertIn("长文字智能识别", replay_html)
        self.assertIn('id="replay-overview"', replay_html)
        self.assertIn('id="replay-loss-features"', replay_html)
        self.assertIn('id="replay-profit-features"', replay_html)
        self.assertIn('id="replay-objective-tabs"', replay_html)
        self.assertIn('id="replay-objective-detail"', replay_html)
        self.assertIn('id="replay-lookback-days"', replay_html)
        self.assertIn('id="replay-minute-window"', replay_html)
        self.assertIn('id="replay-include-minute-features"', replay_html)
        self.assertIn('id="replay-include-fundamentals"', replay_html)
        self.assertIn('id="trade-manual-llm-profile"', replay_html)
        self.assertIn("/api/v1/trades/uploads/manual/parse-text", replay_js)
        self.assertIn("智能识别并加入记录", replay_js)

    def test_replay_assets_hide_inactive_source_panels(self) -> None:
        replay_html = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.html"
        ).read_text(encoding="utf-8")
        theme_css = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "theme.css"
        ).read_text(encoding="utf-8")

        self.assertIn('id="source-panel-screenshot" class="source-panel" hidden', replay_html)
        self.assertIn('id="source-panel-manual" class="source-panel" hidden', replay_html)
        self.assertIn("[hidden]", theme_css)
        self.assertIn("display: none !important;", theme_css)

    def test_replay_assets_include_screenshot_ocr_flow(self) -> None:
        replay_html = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.html"
        ).read_text(encoding="utf-8")
        replay_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.js"
        ).read_text(encoding="utf-8")

        self.assertIn('id="ocr-screenshot-btn"', replay_html)
        self.assertIn('id="screenshot-ocr-summary"', replay_html)
        self.assertIn('id="import-screenshot-records-btn"', replay_html)
        self.assertIn("/api/v1/trades/uploads/screenshot/ocr", replay_js)
        self.assertIn("智能识别截图内容", replay_js)
        self.assertIn("detected_records", replay_js)
        self.assertIn("importScreenshotRecordsToManualList", replay_js)

    def test_strategy_and_backtests_assets_include_capability_guidance(self) -> None:
        strategy_html = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "strategy.html"
        ).read_text(encoding="utf-8")
        strategy_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "strategy.js"
        ).read_text(encoding="utf-8")
        backtests_html = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "backtests.html"
        ).read_text(encoding="utf-8")
        backtests_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "backtests.js"
        ).read_text(encoding="utf-8")

        self.assertIn('id="strategy-capability-summary"', strategy_html)
        self.assertIn('id="strategy-capability-matrix"', strategy_html)
        self.assertIn('id="strategy-llm-profile"', strategy_html)
        self.assertIn("/api/v1/platform/capabilities", strategy_js)
        self.assertIn("fetchLlmProfiles", strategy_js)
        self.assertIn('id="backtest-support-summary"', backtests_html)
        self.assertIn('id="backtest-capability-matrix"', backtests_html)
        self.assertIn("/api/v1/platform/capabilities", backtests_js)
        self.assertIn("当前暂不开放真实回测", backtests_js)

    def test_mentor_and_assistant_assets_include_llm_profile_selectors(self) -> None:
        mentor_html = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "mentor.html"
        ).read_text(encoding="utf-8")
        mentor_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "mentor.js"
        ).read_text(encoding="utf-8")
        assistant_html = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "assistant.html"
        ).read_text(encoding="utf-8")
        assistant_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "assistant.js"
        ).read_text(encoding="utf-8")
        shared_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "shared.js"
        ).read_text(encoding="utf-8")

        self.assertIn('id="mentor-llm-profile"', mentor_html)
        self.assertIn("fetchLlmProfiles", mentor_js)
        self.assertIn('id="assistant-llm-profile"', assistant_html)
        self.assertIn('id="assistant-task-center"', assistant_html)
        self.assertIn('id="assistant-refresh-tasks-btn"', assistant_html)
        self.assertIn("fetchLlmProfiles", assistant_js)
        self.assertIn("/api/v1/assistant/research-tasks", assistant_js)
        self.assertIn("打开结果", assistant_js)
        self.assertIn("/api/v1/platform/llm-profiles", shared_js)

    def test_replay_assets_include_validation_summary_rendering(self) -> None:
        replay_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "replay.js"
        ).read_text(encoding="utf-8")

        self.assertIn("validation_summary", replay_js)
        self.assertIn("buildManualParseValidationLines", replay_js)
        self.assertIn("验收摘要：", replay_js)

    def test_workspace_assets_include_focus_and_data_hub_sections(self) -> None:
        workspace_html = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "workspace.html"
        ).read_text(encoding="utf-8")
        workspace_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "workspace.js"
        ).read_text(encoding="utf-8")

        self.assertIn('id="workspace-focus-cards"', workspace_html)
        self.assertIn('id="workspace-data-hub"', workspace_html)
        self.assertIn("renderFocusCards", workspace_js)
        self.assertIn("renderDataHubStatus", workspace_js)

    def test_backtests_and_replay_assets_include_data_source_guidance(self) -> None:
        backtests_js = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "backtests.js"
        ).read_text(encoding="utf-8")

        self.assertIn("优先链路", backtests_js)
        self.assertIn("执行约束回放", backtests_js)
        self.assertIn("nodes.adjustmentMode.value", backtests_js)
        self.assertIn("nodes.assetType.value", backtests_js)

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
export async function fetchLlmProfiles() {
  return {
    data: {
      items: [
        { profile_id: 'module_default', label: '模块默认模型', enabled: true },
      ],
      defaults: { mentor: 'module_default' },
    },
  };
}
export function populateLlmProfileSelect(node) {
  if (node) {
    node.disabled = false;
    node.value = 'module_default';
  }
}
export function setStatus() {}
export function setInlineStatus() {}
export function clearInlineStatus() {}
export function registerBackgroundTask() {}
export function subscribeBackgroundTasks() { return () => {}; }
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
        self.assertIn("SOURCE_MODE_META", replay_js_source)
        self.assertIn("sourceModeIntro", replay_js_source)
        self.assertIn("sourceModeTitle", replay_js_source)
        self.assertIn("sourceModeSteps", replay_js_source)
        self.assertIn("uploadScreenshotTrade", replay_js_source)
        self.assertIn("uploadManualTrades", replay_js_source)
        self.assertIn("renderReplayOverview", replay_js_source)
        self.assertIn("renderReplayObjectiveTabs", replay_js_source)
        self.assertIn("renderReplayObjectiveDetail", replay_js_source)
        self.assertIn("renderReplayObjectiveMetrics", replay_js_source)
        self.assertIn("renderReplayTradeRecords", replay_js_source)
        self.assertIn("字段来源分布", replay_js_source)
        self.assertIn("renderReplayFieldSourceBreakdown", replay_js_source)
        self.assertIn("renderReplayTradeFieldSources", replay_js_source)
        self.assertIn("analysis_options", replay_js_source)
        self.assertIn("replayAnalysisStatusLabel", replay_js_source)
        self.assertIn('classList.toggle("primary"', replay_js_source)
        self.assertIn('classList.toggle("active"', replay_js_source)
        self.assertIn('disabled>运行 AI 复盘</button>', replay_html_source)
        self.assertIn("成交截图", replay_html_source)
        self.assertIn("手动录入", replay_html_source)
        self.assertIn('class="source-mode-guide"', replay_html_source)
        self.assertIn('id="source-mode-title"', replay_html_source)
        self.assertIn('id="source-mode-steps"', replay_html_source)
        self.assertIn('id="source-mode-intro"', replay_html_source)
        self.assertIn('id="source-panel-screenshot" class="source-panel" hidden', replay_html_source)
        self.assertIn('id="source-panel-manual" class="source-panel" hidden', replay_html_source)
        self.assertIn("或直接粘贴 CSV", replay_html_source)
        self.assertIn('return "做空交易" if side == "short" else "做多交易"', services_source)
        self.assertIn('f"{best_side_label}的累计盈亏和整体表现当前更优"', services_source)
        self.assertIn("def _build_single_side_suggestions(", services_source)
        self.assertIn("def _build_replay_objective_versions(", services_source)
        self.assertIn("def _build_replay_sample_metrics(", services_source)
        self.assertIn("def _build_replay_daily_contexts(", services_source)
        self.assertIn("def _build_replay_analysis_scope(", services_source)

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
        self.assertIn('id="mentor-inline-status"', mentor_html)
        self.assertIn('id="mentor-ask-btn" class="btn disabled" disabled', mentor_html)
        self.assertIn('id="mentor-followup-btn" class="btn disabled" disabled', mentor_html)
        self.assertIn("/api/v1/mentor/topics", mentor_js)
        self.assertIn("/api/v1/mentor/ask-tasks", mentor_js)
        self.assertIn("renderTopics", mentor_js)
        self.assertIn("conversation_history", mentor_js)
        self.assertIn("renderConversation", mentor_js)
        self.assertIn("answer_mode_label", mentor_js)
        self.assertIn("当前模式", mentor_js)
        self.assertIn("registerBackgroundTask", mentor_js)
        self.assertIn("subscribeBackgroundTasks", mentor_js)
        self.assertIn("导师判断", mentor_html)
        self.assertIn("建议下一步", mentor_html)
        self.assertIn("继续追问导师", mentor_html)
        self.assertIn('/assets/mentor.js?v=20260403a', mentor_html)
        self.assertIn('from "/assets/shared.js?v=', mentor_js)

    def test_assistant_assets_expose_workflows_and_structured_research_sections(self) -> None:
        assistant_html_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "assistant.html"
        )
        assistant_js_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / "assistant.js"
        )

        assistant_html = assistant_html_path.read_text(encoding="utf-8")
        assistant_js = assistant_js_path.read_text(encoding="utf-8")

        self.assertIn("金融助手", assistant_html)
        self.assertIn('id="assistant-inline-status"', assistant_html)
        self.assertIn('id="assistant-followup-status"', assistant_html)
        self.assertIn('id="assistant-workflows"', assistant_html)
        self.assertIn('id="assistant-desks"', assistant_html)
        self.assertIn('id="assistant-run-btn" class="btn disabled" disabled', assistant_html)
        self.assertIn('id="assistant-followup-btn" class="btn disabled" disabled', assistant_html)
        self.assertIn("/api/v1/assistant/workflows", assistant_js)
        self.assertIn("/api/v1/assistant/research-tasks", assistant_js)
        self.assertIn("renderWorkflows", assistant_js)
        self.assertIn("registerBackgroundTask", assistant_js)
        self.assertIn("subscribeBackgroundTasks", assistant_js)
        self.assertIn("assistant-selected-workflow", assistant_html)
        self.assertIn("/assets/assistant.js?v=20260403a", assistant_html)

    def test_strategy_and_replay_assets_expose_background_task_status_hooks(self) -> None:
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

        strategy_html = strategy_html_path.read_text(encoding="utf-8")
        strategy_js = strategy_js_path.read_text(encoding="utf-8")
        replay_html = replay_html_path.read_text(encoding="utf-8")
        replay_js = replay_js_path.read_text(encoding="utf-8")

        self.assertIn('id="strategy-inline-status"', strategy_html)
        self.assertIn("/api/v1/strategies/generations", strategy_js)
        self.assertIn("registerBackgroundTask", strategy_js)
        self.assertIn("subscribeBackgroundTasks", strategy_js)

        self.assertIn('id="trade-manual-inline-status"', replay_html)
        self.assertIn('id="replay-inline-status"', replay_html)
        self.assertIn("/api/v1/trades/uploads/manual/parse-text-tasks", replay_js)
        self.assertIn("registerBackgroundTask", replay_js)
        self.assertIn("subscribeBackgroundTasks", replay_js)
        self.assertIn("applyManualParseResult", replay_js)
        self.assertIn("applyReplayResult", replay_js)

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
