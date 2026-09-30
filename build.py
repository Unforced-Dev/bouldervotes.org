#!/usr/bin/env python3
"""Render Boulder Votes from SQLite into docs/.

Voter chrome, not an essay:
  A year is a ballot you zoom into (who is running, what is on it).
  A person is a dossier you zoom into (what they have said, year by year).
  An issue is a comparison you zoom into (this year's field, then earlier).
  Sources stay citations. Full quotes fold. Absence is a blank cell.
"""
from __future__ import annotations

import html
import re
import sqlite3
from pathlib import Path

from build_2026 import Graph2026
from build_forums_2026 import Forums2026
from ingest_2026 import civics_markdown

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "bouldervotes.db"
OUT = ROOT / "docs"
YEARS = (2026, 2025, 2023, 2021, 2019, 2017)

# All styling lives in static/css/site.css (copied to docs/css/). Tokens and
# rationale: Parachute vault "Projects/Boulder Votes/UI overhaul 2026-09-29".
STATIC = ROOT / "static"


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s))


def clip(text: str, n: int = 160) -> str:
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + "…"


def dollars(n: object) -> str:
    if n is None:
        return "—"
    try:
        x = float(n)
    except (TypeError, ValueError):
        return "—"
    if abs(x - round(x)) < 0.005:
        return f"${x:,.0f}"
    return f"${x:,.2f}"


def human_label(value: object) -> str:
    """Raw database enum -> plain English. Anything unrecognized loses its
    underscores so snake_case never reaches a page."""
    v = "" if value is None else str(value).strip()
    return {
        # measure status
        "on_ballot": "on the ballot",
        "not_referred": "not placed on the ballot",
        "referred": "referred to the ballot",
        "passed": "passed",
        "failed": "failed",
        # candidacy status
        "certified": "on the ballot",
        "withdrawn": "withdrew",
        "elected": "elected",
        "lost": "lost",
        # source / question kinds
        "campaign_site": "campaign website",
        "questionnaire": "questionnaire",
        "interview": "interview",
        "article": "press",
        "forum": "forum",
        "video": "video",
        "official": "official record",
        "results": "election results",
        # committee kinds
        "official_candidate": "official candidate committee",
        "unofficial_candidate": "unofficial candidate committee",
        "ballot_measure": "ballot-measure committee",
        "independent_expenditure": "independent expenditure only",
        # endorser kinds
        "organization": "organization",
        "committee": "committee",
        "newspaper": "newspaper",
    }.get(v, v.replace("_", " "))


def kind_label(kind: str | None) -> str:
    return human_label(kind) or "source"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


from build_plain import plain  # noqa: E402  (notes only, never quotes)


def quote_block(verbatim: str, fold: bool = True) -> str:
    """Short answers show whole. Long ones fold on screen; print CSS opens them.
    fold=False (print sheets) never wraps in <details>, so nothing can be hidden."""
    text = verbatim or ""
    compact = " ".join(text.split())
    if len(compact) <= 180 or not fold:
        return f"<blockquote class='answer'>{esc(text)}</blockquote>"
    return (
        f"<details class='quote'><summary>{esc(clip(compact, 150))}</summary>"
        f"<blockquote class='answer'>{esc(text)}</blockquote></details>"
    )


def render_answer(verbatim: str | None, stance: str | None, notes: str | None = None, fold: bool = True) -> str:
    """Show the actual answer. Never let a yes/no stand in for a different question."""
    text = verbatim or ""
    compact = " ".join(text.split())
    notes = notes or ""
    low = compact.lower()
    beat = low.startswith("answered ") and "boulder beat" in low
    grouping = "journalist grouping" in notes.lower() or low.startswith("reported by boulder reporting lab")
    if beat:
        word = {"yes": "Yes", "no": "No", "mixed": "Mixed"}.get((stance or "").lower(), "Answered")
        extra = ""
        if "beat note:" in low:
            extra = compact.split("Beat note:", 1)[-1].strip() if "Beat note:" in compact else compact.split("beat note:", 1)[-1].strip()
            extra = f" {esc(extra)}"
        return (
            f"<p><strong>{esc(word)}</strong>.{extra} "
            f"<span class='note'>Boulder Beat asked for a yes or no by email. The candidate did not explain it.</span></p>"
        )
    if grouping:
        word = {"yes": "Yes", "no": "No", "mixed": "Mixed"}.get((stance or "").lower())
        lead = f"<p><strong>{esc(word)}</strong>. {esc(compact)}</p>" if word else f"<p>{esc(compact)}</p>"
        return (
            lead
            + "<p class='note'>A reporter grouped the candidates by position. This is not the candidate's own written answer.</p>"
        )
    return quote_block(text, fold=fold)


# At most five primary items (tests/test_design.py). Everything else lives
# under Learn, in the footer, or in the year switcher.
PRIMARY_NAV = (
    ("mayor", "index.html#mayor", "Mayor", "Mayor"),
    ("council", "index.html#council", "Council", "Council"),
    ("measures", "index.html#measures", "Ballot measures", "Measures"),
    ("forums", "compare.html", "Forums", "Forums"),
    ("learn", "learn.html", "Learn", "Learn"),
)
ARCHIVE_YEARS = tuple(y for y in YEARS if y != 2026)

TAGLINE = "A nonpartisan guide to City of Boulder elections. Every fact links to its source."

# One place to change the repository address.
REPO_URL = "https://github.com/Unforced-Dev/bouldervotes.org"

# The Learn section: hub groups, in order. (key, href, label, one plain line).
# Keys with a page of their own get the section menu; the rest are links out.
LEARN_GROUPS = (
    ("How voting works", (
        ("civics", "civics.html", "Civics 101", "Who runs the city, what it can decide, and how ranked-choice voting for mayor works."),
    )),
    ("Who's behind the campaigns", (
        ("orgs", "orgs.html", "Endorsing organizations", "Who each group is, how it picks candidates, and whom it endorsed."),
        ("finance", "finance.html", "Campaign money", "City clerk filings: raised, spent, matching funds and donors for every committee."),
    )),
    ("What candidates have said", (
        ("issues", "issues.html", "Issues", "Questions asked each cycle, grouped by topic, with the answers on file."),
        ("people", "people.html", "People", "Every candidate and endorser in this guide, across years."),
        ("questionnaires", "questionnaires.html", "Questionnaires", "Written candidate questionnaires we found, with links."),
        ("forums", "forums.html", "Forum calendar", "Every candidate forum, with recordings."),
        ("compare", "compare.html", "Forum answers, side by side", "One forum question, every candidate we quote, in ballot order."),
        ("print", "print/index.html", "Printable sheets", "One sheet per 2026 candidate. Every answer prints in full."),
    )),
    ("Where our facts come from", (
        ("sources", "sources.html", "Sources", "Every document this guide cites."),
        ("about", "about.html", "About this guide", "Who runs it, how it works, and what we won't do."),
        ("api", "api/index.html", "Open data", "The whole guide as plain text and JSON, for AI assistants and developers."),
    )),
)
LEARN_PAGES = {k: (href, label) for _, items in LEARN_GROUPS for k, href, label, _ in items}
# Listed in the Learn menu but built as part of another section (Forums, print), so no section menu on them.
LEARN_LINK_ONLY = {"compare", "print"}


def learn_nav(key: str, prefix: str = "", trail: str | None = None) -> str:
    """Breadcrumb plus the Learn section menu. A list at desktop, a <details> at phone width. No JS."""
    href, label = LEARN_PAGES[key]
    crumb = f"<a href='{prefix}learn.html'>Learn</a> › "
    crumb += f"<a href='{prefix}{href}'>{esc(label)}</a> › {esc(trail)}" if trail else esc(label)

    def groups() -> str:
        out = []
        for title, items in LEARN_GROUPS:
            links = "".join(
                f"<li><a href='{prefix}{h}'{' aria-current=\"page\"' if k == key else ''}>{esc(lab)}</a></li>"
                for k, h, lab, _ in items)
            out.append(f"<div><h2>{esc(title)}</h2><ul>{links}</ul></div>")
        years = "".join(f"<li><a href='{prefix}{y}.html'>{y}</a></li>" for y in ARCHIVE_YEARS)
        out.append(f"<div><h2>Past elections</h2><ul class='years-inline'>{years}</ul></div>")
        return "".join(out)

    menu = groups()
    return (f"<nav class='learn-nav' aria-label='Learn section'>"
            f"<p class='crumb'>{crumb}</p>"
            f"<details class='learn-menu'><summary>More in Learn</summary><div class='learn-groups'>{menu}"
            f"<p class='learn-hub'><a href='{prefix}learn.html'>All Learn pages</a></p></div></details>"
            f"<div class='learn-side'><p class='learn-hub'><a href='{prefix}learn.html'>Learn</a></p>"
            f"<div class='learn-groups'>{menu}</div></div>"
            f"</nav>")

# Inline wordmark: three Flatirons slabs over a ballot line. Accent via currentColor.
OG_IMAGE = "https://bouldervotes.org/img/og-card.png?v=1"  # bump v= to bust Facebook/iMessage caches
OG_DESC = ("Nonpartisan guide to the Nov. 3, 2026 City of Boulder election: mayor, council and measures 2J–2M, "
           "with a source for every fact.")

LOGO_SVG = (
    '<svg viewBox="0 0 40 40" role="img" aria-label="Boulder Votes logo" focusable="false">'
    '<rect width="40" height="40" rx="9" fill="currentColor"/>'
    '<path d="M7 29 L13.5 12 L17 20.5 L21 9 L26.5 21 L29.5 15 L34 29 Z" fill="#fff"/>'
    '<path d="M13.5 12 L15.2 29 M21 9 L22.6 29 M29.5 15 L30.6 29" stroke="currentColor" stroke-width="1.6" opacity=".55"/>'
    '<rect x="7" y="31" width="27" height="2.6" rx="1.3" fill="#fff"/></svg>'
)


