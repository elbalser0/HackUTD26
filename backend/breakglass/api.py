"""HTTP API: read records/apply runs, and annotate records (report/decision).

Deliberately absent: anything that runs Terraform, accepts paths, or accepts
commands. Those stay in the CLI, driven by a human at a terminal.
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, analytics, auth, admin, service
from .config import load_settings
from .storage import StorageUnavailable, open_database
from .db import Database
from .models import (
    ActivityOut,
    AdminLogOut,
    ApplyRunList,
    ApplyRunOut,
    DecisionIn,
    EventList,
    HealthOut,
    MeOut,
    OverviewOut,
    RecordList,
    RecordOut,
    ReportIn,
    Resolution,
    RunOutcome,
    TimelineOut,
    utcnow,
)

log = logging.getLogger("breakglass.api")


@lru_cache(maxsize=1)
def get_db():
    return open_database(load_settings())


class AuthDenied(Exception):
    """401/403 with a stable machine-readable code so the UI can explain it."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _err(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}}, headers=headers)


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
        started_at=row["started_at"],
        reviewer=row["reviewer"],
        reviewer_assurance=row["reviewer_assurance"],
        rationale=row["rationale"],
    )


def create_app(db: Database | None = None, allowed_hosts: list[str] | None = None,
               admin_token: str | None = None, firebase_project_id: str | None = None,
               admin_emails: list[str] | None = None, verifier: "auth.Verifier | None" = None,
               all_admins: bool | None = None) -> FastAPI:
    settings = load_settings()
    token = admin_token if admin_token is not None else settings.admin_token
    project = (firebase_project_id if firebase_project_id is not None else settings.firebase_project_id) or None
    admins = {e.strip().lower() for e in (admin_emails if admin_emails is not None else settings.admin_emails)
              if e and e.strip()}
    everyone_admin = settings.all_admins if all_admins is None else all_admins
    # Firebase is on only when a project id is configured (an injected verifier alone does not enable it).
    verify = (verifier or auth.firebase_verifier(project)) if project else None
    app = FastAPI(title="Argus API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    # Host allowlist blocks DNS-rebinding pages from reaching this unauthenticated local API.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or list(settings.allowed_hosts))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
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
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
                409: "conflict"}.get(exc.status_code, "error")
        return _err(exc.status_code, code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(AuthDenied)
    async def _auth_denied(_: Request, exc: AuthDenied):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return _err(exc.status, exc.code, exc.message, headers=headers)

    @app.exception_handler(service.NotFound)
    async def _nf(_: Request, exc: service.NotFound):
        return _err(404, "not_found", str(exc))

    @app.exception_handler(service.Conflict)
    async def _conflict(_: Request, exc: service.Conflict):
        return _err(409, "conflict", str(exc))

    @app.exception_handler(service.BadInput)
    async def _bad_input(_: Request, exc: service.BadInput):
        return _err(422, "validation_error", str(exc))

    @app.exception_handler(StorageUnavailable)
    async def _storage(_: Request, exc: StorageUnavailable):
        log.error("storage unavailable: %s", exc)
        return _err(503, "storage_unavailable", "the database is unavailable; nothing was recorded")

    @app.exception_handler(Exception)
    async def _internal(_: Request, exc: Exception):
        log.exception("unhandled error")  # details to server log only, never to the client
        return _err(500, "internal", "internal error")

    def signed_in(request: Request) -> "auth.Identity | None":
        """Verified Firebase identity for web writes. None when Firebase is not configured
        (writes stay open, as before). Bearer header only, never a URL parameter."""
        if verify is None:
            return None
        supplied = auth.bearer_token(request.headers.get("authorization"))
        if supplied is None:
            raise AuthDenied(401, "sign_in_required", "sign-in required")
        try:
            return auth.identity_from(supplied, verify)
        except auth.InvalidToken:
            raise AuthDenied(401, "sign_in_invalid", "sign-in invalid or expired") from None
        except auth.NotAllowed:
            raise AuthDenied(403, "email_unverified", "a verified email is required") from None

    def is_admin_email(email: str | None) -> bool:
        """The one admin rule used by both /api/me (persona) and require_admin (enforcement)."""
        return verify is not None and bool(email) and (everyone_admin or email in admins)

    def require_reader(request: Request) -> None:
        """Reads: open when Firebase is not configured (offline demo). Otherwise any verified
        sign-in (employee or admin) or the shared admin token."""
        if verify is None:
            return
        supplied = auth.bearer_token(request.headers.get("authorization"))
        if supplied is not None and auth.is_shared_admin_token(supplied, token):
            return
        signed_in(request)

    def require_admin(request: Request) -> None:
        """Server-side gate for /api/admin/*: the shared token (offline fallback) OR a
        Firebase sign-in whose verified email is allowlisted. Fails closed."""
        firebase_admin = verify is not None and (bool(admins) or everyone_admin)
        if not token and not firebase_admin:
            raise AuthDenied(403, "admin_not_configured", "admin access is not configured on this server")
        supplied = auth.bearer_token(request.headers.get("authorization"))
        if supplied is None:
            raise AuthDenied(401, "unauthorized", "admin credentials required")
        if auth.is_shared_admin_token(supplied, token):
            return
        if verify is None:
            raise AuthDenied(401, "unauthorized", "admin credentials required")
        try:
            who = auth.identity_from(supplied, verify)
        except auth.InvalidToken:
            raise AuthDenied(401, "unauthorized", "admin credentials required") from None
        except auth.NotAllowed:
            raise AuthDenied(403, "email_unverified", "a verified email is required") from None
        if not is_admin_email(who.email):
            raise AuthDenied(403, "not_admin", "this account is not an admin")

    def _aware(name: str, raw: str | None) -> datetime | None:
        if raw is None:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise service.BadInput(f"{name}: not an ISO 8601 timestamp") from None
        if parsed.tzinfo is None:
            raise service.BadInput(f"{name}: timezone required (e.g. a trailing Z)")
        return parsed

    @app.get("/api/me", response_model=MeOut)
    def me(request: Request):
        """Which persona the UI should show. Display only: every route enforces access itself."""
        supplied = auth.bearer_token(request.headers.get("authorization"))
        if supplied is not None and auth.is_shared_admin_token(supplied, token):
            return MeOut(signed_in=False, email=None, display_name=None, role="admin", auth_mode="shared-token")
        if verify is None:
            return MeOut(signed_in=False, email=None, display_name=None, role=None, auth_mode="none")
        if supplied is None:
            return MeOut(signed_in=False, email=None, display_name=None, role=None, auth_mode="firebase")
        who = signed_in(request)
        return MeOut(signed_in=True, email=who.email, display_name=who.name,
                     role="admin" if is_admin_email(who.email) else "employee", auth_mode="firebase")

    @app.get("/api/admin/log", response_model=AdminLogOut, dependencies=[Depends(require_admin)])
    def admin_log(engineer: str | None = Query(default=None, max_length=100),
                  resource: str | None = Query(default=None, max_length=300),
                  since: str | None = Query(default=None), until: str | None = Query(default=None),
                  outcome: RunOutcome | None = Query(default=None),
                  event_type: str | None = Query(default=None, alias="type", max_length=40),
                  limit: int = Query(default=100, ge=1, le=500)):
        if event_type is not None and event_type not in admin.EVENT_TYPES:
            raise service.BadInput("type: must be one of " + ", ".join(admin.EVENT_TYPES))
        return admin.log(database(), engineer=engineer, resource=resource, since=_aware("since", since),
                         until=_aware("until", until), outcome=outcome, event_type=event_type, limit=limit)

    @app.get("/api/admin/overview", response_model=OverviewOut, dependencies=[Depends(require_admin)])
    def admin_overview(window: str = Query(default="24h", pattern="^(24h|7d)$")):
        return admin.overview(database(), window=window, now=utcnow(), environment=settings.environment)

    @app.get("/api/admin/analytics", response_model=ActivityOut, dependencies=[Depends(require_admin)])
    def admin_analytics(environment: str = Query(min_length=1, max_length=100),
                        since: str = Query(), until: str = Query()):
        return analytics.activity(database(), environment, _aware("since", since), _aware("until", until))

    @app.get("/api/admin/records/{record_id}/timeline", response_model=TimelineOut,
             dependencies=[Depends(require_admin)])
    def admin_timeline(record_id: str):
        result = admin.timeline(database(), record_id)
        if result is None:
            raise service.NotFound(f"record {record_id} not found")
        return result

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
                         last_scan_at=None, last_scan_status=None,
                         auth={"firebase_project_id": project, "writes_require_sign_in": verify is not None,
                               "reads_require_sign_in": verify is not None,
                               "admin_via_firebase": verify is not None and (bool(admins) or everyone_admin),
                               "admin_via_shared_token": bool(token)})
        if last is not None:
            try:
                body = body.model_copy(update={
                    "last_scan_at": datetime.fromisoformat(last["started_at"].replace("Z", "+00:00")),
                    "last_scan_status": last["status"]})
            except (ValueError, TypeError, AttributeError):
                pass  # malformed row: report no scan age rather than failing health
        return JSONResponse(status_code=code, content=json.loads(body.model_dump_json()))

    @app.get("/api/records", response_model=RecordList, dependencies=[Depends(require_reader)])
    def list_records(resolution: Resolution | None = Query(default=None)):
        rows = database().list_records(resolution=resolution.value if resolution else None)
        return RecordList(records=service.records_out(database(), rows))

    @app.get("/api/records/{record_id}", response_model=RecordOut, dependencies=[Depends(require_reader)])
    def get_record(record_id: str):
        row = database().get_record(record_id)
        if row is None:
            raise service.NotFound(f"record {record_id} not found")
        return service.records_out(database(), [row])[0]

    @app.post("/api/records/{record_id}/report", response_model=RecordOut)
    def post_report(record_id: str, body: ReportIn, request: Request):
        who = signed_in(request)
        if who is None:
            return service.report(database(), record_id, body)
        return service.report(database(), record_id, body, account=who.email, account_name=who.name,
                              assurance=auth.VERIFIED_ASSURANCE)

    @app.post("/api/records/{record_id}/decision", response_model=RecordOut)
    def post_decision(record_id: str, body: DecisionIn, request: Request):
        who = signed_in(request)
        if who is None:
            return service.decide(database(), record_id, body)
        return service.decide(database(), record_id, body, actor=who.email, assurance=auth.VERIFIED_ASSURANCE)

    @app.get("/api/records/{record_id}/events", response_model=EventList, dependencies=[Depends(require_reader)])
    def record_events(record_id: str):
        """Append-only history for one record: reports, decisions, wrapper reviews (PRD R6/R10)."""
        if database().get_record(record_id) is None:
            raise service.NotFound(f"record {record_id} not found")
        return EventList(events=[service.event_out(e) for e in database().list_events(record_id=record_id)])

    @app.get("/api/apply-runs/{run_id}/events", response_model=EventList, dependencies=[Depends(require_reader)])
    def run_events(run_id: str):
        """Reviews, run_started and run_finished events for one wrapper run (PRD R7/R8)."""
        if database().get_apply_run(run_id) is None:
            raise service.NotFound(f"apply run {run_id} not found")
        return EventList(events=[service.event_out(e) for e in database().list_events(run_id=run_id)])

    @app.get("/api/apply-runs", response_model=ApplyRunList, dependencies=[Depends(require_reader)])
    def list_apply_runs(limit: int = Query(default=20, ge=1, le=100)):
        return ApplyRunList(apply_runs=[apply_run_out(r) for r in database().list_apply_runs(limit)])

    @app.get("/api/apply-runs/{run_id}", response_model=ApplyRunOut, dependencies=[Depends(require_reader)])
    def get_apply_run(run_id: str):
        row = database().get_apply_run(run_id)
        if row is None:
            raise service.NotFound(f"apply run {run_id} not found")
        return apply_run_out(row)

    return app


app = create_app()
