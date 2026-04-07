from __future__ import annotations

import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
API_SRC = WORKSPACE_ROOT / "apps" / "api" / "src"
VENV_LIB = WORKSPACE_ROOT / ".venv" / "lib"

if API_SRC.exists() and str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

if VENV_LIB.exists():
    for site_packages in VENV_LIB.glob("python*/site-packages"):
        if str(site_packages) not in sys.path:
            sys.path.insert(0, str(site_packages))

from quant_platform_api.market_data import (  # noqa: E402
    AkshareMarketDataProvider,
    ClickHouseMarketDataProvider,
    MarketBar,
    MarketDataCacheRepository,
    MarketDataService,
    infer_asset_type,
)


class _StubProvider:
    def __init__(self) -> None:
        self.name = "stub-provider"
        self.calls = 0

    def fetch_daily_bars(
        self,
        *,
        ts_code: str,
        asset_type: str,
        start_date: str,
        end_date: str,
        adjustment_mode: str,
    ) -> list[MarketBar]:
        self.calls += 1
        return [
            MarketBar(
                ts_code=ts_code,
                asset_type=asset_type,
                adjustment_mode=adjustment_mode,
                trade_date="2024-01-02",
                open=10.0,
                high=10.5,
                low=9.8,
                close=10.2,
                volume=1000.0,
                amount=10200.0,
                pct_chg=None,
                turnover=None,
                data_source=self.name,
                fetched_at="2026-03-30T10:00:00",
            ),
            MarketBar(
                ts_code=ts_code,
                asset_type=asset_type,
                adjustment_mode=adjustment_mode,
                trade_date="2024-01-03",
                open=10.2,
                high=10.8,
                low=10.0,
                close=10.5,
                volume=1200.0,
                amount=12600.0,
                pct_chg=2.94,
                turnover=None,
                data_source=self.name,
                fetched_at="2026-03-30T10:00:00",
            ),
        ]


class _PrimaryFeedStub:
    name = "internal_clickhouse_dwd"

    def describe_market_feed(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "configured": True,
            "preferred_layer": "dwd",
            "latest_trade_date": "2026-04-03",
        }


