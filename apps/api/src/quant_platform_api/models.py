from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    LEGACY_COMPLETED = "completed"
    COMPLETED = "succeeded"
    FAILED = "failed"
    CANCELING = "canceling"
    CANCELED = "canceled"
    LEGACY_CANCELLED = "cancelled"
    CANCELLED = "canceled"


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class SuccessEnvelope(BaseModel):
    success: bool = True
    request_id: str
    data: Any
    meta: dict[str, Any] | None = None
    error: None = None


class ErrorEnvelope(BaseModel):
    success: bool = False
    request_id: str
    data: None = None
    meta: None = None
    error: ErrorPayload


class DatasetConfig(BaseModel):
    market: str
    timeframe: str
    asset_type: str = "stock"
    from_: datetime = Field(alias="from")
    to: datetime


class PositionSizingConfig(BaseModel):
    mode: str = "fixed_fraction"
    value: float = 1.0
    max_positions: int = 1
    max_position_pct: float = 1.0
    min_trade_unit: int = 100


class RiskControlConfig(BaseModel):
    take_profit_pct: float = 0.08
    stop_loss_pct: float = -0.03
    max_drawdown_pct: float = -0.12
    max_holding_bars: int = 40


class BacktestExecutionContract(BaseModel):
    initial_capital: float
    fee_bps: int
    slippage_bps: int
    fill_price_rule: str
    intrabar_match_policy: str
    calendar: str
    timezone: str
    adjustment_mode: str
    settlement_policy: str | None = None
    same_day_exit_allowed: bool | None = None
    market_constraint_text: str | None = None
    warmup_bars: int = 20
    position_sizing: PositionSizingConfig = Field(default_factory=PositionSizingConfig)
    risk_controls: RiskControlConfig = Field(default_factory=RiskControlConfig)


class DataSnapshotConfig(BaseModel):
    dataset_snapshot_ref: str
    provider: str | None = None
    coverage_status: str = "ready"
    coverage_pct: float | None = None
    missing_rate_pct: float | None = None
    calendar: str | None = None
    timezone: str | None = None
    warmup_bars: int | None = None
    last_synced_at: datetime | None = None


class DatasetSnapshotRecord(BaseModel):
    dataset_snapshot_ref: str
    market: str
    asset_type: str
    frequency: str
    adjustment_mode: str
    date_from: datetime
    date_to: datetime
    provider: str = "shared_market_store"
    coverage_status: str = "ready"
    created_at: datetime = Field(default_factory=utcnow)


class BacktestCreateRequest(BaseModel):
    strategy_version_id: str
    dataset: DatasetConfig
    execution_contract: BacktestExecutionContract
    data_snapshot: DataSnapshotConfig


class OptimizationCreateRequest(BaseModel):
    strategy_version_id: str
    search_space: dict[str, list[int | float]]
    objective: str
    dataset: DatasetConfig
    data_snapshot: DataSnapshotConfig
    execution_contract: BacktestExecutionContract


class ReplayCreateRequest(BaseModel):
    upload_id: str
    focus_dimensions: list[str]
    custom_prompt: str | None = None
    data_snapshot: DataSnapshotConfig | None = None
    analysis_options: dict[str, Any] = Field(default_factory=dict)


class ProjectCreateRequest(BaseModel):
    title: str
    version_label: str | None = None
    natural_language_prompt: str
    strategy_dsl: dict[str, Any]
    strategy_python: str | None = None


class StrategyGenerateRequest(BaseModel):
    prompt: str
    market: str
    market_scope: str = "cn_equity"
    timeframe: str
    timeframes: list[str] = Field(default_factory=list)
    asset_type: str = "stock"
    preferences: dict[str, Any] = Field(default_factory=dict)
    teaching_mode: bool = False
    clarification_answers: dict[str, str] = Field(default_factory=dict)


class StrategyProjectListItem(BaseModel):
    project_id: str
    version_id: str
    title: str
    natural_language_prompt: str
    created_at: datetime


class TradeUploadCreateResult(BaseModel):
    upload_id: str
    status: str
    detected_columns: list[str]
    upload_kind: str = "csv"


