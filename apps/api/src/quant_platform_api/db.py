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
