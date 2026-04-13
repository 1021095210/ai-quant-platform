from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import httpx
from io import BytesIO, StringIO
import json
import math
import re
from time import sleep
from typing import Any, Callable

from quant_platform_api.backtest_engine import run_backtest
from quant_platform_api.config import Settings
from quant_platform_api.market_data import MarketDataService
from quant_platform_api.models import (
    AdminAuditLogRecord,
    AppLogRecord,
    AuthEventRecord,
    CustomIndicatorCreateRequest,
    CustomIndicatorGenerateRequest,
    CustomIndicatorRecord,
    DefaultRuleItem,
    DefaultRuleSection,
    DefaultRuleUpdateRequest,
    ErrorPayload,
    GlossaryTermCreateRequest,
    GlossaryTermRecord,
    AssistantResearchRequest,
    MentorAskRequest,
    StrategyVersionRecord,
    StrategyGenerateRequest,
    TaskRecord,
    TaskStatus,
    TradeRecordItem,
    TradeUploadRecord,
    UserProfile,
    UserRecord,
    UserSessionRecord,
    utcnow,
)
from quant_platform_api.repository import (
    AdminAuditLogRepository,
    ApplicationLogRepository,
    AuthEventRepository,
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
    {
        "indicator_key": "atr",
        "title": "ATR 平均真实波幅",
        "summary": "衡量一段时间内的真实波动范围，常用于止损、仓位和突破过滤。",
        "formula_text": "ATR = MA(TR, 14), TR = max(high-low, abs(high-prev_close), abs(low-prev_close))",
        "usage_hint": "适合用于波动止损、移动止损和“突破幅度是否足够”的确认。",
        "python_code": """prev_close = close.shift(1)\ntrue_range = pd.concat([\n    high - low,\n    (high - prev_close).abs(),\n    (low - prev_close).abs(),\n], axis=1).max(axis=1)\natr = true_range.rolling(14).mean()\n""",
        "default_params": {"period": 14},
    },
    {
        "indicator_key": "adx",
        "title": "ADX 趋势强度指标",
        "summary": "衡量趋势是否足够强，而不是只判断涨跌方向。",
        "formula_text": "ADX = MA(DX, 14), DX = abs(+DI - -DI) / (+DI + -DI) * 100",
        "usage_hint": "常见用法是 ADX > 20 或 25 视为趋势开始增强。",
        "python_code": """up_move = high.diff()\ndown_move = -low.diff()\nplus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)\nminus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)\nprev_close = close.shift(1)\ntr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)\natr = tr.rolling(14).mean().replace(0, 1e-9)\nplus_di = 100 * plus_dm.rolling(14).sum() / atr\nminus_di = 100 * minus_dm.rolling(14).sum() / atr\ndx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9) * 100\nadx = dx.rolling(14).mean()\n""",
        "default_params": {"period": 14},
    },
    {
        "indicator_key": "kdj",
        "title": "KDJ 随机指标",
        "summary": "用价格在近期区间内的位置衡量超买超卖和拐点变化。",
        "formula_text": "RSV = (close - LLV(low, 9)) / (HHV(high, 9) - LLV(low, 9)) * 100",
        "usage_hint": "适合短线拐点观察，常用 K 上穿 D 作为金叉提示。",
        "python_code": """low_n = low.rolling(9).min()\nhigh_n = high.rolling(9).max()\nrsv = (close - low_n) / (high_n - low_n).replace(0, 1e-9) * 100\nk = rsv.ewm(alpha=1/3, adjust=False).mean()\nd = k.ewm(alpha=1/3, adjust=False).mean()\nj = 3 * k - 2 * d\n""",
        "default_params": {"period": 9},
    },
    {
        "indicator_key": "cci",
        "title": "CCI 顺势指标",
        "summary": "比较典型价格与其均值偏离程度，常用于寻找强趋势或极端偏离。",
        "formula_text": "CCI = (TP - MA(TP, 14)) / (0.015 * MeanDeviation)",
        "usage_hint": "CCI > 100 常被视为强势，CCI < -100 常被视为弱势。",
        "python_code": """tp = (high + low + close) / 3\nma = tp.rolling(14).mean()\nmean_dev = (tp - ma).abs().rolling(14).mean().replace(0, 1e-9)\ncci = (tp - ma) / (0.015 * mean_dev)\n""",
        "default_params": {"period": 14},
    },
    {
        "indicator_key": "williams_r",
        "title": "WR 威廉指标",
        "summary": "衡量收盘价在近期区间中的相对位置，常用于超买超卖判断。",
        "formula_text": "WR = (HHV(high, 14) - close) / (HHV(high, 14) - LLV(low, 14)) * -100",
        "usage_hint": "常见参考区间是 -20 以上偏强、-80 以下偏弱。",
        "python_code": """highest_high = high.rolling(14).max()\nlowest_low = low.rolling(14).min()\nwr = (highest_high - close) / (highest_high - lowest_low).replace(0, 1e-9) * -100\n""",
        "default_params": {"period": 14},
    },
    {
        "indicator_key": "obv",
        "title": "OBV 能量潮",
        "summary": "把上涨日成交量记为正、下跌日成交量记为负，用于观察量价同步性。",
        "formula_text": "OBV = cumulative(sum(sign(close-close_prev) * volume))",
        "usage_hint": "适合观察价格创新高时，量能是否也在同步抬升。",
        "python_code": """direction = close.diff().fillna(0).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))\nobv = (direction * volume).cumsum()\n""",
        "default_params": {},
    },
    {
        "indicator_key": "vwap",
        "title": "VWAP 成交量加权平均价",
        "summary": "反映成交量加权后的平均成交成本，常用于盘中强弱和机构成本观察。",
        "formula_text": "VWAP = cumulative(sum(price * volume)) / cumulative(sum(volume))",
        "usage_hint": "适合盘中策略，价格站稳 VWAP 常被视为资金承接较强。",
        "python_code": """typical_price = (high + low + close) / 3\nvwap = (typical_price * volume).cumsum() / volume.cumsum().replace(0, 1e-9)\n""",
        "default_params": {},
    },
    {
        "indicator_key": "mfi",
        "title": "MFI 资金流量指标",
        "summary": "结合价格和成交量判断资金流入流出强度。",
        "formula_text": "MFI = 100 - 100 / (1 + PositiveMoneyFlow / NegativeMoneyFlow)",
        "usage_hint": "适合与 RSI 对照使用，过滤只有价格波动、没有量能支持的信号。",
        "python_code": """tp = (high + low + close) / 3\nmoney_flow = tp * volume\ndirection = tp.diff().fillna(0)\npositive = money_flow.where(direction > 0, 0.0)\nnegative = money_flow.where(direction < 0, 0.0)\nmoney_ratio = positive.rolling(14).sum() / negative.rolling(14).sum().replace(0, 1e-9)\nmfi = 100 - 100 / (1 + money_ratio)\n""",
        "default_params": {"period": 14},
    },
    {
        "indicator_key": "roc",
        "title": "ROC 变动率",
        "summary": "比较当前价格与若干周期前价格的百分比变化，常用于动量判断。",
        "formula_text": "ROC = close / REF(close, 12) - 1",
        "usage_hint": "适合配合趋势指标使用，避免在无趋势区间盲目追涨。",
        "python_code": """past_close = close.shift(12).replace(0, 1e-9)\nroc = close / past_close - 1\n""",
        "default_params": {"period": 12},
    },
    {
        "indicator_key": "bias",
        "title": "BIAS 乖离率",
        "summary": "观察价格偏离均线的程度，用来衡量短期过热或超跌。",
        "formula_text": "BIAS = close / SMA(close, 20) - 1",
        "usage_hint": "适合和均线趋势一起看，帮助识别是否偏离过大不宜追价。",
        "python_code": """ma = close.rolling(20).mean().replace(0, 1e-9)\nbias = close / ma - 1\n""",
        "default_params": {"period": 20},
    },
    {
        "indicator_key": "sar",
        "title": "SAR 抛物转向",
        "summary": "通过追踪趋势中的潜在反转点，为止盈止损提供参考。",
        "formula_text": "SAR 基于趋势极值和加速因子逐步上移或下移",
        "usage_hint": "适合趋势跟踪和移动止损，但震荡行情中容易来回反复。",
        "python_code": """# 伪代码：根据上一周期 SAR、极值 EP、加速因子 AF 递推\nsar = previous_sar + af * (ep - previous_sar)\n""",
        "default_params": {"acceleration": 0.02, "max_acceleration": 0.2},
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

STRATEGY_CLARIFICATION_TITLES: dict[str, str] = {
    "volume_threshold": "量能阈值",
    "volume_threshold_followup": "量能阈值补充",
    "chase_guard": "追高限制",
    "chase_guard_followup": "追高限制补充",
    "confirmation_rule": "确认规则",
    "confirmation_ma_period": "确认均线周期",
    "market_regime": "市场环境条件",
    "market_regime_metric": "市场环境判定标准",
    "position_rule": "试仓/仓位规则",
    "pyramiding_rule": "加仓触发规则",
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


PLATFORM_CAPABILITY_MATRIX = {
    "cn_equity": {
        "market_scope": "cn_equity",
        "market_scope_label": "A股",
        "strategy_status": "supported",
        "strategy_label": "可生成并保存策略",
        "backtest_status": "supported",
        "backtest_label": "支持真实日线回测",
        "replay_status": "supported",
        "replay_label": "支持 CSV / 截图 / 手动复盘，当前以 A 股语义最完整",
        "data_status": "supported",
        "data_label": "已接入 A 股日线缓存与快照摘要",
        "notes": [
            "当前真实回测主链路优先覆盖 A 股日线。",
            "混合周期策略会保留为 DSL 上下文，回测兼容层仍按日线执行。",
        ],
        "supported_backtest_timeframes": ["1d"],
        "supported_asset_types": ["stock", "etf"],
    },
    "us_equity": {
        "market_scope": "us_equity",
        "market_scope_label": "美股",
        "strategy_status": "supported",
        "strategy_label": "可生成并保存策略语义",
        "backtest_status": "unsupported",
        "backtest_label": "当前暂不开放真实回测",
        "replay_status": "limited",
        "replay_label": "可手动导入复盘，但自动识别与制度适配仍有限",
        "data_status": "unsupported",
        "data_label": "数据接入与快照链路尚未正式开放",
        "notes": [
            "当前支持市场语义、规则与研究提示，不支持真实回测执行。",
        ],
        "supported_backtest_timeframes": [],
        "supported_asset_types": ["stock", "etf"],
    },
    "crypto": {
        "market_scope": "crypto",
        "market_scope_label": "加密货币",
        "strategy_status": "supported",
        "strategy_label": "可生成并保存策略语义",
        "backtest_status": "unsupported",
        "backtest_label": "当前暂不开放真实回测",
        "replay_status": "limited",
        "replay_label": "支持手动复盘，自动识别仍以 A 股样本优先",
        "data_status": "unsupported",
        "data_label": "数据接入与快照链路尚未正式开放",
        "notes": [
            "当前支持研究语义与 7x24 市场规则提示，不支持真实回测执行。",
        ],
        "supported_backtest_timeframes": [],
        "supported_asset_types": ["crypto"],
    },
    "london_gold": {
        "market_scope": "london_gold",
        "market_scope_label": "伦敦金",
        "strategy_status": "supported",
        "strategy_label": "可生成并保存策略语义",
        "backtest_status": "unsupported",
        "backtest_label": "当前暂不开放真实回测",
        "replay_status": "limited",
        "replay_label": "支持手动复盘，自动识别与行情联动仍有限",
        "data_status": "unsupported",
        "data_label": "数据接入与快照链路尚未正式开放",
        "notes": [
            "当前支持研究语义与连续交易时段提示，不支持真实回测执行。",
        ],
        "supported_backtest_timeframes": [],
        "supported_asset_types": ["commodity"],
    },
}


def list_platform_capabilities() -> list[dict[str, Any]]:
    return [dict(item) for item in PLATFORM_CAPABILITY_MATRIX.values()]


def _llm_endpoint(base_url: str) -> str:
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    return endpoint


def _module_default_llm_model(settings: Settings, module: str) -> str:
    if module == "strategy":
        return (
            settings.llm_model_strategy
            or settings.llm_model_mentor
            or settings.llm_model_summary
            or "gpt-5-mini"
        )
    if module == "mentor":
        return (
            settings.llm_model_mentor
            or settings.llm_model_summary
            or settings.llm_model_strategy
            or "gpt-5-mini"
        )
    if module == "assistant":
        return (
            settings.llm_model_summary
            or settings.llm_model_mentor
            or settings.llm_model_strategy
            or "gpt-5-mini"
        )
    if module == "trade_text_parse":
        return (
            settings.llm_model_mentor
            or settings.llm_model_summary
            or settings.llm_model_strategy
            or "gpt-5-mini"
        )
    return (
        settings.llm_model_summary
        or settings.llm_model_mentor
        or settings.llm_model_strategy
        or "gpt-5-mini"
    )


def list_llm_profiles(settings: Settings) -> list[dict[str, Any]]:
    default_chain_ready = bool(
        settings.llm_base_url.strip()
        and settings.llm_api_key.strip()
    )

    profiles = [
        {
            "profile_id": "module_default",
            "label": "模块默认模型",
            "provider": "openai_compatible",
            "description": "按当前模块使用推荐模型，适合默认场景。",
            "enabled": default_chain_ready,
            "model": "",
            "recommended_modules": [
                "strategy",
                "mentor",
                "assistant",
                "trade_text_parse",
            ],
            "module_model_hints": {
                "strategy": _module_default_llm_model(settings, "strategy"),
                "mentor": _module_default_llm_model(settings, "mentor"),
                "assistant": _module_default_llm_model(settings, "assistant"),
                "trade_text_parse": _module_default_llm_model(settings, "trade_text_parse"),
            },
        },
        {
            "profile_id": "strategy_model",
            "label": "策略模型",
            "provider": "openai_compatible",
            "description": "优先使用策略生成链路配置的模型。",
            "enabled": bool(default_chain_ready and settings.llm_model_strategy.strip()),
            "model": settings.llm_model_strategy,
            "recommended_modules": ["strategy"],
        },
        {
            "profile_id": "mentor_model",
            "label": "导师模型",
            "provider": "openai_compatible",
            "description": "优先使用导师/讲解链路配置的模型。",
            "enabled": bool(default_chain_ready and settings.llm_model_mentor.strip()),
            "model": settings.llm_model_mentor,
            "recommended_modules": ["mentor", "trade_text_parse"],
        },
        {
            "profile_id": "summary_model",
            "label": "研究模型",
            "provider": "openai_compatible",
            "description": "优先使用摘要/研究链路配置的模型。",
            "enabled": bool(default_chain_ready and settings.llm_model_summary.strip()),
            "model": settings.llm_model_summary,
            "recommended_modules": ["assistant"],
        },
        {
            "profile_id": "deepseek",
            "label": "DeepSeek",
            "provider": "deepseek",
            "description": "适合成本敏感或需要备用模型时使用。",
            "enabled": bool(
                settings.llm_deepseek_base_url.strip()
                and settings.llm_deepseek_api_key.strip()
                and settings.llm_deepseek_model.strip()
            ),
            "model": settings.llm_deepseek_model,
            "recommended_modules": [
                "strategy",
                "mentor",
                "assistant",
                "trade_text_parse",
            ],
        },
        {
            "profile_id": "volcengine",
            "label": "火山方舟",
            "provider": "volcengine",
            "description": "适合后续切入火山方舟部署模型或 DeepSeek 接入点。",
            "enabled": bool(
                settings.llm_volcengine_base_url.strip()
                and settings.llm_volcengine_api_key.strip()
                and settings.llm_volcengine_model.strip()
            ),
            "model": settings.llm_volcengine_model,
            "recommended_modules": [
                "strategy",
                "mentor",
                "assistant",
                "trade_text_parse",
            ],
        },
    ]
    return profiles


def _resolve_llm_runtime(
    settings: Settings,
    requested_profile: str | None,
    *,
    module: str,
) -> dict[str, Any] | None:
    profile_id = (requested_profile or "module_default").strip() or "module_default"

    def _default_runtime() -> dict[str, Any] | None:
        if not (
            settings.llm_base_url.strip()
            and settings.llm_api_key.strip()
        ):
            return None
        return {
            "profile_id": "module_default",
            "label": "模块默认模型",
            "provider": "openai_compatible",
            "base_url": settings.llm_base_url,
            "api_key": settings.llm_api_key,
            "model": _module_default_llm_model(settings, module),
        }

    if profile_id == "module_default":
        return _default_runtime()

    if profile_id == "strategy_model":
        if (
            settings.llm_base_url.strip()
            and settings.llm_api_key.strip()
            and settings.llm_model_strategy.strip()
        ):
            return {
                "profile_id": "strategy_model",
                "label": "策略模型",
                "provider": "openai_compatible",
                "base_url": settings.llm_base_url,
                "api_key": settings.llm_api_key,
                "model": settings.llm_model_strategy,
            }
        return _default_runtime()

    if profile_id == "mentor_model":
        if (
            settings.llm_base_url.strip()
            and settings.llm_api_key.strip()
            and settings.llm_model_mentor.strip()
        ):
            return {
                "profile_id": "mentor_model",
                "label": "导师模型",
                "provider": "openai_compatible",
                "base_url": settings.llm_base_url,
                "api_key": settings.llm_api_key,
                "model": settings.llm_model_mentor,
            }
        return _default_runtime()

    if profile_id == "summary_model":
        if (
            settings.llm_base_url.strip()
            and settings.llm_api_key.strip()
            and settings.llm_model_summary.strip()
        ):
            return {
                "profile_id": "summary_model",
                "label": "研究模型",
                "provider": "openai_compatible",
                "base_url": settings.llm_base_url,
                "api_key": settings.llm_api_key,
                "model": settings.llm_model_summary,
            }
        return _default_runtime()

    if profile_id == "deepseek":
        if (
            settings.llm_deepseek_base_url.strip()
            and settings.llm_deepseek_api_key.strip()
            and settings.llm_deepseek_model.strip()
        ):
            return {
                "profile_id": "deepseek",
                "label": "DeepSeek",
                "provider": "deepseek",
                "base_url": settings.llm_deepseek_base_url,
                "api_key": settings.llm_deepseek_api_key,
                "model": settings.llm_deepseek_model,
            }
        return _default_runtime()

    if profile_id == "volcengine":
        if (
            settings.llm_volcengine_base_url.strip()
            and settings.llm_volcengine_api_key.strip()
            and settings.llm_volcengine_model.strip()
        ):
            return {
                "profile_id": "volcengine",
                "label": "火山方舟",
                "provider": "volcengine",
                "base_url": settings.llm_volcengine_base_url,
                "api_key": settings.llm_volcengine_api_key,
                "model": settings.llm_volcengine_model,
            }
        return _default_runtime()

    return _default_runtime()


def summarize_strategy_capability(
    *,
    market_scope: str,
    primary_timeframe: str,
    timeframes: list[str] | None = None,
    analysis_mode: str = "single_timeframe",
) -> dict[str, Any]:
    base = dict(
        PLATFORM_CAPABILITY_MATRIX.get(
            market_scope,
            {
                "market_scope": market_scope,
                "market_scope_label": _market_scope_label(market_scope),
                "strategy_status": "supported",
                "strategy_label": "可生成并保存策略语义",
                "backtest_status": "unsupported",
                "backtest_label": "当前暂不开放真实回测",
                "replay_status": "limited",
                "replay_label": "复盘支持有限",
                "data_status": "unsupported",
                "data_label": "数据接入尚未开放",
                "notes": [],
                "supported_backtest_timeframes": [],
                "supported_asset_types": [],
            },
        )
    )
    selected_timeframes = list(dict.fromkeys(timeframes or [primary_timeframe]))
    summary = {
        **base,
        "primary_timeframe": primary_timeframe,
        "timeframes": selected_timeframes,
        "analysis_mode": analysis_mode,
        "backtest_mode_label": base["backtest_label"],
        "backtest_warning": "",
        "requires_compatibility_notice": False,
    }
    if market_scope == "cn_equity":
        if (
            _canonicalize_timeframe(primary_timeframe) != "1d"
            or len(selected_timeframes) > 1
            or analysis_mode == "multi_timeframe"
        ):
            summary["backtest_status"] = "limited"
            summary["backtest_mode_label"] = "仅支持日线兼容层回测"
            summary["backtest_warning"] = (
                "当前策略包含非日线或混合周期条件。保存和研究语义正常，但真实回测仍按日线兼容层执行。"
            )
            summary["requires_compatibility_notice"] = True
        else:
            summary["backtest_mode_label"] = "可直接运行真实日线回测"
            summary["backtest_warning"] = "当前组合处于平台真实回测主链路内。"
    else:
        summary["backtest_warning"] = (
            f"{base['market_scope_label']} 当前仅支持策略语义与规则研究，回测中心会阻止发起真实回测。"
        )
    return summary


def validate_backtest_capability(strategy_dsl: dict[str, Any]) -> None:
    summary = summarize_strategy_capability(
        market_scope=strategy_dsl.get("market_scope", "cn_equity"),
        primary_timeframe=strategy_dsl.get("timeframe", "1d"),
        timeframes=strategy_dsl.get("timeframes") or [strategy_dsl.get("timeframe", "1d")],
        analysis_mode=strategy_dsl.get("analysis_mode", "single_timeframe"),
    )
    if summary["backtest_status"] == "unsupported":
        raise TaskExecutionError(
            "INVALID_ARGUMENT",
            f"{summary['market_scope_label']} 当前仅支持策略语义和规则研究，暂不开放真实回测。",
        )


def _safe_number(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _extract_strategy_questions(
    prompt: str,
    normalized: str,
    clarification_answers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    clarification_answers = clarification_answers or {}

    def add(
        question_id: str,
        title: str,
        detail: str,
        suggested_choices: list[str],
        *,
        depends_on: str | None = None,
    ) -> None:
        answer = (clarification_answers.get(question_id) or "").strip()
        if answer:
            return
        if any(item["id"] == question_id for item in questions):
            return
        round_type = "followup" if depends_on else "initial"
        questions.append(
            {
                "id": question_id,
                "title": title,
                "detail": detail,
                "suggested_choices": suggested_choices,
                "depends_on": depends_on,
                "depends_on_title": STRATEGY_CLARIFICATION_TITLES.get(depends_on or "", depends_on),
                "round_type": round_type,
            }
        )

    if ("量能放大" in prompt or "放量" in prompt or "量价共振" in prompt) and not re.search(
        r"(量比|成交量|成交额).{0,8}(\d+(\.\d+)?)",
        prompt,
    ):
        add(
            "volume_threshold",
            "量能条件需要补阈值",
            "当前已识别到量能相关条件，但没有看到明确阈值。建议补充量比、均量倍数或成交额阈值。",
            ["量比 >= 1.2", "成交量 >= 10日均量的 1.5 倍", "成交额 >= 过去 20 日均值"],
        )
    if "不追高" in prompt or "别追高" in prompt or "不要追高" in prompt:
        add(
            "chase_guard",
            "追高限制需要补定义",
            "当前已识别到“不追高”，但还没有价格边界。建议补充前 15 分钟涨幅上限、开盘涨幅上限或距离前高约束。",
            ["前 15 分钟涨幅 <= 1%", "开盘涨幅 <= 2%", "距离前高 >= 1% 才允许追入"],
        )
    if "确认后" in prompt or "等确认" in prompt or "确认再" in prompt:
        add(
            "confirmation_rule",
            "确认条件需要补充",
            "当前提到了“确认后再入场”，但没有说明确认依据。建议明确是均线确认、分钟结构确认、放量确认还是收盘确认。",
            ["15 分钟收盘站上均线", "阳线占比 >= 50%", "量比 >= 1.2 后再入场"],
        )
    if "大盘不差" in prompt or "市场环境好" in prompt or "环境允许" in prompt:
        add(
            "market_regime",
            "市场环境条件需要补定义",
            "当前已识别到环境过滤，但没有给出明确标准。建议补充趋势市、指数均线位置、波动率或行业强弱条件。",
            ["指数站上 20 日均线", "只在趋势市开仓", "行业强度排名前 30%"],
        )
    if "试仓" in prompt and "仓位" not in prompt:
        add(
            "position_rule",
            "试仓规则需要补充",
            "当前提到了“试仓”，建议补充试仓仓位比例或最大持仓数。",
            ["首次仓位 20%", "最多 1 只持仓", "分两次加仓"],
        )

    volume_answer = (clarification_answers.get("volume_threshold") or "").strip()
    if volume_answer and _extract_number(volume_answer) is None:
        add(
            "volume_threshold_followup",
            "量能规则仍需明确数值或比较口径",
            "当前已经补了量能说明，但还缺少可执行的数值阈值。建议直接给出量比、均量倍数或成交额门槛。",
            ["量比 >= 1.2", "成交量 >= 10日均量的 1.5 倍", "成交额 >= 20日均值"],
            depends_on="volume_threshold",
        )

    chase_answer = (clarification_answers.get("chase_guard") or "").strip()
    if chase_answer and _extract_number(chase_answer) is None:
        add(
            "chase_guard_followup",
            "追高限制仍需明确边界",
            "当前已经补了追高说明，但还缺少可执行阈值。建议直接给出涨幅上限、距离前高比例或分钟窗口边界。",
            ["前 15 分钟涨幅 <= 1%", "距离前高 >= 1% 才允许追入", "开盘涨幅 <= 2%"],
            depends_on="chase_guard",
        )

    confirmation_answer = (clarification_answers.get("confirmation_rule") or "").strip()
    if confirmation_answer and "均线" in confirmation_answer and not re.search(
        r"(\d+\s*(日|分钟|m|h)?\s*均线|ma\s*\d+)",
        confirmation_answer,
        flags=re.IGNORECASE,
    ) and not re.search(
        r"(收盘|站上|突破|回踩|15分钟|30分钟|60分钟|日线|周线|月线|主周期)",
        confirmation_answer,
    ):
        add(
            "confirmation_ma_period",
            "确认规则里的均线周期仍需补充",
            "你已经说明要做均线确认，但还没有说明具体均线周期。建议补充 5 日、10 日、20 日或分钟均线周期。",
            ["15 分钟收盘站上 5 均线", "15 分钟收盘站上 10 均线", "日线站上 20 日均线"],
            depends_on="confirmation_rule",
        )

    market_regime_answer = (clarification_answers.get("market_regime") or "").strip()
    if market_regime_answer and not re.search(
        r"(均线|排名|波动率|强度|涨幅|beta|百分位|量能|行业)",
        market_regime_answer,
        flags=re.IGNORECASE,
    ):
        add(
            "market_regime_metric",
            "市场环境条件还缺少判定标准",
            "你已经说明需要环境过滤，但还没有给出平台可执行的判定标准。建议补充指数均线、行业排名、波动率或资金强度条件。",
            ["指数站上 20 日均线", "行业强度排名前 30%", "波动率低于过去 20 日 70% 分位"],
            depends_on="market_regime",
        )

    position_answer = (clarification_answers.get("position_rule") or "").strip()
    if position_answer and ("加仓" in position_answer or "分两次" in position_answer) and not re.search(
        r"(回踩|突破|盈利|亏损|涨|跌|触发|超过|低于)",
        position_answer,
    ):
        add(
            "pyramiding_rule",
            "加仓规则仍需补触发条件",
            "当前已识别到分批建仓或加仓，但还没有看到何时加仓。建议补充突破、回踩、盈利扩张或风险收敛条件。",
            ["首次 20%，突破前高后再加 20%", "首次 30%，回踩均线确认后再加仓", "首次 20%，浮盈 2% 后再加仓"],
            depends_on="position_rule",
        )
    return questions


def _extract_number(text: str) -> float | None:
    match = re.search(r"(-?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _apply_strategy_clarifications(
    *,
    strategy_dsl: dict[str, Any],
    clarification_answers: dict[str, str],
    entry_context: list[dict[str, Any]],
) -> None:
    cleaned = {
        key: value.strip()
        for key, value in clarification_answers.items()
        if isinstance(value, str) and value.strip()
    }
    if not cleaned:
        return

    strategy_dsl["clarifications"] = cleaned
    filters = strategy_dsl.setdefault("filters", {})

    volume_answer = cleaned.get("volume_threshold")
    if volume_answer:
        numeric = _extract_number(volume_answer)
        if numeric is not None and not any(item.get("indicator") == "volume_ratio" for item in strategy_dsl.get("entry", {}).get("all", [])):
            strategy_dsl["entry"]["all"].append(
                {
                    "indicator": "volume_ratio",
                    "params": {"period": 10},
                    "operator": ">=",
                    "value": numeric,
                    "timeframe": strategy_dsl["timeframe"],
                }
            )

    chase_answer = cleaned.get("chase_guard")
    if chase_answer:
        numeric = _extract_number(chase_answer)
        if numeric is not None:
            filters["intraday_entry_timing"] = {
                "enabled": True,
                "max_first_15m_return_pct": numeric,
                "source": "clarification_answer",
            }

    confirmation_answer = cleaned.get("confirmation_rule")
    if confirmation_answer:
        entry_context.append(
            {
                "timeframe": strategy_dsl["timeframe"],
                "expression": f"补充确认规则：{confirmation_answer}",
                "indicator": "clarified_confirmation_rule",
                "operator": "==",
                "value": True,
            }
        )

    market_regime_answer = cleaned.get("market_regime")
    if market_regime_answer:
        filters["market_regime"] = {
            "enabled": True,
            "preferred": market_regime_answer,
            "source": "clarification_answer",
        }

    position_answer = cleaned.get("position_rule")
    if position_answer:
        strategy_dsl.setdefault("position", {})["clarified_rule"] = position_answer

    volume_followup_answer = cleaned.get("volume_threshold_followup")
    if volume_followup_answer:
        numeric = _extract_number(volume_followup_answer)
        if numeric is not None:
            for item in strategy_dsl.get("entry", {}).get("all", []):
                if item.get("indicator") == "volume_ratio":
                    item["operator"] = ">="
                    item["value"] = numeric
                    break

    chase_followup_answer = cleaned.get("chase_guard_followup")
    if chase_followup_answer:
        numeric = _extract_number(chase_followup_answer)
        if numeric is not None:
            filters["intraday_entry_timing"] = {
                "enabled": True,
                "max_first_15m_return_pct": numeric,
                "source": "clarification_answer",
            }

    confirmation_period_answer = cleaned.get("confirmation_ma_period")
    if confirmation_period_answer:
        entry_context.append(
            {
                "timeframe": strategy_dsl["timeframe"],
                "expression": f"补充均线确认：{confirmation_period_answer}",
                "indicator": "clarified_confirmation_period",
                "operator": "==",
                "value": True,
            }
        )

    market_regime_metric_answer = cleaned.get("market_regime_metric")
    if market_regime_metric_answer:
        filters["market_regime"] = {
            "enabled": True,
            "preferred": market_regime_metric_answer,
            "source": "clarification_answer",
        }

    pyramiding_answer = cleaned.get("pyramiding_rule")
    if pyramiding_answer:
        strategy_dsl.setdefault("position", {})["pyramiding_rule"] = pyramiding_answer


def _build_strategy_clarification_round(
    *,
    clarification_answers: dict[str, str],
    questions_for_user: list[dict[str, Any]],
) -> dict[str, Any]:
    answered_items = [
        {
            "id": key,
            "title": STRATEGY_CLARIFICATION_TITLES.get(key, key),
            "answer": value,
        }
        for key, value in clarification_answers.items()
        if isinstance(value, str) and value.strip()
    ]
    pending_topics = [
        {
            "id": item["id"],
            "title": item["title"],
            "depends_on": item.get("depends_on"),
            "depends_on_title": item.get("depends_on_title"),
            "round_type": item.get("round_type", "initial"),
        }
        for item in questions_for_user
    ]
    pending_count = len(questions_for_user)
    answered_count = len(answered_items)
    if pending_count == 0 and answered_count == 0:
        status = "no_questions"
        stage_label = "当前无需澄清"
        guidance = "当前策略表达已经足够清晰，没有待补充问题。"
    elif pending_count == 0:
        status = "completed"
        stage_label = "澄清完成"
        guidance = "当前补充项已经足够，系统可以据此进入正式理解与生成链路。"
    elif answered_count == 0:
        status = "first_round_pending"
        stage_label = "第一轮澄清"
        guidance = "请先补充这些关键条件，系统才能判断是否能生成正式策略版本。"
    else:
        status = "followup_pending"
        stage_label = "继续澄清"
        guidance = "系统已吸收你上一轮补充结果，但仍有下一轮待确认项。继续补充后再生成正式版本。"
    next_focus = pending_topics[0]["title"] if pending_topics else None
    if answered_items:
        memory_summary = "；".join(
            f"{item['title']}={item['answer']}" for item in answered_items[:4]
        )
    else:
        memory_summary = "当前还没有已确认的补充项。"
    return {
        "status": status,
        "stage_label": stage_label,
        "guidance": guidance,
        "answered_count": answered_count,
        "pending_count": pending_count,
        "answered_items": answered_items,
        "pending_topics": pending_topics,
        "memory_summary": memory_summary,
        "next_focus": next_focus,
    }


def _extract_strategy_unsupported_items(prompt: str, normalized: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add(item_id: str, title: str, detail: str, level: str = "hard") -> None:
        if any(entry["id"] == item_id for entry in items):
            return
        items.append(
            {
                "id": item_id,
                "title": title,
                "detail": detail,
                "level": level,
            }
        )

    if any(marker in prompt or marker in normalized for marker in ["盘口", "逐笔", "委托队列", "l2", "orderbook", "tick逐笔"]):
        add(
            "market_microstructure",
            "当前不支持盘口 / 逐笔 / L2 数据驱动策略",
            "策略里出现了盘口、逐笔成交或委托队列语义。平台当前没有把这类数据接入策略工坊真值层，不能生成可靠可执行版本。",
        )
    if any(marker in prompt or marker in normalized for marker in ["公告", "新闻", "研报", "舆情", "微博", "社交媒体", "消息面", "财报发布"]):
        add(
            "external_event_dependency",
            "当前不支持实时公告 / 新闻 / 舆情驱动的真值策略条件",
            "策略里出现了公告、新闻、研报或舆情这类外部事件依赖。平台当前还没有把这些事件源接入策略工坊真值层，不能直接生成可靠可执行版本。",
        )
    if any(
        marker in prompt or marker in normalized
        for marker in [
            "北向资金",
            "主力资金",
            "资金净流入",
            "资金流入",
            "龙虎榜",
            "融资融券",
            "两融",
            "封单",
            "封板资金",
        ]
    ):
        add(
            "capital_flow_dependency",
            "当前不支持资金面 / 榜单驱动的真值策略条件",
            "策略里出现了北向资金、主力资金、龙虎榜、融资融券或封单这类资金面 / 榜单依赖。平台当前没有把它们接入策略工坊真值层，不能直接生成可靠可执行版本。",
        )
    if any(marker in prompt or marker in normalized for marker in ["集合竞价", "竞价", "盘前", "盘后", "夜盘", "尾盘竞价"]):
        add(
            "session_execution_dependency",
            "当前不支持集合竞价 / 盘前盘后 / 夜盘执行语义",
            "策略里出现了集合竞价、盘前盘后或夜盘执行语义。平台当前真实执行链路还没有对这类会话阶段建模，不能直接生成可靠可执行版本。",
        )
    future_rules = [
        (
            "future_reference_low",
            ("当日最低价", "今日最低价", "盘中最低价"),
            ("买入", "开仓"),
            "用“当日最低价/盘中最低价”作为当日买入触发条件，容易在入场时引用尚未发生的未来信息。需要改写成当下可观察条件。",
        ),
        (
            "future_reference_high_entry",
            ("当日最高价", "今日最高价", "盘中最高价"),
            ("买入", "开仓"),
            "用“当日最高价/盘中最高价”辅助当日买入，会在入场决策时引用尚未发生的未来信息。需要改写成当下可观察条件。",
        ),
        (
            "future_reference_high",
            ("当日最高价", "今日最高价", "盘中最高价"),
            ("卖出", "止盈"),
            "用“当日最高价/盘中最高价”作为离场条件，容易在决策时引用未来信息。需要改写成当下可观察条件。",
        ),
        (
            "future_reference_close",
            ("当日收盘价", "今日收盘价"),
            ("买入", "开仓", "卖出", "止盈", "止损"),
            "直接使用“当日收盘价/今日收盘价”作为当日盘中决策依据，容易在尚未收盘时引用未来信息。需要改写成收盘后执行或次日执行条件。",
        ),
        (
            "future_reference_pct_change",
            ("当日涨幅", "今日涨幅", "最终涨幅"),
            ("买入", "开仓", "卖出", "止盈", "止损"),
            "直接使用“当日涨幅/今日涨幅/最终涨幅”作为当日盘中决策依据，会把尚未收盘的最终结果当成已知信息。需要改写成当前涨幅或上一周期涨幅。",
        ),
        (
            "future_reference_amplitude",
            ("当日振幅", "今日振幅", "最终振幅"),
            ("买入", "开仓", "卖出", "止盈", "止损"),
            "直接使用“当日振幅/今日振幅/最终振幅”作为当日盘中决策依据，会把尚未完成的全天波动范围当成已知信息。需要改写成当前窗口振幅或上一周期振幅。",
        ),
        (
            "future_reference_volume",
            ("当日成交量", "今日成交量", "全天成交量", "最终成交量"),
            ("买入", "开仓", "卖出", "止盈", "止损", "确认"),
            "直接使用“当日成交量/全天成交量/最终成交量”作为盘中条件，会把尚未完成的全天成交结果当成已知信息。需要改写成当前量比、当前分钟成交量或上一周期量能。",
        ),
    ]
    for item_id, metric_markers, action_markers, detail in future_rules:
        if any(marker in prompt for marker in metric_markers) and any(marker in prompt for marker in action_markers):
            add(item_id, "当前表达存在未来函数风险", detail)
    if ("收盘前" in prompt or "尾盘前" in prompt) and ("确认" in prompt or "判断" in prompt) and ("收盘价" in prompt):
        add(
            "future_close_confirmation",
            "当前表达存在未来函数风险",
            "在“收盘前”使用“收盘价确认”会把尚未形成的最终收盘价当成当下可见信息，需要改写成收盘后确认或使用当前价格条件。",
        )
    return items


def _build_strategy_understanding(
    *,
    request: StrategyGenerateRequest,
    market_scope_label: str,
    selected_timeframes: list[str],
    strategy_dsl: dict[str, Any],
    entry_context: list[dict[str, Any]],
    exit_context: list[dict[str, Any]],
    matched_custom_indicators: list[CustomIndicatorRecord],
    matched_terms: list[GlossaryTermRecord],
    questions_for_user: list[dict[str, Any]],
    unsupported_items: list[dict[str, Any]],
    capability_summary: dict[str, Any],
    ai_interpretation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry_conditions = [
        {
            "label": item.get("indicator"),
            "timeframe": _timeframe_label(item.get("timeframe", strategy_dsl["timeframe"])),
            "operator": item.get("operator"),
            "value": item.get("value"),
        }
        for item in strategy_dsl.get("entry", {}).get("all", [])
    ]
    exit_conditions = [
        {
            "label": item.get("indicator"),
            "timeframe": _timeframe_label(item.get("timeframe", strategy_dsl["timeframe"])),
            "operator": item.get("operator"),
            "value": item.get("value"),
        }
        for item in strategy_dsl.get("exit", {}).get("any", [])
    ]
    risk_controls = [
        {
            "label": "止盈比例",
            "value": next(
                (item.get("value") for item in strategy_dsl.get("exit", {}).get("any", []) if item.get("indicator") == "take_profit_pct"),
                None,
            ),
        },
        {
            "label": "止损比例",
            "value": next(
                (item.get("value") for item in strategy_dsl.get("exit", {}).get("any", []) if item.get("indicator") == "stop_loss_pct"),
                None,
            ),
        },
    ]
    execution_assumptions = [
        f"当前主执行周期：{_timeframe_label(strategy_dsl['timeframe'])}",
        f"当前回测兼容层周期：{_timeframe_label(strategy_dsl.get('backtest_timeframe', strategy_dsl['timeframe']))}",
    ]
    if capability_summary.get("requires_compatibility_notice"):
        execution_assumptions.append("混合周期或非日线条件当前会先沉淀为语义层，真实回测仍按日线兼容层理解。")
    if request.market_scope != "cn_equity":
        execution_assumptions.append("当前市场只支持策略语义与规则研究，不支持真实回测执行。")
    ai_summary = (ai_interpretation or {}).get("summary") or ""
    return {
        "parse_mode": (ai_interpretation or {}).get("mode", "rules_only"),
        "market_scope_label": market_scope_label,
        "market": request.market,
        "asset_type": request.asset_type,
        "primary_timeframe_label": _timeframe_label(strategy_dsl["timeframe"]),
        "timeframe_labels": [_timeframe_label(item) for item in selected_timeframes],
        "data_dependencies": [
            f"{market_scope_label} 行情",
            *([f"{item.name}（自定义指标）" for item in matched_custom_indicators] or []),
            *([f"{item.term}（术语解释）" for item in matched_terms] or []),
        ],
        "entry_conditions": entry_conditions,
        "entry_context": entry_context,
        "exit_conditions": exit_conditions,
        "exit_context": exit_context,
        "risk_controls": [item for item in risk_controls if item["value"] is not None],
        "position_rules": strategy_dsl.get("position", {}),
        "clarifications": strategy_dsl.get("clarifications", {}),
        "execution_assumptions": execution_assumptions,
        "ambiguities": [item["title"] for item in questions_for_user],
        "questions_for_user": questions_for_user,
        "unsupported_items": unsupported_items,
        "capability_summary": capability_summary,
        "ai_summary": ai_summary,
        "ai_profile_label": (ai_interpretation or {}).get("llm_profile_label", ""),
        "ai_unresolved_items": (ai_interpretation or {}).get("unresolved_items", []),
        "ai_risky_items": (ai_interpretation or {}).get("risky_items", []),
    }


def _build_strategy_structured_spec(
    *,
    request: StrategyGenerateRequest,
    market_scope_label: str,
    strategy_dsl: dict[str, Any],
    capability_summary: dict[str, Any],
    questions_for_user: list[dict[str, Any]],
    unsupported_items: list[dict[str, Any]],
    ai_interpretation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ai_hints = _build_strategy_ai_structured_hints(
        ai_interpretation=ai_interpretation,
        market_scope_label=market_scope_label,
        selected_timeframes=strategy_dsl.get("timeframes", []),
    )
    ai_unresolved_items = [
        item.get("title", "")
        for item in (ai_interpretation or {}).get("unresolved_items", [])
        if item.get("title")
    ]
    ai_field_targets = _build_strategy_ai_field_targets(ai_hints, ai_unresolved_items)
    ai_value_targets = _build_strategy_ai_value_targets(ai_hints, ai_unresolved_items)
    return {
        "market_scope_label": market_scope_label,
        "market": request.market,
        "asset_type": request.asset_type,
        "analysis_mode": strategy_dsl.get("analysis_mode", "single_timeframe"),
        "primary_timeframe_label": _timeframe_label(strategy_dsl["timeframe"]),
        "observation_timeframe_labels": [
            _timeframe_label(item) for item in strategy_dsl.get("timeframes", [])
        ],
        "entry_rule_count": len(strategy_dsl.get("entry", {}).get("all", [])),
        "entry_context_count": len(strategy_dsl.get("entry_context", [])),
        "exit_rule_count": len(strategy_dsl.get("exit", {}).get("any", [])),
        "exit_context_count": len(strategy_dsl.get("exit_context", [])),
        "data_dependencies": capability_summary.get("notes", []),
        "position": strategy_dsl.get("position", {}),
        "execution_assumptions": [
            f"主执行周期：{_timeframe_label(strategy_dsl['timeframe'])}",
            f"回测兼容层：{_timeframe_label(strategy_dsl.get('backtest_timeframe', strategy_dsl['timeframe']))}",
        ],
        "clarifications": strategy_dsl.get("clarifications", {}),
        "clarification_memory": "；".join(
            f"{STRATEGY_CLARIFICATION_TITLES.get(key, key)}={value}"
            for key, value in strategy_dsl.get("clarifications", {}).items()
        ),
        "open_questions": [item["title"] for item in questions_for_user],
        "unsupported_items": [item["title"] for item in unsupported_items],
        "ai_candidate_summary": (ai_interpretation or {}).get("summary", ""),
        "ai_profile_label": (ai_interpretation or {}).get("llm_profile_label", ""),
        "ai_unresolved_items": ai_unresolved_items,
        "ai_structured_hints": ai_hints,
        "ai_field_targets": ai_field_targets,
        "ai_value_targets": ai_value_targets,
    }


def _build_strategy_hard_validation(
    *,
    capability_summary: dict[str, Any],
    generation_decision: dict[str, Any],
    questions_for_user: list[dict[str, Any]],
    unsupported_items: list[dict[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(check_id: str, title: str, status: str, detail: str) -> None:
        checks.append(
            {
                "id": check_id,
                "title": title,
                "status": status,
                "detail": detail,
            }
        )

    backtest_status = capability_summary.get("backtest_status", "unsupported")
    add(
        "market_execution_support",
        "市场与回测支持范围",
        "pass" if backtest_status == "supported" else "warn",
        capability_summary.get("backtest_warning")
        or "当前策略的真实执行范围需要继续确认。",
    )

    add(
        "timeframe_execution_scope",
        "周期与执行兼容范围",
        "pass"
        if not capability_summary.get("requires_compatibility_notice")
        else "warn",
        "当前周期组合处于平台真实执行主链路内。"
        if not capability_summary.get("requires_compatibility_notice")
        else "当前策略包含混合周期或非日线条件，当前真实回测仍按日线兼容层理解。",
    )

    add(
        "clarification_completeness",
        "模糊条件与补充信息",
        "pass" if not questions_for_user else "warn",
        "当前没有待补充问题。"
        if not questions_for_user
        else "仍有模糊条件或缺参数，需要用户补充后再进入正式版本。",
    )

    future_risk_items = [
        item for item in unsupported_items if "future_" in item.get("id", "")
    ]
    add(
        "future_function_risk",
        "未来函数风险",
        "pass" if not future_risk_items else "fail",
        "当前没有识别到明显未来函数风险。"
        if not future_risk_items
        else "当前表达引用了同日最高价/最低价等未来信息，不能直接生成可靠策略。",
    )

    microstructure_items = [
        item for item in unsupported_items if item.get("id") == "market_microstructure"
    ]
    external_event_items = [
        item for item in unsupported_items if item.get("id") == "external_event_dependency"
    ]
    capital_flow_items = [
        item for item in unsupported_items if item.get("id") == "capital_flow_dependency"
    ]
    session_execution_items = [
        item for item in unsupported_items if item.get("id") == "session_execution_dependency"
    ]
    add(
        "unsupported_data_dependency",
        "平台不支持的数据依赖",
        "pass" if not (microstructure_items or external_event_items or capital_flow_items or session_execution_items) else "fail",
        "当前表达没有依赖平台未接入的数据源或执行会话。"
        if not (microstructure_items or external_event_items or capital_flow_items or session_execution_items)
        else "当前策略依赖了平台真值层尚未支持的数据源或执行会话，例如盘口/L2、实时公告新闻、资金面榜单、集合竞价或盘前盘后执行。",
    )

    add(
        "formal_generation_state",
        "正式策略生成资格",
        "pass" if generation_decision.get("allow_save") else "warn",
        generation_decision.get("summary")
        or "当前仍需继续确认后才能进入正式版本。",
    )

    if any(item.get("status") == "fail" for item in checks):
        overall_status = "fail"
    elif any(item.get("status") == "warn" for item in checks):
        overall_status = "warn"
    else:
        overall_status = "pass"

    return {
        "overall_status": overall_status,
        "checks": checks,
    }


def _build_strategy_generation_pipeline(
    *,
    request: StrategyGenerateRequest,
    strategy_dsl: dict[str, Any],
    generation_decision: dict[str, Any],
    structured_spec: dict[str, Any],
    hard_validation: dict[str, Any],
    ai_interpretation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items = [
        {
            "id": "natural_language",
            "title": "自然语言策略想法",
            "status": "pass",
            "summary": "用户原始输入，作为策略理解起点。",
            "detail": request.prompt.strip(),
        },
    ]
    if ai_interpretation:
        items.append(
            {
                "id": "ai_understanding",
                "title": "AI 候选理解",
                "status": "pass"
                if not ai_interpretation.get("unresolved_items")
                else "warn",
                "summary": "AI 只负责补强策略语义理解，不能直接决定平台真值层或绕过硬校验。",
                "detail": ai_interpretation.get("summary")
                or "当前没有 AI 候选理解摘要。",
            }
        )
    items.extend([
        {
            "id": "structured_spec",
            "title": "结构化策略规格",
            "status": "pass" if not structured_spec.get("open_questions") else "warn",
            "summary": "平台真值层，后续 DSL 与代码都基于这层生成。",
            "detail": f"市场={structured_spec['market_scope_label']}，主周期={structured_spec['primary_timeframe_label']}，入场规则={structured_spec['entry_rule_count']} 条，离场规则={structured_spec['exit_rule_count']} 条。",
        },
        {
            "id": "hard_validation",
            "title": "平台硬校验",
            "status": hard_validation["overall_status"],
            "summary": "由平台规则判断是否可进入正式版本，不交给 AI 自己决定。",
            "detail": "；".join(
                f"{item['title']}：{'通过' if item['status'] == 'pass' else '需确认' if item['status'] == 'warn' else '拒绝'}"
                for item in hard_validation["checks"]
            ),
        },
        {
            "id": "clarification_context",
            "title": "澄清上下文记忆",
            "status": "pass" if strategy_dsl.get("clarifications") else "warn",
            "summary": "已回答的补充项会继续进入后续轮次，而不是每轮都从头询问。",
            "detail": "；".join(
                f"{STRATEGY_CLARIFICATION_TITLES.get(key, key)}={value}"
                for key, value in strategy_dsl.get("clarifications", {}).items()
            )
            or "当前还没有已确认的补充项。",
        },
        {
            "id": "dsl",
            "title": "DSL / 结构化执行规格",
            "status": "pass",
            "summary": "回测与保存当前以这份 DSL 作为主执行规格。",
            "detail": f"analysis_mode={strategy_dsl.get('analysis_mode')}，backtest_timeframe={strategy_dsl.get('backtest_timeframe')}，entry_context={len(strategy_dsl.get('entry_context', []))}，exit_context={len(strategy_dsl.get('exit_context', []))}。",
        },
        {
            "id": "python",
            "title": "Python 策略代码",
            "status": "pass" if generation_decision.get("allow_python_generation") else "fail",
            "summary": "Python 代码是 DSL 的派生表达，不应反向作为真值来源。",
            "detail": "当前允许生成正式 Python 策略代码。"
            if generation_decision.get("allow_python_generation")
            else "当前仅保留候选理解结果，不能直接输出可靠可执行的 Python 策略。",
        },
    ])
    return items


def _merge_strategy_questions(
    existing_questions: list[dict[str, Any]],
    ai_interpretation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not ai_interpretation:
        return existing_questions

    def classify_question_id(title: str, detail: str) -> str | None:
        text = f"{title} {detail}".lower()
        if any(marker in text for marker in ["量能", "量比", "成交量", "成交额"]):
            return "volume_threshold"
        if any(marker in text for marker in ["追高", "高开", "涨幅上限", "距离前高"]):
            return "chase_guard"
        if any(marker in text for marker in ["确认", "金叉", "站上", "回踩", "均线确认"]):
            return "confirmation_rule"
        if any(marker in text for marker in ["环境", "趋势市", "指数", "行业强弱", "市场状态"]):
            return "market_regime"
        if any(marker in text for marker in ["试仓", "仓位", "加仓", "分批建仓", "持仓比例"]):
            return "position_rule"
        return None

    merged = list(existing_questions)
    seen_ids = {item["id"] for item in merged}
    seen_titles = {item["title"] for item in merged}
    for index, item in enumerate(ai_interpretation.get("unresolved_items", []), start=1):
        title = str(item.get("title") or "").strip()
        detail = str(item.get("detail") or "").strip()
        if not title or title in seen_titles:
            continue
        question_id = classify_question_id(title, detail) or str(item.get("id") or f"ai_clarify_{index}").strip() or f"ai_clarify_{index}"
        while question_id in seen_ids:
            question_id = f"{question_id}_next"
        merged.append(
            {
                "id": question_id,
                "title": title,
                "detail": detail or "当前这部分语义仍需你进一步确认。",
                "suggested_choices": [
                    str(choice).strip()
                    for choice in item.get("suggested_choices", [])
                    if str(choice).strip()
                ],
                "depends_on": None,
                "depends_on_title": None,
                "round_type": "ai_followup",
                "source": "llm",
            }
        )
        seen_ids.add(question_id)
        seen_titles.add(title)
    return merged


def _build_strategy_ai_structured_hints(
    *,
    ai_interpretation: dict[str, Any] | None,
    market_scope_label: str,
    selected_timeframes: list[str],
) -> dict[str, Any]:
    if not ai_interpretation:
        return {
            "market_scope_hint": "",
            "timeframe_hints": [],
            "data_dependencies": [],
            "entry_intent": [],
            "exit_intent": [],
            "risk_controls": [],
            "position_intent": "",
            "execution_assumptions": [],
            "filter_intent": [],
        }
    timeframe_hints = [
        _timeframe_label(_canonicalize_timeframe(item))
        for item in ai_interpretation.get("timeframe_hints", [])
        if str(item).strip()
    ]
    return {
        "market_scope_hint": str(ai_interpretation.get("market_scope_hint") or market_scope_label).strip(),
        "timeframe_hints": timeframe_hints,
        "data_dependencies": [
            str(item).strip()
            for item in ai_interpretation.get("data_dependencies", [])
            if str(item).strip()
        ],
        "entry_intent": [
            str(item).strip()
            for item in ai_interpretation.get("entry_intent", [])
            if str(item).strip()
        ],
        "exit_intent": [
            str(item).strip()
            for item in ai_interpretation.get("exit_intent", [])
            if str(item).strip()
        ],
        "risk_controls": [
            str(item).strip()
            for item in ai_interpretation.get("risk_controls", [])
            if str(item).strip()
        ],
        "position_intent": str(ai_interpretation.get("position_intent") or "").strip(),
        "execution_assumptions": [
            str(item).strip()
            for item in ai_interpretation.get("execution_assumptions", [])
            if str(item).strip()
        ],
        "filter_intent": [
            str(item).strip()
            for item in ai_interpretation.get("filter_intent", [])
            if str(item).strip()
        ],
    }


def _build_strategy_ai_field_targets(ai_hints: dict[str, Any], unresolved_items: list[str]) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(field: str, label: str, reason: str) -> None:
        if field in seen:
            return
        seen.add(field)
        targets.append({"field": field, "label": label, "reason": reason})

    if ai_hints.get("market_scope_hint"):
        add("market_scope", "市场范围", "AI 已识别出市场范围候选，需要与你选择的市场范围核对。")
    if ai_hints.get("timeframe_hints"):
        add("timeframes", "周期设置", "AI 已识别出主周期或观察周期候选，需要与真实执行周期对齐。")
    if ai_hints.get("data_dependencies"):
        add("data_dependencies", "数据依赖", "AI 已识别出依赖的数据源或指标，需要确认平台是否支持。")
    if ai_hints.get("entry_intent"):
        add("entry_rules", "入场规则", "AI 已提炼出入场意图，建议与你的正式入场规则逐项核对。")
    if ai_hints.get("filter_intent"):
        add("filters", "过滤条件", "AI 已提炼出过滤意图，建议确认是否应写入过滤条件而不是主入场信号。")
    if ai_hints.get("exit_intent"):
        add("exit_rules", "离场规则", "AI 已提炼出离场意图，建议核对止盈、止损和退出条件。")
    if ai_hints.get("risk_controls"):
        add("risk_controls", "风控规则", "AI 已提炼出风控意图，建议确认是否需要固化为止损或仓位约束。")
    if ai_hints.get("position_intent"):
        add("position", "仓位规则", "AI 已提炼出仓位或加仓意图，建议确认仓位字段。")

    unresolved_text = " ".join(unresolved_items)
    if any(marker in unresolved_text for marker in ["量能", "量比", "成交量", "成交额"]):
        add("entry_rules", "入场规则", "当前量能条件仍未完全量化，入场规则可能还需要补阈值。")
    if any(marker in unresolved_text for marker in ["环境", "趋势市", "指数", "行业"]):
        add("filters", "过滤条件", "当前市场环境条件仍不完整，过滤条件需要继续确认。")
    if any(marker in unresolved_text for marker in ["仓位", "试仓", "加仓", "分批"]):
        add("position", "仓位规则", "当前仓位与加仓条件仍需补充。")
    return targets


def _build_strategy_ai_value_targets(
    ai_hints: dict[str, Any],
    unresolved_items: list[str],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(field: str, label: str, suggested_values: list[str], reason: str) -> None:
        cleaned = [
            item.strip()
            for item in suggested_values
            if isinstance(item, str) and item.strip()
        ]
        if field in seen or not cleaned:
            return
        seen.add(field)
        targets.append(
            {
                "field": field,
                "label": label,
                "suggested_values": cleaned[:4],
                "reason": reason,
            }
        )

    add(
        "market_scope",
        "市场范围建议值",
        [ai_hints.get("market_scope_hint", "")],
        "AI 已给出市场范围候选，建议先确认市场语义是否正确。",
    )
    add(
        "timeframes",
        "周期建议值",
        list(ai_hints.get("timeframe_hints", [])),
        "AI 已识别主周期和观察周期候选，建议确认周期组合是否符合真实执行逻辑。",
    )
    add(
        "data_dependencies",
        "数据依赖建议值",
        list(ai_hints.get("data_dependencies", [])),
        "AI 已识别依赖的数据源或指标，建议确认这些依赖是否真的是你想要的真值层。",
    )
    add(
        "entry_rules",
        "入场规则建议值",
        list(ai_hints.get("entry_intent", [])),
        "AI 已提炼入场意图，建议确认是否要固化为主入场条件。",
    )
    add(
        "filters",
        "过滤条件建议值",
        list(ai_hints.get("filter_intent", [])),
        "AI 已提炼过滤意图，建议确认这些条件是否应写进过滤层而不是主入场信号。",
    )
    add(
        "exit_rules",
        "离场规则建议值",
        list(ai_hints.get("exit_intent", [])),
        "AI 已提炼离场意图，建议确认是否作为止盈、止损或退出规则。",
    )
    add(
        "risk_controls",
        "风控规则建议值",
        list(ai_hints.get("risk_controls", [])),
        "AI 已提炼风控意图，建议确认是否作为止损、持仓上限或风险开关。",
    )
    add(
        "position",
        "仓位规则建议值",
        [ai_hints.get("position_intent", "")],
        "AI 已提炼仓位或加仓意图，建议确认是否写入仓位规则。",
    )

    unresolved_text = " ".join(unresolved_items)
    if any(marker in unresolved_text for marker in ["量能", "量比", "成交量", "成交额"]):
        add(
            "entry_rules",
            "入场阈值建议值",
            ["量比 >= 1.2", "量比 >= 1.5", "成交量高于 10 日均量 1.3 倍"],
            "当前量能条件还没完全量化，建议先确认明确阈值。",
        )
    if any(marker in unresolved_text for marker in ["追高", "高开", "涨幅上限", "前高"]):
        add(
            "filters",
            "追高限制建议值",
            ["前 15 分钟涨幅 <= 1%", "距离前高不超过 0.5%", "高开不超过 2%"],
            "当前追高限制还不够具体，建议补充可执行上限。",
        )
    if any(marker in unresolved_text for marker in ["趋势市", "环境", "指数", "行业"]):
        add(
            "filters",
            "市场环境建议值",
            ["指数站上 20 日均线时开仓", "仅在趋势市开仓", "行业强于大盘时开仓"],
            "当前市场环境条件还较模糊，建议补成可执行过滤条件。",
        )
    if any(marker in unresolved_text for marker in ["仓位", "试仓", "加仓", "分批"]):
        add(
            "position",
            "仓位与加仓建议值",
            ["首次仓位 20%", "首次仓位 30%", "突破后最多加仓 1 次"],
            "当前仓位与加仓规则还不够具体，建议补成明确比例与触发条件。",
        )
    return targets


def _build_strategy_field_mapping(
    *,
    request: StrategyGenerateRequest,
    strategy_dsl: dict[str, Any],
    generation_decision: dict[str, Any],
    strategy_python: str,
) -> list[dict[str, Any]]:
    position_text = "；".join(
        f"{key}={value}" for key, value in strategy_dsl.get("position", {}).items()
    ) or "默认单策略单持仓"
    entry_rules = strategy_dsl.get("entry", {}).get("all", [])
    exit_rules = strategy_dsl.get("exit", {}).get("any", [])
    entry_context = strategy_dsl.get("entry_context", [])
    def dsl_snippet(value: Any) -> str:
        return repr(value)
    items: list[dict[str, Any]] = [
        {
            "id": "market_scope",
            "label": "市场范围",
            "user_expression": request.market_scope,
            "structured_value": strategy_dsl.get("market_scope_label"),
            "dsl_path": "market_scope / market_scope_label",
            "python_mapping": "context.market_scope",
            "dsl_snippet": dsl_snippet(
                {
                    "market_scope": strategy_dsl.get("market_scope"),
                    "market_scope_label": strategy_dsl.get("market_scope_label"),
                }
            ),
            "python_snippet": "\n".join(
                [
                    f"market_scope: str = '{strategy_dsl.get('market_scope')}'",
                    "        'market_scope': config.market_scope,",
                ]
            ),
        },
        {
            "id": "primary_timeframe",
            "label": "主执行周期",
            "user_expression": request.timeframe,
            "structured_value": _timeframe_label(strategy_dsl.get("timeframe", "1d")),
            "dsl_path": "timeframe",
            "python_mapping": "context.primary_timeframe",
            "dsl_snippet": dsl_snippet(
                {
                    "timeframe": strategy_dsl.get("timeframe"),
                    "timeframes": strategy_dsl.get("timeframes"),
                }
            ),
            "python_snippet": "\n".join(
                [
                    f"timeframe: str = '{strategy_dsl.get('timeframe', '1d')}'",
                    f"timeframes: tuple[str, ...] = {tuple(strategy_dsl.get('timeframes') or [strategy_dsl.get('timeframe', '1d')])!r}",
                    "        'timeframe': config.timeframe,",
                    "        'timeframes': list(config.timeframes),",
                ]
            ),
        },
        {
            "id": "entry_rules",
            "label": "入场规则",
            "user_expression": request.prompt,
            "structured_value": f"{len(strategy_dsl.get('entry', {}).get('all', []))} 条主入场规则",
            "dsl_path": "entry.all",
            "python_mapping": "build_entry_signal()",
            "dsl_snippet": dsl_snippet(entry_rules[:2] if len(entry_rules) > 2 else entry_rules),
            "python_snippet": "\n".join(
                [
                    "        'entry': {",
                    "            'all': [",
                    *[f"                {repr({'indicator': rule.get('indicator'), 'params': rule.get('params', {}), 'operator': rule.get('operator'), 'value': rule.get('value')})}," for rule in entry_rules[:2]],
                    "            ]",
                    "        },",
                ]
            ),
        },
        {
            "id": "entry_context",
            "label": "观察层 / 上下文条件",
            "user_expression": request.prompt,
            "structured_value": f"{len(strategy_dsl.get('entry_context', []))} 条入场上下文",
            "dsl_path": "entry_context",
            "python_mapping": "evaluate_entry_context()",
            "dsl_snippet": dsl_snippet(entry_context[:2] if len(entry_context) > 2 else entry_context),
            "python_snippet": "\n".join(
                [
                    "        'entry_context': [",
                    *[f"            {repr(rule)}," for rule in entry_context[:2]],
                    "        ],",
                ]
            ) if entry_context else "当前无 entry_context 代码片段",
        },
        {
            "id": "exit_rules",
            "label": "离场与风控",
            "user_expression": request.prompt,
            "structured_value": f"{len(strategy_dsl.get('exit', {}).get('any', []))} 条离场规则",
            "dsl_path": "exit.any",
            "python_mapping": "build_exit_signal()",
            "dsl_snippet": dsl_snippet(exit_rules[:2] if len(exit_rules) > 2 else exit_rules),
            "python_snippet": "\n".join(
                [
                    "        'exit': {",
                    "            'any': [",
                    *[f"                {repr(rule)}," for rule in exit_rules[:2]],
                    "            ]",
                    "        },",
                ]
            ),
        },
        {
            "id": "position_rules",
            "label": "仓位规则",
            "user_expression": strategy_dsl.get("clarifications", {}).get("position_rule", "默认单策略单持仓"),
            "structured_value": position_text,
            "dsl_path": "position",
            "python_mapping": "build_position_config()",
            "dsl_snippet": dsl_snippet(strategy_dsl.get("position", {})),
            "python_snippet": "\n".join(
                [
                    f"        'position': {repr(strategy_dsl.get('position', {}))},",
                ]
            ),
        },
    ]
    if generation_decision.get("status") in {"needs_confirmation", "rejected"}:
        items.append(
            {
                "id": "generation_gate",
                "label": "正式生成门槛",
                "user_expression": request.prompt,
                "structured_value": generation_decision.get("label"),
                "dsl_path": "generation_decision",
                "python_mapping": "当前先阻断正式代码生成或保存",
                "dsl_snippet": dsl_snippet(generation_decision),
                "python_snippet": strategy_python.splitlines()[0] if strategy_python else "当前无 Python 代码片段",
            }
        )
    return items


def _build_strategy_generation_decision(
    *,
    capability_summary: dict[str, Any],
    questions_for_user: list[dict[str, Any]],
    unsupported_items: list[dict[str, Any]],
) -> dict[str, Any]:
    hard_unsupported = [item for item in unsupported_items if item.get("level", "hard") == "hard"]
    if hard_unsupported:
        return {
            "status": "rejected",
            "label": "当前应拒绝输出",
            "summary": "当前策略包含平台暂不支持的数据依赖或明显未来函数风险，不能生成可靠的可执行策略版本。",
            "allow_python_generation": False,
            "allow_save": False,
            "allow_backtest_handoff": False,
        }
    if questions_for_user:
        return {
            "status": "needs_confirmation",
            "label": "需补充后再生成正式版本",
            "summary": "系统已经理解到基础策略方向，但仍有模糊条件或缺参数。当前结果只能作为候选理解，不建议直接保存为正式策略版本。",
            "allow_python_generation": True,
            "allow_save": False,
            "allow_backtest_handoff": False,
        }
    if capability_summary.get("backtest_status") != "supported":
        return {
            "status": "semantic_only",
            "label": "当前仅可描述 / 保存，不能直接真实执行",
            "summary": capability_summary.get("backtest_warning") or "当前策略可生成并保存语义，但真实回测执行仍受平台支持边界限制。",
            "allow_python_generation": True,
            "allow_save": True,
            "allow_backtest_handoff": True,
        }
    return {
        "status": "ready",
        "label": "可直接生成并保存",
        "summary": "当前策略表达清晰，平台支持范围也明确，可以继续保存并进入回测中心验证。",
        "allow_python_generation": True,
        "allow_save": True,
        "allow_backtest_handoff": True,
    }


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
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._indicator_repository = indicator_repository
        self._glossary_repository = glossary_repository
        self._settings = settings or Settings()

    def create_project(
        self,
        *,
        user_id: str,
        workspace_id: str,
        title: str,
        version_label: str | None,
        natural_language_prompt: str,
        strategy_dsl: dict[str, Any],
        strategy_python: str | None = None,
    ) -> StrategyVersionRecord:
        record = StrategyVersionRecord(
            user_id=user_id,
            workspace_id=workspace_id,
            version_label=(version_label or "").strip(),
            title=title,
            natural_language_prompt=natural_language_prompt,
            strategy_dsl=strategy_dsl,
            strategy_python=strategy_python,
        )
        if not record.version_label:
            record.version_label = record.version_id
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
        clarification_answers = {
            key: value.strip()
            for key, value in (request.clarification_answers or {}).items()
            if isinstance(value, str) and value.strip()
        }
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
        ai_interpretation = self._parse_strategy_with_llm(
            request=request,
            clarification_answers=clarification_answers,
        )
        questions_for_user = _extract_strategy_questions(
            prompt,
            normalized,
            clarification_answers,
        )
        questions_for_user = _merge_strategy_questions(
            questions_for_user,
            ai_interpretation,
        )
        clarification_round = _build_strategy_clarification_round(
            clarification_answers=clarification_answers,
            questions_for_user=questions_for_user,
        )
        unsupported_items = _extract_strategy_unsupported_items(prompt, normalized)

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
        _apply_strategy_clarifications(
            strategy_dsl=strategy_dsl,
            clarification_answers=clarification_answers,
            entry_context=entry_context,
        )
        capability_summary = summarize_strategy_capability(
            market_scope=request.market_scope,
            primary_timeframe=primary_timeframe,
            timeframes=selected_timeframes,
            analysis_mode=strategy_dsl["analysis_mode"],
        )
        understanding = _build_strategy_understanding(
            request=request,
            market_scope_label=market_scope_label,
            selected_timeframes=selected_timeframes,
            strategy_dsl=strategy_dsl,
            entry_context=entry_context,
            exit_context=exit_context,
            matched_custom_indicators=matched_custom_indicators,
            matched_terms=matched_terms,
            questions_for_user=questions_for_user,
            unsupported_items=unsupported_items,
            capability_summary=capability_summary,
            ai_interpretation=ai_interpretation,
        )
        generation_decision = _build_strategy_generation_decision(
            capability_summary=capability_summary,
            questions_for_user=questions_for_user,
            unsupported_items=unsupported_items,
        )
        structured_spec = _build_strategy_structured_spec(
            request=request,
            market_scope_label=market_scope_label,
            strategy_dsl=strategy_dsl,
            capability_summary=capability_summary,
            questions_for_user=questions_for_user,
            unsupported_items=unsupported_items,
            ai_interpretation=ai_interpretation,
        )
        hard_validation = _build_strategy_hard_validation(
            capability_summary=capability_summary,
            generation_decision=generation_decision,
            questions_for_user=questions_for_user,
            unsupported_items=unsupported_items,
        )
        generation_pipeline = _build_strategy_generation_pipeline(
            request=request,
            strategy_dsl=strategy_dsl,
            generation_decision=generation_decision,
            structured_spec=structured_spec,
            hard_validation=hard_validation,
            ai_interpretation=ai_interpretation,
        )
        strategy_python = (
            _render_strategy_python(
                strategy_dsl,
                teaching_mode=request.teaching_mode,
                matched_custom_indicators=matched_custom_indicators,
                matched_terms=matched_terms,
            )
            if generation_decision["allow_python_generation"]
            else "# 当前策略存在不支持项或未来函数风险，需先修改后再生成 Python 策略。"
        )
        field_mapping = _build_strategy_field_mapping(
            request=request,
            strategy_dsl=strategy_dsl,
            generation_decision=generation_decision,
            strategy_python=strategy_python,
        )
        if generation_decision["allow_python_generation"]:
            summary_parts = [
                f"已根据描述生成一套面向 {market_scope_label} {request.market} 的 {side} 向 Python 策略，主周期为 {_timeframe_label(primary_timeframe)}。"
            ]
        else:
            summary_parts = [
                f"已识别到一套面向 {market_scope_label} {request.market} 的候选策略理解结果，但当前不允许直接生成正式 Python 策略。"
            ]
        if len(selected_timeframes) > 1:
            summary_parts.append(
                "已保留混合周期条件："
                + " / ".join(_timeframe_label(item) for item in selected_timeframes)
                + "。"
            )
        if request.teaching_mode:
            summary_parts.append("教学模式已开启，Python 代码中为主要语句补充了逐行注释。")
        if clarification_answers:
            summary_parts.append("已应用你补充的条件说明，并据此重新理解策略。")
            if questions_for_user:
                summary_parts.append("当前补充后仍有下一轮待确认项，建议继续澄清后再保存为正式版本。")
        if ai_interpretation:
            summary_parts.append("当前已启用 AI 候选理解补强，但最终真值层仍以平台结构化规格和硬校验为准。")
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
        if questions_for_user:
            summary_parts.append("当前仍有待补充问题，建议先确认系统理解结果，再保存为正式策略版本。")
        if unsupported_items:
            summary_parts.append("当前识别到平台暂不支持或存在未来函数风险的内容，不能直接生成可靠可执行策略。")
        return {
            "strategy_dsl": strategy_dsl,
            "strategy_python": strategy_python,
            "capability_summary": capability_summary,
            "understanding_card": understanding,
            "structured_spec": structured_spec,
            "hard_validation": hard_validation,
            "generation_pipeline": generation_pipeline,
            "field_mapping": field_mapping,
            "questions_for_user": questions_for_user,
            "clarification_round": clarification_round,
            "unsupported_items": unsupported_items,
            "generation_decision": generation_decision,
            "ai_interpretation": ai_interpretation,
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

    def _parse_strategy_with_llm(
        self,
        *,
        request: StrategyGenerateRequest,
        clarification_answers: dict[str, str],
    ) -> dict[str, Any] | None:
        runtime = _resolve_llm_runtime(
            self._settings,
            request.llm_profile,
            module="strategy",
        )
        if not runtime:
            return None
        endpoint = _llm_endpoint(runtime["base_url"])
        system_prompt = (
            "你是量化策略语义解析助手。你的职责是把中文自然语言策略理解成候选 JSON，"
            "用于后续平台结构化约束和人工确认。不要直接输出 Python 代码，不要编造平台未明确给出的规则。"
            "无法确认就留空或列为 unresolved_items。"
            "输出必须是 JSON 对象，字段固定为：summary、market_scope_hint、timeframe_hints、data_dependencies、entry_intent、exit_intent、risk_controls、filter_intent、position_intent、execution_assumptions、unresolved_items、risky_items。"
            "其中 unresolved_items 是数组，每项字段固定为：title、detail、suggested_choices。"
            "其中 risky_items 是数组字符串，用于提醒可能存在的语义风险，但不能替代平台硬校验。"
        )
        request_payload = {
            "model": runtime["model"],
            "temperature": 0.1,
            "stream": True,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "prompt": request.prompt,
                            "market_scope": request.market_scope,
                            "market": request.market,
                            "timeframe": request.timeframe,
                            "timeframes": request.timeframes,
                            "asset_type": request.asset_type,
                            "clarification_answers": clarification_answers,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        try:
            with httpx.Client(timeout=45) as client:
                with client.stream(
                    "POST",
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {runtime['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                ) as response:
                    response.raise_for_status()
                    content = self._extract_stream_content(response)
            parsed = self._extract_json_object(content)
        except Exception:
            return None
        return {
            "mode": "llm_assisted",
            "llm_profile": runtime["profile_id"],
            "llm_profile_label": runtime["label"],
            "summary": str(parsed.get("summary") or "").strip(),
            "market_scope_hint": str(parsed.get("market_scope_hint") or "").strip(),
            "timeframe_hints": [
                str(item).strip()
                for item in parsed.get("timeframe_hints", [])
                if str(item).strip()
            ],
            "data_dependencies": [
                str(item).strip()
                for item in parsed.get("data_dependencies", [])
                if str(item).strip()
            ],
            "entry_intent": [
                str(item).strip()
                for item in parsed.get("entry_intent", [])
                if str(item).strip()
            ],
            "exit_intent": [
                str(item).strip()
                for item in parsed.get("exit_intent", [])
                if str(item).strip()
            ],
            "risk_controls": [
                str(item).strip()
                for item in parsed.get("risk_controls", [])
                if str(item).strip()
            ],
            "filter_intent": [
                str(item).strip()
                for item in parsed.get("filter_intent", [])
                if str(item).strip()
            ],
            "position_intent": str(parsed.get("position_intent") or "").strip(),
            "execution_assumptions": [
                str(item).strip()
                for item in parsed.get("execution_assumptions", [])
                if str(item).strip()
            ],
            "unresolved_items": [
                {
                    "title": str(item.get("title") or "").strip(),
                    "detail": str(item.get("detail") or "").strip(),
                    "suggested_choices": [
                        str(choice).strip()
                        for choice in item.get("suggested_choices", [])
                        if str(choice).strip()
                    ],
                }
                for item in parsed.get("unresolved_items", [])
                if isinstance(item, dict) and str(item.get("title") or "").strip()
            ],
            "risky_items": [
                str(item).strip()
                for item in parsed.get("risky_items", [])
                if str(item).strip()
            ],
        }

    def _extract_stream_content(self, response: httpx.Response) -> str:
        content_parts: list[str] = []
        for raw_line in response.iter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content"):
                    content_parts.append(delta["content"])
        return "".join(content_parts).strip()

    def _extract_json_object(self, content: str) -> dict[str, Any]:
        content = content.strip()
        if not content:
            return {}
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(content[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


class AuthService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        session_repository: UserSessionRepository,
        auth_event_repository: AuthEventRepository,
    ) -> None:
        self._user_repository = user_repository
        self._session_repository = session_repository
        self._auth_event_repository = auth_event_repository

    def seed_initial_accounts(
        self,
        *,
        enable_default_accounts: bool,
        initial_admin_username: str = "",
        initial_admin_contact: str = "",
        initial_admin_password: str = "",
    ) -> None:
        defaults: list[tuple[str, str, str, str]] = []
        if enable_default_accounts:
            defaults.extend(
                [
                    ("1111", "1111@example.com", "618618", "user"),
                    ("admin", "admin@example.com", "618618", "admin"),
                ]
            )
        if initial_admin_username and initial_admin_contact and initial_admin_password:
            defaults.append(
                (
                    initial_admin_username.strip(),
                    initial_admin_contact.strip(),
                    initial_admin_password,
                    "admin",
                )
            )
        existing_users = self._user_repository.list()
        existing_usernames = {item.username for item in existing_users}
        existing_contacts = {item.contact for item in existing_users}
        for username, contact, password, role in defaults:
            if username in existing_usernames or contact in existing_contacts:
                continue
            self._user_repository.create(
                UserRecord(
                    username=username,
                    contact=contact,
                    password_hash=hash_password(password),
                    role=role,
                )
            )
            existing_usernames.add(username)
            existing_contacts.add(contact)

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

    def login(
        self,
        *,
        username: str,
        password: str,
        ip_address: str | None = None,
    ) -> tuple[UserProfile, str]:
        normalized_username = username.strip()
        record = self._user_repository.get_by_username(normalized_username)
        if record is None:
            self._record_auth_event(
                user_id=None,
                username=normalized_username,
                event_type="login",
                outcome="failed",
                reason="invalid_credentials",
                ip_address=ip_address,
            )
            raise TaskExecutionError("FORBIDDEN", "invalid username or password")
        if record.status != "active":
            self._record_auth_event(
                user_id=record.user_id,
                username=record.username,
                event_type="login",
                outcome="blocked",
                reason=record.status_reason or "account is suspended",
                ip_address=ip_address,
            )
            raise TaskExecutionError("FORBIDDEN", "account is suspended")
        if not verify_password(password, record.password_hash):
            self._record_auth_event(
                user_id=record.user_id,
                username=record.username,
                event_type="login",
                outcome="failed",
                reason="invalid_credentials",
                ip_address=ip_address,
            )
            raise TaskExecutionError("FORBIDDEN", "invalid username or password")
        session = self._session_repository.create(
            UserSessionRecord(
                user_id=record.user_id,
                session_token=issue_session_token(),
            )
        )
        self._record_auth_event(
            user_id=record.user_id,
            username=record.username,
            event_type="login",
            outcome="succeeded",
            ip_address=ip_address,
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
                if user.status != "active":
                    self._session_repository.delete_by_token(session_token)
                    return None
                return self._to_profile(user)
        return None

    def logout(self, session_token: str | None, *, ip_address: str | None = None) -> None:
        if session_token:
            session = self._session_repository.get_by_token(session_token)
            self._session_repository.delete_by_token(session_token)
            if session is not None:
                user = self._user_repository.get(session.user_id)
                self._record_auth_event(
                    user_id=session.user_id,
                    username=user.username if user else session.user_id,
                    event_type="logout",
                    outcome="succeeded",
                    ip_address=ip_address,
                )

    def _to_profile(self, record: UserRecord) -> UserProfile:
        return UserProfile(
            user_id=record.user_id,
            workspace_id=self.workspace_id_for_user_id(record.user_id),
            username=record.username,
            contact=record.contact,
            role=record.role,
            status=record.status,
            status_reason=record.status_reason,
            created_at=record.created_at,
        )

    def _record_auth_event(
        self,
        *,
        user_id: str | None,
        username: str,
        event_type: str,
        outcome: str,
        reason: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        self._auth_event_repository.create(
            AuthEventRecord(
                user_id=user_id,
                username=username or "unknown",
                event_type=event_type,
                outcome=outcome,
                reason=reason,
                ip_address=ip_address,
            )
        )

    @staticmethod
    def workspace_id_for_user_id(user_id: str) -> str:
        normalized = user_id.replace("user_", "")
        return f"ws_{normalized[:12] or 'default'}"

    @staticmethod
    def is_admin(user: UserProfile | None) -> bool:
        return bool(user and user.role == "admin")


class AppLogService:
    def __init__(self, repository: ApplicationLogRepository) -> None:
        self._repository = repository

    def record(
        self,
        *,
        message: str,
        source: str,
        category: str,
        level: str = "error",
        request_path: str | None = None,
        user: UserProfile | None = None,
        details: dict[str, Any] | None = None,
    ) -> AppLogRecord:
        normalized_message = message.strip() or "unknown application error"
        return self._repository.create(
            AppLogRecord(
                level=level,
                source=source,
                category=category,
                message=normalized_message,
                request_path=request_path,
                user_id=user.user_id if user else None,
                username=user.username if user else None,
                workspace_id=user.workspace_id if user else None,
                details=details or {},
            )
        )

    def list_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            for item in self._repository.list_recent(limit=limit)
        ]


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


class MentorService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    def list_topics(self) -> list[dict[str, Any]]:
        return [
            {
                "topic_id": "mentor_start_here",
                "title": "我完全是新手，先学什么",
                "summary": "先建立交易、风控和平台使用顺序，避免一上来就追求复杂策略。",
                "prompt": "我是交易新手，也没太多量化经验，应该先学什么，再怎么用这个平台？",
                "path": "/workspace",
            },
            {
                "topic_id": "mentor_indicator_basics",
                "title": "均线、MACD、RSI 怎么看",
                "summary": "先理解这些指标在趋势、动量和节奏判断里分别干什么。",
                "prompt": "均线、MACD、RSI 这些技术指标分别适合看什么？新手应该怎么学？",
                "path": "/indicators",
            },
            {
                "topic_id": "mentor_backtest_reading",
                "title": "回测结果怎么看",
                "summary": "把胜率、盈亏比、回撤、交易次数和成交假设一起读，不只盯收益率。",
                "prompt": "回测结果里我应该先看哪些指标？怎样判断一个策略值不值得继续研究？",
                "path": "/backtests",
            },
            {
                "topic_id": "mentor_platform_workflow",
                "title": "平台正确使用顺序",
                "summary": "先学指标和规则，再生成策略，最后做回测和复盘。",
                "prompt": "这个平台从头到尾应该怎么用？每个模块适合在什么阶段进入？",
                "path": "/strategy",
            },
        ]

    def answer(self, request: MentorAskRequest) -> dict[str, Any]:
        question = request.question.strip()
        if not question:
            raise TaskExecutionError("INVALID_ARGUMENT", "question is required")

        effective_question = self._resolve_effective_question(
            question=question,
            conversation_history=request.conversation_history,
        )
        normalized = effective_question.lower()
        topic = self._classify_topic(effective_question, normalized)
        market_scope = request.market_scope or self._infer_market_scope(effective_question)
        is_follow_up = bool(request.conversation_history)
        headline, explanation, why_it_matters, action_plan, glossary = self._build_topic_answer(
            topic=topic,
            market_scope=market_scope,
            experience_level=request.experience_level,
            is_follow_up=is_follow_up,
            original_question=question,
            effective_question=effective_question,
        )
        response = {
            "mentor_name": "金融导师",
            "mentor_role": "多市场实战导师",
            "question": question,
            "effective_question": effective_question,
            "topic": topic,
            "experience_level": request.experience_level,
            "market_scope": market_scope,
            "current_module": request.current_module,
            "is_follow_up": is_follow_up,
            "headline": headline,
            "answer": explanation,
            "why_it_matters": why_it_matters,
            "action_plan": action_plan,
            "glossary": glossary,
            "related_modules": self._related_modules_for_topic(topic),
            "risk_note": self._risk_note_for_market(market_scope),
            "answer_source": "fallback",
            "answer_mode_label": "平台导师兜底",
        }
        try:
            llm_payload = self._answer_with_llm(
                request=request,
                question=question,
                effective_question=effective_question,
                experience_level=request.experience_level,
                market_scope=market_scope,
                current_module=request.current_module,
                conversation_history=request.conversation_history,
                fallback_response=response,
            )
            if llm_payload:
                response.update(llm_payload)
                response["answer_source"] = "llm"
                response["answer_mode_label"] = "AI 实时回答"
        except Exception:
            pass
        return response

    def _answer_with_llm(
        self,
        *,
        request: MentorAskRequest,
        question: str,
        effective_question: str,
        experience_level: str,
        market_scope: str,
        current_module: str | None,
        conversation_history: list[dict[str, str]],
        fallback_response: dict[str, Any],
    ) -> dict[str, Any] | None:
        runtime = _resolve_llm_runtime(
            self._settings,
            request.llm_profile,
            module="mentor",
        )
        if not runtime:
            return None
        endpoint = _llm_endpoint(runtime["base_url"])

        prompt_payload = {
            "question": question,
            "effective_question": effective_question,
            "experience_level": experience_level,
            "market_scope": market_scope,
            "current_module": current_module,
            "conversation_history": conversation_history,
            "fallback_response": {
                "headline": fallback_response["headline"],
                "answer": fallback_response["answer"],
                "why_it_matters": fallback_response["why_it_matters"],
                "action_plan": fallback_response["action_plan"],
                "glossary": fallback_response["glossary"],
                "risk_note": fallback_response["risk_note"],
            },
        }
        system_prompt = (
            "你是一名有多年实战经验的金融导师，面向中文用户回答交易、技术指标、"
            "市场制度和本平台使用问题。回答必须真正跟随用户追问深入解释，不能重复上一轮原话。"
            "请优先解释构造逻辑、为什么有效、常见误用和实际使用顺序。"
            "输出必须是 JSON，对象字段固定为：headline、answer、why_it_matters、action_plan、glossary。"
            "其中 action_plan 是 3 条中文步骤数组；glossary 是 2-4 个对象数组，每个对象含 term 和 meaning。"
        )
        request_payload = {
            "model": runtime["model"],
            "temperature": 0.35,
            "stream": True,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
            ],
        }
        content = ""
        for attempt in range(3):
            try:
                with httpx.Client(timeout=45) as client:
                    with client.stream(
                        "POST",
                        endpoint,
                        headers={
                            "Authorization": f"Bearer {runtime['api_key']}",
                            "Content-Type": "application/json",
                        },
                        json=request_payload,
                    ) as response:
                        response.raise_for_status()
                        content = self._extract_stream_content(response)
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    sleep(1.2 * (attempt + 1))
                    continue
                raise
        parsed = self._extract_json_object(content)
        return {
            "headline": str(parsed.get("headline") or fallback_response["headline"]),
            "answer": str(parsed.get("answer") or fallback_response["answer"]),
            "why_it_matters": str(
                parsed.get("why_it_matters") or fallback_response["why_it_matters"]
            ),
            "action_plan": self._normalize_action_plan(
                parsed.get("action_plan") or fallback_response["action_plan"]
            ),
            "glossary": self._normalize_glossary(
                parsed.get("glossary") or fallback_response["glossary"]
            ),
            "llm_profile": runtime["profile_id"],
            "llm_profile_label": runtime["label"],
        }

    def _extract_stream_content(self, response: httpx.Response) -> str:
        content_parts: list[str] = []
        for raw_line in response.iter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload_text = line[5:].strip()
            if payload_text == "[DONE]":
                break
            try:
                chunk = json.loads(payload_text)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                content_parts.append(str(piece))
        if content_parts:
            return "".join(content_parts)
        return response.text

    def _extract_json_object(self, content: str) -> dict[str, Any]:
        candidate = content.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, flags=re.S)
        if fenced:
            candidate = fenced.group(1)
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = candidate[start : end + 1]
        return json.loads(candidate)

    def _normalize_action_plan(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()][:5]
        return []

    def _normalize_glossary(self, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in value[:5]:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term", "")).strip()
            meaning = str(item.get("meaning", "")).strip()
            if term and meaning:
                normalized.append({"term": term, "meaning": meaning})
        return normalized

    def _resolve_effective_question(
        self,
        *,
        question: str,
        conversation_history: list[dict[str, str]],
    ) -> str:
        follow_up_markers = ("再解释", "详细", "举个例子", "还是不懂", "不明白", "进一步", "再展开", "具体一点")
        if not conversation_history or not any(marker in question for marker in follow_up_markers):
            return question
        for item in reversed(conversation_history):
            if item.get("role") == "user" and item.get("content"):
                return f"{item['content']}。补充问题：{question}"
        return question

    def _classify_topic(self, question: str, normalized: str) -> str:
        if any(keyword in question for keyword in ("回测", "胜率", "回撤", "盈亏比", "净值")):
            return "backtest_reading"
        if any(keyword in question for keyword in ("均线", "MACD", "RSI", "KDJ", "布林", "指标")):
            return "indicator_basics"
        if any(keyword in question for keyword in ("平台", "模块", "怎么用", "工作台", "流程")):
            return "platform_workflow"
        if any(keyword in question for keyword in ("风控", "止损", "仓位", "亏损")):
            return "risk_management"
        if any(keyword in question for keyword in ("做空", "融券", "双向", "卖空")):
            return "market_constraints"
        if any(keyword in question for keyword in ("策略", "信号", "买入", "卖出", "周期")):
            return "strategy_design"
        if any(keyword in normalized for keyword in ("replay", "复盘", "交割单")):
            return "trade_review"
        return "getting_started"

    def _infer_market_scope(self, question: str) -> str:
        if any(keyword in question for keyword in ("美股", "纳斯达克", "AAPL")):
            return "us_equity"
        if any(keyword in question for keyword in ("比特币", "以太坊", "加密", "BTC", "ETH", "USDT")):
            return "crypto"
        if any(keyword in question for keyword in ("伦敦金", "黄金", "XAU")):
            return "london_gold"
        return "cn_equity"

    def _related_modules_for_topic(self, topic: str) -> list[dict[str, str]]:
        mapping = {
            "getting_started": [
                {"label": "用户工作台", "path": "/workspace", "reason": "先看清研究入口和当前状态"},
                {"label": "金融导师", "path": "/mentor", "reason": "边问边学，不懂的概念先在这里消化"},
            ],
            "indicator_basics": [
                {"label": "指标设置", "path": "/indicators", "reason": "先看传统指标含义，再设计自定义指标"},
                {"label": "规则模块", "path": "/rules", "reason": "把你常用术语补进术语库"},
            ],
            "strategy_design": [
                {"label": "策略工坊", "path": "/strategy", "reason": "把交易想法转成可保存、可回测的策略版本"},
                {"label": "回测中心", "path": "/backtests", "reason": "验证规则是否在历史数据上稳定"},
            ],
            "backtest_reading": [
                {"label": "回测中心", "path": "/backtests", "reason": "先看净值、回撤、交易次数和成交假设"},
                {"label": "交易复盘", "path": "/replay", "reason": "把真实交易和回测表现对照起来"},
            ],
            "risk_management": [
                {"label": "回测中心", "path": "/backtests", "reason": "把止损、回撤和仓位规则写进执行配置"},
                {"label": "交易复盘", "path": "/replay", "reason": "从真实亏损单里找风控漏洞"},
            ],
            "trade_review": [
                {"label": "交易复盘", "path": "/replay", "reason": "导入成交记录，先看方向、盈亏和持仓时长"},
                {"label": "策略工坊", "path": "/strategy", "reason": "把复盘结论回灌到下一版策略"},
            ],
            "platform_workflow": [
                {"label": "指标设置", "path": "/indicators", "reason": "先理解指标和市场规则"},
                {"label": "策略工坊", "path": "/strategy", "reason": "把交易想法整理成可执行策略"},
                {"label": "回测中心", "path": "/backtests", "reason": "用明确成交和风控假设验证"},
            ],
            "market_constraints": [
                {"label": "规则模块", "path": "/rules", "reason": "先理解不同市场的制度边界"},
                {"label": "回测中心", "path": "/backtests", "reason": "把市场约束写进回测配置"},
            ],
        }
        return mapping.get(topic, mapping["getting_started"])

    def _build_topic_answer(
        self,
        *,
        topic: str,
        market_scope: str,
        experience_level: str,
        is_follow_up: bool,
        original_question: str,
        effective_question: str,
    ) -> tuple[str, str, str, list[str], list[dict[str, str]]]:
        if topic == "indicator_basics":
            detailed_follow_up = any(
                marker in (original_question + effective_question)
                for marker in ("构造逻辑", "为什么有效", "更详细", "精准", "具体含义", "怎么用")
            )
            if detailed_follow_up:
                return (
                    "先把均线、MACD、RSI 分成三种不同职责，再理解它们为什么会有效。",
                    "均线的本质，是把一段时间的平均成交成本平滑出来，所以它更适合看趋势方向和市场共识成本。价格持续站在均线上方，说明最近一段时间买入的人整体处于优势区，这就是它能帮助判断趋势的原因。"
                    " MACD 的本质，是比较短周期和长周期指数平均价格的差值变化，所以它看的是趋势有没有加速、减速，以及动量是否跟趋势共振。它有效，不是因为金叉本身神奇，而是因为短期价格推动力开始持续强于长期平均。"
                    " RSI 的本质，是统计一段时间内上涨力度和下跌力度的相对强弱，所以它更适合看节奏、超买超卖和短期情绪。它有效的前提不是单独使用，而是放到趋势环境里去看，例如上升趋势里 RSI 回落后重新转强，比单纯看到 RSI 大于 70 更有意义。",
                    "如果把这三类指标混成同一种用途，你就会在趋势里拿 RSI 抓顶，在震荡里拿均线追突破，最后觉得每个指标都不稳定。",
                    [
                        "先在指标设置里分别看均线、MACD、RSI 的公式和默认参数，理解它们到底在度量什么。",
                        "用一张历史行情图，只观察一个指标在趋势行情和震荡行情中的表现差异。",
                        "再回到策略工坊，把“趋势判断”和“节奏确认”拆成两层条件，不要让一个指标同时负责所有任务。",
                    ],
                    [
                        {"term": "均线", "meaning": "一段时间内市场平均成交成本的平滑表达，更适合看趋势方向。"},
                        {"term": "MACD", "meaning": "快慢均线差值及其变化，更适合看趋势与动量是否共振。"},
                        {"term": "RSI", "meaning": "涨跌力度的相对强弱，更适合看短期节奏和超买超卖。"},
                    ],
                )
            intro = "我顺着你刚才的问题，再把指标怎么用讲得更白一点。 " if is_follow_up else ""
            return (
                "先分清趋势指标、动量指标和波动指标，再决定它们各自负责什么。",
                intro + "均线更适合看趋势方向，MACD 更适合看趋势和动量是否共振，RSI 更适合观察短期强弱和节奏。新手不要把很多指标叠在一起，而是先选一类趋势指标、一类节奏指标，再看它们是否在同一段行情里给出一致信号。",
                "指标真正的作用是帮助你过滤环境、确认节奏，而不是替你直接按下买卖按钮。",
                [
                    "先在指标设置里逐个看均线、MACD、RSI 的说明和代码。",
                    "只保留一套最小组合，比如均线 + RSI，不要一开始堆太多指标。",
                    "再去策略工坊，把理解后的条件写成自然语言，生成第一版策略。",
                ],
                [
                    {"term": "趋势指标", "meaning": "帮助你判断方向是否在持续向上或向下。"},
                    {"term": "动量指标", "meaning": "帮助你判断当前涨跌是否有延续性。"},
                ],
            )
        if topic == "backtest_reading":
            intro = "针对你这次追问，我把回测结果应该先看什么讲得再具体一点。 " if is_follow_up else ""
            return (
                "先看最大回撤和交易次数，再看收益率；先确认成交假设，再评价策略好坏。",
                intro + "很多人只盯累计收益，但真实研究里，更重要的是这个收益是不是建立在合理的回撤、可接受的交易频率和清晰的成交假设上。你应该先看净值曲线是否平稳、回撤是否超过承受范围、交易次数是否太少，以及成交方式、滑点、手续费是否合理。",
                "如果成交方式、滑点或市场约束写得含糊，哪怕收益看起来很好，也不一定代表真实可执行结果。",
                [
                    "先看净值曲线和最大回撤，判断策略波动是否可接受。",
                    "再看交易次数和平均单笔收益，避免样本太少得出错误结论。",
                    "最后检查回测配置摘要，确认复权、成交方式、手续费和市场约束都合理。",
                ],
                [
                    {"term": "最大回撤", "meaning": "从历史高点回落到低点的最大幅度。"},
                    {"term": "盈亏比", "meaning": "平均赚钱幅度和平均亏钱幅度的对比。"},
                ],
            )
        if topic == "platform_workflow":
            intro = "你如果还是觉得平台顺序不清楚，就先记住这一条主线。 " if is_follow_up else ""
            return (
                "正确顺序不是先回测，而是先讲清楚规则，再去验证规则。",
                intro + "成熟的研究流程通常是：先理解指标和市场规则，再把经验写成策略描述，接着在策略工坊生成结构化策略，之后在回测中心用明确配置验证，最后把真实交易或模拟结果带到复盘模块做修正。",
                "如果顺序反过来，你很容易得到一堆收益数字，却说不清这些数字是怎么来的，也无法稳定复现。",
                [
                    "第一次使用时，先逛指标设置和规则模块，把常见术语和市场制度看明白。",
                    "第二步进入策略工坊，写出一套能用中文讲清楚的入场、出场和风控逻辑。",
                    "第三步去回测中心验证，再把问题带回策略工坊和交易复盘继续改。",
                ],
                [
                    {"term": "策略版本", "meaning": "每一轮研究保存下来的独立版本，便于回测和对比。"},
                    {"term": "数据快照", "meaning": "某次回测绑定的数据范围和来源摘要，用来保证结果可追踪。"},
                ],
            )
        if topic == "risk_management":
            intro = "你这次是在追问风控细节，我把重点直接收敛到最容易落地的几条。 " if is_follow_up else ""
            return (
                "先管亏损，再讨论放大收益；风控不是附属项，而是策略本体的一部分。",
                intro + "新手最容易犯的错误，是先看买点，再补止损和仓位。成熟做法正好相反：先定义单笔最多能亏多少、总回撤能接受多少、是否允许加仓，再决定信号值不值得做。",
                "没有明确的仓位和止损约束，哪怕信号本身不错，结果也可能因为单笔失控而完全变形。",
                [
                    "在回测中心先设置最大回撤保护、最大持有 Bar 数和仓位模式。",
                    "把止损、止盈和同日是否允许卖出的规则写清楚，不要留给自己临盘发挥。",
                    "复盘时优先看亏损最大的几笔，判断是信号问题还是仓位问题。",
                ],
                [
                    {"term": "仓位", "meaning": "每次交易投入多少资金或多少数量。"},
                    {"term": "止损", "meaning": "当亏损达到预设阈值时主动退出，控制单笔风险。"},
                ],
            )
        if topic == "trade_review":
            intro = "如果你是在追问复盘到底该怎么做，我把它再压缩成更实际的话。 " if is_follow_up else ""
            return (
                "复盘不是回忆过程，而是把真实成交转成下一版规则。",
                intro + "你真正要看的不是哪一笔赚了，而是哪些交易类型在重复赚钱，哪些错误在重复发生。方向、持仓时长、盈亏分布、入场时间和退出方式，都是下一版策略能直接吸收的线索。",
                "如果复盘只停留在情绪总结，你会觉得自己学到了很多，但下一次下单时还是重复旧错误。",
                [
                    "先把真实成交按方向、持仓天数和盈亏大小分组。",
                    "找出亏损最集中的场景，比如追高、逆势或止损过慢。",
                    "把结论写回策略工坊或规则模块，形成下一版明确规则。",
                ],
                [
                    {"term": "复盘", "meaning": "把真实交易拆成可解释、可改进的模式。"},
                    {"term": "样本", "meaning": "用于分析的一组交易记录，样本太少时结论容易失真。"},
                ],
            )
        if topic == "market_constraints":
            market_name = MARKET_SCOPE_LABELS.get(market_scope, "当前市场")
            intro = "我结合你刚才的追问，把市场制度边界说得更直接一点。 " if is_follow_up else ""
            explanation = intro + f"{market_name} 的制度边界会直接决定哪些建议成立。"
            if market_scope == "cn_equity":
                explanation += " 对于 A股现货股票，平台默认按“买入后卖出”的单向交易研究，不会把做空当成常规建议；如果你研究的是融资融券、股指期货或期权，需要单独说明。"
            else:
                explanation += " 这个市场允许的成交节奏和双向交易能力，与 A股现货不一样，回测和复盘都要按对应制度解释。"
            return (
                "先确认市场制度边界，再讨论做多还是做空。",
                explanation,
                "市场制度不是备注项，而是策略是否可执行的硬边界。",
                [
                    "先在规则模块确认市场默认规则和术语。",
                    "回测时把交易日历、时区、结算规则和市场约束明确写进配置。",
                    "如果涉及做空、盘前盘后或杠杆，请在策略描述里显式说明。",
                ],
                [
                    {"term": "T+1", "meaning": "当日买入后通常需要下一个交易日才能卖出。"},
                    {"term": "双向交易", "meaning": "既可以做多，也可以在允许时做空。"},
                ],
            )
        if topic == "strategy_design":
            intro = "如果你想让策略描述更容易落地，我建议按这套顺序继续拆。 " if is_follow_up else ""
            return (
                "先把入场、出场、风控三件事讲完整，再生成策略版本。",
                intro + "好的策略描述不是一句“金叉买入”，而是要讲清楚：什么环境下看这个信号、满足什么条件才进场、什么情况下退出、一次最多承担多大风险。平台最适合帮你把这种口语经验整理成结构化策略。",
                "如果你的描述只讲买点，不讲卖点和风控，后面回测出来的结果大多不可用。",
                [
                    "先用一句话写清楚你想做的市场、周期和主要场景。",
                    "再补充入场条件、退出条件、仓位和风险控制。",
                    "最后在策略工坊生成策略版本，并保存成便于比较的版本标签。",
                ],
                [
                    {"term": "入场条件", "meaning": "满足哪些信号和环境后才允许开仓。"},
                    {"term": "退出条件", "meaning": "止盈、止损或趋势转弱时如何离场。"},
                ],
            )
        intro = "我沿着你刚才的问题继续补充。 " if is_follow_up else ""
        first_step = "先去指标设置看一两个最常见指标。"
        if experience_level not in {"beginner", "newbie"}:
            first_step = "先用最小可验证假设跑一轮实验。"
        return (
            "先建立最小研究闭环，再逐步增加复杂度。",
            intro + "对刚接触交易和量化的人来说，最重要的不是一次学完所有概念，而是先跑通“理解一个概念、写出一条规则、做一次验证、复盘一次结果”的闭环。平台就是按这个顺序设计的。",
            "只要你能稳定跑通这个闭环，后面无论加指标、换市场还是接更复杂的数据，都会更稳。",
            [
                first_step,
                "再去策略工坊写一条能用自然语言讲清楚的简单规则。",
                "接着用回测中心验证，再到交易复盘总结哪里需要修正。",
            ],
            [
                {"term": "研究闭环", "meaning": "从想法、验证到修正的完整循环。"},
                {"term": "最小可验证假设", "meaning": "先用最简单、最明确的一版规则验证方向。"},
            ],
        )

    def _risk_note_for_market(self, market_scope: str) -> str:
        if market_scope == "cn_equity":
            return "A股现货研究默认按买入后卖出的单向交易理解；如果涉及融券、期权或期货，需要单独声明交易制度。"
        if market_scope == "crypto":
            return "加密货币默认按 7x24 连续交易理解，频率更高时更要注意手续费、滑点和样本噪声。"
        if market_scope == "us_equity":
            return "美股默认允许同日买卖，但盘前盘后、时区和财报窗口会显著改变成交环境。"
        return "不同市场的时区、交易日历和波动特征差异很大，先确认制度边界再扩展策略。"


class TradeUploadService:
    def __init__(
        self,
        repository: TradeUploadRepository,
        *,
        market_data_service: MarketDataService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._market_data_service = market_data_service
        self._ocr_engine: Any | None = None
        self._settings = settings or Settings()

    def create_upload(
        self,
        source_file_name: str,
        raw_text: str,
        *,
        upload_kind: str = "csv",
        metadata: dict[str, Any] | None = None,
        user_id: str,
        workspace_id: str,
    ) -> TradeUploadRecord:
        detected_columns = self._detect_columns(raw_text) if upload_kind == "csv" else []
        record = TradeUploadRecord(
            user_id=user_id,
            workspace_id=workspace_id,
            source_file_name=source_file_name,
            raw_text=raw_text,
            upload_kind=upload_kind,
            detected_columns=detected_columns,
            metadata=metadata or {},
        )
        return self._repository.create(record)

    def create_manual_upload(
        self,
        *,
        source_file_name: str,
        upload_kind: str,
        records: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
        user_id: str,
        workspace_id: str,
    ) -> TradeUploadRecord:
        parsed_records = [
            TradeRecordItem(
                trade_id=f"trade_{index + 1:03d}",
                symbol=item["symbol"],
                side="short"
                if str(item.get("side", "long")).lower() in {"short", "sell", "做空"}
                else "long",
                entry_time=item["entry_time"],
                exit_time=item.get("exit_time"),
                pnl=float(item.get("pnl", 0.0)),
                entry_price=_safe_number(item.get("entry_price")),
                exit_price=_safe_number(item.get("exit_price")),
                notes=(str(item.get("notes", "")).strip() or None),
                source_kind="screenshot_form" if upload_kind == "screenshot" else "manual_entry",
                input_confidence="needs_review" if upload_kind == "screenshot" else "user_provided",
                provenance_tags=[upload_kind],
                derived_fields=[],
                needs_confirmation=upload_kind == "screenshot",
                conflict_flags=[],
            )
            for index, item in enumerate(records)
        ]
        record = TradeUploadRecord(
            user_id=user_id,
            workspace_id=workspace_id,
            source_file_name=source_file_name,
            raw_text=json.dumps(records, ensure_ascii=False),
            upload_kind=upload_kind,
            status="parsed",
            detected_columns=["symbol", "side", "entry_time", "exit_time", "pnl"],
            column_mapping={
                "symbol": "symbol",
                "side": "side",
                "entry_time": "entry_time",
                "exit_time": "exit_time",
                "pnl": "pnl",
            },
            metadata=metadata or {},
            records=parsed_records,
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
                    entry_price=_safe_number(
                        row.get(column_mapping.get("entry_price", ""), "")
                    ),
                    exit_price=_safe_number(
                        row.get(column_mapping.get("exit_price", ""), "")
                    ),
                    notes=(row.get(column_mapping.get("notes", ""), "") or None),
                    source_kind="csv_import",
                    input_confidence="user_provided",
                    provenance_tags=["csv_import"],
                    derived_fields=[],
                    needs_confirmation=False,
                    conflict_flags=[],
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

    def parse_manual_trade_text(
        self,
        *,
        text: str,
        market: str,
        adjustment_mode: str,
        llm_profile: str = "module_default",
        user_id: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        normalized_text = text.strip()
        if not normalized_text:
            raise TaskExecutionError("INVALID_ARGUMENT", "请先输入需要识别的长文字内容。")

        llm_parse = self._parse_trade_text_with_llm(
            text=normalized_text,
            market=market,
            llm_profile=llm_profile,
        )

        grouped_candidates = self._extract_grouped_trade_candidates(
            normalized_text,
            market=market,
        )
        if len(grouped_candidates) > 1:
            return self._build_grouped_text_trade_records(
                grouped_candidates=grouped_candidates,
                text=normalized_text,
                market=market,
                adjustment_mode=adjustment_mode,
                llm_parse=llm_parse,
            )

        trade_date = self._extract_labeled_trade_date(normalized_text, "买入日期") or self._extract_trade_date(normalized_text)
        if trade_date is None:
            raise TaskExecutionError("INVALID_ARGUMENT", "未识别到交易日期，请至少包含 YYYY-MM-DD。")

        symbols = self._extract_symbols_by_market(normalized_text, market)
        if not symbols:
            raise TaskExecutionError("INVALID_ARGUMENT", "未识别到股票代码，请至少包含一个可识别的标的代码。")

        ai_single = self._match_llm_group(
            llm_parse,
            trade_date=trade_date.isoformat(),
        )
        entry_rule = (
            self._extract_entry_rule_or_none(normalized_text)
            or self._extract_rule_from_llm_text(ai_single.get("entry_rule_text") if ai_single else None, kind="entry")
            or self._extract_rule_from_llm_text(llm_parse.get("global_entry_rule") if llm_parse else None, kind="entry")
            or {"label": "当日开盘价买入", "price_field": "open", "offset": 0}
        )
        exit_rule = (
            self._extract_exit_rule(normalized_text)
            or self._extract_rule_from_llm_text(ai_single.get("exit_rule_text") if ai_single else None, kind="exit")
            or self._extract_rule_from_llm_text(llm_parse.get("global_exit_rule") if llm_parse else None, kind="exit")
        )
        explicit_exit_date = (
            self._extract_labeled_trade_date(normalized_text, "卖出日期")
            or self._extract_iso_date(ai_single.get("explicit_exit_date") if ai_single else None)
        )

        records = [
            self._build_text_trade_record(
                trade_date=trade_date,
                symbol=symbol,
                market=market,
                adjustment_mode=adjustment_mode,
                entry_rule=entry_rule,
                exit_rule=exit_rule,
                explicit_exit_date=explicit_exit_date,
                index=index,
                llm_used=bool(llm_parse),
            )
            for index, symbol in enumerate(symbols, start=1)
        ]

        return {
            "market": market,
            "trade_date": trade_date.isoformat(),
            "entry_rule": entry_rule["label"],
            "exit_rule": exit_rule["label"] if exit_rule else "未提供卖出规则",
            "record_count": len(records),
            "parse_mode": "hybrid_llm" if llm_parse else "deterministic",
            "ai_review": self._build_ai_review_summary(llm_parse),
            "input_truth_summary": _build_trade_input_truth_summary(
                records,
                source_context="text_parse",
            ),
            "records": [item.model_dump(mode="json") for item in records],
            "summary": (
                f"已识别 {len(records)} 笔交易，日期为 {trade_date.isoformat()}，"
                f"买入规则按“{entry_rule['label']}”理解。"
            ),
        }

    def _build_grouped_text_trade_records(
        self,
        *,
        grouped_candidates: list[dict[str, Any]],
        text: str,
        market: str,
        adjustment_mode: str,
        llm_parse: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        global_entry_rule = (
            self._extract_entry_rule_or_none(text)
            or self._extract_rule_from_llm_text(llm_parse.get("global_entry_rule") if llm_parse else None, kind="entry")
        )
        global_exit_rule = (
            self._extract_exit_rule(text)
            or self._extract_rule_from_llm_text(llm_parse.get("global_exit_rule") if llm_parse else None, kind="exit")
        )
        records: list[TradeRecordItem] = []
        group_summaries: list[dict[str, Any]] = []
        for group in grouped_candidates:
            trade_date = group["trade_date"]
            symbols = group["symbols"]
            block_text = group["block_text"]
            llm_group = self._match_llm_group(llm_parse, trade_date=trade_date.isoformat())
            block_entry_rule = (
                self._extract_entry_rule_or_none(block_text)
                or self._extract_rule_from_llm_text(llm_group.get("entry_rule_text") if llm_group else None, kind="entry")
                or global_entry_rule
                or {"label": "当日开盘价买入", "price_field": "open", "offset": 0}
            )
            block_exit_rule = (
                self._extract_exit_rule(block_text)
                or self._extract_rule_from_llm_text(llm_group.get("exit_rule_text") if llm_group else None, kind="exit")
                or global_exit_rule
            )
            explicit_exit_date = (
                self._extract_labeled_trade_date(block_text, "卖出日期")
                or self._extract_iso_date(llm_group.get("explicit_exit_date") if llm_group else None)
            )
            group_records: list[TradeRecordItem] = []
            for index, symbol in enumerate(symbols, start=1):
                record = self._build_text_trade_record(
                    trade_date=trade_date,
                    symbol=symbol,
                    market=market,
                    adjustment_mode=adjustment_mode,
                    entry_rule=block_entry_rule,
                    exit_rule=block_exit_rule,
                    explicit_exit_date=explicit_exit_date,
                    index=len(records) + 1,
                    llm_used=bool(llm_parse),
                )
                records.append(record)
                group_records.append(record)
            group_summaries.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "record_count": len(group_records),
                    "symbols": symbols,
                    "entry_rule": block_entry_rule["label"],
                    "exit_rule": block_exit_rule["label"] if block_exit_rule else "未提供卖出规则",
                }
            )

        if not records:
            raise TaskExecutionError("INVALID_ARGUMENT", "未识别到可生成成交记录的日期和标的代码。")

        trade_dates = [item["trade_date"].isoformat() for item in grouped_candidates]
        return {
            "market": market,
            "trade_date": trade_dates[0],
            "trade_dates": trade_dates,
            "group_count": len(grouped_candidates),
            "entry_rule": global_entry_rule["label"] if global_entry_rule else "按各日期块独立识别",
            "exit_rule": global_exit_rule["label"] if global_exit_rule else "按各日期块独立识别",
            "record_count": len(records),
            "parse_mode": "hybrid_llm" if llm_parse else "deterministic",
            "ai_review": self._build_ai_review_summary(llm_parse),
            "group_summaries": group_summaries,
            "input_truth_summary": _build_trade_input_truth_summary(
                records,
                source_context="text_parse",
            ),
            "records": [item.model_dump(mode="json") for item in records],
            "summary": (
                f"已识别 {len(grouped_candidates)} 个交易日期、{len(records)} 笔交易，"
                "识别结果已按日期块分别整理。"
            ),
        }

    def recognize_trade_screenshot(
        self,
        *,
        content: bytes,
        market: str,
    ) -> dict[str, Any]:
        lines = self._ocr_image_lines(content)
        combined_text = "\n".join(lines).strip()
        if not combined_text:
            raise TaskExecutionError("INVALID_ARGUMENT", "当前截图里未识别到可用文字，请换一张更清晰的成交截图或继续手工补录。")

        detected_date = self._extract_trade_date(combined_text)
        symbol_candidates = self._extract_symbols_by_market(combined_text, market)
        side = self._extract_trade_side(combined_text, market)
        pnl = self._extract_trade_pnl(combined_text)
        entry_time = None
        if detected_date is not None:
            entry_time = self._default_entry_time_for_market(detected_date, market)

        notes_parts = ["来源：截图 OCR 识别"]
        if symbol_candidates:
            notes_parts.append(f"识别到代码 {', '.join(symbol_candidates[:3])}")
        if detected_date is not None:
            notes_parts.append(f"识别到日期 {detected_date.isoformat()}")

        return {
            "raw_text": combined_text,
            "symbol_candidates": symbol_candidates,
            "suggested_symbol": symbol_candidates[0] if symbol_candidates else "",
            "suggested_side": side,
            "suggested_market": market,
            "detected_trade_date": detected_date.isoformat() if detected_date else None,
            "suggested_entry_time": entry_time.isoformat() if entry_time else None,
            "suggested_exit_time": None,
            "suggested_pnl": pnl,
            "suggested_notes": "；".join(notes_parts),
        }

    def _build_text_trade_record(
        self,
        *,
        trade_date: date,
        symbol: str,
        market: str,
        adjustment_mode: str,
        entry_rule: dict[str, Any],
        exit_rule: dict[str, Any] | None,
        explicit_exit_date: date | None,
        index: int,
        llm_used: bool = False,
    ) -> TradeRecordItem:
        bars, data_source = self._load_trade_bars(
            symbol=symbol,
            trade_date=trade_date,
            adjustment_mode=adjustment_mode,
        )
        entry_bar = self._find_bar_by_offset(
            bars,
            trade_date.isoformat(),
            entry_rule.get("offset", 0),
        ) or self._find_first_bar_on_or_after(bars, trade_date)
        if entry_bar is None:
            raise TaskExecutionError("NOT_FOUND", f"{symbol} 在 {trade_date.isoformat()} 附近没有可用行情。")

        entry_price = self._resolve_entry_price(entry_bar, entry_rule)
        entry_time = self._resolve_entry_time(entry_bar.trade_date, entry_rule)
        exit_price = None
        exit_time = None
        pnl = 0.0
        source_label = data_source.get("provider") or "未知数据源"
        notes = f"来源：长文字智能识别；补价来源：{source_label}；买入规则：{entry_rule['label']}"
        derived_fields = ["entry_price"]
        provenance_tags = [
            "text_parse",
            "daily_bar_fill",
            "llm_hybrid" if llm_used else "rule_parser",
        ]
        conflict_flags: list[str] = []

        if exit_rule is not None:
            exit_match = self._resolve_exit_from_rule(
                bars=bars,
                entry_bar=entry_bar,
                entry_price=entry_price,
                entry_rule=entry_rule,
                exit_rule=exit_rule,
            )
            exit_price = exit_match.get("exit_price")
            exit_time = exit_match.get("exit_time")
            pnl = exit_match.get("pnl", 0.0)
            derived_fields.extend(["exit_price", "pnl"])
            notes = f"{notes}；卖出规则：{exit_rule['label']}；{exit_match['note']}"
        elif explicit_exit_date is not None:
            target_bar = self._find_first_bar_on_or_after(bars, explicit_exit_date) or entry_bar
            exit_price = float(target_bar.close)
            exit_time = datetime.fromisoformat(f"{target_bar.trade_date}T15:00:00+00:00")
            pnl = exit_price - entry_price
            derived_fields.extend(["exit_price", "pnl"])
            notes = f"{notes}；按卖出日期 {explicit_exit_date.isoformat()} 的收盘价补全"
        else:
            conflict_flags.append("missing_exit_rule")

        return TradeRecordItem(
            trade_id=f"text_trade_{index:03d}",
            symbol=symbol,
            side="long" if market == "cn_equity" else "long",
            entry_time=entry_time,
            exit_time=exit_time,
            pnl=round(pnl, 4),
            entry_price=round(entry_price, 4),
            exit_price=round(exit_price, 4) if exit_price is not None else None,
            notes=notes,
            source_kind="text_parse_hybrid" if llm_used else "text_parse_rule",
            input_confidence="needs_review",
            provenance_tags=provenance_tags,
            derived_fields=derived_fields,
            needs_confirmation=True,
            conflict_flags=conflict_flags,
        )

    def _load_trade_bars(
        self,
        *,
        symbol: str,
        trade_date: date,
        adjustment_mode: str,
    ) -> tuple[list[Any], dict[str, Any]]:
        if self._market_data_service is None:
            raise TaskExecutionError("INTERNAL_ERROR", "market data service unavailable")
        start_date = trade_date - timedelta(days=40)
        end_date = trade_date + timedelta(days=30)
        return self._market_data_service.load_daily_bars(
            ts_code=symbol,
            start_date=start_date,
            end_date=end_date,
            adjustment_mode=adjustment_mode,
        )

    def _find_first_bar_on_or_after(self, bars: list[Any], trade_date: date) -> Any | None:
        for bar in bars:
            if date.fromisoformat(bar.trade_date) >= trade_date:
                return bar
        return None

    def _resolve_entry_price(self, bar: Any, entry_rule: dict[str, Any]) -> float:
        explicit_price = entry_rule.get("explicit_price")
        if explicit_price is not None:
            return float(explicit_price)
        price_field = entry_rule["price_field"]
        return float(getattr(bar, price_field))

    def _resolve_entry_time(self, trade_date_text: str, entry_rule: dict[str, Any]) -> datetime:
        time_text = "09:30:00" if entry_rule["price_field"] == "open" else "15:00:00"
        return datetime.fromisoformat(f"{trade_date_text}T{time_text}+00:00")

    def _resolve_exit_from_rule(
        self,
        *,
        bars: list[Any],
        entry_bar: Any,
        entry_price: float,
        entry_rule: dict[str, Any],
        exit_rule: dict[str, Any],
    ) -> dict[str, Any]:
        if exit_rule["type"] == "atr_low_break":
            atr_value = self._estimate_atr14(bars, entry_bar.trade_date)
            threshold = round(entry_price - exit_rule["multiplier"] * atr_value, 4)
            future_bars = [bar for bar in bars if date.fromisoformat(bar.trade_date) >= date.fromisoformat(entry_bar.trade_date)]
            for bar in future_bars:
                if float(bar.low) <= threshold:
                    exit_time = datetime.fromisoformat(f"{bar.trade_date}T15:00:00+00:00")
                    return {
                        "exit_price": threshold,
                        "exit_time": exit_time,
                        "pnl": threshold - entry_price,
                        "note": f"按 ATR 阈值 {threshold:.4f} 触发卖出",
                    }
            fallback_bar = future_bars[min(9, len(future_bars) - 1)] if future_bars else entry_bar
            fallback_price = float(fallback_bar.close)
            return {
                "exit_price": fallback_price,
                "exit_time": datetime.fromisoformat(f"{fallback_bar.trade_date}T15:00:00+00:00"),
                "pnl": fallback_price - entry_price,
                "note": "数据范围内未触发 ATR 阈值，已按后续可用收盘价补全",
            }

        if exit_rule["type"] == "explicit_price":
            exit_price = float(exit_rule["value"])
            target_bar = self._find_bar_by_offset(
                bars,
                entry_bar.trade_date,
                exit_rule.get("offset", 0),
            ) or entry_bar
            return {
                "exit_price": exit_price,
                "exit_time": datetime.fromisoformat(f"{target_bar.trade_date}T15:00:00+00:00"),
                "pnl": exit_price - entry_price,
                "note": "按文字中给出的卖出价格补全",
            }

        if exit_rule["type"] == "next_close":
            next_bar = self._find_bar_by_offset(bars, entry_bar.trade_date, 1)
            target_bar = next_bar or entry_bar
            exit_price = float(target_bar.close)
            return {
                "exit_price": exit_price,
                "exit_time": datetime.fromisoformat(f"{target_bar.trade_date}T15:00:00+00:00"),
                "pnl": exit_price - entry_price,
                "note": "按次日收盘价卖出补全",
            }

        if exit_rule["type"] == "offset_close":
            target_bar = self._find_bar_by_offset(
                bars,
                entry_bar.trade_date,
                exit_rule.get("offset", 0),
            ) or entry_bar
            exit_price = float(target_bar.close)
            return {
                "exit_price": exit_price,
                "exit_time": datetime.fromisoformat(f"{target_bar.trade_date}T15:00:00+00:00"),
                "pnl": exit_price - entry_price,
                "note": "按指定交易日收盘价卖出补全",
            }

        if exit_rule["type"] == "take_profit_pct":
            threshold = round(entry_price * (1 + exit_rule["pct"]), 4)
            future_bars = [bar for bar in bars if date.fromisoformat(bar.trade_date) >= date.fromisoformat(entry_bar.trade_date)]
            for bar in future_bars:
                if float(bar.high) >= threshold:
                    return {
                        "exit_price": threshold,
                        "exit_time": datetime.fromisoformat(f"{bar.trade_date}T15:00:00+00:00"),
                        "pnl": threshold - entry_price,
                        "note": f"按止盈阈值 {threshold:.4f} 触发卖出",
                    }
            fallback_bar = future_bars[min(4, len(future_bars) - 1)] if future_bars else entry_bar
            fallback_price = float(fallback_bar.close)
            return {
                "exit_price": fallback_price,
                "exit_time": datetime.fromisoformat(f"{fallback_bar.trade_date}T15:00:00+00:00"),
                "pnl": fallback_price - entry_price,
                "note": f"数据范围内未触发止盈阈值 {threshold:.4f}，已按后续可用收盘价补全",
            }

        if exit_rule["type"] == "stop_loss_pct":
            threshold = round(entry_price * (1 - exit_rule["pct"]), 4)
            future_bars = [bar for bar in bars if date.fromisoformat(bar.trade_date) >= date.fromisoformat(entry_bar.trade_date)]
            for bar in future_bars:
                if float(bar.low) <= threshold:
                    return {
                        "exit_price": threshold,
                        "exit_time": datetime.fromisoformat(f"{bar.trade_date}T15:00:00+00:00"),
                        "pnl": threshold - entry_price,
                        "note": f"按止损阈值 {threshold:.4f} 触发卖出",
                    }
            fallback_bar = future_bars[min(4, len(future_bars) - 1)] if future_bars else entry_bar
            fallback_price = float(fallback_bar.close)
            return {
                "exit_price": fallback_price,
                "exit_time": datetime.fromisoformat(f"{fallback_bar.trade_date}T15:00:00+00:00"),
                "pnl": fallback_price - entry_price,
                "note": f"数据范围内未触发止损阈值 {threshold:.4f}，已按后续可用收盘价补全",
            }

        target_bar = entry_bar
        exit_price = float(target_bar.close)
        return {
            "exit_price": exit_price,
            "exit_time": datetime.fromisoformat(f"{target_bar.trade_date}T15:00:00+00:00"),
            "pnl": exit_price - entry_price,
            "note": "按当日收盘价卖出补全",
        }

    def _find_bar_by_offset(self, bars: list[Any], trade_date_text: str, offset: int) -> Any | None:
        future_bars = [bar for bar in bars if date.fromisoformat(bar.trade_date) >= date.fromisoformat(trade_date_text)]
        if len(future_bars) <= offset:
            return None
        return future_bars[offset]

    def _estimate_atr14(self, bars: list[Any], entry_trade_date_text: str) -> float:
        entry_trade_date = date.fromisoformat(entry_trade_date_text)
        history = [bar for bar in bars if date.fromisoformat(bar.trade_date) <= entry_trade_date]
        if not history:
            return 1.0
        true_ranges: list[float] = []
        previous_close: float | None = None
        for bar in history[-20:]:
            high = float(bar.high)
            low = float(bar.low)
            if previous_close is None:
                tr = high - low
            else:
                tr = max(high - low, abs(high - previous_close), abs(low - previous_close))
            true_ranges.append(tr)
            previous_close = float(bar.close)
        recent = true_ranges[-14:] or true_ranges
        return max(sum(recent) / len(recent), 0.01)

    def _extract_trade_date(self, text: str) -> date | None:
        match = re.search(r"(20\d{2}[-/]\d{2}[-/]\d{2})", text)
        if match is None:
            return None
        return date.fromisoformat(match.group(1).replace("/", "-"))

    def _extract_grouped_trade_candidates(self, text: str, *, market: str) -> list[dict[str, Any]]:
        matches = list(re.finditer(r"(20\d{2}[-/]\d{2}[-/]\d{2})", text))
        groups: list[dict[str, Any]] = []
        for index, match in enumerate(matches):
            trade_date = date.fromisoformat(match.group(1).replace("/", "-"))
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[start:end]
            symbols = self._extract_symbols_by_market(block, market)
            if symbols:
                groups.append(
                    {
                        "trade_date": trade_date,
                        "symbols": symbols,
                        "block_text": block,
                    }
                )
        return groups

    def _extract_labeled_trade_date(self, text: str, label: str) -> date | None:
        match = re.search(rf"{label}[:：]?\s*(20\d{{2}}[-/]\d{{2}}[-/]\d{{2}})", text)
        if match is None:
            return None
        return date.fromisoformat(match.group(1).replace("/", "-"))

    def _extract_symbols(self, text: str) -> list[str]:
        segment_match = re.search(r"买入[:：]\s*(.+?)(?:买入方式|卖出方式|$)", text, flags=re.S)
        target_text = segment_match.group(1) if segment_match else text
        found = re.findall(r"\b\d{6}\.(?:SH|SZ)\b", target_text.upper())
        deduped: list[str] = []
        for symbol in found:
            if symbol not in deduped:
                deduped.append(symbol)
        return deduped

    def _extract_symbols_by_market(self, text: str, market: str) -> list[str]:
        normalized = text.upper().replace(" ", "")
        if market == "cn_equity":
            direct = re.findall(r"\d{6}\.(?:SH|SZ)\b", normalized)
            embedded = re.findall(r"(\d{6})[A-Z0-9_\-\u4e00-\u9fff]*\.(SH|SZ)\b", normalized)
            plain = re.findall(r"\b\d{6}\b", normalized)
            deduped: list[str] = []
            for symbol in direct:
                if symbol not in deduped:
                    deduped.append(symbol)
            for code, suffix in embedded:
                inferred = f"{code}.{suffix}"
                if inferred not in deduped:
                    deduped.append(inferred)
            for symbol in plain:
                inferred = f"{symbol}.SH" if symbol.startswith(("5", "6", "9")) else f"{symbol}.SZ"
                if inferred not in deduped:
                    deduped.append(inferred)
            return deduped
        if market == "us_equity":
            candidates = re.findall(r"\b[A-Z]{1,5}\b", normalized)
            return [item for item in candidates if item not in {"BUY", "SELL", "OPEN", "CLOSE", "USD"}][:5]
        if market == "crypto":
            return re.findall(r"\b[A-Z0-9]{6,15}\b", normalized)[:5]
        if market == "london_gold":
            return [item for item in re.findall(r"\b(?:XAUUSD|GOLD|XAU)\b", normalized)][:3]
        return []

    def _extract_trade_side(self, text: str, market: str) -> str:
        normalized = text.upper()
        if market != "cn_equity" and any(marker in normalized for marker in ("SHORT", "SELLSHORT", "做空")):
            return "short"
        if any(marker in normalized for marker in ("BUY", "买入", "建仓")):
            return "long"
        if market != "cn_equity" and any(marker in normalized for marker in ("SELL", "卖出", "平空")):
            return "short"
        return "long"

    def _extract_trade_pnl(self, text: str) -> float:
        match = re.search(
            r"(?:盈亏|浮盈浮亏|收益|P/?L)[:：]?\s*([+-]?\d+(?:\.\d+)?)",
            text,
            flags=re.I,
        )
        if match is not None:
            return float(match.group(1))
        for line in text.splitlines():
            candidate = line.strip().replace(",", "")
            if not candidate:
                continue
            if any(marker in candidate.upper() for marker in ("SH", "SZ", "USDT", "XAU", "-")):
                continue
            if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", candidate):
                return float(candidate)
        return 0.0

    def _default_entry_time_for_market(self, trade_date: date, market: str) -> datetime:
        if market == "us_equity":
            time_text = "09:30:00"
        elif market == "crypto":
            time_text = "00:00:00"
        elif market == "london_gold":
            time_text = "08:00:00"
        else:
            time_text = "09:30:00"
        return datetime.fromisoformat(f"{trade_date.isoformat()}T{time_text}+00:00")

    def _ocr_image_lines(self, content: bytes) -> list[str]:
        try:
            import numpy as np
            from PIL import Image
            from rapidocr_onnxruntime import RapidOCR
        except Exception as exc:  # pragma: no cover - import is validated in runtime tests
            raise TaskExecutionError("INTERNAL_ERROR", "OCR 依赖不可用，请重新安装应用依赖。") from exc

        if self._ocr_engine is None:
            self._ocr_engine = RapidOCR()

        image = Image.open(BytesIO(content)).convert("RGB")
        result, _ = self._ocr_engine(np.array(image))
        if not result:
            return []
        ordered = sorted(result, key=lambda item: (item[0][0][1], item[0][0][0]))
        return [str(item[1]).strip() for item in ordered if str(item[1]).strip()]

    def _extract_entry_rule(self, text: str) -> dict[str, Any]:
        explicit_price_match = re.search(
            r"买入(?:价|价格)[:：]?\s*([0-9]+(?:\.[0-9]+)?)",
            text,
            flags=re.I,
        )
        if explicit_price_match is not None:
            explicit_price = float(explicit_price_match.group(1))
            return {
                "label": f"按买入价 {explicit_price:g} 买入",
                "price_field": "open",
                "offset": 0,
                "explicit_price": explicit_price,
            }
        offset_match = re.search(r"第([0-9]+)个交易日(开盘价|收盘价)买入", text)
        if offset_match is not None:
            offset = max(int(offset_match.group(1)) - 1, 0)
            price_field = "open" if offset_match.group(2) == "开盘价" else "close"
            return {
                "label": f"第 {offset + 1} 个交易日{offset_match.group(2)}买入",
                "price_field": price_field,
                "offset": offset,
            }
        if "次日开盘价买入" in text:
            return {"label": "次日开盘价买入", "price_field": "open", "offset": 1}
        if "次日收盘价买入" in text:
            return {"label": "次日收盘价买入", "price_field": "close", "offset": 1}
        if "当日收盘价买入" in text:
            return {"label": "当日收盘价买入", "price_field": "close", "offset": 0}
        return {"label": "当日开盘价买入", "price_field": "open", "offset": 0}

    def _extract_entry_rule_or_none(self, text: str) -> dict[str, Any] | None:
        markers = (
            "买入方式",
            "买入价",
            "买入价格",
            "次日开盘价买入",
            "次日收盘价买入",
            "当日收盘价买入",
            "当日开盘价买入",
            "第",
        )
        if not any(marker in text for marker in markers):
            return None
        return self._extract_entry_rule(text)

    def _parse_trade_text_with_llm(
        self,
        *,
        text: str,
        market: str,
        llm_profile: str = "module_default",
    ) -> dict[str, Any] | None:
        runtime = _resolve_llm_runtime(
            self._settings,
            llm_profile,
            module="trade_text_parse",
        )
        if not runtime:
            return None
        endpoint = _llm_endpoint(runtime["base_url"])
        system_prompt = (
            "你是交易记录文本解析助手。请把中文长文本里的多日期交易清单解析成 JSON。"
            "不要编造不存在的代码或日期。无法确认就留空。"
            "输出必须是 JSON 对象，字段固定为：global_entry_rule、global_exit_rule、groups、warnings。"
            "groups 是数组，每个对象字段固定为：trade_date、symbols、entry_rule_text、exit_rule_text、explicit_exit_date、confidence。"
            "trade_date 统一用 YYYY-MM-DD，symbols 统一用标准代码。"
        )
        request_payload = {
            "model": runtime["model"],
            "temperature": 0.1,
            "stream": True,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "market": market,
                            "text": text,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        try:
            with httpx.Client(timeout=45) as client:
                with client.stream(
                    "POST",
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {runtime['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                ) as response:
                    response.raise_for_status()
                    content = self._extract_stream_content(response)
            parsed = self._extract_json_object(content)
            groups = parsed.get("groups")
            if not isinstance(groups, list):
                return None
            return {
                "global_entry_rule": str(parsed.get("global_entry_rule") or "").strip(),
                "global_exit_rule": str(parsed.get("global_exit_rule") or "").strip(),
                "llm_profile": runtime["profile_id"],
                "llm_profile_label": runtime["label"],
                "groups": [
                    {
                        "trade_date": str(item.get("trade_date") or "").strip(),
                        "symbols": [str(symbol).strip().upper() for symbol in item.get("symbols", []) if str(symbol).strip()],
                        "entry_rule_text": str(item.get("entry_rule_text") or "").strip(),
                        "exit_rule_text": str(item.get("exit_rule_text") or "").strip(),
                        "explicit_exit_date": str(item.get("explicit_exit_date") or "").strip(),
                        "confidence": str(item.get("confidence") or "").strip(),
                    }
                    for item in groups
                    if isinstance(item, dict)
                ],
                "warnings": [str(item).strip() for item in parsed.get("warnings", []) if str(item).strip()],
            }
        except Exception:
            return None

    def _extract_stream_content(self, response: httpx.Response) -> str:
        content_parts: list[str] = []
        for raw_line in response.iter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload_text = line[5:].strip()
            if payload_text == "[DONE]":
                break
            try:
                chunk = json.loads(payload_text)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                content_parts.append(str(piece))
        if content_parts:
            return "".join(content_parts)
        return response.text

    def _extract_json_object(self, content: str) -> dict[str, Any]:
        candidate = content.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, flags=re.S)
        if fenced:
            candidate = fenced.group(1)
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = candidate[start : end + 1]
        return json.loads(candidate)

    def _extract_rule_from_llm_text(self, text: str | None, *, kind: str) -> dict[str, Any] | None:
        if not text:
            return None
        if kind == "entry":
            return self._extract_entry_rule_or_none(text)
        return self._extract_exit_rule(text)

    def _match_llm_group(self, llm_parse: dict[str, Any] | None, *, trade_date: str) -> dict[str, Any] | None:
        if not llm_parse:
            return None
        for item in llm_parse.get("groups", []):
            if item.get("trade_date") == trade_date:
                return item
        return None

    def _extract_iso_date(self, text: str | None) -> date | None:
        if not text:
            return None
        match = re.search(r"(20\d{2}[-/]\d{2}[-/]\d{2})", text)
        if match is None:
            return None
        return date.fromisoformat(match.group(1).replace("/", "-"))

    def _build_ai_review_summary(self, llm_parse: dict[str, Any] | None) -> dict[str, Any]:
        if not llm_parse:
            return {
                "enabled": False,
                "used": False,
                "mode_label": "规则解析",
                "profile_label": "",
                "warnings": [],
            }
        return {
            "enabled": True,
            "used": True,
            "mode_label": "AI 混合解析",
            "profile_label": str(llm_parse.get("llm_profile_label") or ""),
            "group_count": len(llm_parse.get("groups", [])),
            "warnings": llm_parse.get("warnings", []),
        }

    def _extract_exit_rule(self, text: str) -> dict[str, Any] | None:
        explicit_price_match = re.search(
            r"卖出(?:价|价格)[:：]?\s*([0-9]+(?:\.[0-9]+)?)",
            text,
            flags=re.I,
        )
        if explicit_price_match is not None:
            explicit_price = float(explicit_price_match.group(1))
            return {
                "type": "explicit_price",
                "label": f"按卖出价 {explicit_price:g} 卖出",
                "value": explicit_price,
            }
        offset_match = re.search(r"第([0-9]+)个交易日收盘价卖出", text)
        if offset_match is not None:
            offset = max(int(offset_match.group(1)) - 1, 0)
            return {
                "type": "offset_close",
                "label": f"第 {offset + 1} 个交易日收盘价卖出",
                "offset": offset,
            }
        take_profit_match = re.search(r"(?:止盈|高于买入价)([0-9]+(?:\.[0-9]+)?)%", text)
        if take_profit_match is not None:
            return {
                "type": "take_profit_pct",
                "label": f"上涨 {take_profit_match.group(1)}% 止盈卖出",
                "pct": float(take_profit_match.group(1)) / 100,
            }
        stop_loss_match = re.search(r"(?:止损|低于买入价)([0-9]+(?:\.[0-9]+)?)%", text)
        if stop_loss_match is not None:
            return {
                "type": "stop_loss_pct",
                "label": f"下跌 {stop_loss_match.group(1)}% 止损卖出",
                "pct": float(stop_loss_match.group(1)) / 100,
            }
        atr_match = re.search(
            r"(?:最低价|价格)(?:低于|跌破)当日开盘价-([0-9]+(?:\.[0-9]+)?)倍atr(?:的值)?(?:则)?(?:时卖出|卖出)?",
            text,
            flags=re.I,
        )
        if atr_match is not None:
            return {
                "type": "atr_low_break",
                "label": f"当最低价低于当日开盘价减去 {atr_match.group(1)} 倍 ATR 时卖出",
                "multiplier": float(atr_match.group(1)),
            }
        if "次日收盘价卖出" in text:
            return {"type": "next_close", "label": "次日收盘价卖出"}
        if "当日收盘价卖出" in text:
            return {"type": "same_close", "label": "当日收盘价卖出"}
        return None


class FinancialAssistantService(MentorService):
    def list_workflows(self) -> list[dict[str, Any]]:
        return [
            {
                "workflow_id": "market_map",
                "title": "市场地图",
                "summary": "快速收拢市场主线、风格、情绪与关键风险，适合盘前或盘后总览。",
                "best_for": "盘前判断主线、盘后回顾当天结构变化",
                "deliverables": ["市场主线摘要", "风格与情绪判断", "关键风险清单"],
            },
            {
                "workflow_id": "company_deep_dive",
                "title": "公司深研",
                "summary": "围绕单一标的做基本面、预期差、催化剂和风险的结构化研究。",
                "best_for": "研究个股、ETF 持仓映射、财报前准备",
                "deliverables": ["核心观点", "多空分歧", "催化剂与风险"],
            },
            {
                "workflow_id": "event_impact",
                "title": "事件冲击",
                "summary": "把政策、财报、宏观数据或行业事件拆成影响链，判断受益与受损方向。",
                "best_for": "政策事件、行业会议、公司公告后的快速判断",
                "deliverables": ["事件影响链", "受益/受损对象", "跟踪点"],
            },
            {
                "workflow_id": "bull_bear_debate",
                "title": "多空辩论",
                "summary": "模拟多头与空头研究员辩论，避免单边确认偏误。",
                "best_for": "准备建仓前做反方论证，或复核已有观点",
                "deliverables": ["多头论点", "空头论点", "关键变量"],
            },
            {
                "workflow_id": "risk_committee",
                "title": "风险委员会",
                "summary": "从仓位、波动、制度约束和数据可信度角度审视交易想法。",
                "best_for": "准备回测、准备实盘执行、复核失败策略",
                "deliverables": ["风险清单", "仓位建议", "执行前核对项"],
            },
            {
                "workflow_id": "ic_memo",
                "title": "投委会纪要",
                "summary": "把研究结论压缩成机构可流转的结论、证据、反证和执行建议。",
                "best_for": "向团队同步研究结论，沉淀正式研究输出",
                "deliverables": ["执行摘要", "核心证据", "反证条件", "下一步动作"],
            },
        ]

    def list_desks(self) -> list[dict[str, Any]]:
        return [
            {"desk_id": "macro_news", "title": "宏观与新闻台", "focus": "政策、宏观、事件与情绪催化"},
            {"desk_id": "fundamental", "title": "基本面研究员", "focus": "商业模式、盈利驱动、估值与预期差"},
            {"desk_id": "technical", "title": "技术与成交结构台", "focus": "趋势、节奏、成交密集区与风险位"},
            {"desk_id": "sentiment", "title": "情绪与风格台", "focus": "市场风格轮动、拥挤度、强弱分布"},
            {"desk_id": "bull", "title": "多头研究员", "focus": "寻找被低估的正面逻辑和催化兑现路径"},
            {"desk_id": "bear", "title": "空头研究员", "focus": "寻找证据不足、估值透支和执行风险"},
            {"desk_id": "risk_pm", "title": "风控与组合经理", "focus": "仓位、约束、回撤承受与执行顺序"},
        ]

    def analyze(self, request: AssistantResearchRequest) -> dict[str, Any]:
        query = request.query.strip()
        if not query:
            raise TaskExecutionError("INVALID_ARGUMENT", "query is required")

        workflow = self._resolve_workflow(request.workflow_id)
        fallback = self._build_assistant_fallback(workflow=workflow, request=request)
        response = {
            "assistant_name": "金融助手",
            "assistant_role": "机构研究协作台",
            "query": query,
            "workflow_id": workflow["workflow_id"],
            "workflow_title": workflow["title"],
            "market_scope": request.market_scope,
            "research_depth": request.research_depth,
            "target_symbol": request.target_symbol,
            "current_module": request.current_module,
            "workflow_steps": self._workflow_steps_for(workflow["workflow_id"]),
            "desk_lineup": self.list_desks(),
            **fallback,
            "answer_source": "fallback",
            "answer_mode_label": "平台研究模板",
        }
        try:
            llm_payload = self._answer_with_assistant_llm(
                workflow=workflow,
                request=request,
                fallback=response,
            )
            if llm_payload:
                response.update(llm_payload)
                response["answer_source"] = "llm"
                response["answer_mode_label"] = "AI 研究编组"
        except Exception:
            pass
        return response

    def _resolve_workflow(self, workflow_id: str) -> dict[str, Any]:
        for item in self.list_workflows():
            if item["workflow_id"] == workflow_id:
                return item
        return self.list_workflows()[0]

    def _workflow_steps_for(self, workflow_id: str) -> list[str]:
        mapping = {
            "market_map": ["先收拢市场主线", "再判断风格与情绪", "最后列出明日优先跟踪项"],
            "company_deep_dive": ["先明确研究对象与市场", "再拆核心驱动与风险", "最后沉淀验证清单与模块入口"],
            "event_impact": ["先定义事件本身", "再拆影响链条", "最后判断受益、受损与验证点"],
            "bull_bear_debate": ["先写多头逻辑", "再强制写空头反驳", "最后提炼需要继续验证的关键变量"],
            "risk_committee": ["先列执行假设", "再审视仓位与约束", "最后给出执行前核对项"],
            "ic_memo": ["先压缩结论", "再列支撑证据与反证条件", "最后沉淀动作建议和输出格式"],
        }
        return mapping.get(workflow_id, mapping["market_map"])

    def _build_assistant_fallback(
        self,
        *,
        workflow: dict[str, Any],
        request: AssistantResearchRequest,
    ) -> dict[str, Any]:
        target = request.target_symbol or "当前研究对象"
        workflow_id = workflow["workflow_id"]
        summary_map = {
            "market_map": f"先把 {request.market_scope} 市场主线、情绪、风格和关键风险梳理清楚，再决定当天研究优先级。",
            "company_deep_dive": f"围绕 {target} 先拆盈利驱动、估值预期和催化剂，再判断研究是否值得继续加深。",
            "event_impact": f"这次更适合先把事件影响链拆开，看它会如何传导到 {target} 或相关板块。",
            "bull_bear_debate": f"对 {target} 不要只写单边理由，先把多头和空头都摆上桌，再决定是否值得下注。",
            "risk_committee": "先把成交假设、市场制度和仓位边界写清楚，再进入回测或执行。",
            "ic_memo": "先用投委会口径压缩观点，再补证据、反证和行动建议。",
        }
        desk_briefs = [
            {
                "desk": "宏观与新闻台",
                "title": "外部驱动",
                "summary": "先确认与你的问题相关的政策、宏观和新闻变量，避免只从价格本身下结论。",
            },
            {
                "desk": "基本面研究员",
                "title": "驱动与预期差",
                "summary": f"围绕 {target} 拆收入、利润、现金流、估值和市场预期差，不要只写概念性逻辑。",
            },
            {
                "desk": "技术与成交结构台",
                "title": "价格与节奏",
                "summary": "确认趋势环境、关键价位、放量/缩量关系和节奏位置，避免研究结论与执行节奏脱节。",
            },
            {
                "desk": "风控与组合经理",
                "title": "执行边界",
                "summary": "把市场制度、持仓上限、回撤承受和数据可信度一起纳入结论，不做脱离执行条件的建议。",
            },
        ]
        debate = [
            {"side": "多头", "view": f"{target} 如果要成立多头逻辑，必须看到驱动、催化和市场承接三者同时成立。"},
            {"side": "空头", "view": "如果核心证据只停留在想象或单一事件刺激，研究就还不够扎实，容易高估胜率。"},
        ]
        risk_checklist = [
            "先确认市场制度边界，尤其是 T+1、可否做空、最小交易单位和流动性。",
            "把数据口径、时间范围和快照来源写清楚，避免研究结论不可复现。",
            "如果要进入回测或执行，先定义失败条件，而不是只定义成功剧本。",
        ]
        next_actions = [
            "先把问题压缩成一个明确研究任务，不要把多个目标混在一句话里。",
            "如果要落成策略，下一步去策略工坊整理成入场、出场和风控条件。",
            "如果要验证执行，下一步去回测中心把成交与市场约束写进配置。",
        ]
        related_modules = [
            {"label": "策略工坊", "path": "/strategy", "reason": "把研究结论转成可执行规则"},
            {"label": "回测中心", "path": "/backtests", "reason": "验证执行假设和风险控制是否成立"},
            {"label": "规则模块", "path": "/rules", "reason": "补市场制度与术语边界"},
        ]
        if workflow_id == "company_deep_dive":
            related_modules.insert(0, {"label": "指标设置", "path": "/indicators", "reason": "从指标和因子层补研究抓手"})
        return {
            "executive_summary": summary_map.get(workflow_id, summary_map["market_map"]),
            "desk_briefs": desk_briefs,
            "debate": debate,
            "risk_checklist": risk_checklist,
            "deliverables": workflow["deliverables"],
            "next_actions": next_actions,
            "related_modules": related_modules,
        }

    def _answer_with_assistant_llm(
        self,
        *,
        workflow: dict[str, Any],
        request: AssistantResearchRequest,
        fallback: dict[str, Any],
    ) -> dict[str, Any] | None:
        runtime = _resolve_llm_runtime(
            self._settings,
            request.llm_profile,
            module="assistant",
        )
        if not runtime:
            return None
        endpoint = _llm_endpoint(runtime["base_url"])

        system_prompt = (
            "你是一名机构级金融研究助手，模拟宏观、基本面、技术、情绪、多头、空头、风控与组合经理的协作。"
            "请用中文输出结构化研究结果，不要写成泛泛聊天。"
            "输出必须是 JSON，对象字段固定为：executive_summary、desk_briefs、debate、risk_checklist、deliverables、next_actions、related_modules。"
            "desk_briefs 是 3 到 6 个对象数组，每个对象含 desk、title、summary。"
            "debate 是 2 个对象数组，每个对象含 side、view。"
            "risk_checklist、deliverables、next_actions 都是中文字符串数组。"
            "related_modules 是对象数组，每个对象含 label、path、reason，路径仅限 /strategy /backtests /rules /indicators /replay /mentor /workspace。"
        )
        prompt_payload = {
            "workflow": workflow,
            "query": request.query,
            "target_symbol": request.target_symbol,
            "market_scope": request.market_scope,
            "research_depth": request.research_depth,
            "current_module": request.current_module,
            "conversation_history": request.conversation_history,
            "fallback": {
                "executive_summary": fallback["executive_summary"],
                "deliverables": fallback["deliverables"],
                "risk_checklist": fallback["risk_checklist"],
            },
        }
        request_payload = {
            "model": runtime["model"],
            "temperature": 0.35,
            "stream": True,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
            ],
        }
        content = ""
        for attempt in range(3):
            try:
                with httpx.Client(timeout=60) as client:
                    with client.stream(
                        "POST",
                        endpoint,
                        headers={
                            "Authorization": f"Bearer {runtime['api_key']}",
                            "Content-Type": "application/json",
                        },
                        json=request_payload,
                    ) as response:
                        response.raise_for_status()
                        content = self._extract_stream_content(response)
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    sleep(1.2 * (attempt + 1))
                    continue
                raise

        parsed = self._extract_json_object(content)
        return {
            "executive_summary": str(parsed.get("executive_summary") or fallback["executive_summary"]),
            "desk_briefs": self._normalize_assistant_desks(parsed.get("desk_briefs") or fallback["desk_briefs"]),
            "debate": self._normalize_debate(parsed.get("debate") or fallback["debate"]),
            "risk_checklist": self._normalize_string_list(parsed.get("risk_checklist") or fallback["risk_checklist"]),
            "deliverables": self._normalize_string_list(parsed.get("deliverables") or fallback["deliverables"]),
            "next_actions": self._normalize_string_list(parsed.get("next_actions") or fallback["next_actions"]),
            "related_modules": self._normalize_related_modules(parsed.get("related_modules") or fallback["related_modules"]),
            "llm_profile": runtime["profile_id"],
            "llm_profile_label": runtime["label"],
        }

    def _normalize_assistant_desks(self, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, str]] = []
        for item in value[:6]:
            if not isinstance(item, dict):
                continue
            desk = str(item.get("desk", "")).strip()
            title = str(item.get("title", "")).strip()
            summary = str(item.get("summary", "")).strip()
            if desk and title and summary:
                items.append({"desk": desk, "title": title, "summary": summary})
        return items

    def _normalize_debate(self, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, str]] = []
        for item in value[:4]:
            if not isinstance(item, dict):
                continue
            side = str(item.get("side", "")).strip()
            view = str(item.get("view", "")).strip()
            if side and view:
                items.append({"side": side, "view": view})
        return items

    def _normalize_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:6]

    def _normalize_related_modules(self, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, str]] = []
        for item in value[:6]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            path = str(item.get("path", "")).strip()
            reason = str(item.get("reason", "")).strip()
            if label and path.startswith("/") and reason:
                items.append({"label": label, "path": path, "reason": reason})
        return items


class WorkspaceService:
    def __init__(
        self,
        *,
        strategy_service: StrategyService,
        task_repository: TaskRepository,
        market_data_service: MarketDataService | None = None,
    ) -> None:
        self._strategy_service = strategy_service
        self._task_repository = task_repository
        self._market_data_service = market_data_service

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
                    "version_label": item.version_label,
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
            "data_hub_status": self._market_data_service.describe_pipeline()
            if self._market_data_service is not None
            else {},
            "focus_cards": self._build_focus_cards(
                projects=projects,
                backtests=backtests,
                replays=replays,
            ),
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

    def _build_focus_cards(
        self,
        *,
        projects: list[StrategyVersionRecord],
        backtests: list[TaskRecord],
        replays: list[TaskRecord],
    ) -> list[dict[str, str]]:
        cards: list[dict[str, str]] = []
        if projects:
            latest_project = projects[0]
            cards.append(
                {
                    "title": "继续当前策略版本",
                    "summary": f"{latest_project.title} · {latest_project.version_label or latest_project.version_id}",
                    "action_label": "回到策略工坊",
                    "path": "/strategy",
                }
            )
        if backtests:
            latest_backtest = backtests[0]
            metrics = latest_backtest.result.get("metrics", {})
            cards.append(
                {
                    "title": "先看最近一次回测",
                    "summary": (
                        f"收益 {round(float(metrics.get('total_return_pct', 0.0) or 0.0), 2)}%，"
                        f" 交易 {int(metrics.get('trade_count', 0) or 0)} 笔。"
                    ),
                    "action_label": "打开回测中心",
                    "path": "/backtests",
                }
            )
        if replays:
            latest_replay = replays[0]
            cards.append(
                {
                    "title": "把复盘结论回灌到规则",
                    "summary": latest_replay.result.get(
                        "summary",
                        "最近一轮复盘已完成，可把建议规则回写到下一版策略。",
                    ),
                    "action_label": "进入交易复盘",
                    "path": "/replay",
                }
            )
        if not cards:
            cards.append(
                {
                    "title": "先跑通第一条研究闭环",
                    "summary": "先问金融导师，再去策略工坊生成第一版策略，之后运行回测并做复盘。",
                    "action_label": "打开金融导师",
                    "path": "/mentor",
                }
            )
        return cards[:3]


class AdminService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        session_repository: UserSessionRepository,
        auth_event_repository: AuthEventRepository,
        audit_log_repository: AdminAuditLogRepository,
        app_log_repository: ApplicationLogRepository,
        strategy_repository: StrategyRepository,
        task_repository: TaskRepository,
    ) -> None:
        self._user_repository = user_repository
        self._session_repository = session_repository
        self._auth_event_repository = auth_event_repository
        self._audit_log_repository = audit_log_repository
        self._app_log_repository = app_log_repository
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
        security_events = self._auth_event_repository.list_recent(limit=200)
        audit_logs = self._audit_log_repository.list_recent(limit=50)
        app_logs = self._app_log_repository.list_recent(limit=200)
        cutoff_24h = now - timedelta(hours=24)
        failed_logins_24h = len(
            [
                item
                for item in security_events
                if item.event_type == "login"
                and item.outcome in {"failed", "blocked"}
                and self._comparable_datetime(item.created_at) >= self._comparable_datetime(cutoff_24h)
            ]
        )
        app_errors_24h = len(
            [
                item
                for item in app_logs
                if item.level == "error"
                and self._comparable_datetime(item.created_at) >= self._comparable_datetime(cutoff_24h)
            ]
        )

        return {
            "counts": {
                "users": len(users),
                "admins": len([item for item in users if item.role == "admin"]),
                "suspended_users": len([item for item in users if item.status != "active"]),
                "active_sessions": len(sessions),
                "projects": len(projects),
                "backtests": len(backtests),
                "replays": len(replays),
                "running_tasks": len(running_tasks),
                "failed_tasks": len(failed_tasks),
                "new_users_7d": len([item for item in users if item.created_at >= cutoff_7d]),
                "failed_logins_24h": failed_logins_24h,
                "app_errors_24h": app_errors_24h,
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
            "recent_audit_logs": self.list_audit_logs(limit=8),
            "recent_security_events": self.list_security_events(limit=8),
            "recent_app_logs": self.list_app_logs(limit=8),
            "governance_notes": self._build_governance_notes(
                users=len(users),
                running_tasks=len(running_tasks),
                failed_tasks=len(failed_tasks),
                coverage_risk_count=len(coverage_risk_snapshots),
                suspended_users=len([item for item in users if item.status != "active"]),
                failed_logins_24h=failed_logins_24h,
                app_errors_24h=app_errors_24h,
                audit_events=len(audit_logs),
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
        self._record_audit_log(
            actor_user_id=current_user_id,
            target_user_id=updated.user_id,
            action="user.role_updated",
            summary=f"将 {updated.username} 的角色更新为 {normalized_role}",
            details={"role": normalized_role},
        )
        return updated

    def update_user_status(
        self,
        *,
        current_user_id: str,
        target_user_id: str,
        status: str,
        reason: str | None,
    ) -> UserRecord:
        normalized_status = status.strip().lower()
        if normalized_status not in {"active", "suspended"}:
            raise TaskExecutionError("INVALID_ARGUMENT", "status must be active or suspended")

        target = self._user_repository.get(target_user_id)
        if target is None:
            raise TaskExecutionError("NOT_FOUND", "user not found")
        if target.user_id == current_user_id and normalized_status != "active":
            raise TaskExecutionError("STATE_CONFLICT", "cannot suspend current admin session")
        if target.role == "admin" and normalized_status != "active":
            active_admin_count = len(
                [
                    item
                    for item in self._user_repository.list()
                    if item.role == "admin" and item.status == "active"
                ]
            )
            if active_admin_count <= 1:
                raise TaskExecutionError("STATE_CONFLICT", "cannot suspend the last active admin")

        normalized_reason = (reason or "").strip() or None
        updated = self._user_repository.update_status(
            target_user_id,
            status=normalized_status,
            reason=normalized_reason,
        )
        if updated is None:
            raise TaskExecutionError("NOT_FOUND", "user not found")
        if normalized_status != "active":
            self._session_repository.delete_by_user_id(target_user_id)
        self._record_audit_log(
            actor_user_id=current_user_id,
            target_user_id=updated.user_id,
            action="user.status_updated",
            summary=f"将 {updated.username} 的状态更新为 {normalized_status}",
            details={"status": normalized_status, "reason": normalized_reason},
        )
        return updated

    def reset_user_password(
        self,
        *,
        current_user_id: str,
        target_user_id: str,
        new_password: str,
    ) -> UserRecord:
        normalized_password = new_password.strip()
        if len(normalized_password) < 6:
            raise TaskExecutionError("INVALID_ARGUMENT", "new_password must be at least 6 characters")
        target = self._user_repository.get(target_user_id)
        if target is None:
            raise TaskExecutionError("NOT_FOUND", "user not found")
        updated = self._user_repository.update_password_hash(
            target_user_id,
            hash_password(normalized_password),
        )
        if updated is None:
            raise TaskExecutionError("NOT_FOUND", "user not found")
        self._session_repository.delete_by_user_id(target_user_id)
        self._record_audit_log(
            actor_user_id=current_user_id,
            target_user_id=updated.user_id,
            action="user.password_reset",
            summary=f"已重置 {updated.username} 的登录密码并清理其会话",
            details={"password_reset": True},
        )
        return updated

    def list_audit_logs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        users_by_id = {item.user_id: item for item in self._user_repository.list()}
        logs = self._audit_log_repository.list_recent(limit=limit)
        return [
            {
                "log_id": item.log_id,
                "action": item.action,
                "summary": item.summary,
                "actor_user_id": item.actor_user_id,
                "actor_username": users_by_id.get(item.actor_user_id).username
                if users_by_id.get(item.actor_user_id)
                else item.actor_user_id,
                "target_user_id": item.target_user_id,
                "target_username": users_by_id.get(item.target_user_id).username
                if item.target_user_id and users_by_id.get(item.target_user_id)
                else None,
                "details": item.details,
                "created_at": item.created_at.isoformat(),
            }
            for item in logs
        ]

    def list_security_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "event_id": item.event_id,
                "event_type": item.event_type,
                "outcome": item.outcome,
                "username": item.username,
                "user_id": item.user_id,
                "reason": item.reason,
                "ip_address": item.ip_address,
                "created_at": item.created_at.isoformat(),
            }
            for item in self._auth_event_repository.list_recent(limit=limit)
        ]

    def list_app_logs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "log_id": item.log_id,
                "level": item.level,
                "source": item.source,
                "category": item.category,
                "message": item.message,
                "request_path": item.request_path,
                "user_id": item.user_id,
                "username": item.username,
                "workspace_id": item.workspace_id,
                "details": item.details,
                "created_at": item.created_at.isoformat(),
            }
            for item in self._app_log_repository.list_recent(limit=limit)
        ]

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

        auth_events = self._auth_event_repository.list_recent(limit=500)
        cutoff_24h = utcnow() - timedelta(hours=24)
        last_login_by_user: dict[str, datetime] = {}
        last_failed_login_by_user: dict[str, datetime] = {}
        failed_login_count_24h_by_user: dict[str, int] = {}
        for item in auth_events:
            if item.user_id is None:
                continue
            if item.event_type == "login" and item.outcome == "succeeded":
                last_login_by_user[item.user_id] = max(
                    last_login_by_user.get(item.user_id, item.created_at),
                    item.created_at,
                )
            if item.event_type == "login" and item.outcome in {"failed", "blocked"}:
                last_failed_login_by_user[item.user_id] = max(
                    last_failed_login_by_user.get(item.user_id, item.created_at),
                    item.created_at,
                )
                if self._comparable_datetime(item.created_at) >= self._comparable_datetime(cutoff_24h):
                    failed_login_count_24h_by_user[item.user_id] = (
                        failed_login_count_24h_by_user.get(item.user_id, 0) + 1
                    )

        items = [
            {
                "user_id": item.user_id,
                "workspace_id": AuthService.workspace_id_for_user_id(item.user_id),
                "username": item.username,
                "contact": item.contact,
                "role": item.role,
                "status": item.status,
                "status_reason": item.status_reason,
                "created_at": item.created_at.isoformat(),
                "active_sessions": session_count_by_user.get(item.user_id, 0),
                "project_count": project_count_by_user.get(item.user_id, 0),
                "backtest_count": task_summary_by_user.get(item.user_id, {}).get("backtests", 0),
                "replay_count": task_summary_by_user.get(item.user_id, {}).get("replays", 0),
                "optimization_count": task_summary_by_user.get(item.user_id, {}).get("optimizations", 0),
                "running_task_count": task_summary_by_user.get(item.user_id, {}).get("running_tasks", 0),
                "failed_task_count": task_summary_by_user.get(item.user_id, {}).get("failed_tasks", 0),
                "failed_login_count_24h": failed_login_count_24h_by_user.get(item.user_id, 0),
                "last_login_at": last_login_by_user.get(item.user_id).isoformat()
                if last_login_by_user.get(item.user_id)
                else None,
                "last_failed_login_at": last_failed_login_by_user.get(item.user_id).isoformat()
                if last_failed_login_by_user.get(item.user_id)
                else None,
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
        suspended_users: int,
        failed_logins_24h: int,
        app_errors_24h: int,
        audit_events: int,
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
        if suspended_users:
            notes.append("当前存在停用账户，建议定期复核停用原因并确认是否需要恢复或清理。")
        if failed_logins_24h:
            notes.append("最近 24 小时存在登录失败或阻断记录，建议关注账户安全和登录提示设计。")
        if app_errors_24h:
            notes.append("最近 24 小时存在用户侧或服务侧报错记录，建议管理员优先查看应用日志并复核高频异常。")
        if audit_events == 0:
            notes.append("管理员审计日志刚启用，后续应继续沉淀治理动作证据链。")
        if not notes:
            notes.append("平台运行状态平稳，下一步更适合推进实验对比、审计视图和管理员操作日志。")
        return notes

    def _record_audit_log(
        self,
        *,
        actor_user_id: str,
        target_user_id: str | None,
        action: str,
        summary: str,
        details: dict[str, Any],
    ) -> None:
        self._audit_log_repository.create(
            AdminAuditLogRecord(
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                action=action,
                summary=summary,
                details=details,
            )
        )

    @staticmethod
    def _comparable_datetime(value: datetime) -> datetime:
        return value.replace(tzinfo=None) if value.tzinfo is not None else value


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
        normalized_contract["data_provider"] = data_source.get("provider")
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
            "strategy_spec": project.strategy_dsl,
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
            "execution_summary": backtest.get("execution_summary", {}),
            "strategy_python": project.strategy_python,
            "strategy_title": project.title,
        }

    return _builder


def _normalize_execution_contract(
    execution_contract: dict[str, Any],
    strategy_dsl: dict[str, Any],
) -> dict[str, Any]:
    contract = dict(execution_contract)
    asset_type = strategy_dsl.get("asset_type", "stock")
    calendar = contract.get("calendar", "unknown")
    settlement_policy = contract.get("settlement_policy") or _infer_settlement_policy(
        calendar=calendar,
        asset_type=asset_type,
    )
    strategy_position = strategy_dsl.get("position", {})
    contract["settlement_policy"] = settlement_policy
    contract["same_day_exit_allowed"] = bool(
        contract.get(
            "same_day_exit_allowed",
            settlement_policy != "t_plus_one",
        )
    )
    contract["market_constraint_text"] = (
        contract.get("market_constraint_text")
        or contract.get("market_constraint")
        or _build_market_constraint_text(
            calendar=calendar,
            asset_type=asset_type,
            min_trade_unit=contract.get("position_sizing", {}).get(
                "min_trade_unit",
                100 if asset_type in {"stock", "etf"} else 1,
            ),
            same_day_exit_allowed=contract["same_day_exit_allowed"],
        )
    )
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


def _infer_settlement_policy(*, calendar: str, asset_type: str) -> str:
    if calendar == "cn_a_share" and asset_type in {"stock", "etf"}:
        return "t_plus_one"
    return "t_plus_zero"


def _build_market_constraint_text(
    *,
    calendar: str,
    asset_type: str,
    min_trade_unit: int,
    same_day_exit_allowed: bool,
) -> str:
    if calendar == "cn_a_share" and asset_type in {"stock", "etf"}:
        return f"A股按 T+1 卖出，{asset_type.upper()} 最小交易单位 {min_trade_unit} 股"
    if calendar == "us_equity":
        return "美股默认按 T+0 语义处理，可同日买入卖出，最小交易单位按券商规则执行"
    if calendar == "crypto_24x7":
        return "加密货币默认按 7x24 连续交易处理，可同日反复开平仓"
    if calendar == "london_gold":
        return "伦敦金按全球连续报价时段处理，成交规则需结合交易时段理解"
    return (
        "当前市场允许同日退出持仓"
        if same_day_exit_allowed
        else "当前市场不允许同日退出持仓"
    )


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
    market_data_service: MarketDataService | None = None,
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
        all_holding_minutes = [
            _holding_minutes(item.entry_time, item.exit_time) for item in records
        ]
        avg_holding_minutes = (
            round(sum(all_holding_minutes) / len(all_holding_minutes), 2)
            if all_holding_minutes
            else 0.0
        )
        avg_win_holding_minutes = (
            round(
                sum(_holding_minutes(item.entry_time, item.exit_time) for item in win_records)
                / len(win_records),
                2,
            )
            if win_records
            else 0.0
        )
        avg_loss_holding_minutes = (
            round(
                sum(_holding_minutes(item.entry_time, item.exit_time) for item in loss_records)
                / len(loss_records),
                2,
            )
            if loss_records
            else 0.0
        )

        replay_market = _infer_replay_market(records)
        analysis_options = _normalize_replay_analysis_options(payload.get("analysis_options") or {})
        daily_contexts = _build_replay_daily_contexts(
            records=records,
            replay_market=replay_market,
            analysis_options=analysis_options,
            market_data_service=market_data_service,
        )
        minute_contexts, minute_status = _build_replay_minute_contexts(
            records=records,
            replay_market=replay_market,
            analysis_options=analysis_options,
            market_data_service=market_data_service,
        )
        fundamental_contexts, fundamental_status = _build_replay_fundamental_contexts(
            records=records,
            replay_market=replay_market,
            analysis_options=analysis_options,
            market_data_service=market_data_service,
        )
        analysis_scope = _build_replay_analysis_scope(
            replay_market=replay_market,
            focus_dimensions=payload.get("focus_dimensions") or [],
            analysis_options=analysis_options,
            daily_contexts=daily_contexts,
            minute_contexts=minute_contexts,
            fundamental_contexts=fundamental_contexts,
            minute_status=minute_status,
            fundamental_status=fundamental_status,
        )
        best_side_label = _describe_trade_side(best_side[0], replay_market)
        worst_side_label = _describe_trade_side(worst_side[0], replay_market)
        replay_supports_short = _market_supports_short(replay_market)
        has_side_comparison = len(side_breakdown) > 1

        suggestion_rules: list[dict[str, Any]] = []
        if not replay_supports_short and any(item.side == "short" for item in records):
            suggestion_rules.append(
                {
                    "title": "先核对反向记录来源",
                    "description": (
                        "当前交割单更接近 A 股普通买卖场景，平台默认不按做空规则解释。"
                        "如果记录里出现了反向卖出方向，请先确认是不是方向映射错误，"
                        "或者把它单独归类到融资融券 / 衍生品策略后再复盘。"
                    ),
                    "dsl_patch": {
                        "validation": {
                            "market_supports_short": False,
                            "action": "verify_side_mapping_or_split_strategy",
                        }
                    },
                }
            )
        if has_side_comparison and worst_side[1]["count"] > 0 and worst_side[1]["pnl_sum"] < 0:
            suggestion_rules.append(
                {
                    "title": "收缩弱势方向",
                    "description": _build_side_optimization_description(
                        side=worst_side[0],
                        side_label=worst_side_label,
                        stats=worst_side[1],
                        market=replay_market,
                    ),
                    "dsl_patch": _build_side_optimization_patch(
                        best_side=best_side[0],
                        worst_side=worst_side[0],
                        market=replay_market,
                    ),
                }
            )
        if not has_side_comparison:
            suggestion_rules.extend(
                _build_single_side_suggestions(
                    side=best_side[0],
                    side_label=best_side_label,
                    market=replay_market,
                    stats=best_side[1],
                )
            )
        if loss_records and abs(avg_loss) > avg_win:
            suggestion_rules.append(
                {
                    "title": "收紧止损阈值",
                    "description": (
                        f"当前平均单笔亏损 {avg_loss:.2f}，已经明显大于平均盈利 {avg_win:.2f}。"
                        "建议把止损收紧到 2% 左右，同时把单笔最长持有时间限制在 8 根 K 线内，"
                        "避免亏损拖延放大。"
                    ),
                    "dsl_patch": {
                        "risk": {
                            "stop_loss_pct": -0.02,
                            "max_holding_bars": 8,
                        }
                    },
                }
            )
        if not suggestion_rules:
            suggestion_rules.append(
                {
                    "title": "扩大样本继续验证",
                    "description": (
                        "当前样本没有出现明显失衡，建议保留现有规则，继续按相同市场和周期"
                        "积累至少 20 笔同类交易后，再评估是否需要调整开仓过滤条件。"
                    ),
                    "dsl_patch": {"note": "keep_current_rules"},
                }
            )

        if has_side_comparison:
            summary = (
                f"本次复盘共分析 {total_count} 笔交易，胜率 {win_rate:.1%}，总盈亏 {total_pnl:.2f}。"
                f"当前表现更优的是{best_side_label}，共 {int(best_side[1]['count'])} 笔，累计盈亏 "
                f"{best_side[1]['pnl_sum']:.2f}，平均持有 {best_side[1]['avg_holding_minutes']:.2f} 分钟；"
                f"需要重点优化的是{worst_side_label}，共 {int(worst_side[1]['count'])} 笔，累计盈亏 "
                f"{worst_side[1]['pnl_sum']:.2f}，平均持有 {worst_side[1]['avg_holding_minutes']:.2f} 分钟。"
            )
        else:
            summary = (
                f"本次复盘共分析 {total_count} 笔交易，胜率 {win_rate:.1%}，总盈亏 {total_pnl:.2f}。"
                f"当前样本全部为{best_side_label}，共 {int(best_side[1]['count'])} 笔，累计盈亏 "
                f"{best_side[1]['pnl_sum']:.2f}，平均持有 {best_side[1]['avg_holding_minutes']:.2f} 分钟。"
                "下一步建议优先优化入场过滤、止损阈值和持有周期，而不是做方向优劣比较。"
            )
        trade_records = _build_replay_trade_records(records)
        equity_curve = _build_replay_equity_curve(records)
        loss_features = _build_replay_loss_features(
            records=records,
            market=replay_market,
            total_count=total_count,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_win_holding_minutes=avg_win_holding_minutes,
            avg_loss_holding_minutes=avg_loss_holding_minutes,
            worst_side=worst_side,
            worst_side_label=worst_side_label,
            has_side_comparison=has_side_comparison,
        )
        loss_features.extend(_build_replay_daily_context_features(daily_contexts, target="loss"))
        loss_features.extend(_build_replay_minute_context_features(minute_contexts, target="loss"))
        loss_features.extend(_build_replay_fundamental_features(fundamental_contexts, target="loss"))
        profit_features = _build_replay_profit_features(
            records=records,
            market=replay_market,
            total_count=total_count,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_win_holding_minutes=avg_win_holding_minutes,
            best_side=best_side,
            best_side_label=best_side_label,
        )
        profit_features.extend(_build_replay_daily_context_features(daily_contexts, target="profit"))
        profit_features.extend(_build_replay_minute_context_features(minute_contexts, target="profit"))
        profit_features.extend(_build_replay_fundamental_features(fundamental_contexts, target="profit"))
        suggestion_rules.extend(
            _build_replay_context_suggestions(
                loss_features=loss_features,
                profit_features=profit_features,
            )
        )
        parameter_changes = _build_replay_parameter_changes(suggestion_rules)
        condition_replacements = _build_replay_condition_replacements(suggestion_rules)
        objective_versions = _build_replay_objective_versions(
            records=records,
            suggestion_rules=suggestion_rules,
            trade_records=trade_records,
            best_side=best_side,
            worst_side=worst_side,
            has_side_comparison=has_side_comparison,
            avg_loss=avg_loss,
            avg_holding_minutes=avg_holding_minutes,
            avg_loss_holding_minutes=avg_loss_holding_minutes,
            daily_contexts=daily_contexts,
            minute_contexts=minute_contexts,
            fundamental_contexts=fundamental_contexts,
            replay_market=replay_market,
            market_data_service=market_data_service,
        )
        counterfactual_cases = _build_replay_counterfactual_cases(
            records=records,
            replay_market=replay_market,
            market_data_service=market_data_service,
            daily_context_by_trade_id=_group_replay_contexts_by_trade_id(daily_contexts),
            minute_context_by_trade_id=_group_replay_contexts_by_trade_id(minute_contexts),
            fundamental_context_by_trade_id=_group_replay_contexts_by_trade_id(fundamental_contexts),
        )
        counterfactual_template_summary = _build_replay_counterfactual_template_summary(
            counterfactual_cases
        )
        default_version = next((item for item in objective_versions if item.get("is_default")), objective_versions[0] if objective_versions else None)
        counterfactual_template_summary = _link_counterfactual_templates_to_stability(
            counterfactual_template_summary,
            (default_version or {}).get("search_summary", {}).get("parameter_stability") or {},
        )
        concise_summary = _build_replay_concise_summary(
            total_count=total_count,
            win_rate=win_rate,
            total_pnl=total_pnl,
            best_side_label=best_side_label,
            has_side_comparison=has_side_comparison,
            worst_side_label=worst_side_label,
            loss_features=loss_features,
        )
        return {
            "analysis_id": task_id,
            "dataset_snapshot_ref": payload["data_snapshot"]["dataset_snapshot_ref"],
            "feature_snapshot_ref": f"feature_snapshot_{payload['upload_id']}",
            "analysis_rule_version": "replay_rule_v1",
            "prompt_template_version": settings.replay_prompt_version,
            "summary": summary,
            "concise_summary": concise_summary,
            "overview": {
                "trade_count": total_count,
                "win_rate_pct": round(win_rate * 100.0, 2),
                "total_pnl": round(total_pnl, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "avg_holding_minutes": avg_holding_minutes,
                "default_objective": "sharpe_max",
                "default_objective_label": "夏普最大",
                "market": replay_market,
                "supports_short": replay_supports_short,
                "analysis_scope": analysis_scope,
                "input_truth_summary": _build_trade_input_truth_summary(records),
            },
            "winning_patterns": [
                {
                    "dimension": "side_performance",
                    "pattern": f"{best_side_label}的累计盈亏和整体表现当前更优",
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
                    "pattern": (
                        f"{worst_side_label}当前是主要拖累方向"
                        if has_side_comparison
                        else "当前样本尚未形成可比较的方向差异"
                    ),
                    "support": round(worst_side[1]["count"] / total_count, 2)
                    if total_count
                    else 0.0,
                    "avg_holding_minutes": worst_side[1]["avg_holding_minutes"],
                    "pnl_sum": round(worst_side[1]["pnl_sum"], 2),
                }
            ],
            "loss_features": loss_features,
            "profit_features": profit_features,
            "objective_versions": objective_versions,
            "counterfactual_cases": counterfactual_cases,
            "counterfactual_template_summary": counterfactual_template_summary,
            "parameter_changes": parameter_changes,
            "condition_replacements": condition_replacements,
            "trade_records": trade_records,
            "suggestion_rules": suggestion_rules,
        }

    return _builder


def _build_replay_concise_summary(
    *,
    total_count: int,
    win_rate: float,
    total_pnl: float,
    best_side_label: str,
    has_side_comparison: bool,
    worst_side_label: str,
    loss_features: list[dict[str, Any]],
) -> str:
    feature_summary = loss_features[0]["title"] if loss_features else "当前样本暂未形成明显亏损特征"
    if has_side_comparison:
        return (
            f"这批交易共 {total_count} 笔，胜率 {win_rate:.1%}，总盈亏 {total_pnl:.2f}。"
            f"当前更值得保留的是{best_side_label}，最先要修正的是{worst_side_label}相关出手。"
            f"从样本里最明显的问题看，优先处理“{feature_summary}”。"
        )
    return (
        f"这批交易共 {total_count} 笔，胜率 {win_rate:.1%}，总盈亏 {total_pnl:.2f}。"
        f"当前样本主要还是单方向交易，最优先的动作是先修正“{feature_summary}”，"
        "再决定是否需要扩展更多方向或参数。"
    )


def _build_replay_trade_records(records: list[TradeRecordItem]) -> list[dict[str, Any]]:
    items = sorted(
        records,
        key=lambda item: item.exit_time or item.entry_time,
    )
    trade_rows: list[dict[str, Any]] = []
    for item in items:
        holding_minutes = round(_holding_minutes(item.entry_time, item.exit_time), 2)
        trade_rows.append(
            {
                "trade_id": item.trade_id,
                "symbol": item.symbol,
                "side": item.side,
                "entry_time": item.entry_time.isoformat(),
                "exit_time": item.exit_time.isoformat() if item.exit_time else None,
                "entry_price": item.entry_price,
                "exit_price": item.exit_price,
                "holding_minutes": holding_minutes,
                "holding_label": _format_holding_label(holding_minutes),
                "pnl": round(item.pnl, 2),
                "pnl_pct": _infer_trade_pnl_pct(item),
                "source_kind": item.source_kind,
                "input_confidence": item.input_confidence,
                "provenance_tags": list(item.provenance_tags or []),
                "derived_fields": list(item.derived_fields or []),
                "needs_confirmation": bool(item.needs_confirmation),
                "conflict_flags": list(item.conflict_flags or []),
            }
        )
    return trade_rows


def _build_replay_equity_curve(records: list[TradeRecordItem]) -> list[dict[str, Any]]:
    equity = 0.0
    points: list[dict[str, Any]] = []
    for index, item in enumerate(
        sorted(records, key=lambda row: row.exit_time or row.entry_time),
        start=1,
    ):
        equity += item.pnl
        points.append(
            {
                "index": index,
                "timestamp": (item.exit_time or item.entry_time).isoformat(),
                "symbol": item.symbol,
                "pnl": round(item.pnl, 2),
                "equity": round(equity, 2),
            }
        )
    return points


def _build_replay_sample_metrics(records: list[TradeRecordItem]) -> dict[str, Any]:
    trade_count = len(records)
    total_pnl = sum(item.pnl for item in records)
    wins = [item for item in records if item.pnl > 0]
    losses = [item for item in records if item.pnl <= 0]
    win_rate_pct = (len(wins) / trade_count * 100.0) if trade_count else 0.0
    avg_pnl = (total_pnl / trade_count) if trade_count else 0.0
    pnl_values = [item.pnl for item in records]
    sharpe_like = _build_replay_sharpe_like(pnl_values)
    max_drawdown_pct = _build_replay_max_drawdown_pct(pnl_values)
    return {
        "trade_count": trade_count,
        "total_pnl": round(total_pnl, 2),
        "win_rate_pct": round(win_rate_pct, 2),
        "avg_pnl": round(avg_pnl, 2),
        "profit_count": len(wins),
        "loss_count": len(losses),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_like": round(sharpe_like, 2),
    }


def _build_trade_input_truth_summary(
    records: list[TradeRecordItem],
    *,
    source_context: str | None = None,
) -> dict[str, Any]:
    source_breakdown: dict[str, int] = {}
    confidence_breakdown: dict[str, int] = {}
    derived_field_counts: dict[str, int] = {}
    provenance_tag_counts: dict[str, int] = {}
    conflict_flag_counts: dict[str, int] = {}
    needs_confirmation_count = 0
    for item in records:
        source_kind = item.source_kind or "unknown"
        source_breakdown[source_kind] = source_breakdown.get(source_kind, 0) + 1
        confidence = item.input_confidence or "unknown"
        confidence_breakdown[confidence] = confidence_breakdown.get(confidence, 0) + 1
        if item.needs_confirmation:
            needs_confirmation_count += 1
        for field in item.derived_fields or []:
            derived_field_counts[field] = derived_field_counts.get(field, 0) + 1
        for tag in item.provenance_tags or []:
            provenance_tag_counts[tag] = provenance_tag_counts.get(tag, 0) + 1
        for flag in item.conflict_flags or []:
            conflict_flag_counts[flag] = conflict_flag_counts.get(flag, 0) + 1
    return {
        "record_count": len(records),
        "source_context": source_context or "trade_records",
        "source_breakdown": source_breakdown,
        "confidence_breakdown": confidence_breakdown,
        "needs_confirmation_count": needs_confirmation_count,
        "derived_field_counts": derived_field_counts,
        "provenance_tag_counts": provenance_tag_counts,
        "conflict_flag_counts": conflict_flag_counts,
        "summary": (
            f"共 {len(records)} 笔记录，其中需要人工确认 {needs_confirmation_count} 笔。"
            "平台会区分用户提供字段、系统补价字段和待确认冲突项。"
        ),
    }


def _build_replay_trade_set_changes(
    *,
    baseline_records: list[TradeRecordItem],
    selected_records: list[TradeRecordItem],
    selected_trade_rows: list[dict[str, Any]],
    simulation_mode: str,
) -> dict[str, Any]:
    baseline_rows = _build_replay_trade_records(baseline_records)
    baseline_by_trade_id = {item["trade_id"]: item for item in baseline_rows}
    selected_trade_ids = {
        item.trade_id for item in selected_records if getattr(item, "trade_id", None)
    } or {item.get("trade_id") for item in selected_trade_rows if item.get("trade_id")}

    removed_rows = [
        row for trade_id, row in baseline_by_trade_id.items() if trade_id not in selected_trade_ids
    ]
    removed_losses = sorted(
        [row for row in removed_rows if float(row.get("pnl") or 0) <= 0],
        key=lambda row: float(row.get("pnl") or 0),
    )
    removed_profits = sorted(
        [row for row in removed_rows if float(row.get("pnl") or 0) > 0],
        key=lambda row: float(row.get("pnl") or 0),
        reverse=True,
    )
    limitations = [
        "当前版本基于已发生成交样本的筛选与真实重放，只能识别被过滤掉的交易。",
        "当前链路还不能可靠推导“新规则本来会新增哪些未发生交易”。",
    ]
    return {
        "baseline_trade_count": len(baseline_rows),
        "current_trade_count": len(selected_trade_rows),
        "unchanged_trade_count": len(selected_trade_ids),
        "trade_frequency_delta": len(selected_trade_rows) - len(baseline_rows),
        "removed_loss_count": len(removed_losses),
        "removed_profit_count": len(removed_profits),
        "removed_losses": removed_losses[:5],
        "removed_profits": removed_profits[:5],
        "added_trades_supported": False,
        "added_trades": [],
        "style_exposure": {
            "baseline_avg_holding_minutes": _average_replay_trade_row_holding_minutes(baseline_rows),
            "current_avg_holding_minutes": _average_replay_trade_row_holding_minutes(selected_trade_rows),
            "baseline_long_share_pct": _replay_trade_row_side_share_pct(baseline_rows, side="long"),
            "current_long_share_pct": _replay_trade_row_side_share_pct(selected_trade_rows, side="long"),
            "baseline_top_symbols": _build_replay_symbol_exposure(baseline_rows),
            "current_top_symbols": _build_replay_symbol_exposure(selected_trade_rows),
            "baseline_top_pnl_symbols": _build_replay_symbol_pnl_exposure(baseline_rows),
            "current_top_pnl_symbols": _build_replay_symbol_pnl_exposure(selected_trade_rows),
        },
        "summary": (
            f"本版本当前保留 {len(selected_trade_rows)} 笔交易，较原样本变化 "
            f"{len(selected_trade_rows) - len(baseline_rows):+d} 笔。"
            f"被过滤掉的交易里，亏损单 {len(removed_losses)} 笔，盈利单 {len(removed_profits)} 笔。"
        ),
        "simulation_mode": simulation_mode,
        "limitations": limitations,
    }


def _average_replay_trade_row_holding_minutes(trade_rows: list[dict[str, Any]]) -> float:
    if not trade_rows:
        return 0.0
    return round(
        sum(float(item.get("holding_minutes") or 0.0) for item in trade_rows) / len(trade_rows),
        2,
    )


def _replay_trade_row_side_share_pct(trade_rows: list[dict[str, Any]], *, side: str) -> float:
    if not trade_rows:
        return 0.0
    side_count = sum(1 for item in trade_rows if item.get("side") == side)
    return round((side_count / len(trade_rows)) * 100.0, 2)


def _build_replay_symbol_exposure(trade_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in trade_rows:
        symbol = str(item.get("symbol") or "")
        if not symbol:
            continue
        counts[symbol] = counts.get(symbol, 0) + 1
    total = len(trade_rows)
    items = [
        {
            "symbol": symbol,
            "count": count,
            "share_pct": round((count / total) * 100.0, 2) if total else 0.0,
        }
        for symbol, count in counts.items()
    ]
    items.sort(key=lambda item: (int(item["count"]), float(item["share_pct"])), reverse=True)
    return items[:5]


def _build_replay_symbol_pnl_exposure(trade_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    for item in trade_rows:
        symbol = str(item.get("symbol") or "")
        if not symbol:
            continue
        totals[symbol] = totals.get(symbol, 0.0) + float(item.get("pnl") or 0.0)
    items = [
        {"symbol": symbol, "total_pnl": round(total_pnl, 2)}
        for symbol, total_pnl in totals.items()
    ]
    items.sort(key=lambda item: abs(float(item["total_pnl"])), reverse=True)
    return items[:5]


def _build_replay_sharpe_like(pnl_values: list[float]) -> float:
    if len(pnl_values) < 2:
        return 0.0
    mean_value = sum(pnl_values) / len(pnl_values)
    variance = sum((value - mean_value) ** 2 for value in pnl_values) / (len(pnl_values) - 1)
    if variance <= 0:
        return 0.0
    return (mean_value / math.sqrt(variance)) * math.sqrt(len(pnl_values))


def _build_replay_max_drawdown_pct(pnl_values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown_pct = 0.0
    for pnl in pnl_values:
        equity += pnl
        peak = max(peak, equity)
        if peak <= 0:
            continue
        drawdown_pct = ((equity - peak) / peak) * 100.0
        max_drawdown_pct = min(max_drawdown_pct, drawdown_pct)
    return abs(max_drawdown_pct)


def _normalize_replay_analysis_options(options: dict[str, Any]) -> dict[str, Any]:
    lookback_days = int(options.get("lookback_days", 5) or 5)
    minute_window_minutes = int(options.get("minute_window_minutes", 60) or 60)
    return {
        "lookback_days": min(max(lookback_days, 1), 20),
        "minute_window_minutes": min(max(minute_window_minutes, 15), 240),
        "include_minute_features": bool(options.get("include_minute_features", False)),
        "include_fundamentals": bool(options.get("include_fundamentals", False)),
        "include_market_context": bool(options.get("include_market_context", True)),
        "auto_market_context": bool(options.get("auto_market_context", True)),
    }


def _build_replay_daily_contexts(
    *,
    records: list[TradeRecordItem],
    replay_market: str,
    analysis_options: dict[str, Any],
    market_data_service: MarketDataService | None,
) -> list[dict[str, Any]]:
    if market_data_service is None or replay_market != "cn_a_share":
        return []
    lookback_days = int(analysis_options["lookback_days"])
    contexts: list[dict[str, Any]] = []
    bars_by_symbol: dict[str, list[Any]] = {}
    record_dates = [item.entry_time.date() for item in records]
    if not record_dates:
        return []
    start_date = min(record_dates) - timedelta(days=lookback_days + 10)
    end_date = max(record_dates) + timedelta(days=5)
    for symbol in {item.symbol for item in records if item.symbol.endswith((".SH", ".SZ", ".BJ"))}:
        try:
            bars, data_source = market_data_service.load_daily_bars(
                ts_code=symbol,
                start_date=start_date,
                end_date=end_date,
                adjustment_mode="qfq",
            )
        except Exception:
            continue
        if data_source.get("provider") in {None, "demo"}:
            continue
        bars_by_symbol[symbol] = bars

    for item in records:
        bars = bars_by_symbol.get(item.symbol)
        if not bars:
            continue
        entry_date = item.entry_time.date()
        entry_index = next(
            (index for index, bar in enumerate(bars) if date.fromisoformat(bar.trade_date) >= entry_date),
            None,
        )
        if entry_index is None:
            continue
        prior_bars = bars[max(0, entry_index - lookback_days):entry_index]
        if len(prior_bars) < 3:
            continue
        ma_bars = bars[max(0, entry_index - 5):entry_index]
        if not ma_bars:
            continue
        entry_bar = bars[entry_index]
        start_bar = prior_bars[0]
        avg_volume = sum(float(bar.volume or 0.0) for bar in prior_bars) / len(prior_bars)
        ma5 = sum(float(bar.close) for bar in ma_bars) / len(ma_bars)
        prior_return_pct = (
            ((float(entry_bar.close) - float(start_bar.close)) / float(start_bar.close)) * 100.0
            if float(start_bar.close) != 0
            else 0.0
        )
        volume_ratio = (float(entry_bar.volume or 0.0) / avg_volume) if avg_volume else None
        trend_regime = "trend" if float(entry_bar.close) >= ma5 and prior_return_pct >= 0 else "range"
        contexts.append(
            {
                "trade_id": item.trade_id,
                "symbol": item.symbol,
                "pnl": item.pnl,
                "prior_return_pct": round(prior_return_pct, 2),
                "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
                "above_ma5": float(entry_bar.close) >= ma5,
                "trend_regime": trend_regime,
            }
        )
    return contexts


def _build_replay_minute_contexts(
    *,
    records: list[TradeRecordItem],
    replay_market: str,
    analysis_options: dict[str, Any],
    market_data_service: MarketDataService | None,
) -> tuple[list[dict[str, Any]], str]:
    if not analysis_options["include_minute_features"]:
        return [], "disabled"
    if market_data_service is None or replay_market != "cn_a_share":
        return [], "unavailable"

    contexts: list[dict[str, Any]] = []
    for item in records:
        if not item.symbol.endswith((".SH", ".SZ", ".BJ")):
            continue
        entry_time = _to_market_local_datetime(item.entry_time, replay_market)
        start_time = entry_time - timedelta(minutes=int(analysis_options["minute_window_minutes"]))
        bars, metadata = market_data_service.load_minute_window(
            ts_code=item.symbol,
            start_time=start_time,
            end_time=entry_time,
            adjustment_mode="qfq",
        )
        if metadata.get("status") != "ready" or not bars:
            continue
        first_bar = bars[0]
        last_bar = bars[-1]
        open_price = float(first_bar.open)
        close_price = float(last_bar.close)
        if open_price == 0:
            continue
        high_price = max(float(bar.high) for bar in bars)
        low_price = min(float(bar.low) for bar in bars)
        up_bar_ratio = sum(1 for bar in bars if float(bar.close) >= float(bar.open)) / len(bars)
        first_segment = bars[: min(len(bars), 15)]
        last_segment = bars[max(0, len(bars) - 15):]
        first_open = float(first_segment[0].open)
        first_close = float(first_segment[-1].close)
        last_open = float(last_segment[0].open)
        last_close = float(last_segment[-1].close)
        minute_return_pct = ((close_price - open_price) / open_price) * 100.0
        volatility_pct = ((high_price - low_price) / open_price) * 100.0
        peak_to_close_drawdown_pct = ((close_price - high_price) / high_price) * 100.0 if high_price else 0.0
        first_15m_return_pct = ((first_close - first_open) / first_open) * 100.0 if first_open else 0.0
        last_15m_return_pct = ((last_close - last_open) / last_open) * 100.0 if last_open else 0.0
        close_position_pct = ((close_price - low_price) / (high_price - low_price) * 100.0) if high_price > low_price else 50.0
        contexts.append(
            {
                "trade_id": item.trade_id,
                "symbol": item.symbol,
                "pnl": item.pnl,
                "minute_return_pct": round(minute_return_pct, 2),
                "volatility_pct": round(volatility_pct, 2),
                "peak_to_close_drawdown_pct": round(abs(peak_to_close_drawdown_pct), 2),
                "up_bar_ratio": round(up_bar_ratio, 2),
                "first_15m_return_pct": round(first_15m_return_pct, 2),
                "last_15m_return_pct": round(last_15m_return_pct, 2),
                "close_position_pct": round(close_position_pct, 2),
            }
        )
    return contexts, ("ready" if contexts else "unavailable")


def _build_replay_fundamental_contexts(
    *,
    records: list[TradeRecordItem],
    replay_market: str,
    analysis_options: dict[str, Any],
    market_data_service: MarketDataService | None,
) -> tuple[list[dict[str, Any]], str]:
    if not analysis_options["include_fundamentals"]:
        return [], "disabled"
    if market_data_service is None or replay_market != "cn_a_share":
        return [], "unavailable"

    contexts: list[dict[str, Any]] = []
    for item in records:
        if not item.symbol.endswith((".SH", ".SZ", ".BJ")):
            continue
        snapshot, metadata = market_data_service.load_daily_basic_snapshot(
            ts_code=item.symbol,
            trade_date=item.entry_time.date(),
        )
        financial_snapshot, financial_metadata = market_data_service.load_financial_quality_snapshot(
            ts_code=item.symbol,
            trade_date=item.entry_time.date(),
        )
        if metadata.get("status") != "ready" or snapshot is None:
            continue
        if financial_metadata.get("status") != "ready" or financial_snapshot is None:
            continue
        debt_to_assets = None
        if financial_snapshot.total_assets and financial_snapshot.total_assets > 0 and financial_snapshot.total_liab is not None:
            debt_to_assets = (financial_snapshot.total_liab / financial_snapshot.total_assets) * 100.0
        contexts.append(
            {
                "trade_id": item.trade_id,
                "symbol": item.symbol,
                "pnl": item.pnl,
                "pe_ttm": snapshot.pe_ttm,
                "pb": snapshot.pb,
                "turnover_rate": snapshot.turnover_rate,
                "total_mv": snapshot.total_mv,
                "roe": financial_snapshot.roe,
                "grossprofit_margin": financial_snapshot.grossprofit_margin,
                "op_yoy": financial_snapshot.op_yoy,
                "debt_to_assets": round(debt_to_assets, 2) if debt_to_assets is not None else None,
            }
        )
    return contexts, ("ready" if contexts else "unavailable")


def _build_replay_analysis_scope(
    *,
    replay_market: str,
    focus_dimensions: list[str],
    analysis_options: dict[str, Any],
    daily_contexts: list[dict[str, Any]],
    minute_contexts: list[dict[str, Any]],
    fundamental_contexts: list[dict[str, Any]],
    minute_status: str,
    fundamental_status: str,
) -> dict[str, Any]:
    labels = ["方向表现", "持有时间"]
    if any(item in {"volume_structure", "volume_profile"} for item in focus_dimensions):
        labels.append("量价结构")
    if any(item in {"moving_average_structure", "trend_structure"} for item in focus_dimensions):
        labels.append("均线位置")
    if analysis_options["include_market_context"]:
        labels.append("市场环境")
    if analysis_options["include_minute_features"]:
        labels.append("分钟级特征")
    if analysis_options["include_fundamentals"]:
        labels.append("基本面")
    return {
        "lookback_days": analysis_options["lookback_days"],
        "minute_window_minutes": analysis_options["minute_window_minutes"],
        "include_market_context": analysis_options["include_market_context"],
        "auto_market_context": analysis_options["auto_market_context"],
        "include_minute_features": analysis_options["include_minute_features"],
        "include_fundamentals": analysis_options["include_fundamentals"],
        "labels": labels,
        "daily_context_status": "ready" if daily_contexts else "unavailable",
        "minute_feature_status": minute_status,
        "fundamental_status": fundamental_status,
        "minute_context_count": len(minute_contexts),
        "fundamental_context_count": len(fundamental_contexts),
        "market": replay_market,
    }


def _build_replay_daily_context_features(
    contexts: list[dict[str, Any]],
    *,
    target: str,
) -> list[dict[str, Any]]:
    if not contexts:
        return []
    wins = [item for item in contexts if item["pnl"] > 0]
    losses = [item for item in contexts if item["pnl"] <= 0]
    if not wins or not losses:
        return []

    features: list[dict[str, Any]] = []
    win_avg_volume_ratio = _avg_optional_number(wins, "volume_ratio")
    loss_avg_volume_ratio = _avg_optional_number(losses, "volume_ratio")
    win_avg_prior_return = _avg_optional_number(wins, "prior_return_pct")
    loss_avg_prior_return = _avg_optional_number(losses, "prior_return_pct")
    win_above_ma_rate = sum(1 for item in wins if item["above_ma5"]) / len(wins)
    loss_above_ma_rate = sum(1 for item in losses if item["above_ma5"]) / len(losses)
    win_trend_rate = sum(1 for item in wins if item["trend_regime"] == "trend") / len(wins)
    loss_range_rate = sum(1 for item in losses if item["trend_regime"] == "range") / len(losses)

    if target == "loss":
        if loss_avg_volume_ratio is not None and win_avg_volume_ratio is not None and loss_avg_volume_ratio > win_avg_volume_ratio + 0.3:
            features.append(
                {
                    "id": "loss_volume_chase",
                    "title": "亏损样本更常出现在放量追入时",
                    "detail": (
                        f"亏损单入场日平均量比 {loss_avg_volume_ratio:.2f}，高于盈利单的 {win_avg_volume_ratio:.2f}。"
                        "说明追高式入场需要更强过滤。"
                    ),
                    "support": round(loss_avg_volume_ratio / max(loss_avg_volume_ratio + win_avg_volume_ratio, 0.01), 2),
                }
            )
        if loss_avg_prior_return is not None and win_avg_prior_return is not None and loss_avg_prior_return > win_avg_prior_return + 2:
            features.append(
                {
                    "id": "loss_after_extended_move",
                    "title": "亏损样本更常出现在短期涨幅过大后入场",
                    "detail": (
                        f"亏损单入场前窗口平均涨幅 {loss_avg_prior_return:.2f}%，明显高于盈利单的 {win_avg_prior_return:.2f}%。"
                    ),
                    "support": round(loss_range_rate, 2),
                }
            )
        if loss_range_rate >= 0.5:
            features.append(
                {
                    "id": "loss_range_regime",
                    "title": "震荡环境里更容易出现亏损样本",
                    "detail": f"当前亏损样本里有 {round(loss_range_rate * 100)}% 出现在震荡环境，后续应强化环境过滤。",
                    "support": round(loss_range_rate, 2),
                }
            )
        return features[:3]

    if win_above_ma_rate > loss_above_ma_rate:
        features.append(
            {
                "id": "profit_above_ma5",
                "title": "盈利样本更常在站上5日线时出现",
                "detail": (
                    f"盈利单入场时站上 5 日线的比例为 {round(win_above_ma_rate * 100)}%，"
                    f"高于亏损单的 {round(loss_above_ma_rate * 100)}%。"
                ),
                "support": round(win_above_ma_rate, 2),
            }
        )
    if win_trend_rate >= 0.5:
        features.append(
            {
                "id": "profit_trend_regime",
                "title": "趋势环境下更容易保留盈利结构",
                "detail": f"当前盈利样本里有 {round(win_trend_rate * 100)}% 出现在趋势环境，可作为后续开仓过滤参考。",
                "support": round(win_trend_rate, 2),
            }
        )
    if win_avg_volume_ratio is not None and loss_avg_volume_ratio is not None and win_avg_volume_ratio <= loss_avg_volume_ratio:
        features.append(
            {
                "id": "profit_not_overheated",
                "title": "盈利样本的量能更偏健康而非过热",
                "detail": (
                    f"盈利单平均量比 {win_avg_volume_ratio:.2f}，没有高于亏损单的 {loss_avg_volume_ratio:.2f}。"
                    "更适合保留量能健康而非过热的入场。"
                ),
                "support": round(win_trend_rate, 2),
            }
        )
    return features[:3]


def _build_replay_minute_context_features(
    contexts: list[dict[str, Any]],
    *,
    target: str,
) -> list[dict[str, Any]]:
    if not contexts:
        return []
    wins = [item for item in contexts if item["pnl"] > 0]
    losses = [item for item in contexts if item["pnl"] <= 0]
    if not wins or not losses:
        return []
    win_avg_return = _avg_optional_number(wins, "minute_return_pct")
    loss_avg_return = _avg_optional_number(losses, "minute_return_pct")
    win_avg_drawdown = _avg_optional_number(wins, "peak_to_close_drawdown_pct")
    loss_avg_drawdown = _avg_optional_number(losses, "peak_to_close_drawdown_pct")
    win_up_ratio = _avg_optional_number(wins, "up_bar_ratio")
    loss_up_ratio = _avg_optional_number(losses, "up_bar_ratio")
    win_first_15m = _avg_optional_number(wins, "first_15m_return_pct")
    loss_first_15m = _avg_optional_number(losses, "first_15m_return_pct")
    win_last_15m = _avg_optional_number(wins, "last_15m_return_pct")
    loss_last_15m = _avg_optional_number(losses, "last_15m_return_pct")
    win_close_position = _avg_optional_number(wins, "close_position_pct")
    loss_close_position = _avg_optional_number(losses, "close_position_pct")
    features: list[dict[str, Any]] = []
    if target == "loss":
        if loss_avg_return is not None and win_avg_return is not None and loss_avg_return > win_avg_return:
            features.append(
                {
                    "id": "loss_intraday_chase",
                    "title": "亏损样本更常出现在盘中短时拉升后追入",
                    "detail": (
                        f"亏损单入场前分钟窗口平均涨幅 {loss_avg_return:.2f}%，高于盈利单的 {win_avg_return:.2f}%。"
                    ),
                    "support": 1.0,
                }
            )
        if loss_avg_drawdown is not None and win_avg_drawdown is not None and loss_avg_drawdown > win_avg_drawdown:
            features.append(
                {
                    "id": "loss_intraday_pullback",
                    "title": "亏损样本更常伴随盘中回落加剧",
                    "detail": (
                        f"亏损单分钟窗口峰值回落 {loss_avg_drawdown:.2f}%，高于盈利单的 {win_avg_drawdown:.2f}%。"
                    ),
                    "support": 1.0,
                }
            )
        if loss_first_15m is not None and win_first_15m is not None and loss_first_15m > win_first_15m:
            features.append(
                {
                    "id": "loss_first_15m_hot",
                    "title": "亏损样本更常在开盘前15分钟过热后入场",
                    "detail": (
                        f"亏损单前15分钟平均涨幅 {loss_first_15m:.2f}%，高于盈利单的 {win_first_15m:.2f}%。"
                    ),
                    "support": 1.0,
                }
            )
        if loss_close_position is not None and win_close_position is not None and loss_close_position < win_close_position:
            features.append(
                {
                    "id": "loss_close_weak",
                    "title": "亏损样本更常在分钟窗口末端收在区间偏弱位置",
                    "detail": (
                        f"亏损单窗口收盘位置 {loss_close_position:.2f}%，低于盈利单的 {win_close_position:.2f}%。"
                    ),
                    "support": 1.0,
                }
            )
        if loss_up_ratio is not None and win_up_ratio is not None and loss_up_ratio < win_up_ratio:
            features.append(
                {
                    "id": "loss_bar_structure_weak",
                    "title": "亏损样本的盘中阳线占比更低",
                    "detail": (
                        f"亏损单窗口阳线占比 {loss_up_ratio:.2f}，低于盈利单的 {win_up_ratio:.2f}。"
                    ),
                    "support": 1.0,
                }
            )
        return features[:2]
    if win_avg_return is not None and loss_avg_return is not None and win_avg_return <= loss_avg_return:
        features.append(
            {
                "id": "profit_intraday_not_overheated",
                "title": "盈利样本更适合在盘中结构不过热时入场",
                "detail": (
                    f"盈利单分钟窗口平均涨幅 {win_avg_return:.2f}%，没有高于亏损单的 {loss_avg_return:.2f}%。"
                ),
                "support": 1.0,
            }
        )
    if win_avg_drawdown is not None and loss_avg_drawdown is not None and win_avg_drawdown < loss_avg_drawdown:
        features.append(
            {
                "id": "profit_intraday_stable",
                "title": "盈利样本更常出现在盘中结构更平稳时",
                "detail": (
                    f"盈利单分钟窗口峰值回落 {win_avg_drawdown:.2f}%，低于亏损单的 {loss_avg_drawdown:.2f}%。"
                ),
                "support": 1.0,
            }
        )
    if win_last_15m is not None and loss_last_15m is not None and win_last_15m >= loss_last_15m:
        features.append(
            {
                "id": "profit_last_15m_stable",
                "title": "盈利样本更常在窗口末端保持稳定而不是快速回吐",
                "detail": (
                    f"盈利单末15分钟平均变动 {win_last_15m:.2f}%，优于亏损单的 {loss_last_15m:.2f}%。"
                ),
                "support": 1.0,
            }
        )
    return features[:3]


def _build_replay_fundamental_features(
    contexts: list[dict[str, Any]],
    *,
    target: str,
) -> list[dict[str, Any]]:
    if not contexts:
        return []
    wins = [item for item in contexts if item["pnl"] > 0]
    losses = [item for item in contexts if item["pnl"] <= 0]
    if not wins or not losses:
        return []
    win_avg_pe = _avg_optional_number(wins, "pe_ttm")
    loss_avg_pe = _avg_optional_number(losses, "pe_ttm")
    win_avg_pb = _avg_optional_number(wins, "pb")
    loss_avg_pb = _avg_optional_number(losses, "pb")
    win_avg_turnover = _avg_optional_number(wins, "turnover_rate")
    loss_avg_turnover = _avg_optional_number(losses, "turnover_rate")
    win_avg_roe = _avg_optional_number(wins, "roe")
    loss_avg_roe = _avg_optional_number(losses, "roe")
    win_avg_margin = _avg_optional_number(wins, "grossprofit_margin")
    loss_avg_margin = _avg_optional_number(losses, "grossprofit_margin")
    win_avg_growth = _avg_optional_number(wins, "op_yoy")
    loss_avg_growth = _avg_optional_number(losses, "op_yoy")
    win_avg_debt = _avg_optional_number(wins, "debt_to_assets")
    loss_avg_debt = _avg_optional_number(losses, "debt_to_assets")
    features: list[dict[str, Any]] = []
    if target == "loss":
        if loss_avg_pe is not None and win_avg_pe is not None and loss_avg_pe > win_avg_pe:
            features.append(
                {
                    "id": "loss_high_pe",
                    "title": "亏损样本更常集中在高估值区间",
                    "detail": f"亏损单平均 PE(TTM) {loss_avg_pe:.2f}，高于盈利单的 {win_avg_pe:.2f}。",
                    "support": 1.0,
                }
            )
        if loss_avg_turnover is not None and win_avg_turnover is not None and loss_avg_turnover > win_avg_turnover:
            features.append(
                {
                    "id": "loss_high_turnover",
                    "title": "亏损样本更常出现在高换手环境",
                    "detail": f"亏损单平均换手率 {loss_avg_turnover:.2f}，高于盈利单的 {win_avg_turnover:.2f}。",
                    "support": 1.0,
                }
            )
        if loss_avg_debt is not None and win_avg_debt is not None and loss_avg_debt > win_avg_debt:
            features.append(
                {
                    "id": "loss_higher_debt",
                    "title": "亏损样本更常集中在资产负债率更高的标的",
                    "detail": f"亏损单平均资产负债率 {loss_avg_debt:.2f}%，高于盈利单的 {win_avg_debt:.2f}%。",
                    "support": 1.0,
                }
            )
        return features[:3]
    if win_avg_pb is not None and loss_avg_pb is not None and win_avg_pb <= loss_avg_pb:
        features.append(
            {
                "id": "profit_lower_pb",
                "title": "盈利样本更常分布在相对更低 PB 区间",
                "detail": f"盈利单平均 PB {win_avg_pb:.2f}，低于亏损单的 {loss_avg_pb:.2f}。",
                "support": 1.0,
            }
        )
    if win_avg_turnover is not None and loss_avg_turnover is not None and win_avg_turnover <= loss_avg_turnover:
        features.append(
            {
                "id": "profit_turnover_healthier",
                "title": "盈利样本更常出现在换手更健康的区间",
                "detail": f"盈利单平均换手率 {win_avg_turnover:.2f}，没有高于亏损单的 {loss_avg_turnover:.2f}。",
                "support": 1.0,
            }
        )
    if win_avg_roe is not None and loss_avg_roe is not None and win_avg_roe >= loss_avg_roe:
        features.append(
            {
                "id": "profit_higher_roe",
                "title": "盈利样本更常分布在 ROE 更高的标的",
                "detail": f"盈利单平均 ROE {win_avg_roe:.2f}%，高于亏损单的 {loss_avg_roe:.2f}%。",
                "support": 1.0,
            }
        )
    if win_avg_margin is not None and loss_avg_margin is not None and win_avg_margin >= loss_avg_margin:
        features.append(
            {
                "id": "profit_higher_margin",
                "title": "盈利样本更常分布在毛利率更高的标的",
                "detail": f"盈利单平均毛利率 {win_avg_margin:.2f}%，高于亏损单的 {loss_avg_margin:.2f}%。",
                "support": 1.0,
            }
        )
    if win_avg_growth is not None and loss_avg_growth is not None and win_avg_growth >= loss_avg_growth:
        features.append(
            {
                "id": "profit_higher_growth",
                "title": "盈利样本更常分布在营收增速更强的标的",
                "detail": f"盈利单平均营收增速 {win_avg_growth:.2f}%，高于亏损单的 {loss_avg_growth:.2f}%。",
                "support": 1.0,
            }
        )
    return features[:5]


def _avg_optional_number(items: list[dict[str, Any]], key: str) -> float | None:
    values = [float(item[key]) for item in items if isinstance(item.get(key), (int, float))]
    if not values:
        return None
    return sum(values) / len(values)


def _to_market_local_datetime(value: datetime, market: str) -> datetime:
    if value.tzinfo is None:
        return value
    if market == "cn_a_share":
        return value.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _build_replay_loss_features(
    *,
    records: list[TradeRecordItem],
    market: str,
    total_count: int,
    avg_win: float,
    avg_loss: float,
    avg_win_holding_minutes: float,
    avg_loss_holding_minutes: float,
    worst_side: tuple[str, dict[str, float]],
    worst_side_label: str,
    has_side_comparison: bool,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    if has_side_comparison and worst_side[1]["count"] > 0 and worst_side[1]["pnl_sum"] < 0:
        features.append(
            {
                "id": "weak_side_drag",
                "title": f"{worst_side_label}是当前主要拖累方向",
                "detail": (
                    f"{worst_side_label}共 {int(worst_side[1]['count'])} 笔，累计盈亏 "
                    f"{worst_side[1]['pnl_sum']:.2f}。"
                ),
                "support": round(worst_side[1]["count"] / total_count, 2) if total_count else 0.0,
            }
        )
    if avg_loss < 0 and abs(avg_loss) > avg_win:
        features.append(
            {
                "id": "loss_bigger_than_win",
                "title": "平均亏损明显大于平均盈利",
                "detail": (
                    f"当前平均盈利 {avg_win:.2f}，平均亏损 {avg_loss:.2f}。"
                    "说明止损和持有周期需要优先收紧。"
                ),
                "support": 1.0,
            }
        )
    if avg_loss_holding_minutes > avg_win_holding_minutes and avg_loss_holding_minutes > 0:
        features.append(
            {
                "id": "loss_hold_too_long",
                "title": "亏损单平均持有时间更长",
                "detail": (
                    f"亏损单平均持有 {avg_loss_holding_minutes:.2f} 分钟，"
                    f"高于盈利单的 {avg_win_holding_minutes:.2f} 分钟。"
                ),
                "support": 1.0,
            }
        )
    if market == "cn_a_share":
        features.append(
            {
                "id": "cn_equity_trend_filter",
                "title": "A股样本优先检查趋势和量能过滤",
                "detail": "A股现货更容易在弱趋势和缩量环境里反复试错，复盘时应优先看趋势确认和量比过滤。",
                "support": 1.0,
            }
        )
    if not features:
        features.append(
            {
                "id": "no_clear_loss_pattern",
                "title": "当前样本尚未形成强亏损共性",
                "detail": "建议继续积累样本，至少补到 20 笔同类交易后再做强结论。",
                "support": 0.0,
            }
        )
    return features[:5]


def _build_replay_profit_features(
    *,
    records: list[TradeRecordItem],
    market: str,
    total_count: int,
    avg_win: float,
    avg_loss: float,
    avg_win_holding_minutes: float,
    best_side: tuple[str, dict[str, float]],
    best_side_label: str,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    if best_side[1]["count"] > 0 and best_side[1]["pnl_sum"] > 0:
        features.append(
            {
                "id": "best_side_positive",
                "title": f"{best_side_label}当前样本表现更稳",
                "detail": (
                    f"{best_side_label}共 {int(best_side[1]['count'])} 笔，累计盈亏 "
                    f"{best_side[1]['pnl_sum']:.2f}。"
                ),
                "support": round(best_side[1]["count"] / total_count, 2) if total_count else 0.0,
            }
        )
    if avg_win > 0:
        features.append(
            {
                "id": "positive_avg_win",
                "title": "样本里已经存在可保留的盈利结构",
                "detail": (
                    f"平均盈利 {avg_win:.2f}，说明当前规则里并非没有有效信号，"
                    "关键是保留有效部分并过滤差的出手。"
                ),
                "support": 1.0,
            }
        )
    if avg_win_holding_minutes > 0:
        features.append(
            {
                "id": "win_hold_window",
                "title": "盈利单已表现出可参考的持有节奏",
                "detail": f"盈利单平均持有 {avg_win_holding_minutes:.2f} 分钟，可作为后续持仓优化参考。",
                "support": 1.0,
            }
        )
    if market == "cn_a_share":
        features.append(
            {
                "id": "cn_equity_quality_filter",
                "title": "A股样本里更适合保留趋势同向和量能健康的出手",
                "detail": "后续优先把趋势确认、量比过滤和弱开过滤沉淀成稳定规则。",
                "support": 1.0,
            }
        )
    return features[:5]


def _build_replay_objective_versions(
    *,
    records: list[TradeRecordItem],
    suggestion_rules: list[dict[str, Any]],
    trade_records: list[dict[str, Any]],
    best_side: tuple[str, dict[str, float]],
    worst_side: tuple[str, dict[str, float]],
    has_side_comparison: bool,
    avg_loss: float,
    avg_holding_minutes: float,
    avg_loss_holding_minutes: float,
    daily_contexts: list[dict[str, Any]],
    minute_contexts: list[dict[str, Any]],
    fundamental_contexts: list[dict[str, Any]],
    replay_market: str,
    market_data_service: MarketDataService | None,
) -> list[dict[str, Any]]:
    suggestion_titles = [item.get("title", "") for item in suggestion_rules if item.get("title")]
    baseline_metrics = _build_replay_sample_metrics(records)
    daily_context_by_trade_id = _group_replay_contexts_by_trade_id(daily_contexts)
    minute_context_by_trade_id = _group_replay_contexts_by_trade_id(minute_contexts)
    fundamental_context_by_trade_id = _group_replay_contexts_by_trade_id(fundamental_contexts)
    objective_specs = [
        {
            "objective": "sharpe_max",
            "label": "夏普最大",
            "is_default": True,
            "summary": "默认主推荐版本，更重视收益质量、稳定性和回撤控制。",
            "key_adjustments": suggestion_titles[:2] or ["优先收缩弱势方向并加强开仓过滤"],
        },
        {
            "objective": "win_rate_max",
            "label": "胜率最大",
            "is_default": False,
            "summary": "更重视减少无效出手和降低试错频率。",
            "key_adjustments": suggestion_titles[:2] or ["优先减少低质量开仓"],
        },
        {
            "objective": "max_drawdown_min",
            "label": "回撤最低",
            "is_default": False,
            "summary": "更重视控制亏损扩大和缩短错误持有。",
            "key_adjustments": suggestion_titles[1:3] or ["优先收紧止损和持有周期"],
        },
        {
            "objective": "total_return_max",
            "label": "收益最大",
            "is_default": False,
            "summary": "更重视保留高收益信号，但需接受更高波动。",
            "key_adjustments": suggestion_titles[-2:] or ["优先保留已有优势信号并放宽过强过滤"],
        },
    ]
    items: list[dict[str, Any]] = []
    for spec in objective_specs:
        selected_records, comparison_note = _select_replay_objective_records(
            records=records,
            objective=spec["objective"],
            best_side=best_side,
            worst_side=worst_side,
            has_side_comparison=has_side_comparison,
            avg_loss=avg_loss,
            avg_holding_minutes=avg_holding_minutes,
            avg_loss_holding_minutes=avg_loss_holding_minutes,
            daily_context_by_trade_id=daily_context_by_trade_id,
            minute_context_by_trade_id=minute_context_by_trade_id,
            fundamental_context_by_trade_id=fundamental_context_by_trade_id,
        )
        rerun_result = _rerun_replay_records_on_market_data(
            records=selected_records,
            replay_market=replay_market,
            objective=spec["objective"],
            market_data_service=market_data_service,
            suggestion_rules=suggestion_rules,
            daily_context_by_trade_id=daily_context_by_trade_id,
            minute_context_by_trade_id=minute_context_by_trade_id,
            fundamental_context_by_trade_id=fundamental_context_by_trade_id,
        )
        if rerun_result is not None:
            selected_trade_rows = rerun_result["trade_records"]
            version_metrics = rerun_result["metrics"]
            version_equity_curve = rerun_result["equity_curve"]
            selected_patch = rerun_result["selected_patch"]
            search_summary = rerun_result["search_summary"]
            comparison_note = (
                f"{comparison_note} 当前版本已基于真实日线行情重放生成结果。"
            )
            simulation_mode = "market_rerun_optimized"
        else:
            selected_trade_rows = _build_replay_trade_records(selected_records)
            version_metrics = _build_replay_sample_metrics(selected_records)
            version_equity_curve = _build_replay_equity_curve(selected_records)
            selected_patch = _merge_replay_rule_patches(
                suggestion_rules=suggestion_rules,
                objective=spec["objective"],
            )
            search_summary = {
                "mode": "fallback",
                "evaluated_variants": 0,
                "selected_reason": "当前无真实行情重放，保留样本筛选回放结果。",
                "parameter_stability": _build_replay_parameter_stability([]),
            }
            simulation_mode = "sample_scored_replay"
        trade_set_changes = _build_replay_trade_set_changes(
            baseline_records=records,
            selected_records=selected_records,
            selected_trade_rows=selected_trade_rows,
            simulation_mode=simulation_mode,
        )
        objective_counterfactual = _build_replay_objective_counterfactual_summary(
            records=records,
            replay_market=replay_market,
            market_data_service=market_data_service,
            selected_patch=selected_patch,
            candidate_leaderboard=search_summary.get("candidate_leaderboard") or [],
            daily_context_by_trade_id=daily_context_by_trade_id,
            minute_context_by_trade_id=minute_context_by_trade_id,
            fundamental_context_by_trade_id=fundamental_context_by_trade_id,
        )
        items.append(
            {
                **spec,
                "comparison_note": comparison_note,
                "metrics": version_metrics,
                "baseline_metrics": baseline_metrics,
                "equity_curve": version_equity_curve,
                "trade_records": selected_trade_rows[:10] or trade_records[:10],
                "simulation_mode": simulation_mode,
                "selected_patch": selected_patch,
                "search_summary": search_summary,
                "trade_set_changes": trade_set_changes,
                "objective_counterfactual": objective_counterfactual,
            }
        )
    return items


def _build_replay_counterfactual_cases(
    *,
    records: list[TradeRecordItem],
    replay_market: str,
    market_data_service: MarketDataService | None,
    daily_context_by_trade_id: dict[str, dict[str, Any]],
    minute_context_by_trade_id: dict[str, dict[str, Any]],
    fundamental_context_by_trade_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if replay_market != "cn_a_share" or market_data_service is None:
        return []

    losing_records = sorted(
        [item for item in records if item.pnl < 0],
        key=lambda item: item.pnl,
    )[:3]
    cases: list[dict[str, Any]] = []
    for rank, item in enumerate(losing_records, start=1):
        case = _build_single_trade_counterfactuals(
            item=item,
            rank=rank,
            market_data_service=market_data_service,
            daily_context=daily_context_by_trade_id.get(item.trade_id),
            minute_context=minute_context_by_trade_id.get(item.trade_id),
            fundamental_context=fundamental_context_by_trade_id.get(item.trade_id),
        )
        if case is not None:
            cases.append(case)
    return cases


def _build_replay_objective_counterfactual_summary(
    *,
    records: list[TradeRecordItem],
    replay_market: str,
    market_data_service: MarketDataService | None,
    selected_patch: dict[str, Any],
    candidate_leaderboard: list[dict[str, Any]] | None,
    daily_context_by_trade_id: dict[str, dict[str, Any]],
    minute_context_by_trade_id: dict[str, dict[str, Any]],
    fundamental_context_by_trade_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if replay_market != "cn_a_share" or market_data_service is None:
        return {
            "summary": "当前版本未接入真实行情反事实联动。",
            "considered_count": 0,
            "improved_count": 0,
            "skipped_count": 0,
            "worsened_count": 0,
            "cases": [],
            "focused_cases": [],
            "total_case_count": 0,
            "display_case_count": 0,
            "search_linked_summary": {},
            "available": False,
        }

    losing_records = sorted(
        [item for item in records if item.pnl < 0],
        key=lambda item: item.pnl,
    )
    if not losing_records:
        return {
            "summary": "当前样本没有亏损单，暂不需要单笔反事实联动。",
            "considered_count": 0,
            "improved_count": 0,
            "skipped_count": 0,
            "worsened_count": 0,
            "cases": [],
            "focused_cases": [],
            "total_case_count": 0,
            "display_case_count": 0,
            "search_linked_summary": {},
            "available": True,
        }

    cases: list[dict[str, Any]] = []
    improved_count = 0
    skipped_count = 0
    worsened_count = 0
    for item in losing_records:
        rerun_trade = _rerun_single_replay_trade(
            item=item,
            market_data_service=market_data_service,
            rule_patch=selected_patch,
            minute_context=minute_context_by_trade_id.get(item.trade_id),
            fundamental_context=fundamental_context_by_trade_id.get(item.trade_id),
        )
        original_trade = _build_replay_trade_records([item])[0]
        if rerun_trade is None:
            skipped_count += 1
            cases.append(
                {
                    "trade_id": item.trade_id,
                    "symbol": item.symbol,
                    "result_type": "skipped",
                    "original_pnl": round(float(item.pnl), 2),
                    "counterfactual_pnl": 0.0,
                    "pnl_delta": round(-float(item.pnl), 2),
                    "summary": "当前版本会直接过滤掉这笔亏损交易。",
                    "original_trade": original_trade,
                    "trade_record": None,
                }
            )
            continue
        pnl_delta = round(float(rerun_trade["pnl"]) - float(item.pnl), 2)
        if pnl_delta > 0:
            improved_count += 1
        elif pnl_delta < 0:
            worsened_count += 1
        cases.append(
            {
                "trade_id": item.trade_id,
                "symbol": item.symbol,
                "result_type": "rerun",
                "original_pnl": round(float(item.pnl), 2),
                "counterfactual_pnl": round(float(rerun_trade["pnl"]), 2),
                "pnl_delta": pnl_delta,
                "summary": (
                    f"当前版本对这笔交易的结果变化为 {pnl_delta:+.2f}，"
                    f"结果从 {float(item.pnl):.2f} 变为 {float(rerun_trade['pnl']):.2f}。"
                ),
                "original_trade": original_trade,
                "trade_record": rerun_trade,
            }
        )
    if skipped_count > 0:
        headline = f"当前版本会直接过滤掉 {skipped_count} 笔 Top 亏损单。"
    elif improved_count > 0:
        headline = f"当前版本会改善 {improved_count} 笔 Top 亏损单。"
    elif worsened_count > 0:
        headline = "当前版本对 Top 亏损单的改善有限，部分结果甚至变差。"
    else:
        headline = "当前版本对 Top 亏损单的结果影响较有限。"
    focused_cases = cases[:5]
    return {
        "summary": headline,
        "considered_count": len(losing_records),
        "improved_count": improved_count,
        "skipped_count": skipped_count,
        "worsened_count": worsened_count,
        "cases": cases,
        "focused_cases": focused_cases,
        "total_case_count": len(cases),
        "display_case_count": len(focused_cases),
        "search_linked_summary": _build_replay_search_linked_counterfactual_summary(
            losing_records=losing_records,
            market_data_service=market_data_service,
            candidate_leaderboard=candidate_leaderboard or [],
            daily_context_by_trade_id=daily_context_by_trade_id,
            minute_context_by_trade_id=minute_context_by_trade_id,
            fundamental_context_by_trade_id=fundamental_context_by_trade_id,
        ),
        "available": True,
    }


def _build_replay_counterfactual_template_summary(
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for case in cases:
        recommended_key = case.get("recommended_alternative_key")
        regime_key = str(case.get("trend_regime") or "unknown")
        for alternative in case.get("alternatives") or []:
            key = str(alternative.get("key") or "unknown")
            title = str(alternative.get("title") or key)
            bucket = grouped.setdefault(
                key,
                {
                    "key": key,
                    "title": title,
                    "improved_count": 0,
                    "skipped_count": 0,
                    "worsened_count": 0,
                    "best_choice_count": 0,
                    "total_pnl_improvement": 0.0,
                    "sample_count": 0,
                    "regimes": {},
                },
            )
            improvement = float(alternative.get("pnl_improvement") or 0.0)
            bucket["sample_count"] += 1
            bucket["total_pnl_improvement"] += improvement
            bucket["regimes"][regime_key] = bucket["regimes"].get(regime_key, 0) + 1
            if alternative.get("result_type") == "skipped":
                bucket["skipped_count"] += 1
            elif improvement > 0:
                bucket["improved_count"] += 1
            elif improvement < 0:
                bucket["worsened_count"] += 1
            if key == recommended_key:
                bucket["best_choice_count"] += 1
    items: list[dict[str, Any]] = []
    for bucket in grouped.values():
        sample_count = int(bucket["sample_count"] or 0)
        items.append(
            {
                "key": bucket["key"],
                "title": bucket["title"],
                "focus": _summarize_replay_patch_focus(
                    next(
                        (
                            alternative.get("patch") or {}
                            for case in cases
                            for alternative in case.get("alternatives") or []
                            if str(alternative.get("key") or "unknown") == bucket["key"]
                        ),
                        {},
                    )
                ),
                "improved_count": int(bucket["improved_count"]),
                "skipped_count": int(bucket["skipped_count"]),
                "worsened_count": int(bucket["worsened_count"]),
                "best_choice_count": int(bucket["best_choice_count"]),
                "avg_pnl_improvement": round(
                    float(bucket["total_pnl_improvement"]) / sample_count,
                    2,
                )
                if sample_count
                else 0.0,
                "sample_count": sample_count,
                "dominant_regimes": sorted(
                    (
                        {"regime": key, "count": count}
                        for key, count in (bucket.get("regimes") or {}).items()
                    ),
                    key=lambda item: int(item["count"]),
                    reverse=True,
                )[:2],
            }
        )
    items.sort(
        key=lambda item: (
            int(item["best_choice_count"]),
            int(item["improved_count"]) + int(item["skipped_count"]),
            float(item["avg_pnl_improvement"]),
        ),
        reverse=True,
    )
    return items[:6]


def _link_counterfactual_templates_to_stability(
    items: list[dict[str, Any]],
    parameter_stability: dict[str, Any],
) -> list[dict[str, Any]]:
    sensitivity_axes = parameter_stability.get("sensitivity_axes") or []
    heatmap_pairs = parameter_stability.get("heatmap_pairs") or []
    pair_axis_set = {
        str(pair.get("x_label") or "")
        for pair in heatmap_pairs
    } | {
        str(pair.get("y_label") or "")
        for pair in heatmap_pairs
    }
    enriched: list[dict[str, Any]] = []
    for item in items:
        focus = item.get("focus") or {}
        matched_axes = [
            {
                "label": axis.get("label"),
                "best_value": axis.get("best_value"),
                "in_pair_heatmap": str(axis.get("label") or "") in pair_axis_set,
            }
            for axis in sensitivity_axes
            if str(axis.get("label") or "") in focus
        ]
        enriched.append(
            {
                **item,
                "linked_axes": matched_axes,
                "attribution_summary": _summarize_replay_template_attribution(
                    focus=focus,
                    matched_axes=matched_axes,
                ),
            }
        )
    return enriched


def _summarize_replay_template_attribution(
    *,
    focus: dict[str, Any],
    matched_axes: list[dict[str, Any]],
) -> str:
    if not focus:
        return "当前模板主要体现为路径级调整，还没有明确的参数归因。"
    if matched_axes:
        labels = "、".join(str(item.get("label") or "") for item in matched_axes[:3] if item.get("label"))
        if labels:
            return f"当前模板主要影响 {labels} 这类敏感参数。"
    focus_keys = [str(key) for key in focus.keys()]
    if focus_keys:
        return f"当前模板主要影响 {'、'.join(focus_keys[:3])}。"
    return "当前模板暂未形成清晰的参数归因。"


def _build_single_trade_counterfactuals(
    *,
    item: TradeRecordItem,
    rank: int,
    market_data_service: MarketDataService,
    daily_context: dict[str, Any] | None,
    minute_context: dict[str, Any] | None,
    fundamental_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    baseline_rerun = _rerun_single_replay_trade(
        item=item,
        market_data_service=market_data_service,
        rule_patch={"filters": {}, "risk": {}},
        minute_context=minute_context,
        fundamental_context=fundamental_context,
    )
    if baseline_rerun is None:
        return None
    original_trade = _build_replay_trade_records([item])[0]
    alternatives: list[dict[str, Any]] = []
    for candidate in _build_counterfactual_rule_candidates(
        item=item,
        daily_context=daily_context,
        minute_context=minute_context,
        fundamental_context=fundamental_context,
    ):
        rerun_trade = _rerun_single_replay_trade(
            item=item,
            market_data_service=market_data_service,
            rule_patch=candidate["patch"],
            minute_context=minute_context,
            fundamental_context=fundamental_context,
        )
        alternatives.append(
            _build_counterfactual_alternative_result(
                item=item,
                original_trade=original_trade,
                candidate=candidate,
                rerun_trade=rerun_trade,
            )
        )

    if not alternatives:
        return None

    ranked = sorted(
        alternatives,
        key=lambda option: (
            1 if option["result_type"] == "skipped" else 0,
            float(option.get("pnl_improvement") or 0.0),
        ),
        reverse=True,
    )
    recommended = ranked[0]
    return {
        "trade_id": item.trade_id,
        "rank": rank,
        "symbol": item.symbol,
        "side": item.side,
        "trend_regime": str((daily_context or {}).get("trend_regime") or "unknown"),
        "summary": (
            f"这笔亏损交易优先对照不开仓过滤、延迟入场、收紧止损和止盈优化。"
            f" 当前最值得优先验证的是“{recommended['title']}”。"
        ),
        "original_trade": original_trade,
        "alternatives": alternatives[:6],
        "recommended_alternative_key": recommended["key"],
        "recommended_summary": recommended["summary"],
    }


def _build_counterfactual_rule_candidates(
    *,
    item: TradeRecordItem,
    daily_context: dict[str, Any] | None,
    minute_context: dict[str, Any] | None,
    fundamental_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    candidates = [
        _build_counterfactual_skip_candidate(
            daily_context=daily_context,
            minute_context=minute_context,
            fundamental_context=fundamental_context,
        ),
        {
            "key": "delayed_entry_confirmation",
            "title": "延迟入场确认",
            "kind": "modified_entry",
            "patch": {
                "filters": {
                    "intraday_entry_timing": {
                        "enabled": True,
                        "delay_entry_minutes": 15,
                    }
                },
                "risk": {},
            },
        },
        {
            "key": "tighter_stop_loss",
            "title": "收紧止损",
            "kind": "modified_risk",
            "patch": {
                "filters": {},
                "risk": {
                    "stop_loss_pct": -0.015,
                    "max_holding_bars": 5,
                },
            },
        },
        {
            "key": "time_based_exit",
            "title": "时间止盈 / 持仓上限收紧",
            "kind": "modified_exit",
            "patch": {
                "filters": {},
                "risk": {
                    "max_holding_bars": 3,
                    "take_profit_pct": 0.025,
                    "stop_loss_pct": -0.018,
                },
            },
        },
    ]
    if daily_context and daily_context.get("trend_regime") == "range":
        candidates.append(
            {
                "key": "trend_only_environment",
                "title": "仅在趋势环境开仓",
                "kind": "environment_filter",
                "patch": {
                    "filters": {
                        "market_regime": {"enabled": True, "preferred": "trend"},
                        "trend_confirmation": {"enabled": True, "timeframe": "1d"},
                    },
                    "risk": {},
                },
            }
        )
    elif fundamental_context and (
        float(fundamental_context.get("debt_to_assets") or 0.0) >= 60.0
        or float(fundamental_context.get("roe") or 100.0) < 8.0
    ):
        candidates.append(
            {
                "key": "quality_guard_filter",
                "title": "基本面质量过滤",
                "kind": "environment_filter",
                "patch": {
                    "filters": {
                        "fundamental_guard": {"enabled": True, "max_debt_to_assets": 55},
                        "quality_filter": {"enabled": True, "min_roe": 8},
                    },
                    "risk": {},
                },
            }
        )
    return candidates


def _build_counterfactual_skip_candidate(
    *,
    daily_context: dict[str, Any] | None,
    minute_context: dict[str, Any] | None,
    fundamental_context: dict[str, Any] | None,
) -> dict[str, Any]:
    filters: dict[str, Any]
    if minute_context and float(minute_context.get("first_15m_return_pct") or 0.0) >= 1.0:
        filters = {
            "intraday_entry_timing": {
                "enabled": True,
                "max_first_15m_return_pct": 1.0,
            }
        }
    elif minute_context and float(minute_context.get("close_position_pct") or 100.0) < 50.0:
        filters = {
            "intraday_structure": {
                "enabled": True,
                "min_close_position_pct": 50,
                "min_up_bar_ratio": 0.5,
            }
        }
    elif daily_context and (
        daily_context.get("trend_regime") == "range"
        or not daily_context.get("above_ma5", True)
    ):
        filters = {
            "market_regime": {
                "enabled": True,
                "preferred": "trend",
            },
            "trend_confirmation": {
                "enabled": True,
                "timeframe": "1d",
            },
        }
    elif fundamental_context and (
        float(fundamental_context.get("debt_to_assets") or 0.0) >= 60.0
        or float(fundamental_context.get("roe") or 100.0) < 10.0
    ):
        filters = {
            "fundamental_guard": {
                "enabled": True,
                "max_debt_to_assets": 55,
            },
            "quality_filter": {
                "enabled": True,
                "min_roe": 10,
            },
        }
    else:
        filters = {
            "extension_guard": {
                "enabled": True,
                "max_prior_return_pct": 2.5,
            }
        }
    return {
        "key": "skip_trade_filter",
        "title": "不开仓过滤",
        "kind": "skip_trade",
        "patch": {
            "filters": filters,
            "risk": {},
        },
    }


def _build_counterfactual_alternative_result(
    *,
    item: TradeRecordItem,
    original_trade: dict[str, Any],
    candidate: dict[str, Any],
    rerun_trade: dict[str, Any] | None,
) -> dict[str, Any]:
    original_pnl = float(item.pnl)
    if rerun_trade is None:
        pnl_improvement = round(-original_pnl, 2)
        return {
            "key": candidate["key"],
            "title": candidate["title"],
            "kind": candidate["kind"],
            "result_type": "skipped",
            "summary": (
                f"按“{candidate['title']}”执行后，这笔交易会被过滤掉，"
                f"可直接避免原本 {original_pnl:.2f} 的亏损。"
            ),
            "pnl_improvement": pnl_improvement,
            "trade_record": None,
            "patch": candidate["patch"],
            "comparison": {
                "original_pnl": round(original_pnl, 2),
                "counterfactual_pnl": 0.0,
                "pnl_delta": pnl_improvement,
                "entry_changed": False,
                "exit_changed": False,
            },
        }

    new_pnl = float(rerun_trade["pnl"])
    entry_changed = (
        _normalize_counterfactual_time_value(rerun_trade.get("entry_time"))
        != _normalize_counterfactual_time_value(original_trade.get("entry_time"))
        or rerun_trade.get("entry_price") != original_trade.get("entry_price")
    )
    exit_changed = (
        _normalize_counterfactual_time_value(rerun_trade.get("exit_time"))
        != _normalize_counterfactual_time_value(original_trade.get("exit_time"))
        or rerun_trade.get("exit_price") != original_trade.get("exit_price")
    )
    pnl_improvement = round(new_pnl - original_pnl, 2)
    improvement_text = "改善" if pnl_improvement >= 0 else "变差"
    return {
        "key": candidate["key"],
        "title": candidate["title"],
        "kind": candidate["kind"],
        "result_type": "rerun",
        "summary": (
            f"按“{candidate['title']}”重放后，结果从 {original_pnl:.2f} 变为 {new_pnl:.2f}，"
            f"较原路径{improvement_text} {abs(pnl_improvement):.2f}。"
        ),
        "pnl_improvement": pnl_improvement,
        "trade_record": rerun_trade,
        "patch": candidate["patch"],
        "comparison": {
            "original_pnl": round(original_pnl, 2),
            "counterfactual_pnl": round(new_pnl, 2),
            "pnl_delta": pnl_improvement,
            "entry_changed": entry_changed,
            "exit_changed": exit_changed,
        },
    }


def _build_replay_search_linked_counterfactual_summary(
    *,
    losing_records: list[TradeRecordItem],
    market_data_service: MarketDataService | None,
    candidate_leaderboard: list[dict[str, Any]],
    daily_context_by_trade_id: dict[str, dict[str, Any]],
    minute_context_by_trade_id: dict[str, dict[str, Any]],
    fundamental_context_by_trade_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if market_data_service is None or not candidate_leaderboard:
        return {}
    focused_candidates = [item for item in candidate_leaderboard if item.get("patch")]
    if not focused_candidates:
        return {}
    cases: list[dict[str, Any]] = []
    improved_count = 0
    skipped_count = 0
    worsened_count = 0
    parameter_attribution_buckets: dict[str, dict[str, Any]] = {}
    winning_candidate_buckets: dict[str, dict[str, Any]] = {}
    regime_attribution_buckets: dict[str, dict[str, Any]] = {}
    decisiveness_gaps: list[float] = []
    for item in losing_records:
        best_case: dict[str, Any] | None = None
        options: list[dict[str, Any]] = []
        daily_context = minute_context = None
        daily_context = daily_context_by_trade_id.get(item.trade_id)
        minute_context = minute_context_by_trade_id.get(item.trade_id)
        for candidate in focused_candidates:
            rerun_trade = _rerun_single_replay_trade(
                item=item,
                market_data_service=market_data_service,
                rule_patch=candidate["patch"],
                minute_context=minute_context,
                fundamental_context=fundamental_context_by_trade_id.get(item.trade_id),
            )
            if rerun_trade is None:
                pnl_delta = round(-float(item.pnl), 2)
                result = {
                    "trade_id": item.trade_id,
                    "symbol": item.symbol,
                    "candidate_label": candidate.get("label") or "候选版本",
                    "candidate_score": candidate.get("score"),
                    "focus": candidate.get("focus") or {},
                    "result_type": "skipped",
                    "original_pnl": round(float(item.pnl), 2),
                    "counterfactual_pnl": 0.0,
                    "pnl_delta": pnl_delta,
                    "summary": "当前候选版本会直接过滤掉这笔亏损交易。",
                }
            else:
                new_pnl = round(float(rerun_trade["pnl"]), 2)
                pnl_delta = round(new_pnl - float(item.pnl), 2)
                result = {
                    "trade_id": item.trade_id,
                    "symbol": item.symbol,
                    "candidate_label": candidate.get("label") or "候选版本",
                    "candidate_score": candidate.get("score"),
                    "focus": candidate.get("focus") or {},
                    "result_type": "rerun",
                    "original_pnl": round(float(item.pnl), 2),
                    "counterfactual_pnl": new_pnl,
                    "pnl_delta": pnl_delta,
                    "summary": f"该候选版本会把结果从 {float(item.pnl):.2f} 变为 {new_pnl:.2f}。",
                }
            options.append(
                {
                    "candidate_label": result["candidate_label"],
                    "candidate_score": result["candidate_score"],
                    "focus": result["focus"],
                    "result_type": result["result_type"],
                    "counterfactual_pnl": result["counterfactual_pnl"],
                    "pnl_delta": result["pnl_delta"],
                }
            )
            if best_case is None or float(result["pnl_delta"]) > float(best_case["pnl_delta"]):
                best_case = result
        if best_case is None:
            continue
        options.sort(key=lambda row: float(row.get("pnl_delta") or 0.0), reverse=True)
        best_case["candidate_options"] = options
        regime_key = str((daily_context or {}).get("trend_regime") or "unknown")
        winning_bucket = winning_candidate_buckets.setdefault(
            str(best_case.get("candidate_label") or "候选版本"),
            {
                "candidate_label": str(best_case.get("candidate_label") or "候选版本"),
                "hit_count": 0,
                "improved_count": 0,
                "skipped_count": 0,
                "worsened_count": 0,
                "total_pnl_delta": 0.0,
                "parameters": {},
                "regimes": {},
            },
        )
        winning_bucket["hit_count"] += 1
        winning_bucket["total_pnl_delta"] += float(best_case.get("pnl_delta") or 0.0)
        winning_bucket["regimes"][regime_key] = winning_bucket["regimes"].get(regime_key, 0) + 1
        regime_bucket = regime_attribution_buckets.setdefault(
            regime_key,
            {
                "regime": regime_key,
                "hit_count": 0,
                "improved_count": 0,
                "skipped_count": 0,
                "worsened_count": 0,
                "total_pnl_delta": 0.0,
            },
        )
        regime_bucket["hit_count"] += 1
        regime_bucket["total_pnl_delta"] += float(best_case.get("pnl_delta") or 0.0)
        if best_case["result_type"] == "skipped":
            winning_bucket["skipped_count"] += 1
            regime_bucket["skipped_count"] += 1
        elif float(best_case.get("pnl_delta") or 0.0) > 0:
            winning_bucket["improved_count"] += 1
            regime_bucket["improved_count"] += 1
        else:
            winning_bucket["worsened_count"] += 1
            regime_bucket["worsened_count"] += 1
        if len(options) > 1:
            decisiveness_gaps.append(
                round(
                    float(options[0].get("pnl_delta") or 0.0)
                    - float(options[1].get("pnl_delta") or 0.0),
                    2,
                )
            )
        for key, value in (best_case.get("focus") or {}).items():
            label = str(key)
            bucket = parameter_attribution_buckets.setdefault(
                label,
                {
                    "parameter": label,
                    "values": {},
                    "hit_count": 0,
                    "improved_count": 0,
                    "skipped_count": 0,
                    "worsened_count": 0,
                    "total_pnl_delta": 0.0,
                    "regimes": {},
                    "winning_candidates": {},
                },
            )
            bucket["hit_count"] += 1
            bucket["total_pnl_delta"] += float(best_case.get("pnl_delta") or 0.0)
            bucket["values"][str(value)] = bucket["values"].get(str(value), 0) + 1
            bucket["regimes"][regime_key] = bucket["regimes"].get(regime_key, 0) + 1
            candidate_label = str(best_case.get("candidate_label") or "候选版本")
            bucket["winning_candidates"][candidate_label] = (
                bucket["winning_candidates"].get(candidate_label, 0) + 1
            )
            winning_bucket["parameters"][label] = winning_bucket["parameters"].get(label, 0) + 1
            if best_case["result_type"] == "skipped":
                bucket["skipped_count"] += 1
            elif float(best_case.get("pnl_delta") or 0.0) > 0:
                bucket["improved_count"] += 1
            else:
                bucket["worsened_count"] += 1
        if best_case["result_type"] == "skipped":
            skipped_count += 1
            if float(best_case["pnl_delta"]) > 0:
                improved_count += 1
        elif float(best_case["pnl_delta"]) > 0:
            improved_count += 1
        else:
            worsened_count += 1
        cases.append(best_case)
    cases.sort(key=lambda row: float(row.get("pnl_delta") or 0.0), reverse=True)
    if not cases:
        return {}
    total_option_count = sum(len(case.get("candidate_options") or []) for case in cases)
    parameter_attribution = _build_replay_parameter_attribution_summary(
        parameter_attribution_buckets
    )
    return {
        "summary": "已对全样本亏损单补充对照前几组参数候选，帮助确认哪些单笔还能继续优化。",
        "considered_count": len(losing_records),
        "improved_count": improved_count,
        "skipped_count": skipped_count,
        "worsened_count": worsened_count,
        "candidate_scan_coverage": {
            "candidate_count_per_trade_avg": round(total_option_count / len(cases), 2) if cases else 0.0,
            "focused_candidate_count": len(focused_candidates),
            "total_candidate_pool_count": len(candidate_leaderboard),
            "covered_trade_count": len(cases),
        },
        "winning_candidate_summary": _build_replay_winning_candidate_summary(
            winning_candidate_buckets,
            considered_count=len(cases),
        ),
        "regime_attribution": _build_replay_regime_attribution_summary(
            regime_attribution_buckets,
            considered_count=len(cases),
        ),
        "candidate_decisiveness": _build_replay_candidate_decisiveness_summary(decisiveness_gaps),
        "parameter_attribution": parameter_attribution,
        "cases": cases,
        "focused_cases": cases[:5],
    }


def _build_replay_parameter_attribution_summary(
    buckets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for bucket in buckets.values():
        hit_count = int(bucket["hit_count"] or 0)
        if not hit_count:
            continue
        top_values = sorted(
            (
                {"value": key, "count": count}
                for key, count in (bucket.get("values") or {}).items()
            ),
            key=lambda item: int(item["count"]),
            reverse=True,
        )[:3]
        items.append(
            {
                "parameter": bucket["parameter"],
                "hit_count": hit_count,
                "improved_count": int(bucket["improved_count"]),
                "skipped_count": int(bucket["skipped_count"]),
                "worsened_count": int(bucket["worsened_count"]),
                "avg_pnl_delta": round(float(bucket["total_pnl_delta"]) / hit_count, 2),
                "top_values": top_values,
                "dominant_regimes": sorted(
                    (
                        {"regime": key, "count": count}
                        for key, count in (bucket.get("regimes") or {}).items()
                    ),
                    key=lambda item: int(item["count"]),
                    reverse=True,
                )[:2],
                "winning_candidates": sorted(
                    (
                        {"candidate_label": key, "count": count}
                        for key, count in (bucket.get("winning_candidates") or {}).items()
                    ),
                    key=lambda item: int(item["count"]),
                    reverse=True,
                )[:3],
            }
        )
    items.sort(
        key=lambda item: (
            int(item["hit_count"]),
            int(item["improved_count"]) + int(item["skipped_count"]),
            float(item["avg_pnl_delta"]),
        ),
        reverse=True,
    )
    return items[:6]


def _build_replay_winning_candidate_summary(
    buckets: dict[str, dict[str, Any]],
    *,
    considered_count: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for bucket in buckets.values():
        hit_count = int(bucket["hit_count"] or 0)
        if not hit_count:
            continue
        parameter_focus = sorted(
            (
                {"parameter": key, "count": count}
                for key, count in (bucket.get("parameters") or {}).items()
            ),
            key=lambda item: int(item["count"]),
            reverse=True,
        )[:3]
        items.append(
            {
                "candidate_label": bucket["candidate_label"],
                "hit_count": hit_count,
                "coverage_ratio": round(hit_count / max(considered_count, 1), 2),
                "improved_count": int(bucket["improved_count"]),
                "skipped_count": int(bucket["skipped_count"]),
                "worsened_count": int(bucket["worsened_count"]),
                "avg_pnl_delta": round(float(bucket["total_pnl_delta"]) / hit_count, 2),
                "parameter_focus": parameter_focus,
                "dominant_regimes": sorted(
                    (
                        {"regime": key, "count": count}
                        for key, count in (bucket.get("regimes") or {}).items()
                    ),
                    key=lambda item: int(item["count"]),
                    reverse=True,
                )[:2],
            }
        )
    items.sort(
        key=lambda item: (
            int(item["hit_count"]),
            float(item["avg_pnl_delta"]),
            int(item["improved_count"]) + int(item["skipped_count"]),
        ),
        reverse=True,
    )
    return items[:5]


def _build_replay_regime_attribution_summary(
    buckets: dict[str, dict[str, Any]],
    *,
    considered_count: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for bucket in buckets.values():
        hit_count = int(bucket["hit_count"] or 0)
        if not hit_count:
            continue
        items.append(
            {
                "regime": bucket["regime"],
                "hit_count": hit_count,
                "coverage_ratio": round(hit_count / max(considered_count, 1), 2),
                "improved_count": int(bucket["improved_count"]),
                "skipped_count": int(bucket["skipped_count"]),
                "worsened_count": int(bucket["worsened_count"]),
                "avg_pnl_delta": round(float(bucket["total_pnl_delta"]) / hit_count, 2),
            }
        )
    items.sort(
        key=lambda item: (
            int(item["hit_count"]),
            float(item["avg_pnl_delta"]),
            int(item["improved_count"]) + int(item["skipped_count"]),
        ),
        reverse=True,
    )
    return items


def _build_replay_candidate_decisiveness_summary(gaps: list[float]) -> dict[str, Any]:
    if not gaps:
        return {}
    narrow_count = sum(1 for gap in gaps if gap <= 50)
    clear_count = sum(1 for gap in gaps if gap >= 150)
    return {
        "avg_gap": round(sum(gaps) / len(gaps), 2),
        "narrow_win_count": narrow_count,
        "clear_win_count": clear_count,
        "narrow_win_ratio": round(narrow_count / len(gaps), 2),
        "clear_win_ratio": round(clear_count / len(gaps), 2),
        "summary": (
            "如果最优候选与次优候选差距很小，说明当前最优点可能只是险胜；"
            "如果差距较大，说明当前候选更像稳定胜出。"
        ),
    }


def _normalize_counterfactual_time_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.replace("Z", "+00:00")


def _rerun_replay_records_on_market_data(
    *,
    records: list[TradeRecordItem],
    replay_market: str,
    objective: str,
    market_data_service: MarketDataService | None,
    suggestion_rules: list[dict[str, Any]],
    daily_context_by_trade_id: dict[str, dict[str, Any]],
    minute_context_by_trade_id: dict[str, dict[str, Any]],
    fundamental_context_by_trade_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if market_data_service is None or replay_market != "cn_a_share" or not records:
        return None

    combined_patch = _merge_replay_rule_patches(
        suggestion_rules=suggestion_rules,
        objective=objective,
    )
    optimized_patch, evaluated_variants, parameter_stability, candidate_leaderboard = _optimize_replay_rule_patch(
        records=records,
        replay_market=replay_market,
        objective=objective,
        market_data_service=market_data_service,
        base_patch=combined_patch,
        daily_context_by_trade_id=daily_context_by_trade_id,
        minute_context_by_trade_id=minute_context_by_trade_id,
        fundamental_context_by_trade_id=fundamental_context_by_trade_id,
    )
    rerun_trade_rows: list[dict[str, Any]] = []
    cumulative_pnl = 0.0
    equity_curve: list[dict[str, Any]] = []

    for item in sorted(records, key=lambda row: row.exit_time or row.entry_time):
        rerun_trade = _rerun_single_replay_trade(
            item=item,
            market_data_service=market_data_service,
            rule_patch=optimized_patch,
            minute_context=minute_context_by_trade_id.get(item.trade_id),
            fundamental_context=fundamental_context_by_trade_id.get(item.trade_id),
        )
        if rerun_trade is None:
            continue
        rerun_trade_rows.append(rerun_trade)
        cumulative_pnl += float(rerun_trade["pnl"])
        equity_curve.append(
            {
                "index": len(equity_curve) + 1,
                "timestamp": rerun_trade["exit_time"],
                "symbol": rerun_trade["symbol"],
                "pnl": round(float(rerun_trade["pnl"]), 2),
                "equity": round(cumulative_pnl, 2),
            }
        )

    if not rerun_trade_rows:
        return None
    metrics = _build_replay_trade_rows_metrics(rerun_trade_rows)
    return {
        "trade_records": rerun_trade_rows,
        "equity_curve": equity_curve,
        "metrics": metrics,
        "selected_patch": optimized_patch,
        "search_summary": {
            "mode": "grid_search",
            "evaluated_variants": evaluated_variants,
            "selected_reason": (
                f"已按 {objective} 目标从 {evaluated_variants} 个候选参数版本中选出当前最优版本。"
            ),
            "objective_score": round(_score_replay_objective_metrics(metrics, objective=objective), 4),
            "parameter_stability": parameter_stability,
            "candidate_leaderboard": candidate_leaderboard,
        },
    }


def _merge_replay_rule_patches(
    *,
    suggestion_rules: list[dict[str, Any]],
    objective: str,
) -> dict[str, Any]:
    merged: dict[str, Any] = {"filters": {}, "risk": {}}
    for rule in suggestion_rules:
        patch = rule.get("dsl_patch") or {}
        for key in ("filters", "risk"):
            section = patch.get(key) or {}
            if isinstance(section, dict):
                merged[key].update(section)
    risk = merged["risk"]
    if objective == "sharpe_max":
        risk.setdefault("stop_loss_pct", -0.02)
        risk.setdefault("max_holding_bars", 8)
    elif objective == "win_rate_max":
        risk.setdefault("stop_loss_pct", -0.015)
        risk.setdefault("max_holding_bars", 6)
    elif objective == "max_drawdown_min":
        risk.setdefault("stop_loss_pct", -0.015)
        risk.setdefault("max_holding_bars", 5)
    elif objective == "total_return_max":
        risk.setdefault("stop_loss_pct", -0.03)
        risk.setdefault("max_holding_bars", 12)
    return merged


def _optimize_replay_rule_patch(
    *,
    records: list[TradeRecordItem],
    replay_market: str,
    objective: str,
    market_data_service: MarketDataService,
    base_patch: dict[str, Any],
    daily_context_by_trade_id: dict[str, dict[str, Any]],
    minute_context_by_trade_id: dict[str, dict[str, Any]],
    fundamental_context_by_trade_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], int, dict[str, Any], list[dict[str, Any]]]:
    if replay_market != "cn_a_share":
        return base_patch, 0, _build_replay_parameter_stability([]), []

    risk = base_patch.get("risk") or {}
    filters = base_patch.get("filters") or {}
    candidates: dict[tuple[str, ...], list[Any]] = {
        ("risk", "stop_loss_pct"): _candidate_numeric_values(risk.get("stop_loss_pct"), [-0.015, -0.02, -0.03]),
        ("risk", "take_profit_pct"): _candidate_numeric_values(risk.get("take_profit_pct"), [0.04, 0.06, 0.08]),
        ("risk", "max_holding_bars"): _candidate_numeric_values(risk.get("max_holding_bars"), [5, 8, 12]),
    }
    if "extension_guard" in filters:
        candidates[("filters", "extension_guard", "max_prior_return_pct")] = _candidate_numeric_values(
            filters["extension_guard"].get("max_prior_return_pct"),
            [2.0, 4.0, 6.0],
        )
    if "volume_heat_guard" in filters:
        candidates[("filters", "volume_heat_guard", "max_value")] = _candidate_numeric_values(
            filters["volume_heat_guard"].get("max_value"),
            [1.4, 1.8, 2.2],
        )
    if "intraday_entry_timing" in filters:
        candidates[("filters", "intraday_entry_timing", "max_first_15m_return_pct")] = _candidate_numeric_values(
            filters["intraday_entry_timing"].get("max_first_15m_return_pct"),
            [0.6, 1.0, 1.5],
        )
        candidates[("filters", "intraday_entry_timing", "min_first_15m_return_pct")] = _candidate_numeric_values(
            filters["intraday_entry_timing"].get("min_first_15m_return_pct"),
            [-0.2, 0.0, 0.3],
        )
        candidates[("filters", "intraday_entry_timing", "min_last_15m_return_pct")] = _candidate_numeric_values(
            filters["intraday_entry_timing"].get("min_last_15m_return_pct"),
            [-0.3, 0.0, 0.2],
        )
    if "intraday_structure" in filters:
        candidates[("filters", "intraday_structure", "min_close_position_pct")] = _candidate_numeric_values(
            filters["intraday_structure"].get("min_close_position_pct"),
            [45, 50, 60],
        )
        candidates[("filters", "intraday_structure", "min_up_bar_ratio")] = _candidate_numeric_values(
            filters["intraday_structure"].get("min_up_bar_ratio"),
            [0.45, 0.5, 0.6],
        )
        candidates[("filters", "intraday_structure", "max_peak_to_close_drawdown_pct")] = _candidate_numeric_values(
            filters["intraday_structure"].get("max_peak_to_close_drawdown_pct"),
            [1.0, 2.0, 3.5],
        )
    if "fundamental_guard" in filters:
        candidates[("filters", "fundamental_guard", "max_pe_ttm")] = _candidate_numeric_values(
            filters["fundamental_guard"].get("max_pe_ttm"),
            [25, 35, 45],
        )
        candidates[("filters", "fundamental_guard", "max_debt_to_assets")] = _candidate_numeric_values(
            filters["fundamental_guard"].get("max_debt_to_assets"),
            [45, 55, 65],
        )
    if "quality_filter" in filters:
        candidates[("filters", "quality_filter", "min_roe")] = _candidate_numeric_values(
            filters["quality_filter"].get("min_roe"),
            [8, 10, 12],
        )
        candidates[("filters", "quality_filter", "min_grossprofit_margin")] = _candidate_numeric_values(
            filters["quality_filter"].get("min_grossprofit_margin"),
            [20, 25, 30],
        )
        candidates[("filters", "quality_filter", "min_op_yoy")] = _candidate_numeric_values(
            filters["quality_filter"].get("min_op_yoy"),
            [-5, 0, 5],
        )

    scored_candidates: list[dict[str, Any]] = []
    variants = _limited_replay_patch_variants(base_patch=base_patch, candidates=candidates, limit=24)
    for patch in variants:
        rerun_rows: list[dict[str, Any]] = []
        for item in sorted(records, key=lambda row: row.exit_time or row.entry_time):
            rerun_trade = _rerun_single_replay_trade(
                item=item,
                market_data_service=market_data_service,
                rule_patch=patch,
                minute_context=minute_context_by_trade_id.get(item.trade_id),
                fundamental_context=fundamental_context_by_trade_id.get(item.trade_id),
            )
            if rerun_trade is not None:
                rerun_rows.append(rerun_trade)
        if not rerun_rows:
            continue
        metrics = _build_replay_trade_rows_metrics(rerun_rows)
        score = _score_replay_objective_metrics(metrics, objective=objective)
        scored_candidates.append(
            {
                "score": score,
                "patch": patch,
                "metrics": metrics,
            }
        )
    if not scored_candidates:
        return base_patch, len(variants), _build_replay_parameter_stability([]), []
    ranked_candidates = sorted(scored_candidates, key=lambda item: float(item["score"]), reverse=True)
    best_patch = ranked_candidates[0]["patch"]
    parameter_stability = _build_replay_parameter_stability(
        ranked_candidates,
        records=records,
        selected_patch=best_patch,
        market_data_service=market_data_service,
        daily_context_by_trade_id=daily_context_by_trade_id,
        minute_context_by_trade_id=minute_context_by_trade_id,
        fundamental_context_by_trade_id=fundamental_context_by_trade_id,
    )
    candidate_leaderboard = [
        {
            "label": f"候选 {index + 1}",
            "score": round(float(item["score"]), 4),
            "focus": _summarize_replay_patch_focus(item["patch"]),
            "patch": item["patch"],
        }
        for index, item in enumerate(ranked_candidates[:5])
    ]
    return best_patch, len(variants), parameter_stability, candidate_leaderboard


def _build_replay_parameter_stability(
    scored_candidates: list[dict[str, Any]],
    *,
    records: list[TradeRecordItem] | None = None,
    selected_patch: dict[str, Any] | None = None,
    market_data_service: MarketDataService | None = None,
    daily_context_by_trade_id: dict[str, dict[str, Any]] | None = None,
    minute_context_by_trade_id: dict[str, dict[str, Any]] | None = None,
    fundamental_context_by_trade_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not scored_candidates:
        return {
            "label": "暂无稳定性结论",
            "summary": "当前没有足够的候选版本可用于稳定性判断。",
            "near_best_count": 0,
            "top_candidates": [],
            "neighbor_candidates": [],
            "neighbor_bands": [],
            "sensitivity_axes": [],
            "heatmap_axes": [],
            "heatmap_pairs": [],
            "rolling_windows": [],
            "market_regime_windows": [],
        }
    best_score = float(scored_candidates[0]["score"])
    threshold = max(abs(best_score) * 0.05, 0.05)
    near_best = [
        item for item in scored_candidates if (best_score - float(item["score"])) <= threshold
    ]
    near_best_count = len(near_best)
    if len(scored_candidates) < 3:
        label = "候选版本偏少"
        summary = "当前可比较的候选版本较少，稳定性判断可信度有限。"
    elif near_best_count >= 3:
        label = "参数稳定区较宽"
        summary = "最优版本附近还有多组接近结果，当前参数不属于特别尖锐的单点。"
    elif near_best_count == 2:
        label = "存在相邻可用参数"
        summary = "当前最优值附近还有相邻候选可用，但稳定区仍偏窄。"
    else:
        label = "最优点偏尖锐"
        summary = "当前最优结果与邻近候选差距较大，需要警惕过拟合。"
    top_candidates = []
    for item in scored_candidates[:3]:
        top_candidates.append(
            {
                "score": round(float(item["score"]), 4),
                "focus": _summarize_replay_patch_focus(item["patch"]),
                "trade_count": int(item["metrics"].get("trade_count") or 0),
                "win_rate_pct": round(float(item["metrics"].get("win_rate_pct") or 0.0), 2),
                "max_drawdown_pct": round(float(item["metrics"].get("max_drawdown_pct") or 0.0), 2),
                "sharpe_like": round(float(item["metrics"].get("sharpe_like") or 0.0), 2),
                "total_pnl": round(float(item["metrics"].get("total_pnl") or 0.0), 2),
            }
        )
    return {
        "label": label,
        "summary": summary,
        "near_best_count": near_best_count,
        "top_candidates": top_candidates,
        "neighbor_candidates": _build_replay_neighbor_candidates(scored_candidates, best_score),
        "neighbor_bands": _build_replay_neighbor_bands(scored_candidates, best_score),
        "sensitivity_axes": _build_replay_parameter_sensitivity_axes(scored_candidates),
        "heatmap_axes": _build_replay_parameter_heatmap_axes(scored_candidates),
        "heatmap_pairs": _build_replay_parameter_pair_heatmaps(scored_candidates),
        "rolling_windows": _build_replay_rolling_window_stability(
            records=records or [],
            selected_patch=selected_patch or {},
            market_data_service=market_data_service,
            minute_context_by_trade_id=minute_context_by_trade_id or {},
            fundamental_context_by_trade_id=fundamental_context_by_trade_id or {},
        ),
        "market_regime_windows": _build_replay_market_regime_stability(
            records=records or [],
            selected_patch=selected_patch or {},
            market_data_service=market_data_service,
            daily_context_by_trade_id=daily_context_by_trade_id or {},
            minute_context_by_trade_id=minute_context_by_trade_id or {},
            fundamental_context_by_trade_id=fundamental_context_by_trade_id or {},
        ),
    }


def _build_replay_neighbor_candidates(
    scored_candidates: list[dict[str, Any]],
    best_score: float,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for candidate in scored_candidates[:5]:
        score = round(float(candidate["score"]), 4)
        items.append(
            {
                "score": score,
                "score_delta": round(score - best_score, 4),
                "focus": _summarize_replay_patch_focus(candidate["patch"]),
                "trade_count": int(candidate["metrics"].get("trade_count") or 0),
                "win_rate_pct": round(float(candidate["metrics"].get("win_rate_pct") or 0.0), 2),
                "max_drawdown_pct": round(float(candidate["metrics"].get("max_drawdown_pct") or 0.0), 2),
                "sharpe_like": round(float(candidate["metrics"].get("sharpe_like") or 0.0), 2),
            }
        )
    return items


def _build_replay_neighbor_bands(
    scored_candidates: list[dict[str, Any]],
    best_score: float,
) -> list[dict[str, Any]]:
    if not scored_candidates:
        return []
    thresholds = [
        ("贴近最优", max(abs(best_score) * 0.03, 0.03)),
        ("次近邻", max(abs(best_score) * 0.08, 0.08)),
    ]
    bands = [
        {"label": "贴近最优", "count": 0, "score_deltas": [], "trade_counts": []},
        {"label": "次近邻", "count": 0, "score_deltas": [], "trade_counts": []},
        {"label": "明显回落", "count": 0, "score_deltas": [], "trade_counts": []},
    ]
    for candidate in scored_candidates:
        score = float(candidate["score"])
        score_delta = round(score - best_score, 4)
        distance = best_score - score
        if distance <= thresholds[0][1]:
            band = bands[0]
        elif distance <= thresholds[1][1]:
            band = bands[1]
        else:
            band = bands[2]
        band["count"] += 1
        band["score_deltas"].append(score_delta)
        band["trade_counts"].append(int(candidate["metrics"].get("trade_count") or 0))
    result: list[dict[str, Any]] = []
    for band in bands:
        if not band["count"]:
            continue
        avg_delta = sum(band["score_deltas"]) / len(band["score_deltas"])
        avg_trades = sum(band["trade_counts"]) / len(band["trade_counts"])
        result.append(
            {
                "label": band["label"],
                "count": int(band["count"]),
                "avg_score_delta": round(avg_delta, 4),
                "best_score_delta": round(max(band["score_deltas"]), 4),
                "worst_score_delta": round(min(band["score_deltas"]), 4),
                "avg_trade_count": round(avg_trades, 1),
            }
        )
    return result


def _build_replay_parameter_sensitivity_axes(
    scored_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(scored_candidates) < 2:
        return []
    best_score = float(scored_candidates[0]["score"])
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in scored_candidates:
        focus = _summarize_replay_patch_focus(candidate["patch"])
        score = float(candidate["score"])
        for key, raw_value in focus.items():
            label = str(key)
            group = grouped.setdefault(
                label,
                {
                    "values": {},
                    "best_value": raw_value,
                    "best_score": -math.inf,
                },
            )
            bucket = group["values"].setdefault(
                str(raw_value),
                {"value": raw_value, "scores": []},
            )
            bucket["scores"].append(score)
            if score > float(group["best_score"]):
                group["best_score"] = score
                group["best_value"] = raw_value

    axes: list[dict[str, Any]] = []
    for label, group in grouped.items():
        values = list(group["values"].values())
        if len(values) < 2:
            continue
        value_summaries = []
        for item in values:
            avg_score = sum(item["scores"]) / len(item["scores"])
            value_summaries.append(
                {
                    "value": item["value"],
                    "avg_score": round(avg_score, 4),
                    "count": len(item["scores"]),
                }
            )
        value_summaries.sort(key=lambda item: float(item["avg_score"]), reverse=True)
        spread = round(float(value_summaries[0]["avg_score"]) - float(value_summaries[-1]["avg_score"]), 4)
        sensitivity = "较平稳" if spread <= max(abs(best_score) * 0.03, 0.03) else "较敏感"
        axes.append(
            {
                "label": label,
                "best_value": group["best_value"],
                "score_spread": spread,
                "sensitivity": sensitivity,
                "values": value_summaries[:5],
            }
        )
    axes.sort(key=lambda item: float(item["score_spread"]), reverse=True)
    return axes[:6]


def _build_replay_parameter_heatmap_axes(
    scored_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    axes = _build_replay_parameter_sensitivity_axes(scored_candidates)
    if not axes:
        return []
    result: list[dict[str, Any]] = []
    for axis in axes:
        values = axis.get("values") or []
        if not values:
            continue
        best = max(float(item["avg_score"]) for item in values)
        worst = min(float(item["avg_score"]) for item in values)
        spread = max(best - worst, 0.0001)
        heat_values = []
        for item in values:
            intensity = (float(item["avg_score"]) - worst) / spread
            heat_values.append(
                {
                    **item,
                    "intensity": round(intensity, 3),
                }
            )
        result.append(
            {
                "label": axis["label"],
                "best_value": axis["best_value"],
                "values": heat_values,
            }
        )
    return result


def _build_replay_parameter_pair_heatmaps(
    scored_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sensitivity_axes = _build_replay_parameter_sensitivity_axes(scored_candidates)
    if len(sensitivity_axes) < 2:
        return []
    axis_labels = [str(axis["label"]) for axis in sensitivity_axes[:2]]
    x_label, y_label = axis_labels[0], axis_labels[1]
    grouped: dict[tuple[str, str], list[float]] = {}
    for candidate in scored_candidates:
        focus = _summarize_replay_patch_focus(candidate["patch"])
        if x_label not in focus or y_label not in focus:
            continue
        key = (str(focus[x_label]), str(focus[y_label]))
        grouped.setdefault(key, []).append(float(candidate["score"]))
    if not grouped:
        return []

    x_values = sorted({key[0] for key in grouped.keys()})
    y_values = sorted({key[1] for key in grouped.keys()})
    avg_scores = {
        key: sum(scores) / len(scores)
        for key, scores in grouped.items()
    }
    best = max(avg_scores.values())
    worst = min(avg_scores.values())
    spread = max(best - worst, 0.0001)
    matrix: list[dict[str, Any]] = []
    for y_value in y_values:
        row_cells = []
        for x_value in x_values:
            avg_score = avg_scores.get((x_value, y_value))
            if avg_score is None:
                row_cells.append(
                    {
                        "x_value": x_value,
                        "y_value": y_value,
                        "avg_score": None,
                        "intensity": 0.0,
                        "count": 0,
                    }
                )
                continue
            row_cells.append(
                {
                    "x_value": x_value,
                    "y_value": y_value,
                    "avg_score": round(avg_score, 4),
                    "intensity": round((avg_score - worst) / spread, 3),
                    "count": len(grouped[(x_value, y_value)]),
                }
            )
        matrix.append({"y_value": y_value, "cells": row_cells})
    return [
        {
            "x_label": x_label,
            "y_label": y_label,
            "x_values": x_values,
            "matrix": matrix,
        }
    ]


def _build_replay_rolling_window_stability(
    *,
    records: list[TradeRecordItem],
    selected_patch: dict[str, Any],
    market_data_service: MarketDataService | None,
    minute_context_by_trade_id: dict[str, dict[str, Any]],
    fundamental_context_by_trade_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if market_data_service is None or len(records) < 2:
        return []
    ordered = sorted(records, key=lambda item: item.exit_time or item.entry_time)
    chunk_size = max(1, math.ceil(len(ordered) / 3))
    windows: list[dict[str, Any]] = []
    for index in range(0, len(ordered), chunk_size):
        chunk = ordered[index:index + chunk_size]
        if not chunk:
            continue
        rows = _rerun_replay_records_with_patch(
            records=chunk,
            selected_patch=selected_patch,
            market_data_service=market_data_service,
            minute_context_by_trade_id=minute_context_by_trade_id,
            fundamental_context_by_trade_id=fundamental_context_by_trade_id,
        )
        if not rows:
            continue
        metrics = _build_replay_trade_rows_metrics(rows)
        windows.append(
            {
                "label": f"窗口 {len(windows) + 1}",
                "trade_count": metrics["trade_count"],
                "win_rate_pct": metrics["win_rate_pct"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "sharpe_like": metrics["sharpe_like"],
                "date_range": (
                    f"{(chunk[0].entry_time).date().isoformat()} ~ "
                    f"{((chunk[-1].exit_time or chunk[-1].entry_time).date().isoformat())}"
                ),
            }
        )
    return windows


def _build_replay_market_regime_stability(
    *,
    records: list[TradeRecordItem],
    selected_patch: dict[str, Any],
    market_data_service: MarketDataService | None,
    daily_context_by_trade_id: dict[str, dict[str, Any]],
    minute_context_by_trade_id: dict[str, dict[str, Any]],
    fundamental_context_by_trade_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if market_data_service is None or not records:
        return []
    buckets: dict[str, list[TradeRecordItem]] = {"trend": [], "range": [], "unknown": []}
    for item in records:
        regime = (daily_context_by_trade_id.get(item.trade_id) or {}).get("trend_regime") or "unknown"
        buckets.setdefault(regime, []).append(item)
    results: list[dict[str, Any]] = []
    for regime, bucket in buckets.items():
        if not bucket:
            continue
        rows = _rerun_replay_records_with_patch(
            records=bucket,
            selected_patch=selected_patch,
            market_data_service=market_data_service,
            minute_context_by_trade_id=minute_context_by_trade_id,
            fundamental_context_by_trade_id=fundamental_context_by_trade_id,
        )
        if not rows:
            continue
        metrics = _build_replay_trade_rows_metrics(rows)
        label = {"trend": "趋势环境", "range": "震荡环境", "unknown": "未识别环境"}.get(regime, regime)
        results.append(
            {
                "label": label,
                "trade_count": metrics["trade_count"],
                "win_rate_pct": metrics["win_rate_pct"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "sharpe_like": metrics["sharpe_like"],
            }
        )
    return results


def _rerun_replay_records_with_patch(
    *,
    records: list[TradeRecordItem],
    selected_patch: dict[str, Any],
    market_data_service: MarketDataService,
    minute_context_by_trade_id: dict[str, dict[str, Any]],
    fundamental_context_by_trade_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sorted(records, key=lambda row: row.exit_time or row.entry_time):
        rerun_trade = _rerun_single_replay_trade(
            item=item,
            market_data_service=market_data_service,
            rule_patch=selected_patch,
            minute_context=minute_context_by_trade_id.get(item.trade_id),
            fundamental_context=fundamental_context_by_trade_id.get(item.trade_id),
        )
        if rerun_trade is not None:
            rows.append(rerun_trade)
    return rows


def _summarize_replay_patch_focus(patch: dict[str, Any]) -> dict[str, Any]:
    risk = patch.get("risk") or {}
    filters = patch.get("filters") or {}
    summary: dict[str, Any] = {}
    if "stop_loss_pct" in risk:
        summary["stop_loss_pct"] = risk.get("stop_loss_pct")
    if "take_profit_pct" in risk:
        summary["take_profit_pct"] = risk.get("take_profit_pct")
    if "max_holding_bars" in risk:
        summary["max_holding_bars"] = risk.get("max_holding_bars")
    intraday_entry_timing = filters.get("intraday_entry_timing") or {}
    intraday_structure = filters.get("intraday_structure") or {}
    quality_filter = filters.get("quality_filter") or {}
    extension_guard = filters.get("extension_guard") or {}
    volume_heat_guard = filters.get("volume_heat_guard") or {}
    if "max_first_15m_return_pct" in intraday_entry_timing:
        summary["max_first_15m_return_pct"] = intraday_entry_timing.get("max_first_15m_return_pct")
    if "min_first_15m_return_pct" in intraday_entry_timing:
        summary["min_first_15m_return_pct"] = intraday_entry_timing.get("min_first_15m_return_pct")
    if "min_last_15m_return_pct" in intraday_entry_timing:
        summary["min_last_15m_return_pct"] = intraday_entry_timing.get("min_last_15m_return_pct")
    if "max_peak_to_close_drawdown_pct" in intraday_structure:
        summary["max_peak_to_close_drawdown_pct"] = intraday_structure.get("max_peak_to_close_drawdown_pct")
    if "max_prior_return_pct" in extension_guard:
        summary["max_prior_return_pct"] = extension_guard.get("max_prior_return_pct")
    if "max_value" in volume_heat_guard:
        summary["max_volume_ratio"] = volume_heat_guard.get("max_value")
    if "min_roe" in quality_filter:
        summary["min_roe"] = quality_filter.get("min_roe")
    if "min_grossprofit_margin" in quality_filter:
        summary["min_grossprofit_margin"] = quality_filter.get("min_grossprofit_margin")
    if "min_op_yoy" in quality_filter:
        summary["min_op_yoy"] = quality_filter.get("min_op_yoy")
    return summary


def _candidate_numeric_values(current: Any, defaults: list[Any]) -> list[Any]:
    values = []
    if current is not None:
        values.append(current)
    values.extend(defaults)
    deduped: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = f"{value}"
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    return deduped


def _limited_replay_patch_variants(
    *,
    base_patch: dict[str, Any],
    candidates: dict[tuple[str, ...], list[Any]],
    limit: int,
) -> list[dict[str, Any]]:
    variants = [json.loads(json.dumps(base_patch))]
    for path, options in candidates.items():
        next_variants: list[dict[str, Any]] = []
        for patch in variants:
            for value in options:
                copied = json.loads(json.dumps(patch))
                _set_nested_replay_patch_value(copied, path, value)
                next_variants.append(copied)
                if len(next_variants) >= limit:
                    break
            if len(next_variants) >= limit:
                break
        variants = next_variants or variants
        if len(variants) >= limit:
            break
    return variants[:limit]


def _set_nested_replay_patch_value(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = target
    for key in path[:-1]:
        current = current.setdefault(key, {})
    current[path[-1]] = value


def _score_replay_objective_metrics(metrics: dict[str, Any], *, objective: str) -> float:
    if objective == "win_rate_max":
        return float(metrics.get("win_rate_pct") or 0.0)
    if objective == "max_drawdown_min":
        return -abs(float(metrics.get("max_drawdown_pct") or 0.0))
    if objective == "total_return_max":
        return float(metrics.get("total_pnl") or 0.0)
    sharpe_like = float(metrics.get("sharpe_like") or 0.0)
    drawdown_penalty = abs(float(metrics.get("max_drawdown_pct") or 0.0)) * 0.1
    return sharpe_like - drawdown_penalty


def _rerun_single_replay_trade(
    *,
    item: TradeRecordItem,
    market_data_service: MarketDataService,
    rule_patch: dict[str, Any],
    minute_context: dict[str, Any] | None,
    fundamental_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not item.symbol.endswith((".SH", ".SZ", ".BJ")):
        return None

    entry_date = item.entry_time.date()
    actual_exit_date = (item.exit_time or item.entry_time).date()
    risk = rule_patch.get("risk") or {}
    filters = rule_patch.get("filters") or {}
    max_holding_bars = max(int(risk.get("max_holding_bars", 8)), 1)
    start_date = entry_date - timedelta(days=20)
    end_date = max(actual_exit_date + timedelta(days=max_holding_bars + 10), entry_date + timedelta(days=max_holding_bars + 10))
    bars, metadata = market_data_service.load_daily_bars(
        ts_code=item.symbol,
        start_date=start_date,
        end_date=end_date,
        adjustment_mode="qfq",
    )
    if metadata.get("provider") in {None, "demo"} or not bars:
        return None

    entry_index = next(
        (index for index, bar in enumerate(bars) if date.fromisoformat(bar.trade_date) >= entry_date),
        None,
    )
    if entry_index is None:
        return None

    if not _replay_trade_passes_filters(
        bars=bars,
        entry_index=entry_index,
        filters=filters,
        minute_context=minute_context,
        fundamental_context=fundamental_context,
    ):
        return None

    entry_bar = bars[entry_index]
    minute_entry = _find_replay_intraday_entry(
        market_data_service=market_data_service,
        ts_code=item.symbol,
        entry_time=_to_market_local_datetime(item.entry_time, "cn_a_share"),
        delay_minutes=int(
            ((filters.get("intraday_entry_timing") or {}).get("delay_entry_minutes") or 0)
        ),
    )
    entry_price = (
        float(minute_entry["entry_price"])
        if minute_entry is not None
        else float(item.entry_price)
        if item.entry_price is not None
        else float(entry_bar.open)
    )
    entry_time_value = minute_entry["entry_time"] if minute_entry is not None else item.entry_time.isoformat()
    quantity = _infer_replay_trade_quantity(item)
    exit_index_limit = min(len(bars) - 1, entry_index + max_holding_bars)
    stop_loss_pct = risk.get("stop_loss_pct")
    take_profit_pct = risk.get("take_profit_pct")
    minute_entry_used = minute_entry is not None
    minute_exit_used = False

    selected_exit_bar = bars[exit_index_limit]
    exit_price = float(selected_exit_bar.close)
    exit_reason = "max_holding_bars"
    exit_time_value: str | None = None
    for bar_index in range(entry_index + 1, exit_index_limit + 1):
        current_bar = bars[bar_index]
        if current_bar.is_suspended or current_bar.is_limit_down:
            continue
        if isinstance(stop_loss_pct, (int, float)) or isinstance(take_profit_pct, (int, float)):
            stop_price = (
                entry_price * (1.0 + float(stop_loss_pct))
                if isinstance(stop_loss_pct, (int, float))
                else None
            )
            take_profit_price = (
                entry_price * (1.0 + float(take_profit_pct))
                if isinstance(take_profit_pct, (int, float))
                else None
            )
            minute_stop = _find_replay_intraday_threshold_exit(
                market_data_service=market_data_service,
                ts_code=item.symbol,
                trade_date=date.fromisoformat(current_bar.trade_date),
                stop_price=stop_price if isinstance(stop_loss_pct, (int, float)) else None,
                take_profit_price=take_profit_price,
            )
            if minute_stop is not None:
                selected_exit_bar = current_bar
                exit_price = minute_stop["exit_price"]
                exit_reason = minute_stop["exit_reason"]
                exit_time_value = minute_stop["exit_time"]
                minute_exit_used = True
                break
            if isinstance(stop_loss_pct, (int, float)) and float(current_bar.low) <= stop_price:
                selected_exit_bar = current_bar
                exit_price = stop_price
                exit_reason = "stop_loss_intrabar"
                break
            if isinstance(take_profit_pct, (int, float)) and take_profit_price is not None and float(current_bar.high) >= take_profit_price:
                selected_exit_bar = current_bar
                exit_price = take_profit_price
                exit_reason = "take_profit_intrabar"
                break
        selected_exit_bar = current_bar
        exit_price = float(current_bar.close)

    pnl = (exit_price - entry_price) * quantity
    entry_time_for_holding = item.entry_time
    if minute_entry is not None:
        try:
            entry_time_for_holding = datetime.fromisoformat(minute_entry["entry_time"].replace("Z", "+00:00"))
        except ValueError:
            entry_time_for_holding = item.entry_time
    if exit_time_value:
        try:
            holding_minutes = max(
                (
                    datetime.fromisoformat(exit_time_value.replace("Z", "+00:00")).replace(tzinfo=None)
                    - entry_time_for_holding.replace(tzinfo=None)
                ).total_seconds()
                / 60.0,
                1.0,
            )
        except ValueError:
            holding_minutes = float(
                max(
                    (date.fromisoformat(selected_exit_bar.trade_date) - date.fromisoformat(entry_bar.trade_date)).days,
                    1,
                )
                * 24
                * 60
            )
    else:
        holding_bars = max(
            (date.fromisoformat(selected_exit_bar.trade_date) - date.fromisoformat(entry_bar.trade_date)).days,
            1,
        )
        holding_minutes = float(holding_bars * 24 * 60)
    return {
        "trade_id": item.trade_id,
        "symbol": item.symbol,
        "side": item.side,
        "entry_time": entry_time_value,
        "exit_time": exit_time_value or selected_exit_bar.trade_date,
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "holding_minutes": round(holding_minutes, 2),
        "holding_label": _format_holding_label(holding_minutes),
        "pnl": round(pnl, 2),
        "pnl_pct": round(((exit_price - entry_price) / entry_price) * 100.0, 2) if entry_price else None,
        "exit_reason": exit_reason,
        "minute_stop_used": minute_exit_used,
        "minute_entry_used": minute_entry_used,
        "minute_exit_used": minute_exit_used,
    }


def _find_replay_intraday_entry(
    *,
    market_data_service: MarketDataService,
    ts_code: str,
    entry_time: datetime,
    delay_minutes: int = 0,
) -> dict[str, Any] | None:
    session_start = datetime.combine(entry_time.date(), datetime.min.time()).replace(hour=9, minute=30)
    session_end = datetime.combine(entry_time.date(), datetime.min.time()).replace(hour=15, minute=0)
    target_time = entry_time + timedelta(minutes=max(delay_minutes, 0))
    minute_bars, metadata = market_data_service.load_minute_window(
        ts_code=ts_code,
        start_time=session_start,
        end_time=session_end,
        adjustment_mode="qfq",
    )
    if metadata.get("status") != "ready" or not minute_bars:
        return None
    for bar in minute_bars:
        try:
            trade_time = datetime.fromisoformat(bar.trade_time.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue
        if trade_time >= target_time:
            return {
                "entry_time": bar.trade_time,
                "entry_price": float(bar.open),
            }
    return None


def _find_replay_intraday_threshold_exit(
    *,
    market_data_service: MarketDataService,
    ts_code: str,
    trade_date: date,
    stop_price: float | None,
    take_profit_price: float | None,
) -> dict[str, Any] | None:
    session_start = datetime.combine(trade_date, datetime.min.time()).replace(hour=9, minute=30)
    session_end = datetime.combine(trade_date, datetime.min.time()).replace(hour=15, minute=0)
    minute_bars, metadata = market_data_service.load_minute_window(
        ts_code=ts_code,
        start_time=session_start,
        end_time=session_end,
        adjustment_mode="qfq",
    )
    if metadata.get("status") != "ready" or not minute_bars:
        return None
    for bar in minute_bars:
        low = float(bar.low)
        high = float(bar.high)
        stop_hit = stop_price is not None and low <= float(stop_price)
        take_hit = take_profit_price is not None and high >= float(take_profit_price)
        if stop_hit and take_hit:
            return {
                "exit_time": bar.trade_time,
                "exit_price": float(stop_price),
                "exit_reason": "stop_loss_intraday_minute_conflict",
            }
        if stop_hit:
            return {
                "exit_time": bar.trade_time,
                "exit_price": float(stop_price),
                "exit_reason": "stop_loss_intraday_minute",
            }
        if take_hit:
            return {
                "exit_time": bar.trade_time,
                "exit_price": float(take_profit_price),
                "exit_reason": "take_profit_intraday_minute",
            }
    return None


def _replay_trade_passes_filters(
    *,
    bars: list[Any],
    entry_index: int,
    filters: dict[str, Any],
    minute_context: dict[str, Any] | None,
    fundamental_context: dict[str, Any] | None,
) -> bool:
    entry_bar = bars[entry_index]
    prior_bars = bars[max(0, entry_index - 5):entry_index]
    ma5 = (
        sum(float(bar.close) for bar in prior_bars) / len(prior_bars)
        if prior_bars
        else float(entry_bar.close)
    )
    start_bar = prior_bars[0] if prior_bars else entry_bar
    prior_return_pct = (
        ((float(entry_bar.close) - float(start_bar.close)) / float(start_bar.close)) * 100.0
        if float(start_bar.close) != 0
        else 0.0
    )
    avg_volume = (
        sum(float(bar.volume or 0.0) for bar in prior_bars) / len(prior_bars)
        if prior_bars
        else 0.0
    )
    volume_ratio = (float(entry_bar.volume or 0.0) / avg_volume) if avg_volume else None
    trend_regime = "trend" if float(entry_bar.close) >= ma5 and prior_return_pct >= 0 else "range"

    market_regime = filters.get("market_regime") or {}
    if market_regime.get("preferred") == "trend" and trend_regime != "trend":
        return False

    trend_confirmation = filters.get("trend_confirmation") or {}
    if trend_confirmation and float(entry_bar.close) < ma5:
        return False

    extension_guard = filters.get("extension_guard") or {}
    if "max_prior_return_pct" in extension_guard and prior_return_pct > float(extension_guard["max_prior_return_pct"]):
        return False

    volume_heat_guard = filters.get("volume_heat_guard") or {}
    if volume_ratio is not None and "max_value" in volume_heat_guard and volume_ratio > float(volume_heat_guard["max_value"]):
        return False

    intraday_entry_timing = filters.get("intraday_entry_timing") or {}
    if minute_context and "max_first_15m_return_pct" in intraday_entry_timing:
        if float(minute_context.get("first_15m_return_pct") or 0.0) > float(intraday_entry_timing["max_first_15m_return_pct"]):
            return False
    if minute_context and "min_first_15m_return_pct" in intraday_entry_timing:
        if float(minute_context.get("first_15m_return_pct") or 0.0) < float(intraday_entry_timing["min_first_15m_return_pct"]):
            return False
    if minute_context and "min_last_15m_return_pct" in intraday_entry_timing:
        if float(minute_context.get("last_15m_return_pct") or 0.0) < float(intraday_entry_timing["min_last_15m_return_pct"]):
            return False

    intraday_structure = filters.get("intraday_structure") or {}
    if minute_context:
        min_close_position_pct = intraday_structure.get("min_close_position_pct")
        if isinstance(min_close_position_pct, (int, float)) and float(minute_context.get("close_position_pct") or 0.0) < float(min_close_position_pct):
            return False
        min_up_bar_ratio = intraday_structure.get("min_up_bar_ratio")
        if isinstance(min_up_bar_ratio, (int, float)) and float(minute_context.get("up_bar_ratio") or 0.0) < float(min_up_bar_ratio):
            return False
        max_peak_to_close_drawdown_pct = intraday_structure.get("max_peak_to_close_drawdown_pct")
        if (
            isinstance(max_peak_to_close_drawdown_pct, (int, float))
            and float(minute_context.get("peak_to_close_drawdown_pct") or 0.0) > float(max_peak_to_close_drawdown_pct)
        ):
            return False

    fundamental_guard = filters.get("fundamental_guard") or {}
    quality_filter = filters.get("quality_filter") or {}
    if fundamental_context:
        pe_ttm = fundamental_context.get("pe_ttm")
        if isinstance(pe_ttm, (int, float)) and "max_pe_ttm" in fundamental_guard and pe_ttm > float(fundamental_guard["max_pe_ttm"]):
            return False
        debt_to_assets = fundamental_context.get("debt_to_assets")
        if isinstance(debt_to_assets, (int, float)) and "max_debt_to_assets" in fundamental_guard and debt_to_assets > float(fundamental_guard["max_debt_to_assets"]):
            return False
        roe = fundamental_context.get("roe")
        if isinstance(roe, (int, float)) and "min_roe" in quality_filter and roe < float(quality_filter["min_roe"]):
            return False
        grossprofit_margin = fundamental_context.get("grossprofit_margin")
        if isinstance(grossprofit_margin, (int, float)) and "min_grossprofit_margin" in quality_filter and grossprofit_margin < float(quality_filter["min_grossprofit_margin"]):
            return False
        op_yoy = fundamental_context.get("op_yoy")
        if isinstance(op_yoy, (int, float)) and "min_op_yoy" in quality_filter and op_yoy < float(quality_filter["min_op_yoy"]):
            return False

    return True


def _infer_replay_trade_quantity(item: TradeRecordItem) -> float:
    if item.entry_price is not None and item.exit_price is not None:
        price_delta = float(item.exit_price) - float(item.entry_price)
        if abs(price_delta) > 1e-9:
            inferred = abs(float(item.pnl) / price_delta)
            if inferred > 0:
                return inferred
    return 100.0


def _build_replay_trade_rows_metrics(trade_rows: list[dict[str, Any]]) -> dict[str, Any]:
    trade_count = len(trade_rows)
    total_pnl = sum(float(item["pnl"]) for item in trade_rows)
    wins = [item for item in trade_rows if float(item["pnl"]) > 0]
    losses = [item for item in trade_rows if float(item["pnl"]) <= 0]
    pnl_values = [float(item["pnl"]) for item in trade_rows]
    max_drawdown_pct = _build_replay_max_drawdown_pct(pnl_values)
    sharpe_like = _build_replay_sharpe_like(pnl_values)
    avg_pnl = (total_pnl / trade_count) if trade_count else 0.0
    win_rate_pct = (len(wins) / trade_count * 100.0) if trade_count else 0.0
    minute_entry_aligned_count = sum(1 for item in trade_rows if item.get("minute_entry_used"))
    minute_exit_triggered_count = sum(1 for item in trade_rows if item.get("minute_exit_used"))
    return {
        "trade_count": trade_count,
        "total_pnl": round(total_pnl, 2),
        "win_rate_pct": round(win_rate_pct, 2),
        "avg_pnl": round(avg_pnl, 2),
        "profit_count": len(wins),
        "loss_count": len(losses),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_like": round(sharpe_like, 2),
        "minute_entry_aligned_count": minute_entry_aligned_count,
        "minute_exit_triggered_count": minute_exit_triggered_count,
    }


def _select_replay_objective_records(
    *,
    records: list[TradeRecordItem],
    objective: str,
    best_side: tuple[str, dict[str, float]],
    worst_side: tuple[str, dict[str, float]],
    has_side_comparison: bool,
    avg_loss: float,
    avg_holding_minutes: float,
    avg_loss_holding_minutes: float,
    daily_context_by_trade_id: dict[str, dict[str, Any]],
    minute_context_by_trade_id: dict[str, dict[str, Any]],
    fundamental_context_by_trade_id: dict[str, dict[str, Any]],
) -> tuple[list[TradeRecordItem], str]:
    if not records:
        return [], "当前样本为空，无法生成对照版本。"
    ordered_records = sorted(records, key=lambda item: item.exit_time or item.entry_time)
    weak_side = worst_side[0]
    strong_side = best_side[0]
    negative_records = [item for item in ordered_records if item.pnl <= 0]
    worst_loss_value = min((item.pnl for item in ordered_records), default=0.0)
    worst_loss_cutoff = avg_loss if avg_loss < 0 else worst_loss_value
    long_loss_minutes = max(avg_loss_holding_minutes, avg_holding_minutes)
    target_count_map = {
        "win_rate_max": max(1, len([item for item in ordered_records if item.pnl > 0])),
        "max_drawdown_min": max(1, math.ceil(len(ordered_records) * 0.6)),
        "total_return_max": max(1, math.ceil(len(ordered_records) * 0.75)),
        "sharpe_max": max(1, math.ceil(len(ordered_records) * 0.67)),
    }
    scored_records = [
        (
            item,
            _score_replay_record_for_objective(
                item=item,
                objective=objective,
                weak_side=weak_side,
                strong_side=strong_side,
                has_side_comparison=has_side_comparison,
                worst_loss_cutoff=worst_loss_cutoff,
                long_loss_minutes=long_loss_minutes,
                daily_context=daily_context_by_trade_id.get(item.trade_id),
                minute_context=minute_context_by_trade_id.get(item.trade_id),
                fundamental_context=fundamental_context_by_trade_id.get(item.trade_id),
            ),
        )
        for item in ordered_records
    ]
    selected = [
        item
        for item, _score in sorted(scored_records, key=lambda pair: pair[1], reverse=True)[: target_count_map[objective]]
    ]
    selected.sort(key=lambda item: item.exit_time or item.entry_time)
    if not selected:
        selected = [max(ordered_records, key=lambda item: item.pnl)]
    removed_count = len(ordered_records) - len(selected)
    if objective == "win_rate_max":
        note = (
            f"这个版本按样本筛选回放，结合盈亏、方向、持有、分钟节奏和基本面上下文评分，只保留更接近高胜率的出手。"
            f"本次共剔除 {removed_count} 笔负收益记录，用于对照确认。"
        )
    elif objective == "max_drawdown_min":
        note = (
            f"这个版本按样本筛选回放，结合上下文评分优先剔除导致回撤扩大的长持亏损、盘中过热追入和弱基本面样本。"
            f"本次共剔除 {removed_count} 笔记录，用于对照确认。"
        )
    elif objective == "total_return_max":
        note = (
            f"这个版本按样本筛选回放，优先保留总收益贡献更高且上下文质量更高的交易，并剔除最拖累收益的样本。"
            f"本次共剔除 {removed_count} 笔记录，用于对照确认。"
        )
    else:
        note = (
            f"这个版本按样本筛选回放，结合盈亏、持有、分钟节奏和基本面上下文评分，优先平衡收益质量、回撤和稳定性。"
            f"本次共剔除 {removed_count} 笔弱质量样本，用于对照确认。"
        )
    return selected, note


def _group_replay_contexts_by_trade_id(contexts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in contexts:
        trade_id = item.get("trade_id")
        if isinstance(trade_id, str) and trade_id:
            grouped[trade_id] = item
    return grouped


def _score_replay_record_for_objective(
    *,
    item: TradeRecordItem,
    objective: str,
    weak_side: str,
    strong_side: str,
    has_side_comparison: bool,
    worst_loss_cutoff: float,
    long_loss_minutes: float,
    daily_context: dict[str, Any] | None,
    minute_context: dict[str, Any] | None,
    fundamental_context: dict[str, Any] | None,
) -> float:
    score = float(item.pnl)
    holding_minutes = _holding_minutes(item.entry_time, item.exit_time)

    if objective == "sharpe_max":
        if item.pnl <= 0:
            score -= 20.0
        if holding_minutes >= long_loss_minutes and item.pnl <= 0:
            score -= 20.0
    elif objective == "win_rate_max":
        score = 80.0 if item.pnl > 0 else -80.0
        score -= max(holding_minutes - 60.0, 0.0) * 0.05 if item.pnl <= 0 else 0.0
    elif objective == "max_drawdown_min":
        score = -abs(item.pnl)
        if item.pnl > 0:
            score += 50.0
        if item.pnl < worst_loss_cutoff:
            score -= 30.0
        if holding_minutes >= long_loss_minutes and item.pnl <= 0:
            score -= 20.0
    elif objective == "total_return_max":
        score = float(item.pnl) * 1.25

    if has_side_comparison and weak_side != strong_side and item.side == weak_side and item.pnl <= 0:
        score -= 25.0

    if daily_context:
        if daily_context.get("above_ma5"):
            score += 10.0
        else:
            score -= 8.0
        if daily_context.get("trend_regime") == "trend":
            score += 8.0
        else:
            score -= 10.0 if objective in {"sharpe_max", "max_drawdown_min", "win_rate_max"} else 5.0
        prior_return_pct = daily_context.get("prior_return_pct")
        if isinstance(prior_return_pct, (int, float)) and prior_return_pct >= 4.0:
            score -= 12.0 if objective != "total_return_max" else 6.0
        volume_ratio = daily_context.get("volume_ratio")
        if isinstance(volume_ratio, (int, float)) and volume_ratio >= 1.8:
            score -= 10.0 if objective != "total_return_max" else 4.0

    if minute_context:
        first_15m_return_pct = minute_context.get("first_15m_return_pct")
        if isinstance(first_15m_return_pct, (int, float)) and first_15m_return_pct >= 1.0:
            score -= 14.0 if objective != "total_return_max" else 6.0
        close_position_pct = minute_context.get("close_position_pct")
        if isinstance(close_position_pct, (int, float)) and close_position_pct < 40.0:
            score -= 12.0 if objective != "total_return_max" else 5.0
        up_bar_ratio = minute_context.get("up_bar_ratio")
        if isinstance(up_bar_ratio, (int, float)) and up_bar_ratio < 0.45:
            score -= 8.0
        last_15m_return_pct = minute_context.get("last_15m_return_pct")
        if isinstance(last_15m_return_pct, (int, float)) and last_15m_return_pct >= 0.0:
            score += 6.0
        peak_to_close_drawdown_pct = minute_context.get("peak_to_close_drawdown_pct")
        if isinstance(peak_to_close_drawdown_pct, (int, float)) and peak_to_close_drawdown_pct >= 1.0:
            score -= 10.0 if objective != "total_return_max" else 4.0

    if fundamental_context:
        pe_ttm = fundamental_context.get("pe_ttm")
        if isinstance(pe_ttm, (int, float)) and pe_ttm >= 35.0:
            score -= 8.0 if objective != "total_return_max" else 3.0
        debt_to_assets = fundamental_context.get("debt_to_assets")
        if isinstance(debt_to_assets, (int, float)) and debt_to_assets >= 60.0:
            score -= 12.0 if objective != "total_return_max" else 5.0
        pb = fundamental_context.get("pb")
        if isinstance(pb, (int, float)) and pb <= 3.0:
            score += 4.0
        roe = fundamental_context.get("roe")
        if isinstance(roe, (int, float)) and roe >= 10.0:
            score += 8.0
        grossprofit_margin = fundamental_context.get("grossprofit_margin")
        if isinstance(grossprofit_margin, (int, float)) and grossprofit_margin >= 25.0:
            score += 6.0
        op_yoy = fundamental_context.get("op_yoy")
        if isinstance(op_yoy, (int, float)) and op_yoy >= 0.0:
            score += 5.0

    return score


def _build_replay_context_suggestions(
    *,
    loss_features: list[dict[str, Any]],
    profit_features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    feature_ids = {item.get("id"): item for item in loss_features + profit_features if item.get("id")}

    def add_suggestion(title: str, description: str, dsl_patch: dict[str, Any]) -> None:
        if title in seen_titles:
            return
        seen_titles.add(title)
        suggestions.append(
            {
                "title": title,
                "description": description,
                "dsl_patch": dsl_patch,
            }
        )

    if any(feature_id in feature_ids for feature_id in {"loss_intraday_chase", "loss_first_15m_hot"}):
        add_suggestion(
            "收紧盘中过热追入",
            "亏损样本更常出现在开盘前15分钟已经明显拉升的场景。建议增加盘中过热过滤，只在前15分钟不过热时允许开仓。",
            {
                "filters": {
                    "intraday_entry_timing": {
                        "enabled": True,
                        "max_first_15m_return_pct": 1.0,
                    }
                }
            },
        )
    if any(feature_id in feature_ids for feature_id in {"loss_close_weak", "loss_bar_structure_weak", "profit_last_15m_stable"}):
        add_suggestion(
            "加入盘中结构确认",
            "分钟级样本显示亏损更常伴随窗口末端走弱。建议只在窗口收盘位置和阳线占比都达标时保留开仓。",
            {
                "filters": {
                    "intraday_structure": {
                        "enabled": True,
                        "min_close_position_pct": 50,
                        "min_up_bar_ratio": 0.5,
                    }
                }
            },
        )
    if any(feature_id in feature_ids for feature_id in {"loss_volume_chase", "loss_after_extended_move"}):
        add_suggestion(
            "避免高位放量后追入",
            "日线样本显示亏损更常出现在短期涨幅过大或量能过热后。建议限制入场前窗口涨幅和量比上限。",
            {
                "filters": {
                    "extension_guard": {
                        "enabled": True,
                        "max_prior_return_pct": 4.0,
                    },
                    "volume_heat_guard": {
                        "enabled": True,
                        "max_value": 1.8,
                    },
                }
            },
        )
    if any(feature_id in feature_ids for feature_id in {"loss_range_regime", "profit_trend_regime", "profit_above_ma5"}):
        add_suggestion(
            "只在趋势环境里保留开仓",
            "样本显示趋势环境和站上均线时更容易保留盈利结构。建议把趋势环境和均线同向作为硬过滤。",
            {
                "filters": {
                    "market_regime": {
                        "enabled": True,
                        "preferred": "trend",
                    },
                    "trend_confirmation": {
                        "enabled": True,
                        "timeframe": "1d",
                        "rule": "only_trade_above_ma5_in_trend",
                    },
                }
            },
        )
    if any(feature_id in feature_ids for feature_id in {"loss_high_pe", "loss_higher_debt", "profit_higher_roe", "profit_higher_margin", "profit_higher_growth"}):
        add_suggestion(
            "加入基本面质量过滤",
            "基本面样本显示高负债、弱盈利质量的标的更容易拖累结果。建议把 ROE、毛利率、营收增速和资产负债率加入开仓过滤。",
            {
                "filters": {
                    "fundamental_guard": {
                        "enabled": True,
                        "max_pe_ttm": 35,
                        "max_debt_to_assets": 55,
                    },
                    "quality_filter": {
                        "enabled": True,
                        "min_roe": 10,
                        "min_grossprofit_margin": 25,
                        "min_op_yoy": 0,
                    },
                }
            },
        )
    return suggestions


def _build_replay_parameter_changes(
    suggestion_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for rule in suggestion_rules:
        patch = rule.get("dsl_patch") or {}
        risk = patch.get("risk") or {}
        filters = patch.get("filters") or {}
        position = patch.get("position") or {}
        if "stop_loss_pct" in risk:
            items.append(
                {
                    "parameter": "止损比例",
                    "old_value": "当前未明确限制",
                    "new_value": risk["stop_loss_pct"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        if "max_holding_bars" in risk:
            items.append(
                {
                    "parameter": "最大持有K线数",
                    "old_value": "当前未明确限制",
                    "new_value": risk["max_holding_bars"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        volume_confirmation = filters.get("volume_confirmation") or {}
        if "value" in volume_confirmation:
            items.append(
                {
                    "parameter": "量比阈值",
                    "old_value": "当前未明确限制",
                    "new_value": volume_confirmation["value"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        volume_heat_guard = filters.get("volume_heat_guard") or {}
        if "max_value" in volume_heat_guard:
            items.append(
                {
                    "parameter": "量比上限",
                    "old_value": "当前未明确限制",
                    "new_value": volume_heat_guard["max_value"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        extension_guard = filters.get("extension_guard") or {}
        if "max_prior_return_pct" in extension_guard:
            items.append(
                {
                    "parameter": "入场前窗口涨幅上限",
                    "old_value": "当前未明确限制",
                    "new_value": extension_guard["max_prior_return_pct"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        trend_confirmation = filters.get("trend_confirmation") or {}
        if "timeframe" in trend_confirmation or "entry_timeframe" in trend_confirmation:
            items.append(
                {
                    "parameter": "趋势确认周期",
                    "old_value": "当前未明确限制",
                    "new_value": trend_confirmation.get("entry_timeframe")
                    or trend_confirmation.get("timeframe"),
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        intraday_entry_timing = filters.get("intraday_entry_timing") or {}
        if "max_first_15m_return_pct" in intraday_entry_timing:
            items.append(
                {
                    "parameter": "前15分钟涨幅上限",
                    "old_value": "当前未明确限制",
                    "new_value": intraday_entry_timing["max_first_15m_return_pct"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        intraday_structure = filters.get("intraday_structure") or {}
        if "min_close_position_pct" in intraday_structure:
            items.append(
                {
                    "parameter": "分钟窗口收盘位置下限",
                    "old_value": "当前未明确限制",
                    "new_value": intraday_structure["min_close_position_pct"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        if "min_up_bar_ratio" in intraday_structure:
            items.append(
                {
                    "parameter": "分钟阳线占比下限",
                    "old_value": "当前未明确限制",
                    "new_value": intraday_structure["min_up_bar_ratio"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        market_regime = filters.get("market_regime") or {}
        if "preferred" in market_regime:
            items.append(
                {
                    "parameter": "市场环境偏好",
                    "old_value": "当前未明确限制",
                    "new_value": market_regime["preferred"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        fundamental_guard = filters.get("fundamental_guard") or {}
        if "max_pe_ttm" in fundamental_guard:
            items.append(
                {
                    "parameter": "PE(TTM) 上限",
                    "old_value": "当前未明确限制",
                    "new_value": fundamental_guard["max_pe_ttm"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        if "max_debt_to_assets" in fundamental_guard:
            items.append(
                {
                    "parameter": "资产负债率上限",
                    "old_value": "当前未明确限制",
                    "new_value": fundamental_guard["max_debt_to_assets"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        quality_filter = filters.get("quality_filter") or {}
        if "min_roe" in quality_filter:
            items.append(
                {
                    "parameter": "ROE 下限",
                    "old_value": "当前未明确限制",
                    "new_value": quality_filter["min_roe"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        if "min_grossprofit_margin" in quality_filter:
            items.append(
                {
                    "parameter": "毛利率下限",
                    "old_value": "当前未明确限制",
                    "new_value": quality_filter["min_grossprofit_margin"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        if "min_op_yoy" in quality_filter:
            items.append(
                {
                    "parameter": "营收增速下限",
                    "old_value": "当前未明确限制",
                    "new_value": quality_filter["min_op_yoy"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
        if "reduced_side_size_ratio" in position:
            items.append(
                {
                    "parameter": "弱势方向仓位",
                    "old_value": "当前等同常规仓位",
                    "new_value": position["reduced_side_size_ratio"],
                    "reason": rule.get("title", "复盘建议"),
                }
            )
    return items


def _build_replay_condition_replacements(
    suggestion_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    replacements: list[dict[str, Any]] = []
    for rule in suggestion_rules:
        patch = rule.get("dsl_patch") or {}
        filters = patch.get("filters") or {}
        if "trend_confirmation" in filters:
            timeframe = (
                filters["trend_confirmation"].get("entry_timeframe")
                or filters["trend_confirmation"].get("timeframe")
                or "更高周期"
            )
            replacements.append(
                {
                    "from": "原规则未强制趋势确认",
                    "to": f"入场前先确认 {timeframe} 趋势同向",
                    "reason": rule.get("title", "趋势过滤建议"),
                }
            )
        if "volume_confirmation" in filters:
            replacements.append(
                {
                    "from": "原规则未做量能过滤",
                    "to": f"仅在量比 >= {filters['volume_confirmation'].get('value')} 时允许开仓",
                    "reason": rule.get("title", "量能过滤建议"),
                }
            )
        if "volume_heat_guard" in filters:
            replacements.append(
                {
                    "from": "原规则未限制量比过热场景",
                    "to": f"仅在量比 <= {filters['volume_heat_guard'].get('max_value')} 时允许开仓",
                    "reason": rule.get("title", "量比过热过滤建议"),
                }
            )
        if "extension_guard" in filters:
            replacements.append(
                {
                    "from": "原规则未限制短期涨幅过大后的追入",
                    "to": (
                        "仅在入场前窗口涨幅 "
                        f"<= {filters['extension_guard'].get('max_prior_return_pct')}% 时允许开仓"
                    ),
                    "reason": rule.get("title", "短期过热过滤建议"),
                }
            )
        if "weak_open_filter" in filters:
            replacements.append(
                {
                    "from": "原规则未限制弱开场景",
                    "to": "加入弱开过滤，避免开盘承接不足时贸然入场",
                    "reason": rule.get("title", "弱开过滤建议"),
                }
            )
        if "intraday_entry_timing" in filters:
            replacements.append(
                {
                    "from": "原规则未限制开盘前短时拉升后的追入",
                    "to": (
                        "仅在前15分钟涨幅 "
                        f"<= {filters['intraday_entry_timing'].get('max_first_15m_return_pct')}% 时允许开仓"
                    ),
                    "reason": rule.get("title", "盘中过热过滤建议"),
                }
            )
        if "intraday_structure" in filters:
            replacements.append(
                {
                    "from": "原规则未要求分钟级结构确认",
                    "to": (
                        "仅在分钟窗口收盘位置和阳线占比都达标时保留开仓"
                    ),
                    "reason": rule.get("title", "分钟级结构过滤建议"),
                }
            )
        if "market_regime" in filters:
            replacements.append(
                {
                    "from": "原规则未限制市场环境",
                    "to": f"仅在 {filters['market_regime'].get('preferred')} 环境里保留开仓",
                    "reason": rule.get("title", "市场环境过滤建议"),
                }
            )
        if "fundamental_guard" in filters or "quality_filter" in filters:
            replacements.append(
                {
                    "from": "原规则未要求基本面质量过滤",
                    "to": "加入估值、负债率、ROE、毛利率和营收增速的基本面质量过滤",
                    "reason": rule.get("title", "基本面过滤建议"),
                }
            )
    return replacements


def _infer_trade_pnl_pct(item: TradeRecordItem) -> float | None:
    if item.entry_price and item.entry_price != 0 and item.exit_price is not None:
        return round((item.exit_price - item.entry_price) / item.entry_price * 100.0, 2)
    return None


def _format_holding_label(value: float) -> str:
    if value >= 1440:
        return f"{round(value / 1440, 1)}天"
    if value >= 60:
        return f"{round(value / 60, 1)}小时"
    return f"{round(value, 1)}分钟"


def _holding_minutes(entry_time: datetime, exit_time: datetime | None) -> float:
    if exit_time is None:
        return 0.0
    return max((exit_time - entry_time).total_seconds() / 60.0, 0.0)


def _infer_replay_market(records: list[TradeRecordItem]) -> str:
    normalized_symbols = [item.symbol.upper() for item in records]
    if any(symbol.endswith((".SH", ".SZ", ".BJ")) for symbol in normalized_symbols):
        return "cn_a_share"
    if any(symbol.endswith("USDT") or symbol.endswith("PERP") for symbol in normalized_symbols):
        return "crypto"
    if any("XAU" in symbol or "GOLD" in symbol for symbol in normalized_symbols):
        return "london_gold"
    return "global"


def _market_supports_short(market: str) -> bool:
    return market != "cn_a_share"


def _describe_trade_side(side: str, market: str) -> str:
    if market == "cn_a_share":
        return "反向卖出记录" if side == "short" else "买入后卖出交易"
    return "做空交易" if side == "short" else "做多交易"


def _build_side_optimization_description(
    *,
    side: str,
    side_label: str,
    stats: dict[str, float],
    market: str,
) -> str:
    if market == "cn_a_share" and side == "short":
        return (
            f"{side_label}当前共 {int(stats['count'])} 笔，累计盈亏 {stats['pnl_sum']:.2f}。"
            "当前市场默认不支持普通股票做空，建议先核对交割单方向映射，"
            "确认这部分记录是否应单独归入融资融券或衍生品策略。"
        )
    return (
        f"{side_label}当前共 {int(stats['count'])} 笔，累计盈亏 {stats['pnl_sum']:.2f}。"
        "建议先把该方向仓位降到优势方向的一半，并增加趋势一致性过滤，"
        "例如只在更大周期均线同向时允许入场。"
    )


def _build_side_optimization_patch(
    *,
    best_side: str,
    worst_side: str,
    market: str,
) -> dict[str, Any]:
    if market == "cn_a_share" and worst_side == "short":
        return {
            "validation": {
                "market_supports_short": False,
                "action": "verify_side_mapping_or_split_strategy",
            }
        }
    return {
        "position": {
            "preferred_side": best_side,
            "reduced_side": worst_side,
            "reduced_side_size_ratio": 0.5,
        },
        "filters": {
            "trend_confirmation": {
                "enabled": True,
                "timeframe": "30m",
                "rule": "only_trade_with_higher_timeframe_trend",
            }
        },
        "risk": {
            "max_consecutive_losses_by_side": {
                worst_side: 2,
            }
        },
    }


def _build_single_side_suggestions(
    *,
    side: str,
    side_label: str,
    market: str,
    stats: dict[str, float],
) -> list[dict[str, Any]]:
    if market == "cn_a_share":
        return [
            {
                "title": "只在日线趋势同向时入场",
                "description": (
                    f"当前样本全部为{side_label}，共 {int(stats['count'])} 笔。"
                    "A 股单方向策略先不要急着扩方向，建议只在日线 20 均线向上、"
                    "且前一交易日收盘仍站在 10 日均线之上时才允许开仓。"
                ),
                "dsl_patch": {
                    "filters": {
                        "trend_confirmation": {
                            "enabled": True,
                            "timeframe": "1d",
                            "rules": [
                                "sma_20_slope_positive",
                                "previous_close_above_sma_10",
                            ],
                        }
                    }
                },
            },
            {
                "title": "加入量能和弱开过滤",
                "description": (
                    "A 股里单方向策略常见问题是缩量追涨和弱开承接不足。"
                    "建议只在量比不低于 1.2，且开盘不弱于前收 0.5% 以上时入场，"
                    "把弱开、无量的信号先过滤掉。"
                ),
                "dsl_patch": {
                    "filters": {
                        "volume_confirmation": {
                            "enabled": True,
                            "indicator": "volume_ratio",
                            "operator": ">=",
                            "value": 1.2,
                        },
                        "weak_open_filter": {
                            "enabled": True,
                            "min_open_vs_prev_close_pct": -0.005,
                        },
                    }
                },
            },
            {
                "title": "收紧止损并缩短持有周期",
                "description": (
                    "A 股单方向样本更适合先把亏损截断。"
                    "建议先把止损收紧到 2%，最长持有缩到 8 根 K 线，"
                    "同时把止盈先收在 6% 左右，再用更多样本验证是否需要放宽。"
                ),
                "dsl_patch": {
                    "risk": {
                        "stop_loss_pct": -0.02,
                        "take_profit_pct": 0.06,
                        "max_holding_bars": 8,
                    }
                },
            },
        ]
    if market == "crypto":
        return [
            {
                "title": "只在更高周期趋势一致时追随动量",
                "description": (
                    f"当前样本全部为{side_label}，更适合先做顺势约束。"
                    "建议只有在 1 小时趋势与 15 分钟入场信号同向时才开仓，"
                    "避免在震荡区间里反复追单。"
                ),
                "dsl_patch": {
                    "filters": {
                        "trend_confirmation": {
                            "enabled": True,
                            "entry_timeframe": "15m",
                            "context_timeframe": "1h",
                            "rule": "only_trade_with_higher_timeframe_trend",
                        }
                    }
                },
            },
            {
                "title": "增加波动率过滤和更短的保护止损",
                "description": (
                    "加密货币 7x24 波动大，单方向样本容易被突然扩大的波动吞没。"
                    "建议加入 ATR 或振幅过滤，并把保护止损先收紧到 1.5%，"
                    "同时把最长持有时间缩到 24 根 15 分钟 K 线。"
                ),
                "dsl_patch": {
                    "filters": {
                        "volatility_filter": {
                            "enabled": True,
                            "indicator": "atr_pct",
                            "operator": "<=",
                            "value": 0.03,
                        }
                    },
                    "risk": {
                        "stop_loss_pct": -0.015,
                        "max_holding_bars": 24,
                    },
                },
            },
        ]
    return [
        {
            "title": "先做趋势确认再开仓",
            "description": (
                f"当前样本全部为{side_label}，暂时不能做方向对比。"
                "建议先加更大周期趋势确认，再决定是否保留现有入场信号。"
            ),
            "dsl_patch": {
                "filters": {
                    "trend_confirmation": {
                        "enabled": True,
                        "timeframe": "1d",
                        "rule": "only_trade_with_primary_trend",
                    }
                }
            },
        },
        {
            "title": "收紧风控后继续积累样本",
            "description": (
                "当前更适合先把止损、止盈和最长持有周期收紧，"
                "再继续积累更多同类交易记录。"
            ),
            "dsl_patch": {
                "risk": {
                    "stop_loss_pct": -0.02,
                    "max_holding_bars": 8,
                }
            },
        },
    ]


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
