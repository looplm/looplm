"""LoopLM API — FastAPI application."""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.routers import (
    admin, analysis, analytics, advisor, auth_router, costs_overview, dashboard, datasets, evaluations,
    evaluators, experiments, feedback, fixes, github_oauth, graph, health, imports,
    index_explorer, ingest, ingest_keys, integrations, issues, langsmith, llm_costs, code_agent,
    permissions, project_members, projects, prompts, rag_coverage, route_analysis, source_registry, trace_detail,
    traces, user_settings, version,
)

logger = logging.getLogger("looplm")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Guard: refuse to start with default secret key in production
    if not settings.debug and settings.api_secret_key == "change-me-in-production":
        raise RuntimeError(
            "FATAL: api_secret_key is set to the default value. "
            "Set a strong API_SECRET_KEY environment variable before running in production."
        )

    # Startup: create tables if needed
    from app.db import engine
    from app.models.models import Base
    from app.models.user import User  # noqa: F401 — ensure user table is created
    from app.models.project import Project  # noqa: F401 — ensure project table is created
    from app.models.admin_audit import AdminAudit  # noqa: F401 — ensure audit table is created
    from app.models.github import (  # noqa: F401 — ensure tables are created
        GithubInstallation,
        ProjectGithubApp,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Reconcile syncs orphaned by a previous restart/crash: their in-process
    # background task is gone, but the row is still 'syncing' and would spin
    # the UI's progress bar forever. Mark them as errored so they can be retried.
    from sqlalchemy import update as _sa_update
    from app.db import async_session
    from app.models.models import Integration, SyncStatus
    async with async_session() as session:
        result = await session.execute(
            _sa_update(Integration)
            .where(Integration.sync_status == SyncStatus.syncing)
            .values(
                sync_status=SyncStatus.error,
                last_sync_error="Sync interrupted by server restart",
                sync_progress_current=None,
                sync_progress_total=None,
                sync_started_at=None,
                sync_phase=None,
                sync_message=None,
                sync_since=None,
            )
        )
        await session.commit()
        if result.rowcount:
            logger.warning("Reconciled %d sync(s) orphaned by restart", result.rowcount)

    # Reconcile top-questions analyses orphaned by a restart/crash: their
    # in-process asyncio task is gone, but the row is still 'pending'/'running'
    # and would spin the UI's progress bar forever. Mark them failed so the user
    # can retry. (A live stop now flips status='cancelled' via the DB, which the
    # worker honors cooperatively — so we only ever orphan rows on hard restarts.)
    from datetime import datetime as _dt, timezone as _tz
    from app.models.feedback_eval import FeedbackThemeAnalysis, TopQuestionsAnalysis
    async with async_session() as session:
        for _model, _label in (
            (TopQuestionsAnalysis, "top-questions"),
            (FeedbackThemeAnalysis, "feedback-theme"),
        ):
            result = await session.execute(
                _sa_update(_model)
                .where(_model.status.in_(("pending", "running")))
                .values(
                    status="failed",
                    error="Analysis interrupted by server restart",
                    completed_at=_dt.now(_tz.utc),
                )
            )
            if result.rowcount:
                logger.warning(
                    "Reconciled %d %s analysis(es) orphaned by restart",
                    result.rowcount,
                    _label,
                )
        await session.commit()

    # Start batch eval poller
    from app.services.batch_poller import start_batch_poller, stop_batch_poller
    await start_batch_poller()

    # Start auto-sync poller (scheduled trace syncs)
    from app.services.sync_poller import start_sync_poller, stop_sync_poller
    await start_sync_poller()

    # Start behavioral signal classifier poller (gated by signal_classify_enabled)
    from app.services.signal_classifier_poller import (
        start_signal_classifier_poller,
        stop_signal_classifier_poller,
    )
    await start_signal_classifier_poller()

    # Start autonomous issue detection poller (gated by issue_detection_enabled)
    from app.services.issue_poller import start_issue_poller, stop_issue_poller
    await start_issue_poller()

    yield
    # Shutdown
    await stop_issue_poller()
    await stop_signal_classifier_poller()
    await stop_sync_poller()
    await stop_batch_poller()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="LoopLM — LLM debugging platform API",
    lifespan=lifespan,
)

# --- CORS — env-configurable, no wildcard with credentials ---
_allowed_origins = [
    o.strip()
    for o in settings.cors_allowed_origins.split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request logging middleware ---
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s %s %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


# --- Error handlers — sanitized responses ---
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "NOT_FOUND", "message": "Resource not found"}},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred"}},
    )


# --- Routers ---
app.include_router(health.router)
app.include_router(version.router)
app.include_router(auth_router.router)
app.include_router(projects.router)
app.include_router(integrations.router)
app.include_router(ingest_keys.router)
app.include_router(ingest.router)
app.include_router(traces.router)
app.include_router(trace_detail.router)
app.include_router(feedback.router)
app.include_router(fixes.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(analysis.router)
app.include_router(langsmith.router)
app.include_router(graph.router)
app.include_router(route_analysis.router)
app.include_router(issues.router)
app.include_router(advisor.router)
app.include_router(prompts.router)
app.include_router(evaluations.router)
app.include_router(evaluators.router)
app.include_router(experiments.router)
app.include_router(datasets.router)
app.include_router(rag_coverage.router)
app.include_router(index_explorer.router)
app.include_router(source_registry.router)
app.include_router(imports.router)
app.include_router(code_agent.router)
app.include_router(github_oauth.router)
app.include_router(costs_overview.router)
app.include_router(llm_costs.router)
app.include_router(user_settings.router)
app.include_router(permissions.router)
app.include_router(project_members.router)
app.include_router(admin.router)
