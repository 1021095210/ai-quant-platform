from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from quant_platform_api.market_data import (
    AkshareMarketDataProvider,
    ClickHouseMarketDataProvider,
    DemoMarketDataProvider,
    MarketDataCacheRepository,
    MarketDataService,
    TushareMarketDataProvider,
)
from quant_platform_api.config import Settings
from quant_platform_api.db import build_session_factory, create_schema
from quant_platform_api.models import (
    AdminUserPasswordResetRequest,
    AdminUserRoleUpdateRequest,
    AdminUserStatusUpdateRequest,
    BacktestCreateRequest,
    ClientErrorReportRequest,
    CustomIndicatorCreateRequest,
    CustomIndicatorGenerateRequest,
    DataSnapshotConfig,
    DefaultRuleUpdateRequest,
    DatasetSnapshotRecord,
    ErrorEnvelope,
    ErrorPayload,
    AssistantResearchRequest,
    MentorAskRequest,
    GlossaryTermCreateRequest,
    ManualTradeTextParseRequest,
    TradeUploadManualCreateRequest,
    OptimizationCreateRequest,
    ProjectCreateRequest,
    TradeUploadParseRequest,
    StrategyGenerateRequest,
    ReplayCreateRequest,
    SuccessEnvelope,
    TaskStatus,
    UserLoginRequest,
    UserRegisterRequest,
    utcnow,
)
from quant_platform_api.repository import (
    SQLAlchemyAdminAuditLogRepository,
    SQLAlchemyApplicationLogRepository,
    SQLAlchemyAuthEventRepository,
    SQLAlchemyCustomIndicatorRepository,
    SQLAlchemyDefaultRuleRepository,
    SQLAlchemyDatasetSnapshotRepository,
    SQLAlchemyGlossaryTermRepository,
    SQLAlchemyStrategyRepository,
    SQLAlchemyTaskRepository,
    SQLAlchemyTradeUploadRepository,
    SQLAlchemyUserRepository,
    SQLAlchemyUserSessionRepository,
)
from quant_platform_api.services import (
    AsyncTaskService,
    AuthService,
    AdminService,
    AppLogService,
    FinancialAssistantService,
    IndicatorService,
    MentorService,
    RuleService,
    StrategyService,
    TradeUploadService,
    WorkspaceService,
    build_assistant_research_result,
    _normalize_execution_contract,
    build_mentor_answer_result,
    build_backtest_result,
    build_optimization_result,
    build_replay_result,
    build_trade_screenshot_ocr_result,
    build_strategy_generation_result,
    build_trade_text_parse_result,
    list_llm_profiles,
    list_platform_capabilities,
    make_json_safe,
    summarize_strategy_capability,
    validate_backtest_capability,
)

SESSION_COOKIE_NAME = "quant_session"


