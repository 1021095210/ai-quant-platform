from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from io import StringIO
import sqlite3
from pathlib import Path
from time import sleep
from typing import Any, Protocol


@dataclass(slots=True)
class MarketBar:
    ts_code: str
    asset_type: str
    adjustment_mode: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    pct_chg: float | None
    turnover: float | None
    data_source: str
    fetched_at: str


class MarketDataProvider(Protocol):
    name: str

    def fetch_daily_bars(
        self,
        *,
        ts_code: str,
        asset_type: str,
        start_date: str,
        end_date: str,
        adjustment_mode: str,
    ) -> list[MarketBar]: ...


class TusharePermissionError(RuntimeError):
    pass


class TushareMarketDataProvider:
    name = "tushare"

    def __init__(self, token: str) -> None:
        self._token = token.strip()

    def fetch_daily_bars(
        self,
        *,
        ts_code: str,
        asset_type: str,
        start_date: str,
        end_date: str,
        adjustment_mode: str,
    ) -> list[MarketBar]:
        if not self._token:
            raise TusharePermissionError("missing tushare token")

        import tushare as ts

        pro = ts.pro_api(self._token)
        api_name = "fund_daily" if asset_type == "etf" else "daily"
        fields = "ts_code,trade_date,open,high,low,close,vol,amount,pct_chg"
        try:
            daily_df = getattr(pro, api_name)(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                fields=fields,
            )
        except Exception as exc:  # pragma: no cover - external permission path
            raise TusharePermissionError(str(exc)) from exc

        fetched_at = datetime.utcnow().isoformat()
        rows: list[MarketBar] = []
        for _, item in daily_df.iterrows():
            rows.append(
                MarketBar(
                    ts_code=ts_code,
                    asset_type=asset_type,
                    adjustment_mode=adjustment_mode,
                    trade_date=_format_trade_date(item["trade_date"]),
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item["vol"]),
                    amount=float(item["amount"]),
                    pct_chg=_safe_float(item.get("pct_chg")),
                    turnover=None,
                    data_source=self.name,
                    fetched_at=fetched_at,
                )
            )
        rows.sort(key=lambda item: item.trade_date)
        return rows


