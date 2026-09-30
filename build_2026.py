"""2026 evidence-graph pages: voter start page, candidate sections, endorser
groups, organization pages, measure pages, Civics 101.

Trust rules rendered here (see tools/approve_2026.py for where data is set):
  * Every endorsement line carries a visible provenance label. A campaign claim
    always reads "<X> campaign lists <Y>" so it is never mistaken for the
    endorser's own announcement.
  * Held statements are never printed.
  * Endorsers are grouped (organizations / current elected / former elected /
    other individuals) with the title as printed on the cited page. Grouping
    is presentation, not a score: no counts are ranked, nothing is weighted.
  * Ranked-choice endorsements show their rank.
"""
from __future__ import annotations

from build_plain import plain
import html
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent

GROUPS = [
    ("organization", "Organizations and committees"),
    ("current_elected", "Current elected officials"),
    ("former_elected", "Former elected officials"),
    ("other_individual", "Other individuals"),
]

KEY_DATES_URL = "https://bouldercounty.gov/elections/information/"

# Key dates, as published by Boulder County Elections (KEY_DATES_URL, checked 2026-09-29).
KEY_DATES = [
    ("2026-10-02", "Oct 2", "Ballots mailed; 24-hour drop boxes open"),
    ("2026-10-19", "Oct 19", "Vote Centers open for in-person voting"),
    ("2026-10-26", "Oct 26", "Last recommended day to return a ballot by mail"),
    ("2026-11-03", "Nov 3", "Election Day: ballots must be received by 7 p.m."),
]

PHOTOS = {p["slug"]: p for p in json.loads(
    (ROOT / "data" / "harvest" / "2026" / "photos.json").read_text(encoding="utf-8"))["photos"]}


def initials(name: str) -> str:
    parts = [w for w in name.split() if w[:1].isalpha()]
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else name[:1].upper()


def face(slug: str, name: str, prefix: str, size: int = 96) -> str:
    """Sourced campaign photo, or a neutral monogram tile of the same size.
    Decorative next to the name (alt=""), so screen readers do not hear it twice."""
    ph = PHOTOS.get(slug)
    if ph and ph.get("file"):
        return (f"<img class='face' src='{prefix}{esc(ph['file'])}' alt='' width='{size}' height='{size}' "
                f"loading='lazy' decoding='async'>")
    return f"<span class='face mono' aria-hidden='true' style='width:{size}px;height:{size}px'>{esc(initials(name))}</span>"


def photo_credit(slug: str) -> str:
    ph = PHOTOS.get(slug)
    if ph and ph.get("file"):
        return f"<a href='{esc(ph['credit_url'])}'>{esc(ph['credit'])}</a>"
    return "No photo: " + esc(ph["reason"]) if ph else "No photo on file."


def timeline(today) -> str:
    """Key dates with where the build date falls. Computed at build time; labelled 'as of'."""
    import datetime as dt
    items, nxt = [], None
    today_li = (f"<li class='today' aria-current='date'><time class='d' datetime='{today.isoformat()}'>"
                f"{today.strftime('%b %-d')}</time><span class='t'>Today</span></li>")
    for iso, short, label in KEY_DATES:
        d = dt.date.fromisoformat(iso)
        if d > today and nxt is None:
            items.append(today_li)
        state = "done" if d < today else ("today" if d == today else "")
        if nxt is None and d >= today:
            nxt = (d, label)
        cls = f" class='{state}'" if state else ""
        items.append(f"<li{cls}><time class='d' datetime='{iso}'>{short}</time><span class='t'>{esc(label)}</span></li>")
    if nxt:
        days = (nxt[0] - today).days
        when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
        count = f"<p class='countdown'>Next: {esc(nxt[1].split(';')[0].split(':')[0])} {when}.</p>"
    else:
        count = "<p class='countdown'>Election Day has passed.</p>"
    nice = today.strftime("%B %-d, %Y")
    return (
        "<section class='timeline' aria-labelledby='dates'>"
        f"<div class='timeline-head'><h2 id='dates'>Key dates</h2><span class='asof'>As of {nice}</span></div>"
        f"{count}<ol>{''.join(items)}</ol>"
        "<p class='note'>Ballots are mailed starting Friday, October 2. Your ballot must be <em>received</em> by "
        "7 p.m. Tuesday, November 3. Mail it early or use a 24-hour drop box (they open October 2). "
        f"Dates from <a href='{KEY_DATES_URL}'>Boulder County Elections</a>. October 2 is the planned mailing date, "
        "not a delivery guarantee.</p></section>"
    )

HOME_INTRO = (
    "Boulder Votes is an independent, nonpartisan guide to the City of Boulder's "
    "November 3, 2026 election. It covers the mayor and council races and the four city measures."
)


PROV_LEGEND = """
<details class='fold'><summary>What the labels on each endorsement mean</summary>
<dl class='legend'>
<dt>Endorser's own statement</dt><dd>The organization or person announced it themselves (their site, their press release, or a news story reprinting that release).</dd>
<dt>“X campaign lists Y”</dt><dd>Only the candidate's (or ballot campaign's) own website says so. We didn't find the endorser saying it. It may be true, but it is the campaign's claim.</dd>
<dt>City filing</dt><dd>A committee's registration with the city clerk names the candidate or measure it supports.</dd>
<dt>News listing</dt><dd>A news outlet lists the endorsement, but we did not find the endorser's own statement.</dd>
</dl>
<p class='note'>Titles (e.g. “U.S. Representative”) are as printed on the cited page and describe the person, not an endorsement by their office. A blank title means the source did not give one.</p>
</details>
"""


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s))


def panelize_sections(html_body: str) -> str:
    """Wrap each <h2>-led section in a card (presentation only)."""
    parts = re.split(r"(?=<h2[ >])", html_body)
    return parts[0] + "".join(f"<section class='panel'>{c}</section>" for c in parts[1:])


def ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def first_sentence(text: str | None) -> str:
    text = " ".join((text or "").split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return m.group(1) if m else text


def md_to_html(md: str) -> str:
    """Tiny markdown for civics101.md: headings, paragraphs, lists, bold/italic,
    [Source: url] and [Sources: url ; url] citations."""

    def inline(t: str) -> str:
        t = esc(t)

        def cite(m: re.Match) -> str:
            urls = [u.strip() for u in re.split(r"\s;\s|;\s", m.group(2)) if u.strip()]
            links = ", ".join(f"<a href='{u}'>{'source' if len(urls) == 1 else f'source {i + 1}'}</a>"
                              for i, u in enumerate(urls))
            return f"<span class='note'>[{links}]</span>"

        t = re.sub(r"\[(Sources?):\s*([^\]]+)\]", cite, t)
        t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"<a href='\2'>\1</a>", t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", t)
        return t

    out, para, items = [], [], []

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in md.splitlines():
        s = line.rstrip()
        if not s.strip():
            flush()
            continue
        h = re.match(r"^(#{1,4})\s+(.*)$", s)
        if h:
            flush()
            lvl = len(h.group(1))
            out.append(f"<h{lvl}>{inline(h.group(2))}</h{lvl}>")
            continue
        li = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", s)
        if li:
            if para:
                flush()
            items.append(li.group(1))
            continue
        if items:
            items[-1] += " " + s.strip()
        else:
            para.append(s.strip())
    flush()
    return "\n".join(out)


class Graph2026:
    def __init__(self, con: sqlite3.Connection, out: Path, page):
        self.con = con
        self.q = con.execute
        self.out = out
        self.page = page

    # ------------------------------------------------------------ queries
    def endorsements(self, where: str, params: tuple) -> list[sqlite3.Row]:
        return self.q(
            f"""SELECT e.*, s.url AS source_url, s.title AS source_title,
                       o.slug AS org_slug, o.name AS org_name, op.endorser_kind,
                       p.slug AS person_slug, p.full_name AS person_name,
                       pt.title AS person_title, pt.weight_group,
                       tp.slug AS cand_slug, tp.full_name AS cand_name, ofc.slug AS cand_office,
                       m.letter AS m_letter, m.title AS m_title
                FROM endorsements e
                JOIN sources s ON s.id=e.source_id
                LEFT JOIN organizations o ON o.id=e.endorser_org_id
                LEFT JOIN org_profiles op ON op.org_id=o.id
                LEFT JOIN people p ON p.id=e.endorser_person_id
                LEFT JOIN person_titles pt ON pt.person_id=p.id
                LEFT JOIN candidacies c ON c.id=e.candidacy_id
                LEFT JOIN people tp ON tp.id=c.person_id
                LEFT JOIN races r ON r.id=c.race_id
                LEFT JOIN offices ofc ON ofc.id=r.office_id
                LEFT JOIN measures m ON m.id=e.measure_id
                WHERE e.status='published' AND {where}
                ORDER BY COALESCE(e.rank, 9), COALESCE(o.name, p.sort_name)""",
            params,
        ).fetchall()

    def candidates(self, office: str) -> list[sqlite3.Row]:
        return self.q(
            """SELECT c.id AS candidacy_id, p.id AS person_id, p.slug, p.full_name, c.is_incumbent,
                      c.campaign_url, c.matching_funds, cp.summary, cp.occupation, cp.prior_office,
                      cp.years_in_boulder, cp.research_notes
               FROM candidacies c JOIN people p ON p.id=c.person_id
               JOIN races r ON r.id=c.race_id JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id
               LEFT JOIN candidate_profiles cp ON cp.candidacy_id=c.id
               WHERE e.year=2026 AND o.slug=? ORDER BY c.ballot_position IS NULL, c.ballot_position, p.sort_name""",
            (office,),
        ).fetchall()

    # ------------------------------------------------------------ pieces
    @staticmethod
    def group_of(e) -> str:
        if e["endorser_org_id"]:
            return "organization"
        return e["weight_group"] or "other_individual"

    def endorser_name(self, e, prefix: str) -> str:
        if e["endorser_org_id"]:
            return f"<a href='{prefix}orgs/{esc(e['org_slug'])}.html'>{esc(e['org_name'])}</a>"
        title = f", {esc(e['person_title'])}" if e["person_title"] else ""
        return f"<a href='{prefix}people/{esc(e['person_slug'])}.html'>{esc(e['person_name'])}</a>{title}"

    @staticmethod
    def plain_endorser(e) -> str:
        return e["org_name"] or e["person_name"]

    def target_name(self, e, prefix: str) -> str:
        if e["candidacy_id"]:
            return f"<a href='{prefix}people/{esc(e['cand_slug'])}.html'>{esc(e['cand_name'])}</a> ({esc(e['cand_office'])})"
        if e["measure_id"]:
            return f"<a href='{prefix}measures/2026-{esc(e['m_letter'].lower())}.html'>City {esc(e['m_letter'])}: {esc(e['m_title'])}</a>"
        return f"{esc(e['target_label'])} <span class='note'>(not a City of Boulder measure)</span>"

    def prov_line(self, e) -> str:
        """Visible provenance label + source link. Campaign claims name the campaign."""
        who = esc(self.plain_endorser(e))
        pv = e["provenance"]
        if pv == "campaign_claim":
            claimer = (e["claimed_by"] or "Campaign").removesuffix(" campaign").replace(" (ballot campaign)", " ballot")
            label = f"{esc(claimer)} campaign lists {who}"
            tail = "Only the campaign says so."
        elif pv == "filing":
            label = "City filing"
            tail = "Committee registration with the city clerk names this."
        elif pv == "news_report":
            label = f"News listing: {esc(e['claimed_by'])} lists {who}"
            tail = "We didn't find the endorser's own statement."
        else:
            label = "Endorser's own statement"
            tail = ""
        date = f" · {esc(e['published_on'])}" if e["published_on"] else ""
        return (
            f"<span class='prov prov-{pv}' data-edge='{esc(e['id'])}' data-provenance='{pv}'>"
            f"<span class='prov-label'>{label}</span>. {esc(tail)} "
            f"<a href='{esc(e['source_url'])}'>{esc(e['source_title'])}</a>{date}</span>"
        )

    def edge_li(self, e, prefix: str, show: str) -> str:
        """show='endorser' on candidate/measure pages, 'target' on endorser pages."""
        pos = "Opposes" if e["position"] == "oppose" else ("Supports" if e["measure_id"] or e["target_label"] else "Endorses")
        rank = f" <span class='rank'>{ordinal(e['rank'])} choice (ranked-choice)</span>" if e["rank"] else ""
        main = self.endorser_name(e, prefix) if show == "endorser" else f"{pos}: {self.target_name(e, prefix)}"
        if show == "endorser" and (e["measure_id"] or e["target_label"]):
            main = f"{pos}: " + main
        return f"<li>{main}{rank}{self.prov_line(e)}</li>"

    def grouped_endorsers(self, edges, prefix: str) -> str:
        if not edges:
            return "<p class='empty'>No endorsements on file. That is not opposition.</p>"
        out = []
        for key, label in GROUPS:
            chunk = [e for e in edges if self.group_of(e) == key]
            if not chunk:
                continue
            out.append(f"<h3>{esc(label)} <span class='note'>({len(chunk)})</span></h3>")
            out.append("<ul class='edges'>" + "".join(self.edge_li(e, prefix, "endorser") for e in chunk) + "</ul>")
        return "\n".join(out)

    def summary_line(self, edges, prefix: str) -> str:
        if not edges:
            return "No endorsements on file."
        orgs = []
        for e in edges:
            if e["endorser_org_id"]:
                tag = f" ({ordinal(e['rank'])} choice)" if e["rank"] else ""
                if e["provenance"] == "campaign_claim":
                    tag += " (campaign-listed)"
                if e["provenance"] == "news_report":
                    tag += " (news listing)"
                if e["provenance"] == "filing":
                    tag += " (city filing)"
                orgs.append(f"<a href='{prefix}orgs/{esc(e['org_slug'])}.html'>{esc(e['org_name'])}</a>{esc(tag)}")
        bits = []
        if orgs:
            bits.append("Organizations: " + "; ".join(orgs) + ".")
        people = [e for e in edges if not e["endorser_org_id"]]
        if people:
            counts = []
            for key, label in GROUPS[1:]:
                n = sum(1 for e in people if self.group_of(e) == key)
                if n:
                    lab = label.lower()
                    if n == 1:
                        lab = {"current elected officials": "current elected official",
                               "former elected officials": "former elected official",
                               "other individuals": "other individual"}[lab]
                    counts.append(f"{n} {lab}")
            listed = sum(1 for e in people if e["provenance"] == "campaign_claim")
            src = ", all listed by the campaign" if listed == len(people) else (
                f", {listed} listed by the campaign" if listed else "")
            bits.append("Individuals: " + ", ".join(counts) + src + ".")
        return " ".join(bits)

    def statements(self, person_id: int, status: str = "published") -> list[sqlite3.Row]:
        return self.q(
            """SELECT st.*, s.url AS source_url, s.title AS source_title
               FROM statements st JOIN sources s ON s.id=st.source_id
               WHERE st.person_id=? AND st.status=? ORDER BY st.topic, st.id""",
            (person_id, status),
        ).fetchall()

    @staticmethod
    def quote(text: str) -> str:
        compact = " ".join(text.split())
        if len(compact) <= 220:
            return f"<blockquote class='answer'>{esc(compact)}</blockquote>"
        cut = compact[:200].rsplit(" ", 1)[0] + "…"
        return (f"<details class='quote'><summary>{esc(cut)}</summary>"
                f"<blockquote class='answer'>{esc(compact)}</blockquote></details>")

    # ------------------------------------------------------------ candidate summary (top of page)
    def candidate_summary(self, person_id: int, body: str, slug: str) -> str:
        """Office, bio line and jump links. Same fields in the same order for every
        2026 candidate, mayor or council, so no one gets a different treatment."""
        row = self.q(
            """SELECT p.full_name, o.name AS office, o.slug AS office_slug, c.is_incumbent,
                      c.campaign_url, cp.summary
               FROM candidacies c JOIN people p ON p.id=c.person_id
               JOIN races r ON r.id=c.race_id JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id LEFT JOIN candidate_profiles cp ON cp.candidacy_id=c.id
               WHERE c.person_id=? AND e.year=2026""",
            (person_id,),
        ).fetchone()
        race = "Mayor" if row["office_slug"] == "mayor" else "City Council"
        anchor = "mayor" if row["office_slug"] == "mayor" else "council"
        kicker = f"Running for {esc(row['office'])} · 2026"
        if row["is_incumbent"]:
            kicker += " · Incumbent"
        jumps = []
        for anchor_id, label in (("bio", "About"), ("positions", "Positions"), ("forums", "At the forums"),
                                 ("endorsers", "Endorsements"), ("money", "Money"),
                                 ("questionnaires", "Past answers"), ("campaigns", "Campaigns")):
            if f"id='{anchor_id}'" in body or f'id="{anchor_id}"' in body:
                jumps.append(f"<a href='#{anchor_id}'>{label}</a>")
        snap = self.q("SELECT * FROM finance_snapshots WHERE person_id=? AND year=2026", (person_id,)).fetchone()
        money = ""
        if snap:
            def d(n):
                if n is None:
                    return "—"
                x = float(n)
                return f"${x:,.0f}" if abs(x - round(x)) < 0.005 else f"${x:,.2f}"
            money = (f"<p class='note'>Money (city clerk{', as of ' + esc(snap['reported_on']) if snap['reported_on'] else ''}): "
                     f"raised <span class='num'>{d(snap['contributions'])}</span> · spent <span class='num'>{d(snap['expenditures'])}</span> · "
                     f"matching funds received <span class='num'>{d(snap['matching_received'])}</span>.</p>")
        actions = [f"<a class='btn secondary' href='../print/{esc(slug)}.html'>Print this candidate</a>"]
        if row["campaign_url"]:
            actions.append(f"<a class='btn secondary' href='{esc(row['campaign_url'])}'>Campaign website</a>")
        return (
            f"<p class='crumb'><a href='../index.html'>2026 guide</a> › <a href='../index.html#{anchor}'>{race}</a></p>"
            f"<div class='profile summary'>"
            f"<figure>{face(slug, row['full_name'], '../', 180)}<figcaption>{photo_credit(slug)}</figcaption></figure>"
            f"<div class='who'>"
            f"<p class='kicker'>{kicker}</p>"
            f"<h1>{esc(row['full_name'])}</h1>"
            + (f"<p class='bio-line'>{esc(first_sentence(row['summary']))}</p>" if row["summary"] else "")
            + money
            + f"<nav class='jump' aria-label='On this page'>{''.join(jumps)}</nav>"
            f"<p class='actions print-hint'>{''.join(actions)}</p>"
            f"</div></div>"
        )

    # ------------------------------------------------------------ person page sections
    def person_sections(self, person_id: int, prefix: str = "../") -> str:
        from build import human_label  # late import: build.py imports this module
        bits: list[str] = []
        cand = self.q(
            """SELECT c.id, o.name AS office, o.slug AS office_slug, cp.*
               FROM candidacies c JOIN races r ON r.id=c.race_id JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id LEFT JOIN candidate_profiles cp ON cp.candidacy_id=c.id
               WHERE c.person_id=? AND e.year=2026""",
            (person_id,),
        ).fetchone()
        title = self.q("SELECT pt.*, s.url, s.title AS stitle FROM person_titles pt JOIN sources s ON s.id=pt.source_id WHERE person_id=?",
                       (person_id,)).fetchone()
        if cand:
            bits.append(f"<h2 id='bio'>About this candidate</h2>")
            if cand["summary"]:
                bits.append(f"<p>{esc(cand['summary'])}</p>")
            facts = []
            for k, lab in (("occupation", "Occupation"), ("prior_office", "Public office"), ("years_in_boulder", "In Boulder")):
                if cand[k]:
                    facts.append(f"<li><strong>{lab}:</strong> {esc(cand[k])}</li>")
            if facts:
                bits.append("<ul class='facts'>" + "".join(facts) + "</ul>")
            srcs = self.q("""SELECT DISTINCT s.url FROM profile_sources ps JOIN sources s ON s.id=ps.source_id
                             WHERE ps.candidacy_id=?""", (cand["id"],)).fetchall()
            if srcs:
                bits.append("<p class='note'>Bio sources: " + ", ".join(
                    f"<a href='{esc(r['url'])}'>{esc(re.sub(r'^https?://(www\\.)?', '', r['url']).split('/')[0])}</a>" for r in srcs) + "</p>")
            if cand["research_notes"]:
                bits.append(f"<p class='note'>{esc(plain(cand['research_notes']))}</p>")

            # statements
            pub = self.statements(person_id)
            own = [s for s in pub if s["speaker_is_candidate"]]
            reported = [s for s in pub if not s["speaker_is_candidate"]]
            held = self.statements(person_id, "held")
            bits.append("<h2 id='positions'>In their own words</h2>")
            bits.append("<p class='note'>Short passages from questionnaires, interviews and the campaign website, by topic. "
                        "If a topic is missing, we have no quote on it. That says nothing about their view.</p>")
            if own:
                cur_topic = None
                for s in own:
                    if s["topic"] != cur_topic:
                        bits.append(f"<h3>{esc(s['topic'].replace('-', ' ').capitalize())}</h3>")  # topic
                        cur_topic = s["topic"]
                    date = f" · {esc(s['published_on'])}" if s["published_on"] else ""
                    bits.append(
                        f"<div class='card' data-statement='{esc(s['id'])}'>{self.quote(s['text'])}"
                        f"<p class='note'>Source: {esc(s['publisher'])} · {esc(human_label(s['kind']))}{date} · "
                        f"<a href='{esc(s['source_url'])}'>{esc(s['source_title'])}</a></p></div>"
                    )
            else:
                bits.append("<p class='empty'>No first-person statements on file.</p>")
            if reported:
                bits.append("<h3>What reporters wrote</h3>")
                bits.append("<p class='note'>These are the reporter's words about the candidate, not the candidate's own.</p>")
                for s in reported:
                    date = f" · {esc(s['published_on'])}" if s["published_on"] else ""
                    bits.append(
                        f"<div class='card' data-statement='{esc(s['id'])}'>"
                        f"<div class='meta'>{esc(s['speaker'])} · {esc(s['topic'].replace('-', ' '))}</div>{self.quote(s['text'])}"
                        f"<p class='note'>{esc(s['publisher'])}{date} · <a href='{esc(s['source_url'])}'>{esc(s['source_title'])}</a></p></div>"
                    )
            if held:
                bits.append(
                    f"<p class='held'>{len(held)} further passage{'s' if len(held) != 1 else ''} "
                    f"({', '.join(sorted({h['publisher'] for h in held}))}) not shown yet. We could not find the quoted words in the "
                    f"article, so we are holding them until we can check.</p>"
                )

            edges = self.endorsements("e.candidacy_id=?", (cand["id"],))
            bits.append("<h2 id='endorsers'>Endorsements</h2>")
            bits.append("<p class='note'>Each line says where the endorsement comes from.</p>")
            bits.append(PROV_LEGEND)
            bits.append(self.grouped_endorsers(edges, prefix))
        elif title:
            bits.append(
                f"<p class='lede'>{esc(title['title'])} "
                f"<span class='note'>(title as printed on <a href='{esc(title['url'])}'>a cited 2026 page</a>)</span></p>"
            )

        roles = self.q(
            """SELECT ol.*, o.slug, o.name, s.url FROM org_leadership ol JOIN organizations o ON o.id=ol.org_id
               JOIN sources s ON s.id=ol.source_id WHERE ol.person_id=? ORDER BY o.name""",
            (person_id,),
        ).fetchall()
        if roles:
            bits.append("<h2>Organization roles on file</h2><ul>")
            for r in roles:
                when = "" if r["is_current"] else " <strong>(historical listing, not current)</strong>"
                note = f" <span class='note'>{esc(plain(r['notes']))}</span>" if r["notes"] else ""
                bits.append(f"<li><a href='{prefix}orgs/{esc(r['slug'])}.html'>{esc(r['name'])}</a>: {esc(r['role'])}{when} "
                            f"<a href='{esc(r['url'])}'>source</a>{note}</li>")
            bits.append("</ul>")

        given = self.endorsements("e.endorser_person_id=?", (person_id,))
        if given:
            bits.append("<h2 id='gave'>Endorsements they have given (2026)</h2>")
            bits.append("<p class='note'>These are personal endorsements, not ones made by any office they hold.</p>")
            bits.append("<ul class='edges'>" + "".join(self.edge_li(e, prefix, "target") for e in given) + "</ul>")
        return "\n".join(bits)

    @staticmethod
    def ballot_order_note() -> str:
        o = json.loads((ROOT / "data" / "harvest" / "2026" / "ballot_order.json").read_text(encoding="utf-8"))
        return (f"Listed in the order they appear on your ballot (source: "
                f"<a href='{esc(o['source_url'])}'>City of Boulder candidate list</a>).")

    # ------------------------------------------------------------ pages
    def write_home(self) -> None:
        mayor = self.candidates("mayor")
        council = self.candidates("council")
        ms = self.q("""SELECT m.*, md.plain_summary FROM measures m JOIN elections e ON e.id=m.election_id
                       LEFT JOIN measure_details md ON md.measure_id=m.id
                       WHERE e.year=2026 AND m.letter IS NOT NULL ORDER BY m.letter""").fetchall()
        import datetime as dt
        import os
        today = dt.date.fromisoformat(os.environ.get("BV_TODAY") or dt.date.today().isoformat())
        codes = "".join(
            f"<li><span class='code'>{esc(m['letter'])}</span><span>{esc(m['title'])}</span></li>" for m in ms)

        def names(rows) -> str:
            # Ballot order as plain text; the whole card is already a link, so no nested anchors.
            return "<ol class='names'>" + "".join(f"<li>{esc(r['full_name'])}</li>" for r in rows) + "</ol>"
        b = [
            "<div class='hero'>",
            "<p class='eyebrow'>City of Boulder · Election Day Tuesday, November 3, 2026</p>",
            "<h1>Everything on your Boulder city ballot, with sources</h1>",
            "<p class='intro'>Who is running, what the measures would do, and who is backing whom. We don't endorse anyone. Every quote, endorsement and dollar figure links to its source.</p>",
            "</div>",
            timeline(today),
            "<h2 class='visually-hidden'>On your city ballot</h2>",
            "<div class='races'>",
            f"<a class='race' href='#mayor'><span class='kicker'>Mayor</span><h3>Mayor</h3>"
            f"<p class='rule'>Rank your choices</p><p>{len(mayor)} candidates for one seat. Mark a 1st choice, and a 2nd, 3rd … if you like.</p>"
            f"{names(mayor)}<span class='go'>See the {len(mayor)} candidates</span></a>",
            f"<a class='race' href='#council'><span class='kicker'>City Council</span><h3>City Council</h3>"
            f"<p class='rule'>Vote for up to five</p><p>{len(council)} candidates for five seats. The five with the most votes win.</p>"
            f"{names(council)}<span class='go'>See the {len(council)} candidates</span></a>",
            f"<a class='race' href='#measures'><span class='kicker'>Ballot measures</span><h3>{len(ms)} city measures</h3>"
            f"<ul class='codes'>{codes}</ul><span class='go'>What Yes and No mean</span></a>",
            "</div>",
            f"<p class='about-line' id='what-this-is'>{esc(HOME_INTRO)}</p>",
            "<p class='note'>Your ballot also has county, state, school board and regional races. This guide covers only the City of Boulder.</p>",
        ]

        def cards(rows, office):
            out = ["<div class='who-list'>"]
            for i, r in enumerate(rows, 1):
                edges = self.endorsements("e.candidacy_id=?", (r["candidacy_id"],))
                inc = " · Incumbent" if r["is_incumbent"] else ""
                label = "Mayor" if office == "mayor" else "City Council"
                bio = esc(first_sentence(r["summary"])) if r["summary"] else "<span class='empty'>No bio on file yet.</span>"
                out.append(
                    f"<article class='card cand-card'>"
                    f"<div class='cand-top'>{face(r['slug'], r['full_name'], '', 96)}<div>"
                    f"<p class='ballot-pos'>Ballot position {i}</p>"
                    f"<h3><a href='people/{esc(r['slug'])}.html'>{esc(r['full_name'])}</a></h3>"
                    f"<p class='office'>{label}{inc}</p></div></div>"
                    f"<p class='bio'>{bio}</p>"
                    f"<p class='meta'><strong>Endorsers:</strong> {self.summary_line(edges, '')}</p>"
                    f"<p class='more'><a href='people/{esc(r['slug'])}.html'>Read about {esc(r['full_name'])}: positions, endorsements, money</a></p>"
                    f"</article>"
                )
            out.append("</div>")
            return "\n".join(out)

        b.append(f"<div class='section-head'><h2 id='mayor'>Who's running for mayor</h2><span class='count'>{len(mayor)} candidates · 1 seat · ranked choice</span></div>")
        b.append(f"<p>{len(mayor)} candidates for one seat. You rank them: mark your 1st choice, then a 2nd, 3rd and so on if you want. "
                 "Some groups endorsed a 1st and 2nd choice, and we show that.</p>"
                 f"<p class='note'>{self.ballot_order_note()}</p>")
        b.append(cards(mayor, "mayor"))
        b.append(f"<div class='section-head'><h2 id='council'>Who's running for city council</h2><span class='count'>{len(council)} candidates · 5 seats · vote for up to 5</span></div>")
        b.append(f"<p>{len(council)} candidates for five seats. Vote for up to five; the five with the most votes win.</p>"
                 f"<p class='note'>{self.ballot_order_note()} “Campaign-listed” means the only source is the candidate's own website.</p>")
        b.append(cards(council, "council"))
        b.append(f"<div class='section-head'><h2 id='measures'>What's on the ballot</h2><span class='count'>{len(ms)} city measures</span></div>")
        b.append("<p>Each measure page starts with what a Yes vote and a No vote mean. Below that are the cost, the full ballot wording, and who supports or opposes it.</p>")
        b.append("<div class='measure-list'>")
        for m in ms:
            b.append(
                f"<article class='card'><p class='kicker'>Ballot measure {esc(m['letter'])}</p>"
                f"<h3><span class='code'>{esc(m['letter'])}</span><a href='measures/2026-{esc(m['letter'].lower())}.html'>{esc(m['title'])}</a></h3>"
                f"<p>{esc(first_sentence(m['plain_summary'] or m['summary']))}</p>"
                f"<p class='more'><a href='measures/2026-{esc(m['letter'].lower())}.html'>What Yes and No mean on {esc(m['letter'])}</a></p></article>"
            )
        b.append("</div>")
        b.append("<h2 id='how-to-use'>How to use this guide</h2>"
                 "<ol class='howto'>"
                 "<li><strong>Pick a candidate.</strong> Each page starts with a short bio, then their positions, forum answers, endorsements and money.</li>"
                 "<li><strong>Read their own words.</strong> The source is under every quote. Tap a long answer to open it.</li>"
                 "<li><strong>Check where an endorsement comes from.</strong> Each one says whether the endorser announced it, it came from a city filing or a news story, or “X campaign lists Y” when only the campaign says so.</li>"
                 "<li><strong>Read a measure.</strong> Each measure page leads with what Yes and No mean.</li>"
                 "<li><strong>Print it.</strong> Every candidate has a <a href='print/index.html'>printable sheet</a>. New to city government? Read <a href='civics.html'>Civics 101</a>.</li>"
                 "</ol>")
        b.append("<h2 id='more'>More in this guide</h2><ul>"
                 "<li><a href='compare.html'>What candidates said at forums</a>, side by side</li>"
                 "<li><a href='orgs.html'>Groups that endorse</a> and how they pick candidates</li>"
                 "<li><a href='finance.html'>Campaign money</a> from city filings</li>"
                 "<li><a href='2026.html'>2026 ballot details</a>: questions asked, forums and a money table</li>"
                 "<li><a href='print/index.html'>Printable sheets for every candidate</a></li>"
                 "<li>Earlier elections: <a href='2025.html'>2025</a>, <a href='2023.html'>2023</a>, <a href='2021.html'>2021</a>, "
                 "<a href='2019.html'>2019</a>, <a href='2017.html'>2017</a></li></ul>")
        from build_llm import AI_CAUTION, AI_PROMPT, home_head
        ask = ("<section class='ask-box' aria-labelledby='ask-h'>"
               "<div class='ask-head'><h2 id='ask-h'>Prefer to ask an AI? Copy this into ChatGPT, Claude, or any assistant:</h2>"
               "<button type='button' class='btn secondary copy' data-copy='ai-prompt' hidden>Copy</button></div>"
               f"<p class='prompt-box' id='ai-prompt'>{esc(AI_PROMPT)}</p>"
               f"<p class='note ask-foot'>{esc(AI_CAUTION)}</p>"
               "<script>(function(){var b=document.querySelector('button.copy');if(!b||!navigator.clipboard)return;"
               "b.hidden=false;b.addEventListener('click',function(){var t=document.getElementById(b.dataset.copy).textContent;"
               "navigator.clipboard.writeText(t).then(function(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy'},2000);});});})();</script>"
               "</section>")
        b.insert(b.index("</div>") + 1, ask)  # right after the hero, before key dates
        (self.out / "index.html").write_text(
            self.page("Boulder 2026 election guide", "\n".join(b), year=2026, current=None,
                      head_extra=home_head()), encoding="utf-8")

    def write_orgs(self) -> None:
        (self.out / "orgs").mkdir(exist_ok=True)
        rows = self.q("""SELECT o.*, op.* FROM org_profiles op JOIN organizations o ON o.id=op.org_id
                         ORDER BY o.name""").fetchall()
        idx = ["<h1>Organizations that endorse</h1>",
               "<p class='lede'>Groups and committees that took a side in the 2026 city election, plus a few voters often ask about. "
               "Each page says who they are, how they pick candidates, where their money comes from, and whom they endorsed.</p>",
               "<p class='note'>Committees register with the city clerk and must report their donors. "
               "We list them apart from the groups that sponsor them.</p>"]
        for kind, label in (("organization", "Organizations"), ("committee", "Registered committees"), ("newspaper", "Newspapers")):
            chunk = [r for r in rows if r["endorser_kind"] == kind]
            if not chunk:
                continue
            idx.append(f"<h2>{label}</h2>")
            for r in chunk:
                n = self.q("SELECT COUNT(*) FROM endorsements WHERE endorser_org_id=? AND status='published'", (r["org_id"],)).fetchone()[0]
                note = f"{n} position{'s' if n != 1 else ''} on file for 2026" if n else "no 2026 City of Boulder position on file"
                idx.append(f"<div class='card'><h3><a href='orgs/{esc(r['slug'])}.html'>{esc(r['name'])}</a></h3>"
                           f"<p>{esc(first_sentence(r['summary']))}</p><div class='meta'>{note}</div></div>")
            self._write_org_pages(chunk)
        (self.out / "orgs.html").write_text(self.page("Endorsing organizations", "\n".join(idx), year=2026, current="learn"), encoding="utf-8")

    def _write_org_pages(self, rows) -> None:
        from build import human_label  # late import: build.py imports this module
        for r in rows:
            oid = r["org_id"]

            def srclink(sid):
                if not sid:
                    return ""
                u = self.q("SELECT url FROM sources WHERE id=?", (sid,)).fetchone()[0]
                return f" <a href='{esc(u)}'>source</a>"

            b = ["<p class='crumb'><a href='../index.html'>2026 guide</a> › <a href='../learn.html'>Learn</a> › <a href='../orgs.html'>Endorsing organizations</a></p>", f"<h1>{esc(r['name'])}</h1>"]
            meta = [esc(human_label(r["endorser_kind"]))]
            if r["legal_form"]:
                meta.append(esc(r["legal_form"]))
            if r["founded"]:
                meta.append(f"founded {r['founded']}")
            b.append(f"<p class='note'>{' · '.join(meta)}</p>")
            if r["website"]:
                b.append(f"<p><a href='{esc(r['website'])}'>{esc(r['website'])}</a></p>")
            b.append("<h2>Who they are</h2>")
            b.append(f"<p>{esc(r['summary'])}</p>")
            if r["mission_text"]:
                b.append(f"<p>In their words: <q>{esc(r['mission_text'])}</q>{srclink(r['mission_source_id'])}</p>")
            rel = self.q("""SELECT o.slug, o.name, x.relation, x.source_id, 'out' AS dir FROM org_relations x JOIN organizations o ON o.id=x.related_org_id WHERE x.org_id=?
                            UNION ALL
                            SELECT o.slug, o.name, x.relation, x.source_id, 'in' FROM org_relations x JOIN organizations o ON o.id=x.org_id WHERE x.related_org_id=?""",
                         (oid, oid)).fetchall()
            if rel:
                b.append("<ul>")
                for x in rel:
                    if x["dir"] == "out":
                        b.append(f"<li>This is the {esc(x['relation'])} <a href='{esc(x['slug'])}.html'>{esc(x['name'])}</a>.{srclink(x['source_id'])}</li>")
                    else:
                        b.append(f"<li><a href='{esc(x['slug'])}.html'>{esc(x['name'])}</a> is the {esc(x['relation'])} this group.{srclink(x['source_id'])}</li>")
                b.append("</ul>")
            lead = self.q("""SELECT ol.*, s.url, p.slug AS pslug FROM org_leadership ol JOIN sources s ON s.id=ol.source_id
                             LEFT JOIN people p ON p.id=ol.person_id WHERE ol.org_id=? ORDER BY ol.is_current DESC, ol.id""",
                          (oid,)).fetchall()
            if lead:
                b.append("<h2>Leadership on file</h2><ul>")
                for l in lead:
                    nm = f"<a href='../people/{esc(l['pslug'])}.html'>{esc(l['name'])}</a>" if l["pslug"] else esc(l["name"])
                    when = "" if l["is_current"] else " <strong>(historical listing, not current)</strong>"
                    note = f" <span class='note'>{esc(plain(l['notes']))}</span>" if l["notes"] else ""
                    b.append(f"<li>{nm} — {esc(l['role'])}{when} <a href='{esc(l['url'])}'>source</a>{note}</li>")
                b.append("</ul>")
            b.append("<h2>Money</h2>")
            if r["funding_text"]:
                b.append(f"<p>{esc(r['funding_text'])}{srclink(r['funding_source_id'])}</p>")
            else:
                b.append("<p class='empty'>No funding information verified.</p>")
            b.append("<h2>How they decide</h2>")
            if r["process_text"]:
                b.append(f"<p>{esc(r['process_text'])}{srclink(r['process_source_id'])}</p>")
            else:
                b.append("<p class='empty'>No published endorsement process found.</p>")
            edges = self.endorsements("e.endorser_org_id=?", (oid,))
            b.append("<h2 id='endorsements'>2026 positions</h2>")
            if edges:
                b.append(PROV_LEGEND)
                cands = [e for e in edges if e["candidacy_id"]]
                city = [e for e in edges if e["measure_id"]]
                other = [e for e in edges if e["target_label"]]
                if cands:
                    b.append("<h3>Candidates</h3><ul class='edges'>" + "".join(self.edge_li(e, "../", "target") for e in cands) + "</ul>")
                if city:
                    b.append("<h3>City measures</h3><ul class='edges'>" + "".join(self.edge_li(e, "../", "target") for e in city) + "</ul>")
                if other:
                    b.append("<h3>Other ballot items</h3><ul class='edges'>" + "".join(self.edge_li(e, "../", "target") for e in other) + "</ul>")
                b.append("<p class='note'>These are positions this group, or a campaign where labelled, has published. "
                         "A race with nothing listed doesn't mean the group is against anyone.</p>")
            else:
                b.append("<p class='empty'>No 2026 City of Boulder positions on file.</p>")
            past = self.q("""SELECT pe.*, s.url FROM org_past_endorsements pe JOIN sources s ON s.id=pe.source_id
                             WHERE pe.org_id=? ORDER BY pe.year DESC, pe.id""", (oid,)).fetchall()
            if past:
                b.append("<h2>Earlier endorsements</h2><ul>")
                for p in past:
                    b.append(f"<li>{p['year']}: {esc(p['label'])} <a href='{esc(p['url'])}'>source</a></li>")
                b.append("</ul>")
            srcs = self.q("""SELECT DISTINCT s.url FROM profile_sources ps JOIN sources s ON s.id=ps.source_id WHERE ps.org_id=?""",
                          (oid,)).fetchall()
            if srcs:
                b.append("<h2>Profile sources</h2><ul class='note'>" + "".join(
                    f"<li><a href='{esc(s['url'])}'>{esc(s['url'])}</a></li>" for s in srcs) + "</ul>")
            b.append(f"<p class='note'>Profile compiled {esc(r['as_of'])}.</p>")
            (self.out / "orgs" / f"{r['slug']}.html").write_text(
                self.page(r["name"], panelize_sections("\n".join(b)), prefix="../", year=2026, current="learn"), encoding="utf-8")

    def write_measures(self) -> None:
        (self.out / "measures").mkdir(exist_ok=True)
        rows = self.q("""SELECT m.*, md.*, s.url AS lang_url FROM measures m JOIN measure_details md ON md.measure_id=m.id
                         LEFT JOIN sources s ON s.id=md.language_source_id ORDER BY m.letter""").fetchall()
        lines = self.q("""SELECT rl.*, s.url, s.title FROM reported_lines rl JOIN sources s ON s.id=rl.source_id""").fetchall()
        for m in rows:
            def srclink(sid):
                if not sid:
                    return ""
                u = self.q("SELECT url FROM sources WHERE id=?", (sid,)).fetchone()[0]
                return f" <a href='{esc(u)}'>source</a>"

            b = ["<p class='crumb'><a href='../index.html'>2026 guide</a> › <a href='../index.html#measures'>Measures</a> › "
                 f"{esc(m['letter'])}</p>",
                 f"<p class='kicker'>City of Boulder ballot measure {esc(m['letter'])} · 2026</p>",
                 f"<h1><span class='code code-lg'>{esc(m['letter'])}</span> {esc(m['title'])}</h1>",
                 f"<dl class='yesno'><div><dt>A YES vote means</dt><dd>{esc(m['yes_means'])}</dd></div>"
                 f"<div><dt>A NO vote means</dt><dd>{esc(m['no_means'])}</dd></div></dl>",
                 f"<h2 id='summary'>In plain words</h2><p>{esc(m['plain_summary'])}</p>"]
            head_bits = b[:4]
            head = "\n".join(head_bits)
            if m["fiscal_text"]:
                b.append(f"<h2>Money</h2><p>{esc(m['fiscal_text'])}{srclink(m['fiscal_source_id'])}</p>")
            if m["council_vote_text"]:
                b.append(f"<h2>How it got on the ballot</h2><p>{esc(m['council_vote_text'])}{srclink(m['council_vote_source_id'])}</p>")
            b.append("<h2>Full ballot text</h2>")
            b.append(f"<p><a href='{esc(m['lang_url'])}'>Official text on the City of Boulder website</a></p>")
            b.append(f"<details class='fold'><summary>Read the full ballot wording here</summary>"
                     f"<blockquote class='answer' style='white-space:pre-line'>{esc(m['ballot_language'])}</blockquote></details>")
            edges = self.endorsements("e.measure_id=?", (m["measure_id"],))
            b.append("<h2 id='positions'>Who supports it, who opposes it</h2>")
            b.append(PROV_LEGEND)
            for pos, label in (("endorse", "Supports"), ("oppose", "Opposes")):
                chunk = [e for e in edges if e["position"] == pos]
                b.append(f"<h3>{label}</h3>")
                if chunk:
                    b.append("<ul class='edges'>" + "".join(
                        f"<li>{self.endorser_name(e, '../')}{self.prov_line(e)}</li>" for e in chunk) + "</ul>")
                else:
                    b.append("<p class='empty'>None found so far. There may still be "
                             + ("supporters" if pos == "endorse" else "opponents") + ".</p>")
            mlines = [x for x in lines if x["measure_id"] == m["measure_id"]]
            if mlines:
                b.append("<h3>What reporters said about the candidates</h3>")
            for ln in mlines:
                b.append(f"<p class='card'>{esc(ln['reporter'])} reported ({esc(ln['reported_on'])}): {esc(ln['text'])} "
                         f"<a href='{esc(ln['url'])}'>{esc(ln['title'])}</a><span class='note'> This is the reporter's summary, "
                         f"not each candidate's own answer, so we don't mark anyone yes or no from it.</span></p>")
            extra = getattr(self, "measure_extra", None)
            if extra:
                b.append(extra(m["letter"], "../"))
            unknowns = json.loads(m["unknowns"] or "[]")
            if unknowns:
                b.append("<h2>What we don't know yet</h2><ul>" + "".join(f"<li>{esc(u)}</li>" for u in unknowns) + "</ul>")
            (self.out / "measures" / f"2026-{m['letter'].lower()}.html").write_text(
                self.page(f"{m['letter']}: {m['title']}", head + panelize_sections("\n".join(b[len(head_bits):])), prefix="../", year=2026, current="measures"), encoding="utf-8")

    def write_civics(self, md: str) -> None:
        body = md_to_html(md)
        body += "<p class='note'>Written September 2026. Each paragraph links its source.</p>"
        (self.out / "civics.html").write_text(self.page("Civics 101", body, year=2026, current="learn"), encoding="utf-8")

    def reported_lines_for_question(self, qid: int, prefix: str) -> str:
        lines = self.q("""SELECT rl.*, s.url, s.title FROM reported_lines rl JOIN sources s ON s.id=rl.source_id
                          WHERE rl.question_id=?""", (qid,)).fetchall()
        if not lines:
            return ""
        out = ["<h2>What was reported</h2>"]
        for ln in lines:
            out.append(f"<div class='card'><p>{esc(ln['reporter'])} ({esc(ln['reported_on'])}): {esc(ln['text'])}</p>"
                       f"<p class='note'><a href='{esc(ln['url'])}'>{esc(ln['title'])}</a></p></div>")
        out.append("<p class='note'>This is one reporter's summary, not each candidate's own answer, "
                   "so we don't mark anyone yes or no from it. Each candidate's own words are on their page.</p>")
        return "\n".join(out)
