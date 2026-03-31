from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from quant_platform_api.market_data import MarketBar


def run_backtest(
    *,
    strategy_spec: dict[str, Any],
    bars: list[MarketBar],
    execution_contract: dict[str, Any],
) -> dict[str, Any]:
    if len(bars) < 30:
        return {
            "metrics": {
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "trade_count": 0,
            },
            "equity_curve": [],
            "trades": [],
        }

    data_frame = pd.DataFrame([asdict(item) for item in bars]).sort_values("trade_date")
    data_frame["trade_date"] = pd.to_datetime(data_frame["trade_date"])
    data_frame["close"] = data_frame["close"].astype(float)
    data_frame["open"] = data_frame["open"].astype(float)
    data_frame["high"] = data_frame["high"].astype(float)
    data_frame["low"] = data_frame["low"].astype(float)
    data_frame["volume"] = data_frame["volume"].astype(float)

    entry_rules = strategy_spec.get("entry", {}).get("all", [])
    data_frame["entry_signal"] = True
    for rule in entry_rules:
        data_frame["entry_signal"] &= _compute_rule_signal(data_frame, rule)

    initial_capital = float(execution_contract["initial_capital"])
    fee_rate = float(execution_contract["fee_bps"]) / 10000.0
    slippage_rate = float(execution_contract["slippage_bps"]) / 10000.0
    take_profit = _extract_exit_threshold(strategy_spec, "take_profit_pct", 0.08)
    stop_loss = _extract_exit_threshold(strategy_spec, "stop_loss_pct", -0.03)

    capital = initial_capital
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    current_trade: dict[str, Any] | None = None
    peak_equity = initial_capital
    max_drawdown_pct = 0.0

    for _, row in data_frame.iterrows():
        trade_date = row["trade_date"]
        price = float(row["close"])
        if current_trade is not None:
            mark_to_market = capital * (price / current_trade["entry_price"])
            current_equity = mark_to_market
        else:
            current_equity = capital

        peak_equity = max(peak_equity, current_equity)
        drawdown_pct = ((current_equity - peak_equity) / peak_equity) * 100.0
        max_drawdown_pct = min(max_drawdown_pct, drawdown_pct)
        equity_curve.append(
            {
                "ts": trade_date.strftime("%Y-%m-%d"),
                "equity": round(current_equity, 2),
            }
        )

        if current_trade is None and bool(row["entry_signal"]):
            entry_price = price * (1.0 + slippage_rate)
            current_trade = {
                "entry_time": trade_date.strftime("%Y-%m-%d"),
                "entry_price": entry_price,
                "symbol": strategy_spec.get("market"),
                "side": strategy_spec.get("position", {}).get("side", "long"),
            }
            continue

        if current_trade is None:
            continue

        gross_return = (price - current_trade["entry_price"]) / current_trade["entry_price"]
        if gross_return >= take_profit or gross_return <= stop_loss:
            net_return = gross_return - fee_rate * 2 - slippage_rate
            pnl = capital * net_return
            exit_price = price * (1.0 - slippage_rate)
            capital = capital + pnl
            trades.append(
                {
                    "symbol": current_trade["symbol"],
                    "side": current_trade["side"],
                    "entry_time": current_trade["entry_time"],
                    "exit_time": trade_date.strftime("%Y-%m-%d"),
                    "entry_price": round(current_trade["entry_price"], 4),
                    "exit_price": round(exit_price, 4),
                    "pnl": round(pnl, 2),
                    "return_pct": round(net_return * 100.0, 2),
                    "exit_reason": "take_profit" if gross_return >= take_profit else "stop_loss",
                }
            )
            current_trade = None

    if current_trade is not None:
        final_row = data_frame.iloc[-1]
        final_price = float(final_row["close"]) * (1.0 - slippage_rate)
        gross_return = (final_price - current_trade["entry_price"]) / current_trade["entry_price"]
        net_return = gross_return - fee_rate * 2 - slippage_rate
        pnl = capital * net_return
        capital = capital + pnl
        trades.append(
            {
                "symbol": current_trade["symbol"],
                "side": current_trade["side"],
                "entry_time": current_trade["entry_time"],
                "exit_time": final_row["trade_date"].strftime("%Y-%m-%d"),
                "entry_price": round(current_trade["entry_price"], 4),
                "exit_price": round(final_price, 4),
                "pnl": round(pnl, 2),
                "return_pct": round(net_return * 100.0, 2),
                "exit_reason": "end_of_range",
            }
        )

    metrics = _build_metrics(initial_capital, capital, trades, max_drawdown_pct)
    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
    }


def _compute_rule_signal(data_frame: pd.DataFrame, rule: dict[str, Any]) -> pd.Series:
    indicator = rule.get("indicator")
    params = rule.get("params", {})
    value = rule.get("value")
    if indicator == "sma_cross":
        fast = int(params.get("fast", 5))
        slow = int(params.get("slow", 20))
        fast_series = data_frame["close"].rolling(window=fast).mean()
        slow_series = data_frame["close"].rolling(window=slow).mean()
        return (fast_series > slow_series) & (fast_series.shift(1) <= slow_series.shift(1))
    if indicator == "volume_ratio":
        period = int(params.get("period", 10))
        baseline = data_frame["volume"].rolling(window=period).mean()
        return (data_frame["volume"] / baseline) > float(value)
    if indicator == "rsi":
        period = int(params.get("period", 14))
        delta = data_frame["close"].diff()
        gain = delta.clip(lower=0).rolling(window=period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        return rsi < float(value)
    if indicator == "price_breakout":
        lookback = int(params.get("lookback", 20))
        breakout_line = data_frame["high"].rolling(window=lookback).max().shift(1)
        return data_frame["close"] >= breakout_line
    return pd.Series([False] * len(data_frame), index=data_frame.index)


def _extract_exit_threshold(
    strategy_spec: dict[str, Any],
    indicator_name: str,
    default_value: float,
) -> float:
    exit_rules = strategy_spec.get("exit", {}).get("any", [])
    for rule in exit_rules:
        if rule.get("indicator") == indicator_name:
            return float(rule.get("value", default_value))
    return default_value


def _build_metrics(
    initial_capital: float,
    final_capital: float,
    trades: list[dict[str, Any]],
    max_drawdown_pct: float,
) -> dict[str, Any]:
    total_return_pct = ((final_capital - initial_capital) / initial_capital) * 100.0
    trade_count = len(trades)
    wins = [item for item in trades if item["pnl"] > 0]
    losses = [item for item in trades if item["pnl"] <= 0]
    total_profit = sum(item["pnl"] for item in wins)
    total_loss = abs(sum(item["pnl"] for item in losses))
    profit_factor = (total_profit / total_loss) if total_loss else float(len(wins) > 0)
    win_rate_pct = (len(wins) / trade_count * 100.0) if trade_count else 0.0
    return {
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "win_rate_pct": round(win_rate_pct, 2),
        "profit_factor": round(profit_factor, 2) if trade_count else 0.0,
        "trade_count": trade_count,
    }
