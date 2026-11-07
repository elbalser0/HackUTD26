"""HTTP API: read records/apply runs, and annotate records (report/decision).

Deliberately absent: anything that runs Terraform, accepts paths, or accepts
commands. Those stay in the CLI, driven by a human at a terminal.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from functools import lru_cache

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, service
from .config import load_settings
from .db import Database
from .models import (
    ApplyRunList,
    ApplyRunOut,
    DecisionIn,
    HealthOut,
    RecordList,
    RecordOut,
    ReportIn,
    Resolution,
    utcnow,
)

log = logging.getLogger("breakglass.api")


@lru_cache(maxsize=1)
def get_db() -> Database:
    return Database(load_settings().db_path)


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def apply_run_out(row) -> ApplyRunOut:
    return ApplyRunOut(
        id=row["id"],
        environment=row["environment"],
        generated_at=row["generated_at"],
        plan_fingerprint=row["plan_fingerprint"],
        proposed_changes=json.loads(row["proposed_changes_json"]),
        warnings=json.loads(row["warnings_json"]),
        check_status=row["check_status"],
        coverage_note=row["coverage_note"],
        ack_outcome=row["ack_outcome"],
        ack_note=row["ack_note"],
        completed_at=row["completed_at"],
    )


def create_app(db: Database | None = None, allowed_hosts: list[str] | None = None) -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="Break-Glass Handoff API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    # Host allowlist blocks DNS-rebinding pages from reaching this unauthenticated local API.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or list(settings.allowed_hosts))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    def database() -> Database:
        return db if db is not None else get_db()

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        parts = []
        for e in exc.errors()[:5]:
            loc = ".".join(str(x) for x in e.get("loc", ()) if x != "body")
            parts.append(f"{loc}: {e.get('msg')}")
        return _err(422, "validation_error", "; ".join(parts) or "invalid request")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 409: "conflict"}.get(exc.status_code, "error")
        return _err(exc.status_code, code, str(exc.detail))

    @app.exception_handler(service.NotFound)
    async def _nf(_: Request, exc: service.NotFound):
        return _err(404, "not_found", str(exc))

    @app.exception_handler(service.Conflict)
    async def _conflict(_: Request, exc: service.Conflict):
        return _err(409, "conflict", str(exc))

    @app.exception_handler(service.BadInput)
    async def _bad_input(_: Request, exc: service.BadInput):
        return _err(422, "validation_error", str(exc))

    @app.exception_handler(Exception)
    async def _internal(_: Request, exc: Exception):
        log.exception("unhandled error")  # details to server log only, never to the client
        return _err(500, "internal", "internal error")

    @app.get("/api/health", response_model=HealthOut)
    def health():
        last = None
        try:
            database().ping()
            last = database().last_scan(settings.environment)
            db_status, status, code = "ok", "ok", 200
        except Exception:
            db_status, status, code = "error", "degraded", 503
        body = HealthOut(status=status, version=__version__, db=db_status, environment=settings.environment,
                         terraform_dir_configured=settings.tf_dir is not None, time=utcnow(),
                         last_scan_at=None, last_scan_status=None)
        if last is not None:
            try:
                body = body.model_copy(update={
                    "last_scan_at": datetime.fromisoformat(last["started_at"].replace("Z", "+00:00")),
                    "last_scan_status": last["status"]})
            except (ValueError, TypeError, AttributeError):
                pass  # malformed row: report no scan age rather than failing health
        return JSONResponse(status_code=code, content=json.loads(body.model_dump_json()))

    @app.get("/api/records", response_model=RecordList)
    def list_records(resolution: Resolution | None = Query(default=None)):
        rows = database().list_records(resolution=resolution.value if resolution else None)
        return RecordList(records=[service.record_out(r) for r in rows])

    @app.get("/api/records/{record_id}", response_model=RecordOut)
    def get_record(record_id: str):
        row = database().get_record(record_id)
        if row is None:
            raise service.NotFound(f"record {record_id} not found")
        return service.record_out(row)

    @app.post("/api/records/{record_id}/report", response_model=RecordOut)
    def post_report(record_id: str, body: ReportIn):
        return service.report(database(), record_id, body)

    @app.post("/api/records/{record_id}/decision", response_model=RecordOut)
    def post_decision(record_id: str, body: DecisionIn):
        return service.decide(database(), record_id, body)

    @app.get("/api/apply-runs", response_model=ApplyRunList)
    def list_apply_runs(limit: int = Query(default=20, ge=1, le=100)):
        return ApplyRunList(apply_runs=[apply_run_out(r) for r in database().list_apply_runs(limit)])

    @app.get("/api/apply-runs/{run_id}", response_model=ApplyRunOut)
    def get_apply_run(run_id: str):
        row = database().get_apply_run(run_id)
        if row is None:
            raise service.NotFound(f"apply run {run_id} not found")
        return apply_run_out(row)

    return app


app = create_app()
