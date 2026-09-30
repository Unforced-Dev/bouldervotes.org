#!/usr/bin/env python3
"""Print a compact digest of new feedback. Prints NOTHING when there is none.

    BV_FEEDBACK_ADMIN_TOKEN=... python3 tools/feedback_digest.py [--status new|reviewed|fixed|declined|all]

Reads from the Worker's admin endpoint (see feedback-worker/README.md).
Exits 1 with a message on stderr if the token is missing or the request fails.
Every correction is a claim: check it against sources before changing any data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import urllib.error
import urllib.request

FEEDBACK_URL = "https://feedback.bouldervotes.org/"
if "__file__" in globals():  # inside the repo: use build.py's constant
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    try:
        from build import FEEDBACK_URL
    except Exception:
        pass


def fetch(status: str, token: str) -> list[dict]:
    url = f"{FEEDBACK_URL.rstrip('/')}/admin/feedback?status={status}&limit=200"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "bv-feedback-digest"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "request failed"))
    return data["rows"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="new")
    args = ap.parse_args()
    token = os.environ.get("BV_FEEDBACK_ADMIN_TOKEN")
    if not token:
        print("feedback_digest: BV_FEEDBACK_ADMIN_TOKEN is not set", file=sys.stderr)
        return 1
    try:
        rows = fetch(args.status, token)
    except (urllib.error.URLError, RuntimeError, ValueError) as e:
        print(f"feedback_digest: {e}", file=sys.stderr)
        return 1
    if not rows:
        return 0
    rows.sort(key=lambda r: r["id"])
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    summary = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
    print(f"bouldervotes.org feedback: {len(rows)} {args.status} ({summary})")
    for r in rows:
        who = "person"
        if r["submitter_type"] == "ai-agent":
            who = f"AI agent {r.get('agent_name') or '(unnamed)'}" + (" for a user" if r.get("on_behalf_of_user") else "")
        print(f"\n#{r['id']} {r['created_at'][:16].replace('T', ' ')}Z  {r['kind']}  from {who}")
        if r.get("page_url"):
            print(f"  page:    {r['page_url']}")
        msg = " ".join(r["message"].split())
        if len(msg) > 600:
            msg = msg[:600] + " …"
        print(textwrap.fill(msg, width=100, initial_indent="  ", subsequent_indent="  "))
        if r.get("source_url"):
            print(f"  source:  {r['source_url']}")
        print(f"  contact: {r['contact']}" if r.get("contact") else "  contact: none (no reply possible)")
    print("\nCheck every correction against its source before changing data. "
          "Mark rows with POST /admin/feedback/<id> {\"status\": \"reviewed|fixed|declined\"}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
