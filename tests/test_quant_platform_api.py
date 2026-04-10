from __future__ import annotations

import json
import sys
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch


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
    from PIL import Image, ImageDraw
    from quant_platform_api.models import AssistantResearchRequest
    from quant_platform_api.config import Settings
    from quant_platform_api.main import create_app
    from quant_platform_api.market_data import MarketBar, MinuteBar
    from quant_platform_api.models import MentorAskRequest, TradeRecordItem
    from quant_platform_api.services import (
        FinancialAssistantService,
        MentorService,
        _build_replay_counterfactual_cases,
        _build_replay_context_suggestions,
        _build_replay_fundamental_features,
        _build_replay_minute_context_features,
        _replay_trade_passes_filters,
        _rerun_replay_records_on_market_data,
    )
except ModuleNotFoundError:  # pragma: no cover - handled by skip
    TestClient = None
    Image = None
    ImageDraw = None
    AssistantResearchRequest = None
    Settings = None
    create_app = None
    MarketBar = None
    MinuteBar = None
    MentorAskRequest = None
    TradeRecordItem = None
    FinancialAssistantService = None
    MentorService = None
    _build_replay_counterfactual_cases = None
    _build_replay_context_suggestions = None
    _build_replay_minute_context_features = None
    _build_replay_fundamental_features = None
    _replay_trade_passes_filters = None
    _rerun_replay_records_on_market_data = None


