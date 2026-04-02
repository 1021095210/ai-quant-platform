from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class CheckSpec:
    name: str
    command: list[str]
    required: bool = True


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    command: str
    output: str


def build_check_specs(
    *,
    python_executable: str,
    full_regression: bool = False,
    app_url: str = "",
    database_url: str = "",
    redis_url: str = "",
    minio_endpoint: str = "",
) -> list[CheckSpec]:
    specs = [
        CheckSpec(
            name="design-docs",
            command=[
                python_executable,
                "tools/validate_product_design_docs.py",
            ],
        ),
        CheckSpec(
            name="static-assets",
            command=[
                python_executable,
                "-m",
                "unittest",
                "tests.test_static_assets",
            ],
        ),
        CheckSpec(
            name="release-smoke-suite",
            command=[
                python_executable,
                "-m",
                "unittest",
                "tests.test_release_smoke",
            ],
        ),
    ]
    if full_regression:
        specs.append(
            CheckSpec(
                name="full-test-suite",
                command=[
                    python_executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "test_*.py",
                ],
            )
        )
    if any((app_url, database_url, redis_url, minio_endpoint)):
        verify_command = [
            python_executable,
            "tools/verify_infra_stack.py",
        ]
        if database_url:
            verify_command.extend(["--database-url", database_url])
        if redis_url:
            verify_command.extend(["--redis-url", redis_url])
        if minio_endpoint:
            verify_command.extend(["--minio-endpoint", minio_endpoint])
        if app_url:
            verify_command.extend(["--app-url", app_url])
        specs.append(CheckSpec(name="infra-and-healthz", command=verify_command))
    return specs


def run_check(spec: CheckSpec) -> CheckResult:
    completed = subprocess.run(
        spec.command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = completed.stdout.strip()
    if completed.stderr.strip():
        output = f"{output}\n{completed.stderr.strip()}".strip()
    return CheckResult(
        name=spec.name,
        ok=completed.returncode == 0,
        command=" ".join(spec.command),
        output=output,
    )


def format_report(results: list[CheckResult]) -> dict[str, object]:
    return {
        "success": all(item.ok for item in results),
        "results": [asdict(item) for item in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run release preflight checks for the quant platform.",
    )
    parser.add_argument("--python", dest="python_executable", default=sys.executable)
    parser.add_argument("--full-regression", action="store_true")
    parser.add_argument("--app-url", default="")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--redis-url", default="")
    parser.add_argument("--minio-endpoint", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    specs = build_check_specs(
        python_executable=args.python_executable,
        full_regression=args.full_regression,
        app_url=args.app_url,
        database_url=args.database_url,
        redis_url=args.redis_url,
        minio_endpoint=args.minio_endpoint,
    )
    results = [run_check(spec) for spec in specs]
    report = format_report(results)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Preflight success: {report['success']}")
        for item in report["results"]:
            print(f"\n[{item['name']}] {'OK' if item['ok'] else 'FAIL'}")
            print(item["command"])
            if item["output"]:
                print(item["output"])
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
