"""Plain-English cleanup for editorial NOTE text from the database.

Apply only to our own notes (notes, research_notes, date_source). Never to
verbatim quotes, answers, source titles or URLs: quotes stay word for word.
"""
from __future__ import annotations

import re

_PHRASES = [
    ("catalogued this pass", "listed here"),
    (" (already in ingest.py)", ""),
    (" in this pass", ""),
    (" this pass", ""),
]


def plain(text: object) -> str:
    s = "" if text is None else str(text)
    for old, new in _PHRASES:
        s = s.replace(old, new)
    s = re.sub(r"\bthis pass\b", "this time", s)
    s = re.sub(r"\bThis pass\b", "This time", s)
    s = re.sub(r"\bingested\b", "copied", s)
    s = re.sub(r"\bharvested\b", "collected", s)
    return s
