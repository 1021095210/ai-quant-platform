from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from quant_platform_api.db import Base


class StrategyVersionORM(Base):
    __tablename__ = "strategy_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    natural_language_prompt: Mapped[str] = mapped_column(Text())
    strategy_dsl_json: Mapped[str] = mapped_column(Text())
    strategy_python_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TaskORM(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress_pct: Mapped[int] = mapped_column(Integer())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[str] = mapped_column(Text())
    result_json: Mapped[str] = mapped_column(Text(), default="{}")
    error_json: Mapped[str | None] = mapped_column(Text(), nullable=True)


class TradeUploadORM(Base):
    __tablename__ = "trade_uploads"

    upload_id: Mapped[str] = mapped_column(String(64), primary_key=True)
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
