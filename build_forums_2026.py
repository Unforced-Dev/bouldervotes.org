"""2026 candidate-forum pages: answer cards on candidate pages, one page per
forum, "same question, every candidate" comparison pages, and the forum
section on the 2J / 2K measure pages.

Trust rules rendered here:
  * Every quote carries the standard notice that it comes from an automatic
    transcript, and a "watch at m:ss" link to that moment in the recording.
  * A speaker identified only from speaking order (attribution confidence
    "medium") carries a visible caveat on every card.
  * A yes/no label appears only where tools/approve_forums_2026.py
    FORUM_STANCES set one. No scores, no rankings, no summary of who is right.
  * Held claims are not in the answers table, so they cannot render.
"""
from __future__ import annotations

from build_plain import plain
import html
import json
import re
import sqlite3
from pathlib import Path

H2026 = Path(__file__).resolve().parent / "data" / "harvest" / "2026"

TRANSCRIPT_NOTE = "Automatic transcript; check the recording."
MEDIUM_CAVEAT = "Speaker identified from speaking order; the moderator did not name them."
COMPARE_MIN = 3  # a question needs at least this many candidates to get a comparison page

TOPIC_LABELS = [
    ("housing", "Housing"),
    ("budget/bond 2K", "Budget, debt and the 2K bond"),
    ("transportation", "Transportation"),
    ("growth/development", "Growth and development"),
    ("climate", "Climate and wildfire"),
    ("arts", "Arts and culture"),
    ("homelessness/safety", "Homelessness and public safety"),
    ("labor", "Workers and wages"),
    ("other", "Other topics"),
]

FORUM_CSS = """
.caveat { color: var(--mark); font-size: 0.9rem; margin: 0.2rem 0; }
.forum-answer .who { font-weight: 700; }
table.grid td:first-child { width: 28%; }
table.grid blockquote.answer { margin: 0.2rem 0; }
"""


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s))


def ts(sec: int) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def nice_date(iso: str) -> str:
    months = ["January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December"]
    y, m, d = iso.split("-")
    return f"{months[int(m) - 1]} {int(d)}, {y}"


def parse_notes(notes: str) -> dict:
    out = {}
    for part in (notes or "").split(" | "):
        if ": " in part:
            k, v = part.split(": ", 1)
            out[k.strip()] = v.strip()
    return out


