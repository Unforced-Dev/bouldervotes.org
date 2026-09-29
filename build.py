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
import sqlite3
from pathlib import Path

from build_2026 import EXTRA_CSS, Graph2026
from build_forums_2026 import FORUM_CSS, Forums2026
from ingest_2026 import civics_markdown

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "bouldervotes.db"
OUT = ROOT / "docs"
YEARS = (2026, 2025, 2023, 2021, 2019, 2017)

CSS = """
/* Boulder Votes: civic, calm, print-grade. Tokens: see vault note
   Projects/Boulder Votes/UI pass 2026-09-29. Contrast on --paper:
   ink 17.2:1, muted 9.7:1, link 8.9:1 (all AAA). */
:root {
  --paper: #fbf8f2;
  --panel: #f2ede3;
  --ink: #161513;
  --muted: #45403a;
  --rule: #c8bfae;
  --rule-strong: #6b6358;
  --link: #14487a;
  --link-visited: #5b3577;
  --focus: #ffd21f;
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --measure: 40rem;
  /* legacy names kept so older markup stays neutral */
  --mark: var(--ink);
  --won: var(--ink);
  --chip: var(--panel);
}
* { box-sizing: border-box; }
html { font-size: 125%; -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--serif);
  line-height: 1.6;
  font-kerning: normal;
}
.skip { position: absolute; left: -999px; top: 0; }
.skip:focus { left: 0.5rem; top: 0.5rem; z-index: 10; padding: 0.5rem 0.8rem; background: var(--focus); color: var(--ink); }
header.site { background: var(--paper); border-bottom: 3px double var(--ink); }
.header-inner, main, footer { max-width: 46rem; margin: 0 auto; padding: 0 1.1rem; }
.header-inner { padding-top: 0.9rem; padding-bottom: 0.5rem; }
.brand { font-size: 1.45rem; font-weight: 700; text-decoration: none; color: var(--ink); letter-spacing: 0.01em; }
.brand:visited { color: var(--ink); }
.tagline { margin: 0.1rem 0 0.4rem; font-family: var(--sans); font-size: 0.85rem; color: var(--muted); }
nav.primary ul, nav.past ul { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; }
nav.primary ul { gap: 0 0.1rem; margin-left: -0.55rem; }
nav.primary a {
  display: inline-flex; align-items: center; min-height: 44px; padding: 0 0.55rem;
  font-family: var(--sans); font-size: 0.9rem; font-weight: 600; color: var(--ink);
  text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 0.2em;
}
nav.primary a:visited { color: var(--ink); }
nav.primary a[aria-current] { text-decoration-thickness: 3px; }
nav.past { display: flex; flex-wrap: wrap; align-items: center; gap: 0 0.1rem; font-family: var(--sans); font-size: 0.85rem; color: var(--muted); border-top: 1px solid var(--rule); margin-top: 0.2rem; }
nav.past a { display: inline-flex; align-items: center; min-height: 44px; padding: 0 0.4rem; color: var(--link); }
nav.past a[aria-current] { font-weight: 700; color: var(--ink); text-decoration-thickness: 3px; }
main { padding-bottom: 1rem; }
h1, h2, h3, h4 { line-height: 1.2; text-wrap: balance; }
h1 { font-size: 2.1rem; margin: 1.4rem 0 0.6rem; letter-spacing: -0.005em; }
h2 { font-size: 1.5rem; margin: 2.6rem 0 0.7rem; padding-top: 0.6rem; border-top: 2px solid var(--ink); }
h3 { font-size: 1.2rem; margin: 1.5rem 0 0.4rem; }
h4 { font-size: 1.05rem; margin: 1rem 0 0.3rem; }
p, li, dd { max-width: var(--measure); }
p { margin: 0.6rem 0; }
ul, ol { padding-left: 1.3rem; }
li { margin: 0.3rem 0; }
.lede { font-size: 1.15rem; line-height: 1.5; margin-top: 0; }
.intro { font-size: 1.2rem; line-height: 1.5; margin: 1.2rem 0 0.4rem; max-width: 38rem; }
.note, .empty, .meta { color: var(--muted); font-size: 0.9rem; }
.empty { font-style: italic; }
a { color: var(--link); text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 0.18em; }
a:visited { color: var(--link-visited); }
a:hover { text-decoration-thickness: 2px; }
a:focus-visible, summary:focus-visible {
  outline: 3px solid var(--ink); outline-offset: 2px; background: var(--focus); color: var(--ink);
  text-decoration: none; border-radius: 1px;
}
.kicker { font-family: var(--sans); font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin: 0; }
.crumb { font-family: var(--sans); font-size: 0.85rem; color: var(--muted); margin: 1rem 0 0; }
.crumb a { display: inline-block; padding: 0.35rem 0; }
.jump { font-family: var(--sans); font-size: 0.9rem; margin: 0.6rem 0 1.2rem; display: flex; flex-wrap: wrap; gap: 0 0.3rem; }
.jump a { display: inline-flex; align-items: center; min-height: 44px; padding: 0 0.5rem; border: 1px solid var(--rule-strong); background: var(--paper); margin: 0 0 0.35rem; }
/* cards: one outline, no accent rails, same for every candidate */
.card {
  border: 1px solid var(--rule-strong);
  padding: 0.8rem 1rem;
  margin: 0 0 0.8rem;
  background: var(--paper);
}
.card > :first-child { margin-top: 0; }
.card > :last-child { margin-bottom: 0; }
.card h3 { margin: 0 0 0.3rem; font-size: 1.2rem; }
.card .meta { margin: 0.2rem 0; }
.chips { margin-top: 0.35rem; }
.chip, .pill {
  display: inline-flex; align-items: center; min-height: 44px; padding: 0 0.6rem; margin: 0 0.3rem 0.3rem 0;
  font-family: var(--sans); font-size: 0.85rem; border: 1px solid var(--rule-strong); color: var(--ink); background: var(--paper);
}
.pill.on { background: var(--ink); color: var(--paper); }
.badge { display: inline-block; font-family: var(--sans); font-size: 0.72rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; border: 1px solid var(--rule-strong); color: var(--muted); padding: 0.05rem 0.4rem; margin: 0 0.25rem; vertical-align: 0.2em; }
.choice {
  display: block; border: 1px solid var(--rule-strong); padding: 0.8rem 1rem; margin: 0.5rem 0;
  color: var(--link); background: var(--paper); font-size: 1.05rem;
}
.choice:hover { background: var(--panel); }
.choice .meta { display: block; font-size: 0.85rem; color: var(--muted); margin-top: 0.25rem; text-decoration: none; font-family: var(--sans); }
/* stances: neutral. The word carries the meaning, never a colour. */
.stance { font-family: var(--sans); font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; font-size: 0.8rem; color: var(--ink); }
.stance.yes, .stance.no, .stance.mixed { color: var(--ink); }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; margin: 0.6rem 0 1.2rem; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 0.45rem 0.5rem 0.45rem 0; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { font-family: var(--sans); font-weight: 700; font-size: 0.8rem; letter-spacing: 0.03em; border-bottom: 2px solid var(--ink); }
.num { font-variant-numeric: tabular-nums; text-align: right; }
.won { font-weight: 700; }
.matrix td, .matrix th { text-align: center; }
.matrix th:first-child, .matrix td:first-child { text-align: left; }
details { margin: 0.4rem 0; }
details > summary { cursor: pointer; min-height: 44px; padding: 0.4rem 0; }
details.quote > summary::after { content: " Read the full answer"; font-family: var(--sans); font-size: 0.85rem; color: var(--link); text-decoration: underline; white-space: nowrap; }
details.quote[open] > summary::after { content: " Hide"; }
details.quote[open] > summary { color: var(--muted); }
details.fold > summary { font-family: var(--sans); font-size: 0.95rem; font-weight: 600; color: var(--link); text-decoration: underline; }
blockquote.answer { margin: 0.4rem 0 0.6rem; padding: 0.1rem 0 0.1rem 1rem; border-left: 3px solid var(--ink); font-size: 1rem; max-width: var(--measure); }
footer { margin: 3rem auto 1.5rem; padding-top: 1rem; border-top: 3px double var(--ink); color: var(--muted); font-family: var(--sans); font-size: 0.85rem; line-height: 2; }
footer p { margin: 0.3rem 0; }
/* candidate summary block */
.summary { border: 2px solid var(--ink); background: var(--panel); padding: 1rem 1.1rem; margin: 0.4rem 0 1.4rem; }
.summary h1 { margin: 0.1rem 0 0.4rem; }
.summary p { margin: 0.4rem 0; }
.summary .jump { margin: 0.7rem 0 0; }
.summary .jump a { background: var(--paper); }
/* home */
.who-list { display: grid; gap: 0.8rem; }
.who-list .card { margin: 0; }
.card .more { font-family: var(--sans); font-size: 0.9rem; margin-top: 0.5rem; }
.card .more a { display: inline-flex; align-items: center; min-height: 44px; }
.howto li { margin: 0.5rem 0; }
@media (max-width: 640px) {
  .tagline, nav.past { display: none; }
  .header-inner { padding-top: 0.6rem; padding-bottom: 0.2rem; }
  nav.primary a { padding: 0 0.5rem; font-size: 0.88rem; }
  h1 { font-size: 1.75rem; }
  h2 { font-size: 1.35rem; }
  .header-inner, main, footer { padding: 0 0.9rem; }
  .card, .summary { padding: 0.75rem 0.8rem; }
  table { font-size: 0.85rem; display: block; overflow-x: auto; }
}
@media print {
  html { font-size: 11pt; }
  body { background: #fff; line-height: 1.35; }
  p { margin: 0.35rem 0; }
  blockquote.answer { margin: 0.25rem 0 0.35rem; }
  .card { padding: 0.5rem 0.7rem; margin-bottom: 0.5rem; }
  header.site { border-bottom: 1px solid #000; }
  .tagline, nav.primary, nav.past, .skip, .jump, .print-hint, footer { display: none; }
  .header-inner, main { max-width: none; padding: 0; }
  .brand { font-size: 1rem; }
  a { color: inherit; text-decoration: none; }
  h1 { font-size: 1.6rem; margin-top: 0.4rem; }
  h2 { font-size: 1.2rem; margin: 1rem 0 0.4rem; break-after: avoid; }
  h3 { font-size: 1.05rem; break-after: avoid; }
  .card, .summary { border-color: #777; background: #fff; break-inside: avoid; }
  /* Closed <details> render nothing in print unless forced open. */
  details > summary { display: none; }
  details::details-content { content-visibility: visible; display: block; }
  details > *:not(summary) { display: block; }
  table { display: table; }
  @page { size: letter; margin: 0.5in 0.55in; }
}
"""


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


