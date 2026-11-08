"""Test-wide setup. Tests never read a developer's repo-root .env: a local
BG_FIREBASE_PROJECT_ID or BG_ADMIN_EMAILS there must not change results.
test_dotenv.py opts back in explicitly with a temporary file."""

import os

os.environ["BG_NO_DOTENV"] = "1"
