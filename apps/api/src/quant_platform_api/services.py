from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timedelta
import hashlib
from io import StringIO
import json
import re
from time import sleep
from typing import Any, Callable

from quant_platform_api.backtest_engine import run_backtest
from quant_platform_api.config import Settings
from quant_platform_api.market_data import MarketDataService
from quant_platform_api.models import (
    CustomIndicatorCreateRequest,
    CustomIndicatorGenerateRequest,
    CustomIndicatorRecord,
    DefaultRuleItem,
    DefaultRuleSection,
    DefaultRuleUpdateRequest,
    ErrorPayload,
    GlossaryTermCreateRequest,
    GlossaryTermRecord,
    StrategyVersionRecord,
    StrategyGenerateRequest,
    TaskRecord,
    TaskStatus,
    TradeRecordItem,
    TradeUploadRecord,
    UserProfile,
    UserRecord,
    UserSessionRecord,
)
from quant_platform_api.repository import (
    CustomIndicatorRepository,
    DefaultRuleRepository,
    UserRepository,
    UserSessionRepository,
    GlossaryTermRepository,
    StrategyRepository,
    TaskRepository,
    TradeUploadRepository,
)
from quant_platform_api.security import hash_password, issue_session_token, verify_password


BUILTIN_INDICATORS: list[dict[str, Any]] = [
    {
        "indicator_key": "sma_cross",
        "title": "均线金叉 / 死叉",
        "summary": "比较短周期均线和长周期均线的位置关系，常用于趋势确认。",
        "formula_text": "signal = SMA(close, fast) > SMA(close, slow)",
        "usage_hint": "适合趋势策略，常见配置为 5/20、10/30。",
        "python_code": """def sma(values, period):\n    return values.rolling(period).mean()\n\nfast_ma = sma(close, 5)\nslow_ma = sma(close, 20)\nsignal = fast_ma > slow_ma\n""",
        "default_params": {"fast": 5, "slow": 20},
    },
    {
        "indicator_key": "rsi",
        "title": "RSI 相对强弱指标",
        "summary": "衡量一段时间内涨跌强度，常用于超买超卖判断。",
        "formula_text": "RSI = 100 - 100 / (1 + RS)",
        "usage_hint": "常见阈值为 RSI < 30 超卖、RSI > 70 超买。",
        "python_code": """delta = close.diff()\ngain = delta.clip(lower=0).rolling(14).mean()\nloss = (-delta.clip(upper=0)).rolling(14).mean()\nrs = gain / loss.replace(0, 1e-9)\nrsi = 100 - 100 / (1 + rs)\n""",
        "default_params": {"period": 14},
    },
    {
        "indicator_key": "macd",
        "title": "MACD 指数平滑异同均线",
        "summary": "比较快慢 EMA 的差值和信号线，常用于趋势与动量共振。",
        "formula_text": "MACD = EMA(close, 12) - EMA(close, 26)",
        "usage_hint": "适合配合放量、突破等条件一起使用。",
        "python_code": """ema_fast = close.ewm(span=12, adjust=False).mean()\nema_slow = close.ewm(span=26, adjust=False).mean()\ndif = ema_fast - ema_slow\ndea = dif.ewm(span=9, adjust=False).mean()\nmacd_hist = (dif - dea) * 2\n""",
        "default_params": {"fast": 12, "slow": 26, "signal": 9},
    },
    {
        "indicator_key": "bollinger_band",
        "title": "布林带",
        "summary": "通过均线和标准差构造上下轨，衡量波动与偏离程度。",
        "formula_text": "upper = SMA(close, 20) + 2 * STD(close, 20)",
        "usage_hint": "适合震荡和波动扩张场景。",
        "python_code": """mid = close.rolling(20).mean()\nstd = close.rolling(20).std(ddof=0)\nupper = mid + 2 * std\nlower = mid - 2 * std\n""",
        "default_params": {"period": 20, "std_multiplier": 2},
    },
    {
        "indicator_key": "volume_ratio",
        "title": "量比 / 放量强度",
        "summary": "比较当前成交量和过去均量，用于判断量能是否放大。",
        "formula_text": "volume_ratio = volume / SMA(volume, 10)",
        "usage_hint": "常见阈值 1.2 或 1.5，用来过滤无量信号。",
        "python_code": """volume_ma = volume.rolling(10).mean()\nvolume_ratio = volume / volume_ma.replace(0, 1e-9)\n""",
        "default_params": {"period": 10},
    },
]

DEFAULT_RULE_SECTIONS: list[dict[str, Any]] = [
    {
        "section_id": "rule_cn_equity",
        "section": "A股默认研究规则",
        "items": [
            {
                "title": "股票默认按 T+1 卖出研究",
                "description": "股票买入后默认下一个交易日才能卖出，策略解释和回测约定都优先按此理解。",
            },
            {
                "title": "股票最小交易单位 100 股",
                "description": "策略执行默认按整手撮合，避免生成不符合 A 股习惯的下单描述。",
            },
            {
                "title": "默认执行参数应视平台设置和策略设置而定",
                "description": "平台初始建议可从日线、前复权、次日开盘成交起步，但实际应允许切换到其他周期、复权模式和盘中成交逻辑。",
            },
            {
                "title": "ETF 研究允许与股票共用策略描述",
                "description": "如果用户未明确区分，平台会根据标的代码识别为股票或 ETF，并沿用中国市场语义解释。",
            },
        ],
    },
    {
        "section_id": "rule_us_equity",
        "section": "美股默认研究规则",
        "items": [
            {
                "title": "支持 T+0 交易语义",
                "description": "美股默认允许同日买入卖出，策略解释中不会自动附加 A 股的 T+1 限制。",
            },
            {
                "title": "默认使用美东时区交易日",
                "description": "如果用户没有单独声明，日线和分钟线默认按美东市场会话解释。",
            },
            {
                "title": "允许盘前盘后语义，但需显式说明",
                "description": "如果策略涉及盘前盘后成交、跳空或财报时段，应在提示词中明确标注，避免与常规时段混淆。",
            },
        ],
    },
    {
        "section_id": "rule_crypto",
        "section": "加密货币默认研究规则",
        "items": [
            {
                "title": "默认 7x24 连续交易",
                "description": "加密货币不存在交易日休市概念，平台默认按连续时间轴解释信号和持仓。",
            },
            {
                "title": "允许高频与多周期混合语义",
                "description": "分钟级别、小时级别和日线级别可以在同一策略里并存，但当前真实回测仍需看执行层支持情况。",
            },
            {
                "title": "默认不引入复权语义",
                "description": "加密货币研究通常使用原始价格序列，不自动引入前复权或后复权概念。",
            },
        ],
    },
    {
        "section_id": "rule_london_gold",
        "section": "伦敦金默认研究规则",
        "items": [
            {
                "title": "优先按全球连续报价语义解释",
                "description": "伦敦金更接近连续报价品种，策略解释默认围绕全球时段切换、波动扩张和风险事件展开。",
            },
            {
                "title": "重点关注宏观事件窗口",
                "description": "非农、通胀、利率决议等事件时段会显著影响波动，策略若涉及事件交易应显式写入。",
            },
            {
                "title": "默认按商品类资产约束表达",
                "description": "平台会把伦敦金策略解释成商品 / 贵金属研究语境，而不是股票式涨跌停语义。",
            },
        ],
    }
]


def _builtin_default_rule_sections() -> list[DefaultRuleSection]:
    return [
        DefaultRuleSection(
            section_id=item["section_id"],
            section=item["section"],
            items=[DefaultRuleItem(**rule) for rule in item.get("items", [])],
        )
        for item in DEFAULT_RULE_SECTIONS
    ]

DEFAULT_GLOSSARY_TERMS: list[dict[str, Any]] = [
    {
        "term": "涨停板",
        "meaning": "当日价格涨到交易所允许的上涨上限，通常代表强势封板。",
        "example": "如果提示词里写“接近涨停板不追”，AI 会把它理解成避免追高强封板个股。",
    },
    {
        "term": "炸板",
        "meaning": "股价曾触及涨停但未能封住，随后打开涨停回落。",
        "example": "“炸板后回封”会被理解成先开板再重新走强的形态。",
    },
    {
        "term": "四连板",
        "meaning": "连续四个交易日涨停，表示情绪和连板高度已明显抬升。",
        "example": "“四连板后不追”会被解释成在高位情绪股上增加风险过滤。",
    },
    {
        "term": "一字板",
        "meaning": "开盘即封死涨停且盘中几乎没有换手，K 线像一字。",
        "example": "“一字板不参与”会被解释成避开无法成交或高拥挤的封板形态。",
    },
]

