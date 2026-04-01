from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str):
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(
        database_url,
        future=True,
        connect_args=connect_args,
    )


def build_session_factory(database_url: str) -> sessionmaker:
    engine = build_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def create_schema(session_factory: sessionmaker) -> None:
    engine = session_factory.kw["bind"]
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    strategy_columns = {column["name"] for column in inspector.get_columns("strategy_versions")}
    if "strategy_python_text" not in strategy_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE strategy_versions ADD COLUMN strategy_python_text TEXT")
            )
    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    task_column_definitions = {
        "workspace_id": "VARCHAR(64) DEFAULT 'ws_default'",
        "environment": "VARCHAR(32) DEFAULT 'dev'",
        "resource_refs_json": "TEXT DEFAULT '{}'",
        "config_revision": "VARCHAR(128) DEFAULT ''",
        "created_by": "VARCHAR(64) DEFAULT 'system'",
        "request_id": "VARCHAR(64) DEFAULT ''",
        "trace_id": "VARCHAR(64) DEFAULT ''",
        "idempotency_key": "VARCHAR(255)",
        "priority": "VARCHAR(32) DEFAULT 'normal'",
        "retry_count": "INTEGER DEFAULT 0",
        "error_code": "VARCHAR(64)",
        "error_message": "TEXT",
    }
    for column_name, column_definition in task_column_definitions.items():
        if column_name not in task_columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        f"ALTER TABLE tasks ADD COLUMN {column_name} {column_definition}"
                    )
                )
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" not in user_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(32) DEFAULT 'user'"))
