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
                "final_equity": round(float(execution_contract["initial_capital"]), 2),
                "avg_trade_return_pct": 0.0,
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
    fill_price_rule = execution_contract.get("fill_price_rule", "next_bar_open")
    intrabar_match_policy = execution_contract.get(
        "intrabar_match_policy",
        "no_intrabar_fill",
    )
    warmup_bars = max(int(execution_contract.get("warmup_bars", 20)), 0)
    same_day_exit_allowed = bool(
        execution_contract.get(
            "same_day_exit_allowed",
            execution_contract.get("settlement_policy", "t_plus_zero") != "t_plus_one",
        )
    )
    position_sizing = execution_contract.get("position_sizing", {})
    risk_controls = execution_contract.get("risk_controls", {})
    take_profit = float(
        risk_controls.get(
            "take_profit_pct",
            _extract_exit_threshold(strategy_spec, "take_profit_pct", 0.08),
        )
    )
    stop_loss = float(
        risk_controls.get(
            "stop_loss_pct",
            _extract_exit_threshold(strategy_spec, "stop_loss_pct", -0.03),
        )
    )
    max_drawdown_limit = float(risk_controls.get("max_drawdown_pct", -0.12))
    max_holding_bars = max(int(risk_controls.get("max_holding_bars", 40)), 1)

    cash = initial_capital
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    current_trade: dict[str, Any] | None = None
    pending_entry: dict[str, Any] | None = None
    peak_equity = initial_capital
    max_drawdown_pct = 0.0
    halted_by_drawdown = False

    for index, row in data_frame.iterrows():
        trade_date = row["trade_date"]
        close_price = float(row["close"])
        open_price = float(row["open"])

        if pending_entry is not None and current_trade is None and not halted_by_drawdown:
            entry_price = _apply_slippage(open_price, slippage_rate, side="entry")
            quantity = _resolve_quantity(
                cash=cash,
                equity=cash,
                entry_price=entry_price,
                position_sizing=position_sizing,
            )
            entry_notional = quantity * entry_price
            entry_fee = entry_notional * fee_rate
            if quantity > 0 and entry_notional + entry_fee <= cash:
                cash -= entry_notional + entry_fee
                current_trade = {
                    "entry_time": _format_trade_timestamp(trade_date),
                    "entry_signal_time": pending_entry["signal_time"],
                    "entry_price": entry_price,
                    "quantity": quantity,
                    "entry_notional": round(entry_notional, 2),
                    "symbol": strategy_spec.get("market"),
                    "side": strategy_spec.get("position", {}).get("side", "long"),
                    "entry_index": index,
                    "entry_timestamp": trade_date,
                }
            pending_entry = None

        if current_trade is not None:
            current_equity = cash + current_trade["quantity"] * close_price
        else:
            current_equity = cash

        peak_equity = max(peak_equity, current_equity)
        drawdown_pct = ((current_equity - peak_equity) / peak_equity) * 100.0
        max_drawdown_pct = min(max_drawdown_pct, drawdown_pct)
        equity_curve.append(
            {
                "ts": trade_date.strftime("%Y-%m-%d"),
                "equity": round(current_equity, 2),
            }
        )

        force_exit_reason: str | None = None
        if drawdown_pct <= max_drawdown_limit:
            halted_by_drawdown = True
            if current_trade is not None:
                force_exit_reason = "max_drawdown_guard"

        if current_trade is not None:
            can_exit_today = _can_exit_on_timestamp(
                current_timestamp=trade_date,
                entry_timestamp=current_trade["entry_timestamp"],
                same_day_exit_allowed=same_day_exit_allowed,
            )
            gross_return = (
                (close_price - current_trade["entry_price"]) / current_trade["entry_price"]
            )
            holding_bars = index - current_trade["entry_index"] + 1
            exit_reason = force_exit_reason if can_exit_today else None
            exit_price = close_price
            if exit_reason is None and can_exit_today and intrabar_match_policy == "intrabar_touch_fill":
                intrabar_exit = _resolve_intrabar_exit(
                    entry_price=current_trade["entry_price"],
                    high_price=float(row["high"]),
                    low_price=float(row["low"]),
                    take_profit_pct=take_profit,
                    stop_loss_pct=stop_loss,
                    slippage_rate=slippage_rate,
                )
                if intrabar_exit is not None:
                    exit_reason = intrabar_exit["exit_reason"]
                    exit_price = intrabar_exit["exit_price"]
            if exit_reason is None and can_exit_today and gross_return >= take_profit:
                exit_reason = "take_profit"
            if exit_reason is None and can_exit_today and gross_return <= stop_loss:
                exit_reason = "stop_loss"
            if exit_reason is None and can_exit_today and holding_bars >= max_holding_bars:
                exit_reason = "max_holding_bars"
            if exit_reason is not None:
                if exit_reason not in {"take_profit_intrabar", "stop_loss_intrabar"}:
                    exit_price = _apply_slippage(close_price, slippage_rate, side="exit")
                trade_result = _close_trade(
                    trade=current_trade,
                    exit_price=exit_price,
                    exit_time=_format_trade_timestamp(trade_date),
                    exit_reason=exit_reason,
                    fee_rate=fee_rate,
                    holding_bars=holding_bars,
                )
                cash += trade_result["cash_delta"]
                trades.append(trade_result["trade"])
                current_trade = None
                continue

        if (
            current_trade is None
            and pending_entry is None
            and not halted_by_drawdown
            and index >= warmup_bars
            and bool(row["entry_signal"])
        ):
            if fill_price_rule == "same_bar_close":
                entry_price = _apply_slippage(close_price, slippage_rate, side="entry")
                quantity = _resolve_quantity(
                    cash=cash,
                    equity=current_equity,
                    entry_price=entry_price,
                    position_sizing=position_sizing,
                )
                entry_notional = quantity * entry_price
                entry_fee = entry_notional * fee_rate
                if quantity > 0 and entry_notional + entry_fee <= cash:
                    cash -= entry_notional + entry_fee
                    current_trade = {
                        "entry_time": _format_trade_timestamp(trade_date),
                        "entry_signal_time": _format_trade_timestamp(trade_date),
                        "entry_price": entry_price,
                        "quantity": quantity,
                        "entry_notional": round(entry_notional, 2),
                        "symbol": strategy_spec.get("market"),
                        "side": strategy_spec.get("position", {}).get("side", "long"),
                        "entry_index": index,
                        "entry_timestamp": trade_date,
                    }
            elif index < len(data_frame.index) - 1:
                pending_entry = {"signal_time": _format_trade_timestamp(trade_date)}

    if current_trade is not None:
        final_row = data_frame.iloc[-1]
        trade_result = _close_trade(
            trade=current_trade,
            exit_price=_apply_slippage(float(final_row["close"]), slippage_rate, side="exit"),
            exit_time=_format_trade_timestamp(final_row["trade_date"]),
            exit_reason="end_of_range",
            fee_rate=fee_rate,
            holding_bars=len(data_frame.index) - current_trade["entry_index"],
        )
        cash += trade_result["cash_delta"]
        trades.append(trade_result["trade"])

    metrics = _build_metrics(
        initial_capital,
        cash,
        trades,
        max_drawdown_pct,
        halted_by_drawdown=halted_by_drawdown,
    )
    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
    }