MARKET_SCOPE_LABELS: dict[str, str] = {
    "cn_equity": "A股",
    "us_equity": "美股",
    "crypto": "加密货币",
    "london_gold": "伦敦金",
}

TIMEFRAME_LABELS: dict[str, str] = {
    "1m": "1分钟",
    "5m": "5分钟",
    "15m": "15分钟",
    "30m": "30分钟",
    "1h": "1小时",
    "4h": "4小时",
    "1d": "日线",
    "1w": "周线",
    "1mo": "月线",
}

TIMEFRAME_ORDER: dict[str, int] = {
    key: index for index, key in enumerate(TIMEFRAME_LABELS.keys(), start=1)
}

TIMEFRAME_ALIASES: dict[str, str] = {
    "1m": "1m",
    "1min": "1m",
    "1分钟": "1m",
    "5m": "5m",
    "5min": "5m",
    "5分钟": "5m",
    "15m": "15m",
    "15min": "15m",
    "15分钟": "15m",
    "30m": "30m",
    "30min": "30m",
    "30分钟": "30m",
    "1h": "1h",
    "60m": "1h",
    "1hour": "1h",
    "1小时": "1h",
    "4h": "4h",
    "4hour": "4h",
    "4小时": "4h",
    "1d": "1d",
    "day": "1d",
    "daily": "1d",
    "日线": "1d",
    "1w": "1w",
    "week": "1w",
    "weekly": "1w",
    "周线": "1w",
    "1mo": "1mo",
    "month": "1mo",
    "monthly": "1mo",
    "月线": "1mo",
}

PROMPT_TIMEFRAME_MARKERS: tuple[tuple[str, str], ...] = (
    ("日线", "1d"),
    ("daily", "1d"),
    ("昨日", "1d"),
    ("周线", "1w"),
    ("weekly", "1w"),
    ("月线", "1mo"),
    ("monthly", "1mo"),
)


def _canonicalize_timeframe(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "")
    return TIMEFRAME_ALIASES.get(normalized, normalized or "1d")


def _timeframe_label(value: str) -> str:
    canonical = _canonicalize_timeframe(value)
    return TIMEFRAME_LABELS.get(canonical, canonical)


def _market_scope_label(value: str) -> str:
    return MARKET_SCOPE_LABELS.get(value, value)


def _extract_prompt_timeframes(prompt: str) -> list[str]:
    normalized = prompt.lower()
    detected: list[str] = []
    regex_markers: tuple[tuple[str, str], ...] = (
        (r"(?<!\d)15\s*(分钟|min)", "15m"),
        (r"(?<!\d)5\s*(分钟|min)", "5m"),
        (r"(?<!\d)1\s*(分钟|min)", "1m"),
        (r"(?<!\d)30\s*(分钟|min)", "30m"),
        (r"(?<!\d)1\s*(小时|hour|h)", "1h"),
        (r"60分钟", "1h"),
        (r"(?<!\d)4\s*(小时|hour|h)", "4h"),
    )
    for pattern, timeframe in regex_markers:
        if re.search(pattern, prompt, flags=re.IGNORECASE):
            if timeframe not in detected:
                detected.append(timeframe)
    for marker, timeframe in PROMPT_TIMEFRAME_MARKERS:
        if marker in prompt or marker in normalized:
            if timeframe not in detected:
                detected.append(timeframe)
    return detected


def _normalize_strategy_timeframes(
    primary_timeframe: str,
    requested_timeframes: list[str],
    prompt: str,
) -> list[str]:
    primary = _canonicalize_timeframe(primary_timeframe or "1d")
    merged = [primary]
    for timeframe in requested_timeframes + _extract_prompt_timeframes(prompt):
        canonical = _canonicalize_timeframe(timeframe)
        if canonical not in merged:
            merged.append(canonical)
    ordered_rest = sorted(
        [item for item in merged if item != primary],
        key=lambda item: TIMEFRAME_ORDER.get(item, 999),
    )
    return [primary, *ordered_rest]


