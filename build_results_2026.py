"""Election-night results view for Nov 3, 2026, behind the BV_RESULTS flag.

Renders from data/harvest/2026/results.json, which tools/fetch_results_2026.py
writes from the county's export. Rules (BRIEF-results.md, trust rules):
- Unofficial until the county certifies; every view carries CAVEAT and an as-of time.
- No calls, projections or "leading" words; no elected/passed marks; no colour by candidate.
- Mayor first choices are labelled as first choices. Ranked-choice rounds show
  only when the county's tabulation is in the file.
- Candidates in ballot order; measures as equal YES and NO panels.
- Every vote count links to the county's official results page.

The existing `results`/`measure_results` tables are not used for live results:
they have no as-of time, no unofficial/certified status and no ballots-counted
field, and their `elected`/`passed` columns would make calls on partial counts.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
RESULTS_JSON = ROOT / "data" / "harvest" / "2026" / "results.json"
COUNTY_RESULTS_URL = "https://bouldercounty.gov/elections/results/"
DENVER = ZoneInfo("America/Denver")

# Election night: change this to "1" (keep BV_RESULTS=0 as the off switch), because
# the nightly rebuild and other workers run build.py without BV_RESULTS set.
RESULTS_DEFAULT = "0"

CAVEAT = "Unofficial results until the county certifies. Results update as ballots are counted."
FIRST_CHOICE_NOTE = ("These are first choices only, not the result. If no candidate has more than half "
                     "of the first choices, the county counts in rounds: the candidate with the fewest votes "
                     "is removed and those ballots go to each voter's next choice.")
ROUNDS_UNREAD_NOTE = "The county has posted a round-by-round count, but we could not read its file automatically."
NO_ROUNDS_NOTE = "The county has not posted its round-by-round ranked-choice count yet. It will appear here when it does."
COUNCIL_RULE = "Vote for up to five. When the count is final, the five candidates with the most votes fill the seats."
WORD = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
OFFICE_LABEL = {"mayor": "Mayor", "council": "City Council"}


def results_enabled() -> bool:
    return os.environ.get("BV_RESULTS", RESULTS_DEFAULT) == "1"


def results_path() -> Path:
    return Path(os.environ.get("BV_RESULTS_FILE") or RESULTS_JSON)


def load_results() -> dict | None:
    """The parsed county results, or None before the first fetch."""
    p = results_path()
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def href(url: object) -> str:
    """A link target from the results file, escaped. Only https links pass; anything else
    (javascript:, data:, a relative path) becomes the county's results page."""
    u = "" if url is None else str(url)
    return esc(u if u.startswith("https://") else COUNTY_RESULTS_URL)


def norm_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", name.lower().replace("’", "'").replace("'", "")).split())


def nice_time(iso: str | None) -> str:
    """'9:42 p.m. Tuesday, Nov. 3, 2026' in Boulder time."""
    if not iso:
        return ""
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=DENVER)
    t = t.astimezone(DENVER)
    hour = t.strftime("%-I:%M").replace(":00", "")
    ampm = "a.m." if t.hour < 12 else "p.m."
    month = t.strftime("%b") + ("." if t.strftime("%b") != "May" else "")
    return f"{hour} {ampm} {t.strftime('%A')}, {month} {t.day}, {t.year}"


def pct(n: int, total: int) -> str:
    return f"{n / total * 100:.1f}%" if total else "–"