@dataclass(slots=True)
class AppServices:
    settings: Settings
    auth_service: AuthService
    app_log_service: AppLogService
    admin_service: AdminService
    strategy_service: StrategyService
    indicator_service: IndicatorService
    rule_service: RuleService
    mentor_service: MentorService
    assistant_service: FinancialAssistantService
    trade_upload_service: TradeUploadService
    workspace_service: WorkspaceService
    market_data_service: MarketDataService
    strategy_generation_service: AsyncTaskService
    mentor_answer_service: AsyncTaskService
    assistant_research_service: AsyncTaskService
    trade_text_parse_service: AsyncTaskService
    backtest_service: AsyncTaskService
    optimization_service: AsyncTaskService
    replay_service: AsyncTaskService


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    session_factory = build_session_factory(app_settings.database_url)
    create_schema(session_factory)
    strategy_repository = SQLAlchemyStrategyRepository(session_factory)
    dataset_snapshot_repository = SQLAlchemyDatasetSnapshotRepository(session_factory)
    trade_upload_repository = SQLAlchemyTradeUploadRepository(session_factory)
    task_repository = SQLAlchemyTaskRepository(session_factory)
    indicator_repository = SQLAlchemyCustomIndicatorRepository(session_factory)
    glossary_repository = SQLAlchemyGlossaryTermRepository(session_factory)
    default_rule_repository = SQLAlchemyDefaultRuleRepository(session_factory)
    user_repository = SQLAlchemyUserRepository(session_factory)
    user_session_repository = SQLAlchemyUserSessionRepository(session_factory)
    auth_event_repository = SQLAlchemyAuthEventRepository(session_factory)
    admin_audit_log_repository = SQLAlchemyAdminAuditLogRepository(session_factory)
    application_log_repository = SQLAlchemyApplicationLogRepository(session_factory)
    primary_market_provider = None
    if app_settings.clickhouse_host and app_settings.market_data_provider in {"auto", "clickhouse"}:
        primary_market_provider = ClickHouseMarketDataProvider(
            host=app_settings.clickhouse_host,
            port=app_settings.clickhouse_port,
            username=app_settings.clickhouse_username,
            password=app_settings.clickhouse_password,
            secure=app_settings.clickhouse_secure,
        )
    elif app_settings.market_data_provider in {"auto", "tushare"}:
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
    strategy_service = StrategyService(
        strategy_repository,
        indicator_repository,
        glossary_repository,
        app_settings,
    )
    services = AppServices(
        settings=app_settings,
        auth_service=AuthService(
            user_repository=user_repository,
            session_repository=user_session_repository,
            auth_event_repository=auth_event_repository,
        ),
        app_log_service=AppLogService(application_log_repository),
        admin_service=AdminService(
            user_repository=user_repository,
            session_repository=user_session_repository,
            auth_event_repository=auth_event_repository,
            audit_log_repository=admin_audit_log_repository,
            app_log_repository=application_log_repository,
            strategy_repository=strategy_repository,
            task_repository=task_repository,
        ),
        strategy_service=strategy_service,
        indicator_service=IndicatorService(indicator_repository),
        rule_service=RuleService(glossary_repository, default_rule_repository),
        mentor_service=MentorService(app_settings),
        assistant_service=FinancialAssistantService(
            app_settings,
            market_data_service=market_data_service,
        ),
        trade_upload_service=TradeUploadService(
            trade_upload_repository,
            market_data_service=market_data_service,
            settings=app_settings,
        ),
        workspace_service=WorkspaceService(
            strategy_service=strategy_service,
            task_repository=task_repository,
            market_data_service=market_data_service,
        ),
        market_data_service=market_data_service,
        strategy_generation_service=AsyncTaskService(
            repository=task_repository,
            settings=app_settings,
        ),
        mentor_answer_service=AsyncTaskService(
            repository=task_repository,
            settings=app_settings,
        ),
        assistant_research_service=AsyncTaskService(
            repository=task_repository,
            settings=app_settings,
        ),
        trade_text_parse_service=AsyncTaskService(
            repository=task_repository,
            settings=app_settings,
        ),
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
    services.auth_service.seed_initial_accounts(
        enable_default_accounts=app_settings.enable_default_accounts,
        initial_admin_username=app_settings.initial_admin_username,
        initial_admin_contact=app_settings.initial_admin_contact,
        initial_admin_password=app_settings.initial_admin_password,
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request_id = _resolve_request_id(request)
        request.state.request_id = request_id
        request.state.trace_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = detail.get("code") or _default_error_code(exc.status_code)
        message = detail.get("message") or _default_error_message(code)
        if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            services.app_log_service.record(
                message=message,
                source="server",
                category="http_exception",
                request_path=str(request.url.path),
                user=_get_current_user(request, services.auth_service),
                details={
                    "status_code": exc.status_code,
                    "code": code,
                    "details": detail.get("details", {}),
                },
            )
        return _error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            details=detail.get("details", {}),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        error_details = {"errors": make_json_safe(exc.errors())}
        services.app_log_service.record(
            message="request validation failed",
            source="server",
            category="validation_error",
            level="warning",
            request_path=str(request.url.path),
            user=_get_current_user(request, services.auth_service),
            details=error_details,
        )
        return _error_response(
            request,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_ARGUMENT",
            message="invalid request",
            details=error_details,
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        services.app_log_service.record(
            message=str(exc) or "internal error",
            source="server",
            category="unhandled_exception",
            request_path=str(request.url.path),
            user=_get_current_user(request, services.auth_service),
            details={"type": exc.__class__.__name__},
        )
        return _error_response(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message=str(exc) or "internal error",
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "dashboard.html")

    @app.get("/login")
    def login_page(request: Request):
        if _get_current_user(request, services.auth_service) is not None:
            return RedirectResponse(url="/workspace", status_code=status.HTTP_302_FOUND)
        return FileResponse(static_dir / "login.html")

    @app.get("/register")
    def register_page(request: Request):
        if _get_current_user(request, services.auth_service) is not None:
            return RedirectResponse(url="/workspace", status_code=status.HTTP_302_FOUND)
        return FileResponse(static_dir / "register.html")

    @app.get("/workspace")
    def workspace_page(request: Request):
        if _get_current_user(request, services.auth_service) is None:
            return _login_redirect("/workspace")
        return FileResponse(static_dir / "workspace.html")

    @app.get("/admin")
    def admin_page(request: Request):
        user = _get_current_user(request, services.auth_service)
        if user is None:
            return _login_redirect("/admin")
        if not services.auth_service.is_admin(user):
            return RedirectResponse(url="/workspace", status_code=status.HTTP_302_FOUND)
        return FileResponse(static_dir / "admin.html")

    @app.get("/strategy")
    def strategy_page(request: Request):
        if _get_current_user(request, services.auth_service) is None:
            return _login_redirect("/strategy")
        return FileResponse(static_dir / "strategy.html")

    @app.get("/backtests")
    def backtests_page(request: Request):
        if _get_current_user(request, services.auth_service) is None:
            return _login_redirect("/backtests")
        return FileResponse(static_dir / "backtests.html")

    @app.get("/replay")
    def replay_page(request: Request):
        if _get_current_user(request, services.auth_service) is None:
            return _login_redirect("/replay")
        return FileResponse(static_dir / "replay.html")

    @app.get("/indicators")
    def indicators_page(request: Request):
        if _get_current_user(request, services.auth_service) is None:
            return _login_redirect("/indicators")
        return FileResponse(static_dir / "indicators.html")

    @app.get("/rules")
    def rules_page(request: Request):
        if _get_current_user(request, services.auth_service) is None:
            return _login_redirect("/rules")
        return FileResponse(static_dir / "rules.html")

    @app.get("/mentor")
    def mentor_page(request: Request):
        if _get_current_user(request, services.auth_service) is None:
            return _login_redirect("/mentor")
        return FileResponse(static_dir / "mentor.html")

    @app.get("/assistant")
    def assistant_page(request: Request):
        if _get_current_user(request, services.auth_service) is None:
            return _login_redirect("/assistant")
        return FileResponse(static_dir / "assistant.html")

    @app.get(f"{app_settings.api_prefix}/auth/me")
    def get_current_user(request: Request) -> JSONResponse:
        user = _get_current_user(request, services.auth_service)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ErrorPayload(code="UNAUTHORIZED", message="login required").model_dump(),
            )
        return _success_response(request, data=user.model_dump(mode="json"))

    @app.get(f"{app_settings.api_prefix}/workspace/summary")
    def get_workspace_summary(request: Request) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        return _success_response(
            request,
            data=services.workspace_service.build_summary(
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            ),
        )

    @app.get(f"{app_settings.api_prefix}/admin/summary")
    def get_admin_summary(request: Request) -> JSONResponse:
        _require_admin_user(request, services.auth_service)
        return _success_response(
            request,
            data=services.admin_service.build_summary(),
        )

    @app.get(f"{app_settings.api_prefix}/admin/users")
    def list_admin_users(request: Request) -> JSONResponse:
        _require_admin_user(request, services.auth_service)
        return _success_response(
            request,
            data={"items": services.admin_service.list_users()},
        )

    @app.put(f"{app_settings.api_prefix}/admin/users/{{user_id}}/role")
    def update_admin_user_role(
        request: Request,
        user_id: str,
        payload: AdminUserRoleUpdateRequest,
    ) -> JSONResponse:
        current_user = _require_admin_user(request, services.auth_service)
        try:
            updated = services.admin_service.update_user_role(
                current_user_id=current_user.user_id,
                target_user_id=user_id,
                role=payload.role,
            )
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "message"):
                status_code = status.HTTP_404_NOT_FOUND if exc.code == "NOT_FOUND" else (
                    status.HTTP_409_CONFLICT if exc.code == "STATE_CONFLICT" else status.HTTP_400_BAD_REQUEST
                )
                raise HTTPException(
                    status_code=status_code,
                    detail=ErrorPayload(code=exc.code, message=exc.message).model_dump(),
                ) from exc
            raise
        return _success_response(
            request,
            data={
                "user_id": updated.user_id,
                "username": updated.username,
                "role": updated.role,
            },
        )

    @app.put(f"{app_settings.api_prefix}/admin/users/{{user_id}}/status")
    def update_admin_user_status(
        request: Request,
        user_id: str,
        payload: AdminUserStatusUpdateRequest,
    ) -> JSONResponse:
        current_user = _require_admin_user(request, services.auth_service)
        try:
            updated = services.admin_service.update_user_status(
                current_user_id=current_user.user_id,
                target_user_id=user_id,
                status=payload.status,
                reason=payload.reason,
            )
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "message"):
                status_code = status.HTTP_404_NOT_FOUND if exc.code == "NOT_FOUND" else (
                    status.HTTP_409_CONFLICT if exc.code == "STATE_CONFLICT" else status.HTTP_400_BAD_REQUEST
                )
                raise HTTPException(
                    status_code=status_code,
                    detail=ErrorPayload(code=exc.code, message=exc.message).model_dump(),
                ) from exc
            raise
        return _success_response(
            request,
            data={
                "user_id": updated.user_id,
                "username": updated.username,
                "status": updated.status,
                "status_reason": updated.status_reason,
            },
        )

    @app.post(f"{app_settings.api_prefix}/admin/users/{{user_id}}/reset-password")
    def reset_admin_user_password(
        request: Request,
        user_id: str,
        payload: AdminUserPasswordResetRequest,
    ) -> JSONResponse:
        current_user = _require_admin_user(request, services.auth_service)
        try:
            updated = services.admin_service.reset_user_password(
                current_user_id=current_user.user_id,
                target_user_id=user_id,
                new_password=payload.new_password,
            )
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "message"):
                status_code = status.HTTP_404_NOT_FOUND if exc.code == "NOT_FOUND" else (
                    status.HTTP_409_CONFLICT if exc.code == "STATE_CONFLICT" else status.HTTP_400_BAD_REQUEST
                )
                raise HTTPException(
                    status_code=status_code,
                    detail=ErrorPayload(code=exc.code, message=exc.message).model_dump(),
                ) from exc
            raise
        return _success_response(
            request,
            data={
                "user_id": updated.user_id,
                "username": updated.username,
                "password_reset": True,
            },
        )

    @app.get(f"{app_settings.api_prefix}/admin/audit-logs")
    def list_admin_audit_logs(request: Request) -> JSONResponse:
        _require_admin_user(request, services.auth_service)
        return _success_response(
            request,
            data={"items": services.admin_service.list_audit_logs()},
        )

    @app.get(f"{app_settings.api_prefix}/admin/security-events")
    def list_admin_security_events(request: Request) -> JSONResponse:
        _require_admin_user(request, services.auth_service)
        return _success_response(
            request,
            data={"items": services.admin_service.list_security_events()},
        )

    @app.get(f"{app_settings.api_prefix}/admin/app-logs")
    def list_admin_app_logs(request: Request) -> JSONResponse:
        _require_admin_user(request, services.auth_service)
        return _success_response(
            request,
            data={"items": services.admin_service.list_app_logs()},
        )

    @app.post(f"{app_settings.api_prefix}/auth/register")
    def register_user(
        request: Request,
        payload: UserRegisterRequest,
    ) -> JSONResponse:
        try:
            user = services.auth_service.register(
                username=payload.username,
                contact=payload.contact,
                password=payload.password,
            )
            user, session_token = services.auth_service.login(
                username=payload.username,
                password=payload.password,
                ip_address=_client_ip(request),
            )
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "message"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT
                    if exc.code == "STATE_CONFLICT"
                    else status.HTTP_400_BAD_REQUEST,
                    detail=ErrorPayload(code=exc.code, message=exc.message).model_dump(),
                ) from exc
            raise
        response = _success_response(request, data=user.model_dump(mode="json"))
        _set_session_cookie(response, session_token, app_settings)
        return response

    @app.post(f"{app_settings.api_prefix}/auth/login")
    def login_user(
        request: Request,
        payload: UserLoginRequest,
    ) -> JSONResponse:
        try:
            user, session_token = services.auth_service.login(
                username=payload.username,
                password=payload.password,
                ip_address=_client_ip(request),
            )
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "message"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=ErrorPayload(code=exc.code, message=exc.message).model_dump(),
                ) from exc
            raise
        response = _success_response(request, data=user.model_dump(mode="json"))
        _set_session_cookie(response, session_token, app_settings)
        return response

    @app.post(f"{app_settings.api_prefix}/auth/logout")
    def logout_user(request: Request) -> JSONResponse:
        services.auth_service.logout(
            request.cookies.get(SESSION_COOKIE_NAME),
            ip_address=_client_ip(request),
        )
        response = _success_response(request, data={"logged_out": True})
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return response

    @app.post(f"{app_settings.api_prefix}/client-errors")
    def report_client_error(
        request: Request,
        payload: ClientErrorReportRequest,
    ) -> JSONResponse:
        services.app_log_service.record(
            message=payload.message,
            source=payload.source,
            category=payload.category,
            request_path=payload.request_path,
            user=_get_current_user(request, services.auth_service),
            details=payload.details,
        )
        return _success_response(request, data={"recorded": True})

    @app.get("/healthz")
    def healthz(request: Request) -> JSONResponse:
        llm_profiles = list_llm_profiles(app_settings)
        llm_enabled_profiles = [item["profile_id"] for item in llm_profiles if item.get("enabled")]
        return _success_response(
            request,
            data={
                "status": "ok",
                "app_name": app_settings.app_name,
                "app_env": app_settings.app_env,
                "job_execution_mode": app_settings.job_execution_mode,
                "database_backend": "postgresql"
                if "postgres" in app_settings.database_url
                else "sqlite",
                "redis_configured": bool(app_settings.redis_url),
                "minio_configured": bool(app_settings.minio_endpoint),
                "llm_configured": bool(llm_enabled_profiles),
                "llm_enabled_profiles": llm_enabled_profiles,
                "default_accounts_enabled": app_settings.enable_default_accounts,
                "session_cookie_secure": app_settings.session_cookie_secure,
                "clickhouse_configured": bool(app_settings.clickhouse_host),
            },
        )

    @app.post(f"{app_settings.api_prefix}/strategies/generate")
    def generate_strategy(
        request: Request,
        payload: StrategyGenerateRequest,
    ) -> JSONResponse:
        generated = services.strategy_service.generate_strategy(payload)
        return _success_response(request, data=generated)

    @app.post(f"{app_settings.api_prefix}/strategies/generations")
    def create_strategy_generation_task(
        request: Request,
        payload: StrategyGenerateRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        payload_dict = payload.model_dump(mode="json")
        payload_dict["user_id"] = current_user.user_id
        payload_dict["workspace_id"] = current_user.workspace_id
        record = services.strategy_generation_service.submit(
            kind="strategy_generation",
            payload=payload_dict,
            build_result=build_strategy_generation_result(services.strategy_service),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return _success_response(
            request,
            data={
                "generation_id": record.id,
                "task_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "config_revision": record.config_revision,
                "status_url": f"{app_settings.api_prefix}/strategies/generations/{record.id}",
                "result_url": f"{app_settings.api_prefix}/strategies/generations/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.get(f"{app_settings.api_prefix}/strategies/generations/{{generation_id}}")
    def get_strategy_generation_task(
        request: Request,
        generation_id: str,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        record = _require_task(
            services.strategy_generation_service.get(
                generation_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        return _success_response(request, data=_serialize_task(record, "generation_id"))

    @app.get(f"{app_settings.api_prefix}/platform/capabilities")
    def get_platform_capabilities(request: Request) -> JSONResponse:
        return _success_response(
            request,
            data={"items": list_platform_capabilities()},
        )

    @app.get(f"{app_settings.api_prefix}/platform/llm-profiles")
    def get_platform_llm_profiles(request: Request) -> JSONResponse:
        return _success_response(
            request,
            data={
                "items": list_llm_profiles(app_settings),
                "defaults": {
                    "strategy": "module_default",
                    "mentor": "module_default",
                    "assistant": "module_default",
                    "trade_text_parse": "module_default",
                },
            },
        )

    @app.get(f"{app_settings.api_prefix}/indicators/builtin")
    def list_builtin_indicators(request: Request) -> JSONResponse:
        return _success_response(
            request,
            data={"items": services.indicator_service.list_builtin()},
        )

    @app.get(f"{app_settings.api_prefix}/indicators/custom")
    def list_custom_indicators(request: Request) -> JSONResponse:
        return _success_response(
            request,
            data={
                "items": [
                    item.model_dump(mode="json")
                    for item in services.indicator_service.list_custom()
                ]
            }
        )

    @app.post(f"{app_settings.api_prefix}/indicators/custom/generate")
    def generate_custom_indicator(
        request: Request,
        payload: CustomIndicatorGenerateRequest,
    ) -> JSONResponse:
        generated = services.indicator_service.generate_custom_indicator(payload)
        return _success_response(request, data=generated)

    @app.post(f"{app_settings.api_prefix}/indicators/custom")
    def create_custom_indicator(
        request: Request,
        payload: CustomIndicatorCreateRequest,
    ) -> JSONResponse:
        record = services.indicator_service.create_custom(payload)
        return _success_response(request, data=record.model_dump(mode="json"))

    @app.get(f"{app_settings.api_prefix}/rules/defaults")
    def list_default_rules(request: Request) -> JSONResponse:
        return _success_response(
            request,
            data={"items": services.rule_service.list_default_rules()},
        )

    @app.put(f"{app_settings.api_prefix}/rules/defaults")
    def update_default_rules(
        request: Request,
        payload: DefaultRuleUpdateRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        items = services.rule_service.update_default_rules(payload)
        return _success_response(
            request,
            data={
                "items": items,
                "updated_by": current_user.username,
            },
        )

    @app.post(f"{app_settings.api_prefix}/rules/defaults/reset")
    def reset_default_rules(request: Request) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        items = services.rule_service.reset_default_rules()
        return _success_response(
            request,
            data={
                "items": items,
                "updated_by": current_user.username,
            },
        )

    @app.get(f"{app_settings.api_prefix}/rules/glossary")
    def list_glossary_terms(request: Request) -> JSONResponse:
        return _success_response(
            request,
            data={"items": services.rule_service.list_glossary_terms()},
        )

    @app.post(f"{app_settings.api_prefix}/rules/glossary")
    def create_glossary_term(
        request: Request,
        payload: GlossaryTermCreateRequest,
    ) -> JSONResponse:
        record = services.rule_service.create_glossary_term(payload)
        return _success_response(request, data=record.model_dump(mode="json"))

    @app.get(f"{app_settings.api_prefix}/mentor/topics")
    def list_mentor_topics(request: Request) -> JSONResponse:
        _require_current_user(request, services.auth_service)
        return _success_response(
            request,
            data={"items": services.mentor_service.list_topics()},
        )

    @app.post(f"{app_settings.api_prefix}/mentor/ask")
    def ask_mentor(
        request: Request,
        payload: MentorAskRequest,
    ) -> JSONResponse:
        _require_current_user(request, services.auth_service)
        answer = services.mentor_service.answer(payload)
        return _success_response(request, data=answer)

    @app.post(f"{app_settings.api_prefix}/mentor/ask-tasks")
    def create_mentor_task(
        request: Request,
        payload: MentorAskRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        payload_dict = payload.model_dump(mode="json")
        payload_dict["user_id"] = current_user.user_id
        payload_dict["workspace_id"] = current_user.workspace_id
        record = services.mentor_answer_service.submit(
            kind="mentor_answer",
            payload=payload_dict,
            build_result=build_mentor_answer_result(services.mentor_service),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return _success_response(
            request,
            data={
                "mentor_task_id": record.id,
                "task_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "config_revision": record.config_revision,
                "status_url": f"{app_settings.api_prefix}/mentor/ask-tasks/{record.id}",
                "result_url": f"{app_settings.api_prefix}/mentor/ask-tasks/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.get(f"{app_settings.api_prefix}/mentor/ask-tasks/{{mentor_task_id}}")
    def get_mentor_task(
        request: Request,
        mentor_task_id: str,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        record = _require_task(
            services.mentor_answer_service.get(
                mentor_task_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        return _success_response(request, data=_serialize_task(record, "mentor_task_id"))

    @app.get(f"{app_settings.api_prefix}/assistant/workflows")
    def list_assistant_workflows(request: Request) -> JSONResponse:
        _require_current_user(request, services.auth_service)
        return _success_response(
            request,
            data={
                "items": services.assistant_service.list_workflows(),
                "desks": services.assistant_service.list_desks(),
            },
        )

    @app.post(f"{app_settings.api_prefix}/assistant/analyze")
    def analyze_with_assistant(
        request: Request,
        payload: AssistantResearchRequest,
    ) -> JSONResponse:
        _require_current_user(request, services.auth_service)
        answer = services.assistant_service.analyze(payload)
        return _success_response(request, data=answer)

    @app.post(f"{app_settings.api_prefix}/assistant/research-tasks")
    def create_assistant_research_task(
        request: Request,
        payload: AssistantResearchRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        payload_dict = payload.model_dump(mode="json")
        payload_dict["user_id"] = current_user.user_id
        payload_dict["workspace_id"] = current_user.workspace_id
        record = services.assistant_research_service.submit(
            kind="assistant_research",
            payload=payload_dict,
            build_result=build_assistant_research_result(services.assistant_service),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return _success_response(
            request,
            data={
                "research_task_id": record.id,
                "task_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "config_revision": record.config_revision,
                "status_url": f"{app_settings.api_prefix}/assistant/research-tasks/{record.id}",
                "result_url": f"{app_settings.api_prefix}/assistant/research-tasks/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.get(f"{app_settings.api_prefix}/assistant/research-tasks")
    def list_assistant_research_tasks(request: Request) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        records = services.assistant_research_service.list(
            kind="assistant_research",
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            limit=20,
        )
        items = []
        for record in records:
            payload = record.payload or {}
            result = record.result or {}
            items.append(
                {
                    "research_task_id": record.id,
                    "task_id": record.id,
                    "status": record.status.value,
                    "state": record.status.value,
                    "query": result.get("query") or payload.get("query", ""),
                    "workflow_id": result.get("workflow_id") or payload.get("workflow_id", ""),
                    "workflow_title": result.get("workflow_title") or payload.get("workflow_id", ""),
                    "target_symbol": result.get("target_symbol") or payload.get("target_symbol", ""),
                    "market_scope": result.get("market_scope") or payload.get("market_scope", ""),
                    "answer_source": result.get("answer_source", ""),
                    "summary": result.get("executive_summary", ""),
                    "confidence_label": result.get("confidence_label", ""),
                    "status_url": f"{app_settings.api_prefix}/assistant/research-tasks/{record.id}",
                    "created_at": record.created_at.isoformat(),
                    "ended_at": record.finished_at.isoformat() if record.finished_at else None,
                }
            )
        return _success_response(request, data={"items": items})

    @app.get(f"{app_settings.api_prefix}/assistant/research-tasks/{{research_task_id}}")
    def get_assistant_research_task(
        request: Request,
        research_task_id: str,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        record = _require_task(
            services.assistant_research_service.get(
                research_task_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        return _success_response(request, data=_serialize_task(record, "research_task_id"))

    @app.post(f"{app_settings.api_prefix}/strategies/projects")
    def create_strategy_project(
        request: Request,
        payload: ProjectCreateRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        version = services.strategy_service.create_project(
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            title=payload.title,
            version_label=payload.version_label,
            natural_language_prompt=payload.natural_language_prompt,
            strategy_dsl=payload.strategy_dsl,
            strategy_python=payload.strategy_python,
        )
        return _success_response(
            request,
            data={
                "project_id": version.project_id,
                "version_id": version.version_id,
                "version_label": version.version_label,
                "workspace_id": version.workspace_id,
                "user_id": version.user_id,
            }
        )

    @app.get(f"{app_settings.api_prefix}/strategies/projects")
    def list_strategy_projects(request: Request) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        items = services.strategy_service.list_projects(
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        return _success_response(
            request,
            data={
                "items": [
                    {
                        "project_id": item.project_id,
                        "version_id": item.version_id,
                        "version_label": item.version_label,
                        "workspace_id": item.workspace_id,
                        "user_id": item.user_id,
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
    def get_strategy_project(request: Request, version_id: str) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        item = services.strategy_service.get_project(
            version_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="NOT_FOUND",
                    message="strategy project not found",
                ).model_dump(),
            )
        return _success_response(
            request,
            data={
                "project_id": item.project_id,
                "version_id": item.version_id,
                "version_label": item.version_label,
                "workspace_id": item.workspace_id,
                "user_id": item.user_id,
                "title": item.title,
                "natural_language_prompt": item.natural_language_prompt,
                "strategy_dsl": item.strategy_dsl,
                "strategy_python": item.strategy_python,
                "created_at": item.created_at.isoformat(),
            }
        )

    @app.post(f"{app_settings.api_prefix}/backtests/runs")
    def create_backtest_run(
        request: Request,
        payload: BacktestCreateRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        strategy = services.strategy_service.get_project(
            payload.strategy_version_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        if strategy is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="NOT_FOUND",
                    message="strategy project not found",
                ).model_dump(),
            )
        try:
            validate_backtest_capability(strategy.strategy_dsl)
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "message"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ErrorPayload(code=exc.code, message=exc.message).model_dump(),
                ) from exc
            raise
        payload_dict = payload.model_dump(by_alias=True, mode="json")
        payload_dict["execution_contract"] = _normalize_execution_contract(
            payload_dict["execution_contract"],
            strategy.strategy_dsl,
        )
        payload_dict["data_snapshot"] = _enrich_data_snapshot_payload(
            payload_dict["data_snapshot"],
            payload_dict["dataset"],
            payload_dict["execution_contract"],
        )
        _ensure_dataset_snapshot(
            dataset_snapshot_repository,
            BacktestCreateRequest.model_validate(payload_dict),
        )
        payload_dict["user_id"] = current_user.user_id
        payload_dict["workspace_id"] = current_user.workspace_id
        record = services.backtest_service.submit(
            kind="backtest",
            payload=payload_dict,
            build_result=build_backtest_result(
                app_settings,
                services.strategy_service,
                services.market_data_service,
            ),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return _success_response(
            request,
            data={
                "backtest_run_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "config_revision": record.config_revision,
                "status_url": f"{app_settings.api_prefix}/backtests/runs/{record.id}",
                "result_url": f"{app_settings.api_prefix}/backtests/runs/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.get(f"{app_settings.api_prefix}/backtests/runs")
    def list_backtest_runs(request: Request) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        records = task_repository.list(
            "backtest",
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        return _success_response(
            request,
            data={
                "items": [
                    {
                        "backtest_run_id": record.id,
                        "status": record.status.value,
                        "state": record.status.value,
                        "created_at": record.created_at.isoformat(),
                        "workspace_id": record.workspace_id,
                        "user_id": record.user_id,
                        "config_revision": record.config_revision,
                        "strategy_version_id": record.payload.get("strategy_version_id"),
                        "strategy_title": record.result.get("strategy_title", ""),
                        "market": record.payload.get("dataset", {}).get("market"),
                        "timeframe": record.payload.get("dataset", {}).get("timeframe"),
                        "capability_summary": summarize_strategy_capability(
                            market_scope=record.result.get("strategy_spec", {}).get(
                                "market_scope",
                                "cn_equity",
                            )
                            if record.result.get("strategy_spec")
                            else "cn_equity",
                            primary_timeframe=record.result.get("strategy_spec", {}).get(
                                "timeframe",
                                "1d",
                            )
                            if record.result.get("strategy_spec")
                            else "1d",
                            timeframes=record.result.get("strategy_spec", {}).get("timeframes")
                            if record.result.get("strategy_spec")
                            else ["1d"],
                            analysis_mode=record.result.get("strategy_spec", {}).get(
                                "analysis_mode",
                                "single_timeframe",
                            )
                            if record.result.get("strategy_spec")
                            else "single_timeframe",
                        ),
                        "metrics": record.result.get("metrics", {}),
                        "backtest_config": record.result.get("backtest_config", {}),
                        "data_snapshot_summary": record.result.get(
                            "data_snapshot_summary",
                            {},
                        ),
                        "data_source": record.result.get("data_source", {}),
                    }
                    for record in records
                ]
            }
        )

    @app.get(f"{app_settings.api_prefix}/backtests/compare")
    def compare_backtest_runs(request: Request) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        run_ids = [item for item in request.query_params.getlist("run_ids") if item]
        if len(run_ids) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorPayload(
                    code="INVALID_ARGUMENT",
                    message="at least two backtest runs are required for comparison",
                ).model_dump(),
            )
        if len(run_ids) > 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorPayload(
                    code="INVALID_ARGUMENT",
                    message="at most four backtest runs can be compared at once",
                ).model_dump(),
            )
        records = [
            _require_task(
                services.backtest_service.get(
                    run_id,
                    user_id=current_user.user_id,
                    workspace_id=current_user.workspace_id,
                )
            )
            for run_id in run_ids
        ]
        items = [_build_backtest_compare_item(record) for record in records]
        return _success_response(
            request,
            data={
                "baseline_run_id": records[0].id,
                "items": items,
                "metric_rows": _build_backtest_compare_rows(
                    items,
                    "metrics",
                    (
                        ("total_return_pct", "总收益率"),
                        ("max_drawdown_pct", "最大回撤"),
                        ("win_rate_pct", "胜率"),
                        ("profit_factor", "盈亏比"),
                        ("trade_count", "交易次数"),
                        ("final_equity", "期末权益"),
                    ),
                    only_changed=False,
                ),
                "config_diffs": _build_backtest_compare_rows(
                    items,
                    "backtest_config",
                    (
                        ("fill_price_rule", "成交方式"),
                        ("intrabar_match_policy", "盘中撮合"),
                        ("settlement_policy", "结算规则"),
                        ("adjustment_mode", "复权模式"),
                        ("calendar", "交易日历"),
                        ("timezone", "时区"),
                        ("fee_bps", "手续费(bps)"),
                        ("slippage_bps", "滑点(bps)"),
                        ("warmup_bars", "预热 Bar 数"),
                        ("market_constraint_text", "市场成交约束"),
                        ("position_sizing.mode", "仓位模式"),
                        ("position_sizing.value", "仓位值"),
                        ("position_sizing.max_position_pct", "单笔最大资金占比"),
                        ("position_sizing.min_trade_unit", "最小交易单位"),
                        ("risk_controls.take_profit_pct", "止盈比例"),
                        ("risk_controls.stop_loss_pct", "止损比例"),
                        ("risk_controls.max_drawdown_pct", "最大回撤保护"),
                        ("risk_controls.max_holding_bars", "最大持有 Bar 数"),
                    ),
                ),
                "snapshot_diffs": _build_backtest_compare_rows(
                    items,
                    "data_snapshot_summary",
                    (
                        ("dataset_snapshot_ref", "快照引用"),
                        ("provider", "数据来源"),
                        ("coverage_pct", "覆盖率"),
                        ("missing_rate_pct", "缺失率"),
                        ("calendar", "交易日历"),
                        ("timezone", "时区"),
                        ("bar_count", "Bar 数"),
                        ("warmup_bars", "预热 Bar 数"),
                        ("last_synced_at", "最近同步"),
                    ),
                ),
                "highlights": _build_backtest_compare_highlights(items),
            },
        )

    @app.get(f"{app_settings.api_prefix}/backtests/runs/{{backtest_run_id}}")
    def get_backtest_run(request: Request, backtest_run_id: str) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        record = _require_task(
            services.backtest_service.get(
                backtest_run_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        return _success_response(
            request,
            data=_serialize_task(record, "backtest_run_id"),
        )

    @app.post(f"{app_settings.api_prefix}/backtests/runs/{{backtest_run_id}}/cancel")
    def cancel_backtest_run(request: Request, backtest_run_id: str) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        _require_task(
            services.backtest_service.get(
                backtest_run_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        record = _require_task(services.backtest_service.cancel(backtest_run_id))
        return _success_response(
            request,
            data={
                "backtest_run_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
            }
        )

    @app.delete(f"{app_settings.api_prefix}/backtests/runs/{{backtest_run_id}}")
    def delete_backtest_run(request: Request, backtest_run_id: str) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        record = _require_task(
            services.backtest_service.get(
                backtest_run_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        if record.status in {
            TaskStatus.PENDING,
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.CANCELING,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorPayload(
                    code="STATE_CONFLICT",
                    message="running backtest cannot be deleted",
                ).model_dump(),
            )
        deleted = task_repository.delete(
            backtest_run_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="NOT_FOUND",
                    message="task not found",
                ).model_dump(),
            )
        return _success_response(
            request,
            data={
                "backtest_run_id": backtest_run_id,
                "deleted": True,
            },
        )

    @app.post(f"{app_settings.api_prefix}/optimization-jobs")
    def create_optimization_job(
        request: Request,
        payload: OptimizationCreateRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        strategy = services.strategy_service.get_project(
            payload.strategy_version_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        if strategy is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="NOT_FOUND",
                    message="strategy project not found",
                ).model_dump(),
            )
        payload_dict = payload.model_dump(by_alias=True, mode="json")
        payload_dict["execution_contract"] = _normalize_execution_contract(
            payload_dict["execution_contract"],
            strategy.strategy_dsl,
        )
        payload_dict["data_snapshot"] = _enrich_data_snapshot_payload(
            payload_dict["data_snapshot"],
            payload_dict["dataset"],
            payload_dict["execution_contract"],
        )
        _ensure_dataset_snapshot(
            dataset_snapshot_repository,
            OptimizationCreateRequest.model_validate(payload_dict),
        )
        payload_dict["user_id"] = current_user.user_id
        payload_dict["workspace_id"] = current_user.workspace_id
        record = services.optimization_service.submit(
            kind="optimization",
            payload=payload_dict,
            build_result=build_optimization_result(),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return _success_response(
            request,
            data={
                "job_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "config_revision": record.config_revision,
                "status_url": f"{app_settings.api_prefix}/optimization-jobs/{record.id}",
                "result_url": f"{app_settings.api_prefix}/optimization-jobs/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.get(f"{app_settings.api_prefix}/optimization-jobs/{{job_id}}")
    def get_optimization_job(request: Request, job_id: str) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        record = _require_task(
            services.optimization_service.get(
                job_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        return _success_response(request, data=_serialize_task(record, "job_id"))

    @app.post(f"{app_settings.api_prefix}/optimization-jobs/{{job_id}}/cancel")
    def cancel_optimization_job(request: Request, job_id: str) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        _require_task(
            services.optimization_service.get(
                job_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        record = _require_task(services.optimization_service.cancel(job_id))
        return _success_response(
            request,
            data={
                "job_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
            },
        )

    @app.post(f"{app_settings.api_prefix}/replays/analyses")
    def create_replay_analysis(
        request: Request,
        payload: ReplayCreateRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        upload = services.trade_upload_service.get_upload(
            payload.upload_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        if upload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="NOT_FOUND",
                    message="trade upload not found",
                ).model_dump(),
            )
        _ensure_replay_dataset_snapshot(
            dataset_snapshot_repository,
            services.trade_upload_service,
            payload,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        payload_dict = payload.model_dump(mode="json")
        payload_dict["user_id"] = current_user.user_id
        payload_dict["workspace_id"] = current_user.workspace_id
        record = services.replay_service.submit(
            kind="replay",
            payload=payload_dict,
            build_result=build_replay_result(
                app_settings,
                services.trade_upload_service,
                services.market_data_service,
            ),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return _success_response(
            request,
            data={
                "analysis_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "config_revision": record.config_revision,
                "status_url": f"{app_settings.api_prefix}/replays/analyses/{record.id}",
                "result_url": f"{app_settings.api_prefix}/replays/analyses/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.get(f"{app_settings.api_prefix}/replays/analyses/{{analysis_id}}")
    def get_replay_analysis(request: Request, analysis_id: str) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        record = _require_task(
            services.replay_service.get(
                analysis_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        return _success_response(
            request,
            data=_serialize_task(record, "analysis_id"),
        )

    @app.post(f"{app_settings.api_prefix}/replays/analyses/{{analysis_id}}/cancel")
    def cancel_replay_analysis(request: Request, analysis_id: str) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        _require_task(
            services.replay_service.get(
                analysis_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        record = _require_task(services.replay_service.cancel(analysis_id))
        return _success_response(
            request,
            data={
                "analysis_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
            }
        )

    @app.post(f"{app_settings.api_prefix}/trades/uploads")
    async def upload_trades(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        raw = (await file.read()).decode("utf-8")
        upload = services.trade_upload_service.create_upload(
            file.filename,
            raw,
            upload_kind="csv",
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        return _success_response(
            request,
            data={
                "upload_id": upload.upload_id,
                "status": upload.status,
                "detected_columns": upload.detected_columns,
                "upload_kind": upload.upload_kind,
            }
        )

    @app.post(f"{app_settings.api_prefix}/trades/uploads/manual")
    def upload_manual_trades(
        request: Request,
        payload: TradeUploadManualCreateRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        upload = services.trade_upload_service.create_manual_upload(
            source_file_name=payload.source_file_name or f"{payload.source_type}_entry.json",
            upload_kind=payload.source_type,
            records=[item.model_dump(mode="json") for item in payload.records],
            metadata={
                "source_notes": payload.source_notes,
                "market": payload.market,
            },
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        return _success_response(
            request,
            data={
                "upload_id": upload.upload_id,
                "status": upload.status,
                "detected_columns": upload.detected_columns,
                "upload_kind": upload.upload_kind,
                "record_count": len(upload.records),
            },
        )

    @app.post(f"{app_settings.api_prefix}/trades/uploads/manual/parse-text")
    def parse_manual_trade_text(
        request: Request,
        payload: ManualTradeTextParseRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        parsed = services.trade_upload_service.parse_manual_trade_text(
            text=payload.text,
            market=payload.market,
            adjustment_mode=payload.adjustment_mode,
            llm_profile=payload.llm_profile,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        return _success_response(request, data=parsed)

    @app.post(f"{app_settings.api_prefix}/trades/uploads/manual/parse-text-tasks")
    def create_manual_trade_text_task(
        request: Request,
        payload: ManualTradeTextParseRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        payload_dict = payload.model_dump(mode="json")
        payload_dict["user_id"] = current_user.user_id
        payload_dict["workspace_id"] = current_user.workspace_id
        record = services.trade_text_parse_service.submit(
            kind="trade_text_parse",
            payload=payload_dict,
            build_result=build_trade_text_parse_result(services.trade_upload_service),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return _success_response(
            request,
            data={
                "parse_task_id": record.id,
                "task_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "config_revision": record.config_revision,
                "status_url": f"{app_settings.api_prefix}/trades/uploads/manual/parse-text-tasks/{record.id}",
                "result_url": f"{app_settings.api_prefix}/trades/uploads/manual/parse-text-tasks/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.get(f"{app_settings.api_prefix}/trades/uploads/manual/parse-text-tasks")
    def list_manual_trade_text_tasks(
        request: Request,
        task_kind: str | None = None,
        task_status: str | None = None,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        requested_task_kind = task_kind
        text_records = services.trade_text_parse_service.list(
            kind="trade_text_parse",
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            limit=20,
        )
        ocr_records = services.trade_text_parse_service.list(
            kind="trade_screenshot_ocr",
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            limit=20,
        )
        records = sorted(
            [*text_records, *ocr_records],
            key=lambda item: item.created_at,
            reverse=True,
        )[:20]
        items = []
        for record in records:
            payload = record.payload or {}
            result = record.result or {}
            validation_summary = result.get("validation_summary") or {}
            chunk_summary = result.get("chunk_summary") or {}
            record_task_kind = record.kind
            items.append(
                {
                    "parse_task_id": record.id,
                    "task_id": record.id,
                    "task_kind": record_task_kind,
                    "status": record.status.value,
                    "state": record.status.value,
                    "progress_pct": record.progress_pct,
                    "market": result.get("market") or payload.get("market", ""),
                    "record_count": result.get("record_count", 0),
                    "group_count": result.get("group_count", 0),
                    "chunk_count": chunk_summary.get("chunk_count")
                    or validation_summary.get("chunk_count")
                    or 1,
                    "progress_label": result.get("progress_label", ""),
                    "progress_detail": result.get("progress_detail", {}),
                    "summary": result.get("summary", ""),
                    "validation_readiness": validation_summary.get("validation_readiness", ""),
                    "sample_mode": validation_summary.get("sample_mode", ""),
                    "status_url": (
                        f"{app_settings.api_prefix}/trades/uploads/screenshot/ocr-tasks/{record.id}"
                        if record_task_kind == "trade_screenshot_ocr"
                        else f"{app_settings.api_prefix}/trades/uploads/manual/parse-text-tasks/{record.id}"
                    ),
                    "created_at": record.created_at.isoformat(),
                    "ended_at": record.finished_at.isoformat() if record.finished_at else None,
                }
            )
        if requested_task_kind:
            items = [item for item in items if item["task_kind"] == requested_task_kind]
        if task_status:
            items = [item for item in items if item["status"] == task_status]
        return _success_response(request, data={"items": items})

    @app.get(f"{app_settings.api_prefix}/trades/uploads/manual/parse-text-tasks/{{parse_task_id}}")
    def get_manual_trade_text_task(
        request: Request,
        parse_task_id: str,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        record = _require_task(
            services.trade_text_parse_service.get(
                parse_task_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        return _success_response(request, data=_serialize_task(record, "parse_task_id"))

    @app.post(f"{app_settings.api_prefix}/trades/uploads/manual/parse-text-tasks/{{parse_task_id}}/retry")
    def retry_manual_trade_text_task(
        request: Request,
        parse_task_id: str,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        original = _require_task(
            services.trade_text_parse_service.get(
                parse_task_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        record = services.trade_text_parse_service.submit(
            kind="trade_text_parse",
            payload=dict(original.payload),
            build_result=build_trade_text_parse_result(services.trade_upload_service),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        return _success_response(
            request,
            data={
                "parse_task_id": record.id,
                "task_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "status_url": f"{app_settings.api_prefix}/trades/uploads/manual/parse-text-tasks/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.delete(f"{app_settings.api_prefix}/trades/uploads/manual/parse-text-tasks/{{parse_task_id}}")
    def delete_manual_trade_text_task(
        request: Request,
        parse_task_id: str,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        deleted = services.trade_text_parse_service.delete(
            parse_task_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(code="NOT_FOUND", message="未找到对应的长文字解析任务。").model_dump(),
            )
        return _success_response(request, data={"task_id": parse_task_id, "deleted": True})

    @app.post(f"{app_settings.api_prefix}/trades/uploads/screenshot")
    async def upload_trade_screenshot(
        request: Request,
        file: UploadFile = File(...),
        symbol: str = Form(...),
        side: str = Form("long"),
        entry_time: str = Form(...),
        exit_time: str | None = Form(None),
        pnl: float = Form(0.0),
        market: str | None = Form(None),
        source_notes: str | None = Form(None),
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        content = await file.read()
        upload = services.trade_upload_service.create_manual_upload(
            source_file_name=file.filename or "trade-screenshot.png",
            upload_kind="screenshot",
            records=[
                {
                    "symbol": symbol,
                    "side": side,
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "pnl": pnl,
                }
            ],
            metadata={
                "market": market,
                "source_notes": source_notes,
                "attachment_name": file.filename,
                "attachment_content_type": file.content_type,
                "attachment_size_bytes": len(content),
            },
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        return _success_response(
            request,
            data={
                "upload_id": upload.upload_id,
                "status": upload.status,
                "detected_columns": upload.detected_columns,
                "upload_kind": upload.upload_kind,
                "record_count": len(upload.records),
            },
        )

    @app.post(f"{app_settings.api_prefix}/trades/uploads/screenshot/ocr")
    async def recognize_trade_screenshot(
        request: Request,
        file: UploadFile = File(...),
        market: str = Form("cn_equity"),
    ) -> JSONResponse:
        _require_current_user(request, services.auth_service)
        content = await file.read()
        suggestion = services.trade_upload_service.recognize_trade_screenshot(
            content=content,
            market=market,
        )
        return _success_response(request, data=suggestion)

    @app.post(f"{app_settings.api_prefix}/trades/uploads/screenshot/ocr-tasks")
    async def create_trade_screenshot_ocr_task(
        request: Request,
        files: list[UploadFile] = File(...),
        market: str = Form("cn_equity"),
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        uploaded_files = [item for item in files if item.filename]
        if not uploaded_files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorPayload(code="INVALID_ARGUMENT", message="至少需要上传一张成交截图。").model_dump(),
            )
        encoded_files: list[str] = []
        file_names: list[str] = []
        content_types: list[str] = []
        for file in uploaded_files:
            content = await file.read()
            encoded_files.append(base64.b64encode(content).decode("utf-8"))
            file_names.append(file.filename or "trade-screenshot.png")
            content_types.append(file.content_type or "image/png")
        payload_dict = {
            "market": market,
            "file_names": file_names,
            "content_types": content_types,
            "files_b64": encoded_files,
            "user_id": current_user.user_id,
            "workspace_id": current_user.workspace_id,
        }
        record = services.trade_text_parse_service.submit(
            kind="trade_screenshot_ocr",
            payload=payload_dict,
            build_result=build_trade_screenshot_ocr_result(services.trade_upload_service),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return _success_response(
            request,
            data={
                "ocr_task_id": record.id,
                "task_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "config_revision": record.config_revision,
                "status_url": f"{app_settings.api_prefix}/trades/uploads/screenshot/ocr-tasks/{record.id}",
                "result_url": f"{app_settings.api_prefix}/trades/uploads/screenshot/ocr-tasks/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.get(f"{app_settings.api_prefix}/trades/uploads/screenshot/ocr-tasks/{{ocr_task_id}}")
    def get_trade_screenshot_ocr_task(
        request: Request,
        ocr_task_id: str,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        record = _require_task(
            services.trade_text_parse_service.get(
                ocr_task_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        return _success_response(request, data=_serialize_task(record, "ocr_task_id"))

    @app.post(f"{app_settings.api_prefix}/trades/uploads/screenshot/ocr-tasks/{{ocr_task_id}}/retry")
    def retry_trade_screenshot_ocr_task(
        request: Request,
        ocr_task_id: str,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        original = _require_task(
            services.trade_text_parse_service.get(
                ocr_task_id,
                user_id=current_user.user_id,
                workspace_id=current_user.workspace_id,
            )
        )
        record = services.trade_text_parse_service.submit(
            kind="trade_screenshot_ocr",
            payload=dict(original.payload),
            build_result=build_trade_screenshot_ocr_result(services.trade_upload_service),
            request_id=request.state.request_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        return _success_response(
            request,
            data={
                "ocr_task_id": record.id,
                "task_id": record.id,
                "status": record.status.value,
                "state": record.status.value,
                "progress_pct": record.progress_pct,
                "status_url": f"{app_settings.api_prefix}/trades/uploads/screenshot/ocr-tasks/{record.id}",
            },
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.delete(f"{app_settings.api_prefix}/trades/uploads/screenshot/ocr-tasks/{{ocr_task_id}}")
    def delete_trade_screenshot_ocr_task(
        request: Request,
        ocr_task_id: str,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        deleted = services.trade_text_parse_service.delete(
            ocr_task_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(code="NOT_FOUND", message="未找到对应的截图 OCR 任务。").model_dump(),
            )
        return _success_response(request, data={"task_id": ocr_task_id, "deleted": True})

    @app.post(f"{app_settings.api_prefix}/trades/uploads/{{upload_id}}/parse")
    def parse_trade_upload(
        request: Request,
        upload_id: str,
        payload: TradeUploadParseRequest,
    ) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        mapping = payload.column_mapping
        upload = services.trade_upload_service.parse_upload(
            upload_id,
            mapping,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        if upload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="NOT_FOUND",
                    message="trade upload not found",
                ).model_dump(),
            )
        return _success_response(
            request,
            data={
                "upload_id": upload.upload_id,
                "raw_row_count": len(upload.raw_text.splitlines()) - 1,
                "fill_count": len(upload.records),
                "record_count": len(upload.records),
                "status": upload.status,
            }
        )

    @app.get(f"{app_settings.api_prefix}/trades/uploads/{{upload_id}}/records")
    def get_trade_records(request: Request, upload_id: str) -> JSONResponse:
        current_user = _require_current_user(request, services.auth_service)
        upload = services.trade_upload_service.get_upload(
            upload_id,
            user_id=current_user.user_id,
            workspace_id=current_user.workspace_id,
        )
        if upload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorPayload(
                    code="NOT_FOUND",
                    message="trade upload not found",
                ).model_dump(),
            )
        return _success_response(
            request,
            data={"items": [item.model_dump(mode="json") for item in upload.records]}
        )

    return app


def _require_task(record: Any) -> Any:
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorPayload(code="NOT_FOUND", message="task not found").model_dump(),
        )
    return record


def _serialize_task(record: Any, identifier_key: str) -> dict[str, Any]:
    payload = {
        identifier_key: record.id,
        "task_id": record.id,
        "task_type": record.kind,
        "user_id": record.user_id,
        "status": record.status.value,
        "state": record.status.value,
        "progress_pct": record.progress_pct,
        "workspace_id": record.workspace_id,
        "environment": record.environment,
        "resource_refs": record.resource_refs,
        "config_revision": record.config_revision,
        "request_id": record.request_id,
        "trace_id": record.trace_id,
        "created_at": record.created_at.isoformat(),
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "ended_at": record.finished_at.isoformat() if record.finished_at else None,
    }
    payload.update(record.result)
    dataset_snapshot_ref = record.payload.get("data_snapshot", {}).get("dataset_snapshot_ref")
    if dataset_snapshot_ref and "dataset_snapshot_ref" not in payload:
        payload["dataset_snapshot_ref"] = dataset_snapshot_ref
    if record.error is not None:
        payload["error"] = record.error.model_dump()
    if record.status == TaskStatus.CANCELED:
        payload["error"] = {
            "code": "STATE_CONFLICT",
            "message": "task was cancelled",
            "details": {},
        }
    return payload


def _build_backtest_compare_item(record: Any) -> dict[str, Any]:
    strategy_title = record.result.get("strategy_title") or record.payload.get(
        "strategy_version_id",
        "未命名策略",
    )
    return {
        "backtest_run_id": record.id,
        "display_title": strategy_title,
        "created_at": record.created_at.isoformat(),
        "market": record.payload.get("dataset", {}).get("market"),
        "timeframe": record.payload.get("dataset", {}).get("timeframe"),
        "metrics": record.result.get("metrics", {}),
        "backtest_config": record.result.get("backtest_config", {}),
        "data_snapshot_summary": record.result.get("data_snapshot_summary", {}),
    }


def _build_backtest_compare_rows(
    items: list[dict[str, Any]],
    source_key: str,
    field_specs: tuple[tuple[str, str], ...],
    *,
    only_changed: bool = True,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_path, label in field_specs:
        values = [
            _build_compare_value_cell(
                item,
                source_key=source_key,
                field_path=field_path,
                baseline=item is items[0],
                baseline_value=_get_nested_value(items[0].get(source_key, {}), field_path),
            )
            for item in items
        ]
        normalized_values = [
            jsonable_encoder(cell["value"]) if cell["value"] is not None else None
            for cell in values
        ]
        if all(value is None for value in normalized_values):
            continue
        changed = len({repr(value) for value in normalized_values}) > 1
        if only_changed and not changed:
            continue
        rows.append(
            {
                "field": field_path,
                "label": label,
                "changed": changed,
                "values": values,
            }
        )
    return rows


def _build_compare_value_cell(
    item: dict[str, Any],
    *,
    source_key: str,
    field_path: str,
    baseline: bool,
    baseline_value: Any,
) -> dict[str, Any]:
    value = _get_nested_value(item.get(source_key, {}), field_path)
    cell = {
        "backtest_run_id": item["backtest_run_id"],
        "display_title": item["display_title"],
        "value": value,
        "delta_vs_baseline": None,
    }
    if (
        not baseline
        and isinstance(value, (int, float))
        and isinstance(baseline_value, (int, float))
    ):
        cell["delta_vs_baseline"] = round(value - baseline_value, 2)
    return cell


def _build_backtest_compare_highlights(items: list[dict[str, Any]]) -> list[str]:
    highlights: list[str] = []
    by_return = [
        item for item in items if isinstance(item.get("metrics", {}).get("total_return_pct"), (int, float))
    ]
    if by_return:
        best_return = max(
            by_return,
            key=lambda item: item["metrics"]["total_return_pct"],
        )
        highlights.append(
            f"收益最高的是 {best_return['display_title']}，总收益 {best_return['metrics']['total_return_pct']}%。"
        )
    by_drawdown = [
        item for item in items if isinstance(item.get("metrics", {}).get("max_drawdown_pct"), (int, float))
    ]
    if by_drawdown:
        best_drawdown = max(
            by_drawdown,
            key=lambda item: item["metrics"]["max_drawdown_pct"],
        )
        highlights.append(
            f"回撤控制最好的是 {best_drawdown['display_title']}，最大回撤 {best_drawdown['metrics']['max_drawdown_pct']}%。"
        )
    snapshot_refs = {
        item.get("data_snapshot_summary", {}).get("dataset_snapshot_ref")
        for item in items
        if item.get("data_snapshot_summary", {}).get("dataset_snapshot_ref")
    }
    if snapshot_refs:
        highlights.append(f"本次对比涉及 {len(snapshot_refs)} 个数据快照。")
    return highlights


def _get_nested_value(payload: dict[str, Any], field_path: str) -> Any:
    current: Any = payload
    for part in field_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _ensure_dataset_snapshot(repository: Any, payload: Any) -> None:
    record = _build_dataset_snapshot_record(payload)
    existing = repository.get(record.dataset_snapshot_ref)
    if existing is None:
        repository.create(record)
        return
    comparable_fields = (
        "market",
        "asset_type",
        "frequency",
        "adjustment_mode",
        "date_from",
        "date_to",
    )
    for field_name in comparable_fields:
        if getattr(existing, field_name) != getattr(record, field_name):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorPayload(
                    code="REVISION_CONFLICT",
                    message="dataset snapshot ref conflicts with existing snapshot metadata",
                    details={"dataset_snapshot_ref": record.dataset_snapshot_ref},
                ).model_dump(),
            )


def _ensure_replay_dataset_snapshot(
    repository: Any,
    trade_upload_service: Any,
    payload: ReplayCreateRequest,
    *,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> None:
    if payload.data_snapshot is None:
        payload.data_snapshot = DataSnapshotConfig(
            dataset_snapshot_ref=f"replay_{payload.upload_id}_snapshot"
        )

    upload = trade_upload_service.get_upload(
        payload.upload_id,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    date_from = utcnow()
    date_to = date_from
    if upload is not None and upload.records:
        candidate_times = [
            item.entry_time for item in upload.records
        ] + [item.exit_time for item in upload.records if item.exit_time is not None]
        date_from = min(candidate_times)
        date_to = max(candidate_times)

    record = DatasetSnapshotRecord(
        dataset_snapshot_ref=payload.data_snapshot.dataset_snapshot_ref,
        market="cn_a_share",
        asset_type="stock",
        frequency="1d",
        adjustment_mode="qfq",
        date_from=date_from,
        date_to=date_to,
    )
    existing = repository.get(record.dataset_snapshot_ref)
    if existing is None:
        repository.create(record)
        return


def _build_dataset_snapshot_record(payload: Any) -> DatasetSnapshotRecord:
    dataset = payload.dataset
    execution_contract = payload.execution_contract
    return DatasetSnapshotRecord(
        dataset_snapshot_ref=payload.data_snapshot.dataset_snapshot_ref,
        market=dataset.market,
        asset_type=dataset.asset_type,
        frequency=dataset.timeframe,
        adjustment_mode=execution_contract.adjustment_mode,
        date_from=dataset.from_,
        date_to=dataset.to,
    )


def _enrich_data_snapshot_payload(
    data_snapshot: dict[str, Any],
    dataset: dict[str, Any],
    execution_contract: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(data_snapshot)
    enriched.setdefault("provider", "shared_market_store")
    enriched.setdefault("coverage_status", "ready")
    enriched.setdefault("calendar", execution_contract.get("calendar"))
    enriched.setdefault("timezone", execution_contract.get("timezone"))
    enriched.setdefault("warmup_bars", execution_contract.get("warmup_bars"))
    return enriched


def _resolve_request_id(request: Request) -> str:
    incoming = request.headers.get("X-Request-Id", "").strip()
    return incoming or f"req_{uuid4().hex[:12]}"


def _get_current_user(request: Request, auth_service: AuthService):
    return auth_service.get_user_by_session_token(request.cookies.get(SESSION_COOKIE_NAME))


def _require_current_user(request: Request, auth_service: AuthService):
    user = _get_current_user(request, auth_service)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorPayload(code="UNAUTHORIZED", message="login required").model_dump(),
        )
    return user


def _require_admin_user(request: Request, auth_service: AuthService):
    user = _require_current_user(request, auth_service)
    if not auth_service.is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorPayload(code="FORBIDDEN", message="admin access required").model_dump(),
        )
    return user


def _set_session_cookie(
    response: JSONResponse,
    session_token: str,
    settings: Settings,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        max_age=14 * 24 * 60 * 60,
        samesite=settings.session_cookie_samesite,
        secure=settings.session_cookie_secure,
        domain=settings.session_cookie_domain or None,
        path="/",
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _login_redirect(target_path: str) -> RedirectResponse:
    next_target = quote(target_path, safe="/")
    return RedirectResponse(
        url=f"/login?next={next_target}",
        status_code=status.HTTP_302_FOUND,
    )


def _default_error_code(status_code: int) -> str:
    return {
        400: "INVALID_ARGUMENT",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "STATE_CONFLICT",
        429: "RATE_LIMITED",
    }.get(status_code, "INTERNAL_ERROR")


def _default_error_message(code: str) -> str:
    return {
        "INVALID_ARGUMENT": "invalid request",
        "UNAUTHORIZED": "unauthorized",
        "FORBIDDEN": "forbidden",
        "NOT_FOUND": "resource not found",
        "STATE_CONFLICT": "state conflict",
        "RATE_LIMITED": "rate limited",
        "INTERNAL_ERROR": "internal error",
    }.get(code, "request failed")


def _success_response(
    request: Request,
    *,
    data: Any,
    status_code: int = status.HTTP_200_OK,
    meta: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            SuccessEnvelope(
                request_id=request.state.request_id,
                data=data,
                meta=meta,
            )
        ),
        headers={"X-Request-Id": request.state.request_id},
    )


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            ErrorEnvelope(
                request_id=getattr(request.state, "request_id", _resolve_request_id(request)),
                error=ErrorPayload(
                    code=code,
                    message=message,
                    details=details or {},
                ),
            )
        ),
        headers={"X-Request-Id": getattr(request.state, "request_id", _resolve_request_id(request))},
    )