def page(title: str, body: str, *, prefix: str = "", year: int | None = None, current: str | None = None,
         head_extra: str = "", pre_main: str = "", learn: str | None = None, learn_trail: str | None = None) -> str:
    """Site chrome. `current` is a PRIMARY_NAV key ("mayor", "council", "measures",
    "forums", "learn") or None (home). `learn` is a LEARN_PAGES key: adds the section menu."""
    if learn and not current:
        current = "learn"
    primary = []
    for key, href, label, short in PRIMARY_NAV:
        cur = ' aria-current="page"' if current == key else ""
        text = label if label == short else f'<span class="nav-long">{label}</span><span class="nav-short">{short}</span>'
        primary.append(f'<li><a href="{prefix}{href}"{cur}>{text}</a></li>')
    shown_year = year if year in ARCHIVE_YEARS else 2026
    year_items = "".join(
        f'<li><a href="{prefix}{"index" if y == 2026 else y}.html"'
        f'{" aria-current=page" if y == shown_year else ""}>{y if y != 2026 else "2026 (this election)"}</a></li>'
        for y in YEARS
    )
    yearbar = ""
    if year in ARCHIVE_YEARS:
        chips = "".join(
            f'<a href="{prefix}{"index" if y == 2026 else y}.html"{" aria-current=page" if y == year else ""}>{y}</a>'
            for y in YEARS
        )
        yearbar = (f'<nav class="yearbar" aria-label="Elections by year"><div class="wrap">'
                   f'<span>Past election archive:</span>{chips}</div></nav>')
    if learn:
        body = (f"<div class='learn-layout'>{learn_nav(learn, prefix, learn_trail)}"
                f"<div class='learn-body'>\n{body}\n</div></div>")
    home = f"{prefix}index.html"
    past_links = "".join(f'<li><a href="{prefix}{y}.html">{y} city election</a></li>' for y in ARCHIVE_YEARS)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Boulder Votes</title>
<link rel="preload" href="{prefix}fonts/source-serif-4.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{prefix}fonts/source-sans-3.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{prefix}css/site.css">
<link rel="alternate" type="text/markdown" href="/llms-full.txt" title="Full guide for AI assistants">
<meta name="theme-color" content="#1d5c63">
<meta property="og:site_name" content="Boulder Votes">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)} — Boulder Votes">
<meta property="og:description" content="{OG_DESC}">
<meta property="og:image" content="{OG_IMAGE}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Boulder Votes: everything on your Boulder city ballot, with sources. Election Day Tuesday, Nov. 3, 2026.">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{OG_IMAGE}">
{head_extra}</head>
<body>
<a class="skip" href="#content">Skip to main content</a>
<header class="site">
  <div class="bar">
    <a class="brand" href="{home}">{LOGO_SVG}<span><span class="brand-name">Boulder Votes</span><span class="brand-sub">City of Boulder · November 3, 2026</span></span></a>
    <nav class="primary" aria-label="Main"><ul>{''.join(primary)}</ul></nav>
    <details class="years"><summary><span class="visually-hidden">Election year: </span>{shown_year}</summary><ul>{year_items}</ul></details>
  </div>
</header>
{yearbar}{pre_main}<main id="content">
{body}
</main>
<footer class="site">
  <div class="footer-inner">
    <div>
      <h2>Boulder Votes</h2>
      <p>{esc(TAGLINE)}</p>
      <p>Covers the City of Boulder only. We don't endorse candidates or measures.</p>
      <p class="ai-foot">Open data: <a href="{prefix}llms-full.txt">the whole guide as one text file</a> · <a href="{prefix}api/index.html">JSON</a> · <a href="{prefix}llms.txt">llms.txt</a></p>
      <p><a href="{REPO_URL}">Source code on GitHub</a></p>
    </div>
    <div>
      <h2>2026 election</h2>
      <ul>
        <li><a href="{prefix}index.html#mayor">Mayor</a></li>
        <li><a href="{prefix}index.html#council">City Council</a></li>
        <li><a href="{prefix}index.html#measures">Ballot measures</a></li>
        <li><a href="{prefix}compare.html">Forum answers, side by side</a></li>
        <li><a href="{prefix}print/index.html">Printable sheets</a></li>
        <li><a href="{prefix}2026.html">2026 ballot details</a></li>
      </ul>
    </div>
    <div>
      <h2>Learn</h2>
      <ul>
        <li><a href="{prefix}learn.html">All Learn pages</a></li>
        <li><a href="{prefix}civics.html">Civics 101</a></li>
        <li><a href="{prefix}orgs.html">Endorsing organizations</a></li>
        <li><a href="{prefix}finance.html">Campaign money</a></li>
        <li><a href="{prefix}issues.html">Issues</a></li>
        <li><a href="{prefix}people.html">People</a></li>
        <li><a href="{prefix}forums.html">Forum calendar</a></li>
        <li><a href="{prefix}questionnaires.html">Questionnaires</a></li>
        <li><a href="{prefix}measures.html">All measures</a></li>
        <li><a href="{prefix}sources.html">Sources</a></li>
        <li><a href="{prefix}api/index.html">Data and API</a></li>
        <li><a href="{prefix}about.html">About this guide</a></li>
      </ul>
    </div>
    <div>
      <h2>Earlier elections</h2>
      <ul>{past_links}</ul>
    </div>
  </div>
</footer>
</body>
</html>
"""


def panelize(html_body: str) -> str:
    """Wrap each <h2>-led section in a card. Presentation only: no text changes."""
    parts = re.split(r"(?=<h2[ >])", html_body)
    out = [parts[0]]
    for chunk in parts[1:]:
        out.append(f"<section class='panel'>{chunk}</section>")
    return "".join(out)


def nice_iso(iso: str | None) -> str:
    """2026-09-22 -> Sept. 22, 2026 (AP style)."""
    if not iso:
        return "—"
    months = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
    y, m, d = iso[:10].split("-")
    return f"{months[int(m) - 1]} {int(d)}, {y}"


def report_line(snap) -> str:
    """Which clerk report a finance snapshot comes from, and when we pulled it."""
    keys = snap.keys()
    label = snap["report_label"] if "report_label" in keys else None
    bits = []
    if label:
        bits.append(f"{label} report, filed {nice_iso(snap['reported_on'])}")
    elif snap["reported_on"]:
        bits.append(f"report filed {nice_iso(snap['reported_on'])}")
    else:
        bits.append("no report filed")
    if "retrieved_on" in keys and snap["retrieved_on"]:
        bits.append(f"retrieved {nice_iso(snap['retrieved_on'])}")
    return "; ".join(bits)


def report_cell(r) -> str:
    """Table cell: the clerk's report name and filing date, linked to that statement."""
    if not r["reported_on"]:
        return "No report filed"
    text = f"{nice_iso(r['reported_on'])}" + (f" · {r['report_label']}" if r["report_label"] else "")
    if r["report_url"]:
        return f"<a href='{esc(r['report_url'])}'>{esc(text)}</a>"
    return esc(text)


def money_stats(snap) -> str:
    """Big-number summary of one finance snapshot."""
    cells = [("Raised", snap["contributions"]), ("Spent", snap["expenditures"]),
             ("Matching funds received", snap["matching_received"])]
    if snap["cash_on_hand"] is not None:
        cells.append(("Cash on hand", snap["cash_on_hand"]))
    return "<ul class='stats'>" + "".join(
        f"<li><span class='v'>{dollars(v)}</span><span class='k'>{k}</span></li>" for k, v in cells) + "</ul>"


