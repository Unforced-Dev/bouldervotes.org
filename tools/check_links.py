#!/usr/bin/env python3
"""Report broken local links under docs/. Exit 1 if any.

Checks href/src in every HTML page, and every bouldervotes.org URL in
llms.txt, llms-full.txt and the api/v1 JSON files (they must exist in docs/).

    python3 tools/check_links.py
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

DOCS = Path(__file__).resolve().parent.parent / "docs"
SITE = "https://bouldervotes.org"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v:
                self.links.append(v)
            if k == "id" and v:
                self.ids.add(v)


def parse(path: Path) -> Links:
    p = Links()
    p.feed(path.read_text(encoding="utf-8"))
    return p


def resolve(docs: Path, base: Path, path: str) -> Path:
    if path.startswith("/"):  # site-root absolute, e.g. /llms-full.txt
        target = (docs / unquote(path.lstrip("/"))).resolve()
    else:
        target = (base.parent / unquote(path)).resolve()
    if target.is_dir():
        target = target / "index.html"
    return target


def broken_links(docs: Path = DOCS) -> list[tuple[str, str]]:
    pages = {f: parse(f) for f in docs.rglob("*.html")}
    bad = []
    for f, p in pages.items():
        for href in p.links:
            u = urlparse(href)
            if u.scheme or href.startswith("//") or href.startswith("mailto:"):
                continue
            target = f if not u.path else resolve(docs, f, u.path)
            if not target.exists():
                bad.append((str(f.relative_to(docs)), href))
                continue
            if u.fragment and target.suffix == ".html":
                tp = pages.get(target) or parse(target)
                if u.fragment not in tp.ids:
                    bad.append((str(f.relative_to(docs)), href))
    machine = [docs / "llms.txt", docs / "llms-full.txt", *sorted((docs / "api" / "v1").rglob("*.json"))]
    for f in machine:
        if not f.exists():
            continue
        for url in set(re.findall(re.escape(SITE) + r"(?:/[^\s)\"'<>]*)?", f.read_text(encoding="utf-8"))):
            path = urlparse(url.rstrip(".,;")).path or "/"
            if not resolve(docs, docs / "index.html", path).exists():
                bad.append((str(f.relative_to(docs)), url))
    return bad


if __name__ == "__main__":
    bad = broken_links()
    for f, h in bad:
        print(f"{f}: {h}")
    print(f"{len(bad)} broken local links")
    sys.exit(1 if bad else 0)