def _build_context_rules(prompt: str, selected_timeframes: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = prompt.lower()
    entry_context: list[dict[str, Any]] = []
    exit_context: list[dict[str, Any]] = []
    intraday_timeframe = next(
        (item for item in selected_timeframes if item in {"1m", "5m", "15m", "30m", "1h", "4h"}),
        selected_timeframes[0],
    )

    if ("昨日最低价" in prompt or "昨日低点" in prompt) and "10日均线" in prompt:
        entry_context.append(
            {
                "timeframe": "1d",
                "expression": "昨日最低价小于10日均线",
                "indicator": "previous_low_vs_sma10",
                "operator": "<",
                "value": "sma_10",
            }
        )
    if ("昨日收盘价" in prompt or "昨收" in prompt) and "10日均线" in prompt:
        entry_context.append(
            {
                "timeframe": "1d",
                "expression": "昨日收盘价大于10日均线",
                "indicator": "previous_close_vs_sma10",
                "operator": ">",
                "value": "sma_10",
            }
        )
    if "kdj" in normalized and ("金叉" in prompt or "golden cross" in normalized):
        entry_context.append(
            {
                "timeframe": intraday_timeframe,
                "expression": f"{_timeframe_label(intraday_timeframe)}KDJ金叉",
                "indicator": "kdj_golden_cross",
                "operator": "==",
                "value": True,
            }
        )
    if ("60均线" in prompt or "60 日均线" in prompt or "ma60" in normalized) and ("卖" in prompt or "exit" in normalized):
        exit_context.append(
            {
                "timeframe": intraday_timeframe,
                "expression": f"现价低于{_timeframe_label(intraday_timeframe)}60均线",
                "indicator": "price_below_ma60",
                "operator": "==",
                "value": True,
            }
        )

    if len(selected_timeframes) > 1 and not entry_context:
        entry_context.append(
            {
                "timeframe": selected_timeframes[1],
                "expression": f"补充观察 {_timeframe_label(selected_timeframes[1])} 级别确认",
                "indicator": "secondary_timeframe_context",
                "operator": "==",
                "value": True,
            }
        )

    return entry_context, exit_context


class TaskExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class StrategyService:
    def __init__(
        self,
        repository: StrategyRepository,
        indicator_repository: CustomIndicatorRepository | None = None,
        glossary_repository: GlossaryTermRepository | None = None,
    ) -> None:
        self._repository = repository
        self._indicator_repository = indicator_repository
        self._glossary_repository = glossary_repository

    def create_project(
        self,
        *,
        user_id: str,
        workspace_id: str,
        title: str,
        natural_language_prompt: str,
        strategy_dsl: dict[str, Any],
        strategy_python: str | None = None,
    ) -> StrategyVersionRecord:
        record = StrategyVersionRecord(
            user_id=user_id,
            workspace_id=workspace_id,
            title=title,
            natural_language_prompt=natural_language_prompt,
            strategy_dsl=strategy_dsl,
            strategy_python=strategy_python,
        )
        return self._repository.create(record)

    def list_projects(
        self,
        *,
        user_id: str,
        workspace_id: str,
    ) -> list[StrategyVersionRecord]:
        return self._repository.list_projects(user_id=user_id, workspace_id=workspace_id)

    def get_project(
        self,
        version_id: str,
        *,
        user_id: str,
        workspace_id: str,
    ) -> StrategyVersionRecord | None:
        return self._repository.get(
            version_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )

    def generate_strategy(self, request: StrategyGenerateRequest) -> dict[str, Any]:
        prompt = request.prompt
        normalized = prompt.lower()
        side = "long"
        primary_timeframe = _canonicalize_timeframe(request.timeframe)
        selected_timeframes = _normalize_strategy_timeframes(
            primary_timeframe,
            request.timeframes,
            prompt,
        )
        market_scope_label = _market_scope_label(request.market_scope)
        entry_context, exit_context = _build_context_rules(prompt, selected_timeframes)
        indicators: list[dict[str, Any]] = []
        ambiguities: list[str] = []
        custom_indicators = (
            self._indicator_repository.list() if self._indicator_repository else []
        )
        custom_glossary_terms = (
            self._glossary_repository.list() if self._glossary_repository else []
        )
        glossary_terms = custom_glossary_terms + [
            GlossaryTermRecord(
                term_id=f"default_{index}",
                term=item["term"],
                meaning=item["meaning"],
                example=item["example"],
            )
            for index, item in enumerate(DEFAULT_GLOSSARY_TERMS, start=1)
        ]
        matched_custom_indicators = [
            item
            for item in custom_indicators
            if item.name.lower() in normalized or item.name in prompt
        ]
        matched_terms = [
            item
            for item in glossary_terms
            if item.term.lower() in normalized or item.term in prompt
        ]

        if "做空" in prompt or "short" in normalized:
            ambiguities.append("当前中国股票/ETF 默认仅支持做多回测，已自动按做多策略生成。")

        if "均线" in prompt or "sma" in normalized or "ma" in normalized:
            indicators.append(
                {
                    "indicator": "sma_cross",
                    "params": {"fast": 5, "slow": 20},
                    "operator": "==",
                    "value": True,
                    "timeframe": primary_timeframe,
                }
            )
        if "rsi" in normalized:
            indicators.append(
                {
                    "indicator": "rsi",
                    "params": {"period": 14},
                    "operator": "<",
                    "value": 70,
                    "timeframe": primary_timeframe,
                }
            )
        if "量" in prompt or "volume" in normalized:
            indicators.append(
                {
                    "indicator": "volume_ratio",
                    "params": {"period": 10},
                    "operator": ">",
                    "value": 1.2,
                    "timeframe": primary_timeframe,
                }
            )
        if not indicators:
            indicators.append(
                {
                    "indicator": "price_breakout",
                    "params": {"lookback": 20},
                    "operator": "==",
                    "value": True,
                    "timeframe": primary_timeframe,
                }
            )

        for indicator in matched_custom_indicators:
            indicators.append(
                {
                    "indicator": indicator.name,
                    "params": {"source": "custom_library"},
                    "operator": "==",
                    "value": True,
                    "timeframe": primary_timeframe,
                }
            )

        if len(selected_timeframes) > 1:
            ambiguities.append(
                "已识别为混合周期策略，额外周期条件已写入 DSL 的 entry_context / exit_context。"
            )
        if request.market_scope != "cn_equity":
            ambiguities.append(
                "所选市场范围已写入策略规格；当前真实回测仍优先覆盖 A 股日线，其他市场先保留在策略语义层。"
            )
        if primary_timeframe != "1d" or len(selected_timeframes) > 1:
            ambiguities.append(
                "当前回测引擎仍按日线兼容层执行，可执行规则保留在主周期，跨周期条件已作为上下文存档。"
            )

        strategy_dsl = {
            "asset_type": request.asset_type,
            "market_scope": request.market_scope,
            "market_scope_label": market_scope_label,
            "market": request.market,
            "timeframe": primary_timeframe,
            "timeframes": selected_timeframes,
            "analysis_mode": "multi_timeframe" if len(selected_timeframes) > 1 else "single_timeframe",
            "backtest_timeframe": "1d",
            "entry_context": entry_context,
            "entry": {"all": indicators},
            "exit_context": exit_context,
            "exit": {
                "any": [
                    {
                        "indicator": "take_profit_pct",
                        "operator": ">=",
                        "value": 0.08,
                        "timeframe": primary_timeframe,
                    },
                    {
                        "indicator": "stop_loss_pct",
                        "operator": "<=",
                        "value": -0.03,
                        "timeframe": primary_timeframe,
                    },
                ]
            },
            "position": {"side": side, "max_positions": 1},
        }
        strategy_python = _render_strategy_python(
            strategy_dsl,
            teaching_mode=request.teaching_mode,
            matched_custom_indicators=matched_custom_indicators,
            matched_terms=matched_terms,
        )
        summary_parts = [
            f"已根据描述生成一套面向 {market_scope_label} {request.market} 的 {side} 向 Python 策略，主周期为 {_timeframe_label(primary_timeframe)}。"
        ]
        if len(selected_timeframes) > 1:
            summary_parts.append(
                "已保留混合周期条件："
                + " / ".join(_timeframe_label(item) for item in selected_timeframes)
                + "。"
            )
        if request.teaching_mode:
            summary_parts.append("教学模式已开启，Python 代码中为主要语句补充了逐行注释。")
        if matched_custom_indicators:
            summary_parts.append(
                "已调用自定义指标库中的："
                + "、".join(item.name for item in matched_custom_indicators)
                + "。"
            )
        if matched_terms:
            summary_parts.append(
                "已按术语库解释："
                + "、".join(item.term for item in matched_terms)
                + "。"
            )
        if entry_context or exit_context:
            summary_parts.append("跨周期观察条件已经显式写入策略规格，便于后续接入更真实的多周期执行引擎。")
        return {
            "strategy_dsl": strategy_dsl,
            "strategy_python": strategy_python,
            "human_summary": " ".join(summary_parts),
            "ambiguities": ambiguities,
            "matched_custom_indicators": [
                {
                    "indicator_id": item.indicator_id,
                    "name": item.name,
                    "summary": item.summary,
                }
                for item in matched_custom_indicators
            ],
            "matched_terms": [
                {
                    "term_id": item.term_id,
                    "term": item.term,
                    "meaning": item.meaning,
                }
                for item in matched_terms
            ],
        }


class AuthService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        session_repository: UserSessionRepository,
    ) -> None:
        self._user_repository = user_repository
        self._session_repository = session_repository

    def seed_default_accounts(self) -> None:
        defaults = [
            ("1111", "1111@example.com", "618618", "user"),
            ("admin", "admin@example.com", "618618", "admin"),
        ]
        for username, contact, password, role in defaults:
            if self._user_repository.get_by_username(username) is None:
                self._user_repository.create(
                    UserRecord(
                        username=username,
                        contact=contact,
                        password_hash=hash_password(password),
                        role=role,
                    )
                )

    def register(self, *, username: str, contact: str, password: str) -> UserProfile:
        normalized_username = username.strip()
        normalized_contact = contact.strip()
        if not normalized_username or not normalized_contact or not password:
            raise TaskExecutionError("INVALID_ARGUMENT", "username, contact and password are required")
        if self._user_repository.get_by_username(normalized_username) is not None:
            raise TaskExecutionError("STATE_CONFLICT", "username already exists")
        record = self._user_repository.create(
            UserRecord(
                username=normalized_username,
                contact=normalized_contact,
                password_hash=hash_password(password),
            )
        )
        return self._to_profile(record)

    def login(self, *, username: str, password: str) -> tuple[UserProfile, str]:
        record = self._user_repository.get_by_username(username.strip())
        if record is None or not verify_password(password, record.password_hash):
            raise TaskExecutionError("FORBIDDEN", "invalid username or password")
        session = self._session_repository.create(
            UserSessionRecord(
                user_id=record.user_id,
                session_token=issue_session_token(),
            )
        )
        return self._to_profile(record), session.session_token

    def get_user_by_session_token(self, session_token: str | None) -> UserProfile | None:
        if not session_token:
            return None
        session = self._session_repository.get_by_token(session_token)
        if session is None:
            return None
        for user in self._user_repository.list():
            if user.user_id == session.user_id:
                return self._to_profile(user)
        return None

    def logout(self, session_token: str | None) -> None:
        if session_token:
            self._session_repository.delete_by_token(session_token)

    def _to_profile(self, record: UserRecord) -> UserProfile:
        return UserProfile(
            user_id=record.user_id,
            workspace_id=self.workspace_id_for_user_id(record.user_id),
            username=record.username,
            contact=record.contact,
            role=record.role,
            created_at=record.created_at,
        )

    @staticmethod
    def workspace_id_for_user_id(user_id: str) -> str:
        normalized = user_id.replace("user_", "")
        return f"ws_{normalized[:12] or 'default'}"

    @staticmethod
    def is_admin(user: UserProfile | None) -> bool:
        return bool(user and user.role == "admin")