def kind_label(kind: str | None) -> str:
    return {
        "questionnaire": "questionnaire",
        "forum": "forum",
        "interview": "interview",
        "article": "press",
    }.get(kind or "", kind or "source")


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
            f"<span class='note'>Boulder Beat emailed yes/no — not a written explanation.</span></p>"
        )
    if grouping:
        word = {"yes": "Yes", "no": "No", "mixed": "Mixed"}.get((stance or "").lower())
        lead = f"<p><strong>{esc(word)}</strong>. {esc(compact)}</p>" if word else f"<p>{esc(compact)}</p>"
        return (
            lead
            + "<p class='note'>Journalist grouping of stated positions, not a written answer from the candidate.</p>"
        )
    return quote_block(text, fold=fold)


PRIMARY_NAV = (
    ("index.html", "2026 guide"),
    ("index.html#mayor", "Candidates"),
    ("index.html#measures", "Measures"),
    ("civics.html", "Civics 101"),
    ("orgs.html", "Organizations"),
    ("finance.html", "Money"),
    ("compare.html", "Forum answers"),
    ("print/index.html", "Print"),
    ("about.html", "About"),
)

TAGLINE = "An independent, nonpartisan, sourced guide to City of Boulder elections."


def page(title: str, body: str, *, prefix: str = "", year: int | None = None, current: str | None = None) -> str:
    primary = []
    for href, label in PRIMARY_NAV:
        cur = ' aria-current="page"' if current == href else ""
        primary.append(f'<li><a href="{prefix}{href}"{cur}>{label}</a></li>')
    past = []
    for y in YEARS:
        cur = ' aria-current="page"' if y == year and y != 2026 else ""
        label = f"{y}" if y != 2026 else "2026 ballot"
        past.append(f'<a href="{prefix}{y}.html"{cur}>{label}</a>')
    home = f"{prefix}index.html"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Boulder Votes</title>
