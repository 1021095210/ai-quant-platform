from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(slots=True)
class Settings:
    app_env: str = "development"
    app_name: str = "AI Quant Platform API"
    app_public_url: str = ""
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+pysqlite:///./quant_platform.db"
    market_data_database_path: str = "./market_data.db"
    market_data_provider: str = "auto"
    tushare_token: str = ""
    redis_url: str = ""
    minio_endpoint: str = ""
    minio_console_url: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "quant-platform"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model_strategy: str = ""
    llm_model_summary: str = ""
    allowed_llm_export_fields: str = "symbol,side,entry_time,exit_time,pnl,feature_snapshot"
    backtest_engine_version: str = "engine_v1"
    strategy_prompt_version: str = "v1"
    replay_prompt_version: str = "v1"
    job_execution_mode: str = "background"
    job_simulation_latency_ms: int = 100

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            app_env=os.getenv("APP_ENV", defaults.app_env),
            app_name=os.getenv("APP_NAME", defaults.app_name),
            app_public_url=os.getenv("APP_PUBLIC_URL", defaults.app_public_url),
            api_prefix=os.getenv("API_PREFIX", defaults.api_prefix),
            database_url=os.getenv("DATABASE_URL", defaults.database_url),
            market_data_database_path=os.getenv(
                "MARKET_DATA_DATABASE_PATH",
                defaults.market_data_database_path,
            ),
            market_data_provider=os.getenv(
                "MARKET_DATA_PROVIDER",
                defaults.market_data_provider,
            ),
            tushare_token=os.getenv("TUSHARE_TOKEN", defaults.tushare_token),
            redis_url=os.getenv("REDIS_URL", defaults.redis_url),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", defaults.minio_endpoint),
            minio_console_url=os.getenv("MINIO_CONSOLE", defaults.minio_console_url),
            minio_access_key=os.getenv("MINIO_ACCESS_KEY", defaults.minio_access_key),
            minio_secret_key=os.getenv("MINIO_SECRET_KEY", defaults.minio_secret_key),
            minio_bucket=os.getenv("MINIO_BUCKET", defaults.minio_bucket),
            llm_base_url=os.getenv("LLM_BASE_URL", defaults.llm_base_url),
            llm_api_key=os.getenv("LLM_API_KEY", defaults.llm_api_key),
            llm_model_strategy=os.getenv(
                "LLM_MODEL_STRATEGY",
                defaults.llm_model_strategy,
            ),
            llm_model_summary=os.getenv(
                "LLM_MODEL_SUMMARY",
                defaults.llm_model_summary,
            ),
            allowed_llm_export_fields=os.getenv(
                "ALLOWED_LLM_EXPORT_FIELDS",
                defaults.allowed_llm_export_fields,
            ),
            backtest_engine_version=os.getenv(
                "BACKTEST_ENGINE_VERSION", defaults.backtest_engine_version
            ),
            strategy_prompt_version=os.getenv(
                "STRATEGY_PROMPT_VERSION", defaults.strategy_prompt_version
            ),
            replay_prompt_version=os.getenv(
                "REPLAY_PROMPT_VERSION", defaults.replay_prompt_version
            ),
            job_execution_mode=os.getenv(
                "JOB_EXECUTION_MODE", defaults.job_execution_mode
            ),
            job_simulation_latency_ms=int(
                os.getenv(
                    "JOB_SIMULATION_LATENCY_MS",
                    str(defaults.job_simulation_latency_ms),
                )
            ),
        )