class Roster:
    """Ballot order and person pages for the election in the results file."""

    def __init__(self, con: sqlite3.Connection | None, year: int):
        self.order: dict[str, dict[str, tuple[int | None, str]]] = {"mayor": {}, "council": {}}
        self.measures: dict[str, str] = {}
        if con is None:
            return
        from ingest_2026 import NAME_ALIASES
        self.aliases = {norm_name(k): norm_name(v) for k, v in NAME_ALIASES.items()}
        for office, pos, name, slug in con.execute(
                """SELECT o.slug, c.ballot_position, p.full_name, p.slug FROM candidacies c
                   JOIN people p ON p.id=c.person_id JOIN races r ON r.id=c.race_id
                   JOIN elections e ON e.id=r.election_id JOIN offices o ON o.id=r.office_id
                   WHERE e.year=? AND c.status != 'withdrawn'""", (year,)):
            self.order.setdefault(office, {})[norm_name(name)] = (pos, slug)
        for letter, title in con.execute(
                """SELECT m.letter, m.title FROM measures m JOIN elections e ON e.id=m.election_id
                   WHERE e.year=? AND m.letter IS NOT NULL""", (year,)):
            self.measures[letter.upper()] = title

    def lookup(self, office: str, name: str) -> tuple[int | None, str] | None:
        n = norm_name(name)
        n = getattr(self, "aliases", {}).get(n, n)
        return self.order.get(office, {}).get(n)

    def in_ballot_order(self, office: str, rows: list[dict]) -> bool:
        """True when every listed name except write-ins matches a ballot position we have a source for."""
        named = [r for r in rows if "write" not in r["name"].lower()]
        return bool(named) and all((hit := self.lookup(office, r["name"])) and hit[0] is not None for r in named)

    def order_note(self, office: str, rows: list[dict]) -> str:
        """Say ballot order only when our sourced ballot order was applied to these rows."""
        if self.in_ballot_order(office, rows):
            return "Listed in ballot order."
        return "Listed in the order the county lists them."

    def ballot_sorted(self, office: str, rows: list[dict]) -> list[dict]:
        """Our sourced ballot order when every name matches; otherwise the county's own order
        (its pages list choices in ballot order), so one unmatched spelling can't reshuffle a list.
        Write-ins keep their place after the named candidates."""
        if not self.in_ballot_order(office, rows):
            return rows
        named = [r for r in rows if "write" not in r["name"].lower()]
        return (sorted(named, key=lambda r: self.lookup(office, r["name"])[0])
                + [r for r in rows if "write" in r["name"].lower()])


def _contests(data: dict, office: str) -> list[dict]:
    return [c for c in data.get("contests", []) if c.get("office") == office]


def number(n: int, url: str) -> str:
    return f"<a class='res-num' href='{href(url)}'>{n:,}</a>"


def asof_block(data: dict) -> str:
    county = nice_time(data.get("county_updated"))
    got = nice_time(data.get("retrieved_at"))
    when = (f"Boulder County's count as of <strong>{esc(county)}</strong>." if county
            else f"Retrieved from Boulder County at <strong>{esc(got)}</strong>.")
    fetched = f" We copied it at {esc(got)}." if county and got else ""
    label = (f" The county's page is labelled “{esc(data['county_status'])}”." if data.get("county_status") else "")
    ballots = data.get("ballots_counted_countywide")
    counted = (f"<p>Ballots counted so far across Boulder County (all races, not just the city): "
               f"{number(ballots, data['official_url'])}.</p>" if ballots else "")
    return (f"<div class='res-caveat' role='note'><p class='res-caveat-main'>{esc(CAVEAT)}</p>"
            f"<p>{when}{fetched}{label} <a href='{href(data['official_url'])}'>See the official results from Boulder County</a>.</p>"
            f"{counted}</div>")


def candidate_cell(roster: Roster, office: str, name: str, prefix: str) -> str:
    hit = roster.lookup(office, name)
    return f"<a href='{prefix}people/{esc(hit[1])}.html'>{esc(name)}</a>" if hit else esc(name)


