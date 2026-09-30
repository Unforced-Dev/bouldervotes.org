#!/usr/bin/env python3
"""Re-pull 2026 City of Boulder campaign-finance filings and compare.

    python3 tools/refresh_finance_2026.py            # harvest + before/after table
    python3 tools/refresh_finance_2026.py --compare  # table only (vs git HEAD)

Harvests the live clerk app with harvest_finance.py into
data/harvest/finance_2026.json, then prints each committee's totals before
(the committed copy at git HEAD) and after, with the latest report's name and
filing date. Flags, never hides:
  * any total that went DOWN (should only happen if an amended report says so)
  * matching funds received above contributions
  * committees that vanished or are new
  * committees with no new report since the last pull

Then run: python3 seed.py && python3 build.py && python3 -m unittest && python3 tools/check_links.py
Filing calendar: https://bouldercolorado.gov/election-guidelines
(42nd day Sept 22, 28th Oct 6, 21st Oct 13, 14th Oct 20, Thursday prior Oct 29, 30 days after Dec 3).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REL = "data/harvest/finance_2026.json"
KEYS = ("contributions_total", "matching_received", "expenditures_total")


def before_data() -> dict:
    try:
        raw = subprocess.run(["git", "show", f"HEAD:{REL}"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout
        return json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {"committees": []}


def money(v) -> str:
    return "—" if v is None else f"{v:,.2f}"


def compare(before: dict, after: dict) -> list[str]:
    old = {c["committee_id"]: c for c in before.get("committees", [])}
    new_ids = {c["committee_id"] for c in after["committees"]}
    flags: list[str] = []
    print(f"retrieved: before {before.get('retrieved_on')}  after {after.get('retrieved_on')}")
    print(f"{'committee / candidate':34} {'raised before':>13} {'raised after':>13} {'matching':>10} "
          f"{'spent':>10} {'cash':>10}  latest report (filed)")
    for c in after["committees"]:
        b = old.get(c["committee_id"])
        who = (c.get("person") or c["committee_name"])[:34]
        last = (c.get("statements") or [{}])[-1]
        print(f"{who:34} {money((b or {}).get('contributions_total')):>13} {money(c.get('contributions_total')):>13} "
              f"{money(c.get('matching_received')):>10} {money(c.get('expenditures_total')):>10} "
              f"{money(c.get('cash_on_hand')):>10}  {last.get('label') or 'no report'} ({last.get('submitted_on') or '—'})")
        if b is None:
            flags.append(f"NEW committee: {c['committee_name']}")
            continue
        for k in KEYS:
            if (c.get(k) or 0) < (b.get(k) or 0) - 0.005:
                flags.append(f"DOWN {k}: {who} {money(b.get(k))} -> {money(c.get(k))}")
        if len(c.get("statements") or []) == len(b.get("statements") or []):
            flags.append(f"no new report: {who} (still {last.get('label') or 'none'})")
        if (c.get("matching_received") or 0) > (c.get("contributions_total") or 0) + 0.005:
            flags.append(f"matching above contributions: {who} {money(c.get('matching_received'))} vs "
                         f"{money(c.get('contributions_total'))} (as filed)")
    for cid, b in old.items():
        if cid not in new_ids:
            flags.append(f"GONE from clerk list: {b['committee_name']}")
    return flags


def main() -> None:
    before = before_data()
    if "--compare" not in sys.argv:
        subprocess.run([sys.executable, "harvest_finance.py"], cwd=ROOT, check=True)
    after = json.loads((ROOT / REL).read_text(encoding="utf-8"))
    flags = compare(before, after)
    print()
    print("Flags:" if flags else "Flags: none")
    for f in flags:
        print("  -", f)


if __name__ == "__main__":
    main()
