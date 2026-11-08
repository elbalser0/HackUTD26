"""Firebase (Google) sign-in for the web API.

Agreed design:
- Firebase NOT configured -> today's behavior (writes open, admin via shared token only).
- Firebase configured (project id set):
  * POST report/decision require `Authorization: Bearer <Firebase ID token>` with a
    verified email. The event actor is the account email, assurance
    "google-account (verified sign-in)". Reads stay open (localhost only).
  * /api/admin/* accepts EITHER the shared BG_ADMIN_TOKEN (offline fallback) OR a
    Firebase token whose verified email is in the admin allowlist.
- Token values are never echoed in responses.

The real verifier needs network access to Google's public keys, so these tests
inject a fake verifier. `test_real_verifier_*` checks the wiring to google-auth.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helpers import ENV, load

from breakglass import auth, service
from breakglass.api import create_app
from breakglass.db import Database

PROJECT = "breakglass-test"
SHARED = "shared-admin-token-for-tests"

TOKENS = {
    "tok-dana": {"email": "dana@example.com", "email_verified": True, "name": "Dana", "sub": "u1"},
    "tok-admin": {"email": "Lead@Example.com", "email_verified": True, "name": "Lead", "sub": "u2"},
    "tok-unverified": {"email": "eve@example.com", "email_verified": False, "name": "Eve", "sub": "u3"},
    "tok-noemail": {"email_verified": True, "sub": "u4"},
}


def fake_verifier(token: str) -> dict:
    if token not in TOKENS:
        raise auth.InvalidToken("bad token")
    return TOKENS[token]


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "a.db")
    yield d
    d.close()


def make_client(db, *, firebase=True, admin_token=SHARED, admins=("lead@example.com",)):
    app = create_app(db=db, allowed_hosts=["testserver"], admin_token=admin_token,
                     firebase_project_id=PROJECT if firebase else "",
                     admin_emails=list(admins), verifier=fake_verifier)
    return TestClient(app)


def rid_of(db):
    return service.ingest_refresh_plan(db, ENV, load("refresh_drift_8443")).new_ids[0]


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def events(db, rid):
    return db.list_events(record_id=rid)


# ---- Firebase not configured: unchanged behavior -----------------------------

def test_without_firebase_writes_stay_open(db):
    rid = rid_of(db)
    with make_client(db, firebase=False) as c:
        r = c.post(f"/api/records/{rid}/report", json={"reason": "opened 8443"})
    assert r.status_code == 200
    assert events(db, rid)[-1]["actor_assurance"] == "self-reported"


def test_health_reports_auth_mode_without_secrets(db):
    with make_client(db) as c:
        body = c.get("/api/health").json()
    assert body["auth"] == {"firebase_project_id": PROJECT, "writes_require_sign_in": True,
                            "admin_via_firebase": True, "admin_via_shared_token": True}
    assert SHARED not in str(body)
    with make_client(db, firebase=False, admin_token="") as c:
        body = c.get("/api/health").json()
    assert body["auth"]["writes_require_sign_in"] is False and body["auth"]["admin_via_shared_token"] is False


# ---- writes require sign-in ---------------------------------------------------

@pytest.mark.parametrize("path,body", [
    ("report", {"reason": "opened 8443"}),
    ("decision", {"intent": "keep", "note": "vendor still on 8443"}),
])
@pytest.mark.parametrize("headers,status", [
    ({}, 401),
    (bearer("not-a-real-token"), 401),
    ({"Authorization": "Basic abc"}, 401),
    (bearer("tok-unverified"), 403),
    (bearer("tok-noemail"), 403),
])
def test_writes_reject_missing_invalid_or_unverified(db, path, body, headers, status):
    rid = rid_of(db)
    with make_client(db) as c:
        r = c.post(f"/api/records/{rid}/{path}", json=body, headers=headers)
    assert r.status_code == status
    assert "not-a-real-token" not in r.text
    assert events(db, rid) == [], "a rejected write must not create history"


def test_signed_in_report_records_verified_account(db):
    rid = rid_of(db)
    with make_client(db) as c:
        r = c.post(f"/api/records/{rid}/report", json={"reason": "opened 8443", "reporter": "Paul"},
                   headers=bearer("tok-dana"))
    assert r.status_code == 200
    e = events(db, rid)[-1]
    assert e["actor"] == "dana@example.com"
    assert e["actor_assurance"] == auth.VERIFIED_ASSURANCE
    assert r.json()["reporter"] == "Paul", "a typed reporter name is kept as the self-reported name"


def test_signed_in_report_without_name_uses_account_name(db):
    rid = rid_of(db)
    with make_client(db) as c:
        r = c.post(f"/api/records/{rid}/report", json={"reason": "opened 8443"}, headers=bearer("tok-dana"))
    assert r.json()["reporter"] == "Dana"


def test_signed_in_decision_records_verified_account(db):
    rid = rid_of(db)
    with make_client(db) as c:
        r = c.post(f"/api/records/{rid}/decision", json={"intent": "defer", "note": "ask Paul"},
                   headers=bearer("tok-dana"))
    assert r.status_code == 200
    e = events(db, rid)[-1]
    assert (e["kind"], e["actor"], e["actor_assurance"]) == ("decision", "dana@example.com", auth.VERIFIED_ASSURANCE)


def test_reads_stay_open_with_firebase(db):
    rid = rid_of(db)
    with make_client(db) as c:
        assert c.get("/api/records").status_code == 200
        assert c.get(f"/api/records/{rid}").status_code == 200
        assert c.get(f"/api/records/{rid}/events").status_code == 200


# ---- admin: Firebase admin email OR shared token -------------------------------

def test_admin_via_firebase_admin_email_case_insensitive(db):
    with make_client(db) as c:
        assert c.get("/api/admin/log", headers=bearer("tok-admin")).status_code == 200


def test_admin_rejects_signed_in_non_admin(db):
    with make_client(db) as c:
        assert c.get("/api/admin/log", headers=bearer("tok-dana")).status_code == 403


def test_admin_shared_token_fallback_still_works(db):
    with make_client(db) as c:
        assert c.get("/api/admin/log", headers=bearer(SHARED)).status_code == 200


def test_admin_rejects_no_or_bad_credentials(db):
    with make_client(db) as c:
        assert c.get("/api/admin/log").status_code == 401
        r = c.get("/api/admin/log", headers=bearer("wrong"))
        assert r.status_code == 401 and "wrong" not in r.text


def test_admin_unverified_email_rejected(db):
    with make_client(db, admins=("eve@example.com",)) as c:
        assert c.get("/api/admin/log", headers=bearer("tok-unverified")).status_code == 403


def test_admin_disabled_when_nothing_configured(db):
    with make_client(db, firebase=False, admin_token="") as c:
        assert c.get("/api/admin/log", headers=bearer("tok-admin")).status_code == 403


def test_firebase_admin_without_allowlist_is_never_admin(db):
    with make_client(db, admins=()) as c:
        assert c.get("/api/admin/log", headers=bearer("tok-admin")).status_code == 403


# ---- real verifier wiring --------------------------------------------------------

def test_real_verifier_checks_project_audience(monkeypatch):
    seen = {}

    def fake_verify(token, request, audience=None, clock_skew_in_seconds=0):
        seen.update(token=token, audience=audience)
        return {"email": "x@example.com", "email_verified": True,
                "iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT}
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", fake_verify)
    claims = auth.firebase_verifier(PROJECT)("abc")
    assert seen == {"token": "abc", "audience": PROJECT} and claims["email"] == "x@example.com"


def test_real_verifier_wraps_library_errors(monkeypatch):
    def boom(*a, **k):
        raise ValueError("Token expired")
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", boom)
    with pytest.raises(auth.InvalidToken):
        auth.firebase_verifier(PROJECT)("abc")


def test_real_verifier_rejects_wrong_issuer(monkeypatch):
    monkeypatch.setattr(auth.id_token, "verify_firebase_token",
                        lambda *a, **k: {"email": "x@example.com", "email_verified": True,
                                         "iss": "https://securetoken.google.com/other", "aud": PROJECT})
    with pytest.raises(auth.InvalidToken):
        auth.firebase_verifier(PROJECT)("abc")


# ---- distinct error codes, so the UI can say the right thing -------------------

def _code(r):
    return r.status_code, r.json()["error"]["code"]


def test_write_error_codes(db):
    rid = rid_of(db)
    with make_client(db) as c:
        url = f"/api/records/{rid}/report"
        assert _code(c.post(url, json={"reason": "x"})) == (401, "sign_in_required")
        assert _code(c.post(url, json={"reason": "x"}, headers=bearer("bad"))) == (401, "sign_in_invalid")
        assert _code(c.post(url, json={"reason": "x"}, headers=bearer("tok-unverified"))) == (403, "email_unverified")


def test_admin_error_codes(db):
    with make_client(db) as c:
        assert _code(c.get("/api/admin/log")) == (401, "unauthorized")
        assert _code(c.get("/api/admin/log", headers=bearer("tok-dana"))) == (403, "not_admin")
        assert _code(c.get("/api/admin/log", headers=bearer("tok-unverified"))) == (403, "email_unverified")
    with make_client(db, firebase=False, admin_token="") as c:
        assert _code(c.get("/api/admin/log", headers=bearer("x"))) == (403, "admin_not_configured")
