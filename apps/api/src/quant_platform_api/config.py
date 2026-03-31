from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(slots=True)
class Settings:
    app_name: str = "AI Quant Platform API"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+pysqlite:///./quant_platform.db"
    market_data_database_path: str = "./market_data.db"
    market_data_provider: str = "auto"
    tushare_token: str = ""
    backtest_engine_version: str = "engine_v1"
    strategy_prompt_version: str = "v1"
    replay_prompt_version: str = "v1"
    job_execution_mode: str = "background"
    job_simulation_latency_ms: int = 100

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            app_name=os.getenv("APP_NAME", defaults.app_name),
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