class UserRegisterRequest(BaseModel):
    username: str
    contact: str
    password: str


class UserLoginRequest(BaseModel):
    username: str
    password: str


class MentorAskRequest(BaseModel):
    question: str
    experience_level: str = "beginner"
    market_scope: str | None = None
    current_module: str | None = None
    conversation_history: list[dict[str, str]] = Field(default_factory=list)


class AssistantResearchRequest(BaseModel):
    query: str
    workflow_id: str = "market_map"
    target_symbol: str | None = None
    market_scope: str = "cn_equity"
    research_depth: str = "standard"
    current_module: str | None = None
    conversation_history: list[dict[str, str]] = Field(default_factory=list)


class ClientErrorReportRequest(BaseModel):
    message: str
    source: str = "web"
    category: str = "client_error"
    request_path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AdminUserRoleUpdateRequest(BaseModel):
    role: str


class AdminUserStatusUpdateRequest(BaseModel):
    status: str
    reason: str | None = None


class AdminUserPasswordResetRequest(BaseModel):
    new_password: str


class UserProfile(BaseModel):
    user_id: str
    workspace_id: str
    username: str
    contact: str
    role: str
    status: str = "active"
    status_reason: str | None = None
    created_at: datetime


class TradeUploadParseRequest(BaseModel):
    column_mapping: dict[str, str]


class TradeRecordItem(BaseModel):
    trade_id: str
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime | None
    pnl: float
    entry_price: float | None = None
    exit_price: float | None = None
    notes: str | None = None


class ManualTradeRecordInput(BaseModel):
    symbol: str
    side: str = "long"
    entry_time: datetime
    exit_time: datetime | None = None
    pnl: float = 0.0
    entry_price: float | None = None
    exit_price: float | None = None
    notes: str | None = None


class ManualTradeTextParseRequest(BaseModel):
    text: str
    market: str = "cn_equity"
    adjustment_mode: str = "qfq"


class TradeUploadManualCreateRequest(BaseModel):
    source_type: str = "manual"
    source_file_name: str | None = None
    source_notes: str | None = None
    market: str | None = None
    records: list[ManualTradeRecordInput] = Field(default_factory=list)