def _apply_slippage(price: float, slippage_rate: float, *, side: str) -> float:
    if side == "entry":
        return price * (1.0 + slippage_rate)
    return price * (1.0 - slippage_rate)


def _can_exit_on_timestamp(
    *,
    current_timestamp: pd.Timestamp,
    entry_timestamp: pd.Timestamp,
    same_day_exit_allowed: bool,
) -> bool:
    if same_day_exit_allowed:
        return True
    return current_timestamp.date() > entry_timestamp.date()


def _resolve_intrabar_exit(
    *,
    entry_price: float,
    high_price: float,
    low_price: float,
    take_profit_pct: float,
    stop_loss_pct: float,
    slippage_rate: float,
) -> dict[str, float | str] | None:
    take_profit_price = entry_price * (1.0 + take_profit_pct)
    stop_loss_price = entry_price * (1.0 + stop_loss_pct)
    stop_hit = low_price <= stop_loss_price
    take_hit = high_price >= take_profit_price
    if stop_hit:
        return {
            "exit_reason": "stop_loss_intrabar",
            "exit_price": _apply_slippage(stop_loss_price, slippage_rate, side="exit"),
        }
    if take_hit:
        return {
            "exit_reason": "take_profit_intrabar",
            "exit_price": _apply_slippage(take_profit_price, slippage_rate, side="exit"),
        }
    return None