class Forums2026:
    def __init__(self, con: sqlite3.Connection, out: Path, page):
        self.con = con
        self.out = out
        self.page = page
        self.doc = json.loads((H2026 / "forums.json").read_text(encoding="utf-8"))
        self.forums = {f["slug"]: f for f in self.doc["forums"]}
        self.rows = self._load()
        # Official 2026 ballot order: mayor race first, then council (ballot_order.json via seed).
        self.ballot_rank = {r[0]: r[1] for r in con.execute(
            """SELECT c.person_id, MIN(CASE o.slug WHEN 'mayor' THEN 0 ELSE 100 END + c.ballot_position)
               FROM candidacies c JOIN races r ON r.id=c.race_id JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id
               WHERE e.year=2026 AND c.ballot_position IS NOT NULL GROUP BY c.person_id""")}

    # ------------------------------------------------------------ data
    def _load(self) -> list[dict]:
        rows = self.con.execute(
            """SELECT a.id, a.stance, a.verbatim, a.notes, a.answered_on,
                      p.id AS person_id, p.slug AS pslug, p.full_name, p.sort_name,
                      q.id AS qid, q.prompt, q.issue_slug, i.name AS issue_name,
                      e.slug AS event, e.name AS event_name, e.starts_on,
                      s.url AS source_url, s.title AS source_title
               FROM answers a
               JOIN people p ON p.id=a.person_id
               JOIN questions q ON q.id=a.question_id
               LEFT JOIN issues i ON i.slug=q.issue_slug
               JOIN events e ON e.id=a.event_id
               JOIN sources s ON s.id=a.source_id
               WHERE a.kind='forum' AND s.kind='video' AND q.year=2026"""
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            n = parse_notes(r["notes"])
            d["watch"] = n["Watch"]
            d["confidence"] = n["Attribution confidence"]
            d["claim"] = n["Claim"]
            d["segment"] = n.get("Segment", "")
            d["topic"] = n.get("Topic", "other")
            d["measure"] = n.get("Measure")
            d["tnote"] = n.get("Transcript note")
            d["snote"] = n.get("Stance note")
            m = re.search(r"[?&]v=([\w-]+).*?[?&]t=(\d+)s", d["watch"])
            if m is None:
                raise SystemExit(f"bad watch link on answer {d['id']}")
            d["vid"], d["start"] = m.group(1), int(m.group(2))
            f = self.forums[d["event"]]
            vids = [x["youtube_id"] for x in f["recordings"]]
            d["order"] = (vids.index(d["vid"]), d["start"], d["claim"])
            qs = [x["prompt"] for x in f["questions"]]
            d["qidx"] = qs.index(d["prompt"])
            d["stance_about"] = f["questions"][d["qidx"]]["stance_about"]
            out.append(d)
        out.sort(key=lambda d: (d["starts_on"], d["order"]))
        return out

    def compare_slug(self, event: str, qidx: int) -> str:
        return f"{event}-q{qidx + 1:02d}"

    def question_rows(self, event: str, qidx: int) -> list[dict]:
        return [r for r in self.rows if r["event"] == event and r["qidx"] == qidx]

    def compared(self) -> list[tuple[str, int]]:
        keys = []
        for slug, f in self.forums.items():
            for qi in range(len(f["questions"])):
                if len({r["person_id"] for r in self.question_rows(slug, qi)}) >= COMPARE_MIN:
                    keys.append((slug, qi))
        return keys

    # ------------------------------------------------------------ pieces
    def stance_html(self, r: dict) -> str:
        if r["stance"] in ("yes", "no", "mixed"):
            word = {"yes": "Yes", "no": "No", "mixed": "Mixed"}[r["stance"]]
            extra = f" <span class='note'>{esc(r['snote'])}</span>" if r["snote"] else ""
            return (f"<p><span class='stance {r['stance']}'>{word}</span> on {esc(r['stance_about'])}, "
                    f"in the candidate's own words below.{extra}</p>")
        if r["stance_about"] and r["snote"]:
            return f"<p class='note'>No yes/no label: {esc(r['snote'])}</p>"
        return ""

    def tail(self, r: dict) -> str:
        bits = []
        if r["confidence"] == "medium":
            bits.append(f"<p class='caveat'>{MEDIUM_CAVEAT}</p>")
        if r["tnote"]:
            bits.append(f"<p class='note'>Transcript note: {esc(r['tnote'])}</p>")
        bits.append(
            f"<p class='note'>{TRANSCRIPT_NOTE} <a href='{esc(r['watch'])}'>Watch at {ts(r['start'])}</a> · "
            f"<a href='{esc(r['source_url'])}'>{esc(r['source_title'])}</a></p>")
        return "".join(bits)

    @staticmethod
    def quote(r: dict) -> str:
        return f"<blockquote class='answer'>{esc(' '.join(r['verbatim'].split()))}</blockquote>"

    def card(self, r: dict, prefix: str, *, show_who: bool, show_question: bool, show_forum: bool) -> str:
        f = self.forums[r["event"]]
        meta = ["2026", "forum"]
        if r["issue_name"]:
            meta.append(esc(r["issue_name"]))
        out = [f"<div class='card forum-answer' data-claim='{esc(r['claim'])}' data-confidence='{esc(r['confidence'])}'>",
               f"<div class='meta'>{' · '.join(meta)}</div>"]
        if show_forum:
            out.append(f"<p class='note'><a href='{prefix}forums/{esc(r['event'])}.html'>{esc(f['short'])}</a> · "
                       f"{nice_date(f['date'])}</p>")
        if show_who:
            out.append(f"<p class='who'><a href='{prefix}people/{esc(r['pslug'])}.html'>{esc(r['full_name'])}</a></p>")
        if show_question:
            out.append(f"<h3>{esc(r['prompt'])}</h3>")
        out.append(self.stance_html(r))
        out.append(self.quote(r))
        out.append(self.tail(r))
        out.append("</div><!-- /forum-answer -->")
        return "".join(out)

    # ------------------------------------------------------------ candidate pages
    def person_section(self, person_id: int, prefix: str = "../") -> str:
        mine = [r for r in self.rows if r["person_id"] == person_id]
        if not mine:
            return ""
        b = ["<h2 id='forums'>At the forums, in their own words</h2>",
             "<p class='note'>Short passages from 2026 candidate forums, grouped by topic, each with the question asked "
             "and a link to that moment in the recording. " + TRANSCRIPT_NOTE + " A topic with no quote means we have "
             "no quote, not a position. <a href='" + prefix + "compare.html'>Compare answers to the same question</a>.</p>"]
        labels = dict(TOPIC_LABELS)
        for key, label in TOPIC_LABELS:
            chunk = [r for r in mine if r["topic"] == key]
            if not chunk:
                continue
            b.append(f"<h3>{esc(label)}</h3>")
            for r in chunk:
                b.append(self.card(r, prefix, show_who=False, show_question=True, show_forum=True))
        stray = [r for r in mine if r["topic"] not in labels]
        for r in stray:
            b.append(self.card(r, prefix, show_who=False, show_question=True, show_forum=True))
        return "\n".join(b)

    # ------------------------------------------------------------ forum pages
    def write_forum_pages(self) -> None:
        (self.out / "forums").mkdir(exist_ok=True)
        compared = set(self.compared())
        for slug, f in self.forums.items():
            b = ["<p class='crumb'><a href='../forums.html'>Forums</a> · <a href='../compare.html'>Same question, every candidate</a></p>",
                 f"<h1>{esc(f['name'])}</h1>",
                 f"<p class='lede'>{nice_date(f['date'])}"
                 + (f" · {esc(f['venue'])}" if f["venue"] else "") + "</p>",
                 f"<p>Hosted by {esc(', '.join(f['hosts']))}.</p>",
                 f"<p class='note'>{esc(plain(f['notes']))}</p>",
                 "<h2>Recordings</h2><ul>"]
            for rec in f["recordings"]:
                url = f"https://www.youtube.com/watch?v={rec['youtube_id']}"
                segs = ""
                if len(rec["segments"]) > 1:
                    segs = " — " + ", ".join(
                        f"<a href='{url}&amp;t={s['start']}s'>{esc(s['label'])} from {ts(s['start'])}</a>"
                        for s in rec["segments"])
                extra = " <span class='note'>(no quotes taken from this part)</span>" if rec.get("no_quotes") else ""
                b.append(f"<li><a href='{url}'>{esc(rec['title'])}</a> ({esc(rec['uploader'])}){segs}{extra}</li>")
            b.append("</ul>")
            b.append(f"<p class='note'>Date: {esc(plain(f['date_source']))}</p>")
            if f.get("absent_statement_read"):
                b.append("<p class='note'>Did not attend; the moderator read their submitted statement: "
                         + esc(", ".join(f["absent_statement_read"])) + ".</p>")
            b.append("<h2>Questions and answers, in speaking order</h2>")
            b.append("<p class='note'>Each question, then each candidate we quote, in the order they spoke. These are "
                     "short passages, not full answers: use the watch link to hear the whole answer. " + TRANSCRIPT_NOTE +
                     " A candidate not listed under a question was not quoted by us on it; that is not a position.</p>")
            for qi, q in enumerate(f["questions"]):
                rows = self.question_rows(slug, qi)
                if not rows:
                    continue
                b.append(f"<h3 id='q{qi + 1:02d}'>{esc(q['prompt'])}</h3>")
                links = []
                if q["issue_slug"]:
                    links.append(f"<a href='../issues/{esc(q['issue_slug'])}-2026.html'>issue page</a>")
                if (slug, qi) in compared:
                    links.append(f"<a href='../compare/{self.compare_slug(slug, qi)}.html'>side by side</a>")
                if links:
                    b.append(f"<p class='note'>{' · '.join(links)}</p>")
                for r in rows:
                    b.append(self.card(r, "../", show_who=True, show_question=False, show_forum=False))
            (self.out / "forums" / f"{slug}.html").write_text(
                self.page(f["short"] + " (" + f["date"] + ")", "\n".join(b), prefix="../", year=2026), encoding="utf-8")

    def forum_index_html(self) -> str:
        b = ["<h2>2026 forums: every quoted answer</h2>",
             "<p><a href='compare.html'>Same question, every candidate</a> — forum answers side by side.</p><ul>"]
        for slug, f in sorted(self.forums.items(), key=lambda kv: kv[1]["date"]):
            n = sum(1 for r in self.rows if r["event"] == slug)
            b.append(f"<li><a href='forums/{esc(slug)}.html'>{esc(f['short'])}</a> · {nice_date(f['date'])} · "
                     f"{n} quoted answer{'s' if n != 1 else ''}</li>")
        b.append("</ul>")
        return "\n".join(b)

    # ------------------------------------------------------------ comparison
    def write_compare(self) -> None:
        (self.out / "compare").mkdir(exist_ok=True)
        label = ("<p class='note'><strong>How to read this.</strong> Each page puts one forum question next to every "
                 "candidate we quote answering it, in the order their names appear on the ballot. There are no scores and no summary of who is "
                 "right. A yes/no appears only where the candidate said yes or no (support/oppose) in so many words; "
                 "a blank means they did not, or hedged — read the quote. " + TRANSCRIPT_NOTE + "</p>")
        idx = ["<h1>Same question, every candidate</h1>",
               "<p class='lede'>Questions asked at 2026 candidate forums that three or more candidates answered, "
               "with each candidate's own words side by side.</p>", label]
        cur = None
        for slug, qi in self.compared():
            f = self.forums[slug]
            if slug != cur:
                idx.append(f"<h2>{esc(f['short'])} · {nice_date(f['date'])}</h2>")
                cur = slug
            q = f["questions"][qi]
            rows = self.question_rows(slug, qi)
            n = len({r["person_id"] for r in rows})
            idx.append(f"<a class='choice' href='compare/{self.compare_slug(slug, qi)}.html'>{esc(q['prompt'])}"
                       f"<span class='meta'>{n} candidates</span></a>")
            self._write_compare_page(slug, qi, label)
        (self.out / "compare.html").write_text(
            self.page("Same question, every candidate", "\n".join(idx), year=2026), encoding="utf-8")

    def _write_compare_page(self, slug: str, qi: int, label: str) -> None:
        f = self.forums[slug]
        q = f["questions"][qi]
        rows = self.question_rows(slug, qi)
        people: list[int] = []
        for r in rows:
            if r["person_id"] not in people:
                people.append(r["person_id"])
        people.sort(key=lambda pid: (self.ballot_rank.get(pid, 999),
                                     next(r["sort_name"] for r in rows if r["person_id"] == pid)))
        has_stance = any(r["stance"] for r in rows)
        b = ["<p class='crumb'><a href='../compare.html'>Same question, every candidate</a> · "
             f"<a href='../forums/{esc(slug)}.html#q{qi + 1:02d}'>{esc(f['short'])}</a></p>",
             f"<h1>{esc(q['prompt'])}</h1>",
             f"<p class='note'>Asked at the {esc(f['name'])}, {nice_date(f['date'])}.</p>", label]
        head = "<tr><th>Candidate</th>" + ("<th>Said yes/no</th>" if has_stance else "") + "<th>In their words</th></tr>"
        body = [head]
        for pid in people:
            mine = [r for r in rows if r["person_id"] == pid]
            r0 = mine[0]
            cell = []
            for r in mine:
                cell.append(self.quote(r))
                cell.append(self.tail(r))
            row = f"<tr data-person='{esc(r0['pslug'])}'><td><a href='../people/{esc(r0['pslug'])}.html'>{esc(r0['full_name'])}</a></td>"
            if has_stance:
                st = next((r["stance"] for r in mine if r["stance"]), None)
                row += (f"<td><span class='stance {st}'>{st.capitalize()}</span></td>" if st else "<td></td>")
            row += f"<td>{''.join(cell)}</td></tr>"
            body.append(row)
        b.append(f"<table class='grid'>{''.join(body)}</table>")
        if has_stance:
            b.append(f"<p class='note'>Yes/no is about {esc(q['stance_about'])}, and appears only where the candidate "
                     "said it explicitly. A blank is not a position either way.</p>")
        b.append("<p class='note'>Candidates not listed were not quoted by us on this question — absent, not called on, "
                 "or not captured in our extract. That is not a position.</p>")
        (self.out / "compare" / f"{self.compare_slug(slug, qi)}.html").write_text(
            self.page(q["prompt"][:70], "\n".join(b), prefix="../", year=2026), encoding="utf-8")

    def issue_answer(self, answer_id: int) -> str:
        """Body of an issue-page card for a forum-video answer ('' if not one)."""
        r = next((x for x in self.rows if x["id"] == answer_id), None)
        if r is None:
            return ""
        f = self.forums[r["event"]]
        return (f"<p class='note'><a href='../forums/{esc(r['event'])}.html'>{esc(f['short'])}</a> · "
                f"{nice_date(f['date'])}</p>" + self.stance_html(r) + self.quote(r) + self.tail(r))

    # ------------------------------------------------------------ measures
    def measure_section(self, letter: str, prefix: str = "../") -> str:
        rows = [r for r in self.rows if r["measure"] == letter]
        if not rows:
            return ""
        b = ["<h2 id='forums'>What candidates said at forums</h2>",
             "<p class='note'>Candidates' own words when asked about " + esc(letter) + " at 2026 forums, in speaking "
             "order. A yes/no label appears only where the candidate said yes or no in so many words; otherwise read "
             "the quote. " + TRANSCRIPT_NOTE + " This is not an endorsement tally.</p>"]
        cur = None
        for r in rows:
            if r["event"] != cur:
                f = self.forums[r["event"]]
                b.append(f"<h3>{esc(f['short'])} · {nice_date(f['date'])}</h3>")
                b.append(f"<p class='note'>Asked: {esc(r['prompt'])}</p>")
                cur = r["event"]
            b.append(self.card(r, prefix, show_who=True, show_question=False, show_forum=False))
        return "\n".join(b)
