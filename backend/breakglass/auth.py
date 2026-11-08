"""Firebase (Google) sign-in verification for the web API.

The browser signs in with the Firebase JS SDK and sends its ID token as
`Authorization: Bearer <token>`. We verify the token's signature, expiry,
audience (our project id) and issuer with Google's `google-auth` library, which
needs only the PUBLIC project id: no service-account key, no new secret.

What a verified token proves: the request comes from someone signed in to that
Google account. It does NOT prove they made the console change being
explained; that stays self-reported (PRD §8 "Identity").
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Callable

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

VERIFIED_ASSURANCE = "google-account (verified sign-in)"

Verifier = Callable[[str], dict]


class InvalidToken(Exception):
    """Signature, expiry, audience or issuer check failed. Message is never sent to clients."""


class NotAllowed(Exception):
    """Token is valid but the account may not do this (e.g. unverified email, not an admin)."""


@dataclass(frozen=True)
class Identity:
    email: str
    name: str | None
    uid: str | None


def firebase_verifier(project_id: str) -> Verifier:
    """Real verifier. Fetches (and caches per process) Google's public signing keys."""
    request = google_requests.Request()
    issuer = f"https://securetoken.google.com/{project_id}"

    def verify(token: str) -> dict:
        try:
            claims = id_token.verify_firebase_token(token, request, audience=project_id,
                                                    clock_skew_in_seconds=10)
        except Exception as e:  # expired, bad signature, wrong audience, network...
            raise InvalidToken(type(e).__name__) from None
        if not isinstance(claims, dict) or claims.get("iss") != issuer or claims.get("aud") != project_id:
            raise InvalidToken("issuer/audience mismatch")
        return claims

    return verify


def bearer_token(authorization: str | None) -> str | None:
    scheme, _, value = (authorization or "").partition(" ")
    value = value.strip()
    return value if scheme.lower() == "bearer" and value else None


def identity_from(token: str, verifier: Verifier) -> Identity:
    claims = verifier(token)  # raises InvalidToken
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip() or claims.get("email_verified") is not True:
        raise NotAllowed("a verified email is required")
    name = claims.get("name") if isinstance(claims.get("name"), str) else None
    uid = claims.get("sub") if isinstance(claims.get("sub"), str) else None
    return Identity(email=email.strip().lower(), name=(name or "").strip()[:100] or None, uid=uid)


def is_shared_admin_token(supplied: str, shared: str | None) -> bool:
    return bool(shared) and hmac.compare_digest(supplied.encode(), shared.encode())
