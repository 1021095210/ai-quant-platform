from __future__ import annotations

import sys
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

from quant_platform_api.backtest_engine import run_backtest  # noqa: E402
from quant_platform_api.market_data import MarketBar  # noqa: E402


class BacktestEngineTests(unittest.TestCase):
    def test_backtest_engine_tracks_blocked_entries_and_exits(self) -> None:
        bars: list[MarketBar] = []
        closes = [100.0] * 25 + [102.0, 104.0, 99.0, 98.0, 97.0, 96.0]
        for index, close in enumerate(closes, start=1):
            trade_date = f"2024-01-{index:02d}"
            bars.append(
                MarketBar(
                    ts_code="600519.SH",
                    asset_type="stock",
                    adjustment_mode="raw",
                    trade_date=trade_date,
                    open=close,
                    high=close * 1.01,
                    low=close * 0.99,
                    close=close,
                    volume=100000.0,
                    amount=close * 100000.0,
                    pct_chg=0.0,
                    turnover=1.0,
                    data_source="test",
                    fetched_at="2026-04-07T09:00:00",
                    is_limit_up=index == 26,
                    is_limit_down=index == 28,
                )
            )

        result = run_backtest(
            strategy_spec={
                "market": "600519.SH",
                "position": {"side": "long", "max_positions": 1},
                "entry": {
                    "all": [
                        {
                            "indicator": "price_breakout",
                            "params": {"lookback": 3},
                            "operator": "==",
                            "value": True,
                        }
                    ]
                },
                "exit": {
                    "any": [
                        {"indicator": "stop_loss_pct", "value": -0.01},
                        {"indicator": "take_profit_pct", "value": 0.2},
                    ]
                },
            },
            bars=bars,
            execution_contract={
                "initial_capital": 100000.0,
                "fee_bps": 0,
                "slippage_bps": 0,
                "fill_price_rule": "same_bar_close",
                "intrabar_match_policy": "no_intrabar_fill",
                "calendar": "cn_a_share",
                "timezone": "Asia/Shanghai",
                "adjustment_mode": "raw",
                "settlement_policy": "t_plus_zero",
                "same_day_exit_allowed": True,
                "market_constraint_text": "A股测试规则",
                "position_sizing": {
                    "mode": "fixed_fraction",
                    "value": 1.0,
                    "max_positions": 1,
                    "max_position_pct": 1.0,
                    "min_trade_unit": 100,
                },
                "risk_controls": {
                    "take_profit_pct": 0.2,
                    "stop_loss_pct": -0.01,
                    "max_drawdown_pct": -1.0,
                    "max_holding_bars": 2,
                },
                "warmup_bars": 3,
            },
        )

        self.assertEqual(1, result["execution_summary"]["blocked_entries_limit_up"])
        self.assertEqual(1, result["execution_summary"]["blocked_exits_limit_down"])
        self.assertTrue(result["trades"])


if __name__ == "__main__":
    unittest.main()