def mayor_section(data: dict, roster: Roster, prefix: str = "") -> str:
    out = ["<section class='res-race' aria-labelledby='res-mayor'>",
           "<h2 id='res-mayor'>Mayor</h2><p class='res-kind'>Ranked choice · one seat</p>"]
    cs = _contests(data, "mayor")
    if not cs:
        return "\n".join(out + ["<p>No mayor results in the county's file yet.</p>", "</section>"])
    c = cs[0]
    url = c.get("official_url") or data["official_url"]
    rounds = c.get("rounds") or []
    if rounds:
        rurl = c.get("rounds_url") or url
        posted = nice_time(c.get("rounds_updated"))
        out.append("<h3>The county's ranked-choice count, round by round</h3>")
        out.append(f"<p class='note'>From the county's ranked-choice tabulation{', as of ' + esc(posted) if posted else ''}. "
                   "It changes as more ballots are counted. "
                   f"<a href='{href(rurl)}'>See the county's round-by-round count</a>.</p>")
        out.append("<div class='res-rounds'>")
        for rd in rounds:
            rows = roster.ballot_sorted("mayor", rd["candidates"])
            total = sum(r["votes"] for r in rows)
            out.append(f"<div class='res-round'><h4>Round {rd['round']}</h4><table class='res-table'>"
                       "<thead><tr><th scope='col'>Candidate</th><th scope='col' class='num'>Votes</th>"
                       "<th scope='col' class='num'>Share</th></tr></thead><tbody>")
            for r in rows:
                out.append(f"<tr><th scope='row'>{candidate_cell(roster, 'mayor', r['name'], prefix)}</th>"
                           f"<td class='num'>{number(r['votes'], rurl)}</td><td class='num'>{pct(r['votes'], total)}</td></tr>")
            out.append("</tbody></table>")
            if rd.get("inactive") is not None:
                out.append(f"<p class='meta'>Ballots no longer counted in this round (blank, overvoted, or no choices left): "
                           f"{number(rd['inactive'], rurl)}</p>")
            out.append("</div>")
        out.append("</div>")
    if not rounds and c.get("rounds_error"):
        rurl = c.get("rounds_url") or c.get("rounds_page_url") or url
        out.append(f"<p class='note'>{esc(ROUNDS_UNREAD_NOTE)} <a href='{href(rurl)}'>See the county's round-by-round count</a>.</p>")
    elif not rounds:
        out.append(f"<p class='note'>{esc(NO_ROUNDS_NOTE)}</p>")
    if not c["candidates"]:
        out.append("<p>The county has not posted mayor numbers yet.</p></section>")
        return "\n".join(out)
    out.append("<h3>First-choice votes</h3>")
    out.append(f"<p>{esc(FIRST_CHOICE_NOTE)}</p>")
    rows = roster.ballot_sorted("mayor", c["candidates"])
    total = sum(r["votes"] for r in rows)
    out.append("<table class='res-table'><thead><tr><th scope='col'>Candidate</th>"
               "<th scope='col' class='num'>First choices</th><th scope='col' class='num'>Share</th></tr></thead><tbody>")
    for r in rows:
        out.append(f"<tr><th scope='row'>{candidate_cell(roster, 'mayor', r['name'], prefix)}</th>"
                   f"<td class='num'>{number(r['votes'], url)}</td><td class='num'>{pct(r['votes'], total)}</td></tr>")
    out.append("</tbody></table>")
    out.append(f"<p class='meta'>{roster.order_note('mayor', c['candidates'])}</p></section>")
    return "\n".join(out)


def council_section(data: dict, roster: Roster, prefix: str = "") -> str:
    out = ["<section class='res-race' aria-labelledby='res-council'>",
           "<h2 id='res-council'>City Council</h2>"]
    cs = _contests(data, "council")
    if not cs:
        return "\n".join(out + ["<p>No council results in the county's file yet.</p>", "</section>"])
    for c in cs:
        url = c.get("official_url") or data["official_url"]
        seats = c.get("seats") or 5
        out.append(f"<p class='res-kind'>{WORD.get(seats, seats).capitalize()} seats · most votes</p>")
        if len(cs) > 1:
            out.append(f"<h3>{esc(c['name'])}</h3>")
        out.append(f"<p>{esc(COUNCIL_RULE) if seats == 5 else f'The {WORD.get(seats, seats)} candidates with the most votes fill the seats when the count is final.'}</p>")
        out.append("<table class='res-table'><thead><tr><th scope='col'>Candidate</th>"
                   "<th scope='col' class='num'>Votes</th></tr></thead><tbody>")
        for r in roster.ballot_sorted("council", c["candidates"]):
            out.append(f"<tr><th scope='row'>{candidate_cell(roster, 'council', r['name'], prefix)}</th>"
                       f"<td class='num'>{number(r['votes'], url)}</td></tr>")
        out.append("</tbody></table>")
    seats = cs[0].get("seats") or 5
    out.append(f"<p class='meta'>{roster.order_note('council', cs[0]['candidates'])} Each voter could choose up to {WORD.get(seats, seats)}, "
               "so the votes add up to more than the number of ballots.</p></section>")
    return "\n".join(out)