class TradeUploadRecord(BaseModel):
    upload_id: str = Field(default_factory=lambda: f"upload_{uuid4().hex[:8]}")
    user_id: str
    workspace_id: str
    source_file_name: str
    raw_text: str
    upload_kind: str = "csv"
    status: str = "uploaded"
    detected_columns: list[str] = Field(default_factory=list)
    column_mapping: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    records: list[TradeRecordItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class TaskCreatedResponse(BaseModel):
    id: str
    status: TaskStatus
    state: TaskStatus
    progress_pct: int
    config_revision: str
    status_url: str
    result_url: str


class BacktestResult(BaseModel):
    backtest_run_id: str
    status: TaskStatus
    state: TaskStatus
    progress_pct: int
    config_revision: str
    dataset_snapshot_ref: str
    engine_version: str
    backtest_config: dict[str, Any] = Field(default_factory=dict)
    data_snapshot_summary: dict[str, Any] = Field(default_factory=dict)
    data_source: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorPayload | None = None


class OptimizationResult(BaseModel):
    job_id: str
    status: TaskStatus
    state: TaskStatus
    progress_pct: int
    config_revision: str
    best_params: dict[str, Any] = Field(default_factory=dict)
    best_metrics: dict[str, Any] = Field(default_factory=dict)
    trials: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorPayload | None = None


class ReplayResult(BaseModel):
    analysis_id: str
    status: TaskStatus
    state: TaskStatus
    progress_pct: int
    config_revision: str
    dataset_snapshot_ref: str
    feature_snapshot_ref: str | None = None
    analysis_rule_version: str
    summary: str | None = None
    concise_summary: str | None = None
    overview: dict[str, Any] = Field(default_factory=dict)
    winning_patterns: list[dict[str, Any]] = Field(default_factory=list)
    losing_patterns: list[dict[str, Any]] = Field(default_factory=list)
    loss_features: list[dict[str, Any]] = Field(default_factory=list)
    profit_features: list[dict[str, Any]] = Field(default_factory=list)
    objective_versions: list[dict[str, Any]] = Field(default_factory=list)
    counterfactual_cases: list[dict[str, Any]] = Field(default_factory=list)
    parameter_changes: list[dict[str, Any]] = Field(default_factory=list)
    condition_replacements: list[dict[str, Any]] = Field(default_factory=list)
    trade_records: list[dict[str, Any]] = Field(default_factory=list)
    suggestion_rules: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorPayload | None = None


class ProjectVersionCreated(BaseModel):
    project_id: str
    version_id: str


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: str
    user_id: str = ""
    status: TaskStatus = TaskStatus.PENDING
    progress_pct: int = 0
    workspace_id: str = "ws_default"
    environment: str = "dev"
    resource_refs: dict[str, str] = Field(default_factory=dict)
    config_revision: str = ""
    created_by: str = "system"
    request_id: str = ""
    trace_id: str = ""
    idempotency_key: str | None = None
    priority: str = "normal"
    retry_count: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    payload: dict[str, Any]
    result: dict[str, Any] = Field(default_factory=dict)
    error: ErrorPayload | None = None
    error_code: str | None = None
    error_message: str | None = None


class StrategyVersionRecord(BaseModel):
    project_id: str = Field(default_factory=lambda: f"proj_{uuid4().hex[:8]}")
    version_id: str = Field(default_factory=lambda: f"ver_{uuid4().hex[:8]}")
    version_label: str = ""
    user_id: str
    workspace_id: str
    title: str
    natural_language_prompt: str
    strategy_dsl: dict[str, Any]
    strategy_python: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class CustomIndicatorGenerateRequest(BaseModel):
    prompt: str


class CustomIndicatorCreateRequest(BaseModel):
    name: str
    natural_language_prompt: str
    summary: str
    formula_text: str
    python_code: str
    usage_hint: str
    tags: list[str] = Field(default_factory=list)


class CustomIndicatorRecord(BaseModel):
    indicator_id: str = Field(default_factory=lambda: f"cind_{uuid4().hex[:8]}")
    name: str
    natural_language_prompt: str
    summary: str
    formula_text: str
    python_code: str
    usage_hint: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class GlossaryTermCreateRequest(BaseModel):
    term: str
    meaning: str
    example: str | None = None


class GlossaryTermRecord(BaseModel):
    term_id: str = Field(default_factory=lambda: f"term_{uuid4().hex[:8]}")
    term: str
    meaning: str
    example: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class DefaultRuleItem(BaseModel):
    title: str
    description: str


class DefaultRuleSection(BaseModel):
    section_id: str = Field(default_factory=lambda: f"rule_section_{uuid4().hex[:8]}")
    section: str
    items: list[DefaultRuleItem] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)


class DefaultRuleUpdateRequest(BaseModel):
    items: list[DefaultRuleSection] = Field(default_factory=list)


class UserRecord(BaseModel):
    user_id: str = Field(default_factory=lambda: f"user_{uuid4().hex[:10]}")
    username: str
    contact: str
    password_hash: str
    role: str = "user"
    status: str = "active"
    status_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class UserSessionRecord(BaseModel):
    session_id: str = Field(default_factory=lambda: f"sess_{uuid4().hex[:10]}")
    user_id: str
    session_token: str
    created_at: datetime = Field(default_factory=utcnow)


class AuthEventRecord(BaseModel):
    event_id: str = Field(default_factory=lambda: f"auth_{uuid4().hex[:10]}")
    user_id: str | None = None
    username: str
    event_type: str
    outcome: str
    reason: str | None = None
    ip_address: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class AdminAuditLogRecord(BaseModel):
    log_id: str = Field(default_factory=lambda: f"audit_{uuid4().hex[:10]}")
    actor_user_id: str
    target_user_id: str | None = None
    action: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class AppLogRecord(BaseModel):
    log_id: str = Field(default_factory=lambda: f"applog_{uuid4().hex[:10]}")
    level: str = "error"
    source: str = "server"
    category: str = "runtime"
    message: str
    request_path: str | None = None
    user_id: str | None = None
    username: str | None = None
    workspace_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
