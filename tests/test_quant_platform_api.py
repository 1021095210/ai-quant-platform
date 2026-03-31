from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
API_SRC = WORKSPACE_ROOT / "apps" / "api" / "src"
VENV_LIB = WORKSPACE_ROOT / ".venv" / "lib"

if API_SRC.exists() and str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

if VENV_LIB.exists():
    for site_packages in VENV_LIB.glob("python*/site-packages"):
        if str(site_packages) not in sys.path:
            sys.path.insert(0, str(site_packages))

try:
    from fastapi.testclient import TestClient
    from quant_platform_api.config import Settings
    from quant_platform_api.main import create_app
except ModuleNotFoundError:  # pragma: no cover - handled by skip
    TestClient = None
    Settings = None
    create_app = None


@unittest.skipIf(TestClient is None, "FastAPI dependencies are unavailable")
class QuantPlatformApiTests(unittest.TestCase):
    def _build_client(
        self,
        *,
        job_execution_mode: str = "immediate",
        job_simulation_latency_ms: int = 0,
        database_url: str | None = None,
    ) -> TestClient:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        if database_url is None:
            database_url = f"sqlite+pysqlite:///{Path(temp_dir.name) / 'quant_platform.db'}"

        settings = Settings(
            database_url=database_url,
            market_data_database_path=str(Path(temp_dir.name) / "market_data.db"),
            market_data_provider="demo",
            job_execution_mode=job_execution_mode,
            job_simulation_latency_ms=job_simulation_latency_ms,
        )
        return TestClient(create_app(settings))

    def test_healthz_returns_ok(self) -> None:
        client = self._build_client()

        response = client.get("/healthz")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual("ok", payload["data"]["status"])

    def test_index_page_serves_web_app_shell(self) -> None:
        client = self._build_client()

        response = client.get("/")

        self.assertEqual(200, response.status_code)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("中国股票 / ETF 量化研究平台", response.text)

    def test_main_product_pages_are_accessible(self) -> None:
        client = self._build_client()

        strategy_response = client.get("/strategy")
        indicators_response = client.get("/indicators")
        rules_response = client.get("/rules")
        backtests_response = client.get("/backtests")
        replay_response = client.get("/replay")

        self.assertEqual(200, strategy_response.status_code)
        self.assertEqual(200, indicators_response.status_code)
        self.assertEqual(200, rules_response.status_code)
        self.assertEqual(200, backtests_response.status_code)
        self.assertEqual(200, replay_response.status_code)
        self.assertIn("策略工坊", strategy_response.text)
        self.assertIn("指标设置", indicators_response.text)
        self.assertIn("规则模块", rules_response.text)
        self.assertIn("回测中心", backtests_response.text)
        self.assertIn("交易复盘", replay_response.text)

    def test_generate_strategy_returns_structured_dsl(self) -> None:
        client = self._build_client()

        response = client.post(
            "/api/v1/strategies/generate",
            json={
                "prompt": "当 5 日均线上穿 20 日均线且成交量放大时做多",
                "market": "600519.SH",
                "timeframe": "1d",
                "asset_type": "stock",
                "preferences": {"side": "long"},
            },
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()["data"]
        self.assertIn("strategy_dsl", payload)
        self.assertEqual("600519.SH", payload["strategy_dsl"]["market"])
        self.assertEqual("1d", payload["strategy_dsl"]["timeframe"])
        self.assertTrue(payload["strategy_dsl"]["entry"]["all"])
        self.assertIn("def build_strategy()", payload["strategy_python"])

    def test_generate_strategy_teaching_mode_adds_comments_and_understands_terms(self) -> None:
        client = self._build_client()

        response = client.post(
            "/api/v1/strategies/generate",
            json={
                "prompt": "四连板后不追高，炸板回封后观察量价共振再考虑买入",
                "market": "600519.SH",
                "timeframe": "1d",
                "asset_type": "stock",
                "preferences": {"side": "long"},
                "teaching_mode": True,
            },
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()["data"]
        self.assertIn("#", payload["strategy_python"])
        self.assertTrue(any(item["term"] == "四连板" for item in payload["matched_terms"]))
        self.assertIn("教学模式已开启", payload["human_summary"])

    def test_custom_indicator_generate_save_and_match_in_strategy(self) -> None:
        client = self._build_client()

        generated = client.post(
            "/api/v1/indicators/custom/generate",
            json={"prompt": "生成一个量价共振指标，价格站上20日均线且成交量高于10日均量"},
        )
        self.assertEqual(200, generated.status_code)
        generated_payload = generated.json()["data"]

        created = client.post(
            "/api/v1/indicators/custom",
            json={
                "name": generated_payload["name"],
                "natural_language_prompt": generated_payload["natural_language_prompt"],
                "summary": generated_payload["summary"],
                "formula_text": generated_payload["formula_text"],
                "python_code": generated_payload["python_code"],
                "usage_hint": generated_payload["usage_hint"],
                "tags": generated_payload["tags"],
            },
        )
        self.assertEqual(200, created.status_code)

        listed = client.get("/api/v1/indicators/custom")
        self.assertEqual(200, listed.status_code)
        self.assertEqual(1, len(listed.json()["data"]["items"]))

        strategy = client.post(
            "/api/v1/strategies/generate",
            json={
                "prompt": f"当 {generated_payload['name']} 走强时买入",
                "market": "600519.SH",
                "timeframe": "1d",
                "asset_type": "stock",
                "preferences": {"side": "long"},
            },
        )
        self.assertEqual(200, strategy.status_code)
        strategy_payload = strategy.json()["data"]
        self.assertTrue(
            any(item["name"] == generated_payload["name"] for item in strategy_payload["matched_custom_indicators"])
        )

    def test_rules_endpoints_return_defaults_and_accept_custom_terms(self) -> None:
        client = self._build_client()

        defaults = client.get("/api/v1/rules/defaults")
        self.assertEqual(200, defaults.status_code)
        self.assertTrue(defaults.json()["data"]["items"])

        created = client.post(
            "/api/v1/rules/glossary",
            json={
                "term": "地天板",
                "meaning": "盘中从接近跌停拉到接近涨停的极端反转形态",
                "example": "地天板次日不追高",
            },
        )
        self.assertEqual(200, created.status_code)

        glossary = client.get("/api/v1/rules/glossary")
        self.assertEqual(200, glossary.status_code)
        items = glossary.json()["data"]["items"]
        self.assertTrue(any(item["term"] == "地天板" for item in items))

    def test_create_strategy_project_returns_project_and_version_ids(self) -> None:
        client = self._build_client()

        response = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "放量均线突破策略",
                "natural_language_prompt": "当 5 日均线上穿 20 日均线时做多",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertIn("project_id", data)
        self.assertIn("version_id", data)

    def test_list_strategy_projects_returns_created_items(self) -> None:
        client = self._build_client()

        client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "趋势策略",
                "natural_language_prompt": "价格突破前高且量能放大时做多",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        )

        response = client.get("/api/v1/strategies/projects")

        self.assertEqual(200, response.status_code)
        items = response.json()["data"]["items"]
        self.assertEqual(1, len(items))
        self.assertEqual("趋势策略", items[0]["title"])
        self.assertEqual("600519.SH", items[0]["strategy_dsl"]["market"])
        self.assertIn("def build_strategy()", items[0]["strategy_python"])

    def test_get_strategy_project_returns_python_code(self) -> None:
        client = self._build_client()
        created = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "ETF 趋势策略",
                "natural_language_prompt": "ETF 放量突破买入",
                "strategy_dsl": {"market": "510300.SH", "timeframe": "1d", "asset_type": "etf"},
                "strategy_python": "def build_strategy():\n    return {'asset_type': 'etf'}",
            },
        )
        version_id = created.json()["data"]["version_id"]

        response = client.get(f"/api/v1/strategies/projects/{version_id}")

        self.assertEqual(200, response.status_code)
        payload = response.json()["data"]
        self.assertEqual("ETF 趋势策略", payload["title"])
        self.assertIn("asset_type", payload["strategy_python"])

    def test_backtest_run_completes_and_returns_metrics(self) -> None:
        client = self._build_client()
        created_project = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "白酒趋势策略",
                "natural_language_prompt": "当 5 日均线上穿 20 日均线时做多",
                "strategy_dsl": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "entry": {"all": [{"indicator": "sma_cross", "params": {"fast": 5, "slow": 20}, "operator": "==", "value": True}]},
                    "exit": {"any": [{"indicator": "take_profit_pct", "operator": ">=", "value": 0.08}, {"indicator": "stop_loss_pct", "operator": "<=", "value": -0.03}]},
                    "position": {"side": "long", "max_positions": 1},
                },
                "strategy_python": "def build_strategy():\n    return {'market': '600519.SH'}",
            },
        )
        version_id = created_project.json()["data"]["version_id"]

        created = client.post(
            "/api/v1/backtests/runs",
            json={
                "strategy_version_id": version_id,
                "dataset": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "from": "2024-01-01T00:00:00Z",
                    "to": "2024-12-31T23:59:59Z",
                },
                "execution_contract": {
                    "initial_capital": 100000,
                    "fee_bps": 3,
                    "slippage_bps": 2,
                    "fill_price_rule": "next_bar_open",
                    "intrabar_match_policy": "no_intrabar_fill",
                    "calendar": "cn_a_share",
                    "timezone": "Asia/Shanghai",
                    "adjustment_mode": "qfq",
                },
                "data_snapshot": {"dataset_snapshot_ref": "snapshot_v1"},
            },
        )
        task_id = created.json()["data"]["backtest_run_id"]

        fetched = client.get(f"/api/v1/backtests/runs/{task_id}")

        self.assertEqual(200, fetched.status_code)
        data = fetched.json()["data"]
        self.assertEqual("completed", data["status"])
        self.assertEqual("snapshot_v1", data["dataset_snapshot_ref"])
        self.assertEqual("engine_v1", data["engine_version"])
        self.assertIn("data_source", data)
        self.assertIn("strategy_python", data)

    def test_list_backtest_runs_returns_history(self) -> None:
        client = self._build_client()
        created_project = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "ETF 回测策略",
                "natural_language_prompt": "当价格突破前高时买入",
                "strategy_dsl": {
                    "market": "510300.SH",
                    "timeframe": "1d",
                    "asset_type": "etf",
                    "entry": {"all": [{"indicator": "price_breakout", "params": {"lookback": 20}, "operator": "==", "value": True}]},
                    "exit": {"any": [{"indicator": "take_profit_pct", "operator": ">=", "value": 0.08}, {"indicator": "stop_loss_pct", "operator": "<=", "value": -0.03}]},
                    "position": {"side": "long", "max_positions": 1},
                },
                "strategy_python": "def build_strategy():\n    return {'market': '510300.SH'}",
            },
        )
        version_id = created_project.json()["data"]["version_id"]
        client.post(
            "/api/v1/backtests/runs",
            json={
                "strategy_version_id": version_id,
                "dataset": {
                    "market": "510300.SH",
                    "timeframe": "1d",
                    "asset_type": "etf",
                    "from": "2024-01-01T00:00:00Z",
                    "to": "2024-06-30T23:59:59Z",
                },
                "execution_contract": {
                    "initial_capital": 100000,
                    "fee_bps": 3,
                    "slippage_bps": 2,
                    "fill_price_rule": "next_bar_open",
                    "intrabar_match_policy": "no_intrabar_fill",
                    "calendar": "cn_a_share",
                    "timezone": "Asia/Shanghai",
                    "adjustment_mode": "qfq",
                },
                "data_snapshot": {"dataset_snapshot_ref": "snapshot_etf"},
            },
        )

        response = client.get("/api/v1/backtests/runs")

        self.assertEqual(200, response.status_code)
        items = response.json()["data"]["items"]
        self.assertEqual(1, len(items))
        self.assertEqual("510300.SH", items[0]["market"])
        self.assertEqual("ETF 回测策略", items[0]["strategy_title"])
        self.assertIn("created_at", items[0])

    def test_optimization_job_completes_and_returns_best_metrics(self) -> None:
        client = self._build_client()

        created = client.post(
            "/api/v1/optimization-jobs",
            json={
                "strategy_version_id": "ver_opt",
                "search_space": {
                    "entry.all[0].params.fast": [3, 5, 8],
                    "entry.all[0].params.slow": [15, 20, 30],
                },
                "objective": "profit_factor",
                "dataset": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "from": "2024-01-01T00:00:00Z",
                    "to": "2024-12-31T23:59:59Z",
                },
                "data_snapshot": {"dataset_snapshot_ref": "snapshot_v2"},
                "execution_contract": {
                    "initial_capital": 100000,
                    "fee_bps": 3,
                    "slippage_bps": 2,
                    "fill_price_rule": "next_bar_open",
                    "intrabar_match_policy": "no_intrabar_fill",
                    "calendar": "cn_a_share",
                    "timezone": "Asia/Shanghai",
                    "adjustment_mode": "qfq",
                },
            },
        )
        task_id = created.json()["data"]["job_id"]

        fetched = client.get(f"/api/v1/optimization-jobs/{task_id}")

        self.assertEqual(200, fetched.status_code)
        data = fetched.json()["data"]
        self.assertEqual("completed", data["status"])
        self.assertIn("profit_factor", data["best_metrics"])
        self.assertTrue(data["trials"])

    def test_replay_analysis_can_be_cancelled_in_background_mode(self) -> None:
        client = self._build_client(
            job_execution_mode="background",
            job_simulation_latency_ms=200,
        )

        created = client.post(
            "/api/v1/replays/analyses",
            json={
                "upload_id": "upload_001",
                "focus_dimensions": [
                    "volume_structure",
                    "moving_average_structure",
                ],
                "custom_prompt": "重点分析量价关系",
            },
        )
        task_id = created.json()["data"]["analysis_id"]

        cancelled = client.post(f"/api/v1/replays/analyses/{task_id}/cancel")
        time.sleep(0.3)
        fetched = client.get(f"/api/v1/replays/analyses/{task_id}")

        self.assertEqual(200, cancelled.status_code)
        self.assertEqual("cancelled", cancelled.json()["data"]["status"])
        self.assertEqual(200, fetched.status_code)
        self.assertEqual("cancelled", fetched.json()["data"]["status"])
        self.assertEqual("TASK_CANCELLED", fetched.json()["data"]["error"]["code"])

    def test_unknown_task_returns_not_found(self) -> None:
        client = self._build_client()

        response = client.get("/api/v1/backtests/runs/does-not-exist")

        self.assertEqual(404, response.status_code)
        self.assertEqual("TASK_NOT_FOUND", response.json()["detail"]["code"])

    def test_task_persists_across_app_restarts(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_url = f"sqlite+pysqlite:///{Path(temp_dir.name) / 'quant_platform.db'}"

        first_client = self._build_client(database_url=database_url)
        created_project = first_client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "持久化策略",
                "natural_language_prompt": "均线上穿时做多",
                "strategy_dsl": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "entry": {"all": [{"indicator": "sma_cross", "params": {"fast": 5, "slow": 20}, "operator": "==", "value": True}]},
                    "exit": {"any": [{"indicator": "take_profit_pct", "operator": ">=", "value": 0.08}, {"indicator": "stop_loss_pct", "operator": "<=", "value": -0.03}]},
                    "position": {"side": "long", "max_positions": 1},
                },
                "strategy_python": "def build_strategy():\n    return {'market': '600519.SH'}",
            },
        )
        version_id = created_project.json()["data"]["version_id"]
        created = first_client.post(
            "/api/v1/backtests/runs",
            json={
                "strategy_version_id": version_id,
                "dataset": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "from": "2024-01-01T00:00:00Z",
                    "to": "2024-12-31T23:59:59Z",
                },
                "execution_contract": {
                    "initial_capital": 100000,
                    "fee_bps": 3,
                    "slippage_bps": 2,
                    "fill_price_rule": "next_bar_open",
                    "intrabar_match_policy": "no_intrabar_fill",
                    "calendar": "cn_a_share",
                    "timezone": "Asia/Shanghai",
                    "adjustment_mode": "qfq",
                },
                "data_snapshot": {"dataset_snapshot_ref": "persisted_snapshot"},
            },
        )
        task_id = created.json()["data"]["backtest_run_id"]

        second_client = self._build_client(database_url=database_url)
        fetched = second_client.get(f"/api/v1/backtests/runs/{task_id}")

        self.assertEqual(200, fetched.status_code)
        self.assertEqual("completed", fetched.json()["data"]["status"])
        self.assertEqual(
            "persisted_snapshot",
            fetched.json()["data"]["dataset_snapshot_ref"],
        )

    def test_trade_upload_parse_and_record_listing_flow(self) -> None:
        client = self._build_client()
        csv_text = (
            "symbol,side,entry_time,exit_time,pnl\n"
            "BTCUSDT,long,2024-05-01T10:00:00Z,2024-05-01T12:00:00Z,120.5\n"
            "ETHUSDT,short,2024-05-02T09:00:00Z,2024-05-02T15:00:00Z,-45.2\n"
        )

        upload_response = client.post(
            "/api/v1/trades/uploads",
            files={
                "file": ("trades.csv", csv_text.encode("utf-8"), "text/csv"),
            },
        )

        self.assertEqual(200, upload_response.status_code)
        upload_data = upload_response.json()["data"]
        self.assertEqual(
            ["symbol", "side", "entry_time", "exit_time", "pnl"],
            upload_data["detected_columns"],
        )
        upload_id = upload_data["upload_id"]

        parse_response = client.post(
            f"/api/v1/trades/uploads/{upload_id}/parse",
            json={
                "column_mapping": {
                    "symbol": "symbol",
                    "side": "side",
                    "entry_time": "entry_time",
                    "exit_time": "exit_time",
                    "pnl": "pnl",
                }
            },
        )

        self.assertEqual(200, parse_response.status_code)
        parse_data = parse_response.json()["data"]
        self.assertEqual("parsed", parse_data["status"])
        self.assertEqual(2, parse_data["record_count"])

        records_response = client.get(f"/api/v1/trades/uploads/{upload_id}/records")

        self.assertEqual(200, records_response.status_code)
        items = records_response.json()["data"]["items"]
        self.assertEqual(2, len(items))
        self.assertEqual("BTCUSDT", items[0]["symbol"])
        self.assertEqual("short", items[1]["side"])

    def test_replay_analysis_uses_uploaded_trade_statistics(self) -> None:
        client = self._build_client()
        csv_text = (
            "symbol,side,entry_time,exit_time,pnl\n"
            "BTCUSDT,long,2024-05-01T10:00:00Z,2024-05-01T11:00:00Z,150\n"
            "ETHUSDT,short,2024-05-02T09:00:00Z,2024-05-02T14:00:00Z,-80\n"
            "SOLUSDT,long,2024-05-03T08:00:00Z,2024-05-03T10:30:00Z,60\n"
        )
        upload = client.post(
            "/api/v1/trades/uploads",
            files={"file": ("trades.csv", csv_text.encode("utf-8"), "text/csv")},
        ).json()["data"]
        upload_id = upload["upload_id"]
        client.post(
            f"/api/v1/trades/uploads/{upload_id}/parse",
            json={
                "column_mapping": {
                    "symbol": "symbol",
                    "side": "side",
                    "entry_time": "entry_time",
                    "exit_time": "exit_time",
                    "pnl": "pnl",
                }
            },
        )

        created = client.post(
            "/api/v1/replays/analyses",
            json={
                "upload_id": upload_id,
                "focus_dimensions": ["side_performance"],
                "custom_prompt": "找出表现更强的方向",
            },
        )
        analysis_id = created.json()["data"]["analysis_id"]

        fetched = client.get(f"/api/v1/replays/analyses/{analysis_id}")

        self.assertEqual(200, fetched.status_code)
        data = fetched.json()["data"]
        self.assertEqual("completed", data["status"])
        self.assertIn("本次复盘共分析 3 笔交易", data["summary"])
        self.assertEqual("long side performed better", data["winning_patterns"][0]["pattern"])
        self.assertTrue(data["suggestion_rules"])


if __name__ == "__main__":
    unittest.main()
