from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
API_SRC = WORKSPACE_ROOT / "apps" / "api" / "src"
VENV_LIB = WORKSPACE_ROOT / ".venv" / "lib"

if API_SRC.exists() and str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

if VENV_LIB.exists():
    for site_packages in VENV_LIB.glob("python*/site-packages"):
        if str(site_packages) not in sys.path:
            sys.path.insert(0, str(site_packages))

from quant_platform_api.config import Settings


class SettingsTests(unittest.TestCase):
    def test_from_env_reads_deployment_related_settings(self) -> None:
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "APP_PUBLIC_URL": "https://quant.example.com",
                "DATABASE_URL": "postgresql+psycopg://user:pass@db:5432/app",
                "REDIS_URL": "redis://:secret@redis:6379/0",
                "MINIO_ENDPOINT": "http://minio:9000",
                "MINIO_CONSOLE": "http://minio:9001",
                "MINIO_ACCESS_KEY": "admin",
                "MINIO_SECRET_KEY": "secret",
                "MINIO_BUCKET": "quant-files",
                "LLM_BASE_URL": "https://api.openai.com/v1",
                "LLM_API_KEY": "sk-test",
                "LLM_MODEL_STRATEGY": "gpt-4.1",
                "LLM_MODEL_SUMMARY": "gpt-4.1-mini",
                "LLM_MODEL_MENTOR": "gpt-4.1-nano",
                "LLM_DEEPSEEK_API_KEY": "deepseek-test",
                "LLM_DEEPSEEK_MODEL": "deepseek-chat",
                "ARK_API_KEY": "ark-test",
                "ARK_MODEL": "ep-20260413-demo",
                "ALLOWED_LLM_EXPORT_FIELDS": "symbol,pnl",
                "JOB_SIMULATION_LATENCY_MS": "250",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        self.assertEqual("production", settings.app_env)
        self.assertEqual("https://quant.example.com", settings.app_public_url)
        self.assertEqual("postgresql+psycopg://user:pass@db:5432/app", settings.database_url)
        self.assertEqual("redis://:secret@redis:6379/0", settings.redis_url)
        self.assertEqual("http://minio:9000", settings.minio_endpoint)
        self.assertEqual("http://minio:9001", settings.minio_console_url)
        self.assertEqual("admin", settings.minio_access_key)
        self.assertEqual("secret", settings.minio_secret_key)
        self.assertEqual("quant-files", settings.minio_bucket)
        self.assertEqual("https://api.openai.com/v1", settings.llm_base_url)
        self.assertEqual("sk-test", settings.llm_api_key)
        self.assertEqual("gpt-4.1", settings.llm_model_strategy)
        self.assertEqual("gpt-4.1-mini", settings.llm_model_summary)
        self.assertEqual("gpt-4.1-nano", settings.llm_model_mentor)
        self.assertEqual("https://api.deepseek.com", settings.llm_deepseek_base_url)
        self.assertEqual("deepseek-test", settings.llm_deepseek_api_key)
        self.assertEqual("deepseek-chat", settings.llm_deepseek_model)
        self.assertEqual("https://ark.cn-beijing.volces.com/api/v3", settings.llm_volcengine_base_url)
        self.assertEqual("ark-test", settings.llm_volcengine_api_key)
        self.assertEqual("ep-20260413-demo", settings.llm_volcengine_model)
        self.assertEqual("symbol,pnl", settings.allowed_llm_export_fields)
        self.assertEqual(250, settings.job_simulation_latency_ms)


if __name__ == "__main__":
    unittest.main()
