"""Neutralize terminal control/format characters in user-supplied text.

Reasons and reporter names are user input that we print to a terminal right
before an apply confirmation. ESC sequences could erase or fake warning lines;
bidi overrides could disguise text. Reject them at input, and strip at output
(rows may predate validation).
"""

from __future__ import annotations

import unicodedata


def has_control(text: str) -> bool:
    return any(unicodedata.category(ch) in ("Cc", "Cf") for ch in text)


def safe(text: object) -> str:
    s = "" if text is None else str(text)
    return "".join("?" if unicodedata.category(ch) in ("Cc", "Cf") else ch for ch in s)