class AkshareMarketDataProvider:
    name = "akshare_tencent"

    def fetch_daily_bars(
        self,
        *,
        ts_code: str,
        asset_type: str,
        start_date: str,
        end_date: str,
        adjustment_mode: str,
    ) -> list[MarketBar]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                rows = self._fetch_with_akshare(
                    ts_code=ts_code,
                    asset_type=asset_type,
                    start_date=start_date,
                    end_date=end_date,
                    adjustment_mode=adjustment_mode,
                )
                rows.sort(key=lambda item: item.trade_date)
                return rows
            except Exception as exc:  # pragma: no cover - external retry path
                last_error = exc
                sleep(1 + attempt)
        raise RuntimeError(f"akshare fetch failed: {last_error}") from last_error

    def _fetch_with_akshare(
        self,
        *,
        ts_code: str,
        asset_type: str,
        start_date: str,
        end_date: str,
        adjustment_mode: str,
    ) -> list[MarketBar]:
        import akshare as ak

        symbol = _to_prefixed_symbol(ts_code)
        adjust = "" if adjustment_mode == "raw" else adjustment_mode
        fetched_at = datetime.utcnow().isoformat()
        tx_frame = self._call_tx_history(
            ak=ak,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        rows = self._build_rows_from_tx(
            ts_code=ts_code,
            asset_type=asset_type,
            adjustment_mode=adjustment_mode,
            fetched_at=fetched_at,
            frame=tx_frame,
        )
        if rows:
            return rows

        if asset_type != "etf":
            raise RuntimeError(f"no rows returned for {ts_code}")

        sina_frame = self._call_sina_etf_history(ak=ak, symbol=symbol)
        rows = self._build_rows_from_sina(
            ts_code=ts_code,
            adjustment_mode=adjustment_mode,
            fetched_at=fetched_at,
            frame=sina_frame,
            start_date=start_date,
            end_date=end_date,
        )
        if rows:
            return rows
        raise RuntimeError(f"no rows returned for {ts_code}")

    def _call_tx_history(
        self,
        *,
        ak: Any,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> Any:
        # The upstream helper writes a progress bar to stdout; keep the API logs clean.
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return ak.stock_zh_a_hist_tx(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )

    def _call_sina_etf_history(
        self,
        *,
        ak: Any,
        symbol: str,
    ) -> Any:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return ak.fund_etf_hist_sina(symbol=symbol)

    def _build_rows_from_tx(
        self,
        *,
        ts_code: str,
        asset_type: str,
        adjustment_mode: str,
        fetched_at: str,
        frame: Any,
    ) -> list[MarketBar]:
        rows: list[MarketBar] = []
        previous_close: float | None = None
        for _, item in frame.iterrows():
            volume_lot = _safe_float(item.get("amount")) or 0.0
            volume = volume_lot * 100
            close_price = float(item["close"])
            pct_chg = None
            if previous_close not in (None, 0):
                pct_chg = round(((close_price - previous_close) / previous_close) * 100, 4)
            rows.append(
                MarketBar(
                    ts_code=ts_code,
                    asset_type=asset_type,
                    adjustment_mode=adjustment_mode,
                    trade_date=_format_trade_date(item["date"]),
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=close_price,
                    volume=volume,
                    amount=round(volume * close_price, 4),
                    pct_chg=pct_chg,
                    turnover=None,
                    data_source=self.name,
                    fetched_at=fetched_at,
                )
            )
            previous_close = close_price
        return rows

    def _build_rows_from_sina(
        self,
        *,
        ts_code: str,
        adjustment_mode: str,
        fetched_at: str,
        frame: Any,
        start_date: str,
        end_date: str,
    ) -> list[MarketBar]:
        rows: list[MarketBar] = []
        start_boundary = datetime.strptime(start_date, "%Y%m%d").date()
        end_boundary = datetime.strptime(end_date, "%Y%m%d").date()
        previous_close: float | None = None
        for _, item in frame.iterrows():
            trade_day = item["date"]
            if trade_day < start_boundary or trade_day > end_boundary:
                continue
            close_price = float(item["close"])
            pct_chg = None
            if previous_close not in (None, 0):
                pct_chg = round(((close_price - previous_close) / previous_close) * 100, 4)
            volume = _safe_float(item.get("volume")) or 0.0
            amount = _safe_float(item.get("amount"))
            rows.append(
                MarketBar(
                    ts_code=ts_code,
                    asset_type="etf",
                    adjustment_mode=adjustment_mode,
                    trade_date=_format_trade_date(trade_day),
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=close_price,
                    volume=volume,
                    amount=amount if amount is not None else round(volume * close_price, 4),
                    pct_chg=pct_chg,
                    turnover=None,
                    data_source="akshare_sina_etf",
                    fetched_at=fetched_at,
                )
            )
            previous_close = close_price
        return rows


class DemoMarketDataProvider:
    name = "demo"

    def fetch_daily_bars(
        self,
        *,
        ts_code: str,
        asset_type: str,
        start_date: str,
        end_date: str,
        adjustment_mode: str,
    ) -> list[MarketBar]:
        start = datetime.strptime(start_date, "%Y%m%d").date()
        end = datetime.strptime(end_date, "%Y%m%d").date()
        fetched_at = datetime.utcnow().isoformat()
        rows: list[MarketBar] = []
        current = start
        price = 100.0
        step = 0
        while current <= end:
            if current.weekday() < 5:
                open_price = price
                close_price = price * (1 + (0.002 if step % 5 != 0 else -0.001))
                high_price = max(open_price, close_price) * 1.005
                low_price = min(open_price, close_price) * 0.995
                volume = 1_000_000 + step * 1_000
                rows.append(
                    MarketBar(
                        ts_code=ts_code,
                        asset_type=asset_type,
                        adjustment_mode=adjustment_mode,
                        trade_date=current.strftime("%Y-%m-%d"),
                        open=round(open_price, 4),
                        high=round(high_price, 4),
                        low=round(low_price, 4),
                        close=round(close_price, 4),
                        volume=float(volume),
                        amount=float(volume * close_price),
                        pct_chg=round(((close_price - open_price) / open_price) * 100, 4),
                        turnover=1.0,
                        data_source=self.name,
                        fetched_at=fetched_at,
                    )
                )
                price = close_price
                step += 1
            current = date.fromordinal(current.toordinal() + 1)
        return rows


class MarketDataCacheRepository:
    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._ensure_parent()
        self._ensure_schema()

    def is_range_cached(
        self,
        *,
        ts_code: str,
        asset_type: str,
        adjustment_mode: str,
        start_date: str,
        end_date: str,
    ) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM sync_ranges
                WHERE ts_code = ?
                  AND asset_type = ?
                  AND adjustment_mode = ?
                  AND start_date <= ?
                  AND end_date >= ?
                LIMIT 1
                """,
                (ts_code, asset_type, adjustment_mode, start_date, end_date),
            ).fetchone()
        return row is not None

    def cache_bars(
        self,
        *,
        bars: list[MarketBar],
        ts_code: str,
        asset_type: str,
        adjustment_mode: str,
        start_date: str,
        end_date: str,
        source: str,
    ) -> None:
        ingest_batch_id = self._build_ingest_batch_id(
            ts_code=ts_code,
            asset_type=asset_type,
            adjustment_mode=adjustment_mode,
            start_date=start_date,
            end_date=end_date,
            source=source,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO instruments (
                    instrument_id, ts_code, market, asset_type, listed_status, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id)
                DO UPDATE SET
                    ts_code = excluded.ts_code,
                    market = excluded.market,
                    asset_type = excluded.asset_type,
                    listed_status = excluded.listed_status,
                    updated_at = excluded.updated_at
                """,
                (
                    ts_code,
                    ts_code,
                    _infer_market_from_ts_code(ts_code),
                    asset_type,
                    "listed",
                    datetime.utcnow().isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO ingest_batches (
                    ingest_batch_id, source, market, frequency, adjustment_mode,
                    started_at, completed_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ingest_batch_id)
                DO UPDATE SET
                    completed_at = excluded.completed_at,
                    status = excluded.status
                """,
                (
                    ingest_batch_id,
                    source,
                    _infer_market_from_ts_code(ts_code),
                    "1d",
                    adjustment_mode,
                    datetime.utcnow().isoformat(),
                    datetime.utcnow().isoformat(),
                    "completed",
                ),
            )
            connection.executemany(
                """
                INSERT INTO market_bars (
                    ts_code, asset_type, adjustment_mode, trade_date, open, high, low,
                    close, volume, amount, pct_chg, turnover, data_source, fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ts_code, asset_type, adjustment_mode, trade_date)
                DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    pct_chg = excluded.pct_chg,
                    turnover = excluded.turnover,
                    data_source = excluded.data_source,
                    fetched_at = excluded.fetched_at
                """,
                [
                    (
                        item.ts_code,
                        item.asset_type,
                        item.adjustment_mode,
                        item.trade_date,
                        item.open,
                        item.high,
                        item.low,
                        item.close,
                        item.volume,
                        item.amount,
                        item.pct_chg,
                        item.turnover,
                        item.data_source,
                        item.fetched_at,
                    )
                    for item in bars
                ],
            )
            connection.execute(
                """
                INSERT INTO sync_ranges (
                    ts_code, asset_type, adjustment_mode, start_date, end_date, source, synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ts_code, asset_type, adjustment_mode, start_date, end_date)
                DO UPDATE SET
                    source = excluded.source,
                    synced_at = excluded.synced_at
                """,
                (
                    ts_code,
                    asset_type,
                    adjustment_mode,
                    start_date,
                    end_date,
                    source,
                    datetime.utcnow().isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO coverage_stats (
                    instrument_id, market, frequency, adjustment_mode,
                    min_trade_date, max_trade_date, last_synced_at,
                    coverage_status, ingest_batch_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id, market, frequency, adjustment_mode)
                DO UPDATE SET
                    min_trade_date = excluded.min_trade_date,
                    max_trade_date = excluded.max_trade_date,
                    last_synced_at = excluded.last_synced_at,
                    coverage_status = excluded.coverage_status,
                    ingest_batch_id = excluded.ingest_batch_id
                """,
                (
                    ts_code,
                    _infer_market_from_ts_code(ts_code),
                    "1d",
                    adjustment_mode,
                    start_date,
                    end_date,
                    datetime.utcnow().isoformat(),
                    "ready",
                    ingest_batch_id,
                ),
            )
            connection.commit()

    def get_bars(
        self,
        *,
        ts_code: str,
        asset_type: str,
        adjustment_mode: str,
        start_date: str,
        end_date: str,
    ) -> list[MarketBar]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ts_code, asset_type, adjustment_mode, trade_date, open, high, low, close,
                       volume, amount, pct_chg, turnover, data_source, fetched_at
                FROM market_bars
                WHERE ts_code = ?
                  AND asset_type = ?
                  AND adjustment_mode = ?
                  AND trade_date >= ?
                  AND trade_date <= ?
                ORDER BY trade_date ASC
                """,
                (ts_code, asset_type, adjustment_mode, start_date, end_date),
            ).fetchall()
        return [
            MarketBar(
                ts_code=row[0],
                asset_type=row[1],
                adjustment_mode=row[2],
                trade_date=row[3],
                open=float(row[4]),
                high=float(row[5]),
                low=float(row[6]),
                close=float(row[7]),
                volume=float(row[8]),
                amount=float(row[9]),
                pct_chg=_safe_float(row[10]),
                turnover=_safe_float(row[11]),
                data_source=row[12],
                fetched_at=row[13],
            )
            for row in rows
        ]

    def _ensure_parent(self) -> None:
        Path(self._database_path).resolve().parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)

    def _build_ingest_batch_id(
        self,
        *,
        ts_code: str,
        asset_type: str,
        adjustment_mode: str,
        start_date: str,
        end_date: str,
        source: str,
    ) -> str:
        digest = hashlib.sha256(
            f"{ts_code}:{asset_type}:{adjustment_mode}:{start_date}:{end_date}:{source}".encode(
                "utf-8"
            )
        ).hexdigest()
        return f"ingest_{digest[:16]}"

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id TEXT PRIMARY KEY,
                    ts_code TEXT NOT NULL UNIQUE,
                    market TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    listed_status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trading_calendar (
                    market TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    is_open INTEGER NOT NULL,
                    PRIMARY KEY (market, trade_date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_batches (
                    ingest_batch_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    market TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    adjustment_mode TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_bars (
                    ts_code TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    adjustment_mode TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    amount REAL NOT NULL,
                    pct_chg REAL,
                    turnover REAL,
                    data_source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (ts_code, asset_type, adjustment_mode, trade_date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_ranges (
                    ts_code TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    adjustment_mode TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    synced_at TEXT NOT NULL,
                    PRIMARY KEY (ts_code, asset_type, adjustment_mode, start_date, end_date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS coverage_stats (
                    instrument_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    adjustment_mode TEXT NOT NULL,
                    min_trade_date TEXT NOT NULL,
                    max_trade_date TEXT NOT NULL,
                    last_synced_at TEXT NOT NULL,
                    coverage_status TEXT NOT NULL,
                    ingest_batch_id TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, market, frequency, adjustment_mode)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS correction_batches (
                    correction_batch_id TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    source TEXT NOT NULL,
                    affected_range TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()


class MarketDataService:
    def __init__(
        self,
        *,
        cache_repository: MarketDataCacheRepository,
        primary_provider: MarketDataProvider | None,
        fallback_provider: MarketDataProvider,
    ) -> None:
        self._cache_repository = cache_repository
        self._primary_provider = primary_provider
        self._fallback_provider = fallback_provider

    def load_daily_bars(
        self,
        *,
        ts_code: str,
        start_date: date,
        end_date: date,
        asset_type: str | None = None,
        adjustment_mode: str = "qfq",
    ) -> tuple[list[MarketBar], dict[str, Any]]:
        actual_asset_type = asset_type or infer_asset_type(ts_code)
        start_text = start_date.strftime("%Y%m%d")
        end_text = end_date.strftime("%Y%m%d")
        start_query = start_date.strftime("%Y-%m-%d")
        end_query = end_date.strftime("%Y-%m-%d")
        cached = self._cache_repository.is_range_cached(
            ts_code=ts_code,
            asset_type=actual_asset_type,
            adjustment_mode=adjustment_mode,
            start_date=start_text,
            end_date=end_text,
        )

        provider_name = "cache"
        fallback_reason = ""
        if not cached:
            provider_name, fallback_reason = self._sync_range(
                ts_code=ts_code,
                asset_type=actual_asset_type,
                adjustment_mode=adjustment_mode,
                start_date=start_text,
                end_date=end_text,
            )

        bars = self._cache_repository.get_bars(
            ts_code=ts_code,
            asset_type=actual_asset_type,
            adjustment_mode=adjustment_mode,
            start_date=start_query,
            end_date=end_query,
        )
        metadata = {
            "provider": provider_name if not cached else bars[0].data_source if bars else "cache",
            "served_from_cache": cached,
            "fallback_reason": fallback_reason,
            "bar_count": len(bars),
            "ts_code": ts_code,
            "asset_type": actual_asset_type,
            "adjustment_mode": adjustment_mode,
        }
        return bars, metadata

    def _sync_range(
        self,
        *,
        ts_code: str,
        asset_type: str,
        adjustment_mode: str,
        start_date: str,
        end_date: str,
    ) -> tuple[str, str]:
        fallback_reason = ""
        provider = self._primary_provider
        bars: list[MarketBar] | None = None
        if provider is not None:
            try:
                bars = provider.fetch_daily_bars(
                    ts_code=ts_code,
                    asset_type=asset_type,
                    start_date=start_date,
                    end_date=end_date,
                    adjustment_mode=adjustment_mode,
                )
            except Exception as exc:  # pragma: no cover - external failure path
                fallback_reason = str(exc)

        if bars is None:
            provider = self._fallback_provider
            bars = provider.fetch_daily_bars(
                ts_code=ts_code,
                asset_type=asset_type,
                start_date=start_date,
                end_date=end_date,
                adjustment_mode=adjustment_mode,
            )

        self._cache_repository.cache_bars(
            bars=bars,
            ts_code=ts_code,
            asset_type=asset_type,
            adjustment_mode=adjustment_mode,
            start_date=start_date,
            end_date=end_date,
            source=provider.name,
        )
        return provider.name, fallback_reason


def infer_asset_type(ts_code: str) -> str:
    symbol = ts_code.split(".")[0]
    if symbol.startswith(("15", "16", "50", "51", "52", "56", "58")):
        return "etf"
    return "stock"


def _infer_market_from_ts_code(ts_code: str) -> str:
    if ts_code.upper().endswith(".SZ"):
        return "cn_sz"
    return "cn_sh"


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _format_trade_date(value: Any) -> str:
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _to_prefixed_symbol(ts_code: str) -> str:
    symbol, suffix = ts_code.split(".")
    exchange = suffix.lower()
    if exchange in {"sh", "ss"}:
        return f"sh{symbol}"
    if exchange in {"sz"}:
        return f"sz{symbol}"
    if exchange in {"bj"}:
        return f"bj{symbol}"
    return f"sh{symbol}"
