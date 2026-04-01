from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - resolved in runtime environments
    psycopg = None


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    target: str
    detail: str


def _redact_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not hostname:
        return url
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        if parsed.password is not None:
            netloc = f"{parsed.username}:***@{netloc}"
        else:
            netloc = f"{parsed.username}@{netloc}"
    return parsed._replace(netloc=netloc).geturl()


def _normalize_postgres_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.removeprefix("postgresql+psycopg://")
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url.removeprefix("postgresql+psycopg2://")
    return url


def _check_http(name: str, url: str) -> CheckResult:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return CheckResult(
                name=name,
                ok=200 <= response.status < 400,
                target=url,
                detail=f"status={response.status}",
            )
    except Exception as exc:  # pragma: no cover - network path
        return CheckResult(name=name, ok=False, target=url, detail=str(exc))


def _recv_line(connection: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        byte = connection.recv(1)
        if not byte:
            break
        chunks.append(byte)
        if byte == b"\n":
            break
    return b"".join(chunks).decode("utf-8", errors="replace").strip()


def _check_redis(url: str) -> CheckResult:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 6379
    detail_target = _redact_url(url)
    if not host:
        return CheckResult("redis", False, detail_target, "missing hostname")
    try:
        connection = socket.create_connection((host, port), timeout=5)
        if parsed.scheme == "rediss":
            context = ssl.create_default_context()
            connection = context.wrap_socket(connection, server_hostname=host)
        with connection:
            if parsed.password:
                connection.sendall(f"AUTH {parsed.password}\r\n".encode("utf-8"))
                auth_reply = _recv_line(connection)
                if not auth_reply.startswith("+OK"):
                    return CheckResult("redis", False, detail_target, auth_reply)
            connection.sendall(b"PING\r\n")
            ping_reply = _recv_line(connection)
            return CheckResult(
                "redis",
                ping_reply.startswith("+PONG"),
                detail_target,
                ping_reply,
            )
    except Exception as exc:  # pragma: no cover - network path
        return CheckResult("redis", False, detail_target, str(exc))


def _check_postgres(url: str) -> CheckResult:
    detail_target = _redact_url(url)
    if psycopg is None:
        return CheckResult("postgres", False, detail_target, "psycopg is unavailable")
    try:
        with psycopg.connect(_normalize_postgres_url(url), connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                row = cursor.fetchone()
        return CheckResult("postgres", row == (1,), detail_target, f"row={row}")
    except Exception as exc:  # pragma: no cover - network path
        return CheckResult("postgres", False, detail_target, str(exc))


def _collect_results(args: argparse.Namespace) -> list[CheckResult]:
    results: list[CheckResult] = []
    if args.database_url:
        results.append(_check_postgres(args.database_url))
    if args.redis_url:
        results.append(_check_redis(args.redis_url))
    if args.minio_endpoint:
        results.append(
            _check_http(
                "minio",
                args.minio_endpoint.rstrip("/") + "/minio/health/live",
            )
        )
    if args.app_url:
        results.append(_check_http("app", args.app_url.rstrip("/") + "/healthz"))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify external infra dependencies")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--redis-url", default="")
    parser.add_argument("--minio-endpoint", default="")
    parser.add_argument("--app-url", default="")
    args = parser.parse_args(argv)

    results = _collect_results(args)
    payload: dict[str, Any] = {
        "success": all(result.ok for result in results) if results else True,
        "results": [asdict(result) for result in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