<style>{CSS}{EXTRA_CSS}{FORUM_CSS}</style>
</head>
<body>
<a class="skip" href="#content">Skip to main content</a>
<header class="site">
  <div class="header-inner">
    <a class="brand" href="{home}">Boulder Votes</a>
    <p class="tagline">{esc(TAGLINE)}</p>
    <nav class="primary" aria-label="Main"><ul>{''.join(primary)}</ul></nav>
    <nav class="past" aria-label="Elections by year"><span>Elections:</span> {' '.join(past)}</nav>
  </div>
</header>
<main id="content">
{body}
</main>
<footer>
  <p>City of Boulder only. Cited, not scored, not an endorsement. Nobody here tells you how to vote.</p>
  <p>Elections by year: {' · '.join(f'<a href="{prefix}{y}.html">{y}</a>' for y in YEARS)}</p>
  <p><a href="{prefix}issues.html">Issues</a> ·
  <a href="{prefix}sources.html">Sources</a> ·
  <a href="{prefix}forums.html">Forums</a> ·
  <a href="{prefix}civics.html">Civics 101</a> ·
  <a href="{prefix}orgs.html">Organizations</a> ·
  <a href="{prefix}people.html">People</a> ·
  <a href="{prefix}finance.html">Money</a> ·
  <a href="{prefix}questionnaires.html">Questionnaires</a> ·
  <a href="{prefix}print/index.html">Print</a> ·
  <a href="{prefix}measures.html">All measures</a> ·
  <a href="{prefix}about.html">About</a> ·
  <a href="https://bouldervotes.org/">bouldervotes.org</a></p>