def _format_trade_timestamp(value: pd.Timestamp) -> str:
    if value.hour == 0 and value.minute == 0 and value.second == 0:
        return value.strftime("%Y-%m-%d")
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _resolve_quantity(
    *,
    cash: float,
    equity: float,
    entry_price: float,
    position_sizing: dict[str, Any],
) -> int:
    mode = position_sizing.get("mode", "fixed_fraction")
    max_position_pct = min(max(float(position_sizing.get("max_position_pct", 1.0)), 0.01), 1.0)
    min_trade_unit = max(int(position_sizing.get("min_trade_unit", 100)), 1)
    if entry_price <= 0:
        return 0

    if mode == "fixed_quantity":
        requested = max(int(position_sizing.get("value", min_trade_unit)), min_trade_unit)
        quantity = requested
    else:
        fraction = min(max(float(position_sizing.get("value", 1.0)), 0.01), 1.0)
        target_notional = min(cash, equity * max_position_pct, cash * fraction)
        quantity = int(target_notional // entry_price)

    quantity = (quantity // min_trade_unit) * min_trade_unit
    return max(quantity, 0)


def _close_trade(
    *,
    trade: dict[str, Any],
    exit_price: float,
    exit_time: str,
    exit_reason: str,
    fee_rate: float,
    holding_bars: int | None = None,
) -> dict[str, Any]:
    quantity = int(trade["quantity"])
    entry_price = float(trade["entry_price"])
    entry_notional = float(trade["entry_notional"])
    exit_notional = quantity * exit_price
    exit_fee = exit_notional * fee_rate
    pnl = exit_notional - exit_fee - entry_notional
    return_pct = (pnl / entry_notional * 100.0) if entry_notional else 0.0
    resolved_holding_bars = (
        max(int(holding_bars), 1) if holding_bars is not None else max(int(trade.get("holding_bars", 1)), 1)
    )
    return {
        "cash_delta": exit_notional - exit_fee,
        "trade": {
            "symbol": trade["symbol"],
            "side": trade["side"],
            "entry_time": trade["entry_time"],
            "entry_signal_time": trade.get("entry_signal_time"),
            "exit_time": exit_time,
            "entry_price": round(entry_price, 4),
            "exit_price": round(exit_price, 4),
            "quantity": quantity,
            "entry_notional": round(entry_notional, 2),
            "exit_notional": round(exit_notional, 2),
            "pnl": round(pnl, 2),
            "return_pct": round(return_pct, 2),
            "exit_reason": exit_reason,
            "holding_bars": resolved_holding_bars,
        },
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
    *,
    halted_by_drawdown: bool,
) -> dict[str, Any]:
    total_return_pct = ((final_capital - initial_capital) / initial_capital) * 100.0
    trade_count = len(trades)
    wins = [item for item in trades if item["pnl"] > 0]
    losses = [item for item in trades if item["pnl"] <= 0]
    total_profit = sum(item["pnl"] for item in wins)
    total_loss = abs(sum(item["pnl"] for item in losses))
    profit_factor = (total_profit / total_loss) if total_loss else float(len(wins) > 0)
    win_rate_pct = (len(wins) / trade_count * 100.0) if trade_count else 0.0
    avg_trade_return_pct = (
        sum(item["return_pct"] for item in trades) / trade_count if trade_count else 0.0
    )
    return {
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "win_rate_pct": round(win_rate_pct, 2),
        "profit_factor": round(profit_factor, 2) if trade_count else 0.0,
        "trade_count": trade_count,
        "final_equity": round(final_capital, 2),
        "avg_trade_return_pct": round(avg_trade_return_pct, 2),
        "halted_by_drawdown": halted_by_drawdown,
    }
