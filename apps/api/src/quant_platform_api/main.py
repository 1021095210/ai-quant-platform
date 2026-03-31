from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from quant_platform_api.market_data import (
    AkshareMarketDataProvider,
    DemoMarketDataProvider,
    MarketDataCacheRepository,
    MarketDataService,
    TushareMarketDataProvider,
)
from quant_platform_api.config import Settings
from quant_platform_api.db import build_session_factory, create_schema
from quant_platform_api.models import (
    BacktestCreateRequest,
    CustomIndicatorCreateRequest,
    CustomIndicatorGenerateRequest,
    ErrorPayload,
    GlossaryTermCreateRequest,
    OptimizationCreateRequest,
    ProjectCreateRequest,
    TradeUploadParseRequest,
    StrategyGenerateRequest,
    ReplayCreateRequest,
    SuccessEnvelope,
    TaskStatus,
)
from quant_platform_api.repository import (
    SQLAlchemyCustomIndicatorRepository,
    SQLAlchemyGlossaryTermRepository,
    SQLAlchemyStrategyRepository,
    SQLAlchemyTaskRepository,
    SQLAlchemyTradeUploadRepository,
)
from quant_platform_api.services import (
    AsyncTaskService,
    IndicatorService,
    RuleService,
    StrategyService,
    TradeUploadService,
    build_backtest_result,
    build_optimization_result,
    build_replay_result,
)


