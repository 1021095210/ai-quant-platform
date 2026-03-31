from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class SuccessEnvelope(BaseModel):
    success: bool = True
    data: Any


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: ErrorPayload


class DatasetConfig(BaseModel):
    market: str
    timeframe: str
    asset_type: str = "stock"
    from_: datetime = Field(alias="from")
    to: datetime


class BacktestExecutionContract(BaseModel):
    initial_capital: float
    fee_bps: int
    slippage_bps: int
    fill_price_rule: str
    intrabar_match_policy: str
    calendar: str
    timezone: str
    adjustment_mode: str


class DataSnapshotConfig(BaseModel):
    dataset_snapshot_ref: str


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


class ProjectCreateRequest(BaseModel):
    title: str
    natural_language_prompt: str
    strategy_dsl: dict[str, Any]
    strategy_python: str | None = None


class StrategyGenerateRequest(BaseModel):
    prompt: str
    market: str
    timeframe: str
    asset_type: str = "stock"
    preferences: dict[str, Any] = Field(default_factory=dict)
    teaching_mode: bool = False


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


class TradeUploadParseRequest(BaseModel):
    column_mapping: dict[str, str]


class TradeRecordItem(BaseModel):
    trade_id: str
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime | None
    pnl: float


class TradeUploadRecord(BaseModel):
    upload_id: str = Field(default_factory=lambda: f"upload_{uuid4().hex[:8]}")
    source_file_name: str
    raw_text: str
    status: str = "uploaded"
    detected_columns: list[str] = Field(default_factory=list)
    column_mapping: dict[str, str] = Field(default_factory=dict)
    records: list[TradeRecordItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class TaskCreatedResponse(BaseModel):
    id: str
    status: TaskStatus
    progress_pct: int
    status_url: str
    result_url: str


class BacktestResult(BaseModel):
    backtest_run_id: str
    status: TaskStatus
    progress_pct: int
    dataset_snapshot_ref: str
    engine_version: str
    data_source: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorPayload | None = None


class OptimizationResult(BaseModel):
    job_id: str
    status: TaskStatus
    progress_pct: int
    best_params: dict[str, Any] = Field(default_factory=dict)
    best_metrics: dict[str, Any] = Field(default_factory=dict)
    trials: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorPayload | None = None


class ReplayResult(BaseModel):
    analysis_id: str
    status: TaskStatus
    progress_pct: int
    feature_snapshot_ref: str | None = None
    analysis_rule_version: str
    summary: str | None = None
    winning_patterns: list[dict[str, Any]] = Field(default_factory=list)
    losing_patterns: list[dict[str, Any]] = Field(default_factory=list)
    suggestion_rules: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorPayload | None = None


class ProjectVersionCreated(BaseModel):
    project_id: str
    version_id: str


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: str
    status: TaskStatus = TaskStatus.QUEUED
    progress_pct: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    payload: dict[str, Any]
    result: dict[str, Any] = Field(default_factory=dict)
    error: ErrorPayload | None = None


class StrategyVersionRecord(BaseModel):
    project_id: str = Field(default_factory=lambda: f"proj_{uuid4().hex[:8]}")
    version_id: str = Field(default_factory=lambda: f"ver_{uuid4().hex[:8]}")
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