class IndicatorService:
    def __init__(self, repository: CustomIndicatorRepository) -> None:
        self._repository = repository

    def list_builtin(self) -> list[dict[str, Any]]:
        return BUILTIN_INDICATORS

    def list_custom(self) -> list[CustomIndicatorRecord]:
        return self._repository.list()

    def generate_custom_indicator(
        self, request: CustomIndicatorGenerateRequest
    ) -> dict[str, Any]:
        prompt = request.prompt.strip()
        normalized = prompt.lower()
        if "量" in prompt and "均线" in prompt:
            name = "量价均线共振"
            summary = "同时观察价格相对均线的偏离和成交量相对均量的放大程度。"
            formula_text = "signal = (close / SMA(close, 20) - 1) * (volume / SMA(volume, 10))"
            python_code = """price_bias = close / close.rolling(20).mean() - 1\nvolume_ratio = volume / volume.rolling(10).mean().replace(0, 1e-9)\nsignal = price_bias * volume_ratio\n"""
            usage_hint = "当 signal > 0.03 时，说明价格趋势和量能同时增强。"
            tags = ["量价", "趋势"]
        elif "波动" in prompt or "震荡" in prompt:
            name = "波动压缩强度"
            summary = "用来观察价格波动是否明显收敛，为突破前蓄势做过滤。"
            formula_text = "signal = STD(close, 10) / SMA(close, 20)"
            python_code = """rolling_std = close.rolling(10).std(ddof=0)\nrolling_mean = close.rolling(20).mean().replace(0, 1e-9)\nsignal = rolling_std / rolling_mean\n"""
            usage_hint = "当 signal 持续降低后再重新抬升，可配合突破条件使用。"
            tags = ["波动", "突破"]
        elif "强弱" in prompt or "动量" in prompt or "rps" in normalized:
            name = "短周期动量强度"
            summary = "比较当前收盘价与过去若干周期前的差异，衡量价格推升斜率。"
            formula_text = "signal = close / REF(close, 10) - 1"
            python_code = """past_close = close.shift(10).replace(0, 1e-9)\nsignal = close / past_close - 1\n"""
            usage_hint = "适合和均线趋势一起使用，过滤弱势反弹。"
            tags = ["动量", "趋势"]
        else:
            name = "自定义趋势过滤器"
            summary = "针对自然语言需求生成的自定义过滤器，用来把主观经验转成可验证信号。"
            formula_text = "signal = (close / SMA(close, 20) - 1) + (volume / SMA(volume, 10) - 1)"
            python_code = """price_component = close / close.rolling(20).mean().replace(0, 1e-9) - 1\nvolume_component = volume / volume.rolling(10).mean().replace(0, 1e-9) - 1\nsignal = price_component + volume_component\n"""
            usage_hint = "可把 signal 大于 0 作为方向过滤条件，再结合买卖点信号。"
            tags = ["通用", "过滤"]
        return {
            "name": name,
            "natural_language_prompt": prompt,
            "summary": summary,
            "formula_text": formula_text,
            "python_code": python_code,
            "usage_hint": usage_hint,
            "tags": tags,
        }

    def create_custom(self, request: CustomIndicatorCreateRequest) -> CustomIndicatorRecord:
        record = CustomIndicatorRecord(
            name=request.name,
            natural_language_prompt=request.natural_language_prompt,
            summary=request.summary,
            formula_text=request.formula_text,
            python_code=request.python_code,
            usage_hint=request.usage_hint,
            tags=request.tags,
        )
        return self._repository.create(record)


class RuleService:
    def __init__(
        self,
        glossary_repository: GlossaryTermRepository,
        default_rule_repository: DefaultRuleRepository,
    ) -> None:
        self._glossary_repository = glossary_repository
        self._default_rule_repository = default_rule_repository

    def list_default_rules(self) -> list[dict[str, Any]]:
        records = self._default_rule_repository.list()
        if not records:
            records = _builtin_default_rule_sections()
            self._default_rule_repository.replace_all(records)
        return [item.model_dump(mode="json") for item in records]

    def update_default_rules(
        self,
        request: DefaultRuleUpdateRequest,
    ) -> list[dict[str, Any]]:
        normalized: list[DefaultRuleSection] = []
        for section in request.items:
            title = section.section.strip()
            if not title:
                continue
            items = [
                DefaultRuleItem(
                    title=item.title.strip(),
                    description=item.description.strip(),
                )
                for item in section.items
                if item.title.strip() and item.description.strip()
            ]
            normalized.append(
                DefaultRuleSection(
                    section_id=section.section_id,
                    section=title,
                    items=items,
                )
            )
        if not normalized:
            normalized = _builtin_default_rule_sections()
        records = self._default_rule_repository.replace_all(normalized)
        return [item.model_dump(mode="json") for item in records]

    def reset_default_rules(self) -> list[dict[str, Any]]:
        records = self._default_rule_repository.replace_all(
            _builtin_default_rule_sections()
        )
        return [item.model_dump(mode="json") for item in records]

    def list_glossary_terms(self) -> list[dict[str, Any]]:
        custom_terms = [
            {
                "term_id": item.term_id,
                "term": item.term,
                "meaning": item.meaning,
                "example": item.example,
                "source": "custom",
            }
            for item in self._glossary_repository.list()
        ]
        default_terms = [
            {
                "term_id": f"default_{index}",
                "term": item["term"],
                "meaning": item["meaning"],
                "example": item["example"],
                "source": "default",
            }
            for index, item in enumerate(DEFAULT_GLOSSARY_TERMS, start=1)
        ]
        return custom_terms + default_terms

    def create_glossary_term(
        self, request: GlossaryTermCreateRequest
    ) -> GlossaryTermRecord:
        record = GlossaryTermRecord(
            term=request.term,
            meaning=request.meaning,
            example=request.example,
        )
        return self._glossary_repository.create(record)