@unittest.skipIf(TestClient is None, "FastAPI dependencies are unavailable")
class QuantPlatformApiTests(unittest.TestCase):
    def _build_trade_screenshot_bytes(self, text: str) -> bytes:
        image = Image.new("RGB", (900, 260), "white")
        draw = ImageDraw.Draw(image)
        draw.multiline_text((20, 20), text, fill="black", spacing=8)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _build_client(
        self,
        *,
        job_execution_mode: str = "immediate",
        job_simulation_latency_ms: int = 0,
        database_url: str | None = None,
        market_data_database_path: str | None = None,
        enable_default_accounts: bool = True,
        initial_admin_username: str = "",
        initial_admin_contact: str = "",
        initial_admin_password: str = "",
        session_cookie_secure: bool = False,
        session_cookie_domain: str = "",
        session_cookie_samesite: str = "lax",
        llm_base_url: str = "",
        llm_api_key: str = "",
        llm_model_mentor: str = "",
    ) -> TestClient:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        if database_url is None:
            database_url = f"sqlite+pysqlite:///{Path(temp_dir.name) / 'quant_platform.db'}"
        if market_data_database_path is None:
            market_data_database_path = str(Path(temp_dir.name) / "market_data.db")

        settings = Settings(
            database_url=database_url,
            market_data_database_path=market_data_database_path,
            market_data_provider="demo",
            job_execution_mode=job_execution_mode,
            job_simulation_latency_ms=job_simulation_latency_ms,
            enable_default_accounts=enable_default_accounts,
            initial_admin_username=initial_admin_username,
            initial_admin_contact=initial_admin_contact,
            initial_admin_password=initial_admin_password,
            session_cookie_secure=session_cookie_secure,
            session_cookie_domain=session_cookie_domain,
            session_cookie_samesite=session_cookie_samesite,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model_mentor=llm_model_mentor,
        )
        return TestClient(create_app(settings))

    def _login(
        self,
        client: TestClient,
        *,
        username: str = "1111",
        password: str = "618618",
    ):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(200, response.status_code)
        return response

    def _register_and_login(
        self,
        client: TestClient,
        *,
        username: str,
        contact: str,
        password: str = "618618",
    ):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "contact": contact,
                "password": password,
            },
        )
        self.assertEqual(200, response.status_code)
        return response

    def test_healthz_returns_ok(self) -> None:
        client = self._build_client()

        response = client.get("/healthz", headers={"X-Request-Id": "req_healthz_test"})

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual("req_healthz_test", payload["request_id"])
        self.assertEqual("req_healthz_test", response.headers["X-Request-Id"])
        self.assertEqual("ok", payload["data"]["status"])
        self.assertEqual("development", payload["data"]["app_env"])
        self.assertEqual("sqlite", payload["data"]["database_backend"])
        self.assertFalse(payload["data"]["redis_configured"])
        self.assertFalse(payload["data"]["minio_configured"])
        self.assertFalse(payload["data"]["llm_configured"])
        self.assertTrue(payload["data"]["default_accounts_enabled"])
        self.assertFalse(payload["data"]["session_cookie_secure"])

    def test_production_profile_disables_default_accounts_and_uses_secure_cookie(self) -> None:
        client = self._build_client(
            enable_default_accounts=False,
            initial_admin_username="owner",
            initial_admin_contact="owner@example.com",
            initial_admin_password="OwnerPass618",
            session_cookie_secure=True,
            session_cookie_domain="quant.example.com",
            session_cookie_samesite="strict",
        )

        healthz_response = client.get("/healthz")
        denied_response = client.post(
            "/api/v1/auth/login",
            json={"username": "1111", "password": "618618"},
        )
        login_response = client.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": "OwnerPass618"},
        )

        self.assertEqual(200, healthz_response.status_code)
        self.assertFalse(healthz_response.json()["data"]["default_accounts_enabled"])
        self.assertTrue(healthz_response.json()["data"]["session_cookie_secure"])
        self.assertEqual(403, denied_response.status_code)
        self.assertEqual("FORBIDDEN", denied_response.json()["error"]["code"])
        self.assertEqual(200, login_response.status_code)
        set_cookie = login_response.headers["set-cookie"]
        self.assertIn("Secure", set_cookie)
        self.assertIn("Domain=quant.example.com", set_cookie)
        self.assertIn("SameSite=strict", set_cookie)

    def test_initial_admin_seed_skips_duplicate_contact(self) -> None:
        client = self._build_client(
            enable_default_accounts=True,
            initial_admin_username="platform_admin",
            initial_admin_contact="admin@example.com",
            initial_admin_password="ChangeMe_618618",
        )

        default_admin_login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "618618"},
        )
        custom_admin_login = client.post(
            "/api/v1/auth/login",
            json={"username": "platform_admin", "password": "ChangeMe_618618"},
        )

        self.assertEqual(200, default_admin_login.status_code)
        self.assertEqual(403, custom_admin_login.status_code)
        self.assertEqual("FORBIDDEN", custom_admin_login.json()["error"]["code"])

    def test_index_page_serves_web_app_shell(self) -> None:
        client = self._build_client()

        response = client.get("/")

        self.assertEqual(200, response.status_code)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("量化研究平台", response.text)
        self.assertNotIn("中国股票 / ETF 量化研究平台", response.text)
        self.assertIn("在统一研究工作流中管理策略、回测与交易复盘。", response.text)
        self.assertIn("首页", response.text)

    def test_public_auth_pages_are_accessible(self) -> None:
        client = self._build_client()

        login_response = client.get("/login")
        register_response = client.get("/register")

        self.assertEqual(200, login_response.status_code)
        self.assertEqual(200, register_response.status_code)
        self.assertIn("登录后进入你的量化研究工作台", login_response.text)
        self.assertIn("创建账户后直接进入你的用户工作台", register_response.text)
        self.assertNotIn("访问说明", login_response.text)
        self.assertNotIn("默认测试账户", login_response.text)
        self.assertNotIn("用户名 `1111`", login_response.text)
        self.assertNotIn("用户名 `admin`", login_response.text)

    def test_home_page_does_not_publicly_show_default_accounts(self) -> None:
        client = self._build_client()

        response = client.get("/")

        self.assertEqual(200, response.status_code)
        self.assertNotIn("默认测试账户", response.text)
        self.assertNotIn("用户名 `1111`", response.text)
        self.assertNotIn("用户名 `admin`", response.text)

    def test_protected_pages_redirect_to_login_when_unauthenticated(self) -> None:
        client = self._build_client()

        for path in ["/workspace", "/admin", "/strategy", "/indicators", "/rules", "/mentor", "/assistant", "/backtests", "/replay"]:
            response = client.get(path, follow_redirects=False)
            self.assertEqual(302, response.status_code)
            self.assertEqual(f"/login?next={path}", response.headers["location"])

    def test_default_user_can_login_and_access_workspace(self) -> None:
        client = self._build_client()

        login_response = self._login(client, username="1111", password="618618")
        workspace_response = client.get("/workspace")
        me_response = client.get("/api/v1/auth/me")

        self.assertIn("quant_session", login_response.cookies)
        self.assertEqual(200, workspace_response.status_code)
        self.assertIn("用户工作台", workspace_response.text)
        self.assertEqual(200, me_response.status_code)
        self.assertEqual("1111", me_response.json()["data"]["username"])
        self.assertEqual("user", me_response.json()["data"]["role"])
        self.assertEqual("active", me_response.json()["data"]["status"])
        self.assertTrue(me_response.json()["data"]["workspace_id"].startswith("ws_"))

    def test_admin_page_requires_admin_role(self) -> None:
        client = self._build_client()
        self._login(client, username="1111", password="618618")

        page_response = client.get("/admin", follow_redirects=False)
        api_response = client.get("/api/v1/admin/summary")

        self.assertEqual(302, page_response.status_code)
        self.assertEqual("/workspace", page_response.headers["location"])
        self.assertEqual(403, api_response.status_code)
        self.assertEqual("FORBIDDEN", api_response.json()["error"]["code"])

    def test_admin_console_page_is_accessible_for_admin(self) -> None:
        client = self._build_client()
        self._login(client, username="admin", password="618618")

        response = client.get("/admin")

        self.assertEqual(200, response.status_code)
        self.assertIn("管理后台", response.text)
        self.assertIn("用户管理", response.text)
        self.assertIn("任务审计", response.text)
        self.assertIn("登录安全", response.text)
        self.assertIn("管理员审计日志", response.text)
        self.assertIn("用户报错与应用日志", response.text)

    def test_strategy_page_shows_multi_market_and_multi_timeframe_controls(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/strategy")

        self.assertEqual(200, response.status_code)
        self.assertIn("市场范围", response.text)
        self.assertIn("混合周期观察层", response.text)
        self.assertIn("加密货币", response.text)
        self.assertIn("伦敦金", response.text)
        self.assertIn("策略名称", response.text)
        self.assertIn("版本标签", response.text)
        self.assertIn('id="project-version-label"', response.text)
        self.assertIn('id="project-title"', response.text)
        self.assertIn("系统版本ID将在保存后生成", response.text)
        self.assertIn("当前能力声明", response.text)
        self.assertIn("市场支持状态", response.text)
        self.assertIn("区分“可描述”和“可真实执行”", response.text)
        self.assertIn('id="save-project-btn" class="btn disabled" disabled', response.text)
        self.assertIn('id="go-backtests-link" class="btn disabled"', response.text)

    def test_indicators_page_uses_progressive_save_button_state(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/indicators")

        self.assertEqual(200, response.status_code)
        self.assertIn("生成自定义指标", response.text)
        self.assertIn('id="save-custom-indicator-btn" class="btn disabled" disabled', response.text)

    def test_backtests_page_shows_config_and_snapshot_sections(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/backtests")

        self.assertEqual(200, response.status_code)
        self.assertIn("回测配置摘要", response.text)
        self.assertIn("数据快照摘要", response.text)
        self.assertIn("执行可信度说明", response.text)
        self.assertIn("本次回测支持范围", response.text)
        self.assertIn("平台当前已开放与未开放能力", response.text)
        self.assertIn("仓位模式", response.text)
        self.assertIn("最大回撤保护", response.text)
        self.assertIn("盘中撮合策略", response.text)
        self.assertIn("市场成交约束", response.text)
        self.assertIn("滑点说明", response.text)
        self.assertIn("盘中撮合策略说明", response.text)
        self.assertIn("预热Bar数说明", response.text)
        self.assertIn("最大回撤保护说明", response.text)
        self.assertIn("最大持有Bar数说明", response.text)
        self.assertIn("回测曲线", response.text)
        self.assertIn("成交明细", response.text)
        self.assertIn("实验 / 回测对比", response.text)
        self.assertIn("对比已选回测", response.text)
        self.assertIn("执行配置差异", response.text)
        self.assertIn("数据快照差异", response.text)
        self.assertIn('id="run-backtest-panel"', response.text)
        self.assertIn('id="backtest-history-panel"', response.text)
        self.assertLess(response.text.index("回测曲线"), response.text.index("成交明细"))
        self.assertLess(response.text.index("成交明细"), response.text.index("回测配置摘要"))

    def test_platform_capabilities_endpoint_returns_market_matrix(self) -> None:
        client = self._build_client()

        response = client.get("/api/v1/platform/capabilities")

        self.assertEqual(200, response.status_code)
        items = response.json()["data"]["items"]
        self.assertEqual(4, len(items))
        cn_equity = next(item for item in items if item["market_scope"] == "cn_equity")
        us_equity = next(item for item in items if item["market_scope"] == "us_equity")
        self.assertEqual("supported", cn_equity["backtest_status"])
        self.assertEqual("unsupported", us_equity["backtest_status"])
        self.assertIn("真实日线回测", cn_equity["backtest_label"])

    def test_backtest_run_rejects_market_scope_without_real_backtest_support(self) -> None:
        client = self._build_client()
        self._login(client)
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "美股研究策略",
                "version_label": "语义研究版",
                "natural_language_prompt": "美股日线突破时买入",
                "strategy_dsl": {
                    "market_scope": "us_equity",
                    "market_scope_label": "美股",
                    "market": "AAPL",
                    "timeframe": "1d",
                    "timeframes": ["1d"],
                    "analysis_mode": "single_timeframe",
                    "asset_type": "stock",
                    "entry": {"all": []},
                    "exit": {"any": []},
                    "position": {"side": "long", "max_positions": 1},
                },
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]

        response = client.post(
            "/api/v1/backtests/runs",
            json={
                "strategy_version_id": version_id,
                "dataset": {
                    "market": "AAPL",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "from": "2024-01-01T00:00:00Z",
                    "to": "2024-12-31T00:00:00Z",
                },
                "execution_contract": {
                    "initial_capital": 100000,
                    "fee_bps": 3,
                    "slippage_bps": 2,
                    "fill_price_rule": "next_bar_open",
                    "intrabar_match_policy": "no_intrabar_fill",
                    "calendar": "us_equity",
                    "timezone": "America/New_York",
                    "adjustment_mode": "raw",
                },
                "data_snapshot": {"dataset_snapshot_ref": "aapl_2024_daily"},
            },
        )

        self.assertEqual(400, response.status_code)
        payload = response.json()
        self.assertEqual("INVALID_ARGUMENT", payload["error"]["code"])
        self.assertIn("暂不开放真实回测", payload["error"]["message"])

    def test_rules_page_uses_collapsible_default_rule_container(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/rules")

        self.assertEqual(200, response.status_code)
        self.assertIn('id="default-rules" class="accordion-list empty-state"', response.text)
        self.assertIn('id="save-default-rules-btn" class="btn disabled" disabled', response.text)
        self.assertIn('id="save-glossary-btn" class="btn disabled" disabled', response.text)

    def test_replay_page_uses_progressive_action_buttons(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/replay")

        self.assertEqual(200, response.status_code)
        self.assertIn('id="add-manual-trade-btn" class="btn disabled"', response.text)
        self.assertIn('id="upload-trades-btn" class="btn disabled" disabled', response.text)
        self.assertIn('id="upload-screenshot-btn" class="btn disabled"', response.text)
        self.assertIn('id="upload-manual-btn" class="btn disabled"', response.text)
        self.assertIn('id="run-replay-btn" class="btn secondary disabled" disabled', response.text)
        self.assertIn('id="source-mode-title">CSV 导入</strong>', response.text)
        self.assertIn('id="source-panel-screenshot" class="source-panel" hidden', response.text)
        self.assertIn('id="source-panel-manual" class="source-panel" hidden', response.text)
        self.assertIn('id="source-mode-intro" class="muted-note">适合直接上传券商导出的 CSV', response.text)
        self.assertIn('id="source-mode-steps" class="source-mode-step-list"', response.text)
        self.assertIn('id="ocr-screenshot-btn" class="btn disabled"', response.text)
        self.assertIn('id="screenshot-ocr-summary" class="result-box light"', response.text)

    def test_mentor_page_is_available_after_login(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/mentor")

        self.assertEqual(200, response.status_code)
        self.assertIn("金融导师", response.text)
        self.assertIn("先把交易逻辑讲明白，再带你用平台做验证", response.text)
        self.assertIn('id="mentor-ask-btn" class="btn disabled" disabled', response.text)
        self.assertIn('id="mentor-followup-btn" class="btn disabled" disabled', response.text)

    def test_assistant_page_is_available_after_login(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/assistant")

        self.assertEqual(200, response.status_code)
        self.assertIn("金融助手", response.text)
        self.assertIn("多专家研究协作台", response.text)
        self.assertIn('id="assistant-run-btn" class="btn disabled" disabled', response.text)
        self.assertIn('id="assistant-followup-btn" class="btn disabled" disabled', response.text)
        self.assertIn("继续细化研究", response.text)

    def test_admin_can_login_and_access_workspace(self) -> None:
        client = self._build_client()

        self._login(client, username="admin", password="618618")
        me_response = client.get("/api/v1/auth/me")

        self.assertEqual(200, me_response.status_code)
        self.assertEqual("admin", me_response.json()["data"]["username"])
        self.assertEqual("admin", me_response.json()["data"]["role"])

    def test_admin_summary_exposes_platform_metrics_and_users(self) -> None:
        client = self._build_client()
        self._login(client, username="admin", password="618618")
        client.post(
            "/api/v1/auth/register",
            json={
                "username": "operator",
                "contact": "operator@example.com",
                "password": "618618",
            },
        )
        client.post("/api/v1/auth/logout")
        self._login(client, username="operator", password="618618")
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "管理员汇总策略",
                "natural_language_prompt": "均线上穿时买入",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]
        client.post(
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
                "data_snapshot": {"dataset_snapshot_ref": "admin_snapshot"},
            },
        )
        client.post("/api/v1/auth/logout")
        self._login(client, username="admin", password="618618")

        summary = client.get("/api/v1/admin/summary")
        users = client.get("/api/v1/admin/users")

        self.assertEqual(200, summary.status_code)
        self.assertEqual(200, users.status_code)
        data = summary.json()["data"]
        self.assertGreaterEqual(data["counts"]["users"], 3)
        self.assertGreaterEqual(data["counts"]["admins"], 1)
        self.assertIn("failed_logins_24h", data["counts"])
        self.assertGreaterEqual(data["counts"]["projects"], 1)
        self.assertGreaterEqual(data["counts"]["backtests"], 1)
        self.assertTrue(data["recent_tasks"])
        self.assertTrue(any(item["label"] == "管理员" for item in data["role_distribution"]))
        self.assertTrue(any(item["dataset_snapshot_ref"] == "admin_snapshot" for item in data["snapshot_states"]))
        self.assertIn("recent_audit_logs", data)
        self.assertIn("recent_security_events", data)
        listed_users = users.json()["data"]["items"]
        self.assertTrue(any(item["username"] == "operator" for item in listed_users))
        self.assertTrue(any(item["role"] == "admin" for item in listed_users))

    def test_admin_summary_handles_legacy_task_status_and_naive_event_timestamps(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_path = Path(temp_dir.name) / "quant_platform.db"
        market_data_path = Path(temp_dir.name) / "market_data.db"
        database_url = f"sqlite+pysqlite:///{database_path}"
        client = self._build_client(
            database_url=database_url,
            market_data_database_path=str(market_data_path),
        )

        self._login(client, username="admin", password="618618")
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "旧任务兼容策略",
                "version_label": "旧状态验证版",
                "natural_language_prompt": "5日均线上穿20日均线时买入",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]
        run_response = client.post(
            "/api/v1/backtests/runs",
            json={
                "strategy_version_id": version_id,
                "dataset": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "from": "2024-01-01T00:00:00Z",
                    "to": "2024-06-30T00:00:00Z",
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
                "data_snapshot": {"dataset_snapshot_ref": "legacy_snapshot"},
            },
        )
        self.assertIn(run_response.status_code, {200, 202})
        client.post(
            "/api/v1/client-errors",
            json={
                "message": "旧时间格式兼容验证",
                "category": "client_runtime_error",
                "request_path": "/mentor",
                "details": {"scenario": "legacy_timestamp"},
            },
        )

        legacy_recent_timestamp = (
            datetime.now() - timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S.%f")

        with sqlite3.connect(database_path) as connection:
            connection.execute("update tasks set status = 'completed' where kind = 'backtest'")
            connection.execute(
                "update auth_events set created_at = ? where event_type = 'login'",
                (legacy_recent_timestamp,),
            )
            connection.execute(
                "update application_logs set created_at = ? where message = ?",
                (legacy_recent_timestamp, "旧时间格式兼容验证"),
            )
            connection.commit()

        summary = client.get("/api/v1/admin/summary")

        self.assertEqual(200, summary.status_code)
        payload = summary.json()["data"]
        self.assertGreaterEqual(payload["counts"]["backtests"], 1)
        self.assertGreaterEqual(payload["counts"]["app_errors_24h"], 1)
        self.assertTrue(payload["recent_tasks"])

    def test_admin_can_update_user_role_but_cannot_demote_self(self) -> None:
        client = self._build_client()
        self._login(client, username="admin", password="618618")
        created = client.post(
            "/api/v1/auth/register",
            json={
                "username": "reviewer",
                "contact": "reviewer@example.com",
                "password": "618618",
            },
        )
        created_user_id = created.json()["data"]["user_id"]
        client.post("/api/v1/auth/logout")
        self._login(client, username="admin", password="618618")

        promote = client.put(
            f"/api/v1/admin/users/{created_user_id}/role",
            json={"role": "admin"},
        )
        me = client.get("/api/v1/auth/me").json()["data"]
        self_demote = client.put(
            f"/api/v1/admin/users/{me['user_id']}/role",
            json={"role": "user"},
        )

        self.assertEqual(200, promote.status_code)
        self.assertEqual("admin", promote.json()["data"]["role"])
        self.assertEqual(409, self_demote.status_code)
        self.assertEqual("STATE_CONFLICT", self_demote.json()["error"]["code"])

    def test_admin_can_suspend_and_reactivate_user(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_url = f"sqlite+pysqlite:///{Path(temp_dir.name) / 'quant_platform.db'}"
        market_data_database_path = str(Path(temp_dir.name) / "market_data.db")
        admin_client = self._build_client(
            database_url=database_url,
            market_data_database_path=market_data_database_path,
        )
        user_client = self._build_client(
            database_url=database_url,
            market_data_database_path=market_data_database_path,
        )

        self._login(admin_client, username="admin", password="618618")
        created = admin_client.post(
            "/api/v1/auth/register",
            json={
                "username": "suspend_me",
                "contact": "suspend@example.com",
                "password": "618618",
            },
        )
        user_id = created.json()["data"]["user_id"]
        admin_client.post("/api/v1/auth/logout")
        self._login(admin_client, username="admin", password="618618")
        user_client.post(
            "/api/v1/auth/login",
            json={"username": "suspend_me", "password": "618618"},
        )
        suspend = admin_client.put(
            f"/api/v1/admin/users/{user_id}/status",
            json={"status": "suspended", "reason": "manual review"},
        )
        me_after_suspend = user_client.get("/api/v1/auth/me")
        login_after_suspend = user_client.post(
            "/api/v1/auth/login",
            json={"username": "suspend_me", "password": "618618"},
        )
        reactivate = admin_client.put(
            f"/api/v1/admin/users/{user_id}/status",
            json={"status": "active", "reason": "restored"},
        )
        login_after_reactivate = user_client.post(
            "/api/v1/auth/login",
            json={"username": "suspend_me", "password": "618618"},
        )

        self.assertEqual(200, suspend.status_code)
        self.assertEqual("suspended", suspend.json()["data"]["status"])
        self.assertEqual(401, me_after_suspend.status_code)
        self.assertEqual(403, login_after_suspend.status_code)
        self.assertEqual("FORBIDDEN", login_after_suspend.json()["error"]["code"])
        self.assertEqual(200, reactivate.status_code)
        self.assertEqual("active", reactivate.json()["data"]["status"])
        self.assertEqual(200, login_after_reactivate.status_code)

    def test_admin_can_reset_password_and_old_password_stops_working(self) -> None:
        client = self._build_client()
        self._login(client, username="admin", password="618618")
        created = client.post(
            "/api/v1/auth/register",
            json={
                "username": "reset_me",
                "contact": "reset@example.com",
                "password": "618618",
            },
        )
        user_id = created.json()["data"]["user_id"]
        client.post("/api/v1/auth/logout")
        self._login(client, username="admin", password="618618")
        reset = client.post(
            f"/api/v1/admin/users/{user_id}/reset-password",
            json={"new_password": "987654"},
        )
        old_login = client.post(
            "/api/v1/auth/login",
            json={"username": "reset_me", "password": "618618"},
        )
        new_login = client.post(
            "/api/v1/auth/login",
            json={"username": "reset_me", "password": "987654"},
        )

        self.assertEqual(200, reset.status_code)
        self.assertTrue(reset.json()["data"]["password_reset"])
        self.assertEqual(403, old_login.status_code)
        self.assertEqual(200, new_login.status_code)

    def test_admin_can_view_audit_logs_and_security_events(self) -> None:
        client = self._build_client()
        self._login(client, username="admin", password="618618")
        created = client.post(
            "/api/v1/auth/register",
            json={
                "username": "audit_target",
                "contact": "audit@example.com",
                "password": "618618",
            },
        )
        user_id = created.json()["data"]["user_id"]
        client.post("/api/v1/auth/logout")
        client.post(
            "/api/v1/auth/login",
            json={"username": "audit_target", "password": "wrong-pass"},
        )
        self._login(client, username="admin", password="618618")
        client.put(
            f"/api/v1/admin/users/{user_id}/status",
            json={"status": "suspended", "reason": "security check"},
        )

        audit_logs = client.get("/api/v1/admin/audit-logs")
        security_events = client.get("/api/v1/admin/security-events")

        self.assertEqual(200, audit_logs.status_code)
        self.assertEqual(200, security_events.status_code)
        self.assertTrue(
            any(
                item["action"] == "user.status_updated"
                for item in audit_logs.json()["data"]["items"]
            )
        )
        self.assertTrue(
            any(
                item["event_type"] == "login" and item["outcome"] == "failed"
                for item in security_events.json()["data"]["items"]
            )
        )

    def test_register_logs_in_new_user_and_logout_clears_session(self) -> None:
        client = self._build_client()

        register_response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "demo_user",
                "contact": "demo@example.com",
                "password": "618618",
            },
        )
        me_response = client.get("/api/v1/auth/me")
        logout_response = client.post("/api/v1/auth/logout")
        me_after_logout = client.get("/api/v1/auth/me")

        self.assertEqual(200, register_response.status_code)
        self.assertEqual("demo_user", register_response.json()["data"]["username"])
        self.assertIn("quant_session", register_response.cookies)
        self.assertEqual(200, me_response.status_code)
        self.assertEqual("demo_user", me_response.json()["data"]["username"])
        self.assertEqual(200, logout_response.status_code)
        self.assertEqual(401, me_after_logout.status_code)
        self.assertEqual("UNAUTHORIZED", me_after_logout.json()["error"]["code"])

    def test_login_with_invalid_password_returns_forbidden(self) -> None:
        client = self._build_client()

        response = client.post(
            "/api/v1/auth/login",
            json={"username": "1111", "password": "wrong-password"},
        )

        self.assertEqual(403, response.status_code)
        self.assertEqual("FORBIDDEN", response.json()["error"]["code"])

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
        self.assertEqual("cn_equity", payload["strategy_dsl"]["market_scope"])
        self.assertEqual(["1d"], payload["strategy_dsl"]["timeframes"])
        self.assertTrue(payload["strategy_dsl"]["entry"]["all"])
        self.assertIn("def build_strategy()", payload["strategy_python"])

    def test_generate_strategy_supports_multi_market_and_mixed_timeframes(self) -> None:
        client = self._build_client()

        response = client.post(
            "/api/v1/strategies/generate",
            json={
                "prompt": "昨日最低价小于10日均线，昨日收盘价大于10日均线，今日15分钟KDJ金叉时买入；当现价低于15分钟60均线时卖出。",
                "market_scope": "us_equity",
                "market": "AAPL",
                "timeframe": "15m",
                "timeframes": ["15m", "1d", "1w"],
                "asset_type": "stock",
                "preferences": {"side": "long"},
            },
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()["data"]
        strategy_dsl = payload["strategy_dsl"]
        self.assertEqual("us_equity", strategy_dsl["market_scope"])
        self.assertEqual("AAPL", strategy_dsl["market"])
        self.assertEqual("15m", strategy_dsl["timeframe"])
        self.assertEqual(["15m", "1d", "1w"], strategy_dsl["timeframes"])
        self.assertEqual("multi_timeframe", strategy_dsl["analysis_mode"])
        self.assertEqual("1d", strategy_dsl["backtest_timeframe"])
        self.assertTrue(any(item["expression"] == "昨日最低价小于10日均线" for item in strategy_dsl["entry_context"]))
        self.assertTrue(any(item["expression"] == "昨日收盘价大于10日均线" for item in strategy_dsl["entry_context"]))
        self.assertTrue(any("KDJ金叉" in item["expression"] for item in strategy_dsl["entry_context"]))
        self.assertTrue(any("60均线" in item["expression"] for item in strategy_dsl["exit_context"]))
        self.assertIn("混合周期条件", payload["human_summary"])
        self.assertTrue(any("混合周期策略" in item for item in payload["ambiguities"]))

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

    def test_builtin_indicator_endpoint_includes_common_indicators(self) -> None:
        client = self._build_client()

        response = client.get("/api/v1/indicators/builtin")

        self.assertEqual(200, response.status_code)
        items = response.json()["data"]["items"]
        indicator_keys = {item["indicator_key"] for item in items}
        self.assertIn("atr", indicator_keys)
        self.assertIn("adx", indicator_keys)
        self.assertIn("kdj", indicator_keys)
        self.assertIn("cci", indicator_keys)
        self.assertIn("williams_r", indicator_keys)
        self.assertIn("obv", indicator_keys)
        self.assertIn("vwap", indicator_keys)

    def test_rules_endpoints_return_defaults_and_accept_custom_terms(self) -> None:
        client = self._build_client()

        defaults = client.get("/api/v1/rules/defaults")
        self.assertEqual(200, defaults.status_code)
        default_items = defaults.json()["data"]["items"]
        self.assertTrue(default_items)
        self.assertTrue(any(item["section"] == "A股默认研究规则" for item in default_items))
        self.assertTrue(any(item["section"] == "美股默认研究规则" for item in default_items))
        self.assertTrue(any(item["section"] == "加密货币默认研究规则" for item in default_items))
        self.assertTrue(any(item["section"] == "伦敦金默认研究规则" for item in default_items))

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

    def test_default_rules_can_be_updated_after_login(self) -> None:
        client = self._build_client()
        self._login(client)

        updated = client.put(
            "/api/v1/rules/defaults",
            json={
                "items": [
                    {
                        "section_id": "rule_cn_equity",
                        "section": "A股默认研究规则",
                        "items": [
                            {
                                "title": "执行参数按平台设置决定",
                                "description": "默认周期、复权和成交方式应以当前平台设置和策略设置为准，而不是固定写死为日线前复权次日开盘成交。",
                            }
                        ],
                    },
                    {
                        "section_id": "rule_crypto",
                        "section": "加密货币默认研究规则",
                        "items": [
                            {
                                "title": "允许分钟级执行",
                                "description": "如果执行层支持，分钟级信号可以在盘中触发和成交。",
                            }
                        ],
                    },
                ]
            },
        )

        self.assertEqual(200, updated.status_code)
        self.assertEqual("1111", updated.json()["data"]["updated_by"])

        listed = client.get("/api/v1/rules/defaults")
        self.assertEqual(200, listed.status_code)
        items = listed.json()["data"]["items"]
        self.assertTrue(any(section["section"] == "A股默认研究规则" for section in items))
        self.assertTrue(
            any(
                rule["title"] == "执行参数按平台设置决定"
                for section in items
                for rule in section["items"]
            )
        )

    def test_default_rules_can_be_reset_to_platform_defaults(self) -> None:
        client = self._build_client()
        self._login(client)

        client.put(
            "/api/v1/rules/defaults",
            json={
                "items": [
                    {
                        "section_id": "rule_cn_equity",
                        "section": "A股默认研究规则",
                        "items": [
                            {
                                "title": "临时规则",
                                "description": "临时描述",
                            }
                        ],
                    }
                ]
            },
        )

        reset_response = client.post("/api/v1/rules/defaults/reset")

        self.assertEqual(200, reset_response.status_code)
        items = reset_response.json()["data"]["items"]
        self.assertTrue(
            any(
                rule["title"] == "默认执行参数应视平台设置和策略设置而定"
                for section in items
                for rule in section["items"]
            )
        )
        self.assertFalse(
            any(
                rule["title"] == "临时规则"
                for section in items
                for rule in section["items"]
            )
        )

    def test_rules_page_reflects_multi_market_copy(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/rules")

        self.assertEqual(200, response.status_code)
        self.assertIn("多市场默认研究规则与 AI 术语理解库", response.text)
        self.assertIn("统一管理多市场默认研究规则和术语库", response.text)
        self.assertIn("保存默认规则", response.text)
        self.assertIn("恢复平台默认值", response.text)

    def test_mentor_endpoints_return_topics_and_structured_answer(self) -> None:
        client = self._build_client()
        self._login(client)

        topics_response = client.get("/api/v1/mentor/topics")
        answer_response = client.post(
            "/api/v1/mentor/ask",
            json={
                "question": "A股能不能像加密货币一样直接做空？我这种新手应该先看什么？",
                "experience_level": "beginner",
                "market_scope": "cn_equity",
                "current_module": "mentor",
            },
        )

        self.assertEqual(200, topics_response.status_code)
        self.assertTrue(topics_response.json()["data"]["items"])
        self.assertEqual(200, answer_response.status_code)
        data = answer_response.json()["data"]
        self.assertEqual("金融导师", data["mentor_name"])
        self.assertEqual("market_constraints", data["topic"])
        self.assertIn("A股现货股票", data["answer"])
        self.assertTrue(data["action_plan"])
        self.assertTrue(any(item["path"] == "/rules" for item in data["related_modules"]))

    def test_mentor_followup_uses_conversation_history_for_further_explanation(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/mentor/ask",
            json={
                "question": "还是不太明白，能不能再解释一下回测结果应该先看什么？",
                "experience_level": "beginner",
                "market_scope": "cn_equity",
                "current_module": "mentor",
                "conversation_history": [
                    {"role": "user", "content": "回测结果里我应该先看哪些指标？"},
                    {"role": "assistant", "content": "先看最大回撤和交易次数，再看收益率。"},
                ],
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertTrue(data["is_follow_up"])
        self.assertEqual("backtest_reading", data["topic"])
        self.assertIn("再具体一点", data["answer"])

    def test_mentor_detailed_indicator_followup_is_not_mechanical_without_llm(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/mentor/ask",
            json={
                "question": "能不能更详细精准地讲一下这些指标的具体含义、构造逻辑和为什么有效？",
                "experience_level": "beginner",
                "market_scope": "cn_equity",
                "current_module": "mentor",
                "conversation_history": [
                    {"role": "user", "content": "均线、MACD、RSI 这些技术指标分别适合看什么？新手应该怎么学？"},
                    {"role": "assistant", "content": "先分清趋势指标、动量指标和波动指标。"},
                ],
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual("fallback", data["answer_source"])
        self.assertIn("均线的本质", data["answer"])
        self.assertIn("MACD 的本质", data["answer"])
        self.assertIn("RSI 的本质", data["answer"])
        self.assertEqual("平台导师兜底", data["answer_mode_label"])

    def test_assistant_endpoints_return_workflows_and_structured_analysis(self) -> None:
        client = self._build_client()
        self._login(client)

        workflows_response = client.get("/api/v1/assistant/workflows")
        analyze_response = client.post(
            "/api/v1/assistant/analyze",
            json={
                "query": "请按公司深研模式梳理 600519.SH 的盈利驱动、潜在催化剂与关键风险。",
                "workflow_id": "company_deep_dive",
                "target_symbol": "600519.SH",
                "market_scope": "cn_equity",
                "research_depth": "standard",
                "current_module": "assistant",
            },
        )

        self.assertEqual(200, workflows_response.status_code)
        workflows = workflows_response.json()["data"]
        self.assertTrue(workflows["items"])
        self.assertTrue(workflows["desks"])
        self.assertEqual(200, analyze_response.status_code)
        data = analyze_response.json()["data"]
        self.assertEqual("金融助手", data["assistant_name"])
        self.assertEqual("company_deep_dive", data["workflow_id"])
        self.assertTrue(data["desk_briefs"])
        self.assertTrue(data["debate"])
        self.assertTrue(data["risk_checklist"])
        self.assertTrue(data["related_modules"])

    @patch("quant_platform_api.services.httpx.Client")
    def test_mentor_can_use_llm_answer_when_configured(self, client_mock) -> None:
        stream_response = Mock()
        stream_response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"{\\"headline\\":\\"AI导师判断\\","}}]}',
            'data: {"choices":[{"delta":{"content":"\\"answer\\":\\"这次我会按你的追问继续展开解释。\\","}}]}',
            'data: {"choices":[{"delta":{"content":"\\"why_it_matters\\":\\"因为不同指标负责不同信息层。\\","}}]}',
            'data: {"choices":[{"delta":{"content":"\\"action_plan\\":[\\"先看均线公式\\",\\"再看 MACD 背后的均值差\\",\\"最后把 RSI 放到趋势里用\\"],"}}]}',
            'data: {"choices":[{"delta":{"content":"\\"glossary\\":[{\\"term\\":\\"均线\\",\\"meaning\\":\\"平均成本线\\"}]}"}}]}',
            "data: [DONE]",
        ]
        stream_response.text = ""
        stream_response.raise_for_status.return_value = None

        stream_context = Mock()
        stream_context.__enter__ = Mock(return_value=stream_response)
        stream_context.__exit__ = Mock(return_value=None)

        http_client = Mock()
        http_client.stream.return_value = stream_context
        http_context = Mock()
        http_context.__enter__ = Mock(return_value=http_client)
        http_context.__exit__ = Mock(return_value=None)
        client_mock.return_value = http_context

        service = MentorService(
            Settings(
                llm_base_url="https://llm.example.test/v1",
                llm_api_key="sk-test",
                llm_model_mentor="gpt-5-mini",
            )
        )
        data = service.answer(
            MentorAskRequest(
                question="均线、MACD、RSI 这些技术指标分别适合看什么？新手应该怎么学？",
                experience_level="beginner",
                market_scope="cn_equity",
                current_module="mentor",
            )
        )

        self.assertEqual("llm", data["answer_source"])
        self.assertEqual("AI 实时回答", data["answer_mode_label"])
        self.assertEqual("AI导师判断", data["headline"])
        self.assertIn("继续展开解释", data["answer"])
        self.assertEqual(3, len(data["action_plan"]))

    @patch("quant_platform_api.services.httpx.Client")
    def test_mentor_retries_on_transient_llm_rate_limit(self, client_mock) -> None:
        import httpx

        retry_response = Mock()
        retry_response.status_code = 429
        retry_response.request = httpx.Request("POST", "https://llm.example.test/v1/chat/completions")
        retry_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "rate limited",
            request=retry_response.request,
            response=retry_response,
        )

        ok_response = Mock()
        ok_response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"{\\"headline\\":\\"重试后成功\\",\\"answer\\":\\"这次通过重试拿到了 AI 回答。\\",\\"why_it_matters\\":\\"避免首问偶发退回兜底。\\",\\"action_plan\\":[\\"先提问\\",\\"若限流则短重试\\",\\"再展示结构化答案\\"],\\"glossary\\":[{\\"term\\":\\"限流\\",\\"meaning\\":\\"请求过多时的短暂保护\\"}]}"}}]}',
            "data: [DONE]",
        ]
        ok_response.text = ""
        ok_response.raise_for_status.return_value = None

        retry_context = Mock()
        retry_context.__enter__ = Mock(return_value=retry_response)
        retry_context.__exit__ = Mock(return_value=None)

        ok_context = Mock()
        ok_context.__enter__ = Mock(return_value=ok_response)
        ok_context.__exit__ = Mock(return_value=None)

        http_client = Mock()
        http_client.stream.side_effect = [retry_context, ok_context]
        http_context = Mock()
        http_context.__enter__ = Mock(return_value=http_client)
        http_context.__exit__ = Mock(return_value=None)
        client_mock.return_value = http_context

        service = MentorService(
            Settings(
                llm_base_url="https://llm.example.test/v1",
                llm_api_key="sk-test",
                llm_model_mentor="gpt-5-mini",
            )
        )
        data = service.answer(
            MentorAskRequest(
                question="均线、MACD、RSI 这些技术指标分别适合看什么？新手应该怎么学？",
                experience_level="beginner",
                market_scope="cn_equity",
                current_module="mentor",
            )
        )

        self.assertEqual("llm", data["answer_source"])
        self.assertEqual("重试后成功", data["headline"])
        self.assertEqual(2, http_client.stream.call_count)

    @patch("quant_platform_api.services.httpx.Client")
    def test_assistant_can_use_llm_answer_when_configured(self, client_mock) -> None:
        stream_response = Mock()
        stream_response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"{\\"executive_summary\\":\\"先做驱动拆解，再看多空分歧。\\",\\"desk_briefs\\":[{\\"desk\\":\\"基本面研究员\\",\\"title\\":\\"盈利驱动\\",\\"summary\\":\\"先看收入、利润和预期差。\\"}],\\"debate\\":[{\\"side\\":\\"多头\\",\\"view\\":\\"催化剂足够强。\\"},{\\"side\\":\\"空头\\",\\"view\\":\\"估值已经透支。\\"}],\\"risk_checklist\\":[\\"先核对市场制度\\"],\\"deliverables\\":[\\"执行摘要\\"],\\"next_actions\\":[\\"继续验证核心变量\\"],\\"related_modules\\":[{\\"label\\":\\"策略工坊\\",\\"path\\":\\"/strategy\\",\\"reason\\":\\"把研究转成规则\\"}]}"}}]}',
            "data: [DONE]",
        ]
        stream_response.text = ""
        stream_response.raise_for_status.return_value = None

        stream_context = Mock()
        stream_context.__enter__ = Mock(return_value=stream_response)
        stream_context.__exit__ = Mock(return_value=None)

        http_client = Mock()
        http_client.stream.return_value = stream_context
        http_context = Mock()
        http_context.__enter__ = Mock(return_value=http_client)
        http_context.__exit__ = Mock(return_value=None)
        client_mock.return_value = http_context

        service = FinancialAssistantService(
            Settings(
                llm_base_url="https://llm.example.test/v1",
                llm_api_key="sk-test",
                llm_model_mentor="gpt-5-mini",
            )
        )
        data = service.analyze(
            AssistantResearchRequest(
                query="请按公司深研模式梳理 600519.SH 的盈利驱动、潜在催化剂与关键风险。",
                workflow_id="company_deep_dive",
                target_symbol="600519.SH",
                market_scope="cn_equity",
                research_depth="standard",
                current_module="assistant",
            )
        )

        self.assertEqual("llm", data["answer_source"])
        self.assertEqual("AI 研究编组", data["answer_mode_label"])
        self.assertIn("驱动拆解", data["executive_summary"])
        self.assertEqual("基本面研究员", data["desk_briefs"][0]["desk"])

    def test_client_error_reports_are_visible_in_admin_app_logs(self) -> None:
        client = self._build_client()
        self._login(client, username="1111", password="618618")

        report_response = client.post(
            "/api/v1/client-errors",
            json={
                "message": "策略页脚本报错",
                "source": "web",
                "category": "client_runtime_error",
                "request_path": "/strategy",
                "details": {"module": "strategy"},
            },
        )

        self.assertEqual(200, report_response.status_code)

        client.post("/api/v1/auth/logout")
        self._login(client, username="admin", password="618618")
        logs_response = client.get("/api/v1/admin/app-logs")
        summary_response = client.get("/api/v1/admin/summary")

        self.assertEqual(200, logs_response.status_code)
        items = logs_response.json()["data"]["items"]
        self.assertTrue(any(item["message"] == "策略页脚本报错" for item in items))
        self.assertTrue(any(item["request_path"] == "/strategy" for item in items))
        self.assertEqual(200, summary_response.status_code)
        self.assertGreaterEqual(summary_response.json()["data"]["counts"]["app_errors_24h"], 1)

    def test_create_strategy_project_returns_project_and_version_ids(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "放量均线突破策略",
                "version_label": "日线验证版",
                "natural_language_prompt": "当 5 日均线上穿 20 日均线时做多",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertIn("project_id", data)
        self.assertIn("version_id", data)
        self.assertEqual("日线验证版", data["version_label"])
        self.assertTrue(data["workspace_id"].startswith("ws_"))
        self.assertTrue(data["user_id"].startswith("user_"))

    def test_list_strategy_projects_returns_created_items(self) -> None:
        client = self._build_client()
        self._login(client)

        client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "趋势策略",
                "version_label": "第一轮筛选版",
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
        self.assertEqual("第一轮筛选版", items[0]["version_label"])
        self.assertEqual("600519.SH", items[0]["strategy_dsl"]["market"])
        self.assertIn("def build_strategy()", items[0]["strategy_python"])
        self.assertTrue(items[0]["workspace_id"].startswith("ws_"))

    def test_get_strategy_project_returns_python_code(self) -> None:
        client = self._build_client()
        self._login(client)
        created = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "ETF 趋势策略",
                "version_label": "ETF趋势初版",
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
        self.assertEqual("ETF趋势初版", payload["version_label"])
        self.assertIn("asset_type", payload["strategy_python"])
        self.assertTrue(payload["workspace_id"].startswith("ws_"))

    def test_backtest_run_completes_and_returns_metrics(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_path = Path(temp_dir.name) / "quant_platform.db"
        market_data_path = Path(temp_dir.name) / "market_data.db"
        client = self._build_client(
            database_url=f"sqlite+pysqlite:///{database_path}",
            market_data_database_path=str(market_data_path),
        )
        self._login(client)
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
        payload = fetched.json()
        self.assertIn("request_id", payload)
        data = payload["data"]
        self.assertEqual("succeeded", data["status"])
        self.assertEqual(data["status"], data["state"])
        self.assertTrue(data["user_id"].startswith("user_"))
        self.assertTrue(data["workspace_id"].startswith("ws_"))
        self.assertEqual("snapshot_v1", data["dataset_snapshot_ref"])
        self.assertEqual("engine_v1", data["engine_version"])
        self.assertTrue(data["config_revision"].startswith("cfg_"))
        self.assertEqual("next_bar_open", data["backtest_config"]["fill_price_rule"])
        self.assertEqual("fixed_fraction", data["backtest_config"]["position_sizing"]["mode"])
        self.assertEqual("t_plus_one", data["backtest_config"]["settlement_policy"])
        self.assertFalse(data["backtest_config"]["same_day_exit_allowed"])
        self.assertIn("T+1", data["backtest_config"]["market_constraint_text"])
        self.assertEqual("cn_a_share", data["data_snapshot_summary"]["calendar"])
        self.assertEqual("Asia/Shanghai", data["data_snapshot_summary"]["timezone"])
        self.assertEqual("snapshot_v1", data["data_snapshot_summary"]["dataset_snapshot_ref"])
        self.assertIn("data_source", data)
        self.assertIn("strategy_python", data)

        with sqlite3.connect(database_path) as connection:
            snapshot_row = connection.execute(
                """
                SELECT market, asset_type, frequency, adjustment_mode
                FROM dataset_snapshots
                WHERE dataset_snapshot_ref = ?
                """,
                ("snapshot_v1",),
            ).fetchone()
        self.assertEqual(("600519.SH", "stock", "1d", "qfq"), snapshot_row)

    def test_list_backtest_runs_returns_history(self) -> None:
        client = self._build_client()
        self._login(client)
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
        self.assertTrue(items[0]["workspace_id"].startswith("ws_"))
        self.assertIn("backtest_config", items[0])
        self.assertIn("data_snapshot_summary", items[0])

    def test_completed_backtest_run_can_be_deleted(self) -> None:
        client = self._build_client()
        self._login(client)
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "删除回测策略",
                "natural_language_prompt": "突破前高买入",
                "strategy_dsl": {"market": "510300.SH", "timeframe": "1d", "asset_type": "etf"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]
        run_id = client.post(
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
                "data_snapshot": {"dataset_snapshot_ref": "delete_snapshot_etf"},
            },
        ).json()["data"]["backtest_run_id"]

        deleted = client.delete(f"/api/v1/backtests/runs/{run_id}")
        listing = client.get("/api/v1/backtests/runs")
        detail = client.get(f"/api/v1/backtests/runs/{run_id}")

        self.assertEqual(200, deleted.status_code)
        self.assertTrue(deleted.json()["data"]["deleted"])
        self.assertEqual(run_id, deleted.json()["data"]["backtest_run_id"])
        self.assertEqual([], listing.json()["data"]["items"])
        self.assertEqual(404, detail.status_code)

    def test_running_backtest_run_cannot_be_deleted(self) -> None:
        client = self._build_client(
            job_execution_mode="background",
            job_simulation_latency_ms=400,
        )
        self._login(client)
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "运行中回测策略",
                "natural_language_prompt": "均线上穿买入",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]
        run_id = client.post(
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
                "data_snapshot": {"dataset_snapshot_ref": "running_delete_snapshot"},
            },
        ).json()["data"]["backtest_run_id"]

        deleted = client.delete(f"/api/v1/backtests/runs/{run_id}")

        self.assertEqual(409, deleted.status_code)
        self.assertEqual("STATE_CONFLICT", deleted.json()["error"]["code"])

    def test_compare_backtest_runs_returns_metrics_and_diffs(self) -> None:
        client = self._build_client()
        self._login(client)
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "回测对比策略",
                "natural_language_prompt": "均线上穿时买入",
                "strategy_dsl": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                },
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]

        first = client.post(
            "/api/v1/backtests/runs",
            json={
                "strategy_version_id": version_id,
                "dataset": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
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
                "data_snapshot": {"dataset_snapshot_ref": "compare_snapshot_a"},
            },
        ).json()["data"]["backtest_run_id"]
        second = client.post(
            "/api/v1/backtests/runs",
            json={
                "strategy_version_id": version_id,
                "dataset": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "from": "2024-01-01T00:00:00Z",
                    "to": "2024-06-30T23:59:59Z",
                },
                "execution_contract": {
                    "initial_capital": 100000,
                    "fee_bps": 6,
                    "slippage_bps": 5,
                    "fill_price_rule": "same_bar_close",
                    "intrabar_match_policy": "intrabar_touch_fill",
                    "calendar": "cn_a_share",
                    "timezone": "Asia/Shanghai",
                    "adjustment_mode": "raw",
                    "warmup_bars": 5,
                },
                "data_snapshot": {"dataset_snapshot_ref": "compare_snapshot_b"},
            },
        ).json()["data"]["backtest_run_id"]

        response = client.get(
            "/api/v1/backtests/compare",
            params=[("run_ids", first), ("run_ids", second)],
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual(first, data["baseline_run_id"])
        self.assertEqual(2, len(data["items"]))
        self.assertTrue(data["metric_rows"])
        self.assertTrue(data["config_diffs"])
        self.assertTrue(data["snapshot_diffs"])
        self.assertTrue(data["highlights"])
        config_fields = {item["field"] for item in data["config_diffs"]}
        snapshot_fields = {item["field"] for item in data["snapshot_diffs"]}
        self.assertIn("fill_price_rule", config_fields)
        self.assertIn("dataset_snapshot_ref", snapshot_fields)

    def test_compare_backtest_runs_requires_at_least_two_items(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/api/v1/backtests/compare", params={"run_ids": "only_one"})

        self.assertEqual(400, response.status_code)
        self.assertEqual("INVALID_ARGUMENT", response.json()["error"]["code"])

    def test_backtest_custom_position_and_risk_config_are_persisted(self) -> None:
        client = self._build_client()
        self._login(client)
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "固定数量回测策略",
                "natural_language_prompt": "量比持续大于阈值时买入",
                "strategy_dsl": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "entry": {
                        "all": [
                            {
                                "indicator": "volume_ratio",
                                "params": {"period": 1},
                                "operator": ">",
                                "value": 0.5,
                            }
                        ]
                    },
                    "exit": {"any": []},
                    "position": {"side": "long", "max_positions": 1},
                },
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]

        response = client.post(
            "/api/v1/backtests/runs",
            json={
                "strategy_version_id": version_id,
                "dataset": {
                    "market": "600519.SH",
                    "timeframe": "1d",
                    "asset_type": "stock",
                    "from": "2024-01-01T00:00:00Z",
                    "to": "2024-06-30T23:59:59Z",
                },
                "execution_contract": {
                    "initial_capital": 200000,
                    "fee_bps": 5,
                    "slippage_bps": 1,
                    "fill_price_rule": "same_bar_close",
                    "intrabar_match_policy": "no_intrabar_fill",
                    "calendar": "cn_a_share",
                    "timezone": "Asia/Shanghai",
                    "adjustment_mode": "raw",
                    "warmup_bars": 5,
                    "position_sizing": {
                        "mode": "fixed_quantity",
                        "value": 100,
                        "max_positions": 1,
                        "max_position_pct": 0.5,
                        "min_trade_unit": 100,
                    },
                    "risk_controls": {
                        "take_profit_pct": 0.2,
                        "stop_loss_pct": -0.2,
                        "max_drawdown_pct": -0.3,
                        "max_holding_bars": 5,
                    },
                },
                "data_snapshot": {"dataset_snapshot_ref": "custom_config_snapshot"},
            },
        )
        task_id = response.json()["data"]["backtest_run_id"]

        fetched = client.get(f"/api/v1/backtests/runs/{task_id}")

        self.assertEqual(200, fetched.status_code)
        data = fetched.json()["data"]
        self.assertEqual("fixed_quantity", data["backtest_config"]["position_sizing"]["mode"])
        self.assertEqual(100, data["backtest_config"]["position_sizing"]["value"])
        self.assertEqual(5, data["backtest_config"]["risk_controls"]["max_holding_bars"])
        self.assertEqual("raw", data["backtest_config"]["adjustment_mode"])
        self.assertEqual("t_plus_one", data["backtest_config"]["settlement_policy"])
        self.assertEqual(5, data["data_snapshot_summary"]["warmup_bars"])
        self.assertTrue(data["trades"])
        self.assertEqual(100, data["trades"][0]["quantity"])

    def test_workspace_summary_returns_research_hub_data(self) -> None:
        client = self._build_client()
        self._login(client)
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "工作台汇总策略",
                "natural_language_prompt": "均线上穿时买入",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]
        client.post(
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
                "data_snapshot": {"dataset_snapshot_ref": "workspace_snapshot"},
            },
        )
        upload_id = client.post(
            "/api/v1/trades/uploads",
            files={"file": ("trades.csv", b"symbol,side,entry_time,exit_time,pnl\nBTCUSDT,long,2024-05-01T10:00:00Z,2024-05-01T11:00:00Z,1\n", "text/csv")},
        ).json()["data"]["upload_id"]
        client.post(
            f"/api/v1/trades/uploads/{upload_id}/parse",
            json={"column_mapping": {"symbol": "symbol", "side": "side", "entry_time": "entry_time", "exit_time": "exit_time", "pnl": "pnl"}},
        )
        client.post(
            "/api/v1/replays/analyses",
            json={"upload_id": upload_id, "focus_dimensions": ["side_performance"]},
        )

        summary = client.get("/api/v1/workspace/summary")

        self.assertEqual(200, summary.status_code)
        data = summary.json()["data"]
        self.assertGreaterEqual(data["counts"]["projects"], 1)
        self.assertGreaterEqual(data["counts"]["backtests"], 1)
        self.assertGreaterEqual(data["counts"]["replays"], 1)
        self.assertTrue(data["recent_projects"])
        self.assertTrue(data["recent_backtests"])
        self.assertTrue(data["snapshot_states"])
        self.assertEqual("workspace_snapshot", data["snapshot_states"][0]["dataset_snapshot_ref"])
        self.assertIn("data_hub_status", data)
        self.assertIn("focus_cards", data)
        self.assertTrue(data["focus_cards"])
        self.assertEqual("demo", data["data_hub_status"]["fallback_provider"])

    def test_optimization_job_completes_and_returns_best_metrics(self) -> None:
        client = self._build_client()
        self._login(client)
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "优化策略",
                "natural_language_prompt": "价格突破前高时买入",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]

        created = client.post(
            "/api/v1/optimization-jobs",
            json={
                "strategy_version_id": version_id,
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
        self.assertEqual("succeeded", data["status"])
        self.assertIn("profit_factor", data["best_metrics"])
        self.assertTrue(data["config_revision"].startswith("cfg_"))
        self.assertTrue(data["trials"])

    def test_dataset_snapshot_ref_conflict_returns_revision_conflict(self) -> None:
        client = self._build_client()
        self._login(client)
        created_project = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "快照冲突策略",
                "natural_language_prompt": "价格突破前高时买入",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        )
        version_id = created_project.json()["data"]["version_id"]

        payload = {
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
            "data_snapshot": {"dataset_snapshot_ref": "snapshot_conflict"},
        }
        first = client.post("/api/v1/backtests/runs", json=payload)
        self.assertEqual(202, first.status_code)

        conflicted = client.post(
            "/api/v1/backtests/runs",
            json={
                **payload,
                "dataset": {
                    **payload["dataset"],
                    "timeframe": "1w",
                },
            },
        )

        self.assertEqual(409, conflicted.status_code)
        self.assertEqual("REVISION_CONFLICT", conflicted.json()["error"]["code"])

    def test_replay_analysis_can_be_cancelled_in_background_mode(self) -> None:
        client = self._build_client(
            job_execution_mode="background",
            job_simulation_latency_ms=200,
        )
        self._login(client)
        upload_id = client.post(
            "/api/v1/trades/uploads",
            files={"file": ("trades.csv", b"symbol,side,entry_time,exit_time,pnl\nBTCUSDT,long,2024-05-01T10:00:00Z,2024-05-01T11:00:00Z,1\n", "text/csv")},
        ).json()["data"]["upload_id"]
        client.post(
            f"/api/v1/trades/uploads/{upload_id}/parse",
            json={"column_mapping": {"symbol": "symbol", "side": "side", "entry_time": "entry_time", "exit_time": "exit_time", "pnl": "pnl"}},
        )

        created = client.post(
            "/api/v1/replays/analyses",
            json={
                "upload_id": upload_id,
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
        self.assertEqual("canceled", cancelled.json()["data"]["status"])
        self.assertEqual(200, fetched.status_code)
        self.assertEqual("canceled", fetched.json()["data"]["status"])
        self.assertEqual("STATE_CONFLICT", fetched.json()["data"]["error"]["code"])
        self.assertTrue(fetched.json()["data"]["dataset_snapshot_ref"].startswith("replay_"))

    def test_unknown_task_returns_not_found(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/api/v1/backtests/runs/does-not-exist")

        self.assertEqual(404, response.status_code)
        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertEqual("NOT_FOUND", payload["error"]["code"])
        self.assertIn("request_id", payload)

    def test_task_persists_across_app_restarts(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_url = f"sqlite+pysqlite:///{Path(temp_dir.name) / 'quant_platform.db'}"

        first_client = self._build_client(database_url=database_url)
        self._login(first_client)
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
        self._login(second_client)
        fetched = second_client.get(f"/api/v1/backtests/runs/{task_id}")

        self.assertEqual(200, fetched.status_code)
        self.assertEqual("succeeded", fetched.json()["data"]["status"])
        self.assertEqual(
            "persisted_snapshot",
            fetched.json()["data"]["dataset_snapshot_ref"],
        )
        self.assertTrue(fetched.json()["data"]["config_revision"].startswith("cfg_"))

    def test_trade_upload_parse_and_record_listing_flow(self) -> None:
        client = self._build_client()
        self._login(client)
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
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_path = Path(temp_dir.name) / "quant_platform.db"
        client = self._build_client(
            database_url=f"sqlite+pysqlite:///{database_path}",
        )
        self._login(client)
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
        self.assertEqual("succeeded", data["status"])
        self.assertTrue(data["config_revision"].startswith("cfg_"))
        self.assertTrue(data["dataset_snapshot_ref"].startswith("replay_"))
        self.assertIn("本次复盘共分析 3 笔交易", data["summary"])
        self.assertIn("当前表现更优的是做多交易", data["summary"])
        self.assertIn("需要重点优化的是做空交易", data["summary"])
        self.assertIn("这批交易共 3 笔", data["concise_summary"])
        self.assertEqual("sharpe_max", data["overview"]["default_objective"])
        self.assertEqual("夏普最大", data["overview"]["default_objective_label"])
        self.assertEqual("做多交易的累计盈亏和整体表现当前更优", data["winning_patterns"][0]["pattern"])
        self.assertTrue(data["loss_features"])
        self.assertTrue(data["profit_features"])
        self.assertTrue(data["objective_versions"])
        self.assertIn("counterfactual_cases", data)
        self.assertTrue(data["parameter_changes"])
        self.assertTrue(data["condition_replacements"])
        self.assertTrue(data["trade_records"])
        self.assertEqual("sharpe_max", data["objective_versions"][0]["objective"])
        self.assertTrue(data["objective_versions"][0]["equity_curve"])
        self.assertTrue(data["objective_versions"][0]["trade_records"])
        self.assertIn("metrics", data["objective_versions"][0])
        self.assertIn("baseline_metrics", data["objective_versions"][0])
        self.assertIn("trade_count", data["objective_versions"][0]["metrics"])
        self.assertIn("sharpe_like", data["objective_versions"][0]["metrics"])
        self.assertLessEqual(
            data["objective_versions"][0]["metrics"]["trade_count"],
            data["objective_versions"][0]["baseline_metrics"]["trade_count"],
        )
        self.assertIn("样本筛选回放", data["objective_versions"][0]["comparison_note"])
        self.assertIn("上下文评分", data["objective_versions"][0]["comparison_note"])
        self.assertIn("entry_price", data["trade_records"][0])
        self.assertIn("把该方向仓位降到优势方向的一半", data["suggestion_rules"][0]["description"])
        self.assertTrue(data["suggestion_rules"])

    def test_replay_analysis_returns_analysis_scope_and_daily_context_features(self) -> None:
        client = self._build_client()
        self._login(client)
        csv_text = (
            "symbol,side,entry_time,exit_time,pnl\n"
            "600519.SH,long,2024-05-06T09:30:00Z,2024-05-10T15:00:00Z,1200\n"
            "600519.SH,long,2024-06-03T09:30:00Z,2024-06-05T15:00:00Z,-800\n"
            "510300.SH,long,2024-06-18T09:30:00Z,2024-06-20T15:00:00Z,-500\n"
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
                "focus_dimensions": ["side_performance", "volume_structure", "moving_average_structure"],
                "analysis_options": {
                    "lookback_days": 5,
                    "minute_window_minutes": 60,
                    "include_market_context": True,
                    "auto_market_context": True,
                    "include_minute_features": True,
                    "include_fundamentals": True,
                },
            },
        )
        analysis_id = created.json()["data"]["analysis_id"]
        fetched = client.get(f"/api/v1/replays/analyses/{analysis_id}")

        self.assertEqual(200, fetched.status_code)
        data = fetched.json()["data"]
        scope = data["overview"]["analysis_scope"]
        self.assertEqual(5, scope["lookback_days"])
        self.assertEqual(60, scope["minute_window_minutes"])
        self.assertTrue(scope["include_market_context"])
        self.assertTrue(scope["include_minute_features"])
        self.assertTrue(scope["include_fundamentals"])
        self.assertIn("量价结构", scope["labels"])
        self.assertIn("均线位置", scope["labels"])
        self.assertEqual("unavailable", scope["minute_feature_status"])
        self.assertEqual("unavailable", scope["fundamental_status"])
        self.assertEqual("unavailable", scope["daily_context_status"])

    def test_replay_feature_extractors_build_minute_and_fundamental_summaries(self) -> None:
        minute_loss = _build_replay_minute_context_features(
            [
                {
                    "pnl": -500,
                    "minute_return_pct": 0.4,
                    "peak_to_close_drawdown_pct": 0.2,
                    "first_15m_return_pct": 1.9,
                    "last_15m_return_pct": -0.8,
                    "up_bar_ratio": 0.32,
                    "close_position_pct": 22.0,
                },
                {
                    "pnl": -300,
                    "minute_return_pct": 0.5,
                    "peak_to_close_drawdown_pct": 0.25,
                    "first_15m_return_pct": 1.4,
                    "last_15m_return_pct": -0.5,
                    "up_bar_ratio": 0.4,
                    "close_position_pct": 35.0,
                },
                {
                    "pnl": 800,
                    "minute_return_pct": 0.6,
                    "peak_to_close_drawdown_pct": 0.3,
                    "first_15m_return_pct": 0.2,
                    "last_15m_return_pct": 0.3,
                    "up_bar_ratio": 0.68,
                    "close_position_pct": 74.0,
                },
            ],
            target="loss",
        )
        fundamental_profit = _build_replay_fundamental_features(
            [
                {
                    "pnl": 1200,
                    "pe_ttm": 18.0,
                    "pb": 2.1,
                    "turnover_rate": 1.8,
                    "total_mv": 1200.0,
                    "roe": 16.2,
                    "grossprofit_margin": 41.0,
                    "op_yoy": 18.5,
                    "debt_to_assets": 32.0,
                },
                {
                    "pnl": 900,
                    "pe_ttm": 20.0,
                    "pb": 2.4,
                    "turnover_rate": 2.0,
                    "total_mv": 1100.0,
                    "roe": 13.5,
                    "grossprofit_margin": 38.0,
                    "op_yoy": 12.0,
                    "debt_to_assets": 35.0,
                },
                {
                    "pnl": -700,
                    "pe_ttm": 45.0,
                    "pb": 5.8,
                    "turnover_rate": 4.2,
                    "total_mv": 900.0,
                    "roe": 5.1,
                    "grossprofit_margin": 18.0,
                    "op_yoy": -6.0,
                    "debt_to_assets": 62.0,
                },
            ],
            target="profit",
        )

        self.assertTrue(any("开盘前15分钟过热" in item["title"] for item in minute_loss))
        self.assertTrue(any("分钟窗口末端收在区间偏弱位置" in item["title"] for item in minute_loss))
        self.assertTrue(any("ROE" in item["title"] for item in fundamental_profit))
        self.assertTrue(any("毛利率" in item["title"] for item in fundamental_profit))
        self.assertTrue(any("营收增速" in item["title"] for item in fundamental_profit))

    def test_replay_context_suggestions_generate_structured_rule_patches(self) -> None:
        suggestions = _build_replay_context_suggestions(
            loss_features=[
                {"id": "loss_first_15m_hot", "title": "亏损样本更常在开盘前15分钟过热后入场"},
                {"id": "loss_higher_debt", "title": "亏损样本更常集中在资产负债率更高的标的"},
            ],
            profit_features=[
                {"id": "profit_trend_regime", "title": "趋势环境下更容易保留盈利结构"},
                {"id": "profit_higher_roe", "title": "盈利样本更常分布在 ROE 更高的标的"},
            ],
        )

        self.assertTrue(any(item["title"] == "收紧盘中过热追入" for item in suggestions))
        self.assertTrue(any(item["title"] == "只在趋势环境里保留开仓" for item in suggestions))
        self.assertTrue(any(item["title"] == "加入基本面质量过滤" for item in suggestions))
        intraday_rule = next(item for item in suggestions if item["title"] == "收紧盘中过热追入")
        self.assertIn("intraday_entry_timing", intraday_rule["dsl_patch"]["filters"])
        quality_rule = next(item for item in suggestions if item["title"] == "加入基本面质量过滤")
        self.assertIn("quality_filter", quality_rule["dsl_patch"]["filters"])

    def test_replay_intraday_filters_support_extended_minute_constraints(self) -> None:
        bars = [
            MarketBar(
                ts_code="600519.SH",
                asset_type="stock",
                adjustment_mode="qfq",
                trade_date="2024-05-01",
                open=10.0,
                high=10.1,
                low=9.9,
                close=10.0,
                volume=1000,
                amount=10000,
                pct_chg=0.0,
                turnover=1.0,
                data_source="internal_clickhouse_dwd",
                fetched_at="2026-04-09T00:00:00",
            ),
            MarketBar(
                ts_code="600519.SH",
                asset_type="stock",
                adjustment_mode="qfq",
                trade_date="2024-05-02",
                open=10.0,
                high=10.3,
                low=9.98,
                close=10.2,
                volume=1200,
                amount=11000,
                pct_chg=0.0,
                turnover=1.2,
                data_source="internal_clickhouse_dwd",
                fetched_at="2026-04-09T00:00:00",
            ),
        ]

        passing = _replay_trade_passes_filters(
            bars=bars,
            entry_index=1,
            filters={
                "intraday_entry_timing": {
                    "min_first_15m_return_pct": 0.1,
                    "min_last_15m_return_pct": 0.0,
                },
                "intraday_structure": {
                    "max_peak_to_close_drawdown_pct": 2.0,
                },
            },
            minute_context={
                "first_15m_return_pct": 0.3,
                "last_15m_return_pct": 0.1,
                "close_position_pct": 62.0,
                "up_bar_ratio": 0.6,
                "peak_to_close_drawdown_pct": 1.5,
            },
            fundamental_context=None,
        )
        failing = _replay_trade_passes_filters(
            bars=bars,
            entry_index=1,
            filters={
                "intraday_entry_timing": {
                    "min_first_15m_return_pct": 0.1,
                    "min_last_15m_return_pct": 0.2,
                },
                "intraday_structure": {
                    "max_peak_to_close_drawdown_pct": 1.0,
                },
            },
            minute_context={
                "first_15m_return_pct": 0.3,
                "last_15m_return_pct": 0.1,
                "close_position_pct": 62.0,
                "up_bar_ratio": 0.6,
                "peak_to_close_drawdown_pct": 1.5,
            },
            fundamental_context=None,
        )

        self.assertTrue(passing)
        self.assertFalse(failing)

    def test_replay_market_rerun_uses_real_daily_bars_when_available(self) -> None:
        class FakeMarketDataService:
            def load_daily_bars(self, *, ts_code, start_date, end_date, adjustment_mode):
                return (
                    [
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-01",
                            open=10.0,
                            high=10.2,
                            low=9.9,
                            close=10.1,
                            volume=1000,
                            amount=10000,
                            pct_chg=0.0,
                            turnover=1.0,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-02",
                            open=10.1,
                            high=10.6,
                            low=10.0,
                            close=10.5,
                            volume=1200,
                            amount=11000,
                            pct_chg=0.0,
                            turnover=1.2,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-03",
                            open=10.5,
                            high=10.8,
                            low=10.4,
                            close=10.7,
                            volume=1100,
                            amount=12000,
                            pct_chg=0.0,
                            turnover=1.1,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                    ],
                    {"provider": "internal_clickhouse_dwd", "status": "ready"},
                )

            def load_minute_window(self, *, ts_code, start_time, end_time, adjustment_mode):
                return [], {"provider": "internal_clickhouse_dwd", "status": "unavailable"}

        trade = TradeRecordItem(
            trade_id="trade_1",
            symbol="600519.SH",
            side="long",
            entry_time=datetime.fromisoformat("2024-05-01T09:30:00+00:00"),
            exit_time=datetime.fromisoformat("2024-05-03T15:00:00+00:00"),
            pnl=700.0,
            entry_price=10.0,
            exit_price=10.7,
        )
        rerun = _rerun_replay_records_on_market_data(
            records=[trade],
            replay_market="cn_a_share",
            objective="sharpe_max",
            market_data_service=FakeMarketDataService(),
            suggestion_rules=[
                {
                    "title": "只在趋势环境里保留开仓",
                    "dsl_patch": {
                        "filters": {
                            "market_regime": {"enabled": True, "preferred": "trend"},
                            "trend_confirmation": {"enabled": True, "timeframe": "1d"},
                        },
                        "risk": {"max_holding_bars": 2, "stop_loss_pct": -0.02},
                    },
                }
            ],
            minute_context_by_trade_id={"trade_1": {"first_15m_return_pct": 0.2, "close_position_pct": 72.0, "up_bar_ratio": 0.65}},
            fundamental_context_by_trade_id={"trade_1": {"pe_ttm": 18.0, "pb": 2.1, "roe": 15.0, "grossprofit_margin": 35.0, "op_yoy": 12.0, "debt_to_assets": 32.0}},
        )

        self.assertIsNotNone(rerun)
        assert rerun is not None
        self.assertEqual(1, rerun["metrics"]["trade_count"])
        self.assertTrue(rerun["equity_curve"])
        self.assertGreater(rerun["trade_records"][0]["pnl"], 0)
        self.assertEqual("grid_search", rerun["search_summary"]["mode"])
        self.assertGreaterEqual(rerun["search_summary"]["evaluated_variants"], 1)
        self.assertIn("risk", rerun["selected_patch"])
        self.assertIn("filters", rerun["selected_patch"])

    def test_replay_market_rerun_uses_real_minute_window_for_stop_exit(self) -> None:
        class FakeMarketDataService:
            def load_daily_bars(self, *, ts_code, start_date, end_date, adjustment_mode):
                return (
                    [
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-01",
                            open=10.0,
                            high=10.2,
                            low=9.9,
                            close=10.1,
                            volume=1000,
                            amount=10000,
                            pct_chg=0.0,
                            turnover=1.0,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-02",
                            open=10.1,
                            high=10.3,
                            low=9.75,
                            close=10.25,
                            volume=1200,
                            amount=11000,
                            pct_chg=0.0,
                            turnover=1.2,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                    ],
                    {"provider": "internal_clickhouse_dwd", "status": "ready"},
                )

            def load_minute_window(self, *, ts_code, start_time, end_time, adjustment_mode):
                return (
                    [
                        MinuteBar(
                            ts_code=ts_code,
                            trade_time="2024-05-02T10:01:00+08:00",
                            open=10.0,
                            high=10.05,
                            low=9.97,
                            close=10.02,
                            volume=100,
                            amount=1000,
                            pct_change=0.0,
                            amplitude=0.0,
                            data_source="internal_clickhouse_dwd",
                        ),
                        MinuteBar(
                            ts_code=ts_code,
                            trade_time="2024-05-02T10:15:00+08:00",
                            open=10.02,
                            high=10.03,
                            low=9.79,
                            close=9.82,
                            volume=140,
                            amount=1200,
                            pct_change=0.0,
                            amplitude=0.0,
                            data_source="internal_clickhouse_dwd",
                        ),
                    ],
                    {"provider": "internal_clickhouse_dwd", "status": "ready"},
                )

        trade = TradeRecordItem(
            trade_id="trade_1",
            symbol="600519.SH",
            side="long",
            entry_time=datetime.fromisoformat("2024-05-01T09:30:00+00:00"),
            exit_time=datetime.fromisoformat("2024-05-02T15:00:00+00:00"),
            pnl=700.0,
            entry_price=10.0,
            exit_price=10.25,
        )
        rerun = _rerun_replay_records_on_market_data(
            records=[trade],
            replay_market="cn_a_share",
            objective="max_drawdown_min",
            market_data_service=FakeMarketDataService(),
            suggestion_rules=[
                {
                    "title": "缩短错误持有并收紧止损",
                    "dsl_patch": {"risk": {"max_holding_bars": 2, "stop_loss_pct": -0.02}},
                }
            ],
            minute_context_by_trade_id={},
            fundamental_context_by_trade_id={},
        )

        self.assertIsNotNone(rerun)
        assert rerun is not None
        self.assertEqual("stop_loss_intraday_minute", rerun["trade_records"][0]["exit_reason"])
        self.assertTrue(rerun["trade_records"][0]["minute_stop_used"])
        self.assertIn("T10:15:00", rerun["trade_records"][0]["exit_time"])
        self.assertEqual(1, rerun["metrics"]["minute_exit_triggered_count"])

    def test_replay_market_rerun_uses_real_minute_entry_and_take_profit(self) -> None:
        class FakeMarketDataService:
            def load_daily_bars(self, *, ts_code, start_date, end_date, adjustment_mode):
                return (
                    [
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-01",
                            open=10.0,
                            high=10.2,
                            low=9.95,
                            close=10.15,
                            volume=1000,
                            amount=10000,
                            pct_chg=0.0,
                            turnover=1.0,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-02",
                            open=10.2,
                            high=10.8,
                            low=10.1,
                            close=10.7,
                            volume=1200,
                            amount=11000,
                            pct_chg=0.0,
                            turnover=1.2,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                    ],
                    {"provider": "internal_clickhouse_dwd", "status": "ready"},
                )

            def load_minute_window(self, *, ts_code, start_time, end_time, adjustment_mode):
                if start_time.date().isoformat() == "2024-05-01":
                    return (
                        [
                            MinuteBar(
                                ts_code=ts_code,
                                trade_time="2024-05-01T09:35:00+08:00",
                                open=10.05,
                                high=10.08,
                                low=10.02,
                                close=10.06,
                                volume=120,
                                amount=1000,
                                pct_change=0.0,
                                amplitude=0.0,
                                data_source="internal_clickhouse_dwd",
                            ),
                            MinuteBar(
                                ts_code=ts_code,
                                trade_time="2024-05-01T09:36:00+08:00",
                                open=10.06,
                                high=10.09,
                                low=10.05,
                                close=10.08,
                                volume=100,
                                amount=900,
                                pct_change=0.0,
                                amplitude=0.0,
                                data_source="internal_clickhouse_dwd",
                            ),
                        ],
                        {"provider": "internal_clickhouse_dwd", "status": "ready"},
                    )
                return (
                    [
                        MinuteBar(
                            ts_code=ts_code,
                            trade_time="2024-05-02T10:05:00+08:00",
                            open=10.4,
                            high=10.95,
                            low=10.35,
                            close=10.62,
                            volume=180,
                            amount=1400,
                            pct_change=0.0,
                            amplitude=0.0,
                            data_source="internal_clickhouse_dwd",
                        ),
                    ],
                    {"provider": "internal_clickhouse_dwd", "status": "ready"},
                )

        trade = TradeRecordItem(
            trade_id="trade_2",
            symbol="600519.SH",
            side="long",
            entry_time=datetime.fromisoformat("2024-05-01T09:35:00+08:00"),
            exit_time=datetime.fromisoformat("2024-05-02T15:00:00+08:00"),
            pnl=500.0,
            entry_price=None,
            exit_price=None,
        )
        rerun = _rerun_replay_records_on_market_data(
            records=[trade],
            replay_market="cn_a_share",
            objective="total_return_max",
            market_data_service=FakeMarketDataService(),
            suggestion_rules=[
                {
                    "title": "保留更强盈利空间并设置止盈",
                    "dsl_patch": {"risk": {"max_holding_bars": 2, "take_profit_pct": 0.06, "stop_loss_pct": -0.02}},
                }
            ],
            minute_context_by_trade_id={},
            fundamental_context_by_trade_id={},
        )

        self.assertIsNotNone(rerun)
        assert rerun is not None
        self.assertEqual("take_profit_intraday_minute", rerun["trade_records"][0]["exit_reason"])
        self.assertEqual(10.05, rerun["trade_records"][0]["entry_price"])
        self.assertIn("T09:35:00", rerun["trade_records"][0]["entry_time"])
        self.assertIn("T10:05:00", rerun["trade_records"][0]["exit_time"])
        self.assertTrue(rerun["trade_records"][0]["minute_stop_used"])
        self.assertTrue(rerun["trade_records"][0]["minute_entry_used"])
        self.assertTrue(rerun["trade_records"][0]["minute_exit_used"])
        self.assertEqual(1, rerun["metrics"]["minute_entry_aligned_count"])
        self.assertEqual(1, rerun["metrics"]["minute_exit_triggered_count"])
        self.assertIn("take_profit_pct", rerun["selected_patch"]["risk"])

    def test_replay_counterfactual_cases_build_alternative_paths_for_losing_trade(self) -> None:
        class FakeMarketDataService:
            def load_daily_bars(self, *, ts_code, start_date, end_date, adjustment_mode):
                return (
                    [
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-01",
                            open=10.0,
                            high=10.4,
                            low=9.9,
                            close=10.3,
                            volume=1000,
                            amount=10000,
                            pct_chg=0.0,
                            turnover=1.0,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-02",
                            open=10.35,
                            high=10.55,
                            low=9.7,
                            close=9.85,
                            volume=1200,
                            amount=11000,
                            pct_chg=0.0,
                            turnover=1.2,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                        MarketBar(
                            ts_code=ts_code,
                            asset_type="stock",
                            adjustment_mode="qfq",
                            trade_date="2024-05-03",
                            open=9.9,
                            high=10.0,
                            low=9.75,
                            close=9.95,
                            volume=1100,
                            amount=9000,
                            pct_chg=0.0,
                            turnover=1.1,
                            data_source="internal_clickhouse_dwd",
                            fetched_at="2026-04-09T00:00:00",
                        ),
                    ],
                    {"provider": "internal_clickhouse_dwd", "status": "ready"},
                )

            def load_minute_window(self, *, ts_code, start_time, end_time, adjustment_mode):
                if start_time.date().isoformat() == "2024-05-01":
                    return (
                        [
                            MinuteBar(
                                ts_code=ts_code,
                                trade_time="2024-05-01T09:35:00+08:00",
                                open=10.4,
                                high=10.45,
                                low=10.36,
                                close=10.42,
                                volume=120,
                                amount=1000,
                                pct_change=0.0,
                                amplitude=0.0,
                                data_source="internal_clickhouse_dwd",
                            ),
                            MinuteBar(
                                ts_code=ts_code,
                                trade_time="2024-05-01T09:50:00+08:00",
                                open=10.12,
                                high=10.18,
                                low=10.08,
                                close=10.15,
                                volume=140,
                                amount=1200,
                                pct_change=0.0,
                                amplitude=0.0,
                                data_source="internal_clickhouse_dwd",
                            ),
                        ],
                        {"provider": "internal_clickhouse_dwd", "status": "ready"},
                    )
                return (
                    [
                        MinuteBar(
                            ts_code=ts_code,
                            trade_time="2024-05-02T10:00:00+08:00",
                            open=10.02,
                            high=10.05,
                            low=9.78,
                            close=9.82,
                            volume=180,
                            amount=1400,
                            pct_change=0.0,
                            amplitude=0.0,
                            data_source="internal_clickhouse_dwd",
                        ),
                    ],
                    {"provider": "internal_clickhouse_dwd", "status": "ready"},
                )

        trade = TradeRecordItem(
            trade_id="trade_loss_1",
            symbol="600519.SH",
            side="long",
            entry_time=datetime.fromisoformat("2024-05-01T09:35:00+08:00"),
            exit_time=datetime.fromisoformat("2024-05-02T15:00:00+08:00"),
            pnl=-320.0,
            entry_price=10.4,
            exit_price=9.82,
        )
        cases = _build_replay_counterfactual_cases(
            records=[trade],
            replay_market="cn_a_share",
            market_data_service=FakeMarketDataService(),
            daily_context_by_trade_id={
                "trade_loss_1": {"trend_regime": "range", "above_ma5": False, "prior_return_pct": 4.6}
            },
            minute_context_by_trade_id={
                "trade_loss_1": {
                    "first_15m_return_pct": 1.3,
                    "last_15m_return_pct": -0.4,
                    "close_position_pct": 38.0,
                    "up_bar_ratio": 0.4,
                    "peak_to_close_drawdown_pct": 3.2,
                }
            },
            fundamental_context_by_trade_id={
                "trade_loss_1": {"pe_ttm": 48.0, "roe": 7.0, "debt_to_assets": 66.0}
            },
        )

        self.assertEqual(1, len(cases))
        self.assertEqual("trade_loss_1", cases[0]["trade_id"])
        self.assertEqual(4, len(cases[0]["alternatives"]))
        self.assertEqual("skip_trade_filter", cases[0]["recommended_alternative_key"])
        result_types = {item["result_type"] for item in cases[0]["alternatives"]}
        self.assertIn("skipped", result_types)
        self.assertIn("rerun", result_types)
        delayed = next(item for item in cases[0]["alternatives"] if item["key"] == "delayed_entry_confirmation")
        self.assertEqual("rerun", delayed["result_type"])
        self.assertTrue(delayed["comparison"]["entry_changed"])
        self.assertIsNotNone(delayed["trade_record"])

    def test_manual_trade_upload_creates_parsed_records(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/manual",
            json={
                "source_type": "manual",
                "source_file_name": "manual-entry.json",
                "source_notes": "手动补录",
                "records": [
                    {
                        "symbol": "600519.SH",
                        "side": "long",
                        "entry_time": "2024-05-01T09:30:00Z",
                        "exit_time": "2024-05-03T15:00:00Z",
                        "pnl": 2800,
                    }
                ],
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual("manual", data["upload_kind"])
        self.assertEqual("parsed", data["status"])
        self.assertEqual(1, data["record_count"])

    def test_manual_text_parse_endpoint_recognizes_symbols_and_rules(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/manual/parse-text",
            json={
                "text": (
                    "2025-07-25 买入：603590.SH, 002225.SZ；"
                    "买入方式：当日开盘价买入；"
                    "卖出方式：当最低价低于当日开盘价-0.5倍atr的值则卖出"
                ),
                "market": "cn_equity",
                "adjustment_mode": "qfq",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual(2, data["record_count"])
        self.assertEqual("2025-07-25", data["trade_date"])
        self.assertIn("当日开盘价买入", data["entry_rule"])
        self.assertIn("ATR", data["exit_rule"])
        first = data["records"][0]
        self.assertEqual("603590.SH", first["symbol"])
        self.assertIsNotNone(first["entry_price"])
        self.assertIsNotNone(first["exit_price"])
        self.assertIsNotNone(first["exit_time"])
        self.assertIn("长文字智能识别", first["notes"])
        self.assertIn("补价来源", first["notes"])

    def test_manual_text_parse_endpoint_supports_explicit_prices(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/manual/parse-text",
            json={
                "text": (
                    "2025-07-25 买入：603590.SH；"
                    "买入价：10.5；"
                    "卖出价：11.2"
                ),
                "market": "cn_equity",
                "adjustment_mode": "qfq",
            },
        )

        self.assertEqual(200, response.status_code)
        record = response.json()["data"]["records"][0]
        self.assertEqual(10.5, record["entry_price"])
        self.assertEqual(11.2, record["exit_price"])
        self.assertAlmostEqual(0.7, record["pnl"], places=4)

    def test_manual_text_parse_endpoint_supports_plain_codes_and_explicit_dates(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/manual/parse-text",
            json={
                "text": (
                    "买入日期：2025/07/25；买入：603590, 002225；"
                    "买入方式：当日开盘价买入；卖出日期：2025/07/28"
                ),
                "market": "cn_equity",
                "adjustment_mode": "qfq",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual(2, data["record_count"])
        self.assertEqual("2025-07-25", data["trade_date"])
        first = data["records"][0]
        self.assertEqual("603590.SH", first["symbol"])
        self.assertIsNotNone(first["exit_price"])
        self.assertIn("按卖出日期 2025-07-28 的收盘价补全", first["notes"])

    def test_manual_text_parse_endpoint_supports_offset_exit_rule(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/manual/parse-text",
            json={
                "text": (
                    "2025-07-25 买入：603590.SH；"
                    "买入方式：次日收盘价买入；"
                    "卖出方式：第3个交易日收盘价卖出"
                ),
                "market": "cn_equity",
                "adjustment_mode": "qfq",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertIn("次日收盘价买入", data["entry_rule"])
        self.assertIn("第 3 个交易日收盘价卖出", data["exit_rule"])
        record = data["records"][0]
        self.assertIsNotNone(record["exit_time"])
        self.assertIn("卖出规则", record["notes"])

    def test_manual_text_parse_endpoint_supports_stop_loss_pct_rule(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/manual/parse-text",
            json={
                "text": (
                    "2025-07-25 买入：603590.SH；"
                    "买入方式：当日开盘价买入；"
                    "卖出方式：止损3%"
                ),
                "market": "cn_equity",
                "adjustment_mode": "qfq",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertIn("下跌 3% 止损卖出", data["exit_rule"])
        record = data["records"][0]
        self.assertIsNotNone(record["exit_price"])
        self.assertIn("止损阈值", record["notes"])

    def test_manual_text_parse_endpoint_supports_grouped_trade_lists_with_global_rules(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/manual/parse-text",
            json={
                "text": (
                    "2025-07-25 (Friday)\n"
                    "（8 只）：603590.SH, 002225.SZ, 001283.SZ\n\n"
                    "2025-08-01 (Friday)\n"
                    "（5 只）：603579.SH, 002675.SZ, 000802.SZ, 600501con9.SH, 002174.SZfinalsell\n\n"
                    "以上日期买入，买入方式：当日开盘价买入，卖出方式：价格低于当日开盘价-0.5倍atr时卖出"
                ),
                "market": "cn_equity",
                "adjustment_mode": "qfq",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual(2, len(data["trade_dates"]))
        self.assertEqual(8, data["record_count"])
        self.assertIn("0.5 倍 ATR", data["exit_rule"])
        symbols = {item["symbol"] for item in data["records"]}
        self.assertIn("600501.SH", symbols)
        self.assertIn("002174.SZ", symbols)
        self.assertNotIn("000.SH", symbols)
        self.assertTrue(all("长文字智能识别" in item["notes"] for item in data["records"]))
        self.assertEqual(2, data["group_count"])
        self.assertEqual("当日开盘价买入", data["group_summaries"][0]["entry_rule"])

    def test_manual_text_parse_endpoint_supports_per_group_rules(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/manual/parse-text",
            json={
                "text": (
                    "2025-07-25\n"
                    "买入方式：次日开盘价买入；卖出方式：第3个交易日收盘价卖出\n"
                    "标的：603590.SH, 002225.SZ\n\n"
                    "2025-08-01\n"
                    "买入方式：当日收盘价买入；卖出方式：止损3%\n"
                    "标的：603579.SH"
                ),
                "market": "cn_equity",
                "adjustment_mode": "qfq",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual(2, data["group_count"])
        self.assertEqual("次日开盘价买入", data["group_summaries"][0]["entry_rule"])
        self.assertEqual("第 3 个交易日收盘价卖出", data["group_summaries"][0]["exit_rule"])
        self.assertEqual("当日收盘价买入", data["group_summaries"][1]["entry_rule"])
        self.assertEqual("下跌 3% 止损卖出", data["group_summaries"][1]["exit_rule"])
        self.assertIn("买入规则：次日开盘价买入", data["records"][0]["notes"])
        self.assertIn("卖出规则：第 3 个交易日收盘价卖出", data["records"][0]["notes"])
        self.assertIn("买入规则：当日收盘价买入", data["records"][-1]["notes"])
        self.assertIn("卖出规则：下跌 3% 止损卖出", data["records"][-1]["notes"])

    @patch("quant_platform_api.services.httpx.Client")
    def test_manual_text_parse_endpoint_can_use_llm_for_complex_group_rules(self, client_mock) -> None:
        stream_response = Mock()
        stream_response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"{\\"global_entry_rule\\":\\"\\",\\"global_exit_rule\\":\\"\\",\\"groups\\":[{\\"trade_date\\":\\"2025-07-25\\",\\"symbols\\":[\\"603590.SH\\",\\"002225.SZ\\"],\\"entry_rule_text\\":\\"次日开盘价买入\\",\\"exit_rule_text\\":\\"价格低于当日开盘价-0.5倍atr时卖出\\",\\"explicit_exit_date\\":\\"\\",\\"confidence\\":\\"high\\"},{\\"trade_date\\":\\"2025-08-01\\",\\"symbols\\":[\\"603579.SH\\"],\\"entry_rule_text\\":\\"当日收盘价买入\\",\\"exit_rule_text\\":\\"止损3%\\",\\"explicit_exit_date\\":\\"\\",\\"confidence\\":\\"medium\\"}],\\"warnings\\":[\\"第二组规则来自自然语言推断，请人工确认\\"]}"}}]}',
            "data: [DONE]",
        ]
        stream_response.text = ""
        stream_response.raise_for_status.return_value = None

        stream_context = Mock()
        stream_context.__enter__ = Mock(return_value=stream_response)
        stream_context.__exit__ = Mock(return_value=None)

        http_client = Mock()
        http_client.stream.return_value = stream_context
        http_context = Mock()
        http_context.__enter__ = Mock(return_value=http_client)
        http_context.__exit__ = Mock(return_value=None)
        client_mock.return_value = http_context

        client = self._build_client(
            llm_base_url="https://llm.example.test/v1",
            llm_api_key="sk-test",
            llm_model_mentor="gpt-5-mini",
        )
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/manual/parse-text",
            json={
                "text": (
                    "2025-07-25\n"
                    "603590.SH, 002225.SZ\n"
                    "这组等到次日开盘再买，若价格低于开盘价减去半个 ATR 就走。\n\n"
                    "2025-08-01\n"
                    "603579.SH\n"
                    "这组改成当天收盘再买，止损 3%。"
                ),
                "market": "cn_equity",
                "adjustment_mode": "qfq",
            },
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual("hybrid_llm", data["parse_mode"])
        self.assertTrue(data["ai_review"]["used"])
        self.assertEqual("AI 混合解析", data["ai_review"]["mode_label"])
        self.assertIn("人工确认", data["ai_review"]["warnings"][0])
        self.assertEqual("次日开盘价买入", data["group_summaries"][0]["entry_rule"])
        self.assertEqual("下跌 3% 止损卖出", data["group_summaries"][1]["exit_rule"])
        self.assertIn("买入规则：次日开盘价买入", data["records"][0]["notes"])
        self.assertIn("卖出规则：下跌 3% 止损卖出", data["records"][-1]["notes"])

    def test_screenshot_trade_upload_creates_structured_record(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.post(
            "/api/v1/trades/uploads/screenshot",
            data={
                "market": "cn_equity",
                "symbol": "600519.SH",
                "side": "long",
                "entry_time": "2024-05-01T09:30:00Z",
                "exit_time": "2024-05-03T15:00:00Z",
                "pnl": "2800",
                "source_notes": "券商成交截图",
            },
            files={"file": ("trade.png", b"fake-image-binary", "image/png")},
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual("screenshot", data["upload_kind"])
        self.assertEqual("parsed", data["status"])
        self.assertEqual(1, data["record_count"])

    def test_screenshot_ocr_endpoint_extracts_symbol_and_date(self) -> None:
        client = self._build_client()
        self._login(client)
        image_bytes = self._build_trade_screenshot_bytes(
            "2025-07-25\n603590.SH\n买入\n盈亏: 1280"
        )

        response = client.post(
            "/api/v1/trades/uploads/screenshot/ocr",
            data={"market": "cn_equity"},
            files={"file": ("trade.png", image_bytes, "image/png")},
        )

        self.assertEqual(200, response.status_code)
        data = response.json()["data"]
        self.assertEqual("603590.SH", data["suggested_symbol"])
        self.assertEqual("2025-07-25", data["detected_trade_date"])
        self.assertEqual("long", data["suggested_side"])
        self.assertGreaterEqual(data["suggested_pnl"], 1280)
        self.assertIn("来源：截图 OCR 识别", data["suggested_notes"])

    def test_replay_page_supports_csv_screenshot_and_manual_sources(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/replay")

        self.assertEqual(200, response.status_code)
        self.assertIn("CSV 导入", response.text)
        self.assertIn("成交截图", response.text)
        self.assertIn("手动录入", response.text)
        self.assertIn("建议顺序", response.text)
        self.assertIn("CSV 文件", response.text)
        self.assertIn("或直接粘贴 CSV", response.text)
        self.assertIn("智能识别截图内容", response.text)
        self.assertIn("登记截图并生成记录", response.text)
        self.assertIn("加入手动记录", response.text)
        self.assertIn("长文字智能识别", response.text)
        self.assertIn("智能识别并加入记录", response.text)
        self.assertIn("长文字识别完成后，这里会展示日期分组、识别到的规则和加入记录数摘要。", response.text)
        self.assertIn("价格口径", response.text)
        self.assertIn("精简结论", response.text)
        self.assertIn("复盘概览", response.text)
        self.assertIn("亏损特征", response.text)
        self.assertIn("盈利特征", response.text)
        self.assertIn("优化目标分版本", response.text)
        self.assertIn("单笔反事实复盘", response.text)
        self.assertIn("旧新参数对比", response.text)
        self.assertIn("指标条件替换", response.text)
        self.assertIn("当前样本成交记录", response.text)

    def test_replay_analysis_for_single_side_sample_uses_single_direction_summary(self) -> None:
        client = self._build_client()
        self._login(client)
        csv_text = (
            "symbol,side,entry_time,exit_time,pnl\n"
            "600519.SH,long,2024-05-01T10:00:00Z,2024-05-01T11:00:00Z,150\n"
            "510300.SH,long,2024-05-03T08:00:00Z,2024-05-03T10:30:00Z,60\n"
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
            },
        )
        analysis_id = created.json()["data"]["analysis_id"]
        fetched = client.get(f"/api/v1/replays/analyses/{analysis_id}")

        self.assertEqual(200, fetched.status_code)
        data = fetched.json()["data"]
        self.assertIn("当前样本全部为买入后卖出交易", data["summary"])
        self.assertNotIn("需要重点优化的是买入后卖出交易", data["summary"])
        self.assertEqual("当前样本尚未形成可比较的方向差异", data["losing_patterns"][0]["pattern"])
        self.assertEqual("只在日线趋势同向时入场", data["suggestion_rules"][0]["title"])
        self.assertEqual("加入量能和弱开过滤", data["suggestion_rules"][1]["title"])
        self.assertEqual("收紧止损并缩短持有周期", data["suggestion_rules"][2]["title"])
        self.assertEqual(
            1.2,
            data["suggestion_rules"][1]["dsl_patch"]["filters"]["volume_confirmation"]["value"],
        )
        self.assertEqual(
            -0.02,
            data["suggestion_rules"][2]["dsl_patch"]["risk"]["stop_loss_pct"],
        )

    def test_replay_analysis_avoids_short_suggestions_for_cn_equity_uploads(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_path = Path(temp_dir.name) / "quant_platform.db"
        client = self._build_client(
            database_url=f"sqlite+pysqlite:///{database_path}",
        )
        self._login(client)
        csv_text = (
            "symbol,side,entry_time,exit_time,pnl\n"
            "600519.SH,long,2024-05-01T10:00:00Z,2024-05-01T11:00:00Z,150\n"
            "000001.SZ,short,2024-05-02T09:00:00Z,2024-05-02T14:00:00Z,-80\n"
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
            },
        )
        analysis_id = created.json()["data"]["analysis_id"]
        fetched = client.get(f"/api/v1/replays/analyses/{analysis_id}")

        self.assertEqual(200, fetched.status_code)
        data = fetched.json()["data"]
        self.assertIn("买入后卖出交易", data["summary"])
        self.assertIn("反向卖出记录", data["summary"])
        self.assertNotIn("建议做空", json.dumps(data, ensure_ascii=False))
        self.assertEqual("反向卖出记录当前是主要拖累方向", data["losing_patterns"][0]["pattern"])
        self.assertEqual("先核对反向记录来源", data["suggestion_rules"][0]["title"])

    def test_replay_analysis_uses_crypto_specific_single_side_suggestions(self) -> None:
        client = self._build_client()
        self._login(client)
        csv_text = (
            "symbol,side,entry_time,exit_time,pnl\n"
            "BTCUSDT,long,2024-05-01T10:00:00Z,2024-05-01T11:00:00Z,150\n"
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
            },
        )
        analysis_id = created.json()["data"]["analysis_id"]
        fetched = client.get(f"/api/v1/replays/analyses/{analysis_id}")

        self.assertEqual(200, fetched.status_code)
        data = fetched.json()["data"]
        self.assertIn("当前样本全部为做多交易", data["summary"])
        self.assertEqual("只在更高周期趋势一致时追随动量", data["suggestion_rules"][0]["title"])
        self.assertEqual(
            "15m",
            data["suggestion_rules"][0]["dsl_patch"]["filters"]["trend_confirmation"]["entry_timeframe"],
        )
        self.assertEqual("增加波动率过滤和更短的保护止损", data["suggestion_rules"][1]["title"])

    def test_private_resource_endpoints_require_login(self) -> None:
        client = self._build_client()

        response = client.get("/api/v1/strategies/projects")
        upload_response = client.post(
            "/api/v1/trades/uploads",
            files={"file": ("trades.csv", b"symbol,side,entry_time,exit_time,pnl\n", "text/csv")},
        )

        self.assertEqual(401, response.status_code)
        self.assertEqual("UNAUTHORIZED", response.json()["error"]["code"])
        self.assertEqual(401, upload_response.status_code)
        self.assertEqual("UNAUTHORIZED", upload_response.json()["error"]["code"])

    def test_user_only_sees_own_projects_backtests_and_uploads(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_url = f"sqlite+pysqlite:///{Path(temp_dir.name) / 'quant_platform.db'}"

        owner_client = self._build_client(database_url=database_url)
        self._login(owner_client)
        project = owner_client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "用户一策略",
                "natural_language_prompt": "均线上穿买入",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]
        upload = owner_client.post(
            "/api/v1/trades/uploads",
            files={"file": ("trades.csv", b"symbol,side,entry_time,exit_time,pnl\nBTCUSDT,long,2024-05-01T10:00:00Z,2024-05-01T11:00:00Z,1\n", "text/csv")},
        ).json()["data"]
        owner_client.post(
            "/api/v1/backtests/runs",
            json={
                "strategy_version_id": project["version_id"],
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
                "data_snapshot": {"dataset_snapshot_ref": "owner_only_snapshot"},
            },
        )

        other_client = self._build_client(database_url=database_url)
        self._register_and_login(
            other_client,
            username="other_user",
            contact="other@example.com",
        )

        projects_response = other_client.get("/api/v1/strategies/projects")
        backtests_response = other_client.get("/api/v1/backtests/runs")
        project_get_response = other_client.get(f"/api/v1/strategies/projects/{project['version_id']}")
        records_response = other_client.get(f"/api/v1/trades/uploads/{upload['upload_id']}/records")

        self.assertEqual([], projects_response.json()["data"]["items"])
        self.assertEqual([], backtests_response.json()["data"]["items"])
        self.assertEqual(404, project_get_response.status_code)
        self.assertEqual(404, records_response.status_code)

    def test_user_cannot_compare_other_users_backtests(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_url = f"sqlite+pysqlite:///{Path(temp_dir.name) / 'quant_platform.db'}"

        owner_client = self._build_client(database_url=database_url)
        self._login(owner_client)
        version_id = owner_client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "私有回测策略",
                "natural_language_prompt": "均线上穿时买入",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]
        first = owner_client.post(
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
                "data_snapshot": {"dataset_snapshot_ref": "private_compare_a"},
            },
        ).json()["data"]["backtest_run_id"]
        second = owner_client.post(
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
                    "fee_bps": 5,
                    "slippage_bps": 3,
                    "fill_price_rule": "same_bar_close",
                    "intrabar_match_policy": "intrabar_touch_fill",
                    "calendar": "cn_a_share",
                    "timezone": "Asia/Shanghai",
                    "adjustment_mode": "raw",
                },
                "data_snapshot": {"dataset_snapshot_ref": "private_compare_b"},
            },
        ).json()["data"]["backtest_run_id"]

        other_client = self._build_client(database_url=database_url)
        self._register_and_login(
            other_client,
            username="compare_other",
            contact="compare_other@example.com",
        )

        response = other_client.get(
            "/api/v1/backtests/compare",
            params=[("run_ids", first), ("run_ids", second)],
        )

        self.assertEqual(404, response.status_code)
        self.assertEqual("NOT_FOUND", response.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