def measures_section(data: dict, roster: Roster, prefix: str = "") -> str:
    out = ["<section class='res-race' aria-labelledby='res-measures'>",
           "<h2 id='res-measures'>City measures</h2>"]
    ms = sorted(_contests(data, "measure"), key=lambda m: m.get("code") or m["name"])
    if not ms:
        return "\n".join(out + ["<p>No city measure results in the county's file yet.</p>", "</section>"])
    out.append("<div class='res-measures'>")
    for m in ms:
        url = m.get("official_url") or data["official_url"]
        code = m.get("code") or ""
        title = roster.measures.get(code.upper()) or m["name"]
        total = m["yes"] + m["no"]
        link = (f"<a href='{prefix}measures/2026-{esc(code.lower())}.html'>{esc(title)}</a>"
                if code and code.upper() in roster.measures and str(data.get("election", {}).get("date", "")).startswith("2026")
                else esc(title))
        out.append(f"<article class='res-measure' aria-labelledby='res-m-{esc(code.lower())}'>"
                   f"<h3 id='res-m-{esc(code.lower())}'><span class='code'>{esc(code)}</span> {link}</h3>"
                   "<dl class='res-yesno'>"
                   f"<div><dt>Yes</dt><dd>{number(m['yes'], url)}<span class='res-pct'>{pct(m['yes'], total)}</span></dd></div>"
                   f"<div><dt>No</dt><dd>{number(m['no'], url)}<span class='res-pct'>{pct(m['no'], total)}</span></dd></div>"
                   "</dl></article>")
    out.append("</div></section>")
    return "\n".join(out)


def results_body(data: dict | None, roster: Roster, prefix: str = "") -> str:
    if data is None:
        return ("<h1>Election results</h1>"
                f"<div class='res-caveat' role='note'><p class='res-caveat-main'>{esc(CAVEAT)}</p>"
                "<p>Boulder County posts its first results after the polls close at 7 p.m. on Tuesday, Nov. 3. "
                "They will appear here soon after. "
                f"<a href='{COUNTY_RESULTS_URL}'>Boulder County election results</a>.</p></div>")
    election = data.get("election", {})
    head = [f"<p class='eyebrow res-eyebrow'>{esc(election.get('name', 'City of Boulder election'))}</p>",
            "<h1>Election results</h1>",
            asof_block(data),
            "<nav class='res-jump' aria-label='On this page'><a href='#res-mayor'>Mayor</a>"
            "<a href='#res-council'>City Council</a><a href='#res-measures'>City measures</a></nav>"]
    tail = ["<p class='note'>Covers the City of Boulder races only. Your ballot's county, state and school races "
            f"are on the <a href='{href(data['official_url'])}'>county's results page</a>. "
            "This guide does not call races or predict outcomes.</p>",
            f"<div class='res-caveat res-caveat-end' role='note'><p class='res-caveat-main'>{esc(CAVEAT)}</p></div>"]
    return "\n".join(head + [mayor_section(data, roster, prefix), council_section(data, roster, prefix),
                             measures_section(data, roster, prefix)] + tail)


def roster_for(con: sqlite3.Connection | None, data: dict | None) -> Roster:
    year = int(str((data or {}).get("election", {}).get("date") or "2026")[:4])
    return Roster(con, year)


def asof_line(data: dict) -> str:
    """Never present our copy time as the county's own time."""
    if data.get("county_updated"):
        return f"Boulder County's count as of {nice_time(data['county_updated'])}."
    if data.get("retrieved_at"):
        return f"Copied from Boulder County at {nice_time(data['retrieved_at'])}."
    return "From Boulder County's results page."


