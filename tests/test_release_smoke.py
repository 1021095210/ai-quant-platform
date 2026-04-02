from __future__ import annotations

import sys
import tempfile
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
class ReleaseSmokeTests(unittest.TestCase):
    def _build_client(self) -> TestClient:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        settings = Settings(
            database_url=f"sqlite+pysqlite:///{Path(temp_dir.name) / 'quant_platform.db'}",
            market_data_database_path=str(Path(temp_dir.name) / "market_data.db"),
            market_data_provider="demo",
            job_execution_mode="immediate",
        )
        return TestClient(create_app(settings))

    def _login(
        self,
        client: TestClient,
        *,
        username: str = "1111",
        password: str = "618618",
    ) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(200, response.status_code)

    def test_healthz_returns_ok(self) -> None:
        client = self._build_client()

        response = client.get("/healthz")

        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", response.json()["data"]["status"])

    def test_rules_page_is_accessible_after_login(self) -> None:
        client = self._build_client()
        self._login(client)

        response = client.get("/rules")

        self.assertEqual(200, response.status_code)
        self.assertIn("默认研究规则", response.text)

    def test_admin_summary_is_accessible_for_admin(self) -> None:
        client = self._build_client()
        self._login(client, username="admin", password="618618")

        response = client.get("/api/v1/admin/summary")

        self.assertEqual(200, response.status_code)
        self.assertIn("counts", response.json()["data"])
        self.assertIn("recent_users", response.json()["data"])

    def test_backtest_compare_flow_smoke(self) -> None:
        client = self._build_client()
        self._login(client)
        version_id = client.post(
            "/api/v1/strategies/projects",
            json={
                "title": "发布前烟雾策略",
                "natural_language_prompt": "均线上穿时买入",
                "strategy_dsl": {"market": "600519.SH", "timeframe": "1d", "asset_type": "stock"},
                "strategy_python": "def build_strategy():\n    return {}",
            },
        ).json()["data"]["version_id"]

        run_ids: list[str] = []
        for snapshot_ref, fill_rule in [
            ("release_smoke_a", "next_bar_open"),
            ("release_smoke_b", "same_bar_close"),
        ]:
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
                        "initial_capital": 100000,
                        "fee_bps": 3,
                        "slippage_bps": 2,
                        "fill_price_rule": fill_rule,
                        "intrabar_match_policy": "no_intrabar_fill",
                        "calendar": "cn_a_share",
                        "timezone": "Asia/Shanghai",
                        "adjustment_mode": "qfq",
                    },
                    "data_snapshot": {"dataset_snapshot_ref": snapshot_ref},
                },
            )
            self.assertEqual(202, response.status_code)
            run_ids.append(response.json()["data"]["backtest_run_id"])

        comparison = client.get(
            "/api/v1/backtests/compare",
            params=[("run_ids", run_ids[0]), ("run_ids", run_ids[1])],
        )

        self.assertEqual(200, comparison.status_code)
        self.assertEqual(2, len(comparison.json()["data"]["items"]))


if __name__ == "__main__":
    unittest.main()