def copy_static() -> None:
    """static/ -> docs/ (css, fonts, candidate photos)."""
    import shutil
    for sub in ("css", "fonts", "img"):
        src = STATIC / sub
        if src.exists():
            dst = OUT / sub
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    q = con.execute
    OUT.mkdir(parents=True, exist_ok=True)
    copy_static()
    (OUT / "people").mkdir(exist_ok=True)
    (OUT / "issues").mkdir(exist_ok=True)
    (OUT / "print").mkdir(exist_ok=True)
    (OUT / "find").mkdir(exist_ok=True)

    def race_id(year: int, office: str) -> int | None:
        row = q(
            """SELECT r.id FROM races r
               JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id
               WHERE e.year=? AND o.slug=?""",
            (year, office),
        ).fetchone()
        return None if row is None else row[0]

    def candidates_for(year: int, office: str):
        rid = race_id(year, office)
        if rid is None:
            return []
        return q(
            """SELECT c.id AS candidacy_id, p.id AS person_id, p.slug, p.full_name,
                      c.status, c.is_incumbent, c.matching_funds, c.campaign_url, c.certified_on
               FROM candidacies c JOIN people p ON p.id=c.person_id
               WHERE c.race_id=?
               ORDER BY c.ballot_position IS NULL, c.ballot_position, p.sort_name""",
            (rid,),
        ).fetchall()

    def prior_years(person_id: int, year: int) -> list[sqlite3.Row]:
        return q(
            """SELECT e.year, o.slug AS office, c.status, res.votes, res.elected
               FROM candidacies c
               JOIN races r ON r.id=c.race_id
               JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id
               LEFT JOIN results res ON res.candidacy_id=c.id AND res.round = (
                 SELECT MAX(round) FROM results r2 WHERE r2.candidacy_id=c.id
               )
               WHERE c.person_id=? AND e.year<?
               ORDER BY e.year""",
            (person_id, year),
        ).fetchall()

    def issues_answered(person_id: int) -> list[sqlite3.Row]:
        return q(
            """SELECT DISTINCT COALESCE(q.issue_slug,'other') AS slug,
                      COALESCE(i.name,'This race / other') AS name
               FROM answers a
               JOIN questions q ON q.id=a.question_id
               LEFT JOIN issues i ON i.slug=q.issue_slug
               WHERE a.person_id=?
               ORDER BY name""",
            (person_id,),
        ).fetchall()

    def finance_for(person_id: int, year: int = 2026):
        return q(
            "SELECT * FROM finance_snapshots WHERE person_id=? AND year=?",
            (person_id, year),
        ).fetchone()

    def person_href(slug: str, prefix: str = "") -> str:
        return f"{prefix}people/{slug}.html"

    def issue_href(slug: str, year: int | None = None, prefix: str = "") -> str:
        if year:
            return f"{prefix}issues/{slug}-{year}.html"
        return f"{prefix}issues/{slug}.html"

    def candidate_card(row, year: int, office: str, prefix: str = "") -> str:
        flags = []
        if row["is_incumbent"]:
            flags.append('<span class="badge inc">incumbent</span>')
        if row["matching_funds"]:
            flags.append('<span class="badge match">matching funds</span>')
        prior = prior_years(row["person_id"], year)
        prior_bits = []
        for p in prior:
            bit = f"{p['year']} {p['office']}"
            if p["elected"]:
                bit += " elected"
            elif p["status"] == "lost":
                bit += " lost"
            prior_bits.append(bit)
        returning = f"<div class='meta'>Also: {esc(', '.join(prior_bits))}</div>" if prior_bits else ""
        site = (
            f" · <a href='{esc(row['campaign_url'])}'>campaign</a>"
            if row["campaign_url"]
            else ""
        )
        status = "" if year == 2026 else f"<div class='meta'>{esc(human_label(row['status']))}</div>"
        money = ""
        if year == 2026:
            snap = finance_for(row["person_id"], 2026)
            if snap:
                match = (
                    f" · matching {dollars(snap['matching_received'])}"
                    if snap["matching_received"]
                    else ""
                )
                money = f"<div class='meta'>Raised {dollars(snap['contributions'])}{match}</div>"
        return f"""<div class="card">
          <h3><a href="{esc(person_href(row['slug'], prefix))}">{esc(row['full_name'])}</a> {''.join(flags)}{site}</h3>
          {status}{returning}{money}
        </div>"""

    def results_table(year: int, office: str, prefix: str = "") -> str:
        rid = race_id(year, office)
        if rid is None:
            return ""
        rows = q(
            """SELECT p.full_name, p.slug, res.round, res.votes, res.vote_share, res.place, res.elected
               FROM results res
               JOIN candidacies c ON c.id=res.candidacy_id
               JOIN people p ON p.id=c.person_id
               WHERE c.race_id=?
               ORDER BY res.round, res.place, res.votes DESC""",
            (rid,),
        ).fetchall()
        if not rows:
            return ""
        rounds = sorted({r["round"] for r in rows})
        chunks = []
        for rnd in rounds:
            subset = [r for r in rows if r["round"] == rnd]
            if len(rounds) > 1:
                chunks.append(f"<h3>Round {rnd}</h3>")
            body = ["<tr><th>Place</th><th>Candidate</th><th class='num'>Votes</th></tr>"]
            for r in subset:
                cls = "won" if r["elected"] else ""
                won = " (elected)" if r["elected"] else ""
                body.append(
                    f"<tr class='{cls}'><td class='num'>{r['place'] or ''}</td>"
                    f"<td><a href='{esc(person_href(r['slug'], prefix))}'>{esc(r['full_name'])}</a>{won}</td>"
                    f"<td class='num'>{r['votes']:,}</td></tr>"
                )
            chunks.append(f"<table>{''.join(body)}</table>")
        return "\n".join(chunks)

    # Archive: the outcome comes before the old questions, with source links.
    def archive_results(year: int) -> str:
        sections = ["<section class='archive-outcome' aria-labelledby='outcome'><h2 id='outcome'>Results at a glance</h2>"]
        any_results = False
        for office, label in (("mayor", "Mayor"), ("council", "City council")):
            rid = race_id(year, office)
            if rid is None:
                continue
            rows = q("""SELECT p.full_name, p.slug, res.round, res.votes, res.vote_share,
                               res.elected, s.url AS source_url
                        FROM results res JOIN candidacies c ON c.id=res.candidacy_id
                        JOIN people p ON p.id=c.person_id
                        LEFT JOIN sources s ON s.id=res.source_id
                        WHERE c.race_id=? ORDER BY res.round, res.votes DESC""", (rid,)).fetchall()
            sections.append(f"<h3>{label}</h3>")
            if not rows:
                sections.append("<p>We don't have vote totals for this race. "
                                "<a href='https://electionresults.bouldercounty.gov/'>See Boulder County's official results</a>.</p>")
                continue
            any_results = True
            max_round = max(r['round'] for r in rows)
            winners = [r for r in rows if r['elected'] and r['round'] == max_round]
            # In a multi-round count, keep the final elected marks; none from earlier rounds.
            if not winners:
                winners = [r for r in rows if r['elected']]
            if winners:
                cards = []
                for r in winners:
                    share = f" · {r['vote_share']:g}%" if r['vote_share'] is not None else ""
                    cards.append(f"<div class='archive-winner'><span class='archive-mono' aria-hidden='true'>{esc(initials(r['full_name']))}</span>"
                                 f"<div><span class='badge elected'>Elected</span><h4><a href='{esc(person_href(r['slug']))}'>{esc(r['full_name'])}</a></h4>"
                                 f"<span class='archive-num'>{r['votes']:,}</span> <span class='meta'>votes{share}</span></div></div>")
                sections.append(f"<div class='archive-winners'>{''.join(cards)}</div>")
            else:
                sections.append("<p>Elected candidates are not marked in our results data. "
                                "<a href='https://electionresults.bouldercounty.gov/'>See official results</a>.</p>")
            sources = list(dict.fromkeys(r['source_url'] for r in rows if r['source_url']))
            if sources:
                sections.append("<p class='note'>Official results: " + " · ".join(
                    f"<a href='{esc(url)}'>{'recount' if 'Recount' in url else 'Boulder County'}</a>"
                    for url in sources) + "</p>")
            if max_round > 1:
                sections.append("<details class='archive-rounds'><summary>Mayor's ranked-choice count, round by round</summary>")
                for rnd in sorted({r['round'] for r in rows}):
                    sections.append(f"<h4>Round {rnd}</h4><div class='archive-round-grid'>")
                    for r in (r for r in rows if r['round']==rnd):
                        share = f" ({r['vote_share']:g}%)" if r['vote_share'] is not None else ""
                        sections.append(f"<p><a href='{esc(person_href(r['slug']))}'>{esc(r['full_name'])}</a>: "
                                        f"{r['votes']:,} votes{share}</p>")
                    sections.append("</div>")
                sections.append("</details>")
        measures = measures_for_year(year)
        if measures:
            sections.append("<h3>City measures</h3><div class='archive-measures'>")
            for m in measures:
                if m['yes_votes'] is None or m['no_votes'] is None:
                    sections.append(f"<div class='archive-measure'><strong>{esc(m['letter'] or m['title'])}</strong> "
                                    "No result on file. <a href='https://electionresults.bouldercounty.gov/'>Official results</a></div>")
                    continue
                any_results = True
                total = m['yes_votes']+m['no_votes']
                pct = f"{m['yes_votes']/total*100:.1f}" if total else "0.0"
                source = q("SELECT s.url FROM measure_results mr LEFT JOIN sources s ON s.id=mr.source_id WHERE mr.measure_id=?",(m['id'],)).fetchone()
                link = f" <a href='{esc(source[0])}'>Official count</a>" if source and source[0] else ""
                sections.append(f"<div class='archive-measure'><span class='archive-code'>{esc(m['letter'] or m['title'])}</span> "
                                f"<strong>{'Passed' if m['result_passed'] else 'Failed'}</strong>"
                                f"<span class='archive-num'>{pct}%</span><span class='meta'>yes · {m['yes_votes']:,} yes, {m['no_votes']:,} no</span>{link}</div>")
            sections.append("</div>")
        if not any_results:
            sections.append("<p>No election results on file for this year. "
                            "<a href='https://electionresults.bouldercounty.gov/'>Check Boulder County's official results</a>.</p>")
        return '\n'.join(sections + ['</section>'])

    def initials(name: str) -> str:
        parts = name.split()
        return (parts[0][0] + parts[-1][0]).upper() if len(parts)>1 else name[:2].upper()

    def archive_candidate(row, year: int) -> str:
        result = q("""SELECT res.round, res.votes, res.vote_share, res.elected, res.place,
                             s.url AS source_url
                      FROM results res LEFT JOIN sources s ON s.id=res.source_id
                      WHERE res.candidacy_id=? ORDER BY res.round DESC LIMIT 1""",
                   (row['candidacy_id'],)).fetchone()
        badge = "<span class='badge elected'>Elected</span>" if result and result['elected'] else ""
        if result:
            share = f" · {result['vote_share']:g}%" if result['vote_share'] is not None else ""
            rnd = f" · last recorded round {result['round']}" if result['round']>1 else ""
            outcome = (f"<span class='archive-num'>{result['votes']:,}</span> votes{share}{rnd}"
                       + (f" · <a href='{esc(result['source_url'])}'>Official result</a>" if result['source_url'] else ""))
        else:
            outcome = ("No result on file · <a href='https://electionresults.bouldercounty.gov/'>"
                       "Boulder County official results</a>")
        site = f" · <a href='{esc(row['campaign_url'])}'>campaign</a>" if row['campaign_url'] else ""
        prior = prior_years(row['person_id'],year)
        prior_bits = []
        for p in prior:
            bit = f"{p['year']} {p['office']}"
            if p['elected']:
                bit += " elected"
            elif p['status'] == "lost":
                bit += " lost"
            prior_bits.append(bit)
        returning = " · Also: " + ', '.join(prior_bits) if prior_bits else ""
        flags = ("<span class='badge inc'>incumbent</span>" if row['is_incumbent'] else "") + ("<span class='badge match'>matching funds</span>" if row['matching_funds'] else "")
        status = "" if result and result['elected'] else esc(human_label(row['status']))
        return (f"<article class='card archive-candidate'><span class='archive-mono' aria-hidden='true'>{esc(initials(row['full_name']))}</span>"
                f"<div><h3><a href='{esc(person_href(row['slug']))}'>{esc(row['full_name'])}</a> {badge}{flags}{site}</h3>"
                f"<p class='meta'>{status}{esc(returning)}</p>"
                f"<p class='archive-count'>{outcome}</p></div></article>")

    def measures_for_year(year: int):
        return q(
            """SELECT m.*, mr.yes_votes, mr.no_votes, mr.passed AS result_passed
               FROM measures m
               JOIN elections e ON e.id=m.election_id
               LEFT JOIN measure_results mr ON mr.measure_id=m.id
               WHERE e.year=?
               ORDER BY m.letter IS NULL, m.letter, m.title""",
            (year,),
        ).fetchall()

    def measure_cards(year: int, prefix: str = "") -> str:
        rows = measures_for_year(year)
        if not rows:
            return '<p class="empty">No city measures recorded.</p>'
        bits = []
        for m in rows:
            letter = f"{esc(m['letter'])}: " if m["letter"] else ""
            if m["yes_votes"] is not None and m["no_votes"] is not None:
                total = m["yes_votes"] + m["no_votes"]
                pct = 100.0 * m["yes_votes"] / total if total else 0
                result = (
                    f"Passed · yes {m['yes_votes']:,} ({pct:.0f}%)"
                    if m["result_passed"]
                    else f"Failed · yes {m['yes_votes']:,} ({pct:.0f}%)"
                )
            else:
                result = human_label(m["status"])
            title_html = esc(m["title"])
            if year == 2026 and m["letter"]:
                title_html = f"<a href='{prefix}measures/2026-{esc(m['letter'].lower())}.html'>{title_html}</a>"
            bits.append(
                f"<div class='card'><h3>{letter}{title_html}</h3>"
                f"<div class='meta'>{esc(human_label(m['kind']))} · {esc(result)}</div>"
                f"<p>{esc(clip(m['summary'] or '', 220))}</p></div>"
            )
        return "\n".join(bits)

    def forums_for_year(year: int):
        return q(
            """SELECT e.*, o.name AS host,
                      (SELECT COUNT(*) FROM event_appearances a WHERE a.event_id=e.id AND a.attended=1) AS showed
               FROM events e LEFT JOIN organizations o ON o.id=e.host_org_id
               WHERE e.starts_on LIKE ?
               ORDER BY e.starts_on""",
            (f"{year}%",),
        ).fetchall()

    def issue_years(slug: str) -> list[int]:
        if slug == "other":
            rows = q("SELECT DISTINCT q.year FROM questions q WHERE q.issue_slug IS NULL AND q.year IS NOT NULL")
        else:
            rows = q("SELECT DISTINCT q.year FROM questions q WHERE q.issue_slug=? AND q.year IS NOT NULL", (slug,))
        return sorted({r[0] for r in rows.fetchall()}, reverse=True)

    def all_issues():
        issues = [(r["slug"], r["name"], r["description"]) for r in q("SELECT slug, name, description FROM issues ORDER BY name")]
        other = q("SELECT COUNT(*) FROM questions WHERE issue_slug IS NULL").fetchone()[0]
        if other:
            issues.append(("other", "This race / other", "Lived experience and one-year visions."))
        return issues

    def year_issue_answers(slug: str, year: int, ballot_person_ids: set[int]):
        """Answers on this issue from people on this year's ballot — this year first, then earlier."""
        if slug == "other":
            issue_clause = "q.issue_slug IS NULL"
            params: list = []
        else:
            issue_clause = "q.issue_slug=?"
            params = [slug]
        rows = q(
            f"""SELECT a.id, p.id AS person_id, p.slug, p.full_name, a.stance, a.verbatim,
                       a.kind, q.prompt, q.year AS q_year, s.title AS source_title, s.url AS source_url
                FROM answers a
                JOIN people p ON p.id=a.person_id
                JOIN questions q ON q.id=a.question_id
                JOIN sources s ON s.id=a.source_id
                WHERE {issue_clause}
                ORDER BY p.sort_name, q.year DESC""",
            params,
        ).fetchall()
        return [
            r for r in rows
            if r["person_id"] in ballot_person_ids and (r["q_year"] or 0) <= year
        ]

    def questions_this_year(year: int):
        return q(
            """SELECT q.id, q.prompt, q.kind, COALESCE(q.issue_slug,'other') AS slug,
                      COALESCE(i.name,'This race / other') AS name
               FROM questions q
               LEFT JOIN issues i ON i.slug=q.issue_slug
               WHERE q.year=? AND q.id NOT IN (
                 SELECT a.question_id FROM answers a JOIN sources s ON s.id=a.source_id
                 WHERE a.kind='forum' AND s.kind='video')
               ORDER BY q.id""",
            (year,),
        ).fetchall()

    def write_year_page(year: int, as_home: bool = False) -> None:
        mayor = candidates_for(year, "mayor")
        council = candidates_for(year, "council")
        qs_year = questions_this_year(year)
        how = {
            2026: "You rank the candidates for mayor. For council, vote for up to five; the top five win. Four city measures are also on the ballot.",
            2025: "Four council seats, no mayor. Last odd-year municipal election.",
            2023: "First direct ranked-choice mayor, four council seats. 34,249 city ballots counted.",
            2021: "Five council seats, no directly elected mayor. Top four: four-year terms; fifth: two-year. 33,772 city ballots; 68,885 active city voters.",
            2019: "Six council seats after Jill Grano resigned (the vacancy added a two-year seat). No directly elected mayor. Top four: four-year; fifth and sixth: two-year. 34,971 city ballots; 68,749 active city voters.",
            2017: "Five council seats, no directly elected mayor. Top four: four-year terms; fifth: two-year. 31,765 city ballots; 72,574 active city voters.",
        }[year]
        jump = '<p class="jump">'
        if year != 2026:
            jump += '<a href="#outcome">Results</a>'
        if mayor:
            jump += '<a href="#mayor">Mayor</a>'
        if council:
            jump += '<a href="#council">Council</a>'
        jump += '<a href="#measures">Measures</a>'
        if qs_year:
            jump += '<a href="#questions">Questions</a>'
        if year == 2026:
            jump += '<a href="#money">Money</a>'
        jump += "</p>"
        bits = [
            f"<h1>{'Tuesday, November 3, 2026' if year == 2026 else str(year) + ' city election'}</h1>",
            f"<p class='lede'>{esc(how)}</p>",
            jump,
        ]
        if year != 2026:
            bits.append(archive_results(year))
        if mayor:
            bits.append(f"<h2 id='mayor'>Mayor · {len(mayor)} candidates</h2>")
            for r in mayor:
                bits.append(candidate_card(r, year, "mayor") if year == 2026 else archive_candidate(r, year))
        if council:
            seats = {2026: 5, 2025: 4, 2023: 4, 2021: 5, 2019: 6, 2017: 5}[year]
            bits.append(f"<h2 id='council'>City council · {seats} seats · {len(council)} candidates</h2>")
            if year == 2026:
                bits.append(
                    "<p class='note'>Five seats because Wallach resigned July 23 (before Aug 1) and Adams is running for mayor. "
                    "Not on this ballot (terms through 2028): Benjamin, Speer, Kaplan. "
                    "<a href='finance.html'>Money raised</a> · "
                    "<a href='print/index.html'>Print a sheet</a>.</p>"
                )
            if year == 2019:
                bits.append(
                    "<p class='note'>Six seats because Jill Grano resigned in January 2019. "
                    "Fifth place (Swetlik) and sixth place (Wallach) served two-year terms.</p>"
                )
            for r in council:
                bits.append(candidate_card(r, year, "council") if year == 2026 else archive_candidate(r, year))
            if year == 2026:
                money = q(
                    """SELECT p.full_name, p.slug, f.contributions, f.expenditures, f.matching_received, f.reported_on,
                              f.retrieved_on
                       FROM finance_snapshots f JOIN people p ON p.id=f.person_id
                       WHERE f.year=2026 ORDER BY f.contributions DESC, p.sort_name"""
                ).fetchall()
                if money:
                    bits.append("<h2 id='money'>Money so far</h2>")
                    bits.append(
                        f"<p class='note'>From city clerk filings, latest reports filed through {nice_iso(max(m['reported_on'] or '' for m in money))}; "
                        f"retrieved {nice_iso(money[0]['retrieved_on'])}. City races don't file with the state's TRACER system. "
                        "A $0 is what the campaign reported. "
                        "<a href='finance.html'>Donors, spending, and source</a>.</p>"
                    )
                    rows = ["<tr><th>Candidate</th><th class='num'>Raised</th><th class='num'>Spent</th><th class='num'>Matching</th></tr>"]
                    for m in money:
                        rows.append(
                            f"<tr><td><a href='{esc(person_href(m['slug']))}'>{esc(m['full_name'])}</a></td>"
                            f"<td class='num'>{dollars(m['contributions'])}</td>"
                            f"<td class='num'>{dollars(m['expenditures'])}</td>"
                            f"<td class='num'>{dollars(m['matching_received'])}</td></tr>"
                        )
                    bits.append(f"<table>{''.join(rows)}</table>")
        bits.append("<h2 id='measures'>City measures</h2>")
        bits.append(measure_cards(year))
        evs = forums_for_year(year)
        if evs:
            bits.append("<h2>Forums</h2>")
            bits.append("<ul>")
            for e in evs:
                rec = f' · <a href="{esc(e["recording_url"])}">recording</a>' if e["recording_url"] else ""
                bits.append(
                    f"<li>{esc(e['starts_on'])} {esc(e['name'])}{rec}</li>"
                )
            bits.append("</ul>")
            bits.append(f"<p class='note'><a href='forums.html'>Attendance and notes</a></p>")
        if qs_year:
            bits.append(f"<h2 id='questions'>Questions asked in {year}</h2>")
            bits.append(
                "<p class='note'>Questions candidates were asked this year. "
                "Answers from earlier years are on each person's page.</p>"
            )
            for qu in qs_year:
                bits.append(
                    f"<a class='choice' href='{esc(issue_href(qu['slug'], year))}'>{esc(qu['prompt'])}"
                    f"<span class='meta'>{esc(kind_label(qu['kind']))}</span></a>"
                )
        html_page = page(
            "2026 ballot details" if as_home else f"{year} election",
            "\n".join(bits),
            year=year,
        )
        (OUT / f"{year}.html").write_text(html_page, encoding="utf-8")

    for y in YEARS:
        write_year_page(y, as_home=(y == 2026))
    graph = Graph2026(con, OUT, page)
    forums = Forums2026(con, OUT, page)
    graph.measure_extra = forums.measure_section
    graph.write_home()
    graph.write_orgs()
    graph.write_measures()
    graph.write_civics(civics_markdown())
    forums.write_forum_pages()
    forums.write_compare()

    # ----- issues hub -----
    hub = [
        "<h1>Issues</h1>",
        "<p class='lede'>Questions candidates were asked, sorted by topic and year. A 2023 answer is about the 2023 question, so read it as that, not as a 2026 position. Open a person to see everything they have said.</p>",
        "<h2>Browse issues</h2>",
    ]
    for slug, name, desc in all_issues():
        ys = issue_years(slug)
        if not ys:
            continue
        pills = " ".join(f"<a class='pill' href='{esc(issue_href(slug, y))}'>{y}</a>" for y in ys)
        ongoing = "ongoing" if len(ys) > 1 else f"appeared {ys[0]}"
        hub.append(
            f"<div class='card'><h3><a href='{esc(issue_href(slug))}'>{esc(name)}</a></h3>"
            f"<div class='meta'>{esc(ongoing)} · {esc(desc or '')}</div>"
            f"<div class='chips' style='margin-top:0.4rem'>{pills}</div></div>"
        )
    (OUT / "issues.html").write_text(page("Issues", "\n".join(hub), learn="issues"), encoding="utf-8")

    def questions_for(slug: str, year: int):
        if slug == "other":
            return q(
                "SELECT id, prompt, kind FROM questions WHERE issue_slug IS NULL AND year=? ORDER BY id",
                (year,),
            ).fetchall()
        return q(
            "SELECT id, prompt, kind FROM questions WHERE issue_slug=? AND year=? ORDER BY id",
            (slug, year),
        ).fetchall()

    def answers_for_question(qid: int, person_ids: set[int] | None = None):
        # Ballot order for the question's own year (mayor first, then council), else alphabetical.
        rows = q(
            """SELECT a.id, p.id AS person_id, p.slug, p.full_name, a.stance, a.verbatim, a.notes,
                      s.title AS source_title, s.url AS source_url
               FROM answers a
               JOIN people p ON p.id=a.person_id
               JOIN sources s ON s.id=a.source_id
               JOIN questions qq ON qq.id=a.question_id
               LEFT JOIN (SELECT c.person_id, e.year, MIN(CASE o.slug WHEN 'mayor' THEN 0 ELSE 100 END
                                  + c.ballot_position) AS bpos
                          FROM candidacies c JOIN races r ON r.id=c.race_id
                          JOIN elections e ON e.id=r.election_id JOIN offices o ON o.id=r.office_id
                          WHERE c.ballot_position IS NOT NULL GROUP BY c.person_id, e.year) b
                 ON b.person_id=p.id AND b.year=qq.year
               WHERE a.question_id=?
               ORDER BY b.bpos IS NULL, b.bpos, p.sort_name""",
            (qid,),
        ).fetchall()
        if person_ids is None:
            return rows
        return [r for r in rows if r["person_id"] in person_ids]

    for slug, name, desc in all_issues():
        ys = issue_years(slug)
        # hub page for the issue
        bits = [
            f"<p class='crumb'><a href='../issues.html'>Issues</a></p>",
            f"<h1>{esc(name)}</h1>",
        ]
        if desc:
            bits.append(f"<p class='lede'>{esc(desc)}</p>")
        if len(ys) > 1:
            bits.append(f"<p>Asked in {', '.join(str(y) for y in ys)}. The wording changes from year to year.</p>")
        elif ys:
            bits.append(f"<p>On the record in {ys[0]} so far.</p>")
        bits.append(
            "<p>This issue in: "
            + " ".join(f"<a class='pill' href='{esc(slug)}-{y}.html'>{y}</a>" for y in ys)
            + "</p>"
        )
        (OUT / "issues" / f"{slug}.html").write_text(
            page(name, "\n".join(bits), prefix="../"), encoding="utf-8"
        )

        written_year_pages: set[str] = set()
        for year in YEARS:
            ballot = list(candidates_for(year, "mayor")) + list(candidates_for(year, "council"))
            ballot_ids = {r["person_id"] for r in ballot}
            qs_this = questions_for(slug, year)
            if not qs_this:
                continue
            year_pills = "".join(
                f"<a class='pill{' on' if y == year else ''}' href='{esc(slug)}-{y}.html'>{y}</a> "
                for y in issue_years(slug) or [year]
            )
            body = [
                f"<p class='crumb'><a href='../issues.html'>Issues</a> · <a href='{esc(slug)}.html'>{esc(name)}</a></p>",
                f"<h1>{esc(qs_this[0]['prompt'] if len(qs_this) == 1 else name + ' · ' + str(year))}</h1>",
                f"<p class='note'>{year} · {esc(name)}. This issue in: {year_pills}</p>",
                f"<p>People on the {year} ballot who answered this cycle’s question. "
                f"Answers from earlier years stay on those years' pages.</p>",
            ]
            for qu in qs_this:
                ans = answers_for_question(qu["id"], ballot_ids)
                if len(qs_this) > 1:
                    body.append(f"<h2>{esc(qu['prompt'])}</h2>")
                else:
                    body.append("<h2>Candidate answers</h2>")
                body.append(f"<p class='note'>{esc(kind_label(qu['kind']))}</p>")
                if ans:
                    src = ans[0]
                    body.append(f"<p class='note'><a href='{esc(src['source_url'])}'>{esc(src['source_title'])}</a></p>")
                    groups = [("yes", "Yes"), ("no", "No"), ("mixed", "Mixed"), (None, None)]
                    used_ids = set()
                    for key, label in groups:
                        chunk = [a for a in ans if (a["stance"] if a["stance"] in ("yes", "no", "mixed") else None) == key]
                        if not chunk:
                            continue
                        if label and any(a["stance"] in ("yes", "no", "mixed") for a in ans):
                            body.append(f"<h2>{esc(label)}</h2>")
                        for a in chunk:
                            used_ids.add(a["id"])
                            body.append(
                                f"<div class='card'><h3><a href='{esc(person_href(a['slug'], '../'))}'>{esc(a['full_name'])}</a></h3>"
                                f"{forums.issue_answer(a['id']) or render_answer(a['verbatim'], a['stance'], a['notes'])}"
                                f"</div>"
                            )
                    silent = [r for r in ballot if r["person_id"] not in {a["person_id"] for a in ans}]
                    if silent:
                        body.append(
                            f"<p class='note'>{len(silent)} on this ballot are not in the source for this question. "
                            f"Silence is not a no.</p>"
                        )
                else:
                    reported = graph.reported_lines_for_question(qu["id"], "../")
                    body.append(reported or f"<p class='empty'>No one on the {year} ballot answered this prompt.</p>")
            dest = OUT / "issues" / f"{slug}-{year}.html"
            dest.write_text(page(f"{name} {year}", "\n".join(body), prefix="../", year=year), encoding="utf-8")
            written_year_pages.add(dest.name)
        # drop leftover year-pages that were the old “prior answers bleed onto this year” files
        for leftover in (OUT / "issues").glob(f"{slug}-20*.html"):
            if leftover.name not in written_year_pages:
                leftover.unlink()

    # rebuild issue hub pills now that slices exist — already linked

    # ----- people index -----
    people = q("SELECT * FROM people ORDER BY sort_name").fetchall()
    ballot_2026 = [r["person_id"] for r in candidates_for(2026, "mayor") + candidates_for(2026, "council")]
    on_2026 = set(ballot_2026)
    # 2026 candidates first, in ballot order (mayor, then council); everyone else alphabetical.
    people = sorted(people, key=lambda p: ballot_2026.index(p["id"]) if p["id"] in on_2026 else len(ballot_2026))
    plist = [
        "<h1>People</h1>",
        "<p class='lede'>Everyone who has run for Boulder council or mayor since 2017, plus 2026 endorsers. Open a name to see what they have said, newest first.</p>",
        "<h2>On the 2026 ballot</h2>",
    ]
    later = ["<h2>Earlier cycles only</h2>"]
    for p in people:
        years = q(
            """SELECT e.year, o.slug AS office, c.status
               FROM candidacies c JOIN races r ON r.id=c.race_id
               JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id
               WHERE c.person_id=? ORDER BY e.year DESC""",
            (p["id"],),
        ).fetchall()
        ytxt = ", ".join(f"{y['year']} {y['office']}" for y in years)
        if not ytxt:
            t = q("SELECT title FROM person_titles WHERE person_id=?", (p["id"],)).fetchone()
            ytxt = f"2026 endorser · {t[0]}" if t else "2026 endorser"
        n_ans = q("SELECT COUNT(*) FROM answers WHERE person_id=?", (p["id"],)).fetchone()[0]
        extra = f" · {plural(n_ans, 'answer')}" if n_ans else ""
        snap = finance_for(p["id"], 2026) if p["id"] in on_2026 else None
        if snap:
            extra += f" · raised {dollars(snap['contributions'])}"
        li = f"<div class='card'><h3><a href='{esc(person_href(p['slug']))}'>{esc(p['full_name'])}</a></h3><div class='meta'>{esc(ytxt)}{extra}</div></div>"
        if p["id"] in on_2026:
            plist.append(li)
        else:
            later.append(li)
    plist.extend(later)
    (OUT / "people.html").write_text(page("People", "\n".join(plist), learn="people"), encoding="utf-8")

    # ----- person dossiers -----
    for p in people:
        cands = q(
            """SELECT c.*, e.year, o.name AS office, o.slug AS office_slug
               FROM candidacies c
               JOIN races r ON r.id=c.race_id
               JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id
               WHERE c.person_id=?
               ORDER BY e.year DESC""",
            (p["id"],),
        ).fetchall()
        answers = q(
            """SELECT a.*, q.prompt, q.year AS q_year, q.kind AS q_kind,
                      COALESCE(q.issue_slug,'other') AS issue_slug,
                      COALESCE(i.name,'This race / other') AS issue_name,
                      s.title AS source_title, s.url AS source_url
               FROM answers a
               JOIN questions q ON q.id=a.question_id
               JOIN sources s ON s.id=a.source_id
               LEFT JOIN issues i ON i.slug=q.issue_slug
               WHERE a.person_id=? AND NOT (a.kind='forum' AND s.kind='video')
               ORDER BY q.year DESC, q.id""",
            (p["id"],),
        ).fetchall()
        appearances = q(
            """SELECT e.name, e.starts_on, e.recording_url, a.attended
               FROM event_appearances a JOIN events e ON e.id=a.event_id
               WHERE a.person_id=? ORDER BY e.starts_on DESC""",
            (p["id"],),
        ).fetchall()
        res = q(
            """SELECT res.votes, res.elected, res.round, e.year, o.slug AS office
               FROM results res
               JOIN candidacies c ON c.id=res.candidacy_id
               JOIN races r ON r.id=c.race_id
               JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id
               WHERE c.person_id=?
               ORDER BY e.year, res.round""",
            (p["id"],),
        ).fetchall()

        cand26 = next((c for c in cands if c["year"] == 2026), None)
        bits = []
        if not cand26:
            bits.append(f"<p class='crumb'><a href='../people.html'>People</a></p>")
            bits.append(f"<h1>{esc(p['full_name'])}</h1>")
            if p["notes"]:
                bits.append(f"<p class='lede'>{esc(plain(p['notes']))}</p>")
        history: list[str] = []

        # timeline
        history.append("<h2 id='campaigns'>Campaigns</h2>")
        tbody = ["<tr><th>Year</th><th>Office</th><th>Outcome</th></tr>"]
        for c in cands:
            flags = []
            if c["is_incumbent"]:
                flags.append("incumbent")
            if c["matching_funds"]:
                flags.append("matching funds")
            extra = f" ({', '.join(flags)})" if flags else ""
            outcome = human_label(c["status"])
            rmatch = [r for r in res if r["year"] == c["year"] and r["office"] == c["office_slug"]]
            if rmatch:
                last = rmatch[-1]
                outcome = f"{last['votes']:,} votes" + (" · elected" if last["elected"] else "")
            site = f" · <a href='{esc(c['campaign_url'])}'>campaign</a>" if c["campaign_url"] else ""
            tbody.append(
                f"<tr><td><a href='../{c['year']}.html'>{c['year']}</a></td>"
                f"<td>{esc(c['office'])}{extra}{site}</td><td>{esc(outcome)}</td></tr>"
            )
        history.append(f"<table>{''.join(tbody)}</table>")

        snaps = q(
            "SELECT * FROM finance_snapshots WHERE person_id=? ORDER BY year DESC",
            (p["id"],),
        ).fetchall()
        if snaps and not cand26:
            snap0 = snaps[0]
            history.append(
                f"<p class='note'>{snap0['year']}: raised {dollars(snap0['contributions'])} · "
                f"spent {dollars(snap0['expenditures'])} · "
                f"matching {dollars(snap0['matching_received'])}. "
                f"<a href='#money'>Donors and spending</a>.</p>"
            )

        if not cand26:
            bits.extend(history)
        bits.append(graph.person_sections(p["id"]))
        bits.append(forums.person_section(p["id"]))

        if answers:
            bits.append("<h2 id='questionnaires'>Questionnaire answers by year</h2>")
            bits.append(
                "<p class='note'>Newest first. A yes or no answers only the question on that card, not the whole topic.</p>"
            )
            current_year = None
            for a in answers:
                if a["q_year"] != current_year:
                    bits.append(f"<h3>{a['q_year']}</h3>")
                    current_year = a["q_year"]
                bits.append(f"<div class='card' id='q-{a['id']}'>")
                bits.append(
                    f"<div class='meta'><a href='../{a['q_year']}.html'>{a['q_year']}</a> · "
                    f"{esc(kind_label(a['q_kind']))} · {esc(a['issue_name'])}</div>"
                )
                bits.append(f"<h4>{esc(a['prompt'])}</h4>")
                bits.append(render_answer(a["verbatim"], a["stance"], a["notes"]))
                bits.append(f"<p class='note'>Source: <a href='{esc(a['source_url'])}'>{esc(a['source_title'])}</a></p>")
                bits.append("</div>")
        elif not cands:
            pass
        else:
            bits.append("<p class='empty'>No earlier questionnaire answers on file.</p>")

        if snaps:
            bits.append("<h2 id='money'>Money</h2>")
            for snap in snaps:
                n_donors = q(
                    """SELECT COUNT(*) FROM finance_line_items
                       WHERE snapshot_id=? AND direction='contribution'""",
                    (snap["id"],),
                ).fetchone()[0]
                n_exp = q(
                    """SELECT COUNT(*) FROM finance_line_items
                       WHERE snapshot_id=? AND direction='expenditure'""",
                    (snap["id"],),
                ).fetchone()[0]
                bits.append(money_stats(snap))
                bits.append(
                    f"<p class='note'>{snap['year']} · {esc(snap['committee_name'])} · "
                    f"{esc(report_line(snap))}.</p>"
                )
                if snap["notes"]:
                    bits.append(f"<p class='note'>{esc(plain(snap['notes']))}</p>")
                bits.append(
                    f"<p class='note'>{n_donors} contribution line{'' if n_donors == 1 else 's'}, "
                    f"{n_exp} expenditure{'' if n_exp == 1 else 's'}. City clerk, not TRACER. "
                    f"<a href='{esc(snap['reports_url'] or '../finance.html')}'>Clerk statements</a> · "
                    f"<a href='../finance.html'>Everyone</a>.</p>"
                )
                contribs = q(
                    """SELECT display_name, item_type, occurred_on, amount, from_candidate
                       FROM finance_line_items
                       WHERE snapshot_id=? AND direction='contribution'
                       ORDER BY amount DESC, last_name, first_name""",
                    (snap["id"],),
                ).fetchall()
                if contribs:
                    bits.append(f"<details class='fold'><summary>Who gave: all {len(contribs)} contribution lines</summary>")
                    body = ["<tr><th>Name</th><th>Type</th><th>Date</th><th class='num'>Amount</th></tr>"]
                    for item in contribs:
                        label = esc(item["display_name"])
                        if item["from_candidate"]:
                            label += " <span class='note'>(from candidate)</span>"
                        body.append(
                            f"<tr><td>{label}</td><td>{esc(item['item_type'] or '')}</td>"
                            f"<td>{esc(item['occurred_on'] or '—')}</td>"
                            f"<td class='num'>{dollars(item['amount'])}</td></tr>"
                        )
                    bits.append(f"<table>{''.join(body)}</table></details>")
                spends = q(
                    """SELECT display_name, purpose, occurred_on, amount
                       FROM finance_line_items
                       WHERE snapshot_id=? AND direction='expenditure'
                       ORDER BY amount DESC, last_name""",
                    (snap["id"],),
                ).fetchall()
                if spends:
                    bits.append(f"<details class='fold'><summary>Spent on: all {len(spends)} expenditure lines</summary>")
                    body = ["<tr><th>Payee</th><th>Purpose</th><th>Date</th><th class='num'>Amount</th></tr>"]
                    for item in spends:
                        body.append(
                            f"<tr><td>{esc(item['display_name'])}</td><td>{esc(item['purpose'] or '')}</td>"
                            f"<td>{esc(item['occurred_on'] or '—')}</td>"
                            f"<td class='num'>{dollars(item['amount'])}</td></tr>"
                        )
                    bits.append(f"<table>{''.join(body)}</table></details>")

        if cand26:
            bits.extend(history)

        if appearances:
            bits.append("<h2 id='attendance'>Forum attendance</h2><ul>")
            for a in appearances:
                flag = "attended" if a["attended"] == 1 else "did not attend" if a["attended"] == 0 else "unknown"
                rec = f' · <a href="{esc(a["recording_url"])}">recording</a>' if a["recording_url"] else ""
                bits.append(f"<li>{esc(a['starts_on'])} {esc(a['name'])} — {flag}{rec}</li>")
            bits.append("</ul>")

        latest = cands[0]["year"] if cands else None
        nav_key = None
        if cand26:
            rest = "\n".join(bits)
            body_html = graph.candidate_summary(p["id"], rest, p["slug"]) + panelize(rest)
            nav_key = "mayor" if cand26["office_slug"] == "mayor" else "council"
        else:
            body_html = "\n".join(bits)
        (OUT / "people" / f"{p['slug']}.html").write_text(
            page(p["full_name"], body_html, prefix="../", year=latest if not cand26 else 2026, current=nav_key),
            encoding="utf-8",
        )

    # forums / measures / sources / about remain available, not in primary nav
    from build_upcoming import upcoming_html
    ev_html = ["<h1>Forums</h1>", "<p>Every candidate forum we know of, with recordings. We list who attended only when a published source says so.</p>",
               upcoming_html(), forums.forum_index_html(), "<h2>Calendar</h2>"]
    all_events = q(
        """SELECT e.*, o.name AS host FROM events e
           LEFT JOIN organizations o ON o.id=e.host_org_id ORDER BY e.starts_on DESC"""
    ).fetchall()
    cur_y = None
    for e in all_events:
        y = int(str(e["starts_on"])[:4])
        if y != cur_y:
            ev_html.append(f"<h2>{y}</h2>")
            cur_y = y
        rec = f' · <a href="{esc(e["recording_url"])}">recording</a>' if e["recording_url"] else ""
        ev_html.append(f"<h3>{esc(e['name'])}</h3>")
        ev_html.append(f"<p>{esc(e['starts_on'])} · {esc(e['venue'] or 'venue not recorded')} · {esc(e['host'] or '')}{rec}</p>")
        if e["notes"]:
            ev_html.append(f"<p class='note'>{esc(plain(e['notes']))}</p>")
        apps = q(
            """SELECT p.full_name, p.slug, a.attended FROM event_appearances a
               JOIN people p ON p.id=a.person_id
               LEFT JOIN candidacies c ON c.id=a.candidacy_id
               LEFT JOIN races r ON r.id=c.race_id LEFT JOIN offices o ON o.id=r.office_id
               WHERE a.event_id=?
               ORDER BY c.ballot_position IS NULL, o.slug != 'mayor', c.ballot_position, p.sort_name""",
            (e["id"],),
        ).fetchall()
        if apps:
            ev_html.append("<ul>")
            for a in apps:
                flag = "attended" if a["attended"] == 1 else "did not attend" if a["attended"] == 0 else "unknown"
                ev_html.append(f"<li><a href='{esc(person_href(a['slug']))}'>{esc(a['full_name'])}</a> — {flag}</li>")
            ev_html.append("</ul>")
    (OUT / "forums.html").write_text(page("Forums", "\n".join(ev_html), current="forums", learn="forums"), encoding="utf-8")

    meas_html = ["<h1>City measures</h1>"]
    for year in YEARS:
        meas_html.append(f"<h2>{year}</h2>")
        meas_html.append(measure_cards(year))
    (OUT / "measures.html").write_text(page("Measures", "\n".join(meas_html), current="measures"), encoding="utf-8")

    sources = q(
        """SELECT s.*, o.name AS org FROM sources s
           LEFT JOIN organizations o ON o.id=s.org_id
           ORDER BY s.year DESC, s.published_on DESC, s.title"""
    ).fetchall()
    src_rows = ["<tr><th>Year</th><th>Kind</th><th>Source</th></tr>"]
    for s in sources:
        src_rows.append(
            f"<tr><td>{s['year'] or ''}</td><td>{esc(human_label(s['kind']))}</td>"
            f"<td><a href='{esc(s['url'])}'>{esc(s['title'])}</a></td></tr>"
        )
    (OUT / "sources.html").write_text(
        page("Sources", f"<h1>Sources</h1><p>Every document this guide cites. Quotes appear on the people and issue pages.</p><table>{''.join(src_rows)}</table>", learn="sources"),
        encoding="utf-8",
    )

    qn_html = [
        "<h1>Questionnaires</h1>",
        "<p class='lede'>Written questionnaires candidates filled out. We reprint answers word for word from Boulder Reporting Lab and Boulder Beat. The rest are linked.</p>",
        "<p>The Chamber does send questions every cycle; the 2025 extended-response PDF is the one we have as a file. PLAN used a questionnaire for 2025 endorsements and did not publish the dump on the endorsement page. Open Boulder published 2025 PDFs for eight of eleven candidates. Better Boulder co-hosted the 2025 VOTES! forum with PLAN and Open Boulder (first year of that collaboration).</p>",
    ]
    qn_rows = q(
        """SELECT s.year, s.title, s.url, s.kind, s.notes, o.name AS org
           FROM sources s LEFT JOIN organizations o ON o.id=s.org_id
           WHERE s.kind='questionnaire'
           ORDER BY s.year DESC, s.title"""
    ).fetchall()
    qn_html.append("<table><tr><th>Year</th><th>Source</th></tr>")
    for s in qn_rows:
        org = f"{esc(s['org'])} · " if s["org"] else ""
        note = f"<div class='meta'>{esc(plain(s['notes']))}</div>" if s["notes"] else ""
        qn_html.append(
            f"<tr><td>{s['year'] or ''}</td><td>{org}<a href='{esc(s['url'])}'>{esc(s['title'])}</a>{note}</td></tr>"
        )
    qn_html.append("</table>")
    qn_html.append(
        "<p class='note'>Forum videos, including YouTube, live on the <a href='forums.html'>forums</a> page. "
        "Spoken quotes come only from recordings, with a link to the moment.</p>"
    )
    (OUT / "questionnaires.html").write_text(page("Questionnaires", "\n".join(qn_html), learn="questionnaires"), encoding="utf-8")

    # ----- print packet: a short sheet per 2026 candidate; answers never folded -----
    def print_sheet(row, office: str) -> str:
        answers = q(
            """SELECT a.verbatim, a.stance, a.notes, q.prompt, q.year AS q_year, q.kind AS q_kind,
                      COALESCE(q.issue_slug,'other') AS issue_slug,
                      COALESCE(i.name,'This race / other') AS issue_name,
                      s.title AS source_title, s.url AS source_url
               FROM answers a
               JOIN questions q ON q.id=a.question_id
               JOIN sources s ON s.id=a.source_id
               LEFT JOIN issues i ON i.slug=q.issue_slug
               WHERE a.person_id=? AND NOT (a.kind='forum' AND s.kind='video')
               ORDER BY q.year DESC, a.id""",
            (row["person_id"],),
        ).fetchall()
        cands = q(
            """SELECT c.*, e.year, o.name AS office
               FROM candidacies c
               JOIN races r ON r.id=c.race_id
               JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id
               WHERE c.person_id=? ORDER BY e.year DESC""",
            (row["person_id"],),
        ).fetchall()
        flags = []
        if row["is_incumbent"]:
            flags.append("incumbent")
        if row["matching_funds"]:
            flags.append("matching funds")
        flag_txt = f" · {esc(', '.join(flags))}" if flags else ""
        site = (
            f"<p><a href='{esc(row['campaign_url'])}'>{esc(row['campaign_url'])}</a></p>"
            if row["campaign_url"]
            else ""
        )
        bits = [
            f"<p class='print-hint'>File → Print. Usually one or two pages. Every answer prints in full.</p>",
            f"<h1>{esc(row['full_name'])}</h1>",
            f"<p class='lede'>2026 {esc(office)}{flag_txt}</p>",
            site,
            "<h2>Campaigns</h2>",
        ]
        tbody = ["<tr><th>Year</th><th>Office</th><th>Outcome</th></tr>"]
        for c in cands:
            tbody.append(
                f"<tr><td>{c['year']}</td><td>{esc(c['office'])}</td><td>{esc(human_label(c['status']))}</td></tr>"
            )
        bits.append(f"<table>{''.join(tbody)}</table>")
        if answers:
            bits.append("<h2>What they have said</h2>")
            n = 0
            for a in answers:
                bits.append(
                    f"<div class='card'><div class='meta'>{a['q_year']} · {esc(a['issue_name'])}</div>"
                    f"<h3>{esc(a['prompt'])}</h3>{render_answer(a['verbatim'], a['stance'], a['notes'], fold=False)}"
                    f"<p class='note'>Source: <a href='{esc(a['source_url'])}'>{esc(a['source_title'])}</a></p></div>"
                )
                n += 1
                if n >= 4:
                    break
        else:
            bits.append('<p class="empty">No sourced answers on file yet this cycle.</p>')
        money_flag = "yes" if row["matching_funds"] else "not marked on the clerk candidate list"
        snap = finance_for(row["person_id"], 2026)
        bits.append("<h2>Money</h2>")
        if snap:
            n_donors = q(
                """SELECT COUNT(*) FROM finance_line_items
                   WHERE snapshot_id=? AND direction='contribution'""",
                (snap["id"],),
            ).fetchone()[0]
            bits.append(
                f"<p>Raised {dollars(snap['contributions'])} · spent {dollars(snap['expenditures'])} · "
                f"matching received {dollars(snap['matching_received'])} · "
                f"{n_donors} contribution line{'' if n_donors == 1 else 's'} "
                f"({esc(snap['committee_name'])}; {esc(report_line(snap))}). "
                f"Clerk matching-funds flag: {money_flag}. Not TRACER.</p>"
            )
            if snap["notes"]:
                bits.append(f"<p class='note'>{esc(plain(snap['notes']))}</p>")
        else:
            bits.append(
                f"<p>Matching funds: {money_flag}. Filings: "
                f"<a href='https://webapps.bouldercolorado.gov/election/committeeFilings.php'>city clerk app</a>.</p>"
            )
        bits.append(
            f"<p class='note'><a href='../people/{esc(row['slug'])}.html'>Full dossier</a> · "
            f"<a href='../2026.html'>2026 ballot</a></p>"
        )
        return page(f"Print · {row['full_name']}", "\n".join(bits), prefix="../", year=2026)

    print_index = [
        "<h1>Print packet</h1>",
        "<p class='lede'>One printable sheet per 2026 candidate, with past races, up to four answers in full, and money from city filings. Most run one or two pages.</p>",
        "<p class='print-hint'>Open a sheet, then File → Print. No JavaScript.</p>",
        "<h2>Mayor</h2>",
    ]
    for r in candidates_for(2026, "mayor"):
        (OUT / "print" / f"{r['slug']}.html").write_text(print_sheet(r, "mayor"), encoding="utf-8")
        flags = []
        if r["is_incumbent"]:
            flags.append("incumbent")
        if r["matching_funds"]:
            flags.append("matching funds")
        extra = f" · {esc(', '.join(flags))}" if flags else ""
        snap = finance_for(r["person_id"], 2026)
        raised = f" · raised {dollars(snap['contributions'])}" if snap else ""
        print_index.append(
            f"<div class='card'><h3><a href='{esc(r['slug'])}.html'>{esc(r['full_name'])}</a>{extra}</h3>"
            f"<div class='meta'><a href='{esc(r['slug'])}.html'>print sheet</a>{raised}</div></div>"
        )
    print_index.append("<h2>City council</h2>")
    for r in candidates_for(2026, "council"):
        (OUT / "print" / f"{r['slug']}.html").write_text(print_sheet(r, "city council"), encoding="utf-8")
        flags = []
        if r["is_incumbent"]:
            flags.append("incumbent")
        if r["matching_funds"]:
            flags.append("matching funds")
        extra = f" · {esc(', '.join(flags))}" if flags else ""
        snap = finance_for(r["person_id"], 2026)
        raised = f" · raised {dollars(snap['contributions'])}" if snap else ""
        print_index.append(
            f"<div class='card'><h3><a href='{esc(r['slug'])}.html'>{esc(r['full_name'])}</a>{extra}</h3>"
            f"<div class='meta'><a href='{esc(r['slug'])}.html'>print sheet</a>{raised}</div></div>"
        )
    (OUT / "print" / "index.html").write_text(
        page("Print packet", "\n".join(print_index), prefix="../", year=2026),
        encoding="utf-8",
    )

    # find.html (the "Questions" hub) is retired; the 2026 guide is the entry point.
    stale = OUT / "find.html"
    if stale.exists():
        stale.unlink()
    quiz_gone = page(
        "Moved",
        "<h1>This page has moved</h1>"
        "<p>The 2026 guide starts on the <a href='../index.html'>home page</a>. "
        "The $400 million rec and safety bond is <a href='../measures/2026-2k.html'>ballot measure 2K</a>.</p>",
        prefix="../",
        year=2026,
    )
    for stub in ("bond-yes.html", "bond-no.html", "bond.html"):
        (OUT / "find" / stub).write_text(quiz_gone, encoding="utf-8")

    fin_rows = q(
        """SELECT f.id, p.full_name, p.slug, f.committee_name, f.committee_kind, f.contributions,
                  f.expenditures, f.matching_received, f.cash_on_hand, f.reported_on, f.notes,
                  f.report_label, f.report_url, f.retrieved_on,
                  f.reports_url, f.person_id, s.url AS source_url, s.title AS source_title
           FROM finance_snapshots f
           LEFT JOIN people p ON p.id=f.person_id
           JOIN sources s ON s.id=f.source_id
           WHERE f.year=2026
           ORDER BY f.contributions DESC, COALESCE(p.sort_name, f.committee_name)"""
    ).fetchall()
    fin_retrieved = next((r["retrieved_on"] for r in fin_rows if r["retrieved_on"]), None)
    fin_latest = max((r["reported_on"] or "" for r in fin_rows), default="")
    fin_html = [
        "<h1>Campaign money — 2026</h1>",
        f"<p class='lede'>From City of Boulder clerk filings, retrieved {nice_iso(fin_retrieved)}. "
        f"Figures come from each committee's latest report; the newest was filed {nice_iso(fin_latest)}. "
        "City races don't report to the state's TRACER system. A $0 means the campaign filed a zero.</p>",
        "<p class='note'>Next city filing dates: Oct. 6, Oct. 13, Oct. 20 and Oct. 29, 2026, then Dec. 3 "
        "(<a href='https://bouldercolorado.gov/election-guidelines'>city election guidelines</a>). "
        "Totals here change only when we pull the new reports.</p>",
        "<p class='note'>Past-year dollars: the live app only serves 2026. Historical filings sit in the city’s "
        "<a href='https://documents.bouldercolorado.gov/WebLink/Browse.aspx?id=59131'>Laserfiche archive</a> "
        "(needs cookies and JavaScript). We couldn't read that folder, so past years have no dollar figures here. The asterisks on the clerk's candidate list mark who signed up for matching funds; the Matching column here is money actually received.</p>",
    ]
    candidates = [r for r in fin_rows if r["committee_kind"] == "official_candidate" and r["person_id"]]
    cand_ids = {r["id"] for r in candidates}
    other = [r for r in fin_rows if r["id"] not in cand_ids]
    if candidates:
        fin_html.append(f"<p class='note'><a href='{esc(candidates[0]['source_url'])}'>{esc(candidates[0]['source_title'])}</a></p>")
        body = [
            "<tr><th>Candidate</th><th>Committee</th><th class='num'>Raised</th>"
            "<th class='num'>Spent</th><th class='num'>Matching</th>"
            "<th class='num'>Donors</th><th>Latest report</th></tr>"
        ]
        for r in candidates:
            n_donors = q(
                """SELECT COUNT(*) FROM finance_line_items
                   WHERE snapshot_id=? AND direction='contribution'""",
                (r["id"],),
            ).fetchone()[0]
            body.append(
                f"<tr><td><a href='{esc(person_href(r['slug']))}'>{esc(r['full_name'])}</a></td>"
                f"<td>{esc(r['committee_name'])}</td>"
                f"<td class='num'>{dollars(r['contributions'])}</td>"
                f"<td class='num'>{dollars(r['expenditures'])}</td>"
                f"<td class='num'>{dollars(r['matching_received'])}</td>"
                f"<td class='num'>{n_donors}</td>"
                f"<td>{report_cell(r)}</td></tr>"
            )
        fin_html.append(f"<table>{''.join(body)}</table>")
        noted = [r for r in candidates if r["notes"]]
        if noted:
            fin_html.append("<ul class='note'>")
            for r in noted:
                fin_html.append(f"<li><a href='{esc(person_href(r['slug']))}'>{esc(r['full_name'])}</a> — {esc(plain(r['notes']))}</li>")
            fin_html.append("</ul>")

    cross = q(
        """SELECT giver.full_name AS giver, giver.slug AS giver_slug,
                  recv.full_name AS recv, recv.slug AS recv_slug,
                  li.amount, li.occurred_on, li.item_type
           FROM finance_line_items li
           JOIN people giver ON giver.id=li.donor_person_id
           JOIN finance_snapshots fs ON fs.id=li.snapshot_id
           JOIN people recv ON recv.id=fs.person_id
           WHERE li.direction='contribution' AND li.year=2026
             AND li.donor_person_id IS NOT NULL
             AND li.donor_person_id != fs.person_id
           ORDER BY recv.sort_name, giver.sort_name"""
    ).fetchall()
    if cross:
        fin_html.append("<h2>People in this database who gave to a 2026 candidate</h2>")
        fin_html.append(
            "<p class='note'>Only donors who are also candidates or officeholders in this guide. "
            "Every other donor is listed on the candidate's page.</p>"
        )
        body = ["<tr><th>Gave</th><th>To</th><th>Type</th><th>Date</th><th class='num'>Amount</th></tr>"]
        for r in cross:
            body.append(
                f"<tr><td><a href='{esc(person_href(r['giver_slug']))}'>{esc(r['giver'])}</a></td>"
                f"<td><a href='{esc(person_href(r['recv_slug']))}'>{esc(r['recv'])}</a></td>"
                f"<td>{esc(r['item_type'] or '')}</td>"
                f"<td>{esc(r['occurred_on'] or '—')}</td>"
                f"<td class='num'>{dollars(r['amount'])}</td></tr>"
            )
        fin_html.append(f"<table>{''.join(body)}</table>")

    if other:
        fin_html.append("<h2>Other 2026 committees</h2>")
        fin_html.append(
            "<p class='note'>Ballot-measure, unofficial and independent-expenditure committees, plus any official committee whose candidate is not on the certified clerk list.</p>"
        )
        body = ["<tr><th>Committee</th><th>Kind</th><th class='num'>Raised</th><th class='num'>Spent</th><th>Latest report</th></tr>"]
        for r in other:
            kind = human_label(r["committee_kind"])
            body.append(
                f"<tr><td>{esc(r['committee_name'])}</td><td>{esc(kind)}</td>"
                f"<td class='num'>{dollars(r['contributions'])}</td>"
                f"<td class='num'>{dollars(r['expenditures'])}</td>"
                f"<td>{report_cell(r)}</td></tr>"
            )
        fin_html.append(f"<table>{''.join(body)}</table>")
    fin_html.append("<p><a href='https://webapps.bouldercolorado.gov/election/committeeFilings.php'>Open the clerk app</a> to read each statement.</p>")
    (OUT / "finance.html").write_text(page("Campaign money", "\n".join(fin_html), year=2026, learn="finance"), encoding="utf-8")

    learn = [
        "<p class='eyebrow'>Learn</p>",
        "<h1>Background for the 2026 city ballot</h1>",
        "<p class='lede'>How city government works, who is behind the campaigns, and where our facts come from.</p>",
    ]
    for title, items in LEARN_GROUPS:
        learn.append(f"<section class='learn-group'><h2>{esc(title)}</h2><div class='link-grid'>")
        for _key, href, label, blurb in items:
            learn.append(f"<a class='choice' href='{href}'><strong>{esc(label)}</strong><span class='meta'>{esc(blurb)}</span></a>")
        learn.append("</div></section>")
    learn.append("<section class='learn-group'><h2>Past elections</h2>"
                 "<p>Results, candidates and answers from every City of Boulder election since 2017.</p><p class='chips'>"
                 + "".join(f"<a class='pill' href='{y}.html'>{y}</a>" for y in ARCHIVE_YEARS) + "</p></section>")
    from build_llm import AI_CAUTION, AI_SHORT, AI_PROMPT
    learn.append(
        "<section class='panel ask-ai' id='ask-ai'><h2>Ask an AI</h2>"
        "<p>Using ChatGPT, Claude or another assistant? Tell it:</p>"
        f"<p class='prompt-box'>{esc(AI_SHORT)}</p>"
        "<p>Or paste this longer prompt:</p>"
        f"<p class='prompt-box'>{esc(AI_PROMPT)}</p>"
        "<p>The assistant can read the whole guide from one file, "
        "<a href='llms-full.txt'>llms-full.txt</a>, or the <a href='api/index.html'>JSON data</a>. "
        "That file asks it to stay nonpartisan and cite a source for every claim.</p>"
        f"<p class='note'>{esc(AI_CAUTION)}</p></section>")
    (OUT / "learn.html").write_text(page("Learn", "\n".join(learn), current="learn"), encoding="utf-8")

    about = """
    <h1>About Boulder Votes</h1>
    <p>Boulder Votes is a guide to City of Boulder elections, written with older voters in mind. It covers the mayor and city council races and the city ballot measures.</p>
    <h2>What we won't do</h2>
    <p>We don't endorse, rank or score candidates or measures, and we don't tell you how to vote. We treat every candidate the same way and list them in ballot order.</p>
    <h2>Where the facts come from</h2>
    <p>Every quote, endorsement and dollar figure links to the page it came from. If we can't source a number, we leave it out. Quotes are word for word. Forum quotes come from automatic transcripts, so each one links to that moment in the recording.</p>
    <p>Each endorsement says where it comes from: the endorser's own statement, a city filing, a news listing, or “X campaign lists Y” when only the candidate's website says so. A yes or no answers only the question on that card. A 2023 answer is labelled 2023.</p>
    <p>Campaign money comes from the <a href="https://bouldercolorado.gov/elections/election-committee-filings">city clerk</a>. City races don't report to the state's TRACER system. You'll find 2026 totals and donors on each candidate's page and on the <a href="finance.html">money page</a>. A $0 means the campaign filed a zero. Past years have no dollar figures because the city's archive for them needs a browser to open.</p>
    <h2>What's here</h2>
    <ul>
      <li>The <a href="index.html">2026 guide</a>: key dates, every candidate with a short bio and endorsements, and the four measures.</li>
      <li>A page for each candidate with their words, endorsements and money, and a <a href="print/index.html">printable sheet</a>.</li>
      <li>Pages for <a href="orgs.html">endorsing groups</a>, <a href="issues.html">issues</a>, and every city election since 2017 (the year menu at top right, or the footer).</li>
    </ul>
    <p>The site works without JavaScript and prints cleanly. Folded answers print in full.</p>
    <h2>Source code and data</h2>
    <p>The code that builds this site and the data behind it are public: <a href="{REPO_URL}">source code on GitHub</a>. The same facts are available as <a href="api/index.html">plain text and JSON</a>.</p>
    """.replace("{REPO_URL}", REPO_URL)
    (OUT / "about.html").write_text(page("About", about, learn="about"), encoding="utf-8")

    # keep old race URLs from breaking
    (OUT / "2026-mayor.html").write_text(
        page("2026 mayor", "<h1>2026 mayor</h1><p>Moved onto the <a href='2026.html'>2026 ballot</a>.</p>", year=2026),
        encoding="utf-8",
    )
    (OUT / "2026-council.html").write_text(
        page("2026 council", "<h1>2026 council</h1><p>Moved onto the <a href='2026.html'>2026 ballot</a>.</p>", year=2026),
        encoding="utf-8",
    )

    # Old slug before the ballot-name fix (city roster lists "Dave Martus").
    for sub in ("people", "print"):
        (OUT / sub / "david-martus.html").write_text(
            page("Moved", f"<h1>Dave Martus</h1><p>This page moved to <a href='dave-martus.html'>Dave Martus</a> "
                 "(the name on the ballot).</p>", prefix="../", year=2026),
            encoding="utf-8",
        )

    from build_llm import write_all
    stats = write_all(con, OUT, forums, page)
    print(f"wrote {len(list(OUT.rglob('*.html')))} html files into {OUT}; llms-full.txt {stats['full_bytes']:,} bytes, "
          f"{stats['api_files']} JSON files")
    con.close()


if __name__ == "__main__":
    main()