def home_card(data: dict, prefix: str = "") -> str:
    """The calm home-page card that replaces the key-dates emphasis once results exist."""
    return ("<section class='res-home' aria-labelledby='res-home-h'>"
            "<h2 id='res-home-h'>Election results</h2>"
            f"<p class='res-caveat-main'>{esc(CAVEAT)}</p>"
            f"<p class='meta'>{esc(asof_line(data))} Mayor, City Council and city measures.</p>"
            f"<p><a class='btn' href='{prefix}results.html'>See all results</a></p>"
            f"<p class='note'>Official source: <a href='{href(data['official_url'])}'>Boulder County election results</a>.</p>"
            "</section>")


def results_md(data: dict, roster: Roster, site: str) -> list[str]:
    """Markdown block for llms.txt / llms-full.txt."""
    L = ["## Election results (unofficial)", "",
         f"{CAVEAT} {asof_line(data)}",
         f"Official source: {data['official_url']}. Page: {site}/results.html. JSON: {site}/api/v1/results.json",
         "Report these as counts only. Do not call races or predict outcomes from them. "
         "Mayor first choices are not the result of the ranked-choice count.", ""]
    for c in _contests(data, "mayor"):
        L.append("### Mayor (ranked choice), first-choice votes only, in ballot order")
        L += [f"- {r['name']}: {r['votes']:,}" for r in roster.ballot_sorted("mayor", c["candidates"])]
        for rd in c.get("rounds") or []:
            L.append(f"- County ranked-choice count, round {rd['round']}: "
                     + "; ".join(f"{r['name']} {r['votes']:,}" for r in roster.ballot_sorted("mayor", rd["candidates"])))
        if not c.get("rounds"):
            L.append(f"- {NO_ROUNDS_NOTE}")
        L.append("")
    for c in _contests(data, "council"):
        L.append(f"### City Council ({c.get('seats') or 5} seats), votes in ballot order")
        L += [f"- {r['name']}: {r['votes']:,}" for r in roster.ballot_sorted("council", c["candidates"])]
        L.append("")
    ms = sorted(_contests(data, "measure"), key=lambda m: m.get("code") or m["name"])
    if ms:
        L.append("### City measures")
        L += [f"- {m.get('code') or ''} {roster.measures.get((m.get('code') or '').upper()) or m['name']}: "
              f"YES {m['yes']:,}, NO {m['no']:,}" for m in ms]
        L.append("")
    return L


def results_api(data: dict, roster: Roster) -> dict:
    contests = []
    for c in data.get("contests", []):
        c = dict(c)
        if c.get("office") in ("mayor", "council"):
            c["candidates"] = roster.ballot_sorted(c["office"], c["candidates"])
            if c.get("rounds"):
                c["rounds"] = [dict(rd, candidates=roster.ballot_sorted(c["office"], rd["candidates"])) for rd in c["rounds"]]
        if c.get("office") == "mayor":
            c["candidates_note"] = "First-choice votes only; not the ranked-choice result."
        contests.append(c)
    return {"caveat": CAVEAT, "status": "unofficial",
            "note": "No calls or projections. Candidates in ballot order. Rounds appear only when the county posts them.",
            "election": data.get("election"), "county_updated": data.get("county_updated"),
            "retrieved_at": data.get("retrieved_at"), "official_url": data["official_url"],
            "contests": contests}


def write(out: Path, con: sqlite3.Connection, page) -> None:
    """Called by build.py. Flag off: remove anything a flag-on build left behind."""
    api = out / "api" / "v1" / "results.json"
    if not results_enabled():
        (out / "results.html").unlink(missing_ok=True)
        (out / "css" / "results.css").unlink(missing_ok=True)
        api.unlink(missing_ok=True)
        return
    import shutil
    (out / "css").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "static" / "results" / "results.css", out / "css" / "results.css")
    data = load_results()
    roster = roster_for(con, data)
    head = "<link rel=\"stylesheet\" href=\"css/results.css\">\n"
    (out / "results.html").write_text(
        page("Election results", results_body(data, roster), year=2026, head_extra=head), encoding="utf-8")
    if data is None:
        api.unlink(missing_ok=True)