</footer>
</body>
</html>
"""


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    q = con.execute
    OUT.mkdir(parents=True, exist_ok=True)
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
               ORDER BY p.sort_name""",
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
        status = "" if year == 2026 else f"<div class='meta'>{esc(row['status'])}</div>"
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
                result = m["status"]
            title_html = esc(m["title"])
            if year == 2026 and m["letter"]:
                title_html = f"<a href='{prefix}measures/2026-{esc(m['letter'].lower())}.html'>{title_html}</a>"
            bits.append(
                f"<div class='card'><h3>{letter}{title_html}</h3>"
                f"<div class='meta'>{esc(m['kind'])} · {esc(result)}</div>"
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
            2026: "Mayor is ranked-choice (one seat). Council is plurality — five highest vote-getters win. Four city measures are also on the ballot.",
            2025: "Four council seats, no mayor. Last odd-year municipal election.",
            2023: "First direct ranked-choice mayor, four council seats. 34,249 city ballots counted.",
            2021: "Five council seats, no directly elected mayor. Top four: four-year terms; fifth: two-year. 33,772 city ballots; 68,885 active city voters.",
            2019: "Six council seats after Jill Grano resigned (the vacancy added a two-year seat). No directly elected mayor. Top four: four-year; fifth and sixth: two-year. 34,971 city ballots; 68,749 active city voters.",
            2017: "Five council seats, no directly elected mayor. Top four: four-year terms; fifth: two-year. 31,765 city ballots; 72,574 active city voters.",
        }[year]
        jump = '<p class="jump">'
        if qs_year:
            jump += '<a href="#questions">Questions</a>'
        if mayor:
            jump += '<a href="#mayor">Mayor</a>'
        if council:
            jump += '<a href="#council">Council</a>'
        jump += '<a href="#measures">Measures</a>'
        if year == 2026:
            jump += '<a href="#money">Money</a>'
        jump += "</p>"
        bits = [
            f"<h1>{'Tuesday, November 3, 2026' if year == 2026 else str(year) + ' city election'}</h1>",
            f"<p class='lede'>{esc(how)}</p>",
            jump,
        ]
        if qs_year:
            bits.append(f"<h2 id='questions'>Questions asked in {year}</h2>")
            bits.append(
                "<p class='note'>These are the questions on file for this cycle — not a quiz, not a score. "
                "Earlier answers from people who ran before live on their pages.</p>"
            )
            for qu in qs_year:
                bits.append(
                    f"<a class='choice' href='{esc(issue_href(qu['slug'], year))}'>{esc(qu['prompt'])}"
                    f"<span class='meta'>{esc(kind_label(qu['kind']))}</span></a>"
                )
        if mayor:
            bits.append(f"<h2 id='mayor'>Mayor · {len(mayor)} candidates</h2>")
            if year != 2026:
                bits.append(results_table(year, "mayor"))
            for r in mayor:
                bits.append(candidate_card(r, year, "mayor"))
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
            if year != 2026:
                bits.append(results_table(year, "council"))
            for r in council:
                bits.append(candidate_card(r, year, "council"))
            if year == 2026:
                money = q(
                    """SELECT p.full_name, p.slug, f.contributions, f.expenditures, f.matching_received, f.reported_on
                       FROM finance_snapshots f JOIN people p ON p.id=f.person_id
                       WHERE f.year=2026 ORDER BY f.contributions DESC, p.sort_name"""
                ).fetchall()
                if money:
                    bits.append("<h2 id='money'>Money so far</h2>")
                    bits.append(
                        "<p class='note'>City clerk contributions &amp; expenditures, retrieved 2026-09-01. "
                        "Not TRACER. $0 means they filed that, not that we guessed. "
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
        "<p class='lede'>Each year is the questions asked that cycle. A 2023 yes/no about a 2023 measure is not a 2026 position. Open a person to see what they have said across years.</p>",
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
    (OUT / "issues.html").write_text(page("Issues", "\n".join(hub)), encoding="utf-8")

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
        rows = q(
            """SELECT a.id, p.id AS person_id, p.slug, p.full_name, a.stance, a.verbatim, a.notes,
                      s.title AS source_title, s.url AS source_url
               FROM answers a
               JOIN people p ON p.id=a.person_id
               JOIN sources s ON s.id=a.source_id
               WHERE a.question_id=?
               ORDER BY p.sort_name""",
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
            bits.append(f"<p>Asked in {', '.join(str(y) for y in ys)}. The question wording changes; the issue persists.</p>")
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
                f"We do not copy an earlier year’s yes/no onto this page.</p>",
            ]
            for qu in qs_this:
                ans = answers_for_question(qu["id"], ballot_ids)
                if len(qs_this) > 1:
                    body.append(f"<h2>{esc(qu['prompt'])}</h2>")
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
                            f"That is not a no.</p>"
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
    on_2026 = {r["person_id"] for r in candidates_for(2026, "mayor") + candidates_for(2026, "council")}
    plist = [
        "<h1>People</h1>",
        "<p class='lede'>A person lasts across years. Open a dossier for the questions they have actually answered, newest year first.</p>",
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
        extra = f" · {n_ans} answers" if n_ans else ""
        snap = finance_for(p["id"], 2026) if p["id"] in on_2026 else None
        if snap:
            extra += f" · raised {dollars(snap['contributions'])}"
        li = f"<div class='card'><h3><a href='{esc(person_href(p['slug']))}'>{esc(p['full_name'])}</a></h3><div class='meta'>{esc(ytxt)}{extra}</div></div>"
        if p["id"] in on_2026:
            plist.append(li)
        else:
            later.append(li)
    plist.extend(later)
    (OUT / "people.html").write_text(page("People", "\n".join(plist)), encoding="utf-8")

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
                bits.append(f"<p class='lede'>{esc(p['notes'])}</p>")
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
            outcome = "on the ballot" if c["status"] == "certified" else c["status"]
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
                "<p class='note'>Newest year first. Each card is one question. A yes/no is an answer to that question — not a position on the whole topic.</p>"
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
                bits.append(
                    f"<p>{snap['year']}: raised {dollars(snap['contributions'])} · "
                    f"spent {dollars(snap['expenditures'])} · "
                    f"matching received {dollars(snap['matching_received'])}"
                    + (
                        f" · cash on hand {dollars(snap['cash_on_hand'])}"
                        if snap["cash_on_hand"] is not None
                        else ""
                    )
                    + f" ({esc(snap['committee_name'])}"
                    + (f", as of {esc(snap['reported_on'])}" if snap["reported_on"] else "")
                    + ").</p>"
                )
                if snap["notes"]:
                    bits.append(f"<p class='note'>{esc(snap['notes'])}</p>")
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
        if cand26:
            bits.insert(0, graph.candidate_summary(p["id"], "\n".join(bits), p["slug"]))
        (OUT / "people" / f"{p['slug']}.html").write_text(
            page(p["full_name"], "\n".join(bits), prefix="../", year=latest),
            encoding="utf-8",
        )

    # forums / measures / sources / about remain available, not in primary nav
    ev_html = ["<h1>Forums</h1>", "<p>The calendar behind the year pages. Attendance only when a published source named who showed.</p>",
               forums.forum_index_html(), "<h2>Calendar</h2>"]
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
            ev_html.append(f"<p class='note'>{esc(e['notes'])}</p>")
        apps = q(
            """SELECT p.full_name, p.slug, a.attended FROM event_appearances a
               JOIN people p ON p.id=a.person_id WHERE a.event_id=? ORDER BY p.sort_name""",
            (e["id"],),
        ).fetchall()
        if apps:
            ev_html.append("<ul>")
            for a in apps:
                flag = "attended" if a["attended"] == 1 else "did not attend" if a["attended"] == 0 else "unknown"
                ev_html.append(f"<li><a href='{esc(person_href(a['slug']))}'>{esc(a['full_name'])}</a> — {flag}</li>")
            ev_html.append("</ul>")
    (OUT / "forums.html").write_text(page("Forums", "\n".join(ev_html)), encoding="utf-8")

    meas_html = ["<h1>City measures</h1>"]
    for year in YEARS:
        meas_html.append(f"<h2>{year}</h2>")
        meas_html.append(measure_cards(year))
    (OUT / "measures.html").write_text(page("Measures", "\n".join(meas_html)), encoding="utf-8")

    sources = q(
        """SELECT s.*, o.name AS org FROM sources s
           LEFT JOIN organizations o ON o.id=s.org_id
           ORDER BY s.year DESC, s.published_on DESC, s.title"""
    ).fetchall()
    src_rows = ["<tr><th>Year</th><th>Kind</th><th>Source</th></tr>"]
    for s in sources:
        src_rows.append(
            f"<tr><td>{s['year'] or ''}</td><td>{esc(s['kind'])}</td>"
            f"<td><a href='{esc(s['url'])}'>{esc(s['title'])}</a></td></tr>"
        )
    (OUT / "sources.html").write_text(
        page("Sources", f"<h1>Sources</h1><p>The catalog. Quoted claims live on people and issue pages.</p><table>{''.join(src_rows)}</table>"),
        encoding="utf-8",
    )

    qn_html = [
        "<h1>Questionnaires</h1>",
        "<p class='lede'>Written candidate Q&amp;A we have located. Full verbatim is ingested only when we copied it into the database (BRL, Boulder Beat). Everything else is linked, not scored.</p>",
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
        note = f"<div class='meta'>{esc(s['notes'])}</div>" if s["notes"] else ""
        qn_html.append(
            f"<tr><td>{s['year'] or ''}</td><td>{org}<a href='{esc(s['url'])}'>{esc(s['title'])}</a>{note}</td></tr>"
        )
    qn_html.append("</table>")
    qn_html.append(
        "<p class='note'>Forum videos, including YouTube, live on the <a href='forums.html'>forums</a> page. "
        "We do not invent spoken quotes from a journalist’s grouping or an auto-transcript.</p>"
    )
    (OUT / "questionnaires.html").write_text(page("Questionnaires", "\n".join(qn_html)), encoding="utf-8")

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
            f"<p class='print-hint'>File → Print. A short sheet: usually one or two letter-size pages. Every answer prints in full. Not an endorsement.</p>",
            f"<h1>{esc(row['full_name'])}</h1>",
            f"<p class='lede'>2026 {esc(office)}{flag_txt}</p>",
            site,
            "<h2>Campaigns</h2>",
        ]
        tbody = ["<tr><th>Year</th><th>Office</th><th>Outcome</th></tr>"]
        for c in cands:
            tbody.append(
                f"<tr><td>{c['year']}</td><td>{esc(c['office'])}</td><td>{esc(c['status'])}</td></tr>"
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
                f"(as of {esc(snap['reported_on'])}, {esc(snap['committee_name'])}). "
                f"Clerk matching-funds flag: {money_flag}. Not TRACER.</p>"
            )
            if snap["notes"]:
                bits.append(f"<p class='note'>{esc(snap['notes'])}</p>")
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
        "<p class='lede'>A short printable sheet for each 2026 candidate: their campaigns, up to four answers printed in full, and city clerk money totals. Most sheets are one or two letter-size pages.</p>",
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
                  f.reports_url, f.person_id, s.url AS source_url, s.title AS source_title
           FROM finance_snapshots f
           LEFT JOIN people p ON p.id=f.person_id
           JOIN sources s ON s.id=f.source_id
           WHERE f.year=2026
           ORDER BY f.contributions DESC, COALESCE(p.sort_name, f.committee_name)"""
    ).fetchall()
    fin_html = [
        "<h1>Campaign money — 2026</h1>",
        "<p class='lede'>City of Boulder committee filings, not TRACER. Retrieved 2026-09-01 from the live clerk app. $0 is a filed zero, not a missing record. Cents come from the latest CandE statement; the clerk’s summary table rounds to dollars.</p>",
        "<p class='note'>Past-year dollars: the live app only serves 2026. Historical filings sit in the city’s "
        "<a href='https://documents.bouldercolorado.gov/WebLink/Browse.aspx?id=59131'>Laserfiche archive</a> "
        "(cookie/JS). This pass could not list that folder. Matching-funds asterisks on the clerk candidate list are separate from the matching-received column here.</p>",
    ]
    candidates = [r for r in fin_rows if r["committee_kind"] == "official_candidate" and r["person_id"]]
    cand_ids = {r["id"] for r in candidates}
    other = [r for r in fin_rows if r["id"] not in cand_ids]
    if candidates:
        fin_html.append(f"<p class='note'><a href='{esc(candidates[0]['source_url'])}'>{esc(candidates[0]['source_title'])}</a></p>")
        body = [
            "<tr><th>Candidate</th><th>Committee</th><th class='num'>Raised</th>"
            "<th class='num'>Spent</th><th class='num'>Matching</th>"
            "<th class='num'>Donors</th><th>As of</th></tr>"
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
                f"<td>{esc(r['reported_on'] or '—')}</td></tr>"
            )
        fin_html.append(f"<table>{''.join(body)}</table>")
        noted = [r for r in candidates if r["notes"]]
        if noted:
            fin_html.append("<ul class='note'>")
            for r in noted:
                fin_html.append(f"<li><a href='{esc(person_href(r['slug']))}'>{esc(r['full_name'])}</a> — {esc(r['notes'])}</li>")
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
            "<p class='note'>Only names that already exist as people in this map (candidates, officeholders). "
            "Everyone else is on the candidate’s dossier. Not a complete donor graph.</p>"
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
            "<p class='note'>Ballot-measure and unofficial committees, plus any official committee whose candidate is not on the certified clerk list.</p>"
        )
        body = ["<tr><th>Committee</th><th>Kind</th><th class='num'>Raised</th><th class='num'>Spent</th><th>As of</th></tr>"]
        for r in other:
            kind = (r["committee_kind"] or "").replace("_", " ")
            body.append(
                f"<tr><td>{esc(r['committee_name'])}</td><td>{esc(kind)}</td>"
                f"<td class='num'>{dollars(r['contributions'])}</td>"
                f"<td class='num'>{dollars(r['expenditures'])}</td>"
                f"<td>{esc(r['reported_on'] or '—')}</td></tr>"
            )
        fin_html.append(f"<table>{''.join(body)}</table>")
    fin_html.append("<p><a href='https://webapps.bouldercolorado.gov/election/committeeFilings.php'>Open the clerk app</a> to read each statement.</p>")
    (OUT / "finance.html").write_text(page("Money", "\n".join(fin_html), year=2026), encoding="utf-8")

    about = """
    <h1>About</h1>
    <p>Boulder Votes is a map of City of Boulder elections for people who have to mark a ballot, especially older voters. It is not a feed, not a quiz, and not a scorecard.</p>
    <h2>How to use it</h2>
    <ul>
      <li><strong>The 2026 guide</strong> (home page) — key dates, every mayor and council candidate with a one-line bio and who endorses them, and the four city measures.</li>
      <li><strong>A candidate</strong> — bio, positions in their own words with the source, endorsers grouped (organizations, current elected officials, former elected officials, other individuals), and money.</li>
      <li><strong>An organization</strong> — who they are, how they decide, what we know about their funding, and whom they endorsed.</li>
      <li><strong>Where an endorsement comes from</strong> — every endorsement line is labelled: the endorser's own statement, a city committee filing, or “X campaign lists Y” when the only source is the candidate's own website.</li>
      <li><strong>A year</strong> — that year’s ballot, and the questions asked that cycle.</li>
      <li><strong>A person</strong> — the questions they have answered, newest year first. A 2023 yes/no is labelled 2023 and named as that question. It is not a 2026 position.</li>
      <li><strong>A question</strong> — people on that year’s ballot who answered it. We do not copy an earlier year’s answer onto this year’s page.</li>
      <li><strong>Print</strong> — a short sheet per 2026 candidate (usually one or two pages), with every answer printed in full. File → Print.</li>
    </ul>
    <p>Years on the rail run 2017–2026. 2015 and earlier are out of scope for now.</p>
    <p>A number without a source is not published. Two quotes are never averaged. We do not score candidates. A yes/no is an answer to the question on the card — never a stand-in for a whole topic like “city budget.”</p>
    <p>Municipal campaign-finance filings are with the <a href="https://bouldercolorado.gov/elections/election-committee-filings">city clerk</a>, not TRACER. 2026 totals and itemized donors live on each candidate’s page (below what they have said) and on <a href="finance.html">Money</a>. $0 is a filed zero. Past-year dollars are not copied (the live clerk app only serves 2026; Laserfiche is a JS archive).</p>
    <p>No JavaScript. Large type. Printing any page prints the folded answers in full.</p>
    """
    (OUT / "about.html").write_text(page("About", about), encoding="utf-8")

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

    print(f"wrote {len(list(OUT.rglob('*.html')))} html files into {OUT}")
    con.close()


if __name__ == "__main__":
    main()
