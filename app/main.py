from __future__ import annotations

from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from .database import connect, get_engine, initialize_database
from .reliability import create_reliability_run
from .reliability_reports import get_reliability_run, list_reliability_runs, reliability_trend
from .reliability_scenarios import available_reliability_scenarios
from .reward_batches import (
    create_reward_batch,
    get_reward_batch,
    list_reward_audit_events,
    list_reward_batches,
    list_reward_items,
    list_reward_ledger,
    retry_reward_item,
    reward_delivery_stats,
    submit_reward_batch,
)
from .task_queue import dependency_health, dispatch_reliability_run, dispatch_reward_batch, uses_async_worker


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Reward Delivery Reliability Platform",
    description="Production-oriented reward delivery reliability platform with an executable failure lab.",
    version="1.1.0",
    lifespan=lifespan,
)
DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard.html"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTAINER_FRONTEND_DIST = PROJECT_ROOT / "frontend_dist"
LOCAL_FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
FRONTEND_DIST = CONTAINER_FRONTEND_DIST if CONTAINER_FRONTEND_DIST.exists() else LOCAL_FRONTEND_DIST
API_PREFIX = "/api/v1"


class ReliabilityRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal[
        "duplicate_request",
        "acknowledgement_loss",
        "concurrent_consume",
        "guard_disabled_control",
    ]


class RunAccepted(BaseModel):
    run_id: int
    status: str
    detail_url: str


class RewardItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_id: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    reward_gems: int = Field(gt=0, le=1_000_000)
    failure_mode: Literal["none", "fail_once", "always_fail"] = "none"


class RewardBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=128)
    created_by: str = Field(default="portfolio_admin", min_length=2, max_length=64)
    items: list[RewardItemInput] = Field(min_length=1, max_length=100)


class ActorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(default="portfolio_admin", min_length=2, max_length=64)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _error_payload(
    request: Request,
    code: str,
    message: str,
    *,
    fields: Sequence[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "error": {"code": code, "message": message, "fields": list(fields or [])},
        "request_id": _request_id(request),
    }


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, error: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=_error_payload(request, "VALIDATION_ERROR", "请求参数校验失败", fields=error.errors()),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, error: HTTPException):
    code = "NOT_FOUND" if error.status_code == 404 else "REQUEST_ERROR"
    return JSONResponse(
        status_code=error.status_code,
        content=_error_payload(request, code, str(error.detail)),
        headers=error.headers,
    )


@app.get("/health")
def health(response: Response):
    database_ok = False
    database_backend = "unavailable"
    try:
        with connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ok = True
        database_backend = get_engine().dialect.name
    except Exception:
        database_ok = False
    dependencies = {
        "database": "healthy" if database_ok else "unavailable",
        **dependency_health(),
    }
    required_states = [value for value in dependencies.values() if value != "not_required"]
    status = "ok" if required_states and all(value == "healthy" for value in required_states) else "degraded"
    if status != "ok":
        response.status_code = 503
    return {
        "status": status,
        "mode": "async" if uses_async_worker() else "sync",
        "dependencies": dependencies,
        "database_backend": database_backend,
    }


@app.get("/reliability/scenarios")
@app.get(f"{API_PREFIX}/reliability/scenarios")
def reliability_scenarios():
    return {"items": available_reliability_scenarios()}


@app.post("/reliability/runs", status_code=201)
def create_reliability_experiment(body: ReliabilityRunRequest):
    """Legacy route retaining the original synchronous response shape."""
    try:
        run_id = create_reliability_run(body.scenario)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if dispatch_reliability_run(run_id) == "queued":
        return {"run_id": run_id, "status": "queued", "message": "实验已提交至 Redis/Celery Worker"}
    return get_reliability_run(run_id)


@app.post(f"{API_PREFIX}/reliability/runs", status_code=202, response_model=RunAccepted)
def create_v1_reliability_experiment(body: ReliabilityRunRequest):
    """Create a run and always return the same task-resource contract."""
    run_id = create_reliability_run(body.scenario)
    dispatch_reliability_run(run_id)
    report = get_reliability_run(run_id)
    status = str(report["status"]) if report else "queued"
    return RunAccepted(run_id=run_id, status=status, detail_url=f"{API_PREFIX}/reliability/runs/{run_id}")


@app.get("/reliability/runs")
@app.get(f"{API_PREFIX}/reliability/runs")
def reliability_runs(limit: int = Query(default=12, ge=1, le=50)):
    return {"items": list_reliability_runs(limit=limit), "limit": limit}


@app.get("/reliability/trend")
@app.get(f"{API_PREFIX}/reliability/trend")
def get_reliability_trend(limit: int = Query(default=12, ge=1, le=50)):
    return reliability_trend(limit=limit)


@app.get("/reliability/runs/{run_id}")
@app.get(f"{API_PREFIX}/reliability/runs/{{run_id}}")
def reliability_run_detail(run_id: int):
    report = get_reliability_run(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="可靠性实验不存在")
    return report


@app.get("/dashboard")
def dashboard():
    return FileResponse(DASHBOARD)


@app.get(f"{API_PREFIX}/reward-stats")
def reward_stats():
    return reward_delivery_stats()


@app.post(f"{API_PREFIX}/reward-batches", status_code=201)
def create_batch(body: RewardBatchInput):
    try:
        batch_id = create_reward_batch(
            body.name,
            body.created_by,
            [item.model_dump() for item in body.items],
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return get_reward_batch(batch_id)


@app.get(f"{API_PREFIX}/reward-batches")
def reward_batches(limit: int = Query(default=30, ge=1, le=100)):
    return {"items": list_reward_batches(limit), "limit": limit}


@app.get(f"{API_PREFIX}/reward-batches/{{batch_id}}")
def reward_batch_detail(batch_id: str):
    batch = get_reward_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="奖励批次不存在")
    return batch


@app.post(f"{API_PREFIX}/reward-batches/{{batch_id}}/submit", status_code=202)
def submit_batch(batch_id: str, body: ActorInput):
    try:
        submit_reward_batch(batch_id, body.actor)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    dispatch_reward_batch(batch_id)
    batch = get_reward_batch(batch_id)
    return {
        "batch_id": batch_id,
        "status": batch["status"] if batch else "processing",
        "detail_url": f"{API_PREFIX}/reward-batches/{batch_id}",
    }


@app.post(f"{API_PREFIX}/reward-items/{{item_id}}/retry", status_code=202)
def retry_item(item_id: str, body: ActorInput):
    try:
        batch_id = retry_reward_item(item_id, body.actor)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    dispatch_reward_batch(batch_id)
    return {"item_id": item_id, "batch_id": batch_id, "status": "queued", "detail_url": f"{API_PREFIX}/reward-batches/{batch_id}"}


@app.get(f"{API_PREFIX}/reward-ledger")
def reward_ledger(limit: int = Query(default=100, ge=1, le=200)):
    return {"items": list_reward_ledger(limit), "limit": limit}


@app.get(f"{API_PREFIX}/reward-items")
def reward_items(
    status: Literal["draft", "queued", "processing", "succeeded", "failed"] | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    return {"items": list_reward_items(status=status, limit=limit), "limit": limit}


@app.get(f"{API_PREFIX}/reward-audit-events")
def reward_audit_events(limit: int = Query(default=100, ge=1, le=200)):
    return {"items": list_reward_audit_events(limit), "limit": limit}


if FRONTEND_DIST.exists():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIST, html=True), name="reward-console")
