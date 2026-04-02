from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from quant_platform_api.db import Base


class StrategyVersionORM(Base):
    __tablename__ = "strategy_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="ws_default")
    title: Mapped[str] = mapped_column(String(255))
    natural_language_prompt: Mapped[str] = mapped_column(Text())
    strategy_dsl_json: Mapped[str] = mapped_column(Text())
    strategy_python_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class UserORM(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    contact: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text())
    role: Mapped[str] = mapped_column(String(32), default="user")
    status: Mapped[str] = mapped_column(String(32), default="active")
    status_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class UserSessionORM(Base):
    __tablename__ = "user_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    session_token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthEventORM(Base):
    __tablename__ = "auth_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AdminAuditLogORM(Base):
    __tablename__ = "admin_audit_logs"

    log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(String(64), index=True)
    target_user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text())
    details_json: Mapped[str] = mapped_column(Text(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DatasetSnapshotORM(Base):
    __tablename__ = "dataset_snapshots"

    dataset_snapshot_ref: Mapped[str] = mapped_column(String(120), primary_key=True)
    market: Mapped[str] = mapped_column(String(64), index=True)
    asset_type: Mapped[str] = mapped_column(String(32))
    frequency: Mapped[str] = mapped_column(String(32), index=True)
    adjustment_mode: Mapped[str] = mapped_column(String(32))
    date_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    date_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(64), default="shared_market_store")
    coverage_status: Mapped[str] = mapped_column(String(32), default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TaskORM(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress_pct: Mapped[int] = mapped_column(Integer())
    workspace_id: Mapped[str] = mapped_column(String(64), default="ws_default")
    environment: Mapped[str] = mapped_column(String(32), default="dev")
    resource_refs_json: Mapped[str] = mapped_column(Text(), default="{}")
    config_revision: Mapped[str] = mapped_column(String(128), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    request_id: Mapped[str] = mapped_column(String(64), default="")
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    retry_count: Mapped[int] = mapped_column(Integer(), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[str] = mapped_column(Text())
    result_json: Mapped[str] = mapped_column(Text(), default="{}")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text(), nullable=True)


class TradeUploadORM(Base):
    __tablename__ = "trade_uploads"

    upload_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="ws_default")
    source_file_name: Mapped[str] = mapped_column(String(255))
    raw_text: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), index=True)
    detected_columns_json: Mapped[str] = mapped_column(Text(), default="[]")
    column_mapping_json: Mapped[str] = mapped_column(Text(), default="{}")
    records_json: Mapped[str] = mapped_column(Text(), default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class CustomIndicatorORM(Base):
    __tablename__ = "custom_indicators"

    indicator_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    natural_language_prompt: Mapped[str] = mapped_column(Text())
    summary: Mapped[str] = mapped_column(Text())
    formula_text: Mapped[str] = mapped_column(Text())
    python_code_text: Mapped[str] = mapped_column(Text())
    usage_hint: Mapped[str] = mapped_column(Text())
    tags_json: Mapped[str] = mapped_column(Text(), default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class GlossaryTermORM(Base):
    __tablename__ = "glossary_terms"

    term_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    term: Mapped[str] = mapped_column(String(255), index=True)
    meaning: Mapped[str] = mapped_column(Text())
    example: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DefaultRuleSectionORM(Base):
    __tablename__ = "default_rule_sections"

    section_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    section: Mapped[str] = mapped_column(String(255), index=True)
    items_json: Mapped[str] = mapped_column(Text(), default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