@dataclass(slots=True)
class AppServices:
    settings: Settings
    strategy_service: StrategyService
    indicator_service: IndicatorService
    rule_service: RuleService
    trade_upload_service: TradeUploadService
    market_data_service: MarketDataService
    backtest_service: AsyncTaskService
    optimization_service: AsyncTaskService
    replay_service: AsyncTaskService


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    session_factory = build_session_factory(app_settings.database_url)
    create_schema(session_factory)
    strategy_repository = SQLAlchemyStrategyRepository(session_factory)
    trade_upload_repository = SQLAlchemyTradeUploadRepository(session_factory)
    task_repository = SQLAlchemyTaskRepository(session_factory)
    indicator_repository = SQLAlchemyCustomIndicatorRepository(session_factory)
    glossary_repository = SQLAlchemyGlossaryTermRepository(session_factory)
    primary_market_provider = None
    if app_settings.market_data_provider in {"auto", "tushare"}:
        primary_market_provider = TushareMarketDataProvider(app_settings.tushare_token)

    fallback_market_provider = (
        DemoMarketDataProvider()
        if app_settings.market_data_provider == "demo"
        else AkshareMarketDataProvider()
    )
    market_data_service = MarketDataService(
        cache_repository=MarketDataCacheRepository(
            app_settings.market_data_database_path
        ),
        primary_provider=primary_market_provider,
        fallback_provider=fallback_market_provider,
    )
    services = AppServices(
        settings=app_settings,
        strategy_service=StrategyService(
            strategy_repository,
            indicator_repository,
            glossary_repository,
        ),
        indicator_service=IndicatorService(indicator_repository),
        rule_service=RuleService(glossary_repository),
        trade_upload_service=TradeUploadService(trade_upload_repository),
        market_data_service=market_data_service,
        backtest_service=AsyncTaskService(
            repository=task_repository,
            settings=app_settings,
        ),
        optimization_service=AsyncTaskService(
            repository=task_repository,
            settings=app_settings,
        ),
        replay_service=AsyncTaskService(
            repository=task_repository,
            settings=app_settings,
        ),
    )

    app = FastAPI(title=app_settings.app_name)
    app.state.services = services
    app.state.session_factory = session_factory
    app.state.task_repository = task_repository
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "dashboard.html")

    @app.get("/strategy")
    def strategy_page() -> FileResponse:
        return FileResponse(static_dir / "strategy.html")

    @app.get("/backtests")
    def backtests_page() -> FileResponse:
        return FileResponse(static_dir / "backtests.html")

    @app.get("/replay")
    def replay_page() -> FileResponse:
        return FileResponse(static_dir / "replay.html")

    @app.get("/indicators")
    def indicators_page() -> FileResponse:
        return FileResponse(static_dir / "indicators.html")

    @app.get("/rules")
    def rules_page() -> FileResponse:
        return FileResponse(static_dir / "rules.html")

    @app.get("/healthz")
    def healthz() -> SuccessEnvelope:
        return SuccessEnvelope(
            data={
                "status": "ok",
                "app_name": app_settings.app_name,
                "job_execution_mode": app_settings.job_execution_mode,
            }
        )

    @app.post(f"{app_settings.api_prefix}/strategies/generate")
    def generate_strategy(request: StrategyGenerateRequest) -> SuccessEnvelope:
        generated = services.strategy_service.generate_strategy(request)
        return SuccessEnvelope(data=generated)

    @app.get(f"{app_settings.api_prefix}/indicators/builtin")
    def list_builtin_indicators() -> SuccessEnvelope:
        return SuccessEnvelope(data={"items": services.indicator_service.list_builtin()})

    @app.get(f"{app_settings.api_prefix}/indicators/custom")
    def list_custom_indicators() -> SuccessEnvelope:
        return SuccessEnvelope(
            data={
                "items": [
                    item.model_dump(mode="json")
                    for item in services.indicator_service.list_custom()
                ]
            }
        )

    @app.post(f"{app_settings.api_prefix}/indicators/custom/generate")
    def generate_custom_indicator(
        request: CustomIndicatorGenerateRequest,
    ) -> SuccessEnvelope:
        generated = services.indicator_service.generate_custom_indicator(request)
        return SuccessEnvelope(data=generated)

    @app.post(f"{app_settings.api_prefix}/indicators/custom")
    def create_custom_indicator(
        request: CustomIndicatorCreateRequest,
    ) -> SuccessEnvelope:
        record = services.indicator_service.create_custom(request)
        return SuccessEnvelope(data=record.model_dump(mode="json"))

    @app.get(f"{app_settings.api_prefix}/rules/defaults")
    def list_default_rules() -> SuccessEnvelope:
        return SuccessEnvelope(data={"items": services.rule_service.list_default_rules()})

    @app.get(f"{app_settings.api_prefix}/rules/glossary")
    def list_glossary_terms() -> SuccessEnvelope:
        return SuccessEnvelope(data={"items": services.rule_service.list_glossary_terms()})

    @app.post(f"{app_settings.api_prefix}/rules/glossary")
    def create_glossary_term(request: GlossaryTermCreateRequest) -> SuccessEnvelope:
        record = services.rule_service.create_glossary_term(request)
        return SuccessEnvelope(data=record.model_dump(mode="json"))

    @app.post(f"{app_settings.api_prefix}/strategies/projects")
    def create_strategy_project(request: ProjectCreateRequest) -> SuccessEnvelope:
        version = services.strategy_service.create_project(
            title=request.title,
            natural_language_prompt=request.natural_language_prompt,
            strategy_dsl=request.strategy_dsl,
            strategy_python=request.strategy_python,
        )
        return SuccessEnvelope(
            data={
                "project_id": version.project_id,
                "version_id": version.version_id,
            }
        )

    @app.get(f"{app_settings.api_prefix}/strategies/projects")
    def list_strategy_projects() -> SuccessEnvelope:
        items = services.strategy_service.list_projects()
        return SuccessEnvelope(
            data={
                "items": [
                    {
                        "project_id": item.project_id,
                        "version_id": item.version_id,
                        "title": item.title,
                        "natural_language_prompt": item.natural_language_prompt,
                        "strategy_dsl": item.strategy_dsl,
                        "strategy_python": item.strategy_python,
                        "created_at": item.created_at.isoformat(),
                    }
                    for item in items
                ]
            }
        )

    @app.get(f"{app_settings.api_prefix}/strategies/projects/{{version_id}}")
    def get_strategy_project(version_id: str) -> SuccessEnvelope:
        item = services.strategy_service.get_project(version_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="PROJECT_NOT_FOUND",
                    message="strategy project not found",
                ).model_dump(),
            )
        return SuccessEnvelope(
            data={
                "project_id": item.project_id,
                "version_id": item.version_id,
                "title": item.title,
                "natural_language_prompt": item.natural_language_prompt,
                "strategy_dsl": item.strategy_dsl,
                "strategy_python": item.strategy_python,
                "created_at": item.created_at.isoformat(),
            }
        )

    @app.post(f"{app_settings.api_prefix}/backtests/runs")
    def create_backtest_run(request: BacktestCreateRequest) -> SuccessEnvelope:
        record = services.backtest_service.submit(
            kind="backtest",
            payload=request.model_dump(by_alias=True, mode="json"),
            build_result=build_backtest_result(
                app_settings,
                services.strategy_service,
                services.market_data_service,
            ),
        )
        return SuccessEnvelope(
            data={
                "backtest_run_id": record.id,
                "status": record.status.value,
                "progress_pct": record.progress_pct,
                "status_url": f"{app_settings.api_prefix}/backtests/runs/{record.id}",
                "result_url": f"{app_settings.api_prefix}/backtests/runs/{record.id}",
            }
        )

    @app.get(f"{app_settings.api_prefix}/backtests/runs")
    def list_backtest_runs() -> SuccessEnvelope:
        records = task_repository.list("backtest")
        return SuccessEnvelope(
            data={
                "items": [
                    {
                        "backtest_run_id": record.id,
                        "status": record.status.value,
                        "created_at": record.created_at.isoformat(),
                        "strategy_version_id": record.payload.get("strategy_version_id"),
                        "strategy_title": record.result.get("strategy_title", ""),
                        "market": record.payload.get("dataset", {}).get("market"),
                        "timeframe": record.payload.get("dataset", {}).get("timeframe"),
                        "metrics": record.result.get("metrics", {}),
                        "data_source": record.result.get("data_source", {}),
                    }
                    for record in records
                ]
            }
        )

    @app.get(f"{app_settings.api_prefix}/backtests/runs/{{backtest_run_id}}")
    def get_backtest_run(backtest_run_id: str) -> SuccessEnvelope:
        record = _require_task(services.backtest_service.get(backtest_run_id))
        return SuccessEnvelope(data=_serialize_task(record, "backtest_run_id"))

    @app.post(f"{app_settings.api_prefix}/backtests/runs/{{backtest_run_id}}/cancel")
    def cancel_backtest_run(backtest_run_id: str) -> SuccessEnvelope:
        record = _require_task(services.backtest_service.cancel(backtest_run_id))
        return SuccessEnvelope(
            data={
                "backtest_run_id": record.id,
                "status": record.status.value,
            }
        )

    @app.post(f"{app_settings.api_prefix}/optimization-jobs")
    def create_optimization_job(request: OptimizationCreateRequest) -> SuccessEnvelope:
        record = services.optimization_service.submit(
            kind="optimization",
            payload=request.model_dump(by_alias=True, mode="json"),
            build_result=build_optimization_result(),
        )
        return SuccessEnvelope(
            data={
                "job_id": record.id,
                "status": record.status.value,
                "progress_pct": record.progress_pct,
                "status_url": f"{app_settings.api_prefix}/optimization-jobs/{record.id}",
                "result_url": f"{app_settings.api_prefix}/optimization-jobs/{record.id}",
            }
        )

    @app.get(f"{app_settings.api_prefix}/optimization-jobs/{{job_id}}")
    def get_optimization_job(job_id: str) -> SuccessEnvelope:
        record = _require_task(services.optimization_service.get(job_id))
        return SuccessEnvelope(data=_serialize_task(record, "job_id"))

    @app.post(f"{app_settings.api_prefix}/optimization-jobs/{{job_id}}/cancel")
    def cancel_optimization_job(job_id: str) -> SuccessEnvelope:
        record = _require_task(services.optimization_service.cancel(job_id))
        return SuccessEnvelope(data={"job_id": record.id, "status": record.status.value})

    @app.post(f"{app_settings.api_prefix}/replays/analyses")
    def create_replay_analysis(request: ReplayCreateRequest) -> SuccessEnvelope:
        record = services.replay_service.submit(
            kind="replay",
            payload=request.model_dump(mode="json"),
            build_result=build_replay_result(
                app_settings,
                services.trade_upload_service,
            ),
        )
        return SuccessEnvelope(
            data={
                "analysis_id": record.id,
                "status": record.status.value,
                "progress_pct": record.progress_pct,
                "status_url": f"{app_settings.api_prefix}/replays/analyses/{record.id}",
                "result_url": f"{app_settings.api_prefix}/replays/analyses/{record.id}",
            }
        )

    @app.get(f"{app_settings.api_prefix}/replays/analyses/{{analysis_id}}")
    def get_replay_analysis(analysis_id: str) -> SuccessEnvelope:
        record = _require_task(services.replay_service.get(analysis_id))
        return SuccessEnvelope(data=_serialize_task(record, "analysis_id"))

    @app.post(f"{app_settings.api_prefix}/replays/analyses/{{analysis_id}}/cancel")
    def cancel_replay_analysis(analysis_id: str) -> SuccessEnvelope:
        record = _require_task(services.replay_service.cancel(analysis_id))
        return SuccessEnvelope(
            data={"analysis_id": record.id, "status": record.status.value}
        )

    @app.post(f"{app_settings.api_prefix}/trades/uploads")
    async def upload_trades(file: UploadFile = File(...)) -> SuccessEnvelope:
        raw = (await file.read()).decode("utf-8")
        upload = services.trade_upload_service.create_upload(file.filename, raw)
        return SuccessEnvelope(
            data={
                "upload_id": upload.upload_id,
                "status": upload.status,
                "detected_columns": upload.detected_columns,
            }
        )

    @app.post(f"{app_settings.api_prefix}/trades/uploads/{{upload_id}}/parse")
    def parse_trade_upload(
        upload_id: str,
        payload: TradeUploadParseRequest,
    ) -> SuccessEnvelope:
        mapping = payload.column_mapping
        upload = services.trade_upload_service.parse_upload(upload_id, mapping)
        if upload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="UPLOAD_NOT_FOUND",
                    message="trade upload not found",
                ).model_dump(),
            )
        return SuccessEnvelope(
            data={
                "upload_id": upload.upload_id,
                "raw_row_count": len(upload.raw_text.splitlines()) - 1,
                "fill_count": len(upload.records),
                "record_count": len(upload.records),
                "status": upload.status,
            }
        )

    @app.get(f"{app_settings.api_prefix}/trades/uploads/{{upload_id}}/records")
    def get_trade_records(upload_id: str) -> SuccessEnvelope:
        upload = services.trade_upload_service.get_upload(upload_id)
        if upload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="UPLOAD_NOT_FOUND",
                    message="trade upload not found",
                ).model_dump(),
            )
        return SuccessEnvelope(
            data={"items": [item.model_dump(mode="json") for item in upload.records]}
        )

    return app


def _require_task(record: Any) -> Any:
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorPayload(code="TASK_NOT_FOUND", message="task not found").model_dump(),
        )
    return record


def _serialize_task(record: Any, identifier_key: str) -> dict[str, Any]:
    payload = {
        identifier_key: record.id,
        "status": record.status.value,
        "progress_pct": record.progress_pct,
    }
    payload.update(record.result)
    if record.error is not None:
        payload["error"] = record.error.model_dump()
    if record.status == TaskStatus.CANCELLED:
        payload["error"] = {
            "code": "TASK_CANCELLED",
            "message": "task was cancelled",
            "details": {},
        }
    return payload
