#!/usr/bin/env python3
"""Run tools/chat_eval.json against a chat gateway and write a markdown report.

    python3 tools/chat_eval.py https://haiku-gateway.example.workers.dev [-o report.md] [--only 12,13]

Makes real, billable requests, one per question, each a fresh single-turn
conversation. Never run by the test suite. A person (or a second model) reads
the report against the "expected" line; this script does not grade.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ask(gateway: str, question: str, timeout: int = 90) -> tuple[int, dict]:
    body = json.dumps({"app": "bouldervotes", "messages": [{"role": "user", "content": question}]}).encode()
    req = urllib.request.Request(gateway.rstrip("/") + "/v1/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "bouldervotes-chat-eval/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"ok": False, "error": "http_error", "message": str(e)}
    except Exception as e:  # network, timeout, bad JSON
        return 0, {"ok": False, "error": "client_error", "message": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gateway")
    ap.add_argument("-o", "--out", default="chat_eval_report.md")
    ap.add_argument("--evalfile", default=str(HERE / "chat_eval.json"))
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between requests (rate limits)")
    a = ap.parse_args()

    items = json.loads(Path(a.evalfile).read_text(encoding="utf-8"))
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        items = [i for i in items if i["id"] in keep]

    total = 0.0
    rows = []
    for n, it in enumerate(items):
        if n and a.pause:
            time.sleep(a.pause)
        status, data = ask(a.gateway, it["question"])
        if status == 429 and data.get("retry_after_s", 999) <= 90:
            time.sleep(float(data["retry_after_s"]) + 1)
            status, data = ask(a.gateway, it["question"])
        cost = (data.get("usage") or {}).get("cost_usd") or 0.0
        total += cost
        rows.append((it, status, data, cost))
        print(f"[{it['id']:>2}] {it['category']:<15} HTTP {status} ${cost:.4f}", file=sys.stderr)

    L = ["# Boulder Votes chat evaluation", "",
         f"Gateway: {a.gateway}", f"Questions: {len(rows)}. Total cost: ${total:.4f}. "
         f"OK: {sum(1 for r in rows if r[2].get('ok'))}, errors: {sum(1 for r in rows if not r[2].get('ok'))}.", ""]
    for it, status, data, cost in rows:
        L += [f"## {it['id']}. [{it['category']}] {it['question']}", "",
              f"**Expected:** {it['expected']}", ""]
        if data.get("ok"):
            u = data.get("usage") or {}
            L += [f"**Answer** (cached: {data.get('cached')}, cost ${cost:.4f}, usage: {json.dumps(u)}):", "",
                  *["> " + ln if ln else ">" for ln in str(data.get("answer", "")).splitlines()], ""]
        else:
            L += [f"**Error** (HTTP {status}): `{data.get('error')}`: {data.get('message')}", ""]
        L += ["**Verdict:** _(reviewer fills in: pass / fail, and why)_", "", "---", ""]
    Path(a.out).write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {a.out}; total cost ${total:.4f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