class MarketDataTests(unittest.TestCase):
    def test_infer_asset_type_detects_etf_prefix(self) -> None:
        self.assertEqual("etf", infer_asset_type("510300.SH"))
        self.assertEqual("stock", infer_asset_type("600519.SH"))

    def test_market_data_service_caches_ranges_in_separate_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = _StubProvider()
            service = MarketDataService(
                cache_repository=MarketDataCacheRepository(
                    str(Path(temp_dir) / "market_data.db")
                ),
                primary_provider=None,
                fallback_provider=provider,
            )

            first_rows, first_meta = service.load_daily_bars(
                ts_code="600519.SH",
                asset_type="stock",
                start_date=pd.Timestamp("2024-01-02").date(),
                end_date=pd.Timestamp("2024-01-03").date(),
                adjustment_mode="qfq",
            )
            second_rows, second_meta = service.load_daily_bars(
                ts_code="600519.SH",
                asset_type="stock",
                start_date=pd.Timestamp("2024-01-02").date(),
                end_date=pd.Timestamp("2024-01-03").date(),
                adjustment_mode="qfq",
            )

        self.assertEqual(1, provider.calls)
        self.assertEqual(2, len(first_rows))
        self.assertEqual(2, len(second_rows))
        self.assertFalse(first_meta["served_from_cache"])
        self.assertTrue(second_meta["served_from_cache"])
        self.assertEqual("stub-provider", second_meta["provider"])

    def test_market_data_cache_database_contains_shared_market_schema_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "market_data.db"
            provider = _StubProvider()
            service = MarketDataService(
                cache_repository=MarketDataCacheRepository(str(database_path)),
                primary_provider=None,
                fallback_provider=provider,
            )

            service.load_daily_bars(
                ts_code="600519.SH",
                asset_type="stock",
                start_date=pd.Timestamp("2024-01-02").date(),
                end_date=pd.Timestamp("2024-01-03").date(),
                adjustment_mode="qfq",
            )

            with sqlite3.connect(database_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                coverage = connection.execute(
                    """
                    SELECT market, frequency, adjustment_mode, coverage_status
                    FROM coverage_stats
                    WHERE instrument_id = ?
                    """,
                    ("600519.SH",),
                ).fetchone()
                ingest_batch = connection.execute(
                    "SELECT status FROM ingest_batches LIMIT 1"
                ).fetchone()

        for table_name in {
            "instruments",
            "trading_calendar",
            "ingest_batches",
            "market_bars",
            "sync_ranges",
            "coverage_stats",
            "correction_batches",
        }:
            self.assertIn(table_name, tables)
        self.assertEqual(("cn_sh", "1d", "qfq", "ready"), coverage)
        self.assertEqual(("completed",), ingest_batch)

    def test_akshare_provider_transforms_tencent_history_for_stock(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2024-01-02").date(),
                    "open": 1608.69,
                    "close": 1578.69,
                    "high": 1611.88,
                    "low": 1571.79,
                    "amount": 32156.0,
                },
                {
                    "date": pd.Timestamp("2024-01-03").date(),
                    "open": 1574.8,
                    "close": 1587.69,
                    "high": 1588.91,
                    "low": 1570.02,
                    "amount": 20229.0,
                },
            ]
        )
        provider = AkshareMarketDataProvider()

        with patch("akshare.stock_zh_a_hist_tx", return_value=frame):
            rows = provider.fetch_daily_bars(
                ts_code="600519.SH",
                asset_type="stock",
                start_date="20240101",
                end_date="20240131",
                adjustment_mode="qfq",
            )

        self.assertEqual(2, len(rows))
        self.assertEqual("2024-01-02", rows[0].trade_date)
        self.assertEqual(3215600.0, rows[0].volume)
        self.assertEqual("akshare_tencent", rows[0].data_source)
        self.assertAlmostEqual(0.5701, rows[1].pct_chg or 0.0, places=4)

    def test_akshare_provider_falls_back_to_sina_for_etf(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2024-01-02").date(),
                    "open": 3.22,
                    "high": 3.25,
                    "low": 3.20,
                    "close": 3.24,
                    "volume": 9429306,
                    "amount": 3285755392,
                },
                {
                    "date": pd.Timestamp("2024-01-03").date(),
                    "open": 3.24,
                    "high": 3.27,
                    "low": 3.21,
                    "close": 3.26,
                    "volume": 8000000,
                    "amount": 2600000000,
                },
            ]
        )
        provider = AkshareMarketDataProvider()

        with patch("akshare.stock_zh_a_hist_tx", return_value=pd.DataFrame()), patch(
            "akshare.fund_etf_hist_sina",
            return_value=frame,
        ):
            rows = provider.fetch_daily_bars(
                ts_code="510300.SH",
                asset_type="etf",
                start_date="20240101",
                end_date="20240131",
                adjustment_mode="qfq",
            )

        self.assertEqual(2, len(rows))
        self.assertEqual("akshare_sina_etf", rows[0].data_source)
        self.assertEqual(9429306.0, rows[0].volume)
        self.assertEqual("2024-01-03", rows[1].trade_date)

    def test_clickhouse_provider_can_build_qfq_prices_from_dwd_rows(self) -> None:
        provider = ClickHouseMarketDataProvider(
            host="127.0.0.1",
            port=8123,
            username="root",
            password="secret",
        )
        sample_rows = [
            {
                "trade_date": "2024-01-02",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "pre_close": 10.0,
                "pct_change": 5.0,
                "volume": 1000.0,
                "amount": 10000.0,
                "turnover_rate": 1.2,
                "adj_factor": 2.0,
                "limit_up_price": 11.0,
                "limit_down_price": 9.0,
                "is_suspended": 0,
                "is_limit_up": 0,
                "is_limit_down": 0,
                "sync_time": "2026-04-07T09:00:00",
            },
            {
                "trade_date": "2024-01-03",
                "open": 12.0,
                "high": 13.0,
                "low": 11.0,
                "close": 12.0,
                "pre_close": 10.5,
                "pct_change": 14.2,
                "volume": 1200.0,
                "amount": 14400.0,
                "turnover_rate": 1.3,
                "adj_factor": 4.0,
                "limit_up_price": 13.2,
                "limit_down_price": 10.8,
                "is_suspended": 0,
                "is_limit_up": 1,
                "is_limit_down": 0,
                "sync_time": "2026-04-07T09:00:00",
            },
        ]

        with patch.object(provider, "_query_daily_rows", return_value=sample_rows):
            rows = provider.fetch_daily_bars(
                ts_code="600519.SH",
                asset_type="stock",
                start_date="20240102",
                end_date="20240103",
                adjustment_mode="qfq",
            )

        self.assertEqual(2, len(rows))
        self.assertAlmostEqual(5.0, rows[0].open)
        self.assertAlmostEqual(5.5, rows[0].high)
        self.assertAlmostEqual(5.25, rows[0].close)
        self.assertAlmostEqual(12.0, rows[1].close)
        self.assertTrue(rows[1].is_limit_up)
        self.assertEqual("internal_clickhouse_dwd", rows[0].data_source)

    def test_market_data_service_describe_pipeline_exposes_primary_feed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MarketDataService(
                cache_repository=MarketDataCacheRepository(
                    str(Path(temp_dir) / "market_data.db")
                ),
                primary_provider=_PrimaryFeedStub(),
                fallback_provider=_StubProvider(),
            )

            pipeline = service.describe_pipeline()

        self.assertEqual("internal_clickhouse_dwd", pipeline["preferred_provider"])
        self.assertEqual("dwd", pipeline["primary_feed"]["preferred_layer"])
        self.assertEqual("2026-04-03", pipeline["primary_feed"]["latest_trade_date"])
