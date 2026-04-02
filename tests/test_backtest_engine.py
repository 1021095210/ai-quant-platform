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

from quant_platform_api.backtest_engine import run_backtest
from quant_platform_api.market_data import MarketBar


class BacktestEngineTests(unittest.TestCase):
    def test_intrabar_fill_obeys_t_plus_zero_and_t_plus_one(self) -> None:
        bars = [
            self._bar("2024-01-01T09:30:00", 100.0, 101.0, 99.0, 100.0),
            self._bar("2024-01-01T14:30:00", 100.0, 110.0, 99.0, 105.0),
            self._bar("2024-01-02T09:30:00", 105.0, 110.0, 104.0, 109.0),
        ]
        for index in range(3, 31):
            bars.append(
                self._bar(
                    f"2024-01-{index:02d}T09:30:00",
                    100.0 + index,
                    101.0 + index,
                    99.0 + index,
                    100.5 + index,
                )
            )

        strategy_spec = {
            "market": "TEST.SH",
            "asset_type": "stock",
            "position": {"side": "long"},
            "entry": {"all": []},
            "exit": {"any": []},
        }
        base_contract = {
            "initial_capital": 100000,
            "fee_bps": 0,
            "slippage_bps": 0,
            "fill_price_rule": "same_bar_close",
            "intrabar_match_policy": "intrabar_touch_fill",
            "calendar": "cn_a_share",
            "timezone": "Asia/Shanghai",
            "adjustment_mode": "qfq",
            "warmup_bars": 0,
            "position_sizing": {
                "mode": "fixed_quantity",
                "value": 100,
                "max_positions": 1,
                "max_position_pct": 1.0,
                "min_trade_unit": 1,
            },
            "risk_controls": {
                "take_profit_pct": 0.05,
                "stop_loss_pct": -0.05,
                "max_drawdown_pct": -0.5,
                "max_holding_bars": 20,
            },
        }

        result_t0 = run_backtest(
            strategy_spec=strategy_spec,
            bars=bars,
            execution_contract={
                **base_contract,
                "settlement_policy": "t_plus_zero",
                "same_day_exit_allowed": True,
            },
        )
        result_t1 = run_backtest(
            strategy_spec=strategy_spec,
            bars=bars,
            execution_contract={
                **base_contract,
                "settlement_policy": "t_plus_one",
                "same_day_exit_allowed": False,
            },
        )

        self.assertEqual("2024-01-01T14:30:00", result_t0["trades"][0]["exit_time"])
        self.assertEqual("take_profit_intrabar", result_t0["trades"][0]["exit_reason"])
        self.assertEqual("2024-01-02T09:30:00", result_t1["trades"][0]["exit_time"])
        self.assertEqual("take_profit_intrabar", result_t1["trades"][0]["exit_reason"])

    @staticmethod
    def _bar(trade_date: str, open_price: float, high: float, low: float, close: float) -> MarketBar:
        return MarketBar(
            ts_code="TEST.SH",
            asset_type="stock",
            adjustment_mode="qfq",
            trade_date=trade_date,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=1000.0,
            amount=100000.0,
            pct_chg=0.0,
            turnover=0.0,
            data_source="test",
            fetched_at="2024-01-01T00:00:00",
        )


if __name__ == "__main__":
    unittest.main()
