from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tools.verify_infra_stack import _normalize_postgres_url, _redact_url, main


class DeploymentStackTests(unittest.TestCase):
    def test_verify_infra_stack_redacts_passwords(self) -> None:
        url = "postgresql://quant_user:secret-password@db.example.com:5432/quant_ai"

        redacted = _redact_url(url)

        self.assertEqual(
            "postgresql://quant_user:***@db.example.com:5432/quant_ai",
            redacted,
        )

    def test_verify_infra_stack_normalizes_sqlalchemy_postgres_url(self) -> None:
        url = "postgresql+psycopg://quant_user:secret-password@db.example.com:5432/quant_ai"

        normalized = _normalize_postgres_url(url)

        self.assertEqual(
            "postgresql://quant_user:secret-password@db.example.com:5432/quant_ai",
            normalized,
        )

    def test_verify_infra_stack_main_succeeds_when_no_checks_are_requested(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            exit_code = main([])

        payload = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(payload["success"])
        self.assertEqual([], payload["results"])

    def test_root_readme_answers_architecture_questions(self) -> None:
        readme_path = WORKSPACE_ROOT / "README.md"

        self.assertTrue(readme_path.exists(), "README.md 不存在")
        content = readme_path.read_text(encoding="utf-8")
        self.assertIn("### 1. 前端用什么", content)
        self.assertIn("### 2. 后端用什么", content)
        self.assertIn("### 3. 数据存哪里", content)
        self.assertIn("### 4. 有没有 AI 组件", content)
        self.assertIn("### 5. 怎么部署", content)
        self.assertIn("## 数据流转", content)
        self.assertIn("## 业务流转", content)
        self.assertIn("Vanilla JavaScript", content)
        self.assertIn("FastAPI", content)
        self.assertIn("PostgreSQL", content)

    def test_system_architecture_doc_exists_with_core_sections(self) -> None:
        doc_path = (
            WORKSPACE_ROOT
            / "产品设计"
            / "AI量化交易平台_系统架构与部署方案_2026-04-01.md"
        )

        self.assertTrue(doc_path.exists(), "系统架构与部署方案文档不存在")
        content = doc_path.read_text(encoding="utf-8")
        self.assertIn("### 1. 前端用什么", content)
        self.assertIn("### 5. 怎么部署", content)
        self.assertIn("## 三、数据流转", content)
        self.assertIn("## 四、业务流转", content)
        self.assertIn("## 五、部署与运维", content)
        self.assertIn("Docker", content)
        self.assertIn("Docker Compose", content)

    def test_infra_compose_files_exist(self) -> None:
        compose_path = WORKSPACE_ROOT / "infra" / "docker-compose.yml"
        external_path = WORKSPACE_ROOT / "infra" / "docker-compose.external.yml"
        example_path = WORKSPACE_ROOT / "infra" / "deploy.env.example"

        self.assertTrue(compose_path.exists(), "本地 compose 文件不存在")
        self.assertTrue(external_path.exists(), "外部依赖 compose 文件不存在")
        self.assertTrue(example_path.exists(), "部署环境变量模板不存在")

        compose_content = compose_path.read_text(encoding="utf-8")
        self.assertIn("api:", compose_content)
        self.assertIn("postgres:", compose_content)
        self.assertIn("redis:", compose_content)
        self.assertIn("minio:", compose_content)


if __name__ == "__main__":
    unittest.main()
