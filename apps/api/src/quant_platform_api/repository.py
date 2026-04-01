from __future__ import annotations

import json
from copy import deepcopy
from threading import Lock
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from quant_platform_api.models import (
    CustomIndicatorRecord,
    DefaultRuleSection,
    DatasetSnapshotRecord,
    ErrorPayload,
    GlossaryTermRecord,
    StrategyVersionRecord,
    TradeRecordItem,
    TradeUploadRecord,
    TaskRecord,
    TaskStatus,
    UserRecord,
    UserSessionRecord,
    utcnow,
)
from quant_platform_api.orm import (
    CustomIndicatorORM,
    DefaultRuleSectionORM,
    DatasetSnapshotORM,
    GlossaryTermORM,
    StrategyVersionORM,
    TaskORM,
    TradeUploadORM,
    UserORM,
    UserSessionORM,
)


class TaskRepository(Protocol):
    def create(self, record: TaskRecord) -> TaskRecord: ...

    def get(
        self,
        task_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> TaskRecord | None: ...

    def mark_queued(self, task_id: str) -> TaskRecord | None: ...

    def mark_running(self, task_id: str) -> TaskRecord | None: ...

    def complete(self, task_id: str, result: dict) -> TaskRecord | None: ...

    def fail(self, task_id: str, error: ErrorPayload) -> TaskRecord | None: ...

    def cancel(self, task_id: str) -> TaskRecord | None: ...

    def list(
        self,
        kind: str | None = None,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[TaskRecord]: ...


class StrategyRepository(Protocol):
    def create(self, record: StrategyVersionRecord) -> StrategyVersionRecord: ...

    def exists(self, version_id: str) -> bool: ...

    def list_projects(
        self,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[StrategyVersionRecord]: ...

    def get(
        self,
        version_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> StrategyVersionRecord | None: ...


class DatasetSnapshotRepository(Protocol):
    def create(self, record: DatasetSnapshotRecord) -> DatasetSnapshotRecord: ...

    def get(self, dataset_snapshot_ref: str) -> DatasetSnapshotRecord | None: ...


class UserRepository(Protocol):
    def create(self, record: UserRecord) -> UserRecord: ...

    def get(self, user_id: str) -> UserRecord | None: ...

    def get_by_username(self, username: str) -> UserRecord | None: ...

    def update_role(self, user_id: str, role: str) -> UserRecord | None: ...

    def list(self) -> list[UserRecord]: ...


class UserSessionRepository(Protocol):
    def create(self, record: UserSessionRecord) -> UserSessionRecord: ...

    def get_by_token(self, session_token: str) -> UserSessionRecord | None: ...

    def delete_by_token(self, session_token: str) -> None: ...

    def list(self) -> list[UserSessionRecord]: ...


class TradeUploadRepository(Protocol):
    def create(self, record: TradeUploadRecord) -> TradeUploadRecord: ...

    def get(
        self,
        upload_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> TradeUploadRecord | None: ...

    def update(self, record: TradeUploadRecord) -> TradeUploadRecord: ...


class CustomIndicatorRepository(Protocol):
    def create(self, record: CustomIndicatorRecord) -> CustomIndicatorRecord: ...

    def list(self) -> list[CustomIndicatorRecord]: ...


class GlossaryTermRepository(Protocol):
    def create(self, record: GlossaryTermRecord) -> GlossaryTermRecord: ...

    def list(self) -> list[GlossaryTermRecord]: ...


class DefaultRuleRepository(Protocol):
    def list(self) -> list[DefaultRuleSection]: ...

    def replace_all(self, records: list[DefaultRuleSection]) -> list[DefaultRuleSection]: ...


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[str, TaskRecord] = {}

    def create(self, record: TaskRecord) -> TaskRecord:
        with self._lock:
            self._items[record.id] = deepcopy(record)
            return deepcopy(record)

    def get(
        self,
        task_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> TaskRecord | None:
        with self._lock:
            record = self._items.get(task_id)
            if record is None:
                return None
            if user_id is not None and record.user_id != user_id:
                return None
            if workspace_id is not None and record.workspace_id != workspace_id:
                return None
            return deepcopy(record)

    def mark_queued(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._items.get(task_id)
            if record is None or record.status == TaskStatus.CANCELED:
                return deepcopy(record) if record else None
            record.status = TaskStatus.QUEUED
            return deepcopy(record)

    def mark_running(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._items.get(task_id)
            if record is None or record.status == TaskStatus.CANCELED:
                return deepcopy(record) if record else None
            record.status = TaskStatus.RUNNING
            record.progress_pct = 25
            record.started_at = utcnow()
            return deepcopy(record)

    def complete(self, task_id: str, result: dict) -> TaskRecord | None:
        with self._lock:
            record = self._items.get(task_id)
            if record is None or record.status == TaskStatus.CANCELED:
                return deepcopy(record) if record else None
            record.status = TaskStatus.SUCCEEDED
            record.progress_pct = 100
            record.finished_at = utcnow()
            record.result = deepcopy(result)
            return deepcopy(record)

    def fail(self, task_id: str, error: ErrorPayload) -> TaskRecord | None:
        with self._lock:
            record = self._items.get(task_id)
            if record is None:
                return None
            record.status = TaskStatus.FAILED
            record.finished_at = utcnow()
            record.error = error
            record.error_code = error.code
            record.error_message = error.message
            return deepcopy(record)

    def cancel(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._items.get(task_id)
            if record is None:
                return None
            if record.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                return deepcopy(record)
            record.status = TaskStatus.CANCELING
            record.status = TaskStatus.CANCELED
            record.finished_at = utcnow()
            return deepcopy(record)

    def list(
        self,
        kind: str | None = None,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[TaskRecord]:
        with self._lock:
            items = list(self._items.values())
            if kind is not None:
                items = [item for item in items if item.kind == kind]
            if user_id is not None:
                items = [item for item in items if item.user_id == user_id]
            if workspace_id is not None:
                items = [item for item in items if item.workspace_id == workspace_id]
            items.sort(key=lambda item: item.created_at, reverse=True)
            return [deepcopy(item) for item in items]


class InMemoryStrategyRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[str, StrategyVersionRecord] = {}

    def create(self, record: StrategyVersionRecord) -> StrategyVersionRecord:
        with self._lock:
            self._items[record.version_id] = deepcopy(record)
            return deepcopy(record)

    def exists(self, version_id: str) -> bool:
        with self._lock:
            return version_id in self._items

    def list_projects(
        self,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[StrategyVersionRecord]:
        with self._lock:
            items = list(self._items.values())
            if user_id is not None:
                items = [item for item in items if item.user_id == user_id]
            if workspace_id is not None:
                items = [item for item in items if item.workspace_id == workspace_id]
            return [deepcopy(item) for item in items]

    def get(
        self,
        version_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> StrategyVersionRecord | None:
        with self._lock:
            item = self._items.get(version_id)
            if item is None:
                return None
            if user_id is not None and item.user_id != user_id:
                return None
            if workspace_id is not None and item.workspace_id != workspace_id:
                return None
            return deepcopy(item)


class SQLAlchemyStrategyRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, record: StrategyVersionRecord) -> StrategyVersionRecord:
        with self._session_factory() as session:
            orm = StrategyVersionORM(
                version_id=record.version_id,
                project_id=record.project_id,
                user_id=record.user_id,
                workspace_id=record.workspace_id,
                title=record.title,
                natural_language_prompt=record.natural_language_prompt,
                strategy_dsl_json=json.dumps(record.strategy_dsl, ensure_ascii=False),
                strategy_python_text=record.strategy_python,
                created_at=record.created_at,
            )
            session.add(orm)
            session.commit()
        return record

    def exists(self, version_id: str) -> bool:
        with self._session_factory() as session:
            orm = session.get(StrategyVersionORM, version_id)
            return orm is not None

    def list_projects(
        self,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[StrategyVersionRecord]:
        with self._session_factory() as session:
            statement = select(StrategyVersionORM).order_by(StrategyVersionORM.created_at.desc())
            if user_id is not None:
                statement = statement.where(StrategyVersionORM.user_id == user_id)
            if workspace_id is not None:
                statement = statement.where(StrategyVersionORM.workspace_id == workspace_id)
            items = session.scalars(statement).all()
            return [
                StrategyVersionRecord(
                    project_id=item.project_id,
                    version_id=item.version_id,
                    user_id=item.user_id,
                    workspace_id=item.workspace_id,
                    title=item.title,
                    natural_language_prompt=item.natural_language_prompt,
                    strategy_dsl=json.loads(item.strategy_dsl_json),
                    strategy_python=item.strategy_python_text,
                    created_at=item.created_at,
                )
                for item in items
            ]

    def get(
        self,
        version_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> StrategyVersionRecord | None:
        with self._session_factory() as session:
            statement = select(StrategyVersionORM).where(StrategyVersionORM.version_id == version_id)
            if user_id is not None:
                statement = statement.where(StrategyVersionORM.user_id == user_id)
            if workspace_id is not None:
                statement = statement.where(StrategyVersionORM.workspace_id == workspace_id)
            item = session.scalar(statement)
            if item is None:
                return None
            return StrategyVersionRecord(
                project_id=item.project_id,
                version_id=item.version_id,
                user_id=item.user_id,
                workspace_id=item.workspace_id,
                title=item.title,
                natural_language_prompt=item.natural_language_prompt,
                strategy_dsl=json.loads(item.strategy_dsl_json),
                strategy_python=item.strategy_python_text,
                created_at=item.created_at,
            )


class SQLAlchemyDatasetSnapshotRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, record: DatasetSnapshotRecord) -> DatasetSnapshotRecord:
        with self._session_factory() as session:
            session.add(
                DatasetSnapshotORM(
                    dataset_snapshot_ref=record.dataset_snapshot_ref,
                    market=record.market,
                    asset_type=record.asset_type,
                    frequency=record.frequency,
                    adjustment_mode=record.adjustment_mode,
                    date_from=record.date_from,
                    date_to=record.date_to,
                    provider=record.provider,
                    coverage_status=record.coverage_status,
                    created_at=record.created_at,
                )
            )
            session.commit()
        return record

    def get(self, dataset_snapshot_ref: str) -> DatasetSnapshotRecord | None:
        with self._session_factory() as session:
            item = session.get(DatasetSnapshotORM, dataset_snapshot_ref)
            if item is None:
                return None
            return DatasetSnapshotRecord(
                dataset_snapshot_ref=item.dataset_snapshot_ref,
                market=item.market,
                asset_type=item.asset_type,
                frequency=item.frequency,
                adjustment_mode=item.adjustment_mode,
                date_from=item.date_from,
                date_to=item.date_to,
                provider=item.provider,
                coverage_status=item.coverage_status,
                created_at=item.created_at,
            )


class SQLAlchemyUserRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, record: UserRecord) -> UserRecord:
        with self._session_factory() as session:
            session.add(
                UserORM(
                    user_id=record.user_id,
                    username=record.username,
                    contact=record.contact,
                    password_hash=record.password_hash,
                    role=record.role,
                    created_at=record.created_at,
                )
            )
            session.commit()
        return record

    def get_by_username(self, username: str) -> UserRecord | None:
        with self._session_factory() as session:
            item = session.scalar(select(UserORM).where(UserORM.username == username))
            if item is None:
                return None
            return UserRecord(
                user_id=item.user_id,
                username=item.username,
                contact=item.contact,
                password_hash=item.password_hash,
                role=item.role,
                created_at=item.created_at,
            )

    def get(self, user_id: str) -> UserRecord | None:
        with self._session_factory() as session:
            item = session.get(UserORM, user_id)
            if item is None:
                return None
            return UserRecord(
                user_id=item.user_id,
                username=item.username,
                contact=item.contact,
                password_hash=item.password_hash,
                role=item.role,
                created_at=item.created_at,
            )

    def update_role(self, user_id: str, role: str) -> UserRecord | None:
        with self._session_factory() as session:
            item = session.get(UserORM, user_id)
            if item is None:
                return None
            item.role = role
            session.commit()
            session.refresh(item)
            return UserRecord(
                user_id=item.user_id,
                username=item.username,
                contact=item.contact,
                password_hash=item.password_hash,
                role=item.role,
                created_at=item.created_at,
            )

    def list(self) -> list[UserRecord]:
        with self._session_factory() as session:
            items = session.scalars(select(UserORM).order_by(UserORM.created_at.asc())).all()
            return [
                UserRecord(
                    user_id=item.user_id,
                    username=item.username,
                    contact=item.contact,
                    password_hash=item.password_hash,
                    role=item.role,
                    created_at=item.created_at,
                )
                for item in items
            ]


class SQLAlchemyUserSessionRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, record: UserSessionRecord) -> UserSessionRecord:
        with self._session_factory() as session:
            session.add(
                UserSessionORM(
                    session_id=record.session_id,
                    user_id=record.user_id,
                    session_token=record.session_token,
                    created_at=record.created_at,
                )
            )
            session.commit()
        return record

    def get_by_token(self, session_token: str) -> UserSessionRecord | None:
        with self._session_factory() as session:
            item = session.scalar(
                select(UserSessionORM).where(UserSessionORM.session_token == session_token)
            )
            if item is None:
                return None
            return UserSessionRecord(
                session_id=item.session_id,
                user_id=item.user_id,
                session_token=item.session_token,
                created_at=item.created_at,
            )

    def delete_by_token(self, session_token: str) -> None:
        with self._session_factory() as session:
            item = session.scalar(
                select(UserSessionORM).where(UserSessionORM.session_token == session_token)
            )
            if item is not None:
                session.delete(item)
                session.commit()

    def list(self) -> list[UserSessionRecord]:
        with self._session_factory() as session:
            items = session.scalars(
                select(UserSessionORM).order_by(UserSessionORM.created_at.desc())
            ).all()
            return [
                UserSessionRecord(
                    session_id=item.session_id,
                    user_id=item.user_id,
                    session_token=item.session_token,
                    created_at=item.created_at,
                )
                for item in items
            ]


class SQLAlchemyTaskRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, record: TaskRecord) -> TaskRecord:
        with self._session_factory() as session:
            orm = self._to_orm(record)
            session.add(orm)
            session.commit()
        return record

    def get(
        self,
        task_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> TaskRecord | None:
        with self._session_factory() as session:
            statement = select(TaskORM).where(TaskORM.id == task_id)
            if user_id is not None:
                statement = statement.where(TaskORM.user_id == user_id)
            if workspace_id is not None:
                statement = statement.where(TaskORM.workspace_id == workspace_id)
            orm = session.scalar(statement)
            return self._from_orm(orm) if orm else None

    def mark_queued(self, task_id: str) -> TaskRecord | None:
        with self._session_factory() as session:
            orm = session.get(TaskORM, task_id)
            if orm is None or orm.status == TaskStatus.CANCELED.value:
                return self._from_orm(orm) if orm else None
            orm.status = TaskStatus.QUEUED.value
            session.commit()
            session.refresh(orm)
            return self._from_orm(orm)

    def mark_running(self, task_id: str) -> TaskRecord | None:
        with self._session_factory() as session:
            orm = session.get(TaskORM, task_id)
            if orm is None or orm.status == TaskStatus.CANCELED.value:
                return self._from_orm(orm) if orm else None
            orm.status = TaskStatus.RUNNING.value
            orm.progress_pct = 25
            orm.started_at = utcnow()
            session.commit()
            session.refresh(orm)
            return self._from_orm(orm)

    def complete(self, task_id: str, result: dict) -> TaskRecord | None:
        with self._session_factory() as session:
            orm = session.get(TaskORM, task_id)
            if orm is None or orm.status == TaskStatus.CANCELED.value:
                return self._from_orm(orm) if orm else None
            orm.status = TaskStatus.SUCCEEDED.value
            orm.progress_pct = 100
            orm.finished_at = utcnow()
            orm.result_json = json.dumps(result, ensure_ascii=False)
            session.commit()
            session.refresh(orm)
            return self._from_orm(orm)

    def fail(self, task_id: str, error: ErrorPayload) -> TaskRecord | None:
        with self._session_factory() as session:
            orm = session.get(TaskORM, task_id)
            if orm is None:
                return None
            orm.status = TaskStatus.FAILED.value
            orm.finished_at = utcnow()
            orm.error_code = error.code
            orm.error_message = error.message
            orm.error_json = error.model_dump_json()
            session.commit()
            session.refresh(orm)
            return self._from_orm(orm)

    def cancel(self, task_id: str) -> TaskRecord | None:
        with self._session_factory() as session:
            orm = session.get(TaskORM, task_id)
            if orm is None:
                return None
            if orm.status in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}:
                return self._from_orm(orm)
            orm.status = TaskStatus.CANCELING.value
            orm.status = TaskStatus.CANCELED.value
            orm.finished_at = utcnow()
            session.commit()
            session.refresh(orm)
            return self._from_orm(orm)

    def list_ids(self, kind: str | None = None) -> list[str]:
        with self._session_factory() as session:
            statement = select(TaskORM.id)
            if kind is not None:
                statement = statement.where(TaskORM.kind == kind)
            return list(session.scalars(statement))

    def list(
        self,
        kind: str | None = None,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[TaskRecord]:
        with self._session_factory() as session:
            statement = select(TaskORM).order_by(TaskORM.created_at.desc())
            if kind is not None:
                statement = statement.where(TaskORM.kind == kind)
            if user_id is not None:
                statement = statement.where(TaskORM.user_id == user_id)
            if workspace_id is not None:
                statement = statement.where(TaskORM.workspace_id == workspace_id)
            items = session.scalars(statement).all()
            return [self._from_orm(item) for item in items]

    def _to_orm(self, record: TaskRecord) -> TaskORM:
        return TaskORM(
            id=record.id,
            kind=record.kind,
            user_id=record.user_id,
            status=record.status.value,
            progress_pct=record.progress_pct,
            workspace_id=record.workspace_id,
            environment=record.environment,
            resource_refs_json=json.dumps(record.resource_refs, ensure_ascii=False),
            config_revision=record.config_revision,
            created_by=record.created_by,
            request_id=record.request_id,
            trace_id=record.trace_id,
            idempotency_key=record.idempotency_key,
            priority=record.priority,
            retry_count=record.retry_count,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            payload_json=json.dumps(record.payload, ensure_ascii=False),
            result_json=json.dumps(record.result, ensure_ascii=False),
            error_code=record.error.code if record.error else record.error_code,
            error_message=record.error.message if record.error else record.error_message,
            error_json=record.error.model_dump_json() if record.error else None,
        )

    def _from_orm(self, orm: TaskORM) -> TaskRecord:
        error = (
            ErrorPayload.model_validate_json(orm.error_json)
            if orm.error_json
            else (
                ErrorPayload(code=orm.error_code, message=orm.error_message or "")
                if orm.error_code
                else None
            )
        )
        return TaskRecord(
            id=orm.id,
            kind=orm.kind,
            user_id=orm.user_id,
            status=TaskStatus(orm.status),
            progress_pct=orm.progress_pct,
            workspace_id=orm.workspace_id,
            environment=orm.environment,
            resource_refs=json.loads(orm.resource_refs_json),
            config_revision=orm.config_revision,
            created_by=orm.created_by,
            request_id=orm.request_id,
            trace_id=orm.trace_id,
            idempotency_key=orm.idempotency_key,
            priority=orm.priority,
            retry_count=orm.retry_count,
            created_at=orm.created_at,
            started_at=orm.started_at,
            finished_at=orm.finished_at,
            payload=json.loads(orm.payload_json),
            result=json.loads(orm.result_json),
            error=error,
            error_code=error.code if error else orm.error_code,
            error_message=error.message if error else orm.error_message,
        )


class SQLAlchemyTradeUploadRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, record: TradeUploadRecord) -> TradeUploadRecord:
        with self._session_factory() as session:
            orm = self._to_orm(record)
            session.add(orm)
            session.commit()
        return record

    def get(
        self,
        upload_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> TradeUploadRecord | None:
        with self._session_factory() as session:
            statement = select(TradeUploadORM).where(TradeUploadORM.upload_id == upload_id)
            if user_id is not None:
                statement = statement.where(TradeUploadORM.user_id == user_id)
            if workspace_id is not None:
                statement = statement.where(TradeUploadORM.workspace_id == workspace_id)
            orm = session.scalar(statement)
            return self._from_orm(orm) if orm else None

    def update(self, record: TradeUploadRecord) -> TradeUploadRecord:
        with self._session_factory() as session:
            orm = session.get(TradeUploadORM, record.upload_id)
            if orm is None:
                orm = self._to_orm(record)
                session.add(orm)
            else:
                orm.source_file_name = record.source_file_name
                orm.user_id = record.user_id
                orm.workspace_id = record.workspace_id
                orm.raw_text = record.raw_text
                orm.status = record.status
                orm.detected_columns_json = json.dumps(
                    record.detected_columns, ensure_ascii=False
                )
                orm.column_mapping_json = json.dumps(
                    record.column_mapping, ensure_ascii=False
                )
                orm.records_json = json.dumps(
                    [item.model_dump(mode="json") for item in record.records],
                    ensure_ascii=False,
                )
            session.commit()
        return record

    def _to_orm(self, record: TradeUploadRecord) -> TradeUploadORM:
        return TradeUploadORM(
            upload_id=record.upload_id,
            user_id=record.user_id,
            workspace_id=record.workspace_id,
            source_file_name=record.source_file_name,
            raw_text=record.raw_text,
            status=record.status,
            detected_columns_json=json.dumps(record.detected_columns, ensure_ascii=False),
            column_mapping_json=json.dumps(record.column_mapping, ensure_ascii=False),
            records_json=json.dumps(
                [item.model_dump(mode="json") for item in record.records],
                ensure_ascii=False,
            ),
            created_at=record.created_at,
        )

    def _from_orm(self, orm: TradeUploadORM) -> TradeUploadRecord:
        return TradeUploadRecord(
            upload_id=orm.upload_id,
            user_id=orm.user_id,
            workspace_id=orm.workspace_id,
            source_file_name=orm.source_file_name,
            raw_text=orm.raw_text,
            status=orm.status,
            detected_columns=json.loads(orm.detected_columns_json),
            column_mapping=json.loads(orm.column_mapping_json),
            records=[
                TradeRecordItem.model_validate(item)
                for item in json.loads(orm.records_json)
            ],
            created_at=orm.created_at,
        )


class SQLAlchemyCustomIndicatorRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, record: CustomIndicatorRecord) -> CustomIndicatorRecord:
        with self._session_factory() as session:
            orm = CustomIndicatorORM(
                indicator_id=record.indicator_id,
                name=record.name,
                natural_language_prompt=record.natural_language_prompt,
                summary=record.summary,
                formula_text=record.formula_text,
                python_code_text=record.python_code,
                usage_hint=record.usage_hint,
                tags_json=json.dumps(record.tags, ensure_ascii=False),
                created_at=record.created_at,
            )
            session.add(orm)
            session.commit()
        return record

    def list(self) -> list[CustomIndicatorRecord]:
        with self._session_factory() as session:
            items = session.scalars(
                select(CustomIndicatorORM).order_by(CustomIndicatorORM.created_at.desc())
            ).all()
            return [
                CustomIndicatorRecord(
                    indicator_id=item.indicator_id,
                    name=item.name,
                    natural_language_prompt=item.natural_language_prompt,
                    summary=item.summary,
                    formula_text=item.formula_text,
                    python_code=item.python_code_text,
                    usage_hint=item.usage_hint,
                    tags=json.loads(item.tags_json),
                    created_at=item.created_at,
                )
                for item in items
            ]


class SQLAlchemyGlossaryTermRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, record: GlossaryTermRecord) -> GlossaryTermRecord:
        with self._session_factory() as session:
            orm = GlossaryTermORM(
                term_id=record.term_id,
                term=record.term,
                meaning=record.meaning,
                example=record.example,
                created_at=record.created_at,
            )
            session.add(orm)
            session.commit()
        return record

    def list(self) -> list[GlossaryTermRecord]:
        with self._session_factory() as session:
            items = session.scalars(
                select(GlossaryTermORM).order_by(GlossaryTermORM.created_at.desc())
            ).all()
            return [
                GlossaryTermRecord(
                    term_id=item.term_id,
                    term=item.term,
                    meaning=item.meaning,
                    example=item.example,
                    created_at=item.created_at,
                )
                for item in items
            ]


class SQLAlchemyDefaultRuleRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def list(self) -> list[DefaultRuleSection]:
        with self._session_factory() as session:
            items = session.scalars(
                select(DefaultRuleSectionORM).order_by(DefaultRuleSectionORM.updated_at.asc())
            ).all()
            return [
                DefaultRuleSection(
                    section_id=item.section_id,
                    section=item.section,
                    items=json.loads(item.items_json),
                    updated_at=item.updated_at,
                )
                for item in items
            ]

    def replace_all(self, records: list[DefaultRuleSection]) -> list[DefaultRuleSection]:
        with self._session_factory() as session:
            session.execute(delete(DefaultRuleSectionORM))
            for record in records:
                session.add(
                    DefaultRuleSectionORM(
                        section_id=record.section_id,
                        section=record.section,
                        items_json=json.dumps(
                            [item.model_dump() for item in record.items],
                            ensure_ascii=False,
                        ),
                        updated_at=record.updated_at,
                    )
                )
            session.commit()
        return records
