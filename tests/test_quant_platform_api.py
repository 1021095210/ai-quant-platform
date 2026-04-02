from __future__ import annotations

import sys
import sqlite3
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
        market_data_database_path: str | None = None,
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

        for path in ["/workspace", "/admin", "/strategy", "/indicators", "/rules", "/backtests", "/replay"]:
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

    def test_strategy_page_shows_multi_market_and_multi_timeframe_controls(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/strategy")

        self.assertEqual(200, response.status_code)
        self.assertIn("市场范围", response.text)
        self.assertIn("混合周期观察层", response.text)
        self.assertIn("加密货币", response.text)
        self.assertIn("伦敦金", response.text)

    def test_backtests_page_shows_config_and_snapshot_sections(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/backtests")

        self.assertEqual(200, response.status_code)
        self.assertIn("回测配置摘要", response.text)
        self.assertIn("数据快照摘要", response.text)
        self.assertIn("执行可信度说明", response.text)
        self.assertIn("仓位模式", response.text)
        self.assertIn("最大回撤保护", response.text)
        self.assertIn("盘中撮合策略", response.text)
        self.assertIn("市场成交约束", response.text)
        self.assertIn("滑点说明", response.text)
        self.assertIn("盘中撮合策略说明", response.text)
        self.assertIn("预热Bar数说明", response.text)

    def test_rules_page_uses_collapsible_default_rule_container(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/rules")

        self.assertEqual(200, response.status_code)
        self.assertIn('id="default-rules" class="accordion-list empty-state"', response.text)

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
        self.assertIn("覆盖 A股、美股、加密货币和伦敦金等市场语境", response.text)
        self.assertIn("保存默认规则", response.text)
        self.assertIn("恢复平台默认值", response.text)

    def test_create_strategy_project_returns_project_and_version_ids(self) -> None:
        client = self._build_client()
        self._login(client)

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
        self.assertTrue(data["workspace_id"].startswith("ws_"))
        self.assertTrue(data["user_id"].startswith("user_"))

    def test_list_strategy_projects_returns_created_items(self) -> None:
        client = self._build_client()
        self._login(client)

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
        self.assertTrue(items[0]["workspace_id"].startswith("ws_"))

    def test_get_strategy_project_returns_python_code(self) -> None:
        client = self._build_client()
        self._login(client)
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
        self.assertEqual("long side performed better", data["winning_patterns"][0]["pattern"])
        self.assertTrue(data["suggestion_rules"])

        with sqlite3.connect(database_path) as connection:
            snapshot_row = connection.execute(
                """
                SELECT market, asset_type, frequency, adjustment_mode
                FROM dataset_snapshots
                WHERE dataset_snapshot_ref = ?
                """,
                (data["dataset_snapshot_ref"],),
            ).fetchone()
        self.assertEqual(("cn_a_share", "stock", "1d", "qfq"), snapshot_row)

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


if __name__ == "__main__":
    unittest.main()
