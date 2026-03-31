-- AI 量化交易平台数据库设计
-- 目标：支持策略研究、回测、参数优化、交割单上传与复盘分析

-- 建议使用 PostgreSQL 15+

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 用户
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 策略项目
CREATE TABLE strategy_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 策略版本
CREATE TABLE strategy_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES strategy_projects(id) ON DELETE CASCADE,
    natural_language_prompt TEXT NOT NULL,
    strategy_dsl JSONB NOT NULL,
    explanation TEXT,
    source_type VARCHAR(30) NOT NULL DEFAULT 'nl_generated'
        CHECK (source_type IN ('nl_generated', 'manual_edit', 'replay_promoted')),
    parent_version_id UUID REFERENCES strategy_versions(id) ON DELETE SET NULL,
    prompt_template_version VARCHAR(50) NOT NULL DEFAULT 'v1',
    llm_provider VARCHAR(50),
    llm_model VARCHAR(100),
    llm_request_id VARCHAR(100),
    dsl_schema_version VARCHAR(50) NOT NULL DEFAULT 'dsl_v1',
    validation_rule_version VARCHAR(50) NOT NULL DEFAULT 'strategy_rule_v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_strategy_versions_project_created_at
    ON strategy_versions(project_id, created_at DESC);

-- 指标
CREATE TABLE indicators (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('builtin', 'custom')),
    expression TEXT,
    description TEXT,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_indicators_user_name
    ON indicators(user_id, name)
    WHERE user_id IS NOT NULL;

-- 回测结果
CREATE TABLE backtest_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_version_id UUID NOT NULL REFERENCES strategy_versions(id) ON DELETE CASCADE,
    market VARCHAR(50) NOT NULL,
    timeframe VARCHAR(20) NOT NULL,
    date_from TIMESTAMPTZ NOT NULL,
    date_to TIMESTAMPTZ NOT NULL,
    dataset_snapshot_ref VARCHAR(120) NOT NULL,
    execution_contract JSONB NOT NULL DEFAULT '{}'::jsonb,
    engine_version VARCHAR(50) NOT NULL DEFAULT 'engine_v1',
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    equity_curve JSONB NOT NULL DEFAULT '[]'::jsonb,
    trade_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    progress_pct INTEGER NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    error_code VARCHAR(100),
    error_message TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_backtest_runs_strategy_created_at
    ON backtest_runs(strategy_version_id, created_at DESC);

-- 参数优化任务
CREATE TABLE optimization_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_version_id UUID NOT NULL REFERENCES strategy_versions(id) ON DELETE CASCADE,
    objective VARCHAR(50) NOT NULL,
    search_space JSONB NOT NULL,
    dataset_config JSONB NOT NULL,
    dataset_snapshot_ref VARCHAR(120) NOT NULL,
    execution_contract JSONB NOT NULL DEFAULT '{}'::jsonb,
    engine_version VARCHAR(50) NOT NULL DEFAULT 'engine_v1',
    status VARCHAR(20) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    progress_pct INTEGER NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    best_params JSONB,
    best_metrics JSONB,
    error_code VARCHAR(100),
    error_message TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_optimization_jobs_strategy_created_at
    ON optimization_jobs(strategy_version_id, created_at DESC);

-- 参数优化尝试
CREATE TABLE optimization_trials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES optimization_jobs(id) ON DELETE CASCADE,
    params JSONB NOT NULL,
    metrics JSONB NOT NULL,
    rank_score NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_optimization_trials_job_id
    ON optimization_trials(job_id);

-- 交割单上传记录
CREATE TABLE trade_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_file_name VARCHAR(255) NOT NULL,
    storage_path TEXT NOT NULL,
    storage_sha256 VARCHAR(64),
    market_type VARCHAR(50),
    timezone VARCHAR(50),
    parse_status VARCHAR(20) NOT NULL DEFAULT 'uploaded'
        CHECK (parse_status IN ('uploaded', 'mapping_pending', 'parsed', 'failed', 'purged')),
    detected_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    column_mapping JSONB,
    pii_status VARCHAR(20) NOT NULL DEFAULT 'unknown'
        CHECK (pii_status IN ('unknown', 'clean', 'needs_masking', 'masked')),
    parse_version VARCHAR(50) NOT NULL DEFAULT 'parse_v1',
    normalize_version VARCHAR(50) NOT NULL DEFAULT 'normalize_v1',
    retention_until TIMESTAMPTZ,
    purge_status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (purge_status IN ('active', 'scheduled', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trade_uploads_user_created_at
    ON trade_uploads(user_id, created_at DESC);

-- 原始交割单行
CREATE TABLE trade_raw_rows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id UUID NOT NULL REFERENCES trade_uploads(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    raw_cells JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_cells JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (upload_id, row_number)
);

CREATE INDEX idx_trade_raw_rows_upload_row_number
    ON trade_raw_rows(upload_id, row_number);

-- 标准化后的成交 fills
CREATE TABLE trade_fills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id UUID NOT NULL REFERENCES trade_uploads(id) ON DELETE CASCADE,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('long', 'short')),
    fill_time TIMESTAMPTZ NOT NULL,
    quantity NUMERIC(24, 8),
    fill_price NUMERIC(24, 8),
    fees NUMERIC(24, 8),
    source_row_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trade_fills_upload_symbol_fill_time
    ON trade_fills(upload_id, symbol, fill_time);

-- 聚合后的完整交易记录
CREATE TABLE trade_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id UUID NOT NULL REFERENCES trade_uploads(id) ON DELETE CASCADE,
    open_fill_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    close_fill_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('long', 'short')),
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    quantity NUMERIC(24, 8),
    entry_price NUMERIC(24, 8),
    exit_price NUMERIC(24, 8),
    pnl NUMERIC(24, 8),
    fees NUMERIC(24, 8),
    holding_seconds INTEGER,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trade_records_upload_symbol_entry
    ON trade_records(upload_id, symbol, entry_time);

-- 复盘分析
CREATE TABLE replay_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id UUID NOT NULL REFERENCES trade_uploads(id) ON DELETE CASCADE,
    focus_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    custom_prompt TEXT,
    feature_snapshot_ref VARCHAR(120),
    analysis_rule_version VARCHAR(50) NOT NULL DEFAULT 'replay_rule_v1',
    llm_provider VARCHAR(50),
    llm_model VARCHAR(100),
    llm_request_id VARCHAR(100),
    prompt_template_version VARCHAR(50) NOT NULL DEFAULT 'v1',
    status VARCHAR(20) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    progress_pct INTEGER NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    summary TEXT,
    winning_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
    losing_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
    suggestion_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code VARCHAR(100),
    error_message TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_replay_analyses_upload_created_at
    ON replay_analyses(upload_id, created_at DESC);

-- 说明：
-- 1. 行情数据和大体量 K 线序列默认不放在此库中，使用文件存储或单独行情库。
-- 2. strategy_dsl、metrics、suggestion_rules 使用 JSONB 以支持演示期快速迭代。
-- 3. 通过 dataset_snapshot_ref、execution_contract、engine_version 保障回测可复现。
-- 4. 通过 prompt_template_version、llm_model、analysis_rule_version 保障 AI 输出可追溯。
-- 5. 交割单按 raw rows -> fills -> trade records 三层建模，便于支持真实券商账单。
