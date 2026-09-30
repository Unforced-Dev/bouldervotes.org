"""Upcoming 2026 forums you can attend or watch live.

Data: data/harvest/2026/forums_upcoming.json (researched 2026-09-30; every
event is confirmed on the organizer's own page). Past dates drop off at build
time, so the nightly rebuild keeps the list current.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "harvest" / "2026" / "forums_upcoming.json"

# Plain notes a voter needs. Keyed by event id; the organizer page is the source.
VOTER_NOTES = {
    "2026-09-30-bolo-barha-council-mayor": "In person. Focused on housing and property rights. Free for BOLO and BARHA members; the page doesn't say whether others pay, so call 303-442-3585. Networking follows.",
    "2026-10-06-eof-plan-mayoral-climate": "Online. Register on Zoom to get the link. The Zoom page gives the start time only.",
    "2026-10-13-eof-plan-council-climate": "Online. Register on Zoom to get the link. One outside calendar lists this as a mayoral forum; the organizer's page says City Council candidates.",
    "2026-10-14-brl-kgnu-mayoral-debate": "In person. Free, but get a ticket. Neither host has said whether it will be broadcast or recorded.",
    "2026-10-14-lwv-ballot-issues-pearl": "In person, at a retirement community. Covers state, county and city ballot issues, not candidates. The League says anyone interested is welcome; call ahead about entry.",
    "2026-10-15-lwv-ballot-issues-frasier": "In person, at a retirement community. Covers state, county and city ballot issues, not candidates. The League says anyone interested is welcome; call ahead about entry.",
}

WHAT = {
    "mayor": "Mayoral candidates",
    "council": "City Council candidates",
}


def _today() -> dt.date:
    return dt.date.fromisoformat(os.environ.get("BV_TODAY") or dt.date.today().isoformat())


def _time(t: str | None) -> str:
    if not t:
        return ""
    h, m = map(int, t.split(":"))
    suffix = "a.m." if h < 12 else "p.m."
    h12 = h % 12 or 12
    if h == 12 and m == 0:
        return "noon"
    return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"


def _when(e: dict) -> str:
    d = dt.date.fromisoformat(e["date"])
    day = d.strftime("%A, %B ") + str(d.day)
    start, end = _time(e.get("start_time")), _time(e.get("end_time"))
    span = f"{start} to {end}" if start and end else start
    return f"{day} · {span}" if span else day


def _what(e: dict) -> str:
    races = e.get("races") or []
    if races and str(races[0]).startswith("ballot measures"):
        return "Ballot measures"
    return " and ".join(str(WHAT.get(r, r)) for r in races) or "Candidates"


def _where(e: dict) -> str:
    if not e.get("in_person"):
        return "Online (Zoom)"
    parts = [e.get("venue_name"), e.get("venue_address")]
    return ", ".join(p for p in parts if p)


def upcoming(today: dt.date | None = None) -> list[dict]:
    today = today or _today()
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    rows = [e for e in rows if dt.date.fromisoformat(e["date"]) >= today]
    return sorted(rows, key=lambda e: (e["date"], e.get("start_time") or ""))


def upcoming_html(prefix: str = "") -> str:
    rows = upcoming()
    esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    out = ["<section class='upcoming' aria-labelledby='upcoming-h'>",
           "<h2 id='upcoming-h'>Upcoming forums you can attend</h2>"]
    if not rows:
        out.append("<p>No more public forums are on the calendar before Election Day. "
                   "Past forums and recordings are below.</p></section>")
        return "\n".join(out)
    out.append("<p class='note'>Each listing comes from the organizer's own page. Times are Mountain. "
               "Check the link before you go, since plans change.</p><ul class='events'>")
    for e in rows:
        link = e.get("registration_url") or e["source_url"]
        label = "Register" if e.get("registration_url") else "Details"
        hosts = " and ".join(e.get("hosts") or [])
        out.append(
            "<li class='card event'>"
            f"<p class='event-when'>{esc(_when(e))}</p>"
            f"<h3>{esc(e['title'])}</h3>"
            f"<p><strong>{esc(_what(e))}</strong> · {esc(_where(e))}</p>"
            f"<p class='meta'>Hosted by {esc(hosts)}</p>"
            f"<p>{esc(VOTER_NOTES.get(e['id'], ''))}</p>"
            f"<p><a class='btn secondary' href='{esc(link)}'>{label}</a> "
            f"<a href='{esc(e['source_url'])}'>Organizer's page</a></p>"
            "</li>"
        )
    out.append("</ul></section>")
    return "\n".join(out)


def upcoming_md() -> str:
    rows = upcoming()
    if not rows:
        return "No more public forums are scheduled before Election Day."
    lines = []
    for e in rows:
        link = e.get("registration_url") or e["source_url"]
        lines.append(f"- {_when(e)} (Mountain): {e['title']}. {_what(e)}. {_where(e)}. "
                     f"Hosted by {' and '.join(e.get('hosts') or [])}. {VOTER_NOTES.get(e['id'], '')} "
                     f"Source: {e['source_url']}" + (f" Register: {link}" if link != e["source_url"] else ""))
    return "\n".join(lines)
