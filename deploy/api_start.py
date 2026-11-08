"""Fail closed in production; no local SQLite or unauthenticated fallback."""
import os
import sys


def validate(env):
    missing = [key for key in ("BG_DATABASE_URL", "BG_FIREBASE_PROJECT_ID")
               if not env.get(key, "").strip()]
    if missing:
        raise SystemExit("Required production settings missing: " + ", ".join(missing) + "; these are required before starting the public API.")


if __name__ == "__main__":
    validate(os.environ)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "breakglass.api:app",
                            "--host", "0.0.0.0", "--port", "8000"])
