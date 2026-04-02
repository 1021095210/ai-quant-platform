from __future__ import annotations

import sys
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tools.release_preflight import CheckResult, build_check_specs, format_report  # noqa: E402
from tools.validate_product_design_docs import REQUIRED_SECTIONS, collect_missing_sections  # noqa: E402


class ReleasePreflightTests(unittest.TestCase):
    def test_build_check_specs_without_infra_contains_core_checks(self) -> None:
        specs = build_check_specs(python_executable="python3")

        names = [item.name for item in specs]
        self.assertEqual(
            ["design-docs", "static-assets", "release-smoke-suite"],
            names,
        )

    def test_build_check_specs_with_full_regression_adds_full_suite(self) -> None:
        specs = build_check_specs(
            python_executable="python3",
            full_regression=True,
        )

        self.assertEqual("full-test-suite", specs[-1].name)

    def test_build_check_specs_with_infra_adds_health_check(self) -> None:
        specs = build_check_specs(
            python_executable="python3",
            app_url="https://example.com",
            database_url="postgresql://demo",
            redis_url="redis://demo",
            minio_endpoint="https://minio.example.com",
        )

        self.assertEqual("infra-and-healthz", specs[-1].name)
        self.assertIn("--app-url", specs[-1].command)
        self.assertIn("https://example.com", specs[-1].command)

    def test_format_report_marks_failure_when_any_check_fails(self) -> None:
        report = format_report(
            [
                CheckResult(name="a", ok=True, command="cmd a", output=""),
                CheckResult(name="b", ok=False, command="cmd b", output="boom"),
            ]
        )

        self.assertFalse(report["success"])
        self.assertEqual(2, len(report["results"]))

    def test_common_issues_doc_is_required_and_present(self) -> None:
        self.assertIn(
            "产品设计/AI量化交易平台_常见问题与避免规则.md",
            REQUIRED_SECTIONS,
        )
        missing = collect_missing_sections(WORKSPACE_ROOT)
        self.assertNotIn("产品设计/AI量化交易平台_常见问题与避免规则.md", missing)


if __name__ == "__main__":
    unittest.main()