class TradeUploadService:
    def __init__(self, repository: TradeUploadRepository) -> None:
        self._repository = repository

    def create_upload(
        self,
        source_file_name: str,
        raw_text: str,
        *,
        user_id: str,
        workspace_id: str,
    ) -> TradeUploadRecord:
        detected_columns = self._detect_columns(raw_text)
        record = TradeUploadRecord(
            user_id=user_id,
            workspace_id=workspace_id,
            source_file_name=source_file_name,
            raw_text=raw_text,
            detected_columns=detected_columns,
        )
        return self._repository.create(record)

    def get_upload(
        self,
        upload_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> TradeUploadRecord | None:
        return self._repository.get(
            upload_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )

    def parse_upload(
        self,
        upload_id: str,
        column_mapping: dict[str, str],
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> TradeUploadRecord | None:
        record = self._repository.get(
            upload_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        if record is None:
            return None

        reader = csv.DictReader(StringIO(record.raw_text))
        parsed: list[TradeRecordItem] = []
        for index, row in enumerate(reader):
            symbol = row.get(column_mapping.get("symbol", ""), "BTCUSDT") or "BTCUSDT"
            side = row.get(column_mapping.get("side", ""), "long") or "long"
            entry_time = row.get(column_mapping.get("entry_time", ""), "")
            exit_time = row.get(column_mapping.get("exit_time", ""), "") or None
            pnl_raw = row.get(column_mapping.get("pnl", ""), "0") or "0"
            try:
                pnl = float(pnl_raw)
            except ValueError:
                pnl = 0.0
            parsed.append(
                TradeRecordItem(
                    trade_id=f"trade_{index + 1:03d}",
                    symbol=symbol,
                    side="short" if side.lower() in {"short", "sell", "做空"} else "long",
                    entry_time=entry_time,
                    exit_time=exit_time,
                    pnl=pnl,
                )
            )

        record.column_mapping = column_mapping
        record.records = parsed
        record.status = "parsed"
        return self._repository.update(record)

    def _detect_columns(self, raw_text: str) -> list[str]:
        reader = csv.reader(StringIO(raw_text))
        try:
            header = next(reader)
        except StopIteration:
            return []
        return [item.strip() for item in header]


class WorkspaceService:
    def __init__(
        self,
        *,
        strategy_service: StrategyService,
        task_repository: TaskRepository,
    ) -> None:
        self._strategy_service = strategy_service
        self._task_repository = task_repository

    def build_summary(self, *, user_id: str, workspace_id: str) -> dict[str, Any]:
        projects = self._strategy_service.list_projects(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        backtests = self._task_repository.list(
            "backtest",
            user_id=user_id,
            workspace_id=workspace_id,
        )
        replays = self._task_repository.list(
            "replay",
            user_id=user_id,
            workspace_id=workspace_id,
        )
        all_tasks = self._task_repository.list(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        failed_tasks = [
            item
            for item in all_tasks
            if item.status in {TaskStatus.FAILED, TaskStatus.CANCELED}
        ][:4]

        return {
            "counts": {
                "projects": len(projects),
                "backtests": len(backtests),
                "replays": len(replays),
                "failed_tasks": len(
                    [
                        item
                        for item in all_tasks
                        if item.status in {TaskStatus.FAILED, TaskStatus.CANCELED}
                    ]
                ),
            },
            "recent_projects": [
                {
                    "project_id": item.project_id,
                    "version_id": item.version_id,
                    "title": item.title,
                    "market": item.strategy_dsl.get("market"),
                    "timeframes": item.strategy_dsl.get(
                        "timeframes",
                        [item.strategy_dsl.get("timeframe", "1d")],
                    ),
                    "analysis_mode": item.strategy_dsl.get(
                        "analysis_mode",
                        "single_timeframe",
                    ),
                    "created_at": item.created_at.isoformat(),
                }
                for item in projects[:4]
            ],
            "recent_backtests": [self._summarize_task(item) for item in backtests[:4]],
            "recent_replays": [self._summarize_task(item) for item in replays[:4]],
            "recent_failures": [self._summarize_task(item) for item in failed_tasks],
            "snapshot_states": self._collect_snapshot_states(backtests),
        }

    def _summarize_task(self, record: TaskRecord) -> dict[str, Any]:
        result = record.result
        data_snapshot_summary = result.get("data_snapshot_summary", {})
        return {
            "task_id": record.id,
            "kind": record.kind,
            "status": record.status.value,
            "created_at": record.created_at.isoformat(),
            "config_revision": record.config_revision,
            "title": result.get("strategy_title")
            or result.get("summary")
            or record.payload.get("strategy_version_id")
            or record.payload.get("upload_id")
            or record.kind,
            "metrics": result.get("metrics", {}),
            "dataset_snapshot_ref": result.get("dataset_snapshot_ref")
            or record.payload.get("data_snapshot", {}).get("dataset_snapshot_ref"),
            "data_snapshot_summary": data_snapshot_summary,
            "backtest_config": result.get("backtest_config", {}),
        }

    def _collect_snapshot_states(self, backtests: list[TaskRecord]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for record in backtests:
            summary = record.result.get("data_snapshot_summary", {})
            snapshot_ref = summary.get("dataset_snapshot_ref") or record.payload.get(
                "data_snapshot",
                {},
            ).get("dataset_snapshot_ref")
            if not snapshot_ref or snapshot_ref in seen:
                continue
            seen.add(snapshot_ref)
            items.append(
                {
                    "dataset_snapshot_ref": snapshot_ref,
                    "provider": summary.get("provider", "未知"),
                    "coverage_status": summary.get("coverage_status", "unknown"),
                    "coverage_pct": summary.get("coverage_pct"),
                    "missing_rate_pct": summary.get("missing_rate_pct"),
                    "calendar": summary.get("calendar"),
                    "timezone": summary.get("timezone"),
                    "warmup_bars": summary.get("warmup_bars"),
                    "last_synced_at": summary.get("last_synced_at"),
                    "market": summary.get("market"),
                    "timeframe": summary.get("timeframe"),
                }
            )
            if len(items) >= 4:
                break
        return items


class AdminService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        session_repository: UserSessionRepository,
        strategy_repository: StrategyRepository,
        task_repository: TaskRepository,
    ) -> None:
        self._user_repository = user_repository
        self._session_repository = session_repository
        self._strategy_repository = strategy_repository
        self._task_repository = task_repository

    def build_summary(self) -> dict[str, Any]:
        users = self._user_repository.list()
        sessions = self._session_repository.list()
        projects = self._strategy_repository.list_projects()
        tasks = self._task_repository.list()
        now = datetime.now(tz=users[0].created_at.tzinfo) if users else datetime.now()
        cutoff_7d = now - timedelta(days=7)

        enriched_users = self._build_user_rows(users, sessions, projects, tasks)
        backtests = [item for item in tasks if item.kind == "backtest"]
        replays = [item for item in tasks if item.kind == "replay"]
        failed_tasks = [
            item for item in tasks if item.status in {TaskStatus.FAILED, TaskStatus.CANCELED}
        ]
        running_tasks = [item for item in tasks if item.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}]
        coverage_risk_snapshots = [
            item for item in self._collect_snapshot_states(backtests)
            if item["coverage_status"] != "ready"
            or (item.get("missing_rate_pct") or 0) > 1
        ]

        return {
            "counts": {
                "users": len(users),
                "admins": len([item for item in users if item.role == "admin"]),
                "active_sessions": len(sessions),
                "projects": len(projects),
                "backtests": len(backtests),
                "replays": len(replays),
                "running_tasks": len(running_tasks),
                "failed_tasks": len(failed_tasks),
                "new_users_7d": len([item for item in users if item.created_at >= cutoff_7d]),
            },
            "role_distribution": self._build_distribution(
                [item.role for item in users],
                labels={
                    "admin": "管理员",
                    "user": "普通用户",
                },
            ),
            "task_status_distribution": self._build_distribution(
                [item.status.value for item in tasks],
                labels={
                    "pending": "待处理",
                    "queued": "排队中",
                    "running": "执行中",
                    "succeeded": "已成功",
                    "failed": "已失败",
                    "canceling": "取消中",
                    "canceled": "已取消",
                },
            ),
            "task_kind_distribution": self._build_distribution(
                [item.kind for item in tasks],
                labels={
                    "backtest": "回测",
                    "optimization": "优化",
                    "replay": "复盘",
                },
            ),
            "recent_users": enriched_users[:8],
            "recent_tasks": self._build_recent_tasks(tasks, enriched_users),
            "snapshot_states": self._collect_snapshot_states(backtests),
            "governance_notes": self._build_governance_notes(
                users=len(users),
                running_tasks=len(running_tasks),
                failed_tasks=len(failed_tasks),
                coverage_risk_count=len(coverage_risk_snapshots),
            ),
        }

    def list_users(self) -> list[dict[str, Any]]:
        users = self._user_repository.list()
        sessions = self._session_repository.list()
        projects = self._strategy_repository.list_projects()
        tasks = self._task_repository.list()
        return self._build_user_rows(users, sessions, projects, tasks)

    def update_user_role(
        self,
        *,
        current_user_id: str,
        target_user_id: str,
        role: str,
    ) -> UserRecord:
        normalized_role = role.strip().lower()
        if normalized_role not in {"user", "admin"}:
            raise TaskExecutionError("INVALID_ARGUMENT", "role must be user or admin")

        target = self._user_repository.get(target_user_id)
        if target is None:
            raise TaskExecutionError("NOT_FOUND", "user not found")
        if target.user_id == current_user_id and target.role == "admin" and normalized_role != "admin":
            raise TaskExecutionError("STATE_CONFLICT", "cannot demote current admin session")
        if target.role == "admin" and normalized_role != "admin":
            admin_count = len([item for item in self._user_repository.list() if item.role == "admin"])
            if admin_count <= 1:
                raise TaskExecutionError("STATE_CONFLICT", "cannot demote the last admin")

        updated = self._user_repository.update_role(target_user_id, normalized_role)
        if updated is None:
            raise TaskExecutionError("NOT_FOUND", "user not found")
        return updated

    def _build_user_rows(
        self,
        users: list[UserRecord],
        sessions: list[UserSessionRecord],
        projects: list[StrategyVersionRecord],
        tasks: list[TaskRecord],
    ) -> list[dict[str, Any]]:
        session_count_by_user: dict[str, int] = {}
        for item in sessions:
            session_count_by_user[item.user_id] = session_count_by_user.get(item.user_id, 0) + 1

        project_count_by_user: dict[str, int] = {}
        latest_activity_by_user: dict[str, datetime] = {}
        for item in projects:
            project_count_by_user[item.user_id] = project_count_by_user.get(item.user_id, 0) + 1
            latest_activity_by_user[item.user_id] = max(
                latest_activity_by_user.get(item.user_id, item.created_at),
                item.created_at,
            )

        task_summary_by_user: dict[str, dict[str, int]] = {}
        for item in tasks:
            latest_time = item.finished_at or item.started_at or item.created_at
            latest_activity_by_user[item.user_id] = max(
                latest_activity_by_user.get(item.user_id, latest_time),
                latest_time,
            )
            summary = task_summary_by_user.setdefault(
                item.user_id,
                {
                    "backtests": 0,
                    "replays": 0,
                    "optimizations": 0,
                    "running_tasks": 0,
                    "failed_tasks": 0,
                },
            )
            if item.kind == "backtest":
                summary["backtests"] += 1
            elif item.kind == "replay":
                summary["replays"] += 1
            elif item.kind == "optimization":
                summary["optimizations"] += 1
            if item.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                summary["running_tasks"] += 1
            if item.status in {TaskStatus.FAILED, TaskStatus.CANCELED}:
                summary["failed_tasks"] += 1

        items = [
            {
                "user_id": item.user_id,
                "workspace_id": AuthService.workspace_id_for_user_id(item.user_id),
                "username": item.username,
                "contact": item.contact,
                "role": item.role,
                "created_at": item.created_at.isoformat(),
                "active_sessions": session_count_by_user.get(item.user_id, 0),
                "project_count": project_count_by_user.get(item.user_id, 0),
                "backtest_count": task_summary_by_user.get(item.user_id, {}).get("backtests", 0),
                "replay_count": task_summary_by_user.get(item.user_id, {}).get("replays", 0),
                "optimization_count": task_summary_by_user.get(item.user_id, {}).get("optimizations", 0),
                "running_task_count": task_summary_by_user.get(item.user_id, {}).get("running_tasks", 0),
                "failed_task_count": task_summary_by_user.get(item.user_id, {}).get("failed_tasks", 0),
                "last_activity_at": latest_activity_by_user.get(item.user_id, item.created_at).isoformat(),
            }
            for item in users
        ]
        items.sort(key=lambda item: item["last_activity_at"], reverse=True)
        return items

    def _build_recent_tasks(
        self,
        tasks: list[TaskRecord],
        users: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        usernames = {item["user_id"]: item["username"] for item in users}
        return [
            {
                "task_id": item.id,
                "kind": item.kind,
                "status": item.status.value,
                "created_at": item.created_at.isoformat(),
                "workspace_id": item.workspace_id,
                "user_id": item.user_id,
                "username": usernames.get(item.user_id, item.user_id),
                "config_revision": item.config_revision,
                "dataset_snapshot_ref": item.result.get("dataset_snapshot_ref")
                or item.payload.get("data_snapshot", {}).get("dataset_snapshot_ref"),
                "title": item.result.get("strategy_title")
                or item.result.get("summary")
                or item.payload.get("strategy_version_id")
                or item.payload.get("upload_id")
                or item.kind,
            }
            for item in tasks[:10]
        ]

    def _collect_snapshot_states(self, backtests: list[TaskRecord]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for record in backtests:
            summary = record.result.get("data_snapshot_summary", {})
            snapshot_ref = summary.get("dataset_snapshot_ref") or record.payload.get(
                "data_snapshot",
                {},
            ).get("dataset_snapshot_ref")
            if not snapshot_ref or snapshot_ref in seen:
                continue
            seen.add(snapshot_ref)
            items.append(
                {
                    "dataset_snapshot_ref": snapshot_ref,
                    "provider": summary.get("provider", "未知"),
                    "coverage_status": summary.get("coverage_status", "unknown"),
                    "coverage_pct": summary.get("coverage_pct"),
                    "missing_rate_pct": summary.get("missing_rate_pct"),
                    "calendar": summary.get("calendar"),
                    "timezone": summary.get("timezone"),
                    "warmup_bars": summary.get("warmup_bars"),
                    "last_synced_at": summary.get("last_synced_at"),
                    "market": summary.get("market"),
                    "timeframe": summary.get("timeframe"),
                }
            )
            if len(items) >= 8:
                break
        return items

    def _build_distribution(
        self,
        items: list[str],
        *,
        labels: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in items:
            counts[item] = counts.get(item, 0) + 1
        return [
            {
                "key": key,
                "label": labels.get(key, key) if labels else key,
                "count": value,
            }
            for key, value in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ]

    def _build_governance_notes(
        self,
        *,
        users: int,
        running_tasks: int,
        failed_tasks: int,
        coverage_risk_count: int,
    ) -> list[str]:
        notes: list[str] = []
        if users <= 2:
            notes.append("当前平台仍是低用户规模验证期，建议优先稳住数据可信度和实验对比链路。")
        if running_tasks:
            notes.append("平台当前有运行中任务，建议关注长任务积压和未来的独立 worker 演进。")
        if failed_tasks:
            notes.append("存在失败或取消任务，管理员应优先检查配置冲突、数据快照引用和环境状态。")
        if coverage_risk_count:
            notes.append("部分数据快照存在覆盖风险或缺失率偏高，回测结果在管理视图中需要继续暴露。")
        if not notes:
            notes.append("平台运行状态平稳，下一步更适合推进实验对比、审计视图和管理员操作日志。")
        return notes


class AsyncTaskService:
    def __init__(
        self,
        *,
        repository: TaskRepository,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="jobs")

    def submit(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        build_result: Callable[[str, dict[str, Any]], dict[str, Any]],
        request_id: str,
        user_id: str,
        workspace_id: str,
        idempotency_key: str | None = None,
    ) -> TaskRecord:
        record = self._repository.create(
            TaskRecord(
                kind=kind,
                user_id=user_id,
                payload=payload,
                workspace_id=workspace_id,
                created_by=user_id,
                request_id=request_id,
                trace_id=request_id,
                idempotency_key=idempotency_key,
                config_revision=self._build_config_revision(kind, payload),
                resource_refs=self._build_resource_refs(payload),
            )
        )
        self._repository.mark_queued(record.id)
        mode = self._settings.job_execution_mode
        if mode == "immediate":
            self._run(record.id, payload, build_result)
        else:
            self._executor.submit(self._run, record.id, payload, build_result)
        latest = self._repository.get(record.id)
        assert latest is not None
        return latest

    def get(
        self,
        task_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> TaskRecord | None:
        return self._repository.get(
            task_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )

    def cancel(self, task_id: str) -> TaskRecord | None:
        return self._repository.cancel(task_id)

    def _run(
        self,
        task_id: str,
        payload: dict[str, Any],
        build_result: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        record = self._repository.mark_running(task_id)
        if record is None or record.status.value == "canceled":
            return

        latency_ms = max(self._settings.job_simulation_latency_ms, 0)
        if latency_ms:
            sleep(latency_ms / 1000.0)

        current = self._repository.get(task_id)
        if current is None or current.status.value == "canceled":
            return

        try:
            result = build_result(task_id, payload)
            result.setdefault("config_revision", current.config_revision)
            result.setdefault("request_id", current.request_id)
            result.setdefault("trace_id", current.trace_id)
        except TaskExecutionError as exc:
            self._repository.fail(
                task_id,
                ErrorPayload(code=exc.code, message=exc.message),
            )
            return
        except Exception as exc:  # pragma: no cover - defensive path
            self._repository.fail(
                task_id,
                ErrorPayload(code="INTERNAL_ERROR", message=str(exc)),
            )
            return

        self._repository.complete(task_id, result)

    def _build_config_revision(self, kind: str, payload: dict[str, Any]) -> str:
        snapshot = {
            "kind": kind,
            "payload": payload,
            "backtest_engine_version": self._settings.backtest_engine_version,
            "strategy_prompt_version": self._settings.strategy_prompt_version,
            "replay_prompt_version": self._settings.replay_prompt_version,
        }
        digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return f"cfg_{digest[:16]}"

    def _build_resource_refs(self, payload: dict[str, Any]) -> dict[str, str]:
        refs: dict[str, str] = {}
        if payload.get("strategy_version_id"):
            refs["strategy_version_id"] = payload["strategy_version_id"]
        if payload.get("upload_id"):
            refs["upload_id"] = payload["upload_id"]
        dataset_snapshot_ref = payload.get("data_snapshot", {}).get("dataset_snapshot_ref")
        if dataset_snapshot_ref:
            refs["dataset_snapshot_ref"] = dataset_snapshot_ref
        return refs


def build_backtest_result(
    settings: Settings,
    strategy_service: StrategyService,
    market_data_service: MarketDataService,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    def _builder(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = strategy_service.get_project(
            payload["strategy_version_id"],
            user_id=payload.get("user_id", ""),
            workspace_id=payload.get("workspace_id", "ws_default"),
        )
        if project is None:
            raise TaskExecutionError("NOT_FOUND", "strategy version not found")

        dataset = payload["dataset"]
        bars, data_source = market_data_service.load_daily_bars(
            ts_code=dataset["market"],
            asset_type=dataset.get("asset_type"),
            start_date=datetime.fromisoformat(dataset["from"].replace("Z", "+00:00")).date(),
            end_date=datetime.fromisoformat(dataset["to"].replace("Z", "+00:00")).date(),
            adjustment_mode=payload["execution_contract"].get("adjustment_mode", "qfq"),
        )
        normalized_contract = _normalize_execution_contract(
            payload["execution_contract"],
            project.strategy_dsl,
        )
        backtest = run_backtest(
            strategy_spec={**project.strategy_dsl, "market": dataset["market"]},
            bars=bars,
            execution_contract=normalized_contract,
        )
        dataset_snapshot_ref = payload["data_snapshot"]["dataset_snapshot_ref"]
        return {
            "backtest_run_id": task_id,
            "dataset_snapshot_ref": dataset_snapshot_ref,
            "engine_version": settings.backtest_engine_version,
            "backtest_config": normalized_contract,
            "data_snapshot_summary": _build_data_snapshot_summary(
                dataset_snapshot_ref=dataset_snapshot_ref,
                dataset=dataset,
                execution_contract=normalized_contract,
                data_snapshot=payload.get("data_snapshot", {}),
                data_source=data_source,
                bars=bars,
            ),
            "data_source": data_source,
            "metrics": backtest["metrics"],
            "equity_curve": backtest["equity_curve"],
            "trades": backtest["trades"],
            "strategy_python": project.strategy_python,
            "strategy_title": project.title,
        }

    return _builder


def _normalize_execution_contract(
    execution_contract: dict[str, Any],
    strategy_dsl: dict[str, Any],
) -> dict[str, Any]:
    contract = dict(execution_contract)
    strategy_position = strategy_dsl.get("position", {})
    contract["position_sizing"] = {
        "mode": contract.get("position_sizing", {}).get("mode", "fixed_fraction"),
        "value": float(contract.get("position_sizing", {}).get("value", 1.0)),
        "max_positions": int(
            contract.get("position_sizing", {}).get(
                "max_positions",
                strategy_position.get("max_positions", 1),
            )
        ),
        "max_position_pct": float(
            contract.get("position_sizing", {}).get("max_position_pct", 1.0)
        ),
        "min_trade_unit": int(
            contract.get("position_sizing", {}).get(
                "min_trade_unit",
                100 if strategy_dsl.get("asset_type", "stock") in {"stock", "etf"} else 1,
            )
        ),
    }
    contract["risk_controls"] = {
        "take_profit_pct": float(
            contract.get("risk_controls", {}).get(
                "take_profit_pct",
                _extract_strategy_exit_threshold(strategy_dsl, "take_profit_pct", 0.08),
            )
        ),
        "stop_loss_pct": float(
            contract.get("risk_controls", {}).get(
                "stop_loss_pct",
                _extract_strategy_exit_threshold(strategy_dsl, "stop_loss_pct", -0.03),
            )
        ),
        "max_drawdown_pct": float(
            contract.get("risk_controls", {}).get("max_drawdown_pct", -0.12)
        ),
        "max_holding_bars": int(
            contract.get("risk_controls", {}).get("max_holding_bars", 40)
        ),
    }
    contract["warmup_bars"] = int(contract.get("warmup_bars", 20))
    return contract


def _build_data_snapshot_summary(
    *,
    dataset_snapshot_ref: str,
    dataset: dict[str, Any],
    execution_contract: dict[str, Any],
    data_snapshot: dict[str, Any],
    data_source: dict[str, Any],
    bars: list[Any],
) -> dict[str, Any]:
    coverage_pct = data_snapshot.get("coverage_pct")
    missing_rate_pct = data_snapshot.get("missing_rate_pct")
    if coverage_pct is None:
        coverage_pct = _estimate_coverage_pct(
            start_text=dataset["from"],
            end_text=dataset["to"],
            timeframe=dataset["timeframe"],
            observed_bars=data_source.get("bar_count", len(bars)),
        )
    if missing_rate_pct is None and coverage_pct is not None:
        missing_rate_pct = round(max(0.0, 100.0 - coverage_pct), 2)
    latest_bar = bars[-1] if bars else None
    last_synced_at = (
        data_snapshot.get("last_synced_at")
        or data_source.get("last_synced_at")
        or (latest_bar.fetched_at if latest_bar else None)
    )
    return {
        "dataset_snapshot_ref": dataset_snapshot_ref,
        "market": dataset["market"],
        "timeframe": dataset["timeframe"],
        "asset_type": dataset.get("asset_type", "stock"),
        "provider": data_snapshot.get("provider") or data_source.get("provider", "未知"),
        "coverage_status": data_snapshot.get("coverage_status", "ready"),
        "coverage_pct": coverage_pct,
        "missing_rate_pct": missing_rate_pct,
        "calendar": data_snapshot.get("calendar")
        or execution_contract.get("calendar", "unknown"),
        "timezone": data_snapshot.get("timezone")
        or execution_contract.get("timezone", "UTC"),
        "warmup_bars": int(
            data_snapshot.get("warmup_bars") or execution_contract.get("warmup_bars", 20)
        ),
        "last_synced_at": last_synced_at,
        "served_from_cache": data_source.get("served_from_cache", False),
        "bar_count": data_source.get("bar_count", len(bars)),
        "adjustment_mode": execution_contract.get("adjustment_mode", "qfq"),
    }


def _estimate_coverage_pct(
    *,
    start_text: str,
    end_text: str,
    timeframe: str,
    observed_bars: int,
) -> float | None:
    if timeframe != "1d":
        return None
    start_date = datetime.fromisoformat(start_text.replace("Z", "+00:00")).date()
    end_date = datetime.fromisoformat(end_text.replace("Z", "+00:00")).date()
    if end_date < start_date:
        return None
    expected = 0
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:
            expected += 1
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
    if expected <= 0:
        return None
    return round(min(observed_bars / expected * 100.0, 100.0), 2)


def _extract_strategy_exit_threshold(
    strategy_dsl: dict[str, Any],
    indicator_name: str,
    default_value: float,
) -> float:
    for rule in strategy_dsl.get("exit", {}).get("any", []):
        if rule.get("indicator") == indicator_name:
            return float(rule.get("value", default_value))
    return default_value


def build_optimization_result() -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    def _builder(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        search_space = payload["search_space"]
        best_params = {
            key: values[min(1, len(values) - 1)] for key, values in search_space.items()
        }
        return {
            "job_id": task_id,
            "best_params": best_params,
            "best_metrics": {
                "profit_factor": 1.82,
                "total_return_pct": 21.3,
            },
            "trials": [
                {
                    "params": best_params,
                    "metrics": {"profit_factor": 1.82, "total_return_pct": 21.3},
                }
            ],
        }

    return _builder


def build_replay_result(
    settings: Settings,
    trade_upload_service: TradeUploadService,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    def _builder(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        upload = trade_upload_service.get_upload(payload["upload_id"])
        if upload is None:
            raise TaskExecutionError("NOT_FOUND", "trade upload not found")

        records = upload.records
        total_count = len(records)
        win_records = [item for item in records if item.pnl > 0]
        loss_records = [item for item in records if item.pnl <= 0]
        total_pnl = sum(item.pnl for item in records)
        win_rate = (len(win_records) / total_count) if total_count else 0.0

        side_breakdown: dict[str, dict[str, float]] = {}
        for item in records:
            stats = side_breakdown.setdefault(
                item.side,
                {"count": 0.0, "pnl_sum": 0.0, "avg_holding_minutes": 0.0},
            )
            stats["count"] += 1
            stats["pnl_sum"] += item.pnl
            stats["avg_holding_minutes"] += _holding_minutes(
                item.entry_time,
                item.exit_time,
            )

        for stats in side_breakdown.values():
            if stats["count"]:
                stats["avg_holding_minutes"] = round(
                    stats["avg_holding_minutes"] / stats["count"],
                    2,
                )

        best_side = max(
            side_breakdown.items(),
            key=lambda pair: pair[1]["pnl_sum"],
            default=(
                "long",
                {"count": 0.0, "pnl_sum": 0.0, "avg_holding_minutes": 0.0},
            ),
        )
        worst_side = min(
            side_breakdown.items(),
            key=lambda pair: pair[1]["pnl_sum"],
            default=(
                "short",
                {"count": 0.0, "pnl_sum": 0.0, "avg_holding_minutes": 0.0},
            ),
        )

        avg_win = (
            sum(item.pnl for item in win_records) / len(win_records)
            if win_records
            else 0.0
        )
        avg_loss = (
            sum(item.pnl for item in loss_records) / len(loss_records)
            if loss_records
            else 0.0
        )

        suggestion_rules: list[dict[str, Any]] = []
        if worst_side[1]["count"] > 0 and worst_side[1]["pnl_sum"] < 0:
            suggestion_rules.append(
                {
                    "title": "收缩弱势方向",
                    "description": f"{worst_side[0]} 方向累计表现更弱，建议先降低该方向仓位或增加过滤条件。",
                    "dsl_patch": {
                        "position": {
                            "preferred_side": best_side[0],
                            "reduced_side": worst_side[0],
                        }
                    },
                }
            )
        if loss_records and abs(avg_loss) > avg_win:
            suggestion_rules.append(
                {
                    "title": "收紧止损阈值",
                    "description": "平均亏损显著大于平均盈利，建议把止损收紧到 2% 左右并继续验证。",
                    "dsl_patch": {"risk": {"stop_loss_pct": -0.02}},
                }
            )
        if not suggestion_rules:
            suggestion_rules.append(
                {
                    "title": "扩大样本继续验证",
                    "description": "当前样本没有明显失衡，可保留规则并继续积累更多交易样本。",
                    "dsl_patch": {"note": "keep_current_rules"},
                }
            )

        summary = (
            f"本次复盘共分析 {total_count} 笔交易，胜率 {win_rate:.1%}，总盈亏 {total_pnl:.2f}。"
            f"{best_side[0]} 方向当前表现更优，{worst_side[0]} 方向需要重点优化。"
        )
        return {
            "analysis_id": task_id,
            "dataset_snapshot_ref": payload["data_snapshot"]["dataset_snapshot_ref"],
            "feature_snapshot_ref": f"feature_snapshot_{payload['upload_id']}",
            "analysis_rule_version": "replay_rule_v1",
            "prompt_template_version": settings.replay_prompt_version,
            "summary": summary,
            "winning_patterns": [
                {
                    "dimension": "side_performance",
                    "pattern": f"{best_side[0]} side performed better",
                    "support": round(best_side[1]["count"] / total_count, 2)
                    if total_count
                    else 0.0,
                    "avg_holding_minutes": best_side[1]["avg_holding_minutes"],
                    "pnl_sum": round(best_side[1]["pnl_sum"], 2),
                }
            ],
            "losing_patterns": [
                {
                    "dimension": "side_performance",
                    "pattern": f"{worst_side[0]} side underperformed",
                    "support": round(worst_side[1]["count"] / total_count, 2)
                    if total_count
                    else 0.0,
                    "avg_holding_minutes": worst_side[1]["avg_holding_minutes"],
                    "pnl_sum": round(worst_side[1]["pnl_sum"], 2),
                }
            ],
            "suggestion_rules": suggestion_rules,
        }

    return _builder


def _holding_minutes(entry_time: datetime, exit_time: datetime | None) -> float:
    if exit_time is None:
        return 0.0
    return max((exit_time - entry_time).total_seconds() / 60.0, 0.0)


def _render_strategy_python(
    strategy_spec: dict[str, Any],
    *,
    teaching_mode: bool = False,
    matched_custom_indicators: list[CustomIndicatorRecord] | None = None,
    matched_terms: list[GlossaryTermRecord] | None = None,
) -> str:
    matched_custom_indicators = matched_custom_indicators or []
    matched_terms = matched_terms or []
    timeframes = strategy_spec.get("timeframes") or [strategy_spec["timeframe"]]
    lines: list[tuple[str, str | None]] = [
        ("from dataclasses import dataclass", "导入 dataclass，方便把策略基础配置写成清晰的数据结构。"),
        ("", None),
        ("", None),
        ("@dataclass", "把下面这个类声明成 dataclass，省去手写初始化函数。"),
        ("class StrategyConfig:", "集中保存市场、周期、资产类型这些基础配置。"),
        (
            f"    market_scope: str = '{strategy_spec.get('market_scope', 'cn_equity')}'",
            "记录市场范围，方便后续切换到 A股、美股、加密或伦敦金语义。",
        ),
        (f"    market: str = '{strategy_spec['market']}'", "设置默认研究标的代码。"),
        (
            f"    timeframe: str = '{strategy_spec['timeframe']}'",
            "设置主执行周期，当前回测兼容层会优先参考它。",
        ),
        (
            f"    timeframes: tuple[str, ...] = {tuple(timeframes)!r}",
            "保留策略涉及的全部周期，混合周期策略会在这里显式列出。",
        ),
        (f"    asset_type: str = '{strategy_spec.get('asset_type', 'stock')}'", "设置资产类型，决定市场语义和执行约束。"),
    ]
    if matched_custom_indicators:
        lines.extend(
            [
                ("", None),
                (
                    f"# 已识别自定义指标：{', '.join(item.name for item in matched_custom_indicators)}",
                    None,
                ),
            ]
        )
    if matched_terms:
        lines.extend(
            [
                (
                    f"# 已识别术语：{'；'.join(f'{item.term}={item.meaning}' for item in matched_terms)}",
                    None,
                )
            ]
        )
    lines.extend(
        [
            ("", None),
            (
                f"# 当前回测兼容层实际执行周期：{strategy_spec.get('backtest_timeframe', strategy_spec['timeframe'])}",
                None,
            ),
            ("", None),
            ("def build_strategy():", "构造最终给回测引擎使用的策略结构。"),
            ("    config = StrategyConfig()", "先实例化一份基础配置。"),
            ("    return {", "返回机器可执行的策略字典。"),
            ("        'market_scope': config.market_scope,", "告诉引擎当前策略属于哪个市场范围。"),
            ("        'market': config.market,", "告诉引擎当前回测的标的。"),
            ("        'timeframe': config.timeframe,", "告诉引擎当前回测周期。"),
            ("        'timeframes': list(config.timeframes),", "保留所有分析周期，供多周期引擎复用。"),
            ("        'asset_type': config.asset_type,", "告诉引擎这是股票还是 ETF。"),
            (
                f"        'analysis_mode': '{strategy_spec.get('analysis_mode', 'single_timeframe')}',",
                "声明当前策略是单周期还是混合周期。",
            ),
            (
                f"        'backtest_timeframe': '{strategy_spec.get('backtest_timeframe', strategy_spec['timeframe'])}',",
                "标记现有回测兼容层真正执行的周期。",
            ),
        ]
    )
    if strategy_spec.get("entry_context"):
        lines.extend(
            [
                ("        'entry_context': [", "这里保留跨周期的观察条件，当前先做语义层沉淀。"),
            ]
        )
        for rule in strategy_spec.get("entry_context", []):
            lines.append(
                (
                    "            " + repr(rule) + ",",
                    f"这是一个跨周期入场上下文，表达式是 {rule.get('expression')}。",
                )
            )
        lines.append(("        ],", "跨周期入场上下文结束。"))
    if strategy_spec.get("exit_context"):
        lines.extend(
            [
                ("        'exit_context': [", "这里保留跨周期的离场上下文。"),
            ]
        )
        for rule in strategy_spec.get("exit_context", []):
            lines.append(
                (
                    "            " + repr(rule) + ",",
                    f"这是一个跨周期离场上下文，表达式是 {rule.get('expression')}。",
                )
            )
        lines.append(("        ],", "跨周期离场上下文结束。"))
    lines.extend(
        [
            ("        'entry': {", "下面开始定义入场条件。"),
            ("            'all': [", "all 表示这些条件需要同时满足。"),
        ]
    )
    for rule in strategy_spec.get("entry", {}).get("all", []):
        rule_dict = {
            "indicator": rule.get("indicator"),
            "params": rule.get("params", {}),
            "operator": rule.get("operator"),
            "value": rule.get("value"),
        }
        lines.append(
            (
                "                " + repr(rule_dict) + ",",
                f"这是一个入场条件，当前指标是 {rule.get('indicator')}。",
            )
        )
    lines.extend(
        [
            ("            ]", "入场条件列表结束。"),
            ("        },", "入场配置结束。"),
            ("        'exit': {", "下面开始定义退出条件。"),
            ("            'any': [", "any 表示任意一个退出条件触发就可以离场。"),
        ]
    )
    for rule in strategy_spec.get("exit", {}).get("any", []):
        lines.append(
            (
                "                " + repr(rule) + ",",
                f"这是一个退出条件，当前指标是 {rule.get('indicator')}。",
            )
        )
    lines.extend(
        [
            ("            ]", "退出条件列表结束。"),
            ("        },", "退出配置结束。"),
            (
                f"        'position': {repr(strategy_spec.get('position', {}))},",
                "仓位配置定义了方向和最大持仓数。",
            ),
            ("    }", "策略字典构造完成。"),
            ("", None),
            ("", None),
            ("if __name__ == '__main__':", "本地直接运行脚本时，打印策略内容便于自查。"),
            ("    print(build_strategy())", "输出最终策略结构，用来核对策略是否按预期生成。"),
        ]
    )
    if not teaching_mode:
        return "\n".join(code for code, _ in lines)

    return "\n".join(_format_teaching_line(code, comment) for code, comment in lines)


def _format_teaching_line(code: str, comment: str | None) -> str:
    if not code or not comment:
        return code
    return f"{code}  # {comment}"
