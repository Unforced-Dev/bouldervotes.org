"""Integrity + trust-rule tests for the 2026 evidence graph.

Run after `python3 seed.py && python3 build.py`:
    python3 -m unittest
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "bouldervotes.db"
DOCS = ROOT / "docs"
H = ROOT / "data" / "harvest" / "2026"

AUDIT_HELD = {"E69", "E71", "E77", "E139", "E235"}
HELD_STATEMENTS = {
    ("Jameson Goldstein", "privacy"), ("Aquiles La Grave", "budget"), ("Rachel Rose Isaacson", "housing"),
    ("Tara Winer", "budget"), ("Ryan Schuchard", "climate"), ("Jill Grano", "housing"), ("Dave Martus", "budget"),
}


_CON = None


def db():
    global _CON
    if _CON is None:
        _CON = sqlite3.connect(DB)
        _CON.row_factory = sqlite3.Row
    return _CON


def tearDownModule():
    if _CON is not None:
        _CON.close()


class ProvSpans(HTMLParser):
    """Collect every provenance span (data-edge) and its visible text."""

    def __init__(self):
        super().__init__()
        self.spans: list[dict] = []
        self._stack: list[dict | None] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "span" and "data-edge" in a:
            rec = {"edge": a["data-edge"], "prov": a.get("data-provenance"), "text": ""}
            self.spans.append(rec)
            self._stack.append(rec)
        elif tag == "span":
            self._stack.append(None)

    def handle_endtag(self, tag):
        if tag == "span" and self._stack:
            self._stack.pop()

    def handle_data(self, data):
        for rec in self._stack:
            if rec is not None:
                rec["text"] += data


class TestData(unittest.TestCase):
    def test_harvest_is_committed_json(self):
        for name in ("candidates", "statements", "endorsements", "organizations", "measures"):
            self.assertTrue((H / f"{name}.json").exists(), name)
        src = (ROOT / "ingest_2026.py").read_text()
        self.assertIn("data\" / \"harvest\" / \"2026\"", src)

    def test_foreign_keys(self):
        con = db()
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        # explicit joins for the new tables
        for sql in (
            "SELECT COUNT(*) FROM endorsements e LEFT JOIN sources s ON s.id=e.source_id WHERE s.id IS NULL",
            "SELECT COUNT(*) FROM endorsements e LEFT JOIN organizations o ON o.id=e.endorser_org_id WHERE e.endorser_org_id IS NOT NULL AND o.id IS NULL",
            "SELECT COUNT(*) FROM endorsements e LEFT JOIN people p ON p.id=e.endorser_person_id WHERE e.endorser_person_id IS NOT NULL AND p.id IS NULL",
            "SELECT COUNT(*) FROM endorsements e LEFT JOIN candidacies c ON c.id=e.candidacy_id WHERE e.candidacy_id IS NOT NULL AND c.id IS NULL",
            "SELECT COUNT(*) FROM endorsements e LEFT JOIN measures m ON m.id=e.measure_id WHERE e.measure_id IS NOT NULL AND m.id IS NULL",
            "SELECT COUNT(*) FROM statements st LEFT JOIN candidacies c ON c.id=st.candidacy_id WHERE c.id IS NULL",
            "SELECT COUNT(*) FROM statements st LEFT JOIN sources s ON s.id=st.source_id WHERE s.id IS NULL",
        ):
            self.assertEqual(con.execute(sql).fetchone()[0], 0, sql)

    def test_source_urls_unique(self):
        con = db()
        dup = con.execute("SELECT url, COUNT(*) FROM sources GROUP BY url HAVING COUNT(*)>1").fetchall()
        self.assertEqual(dup, [])

    def test_all_19_candidates(self):
        con = db()
        rows = con.execute(
            """SELECT p.full_name, o.slug FROM candidacies c JOIN people p ON p.id=c.person_id
               JOIN races r ON r.id=c.race_id JOIN elections e ON e.id=r.election_id
               JOIN offices o ON o.id=r.office_id WHERE e.year=2026"""
        ).fetchall()
        self.assertEqual(len(rows), 19)
        self.assertEqual(sum(1 for r in rows if r["slug"] == "mayor"), 6)
        self.assertEqual(sum(1 for r in rows if r["slug"] == "council"), 13)
        names = {r["full_name"] for r in rows}
        self.assertIn("Dave Martus", names)
        self.assertNotIn("David Martus", names)
        research = {c["name"] for c in json.loads((H / "candidates.json").read_text())}
        self.assertEqual(research, names)
        prof = con.execute("SELECT COUNT(*) FROM candidate_profiles").fetchone()[0]
        self.assertEqual(prof, 19)
        for r in rows:
            self.assertTrue((DOCS / "people" / (r["full_name"].lower().replace(" ", "-") + ".html")).exists(), r["full_name"])

    def test_every_endorsement_has_source(self):
        con = db()
        bad = con.execute(
            """SELECT e.id FROM endorsements e LEFT JOIN sources s ON s.id=e.source_id
               WHERE s.url IS NULL OR s.url NOT LIKE 'http%'"""
        ).fetchall()
        self.assertEqual(bad, [])
        for e in json.loads((H / "endorsements.json").read_text()):
            self.assertTrue(e["source_url"].startswith("http"), e["id"])
            self.assertIn(e["provenance"], {"endorser_statement", "campaign_claim", "filing", "news_report"})

    def test_every_statement_has_source_and_publisher(self):
        con = db()
        bad = con.execute(
            """SELECT st.id FROM statements st LEFT JOIN sources s ON s.id=st.source_id
               WHERE s.url IS NULL OR s.url NOT LIKE 'http%' OR COALESCE(st.publisher,'')='' OR COALESCE(st.speaker,'')=''"""
        ).fetchall()
        self.assertEqual(bad, [])

    def test_held_statements(self):
        con = db()
        held = con.execute(
            """SELECT p.full_name, st.topic, s.url FROM statements st JOIN people p ON p.id=st.person_id
               JOIN sources s ON s.id=st.source_id WHERE st.status='held'"""
        ).fetchall()
        self.assertEqual({(r[0], r[1]) for r in held}, HELD_STATEMENTS)
        self.assertTrue(all("dailycamera.com" in r[2] for r in held))

    def test_audit_held_edges_are_campaign_claims(self):
        con = db()
        rows = {r["id"]: r for r in con.execute("SELECT * FROM endorsements WHERE id IN (%s)" % ",".join("?" * len(AUDIT_HELD)), tuple(AUDIT_HELD))}
        self.assertEqual(set(rows), AUDIT_HELD)
        for r in rows.values():
            self.assertEqual(r["provenance"], "campaign_claim", r["id"])
            self.assertTrue(r["claimed_by"])

    def test_ranked_choice_ranks_kept(self):
        con = db()
        got = {r[0]: r[1] for r in con.execute("SELECT id, rank FROM endorsements WHERE rank IS NOT NULL")}
        reviewed = {"E0": 1, "E1": 2, "E46": 1, "E47": 2, "E204": 1}
        self.assertEqual({key: got.get(key) for key in reviewed}, reviewed)
        self.assertTrue(all(type(rank) is int and rank > 0 for rank in got.values()))

    def test_no_bond_fanout(self):
        con = db()
        n = con.execute(
            """SELECT COUNT(*) FROM answers a JOIN questions q ON q.id=a.question_id
               JOIN sources s ON s.id=a.source_id
               WHERE q.issue_slug='bond' AND q.year=2026
                 AND NOT (a.kind='forum' AND s.kind='video')"""
        ).fetchone()[0]
        self.assertEqual(n, 0, "journalist grouping must not become per-candidate bond answers")
        self.assertGreaterEqual(con.execute("SELECT COUNT(*) FROM reported_lines").fetchone()[0], 1)

    def test_every_edge_has_verification_ledger_entry(self):
        edges = json.loads((H / "endorsements.json").read_text())
        ledger = {x["id"]: x for x in json.loads((H / "endorsement_verification.json").read_text())}
        self.assertEqual({e["id"] for e in edges}, set(ledger))
        for e in edges:
            v = ledger[e["id"]]
            self.assertIn(v["result"], {"PASS", "CORRECTED", "HOLD", "REMOVE", "AUTO"}, e["id"])
            self.assertTrue(v["evidence_url"].startswith("http"), e["id"])
            self.assertRegex(v["checked_on"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(v["note"].strip(), e["id"])
            self.assertEqual(e["verification"]["result"], v["result"], e["id"])
            if v["result"] == "REMOVE":
                self.assertNotEqual(e["status"], "published", e["id"])
            if v["result"] == "HOLD":
                self.assertNotEqual(e["provenance"], "endorser_statement", e["id"])

    def test_endorser_statements_have_endorser_authored_source(self):
        from tools.approve_2026 import AUTHORED_ELSEWHERE, domain
        orgs = {o["slug"]: o for o in json.loads((H / "organizations.json").read_text())}

        def site(u):
            return ".".join(domain(u).split(".")[-2:])

        for e in json.loads((H / "endorsements.json").read_text()):
            if e["provenance"] != "endorser_statement":
                continue
            self.assertIsNone(e["claimed_by"], e["id"])
            url = e["source_url"]
            own = orgs[e["endorser_slug"]].get("website")
            if own and site(own) == site(url):
                continue
            self.assertTrue(any(k in url for k in AUTHORED_ELSEWHERE),
                            f"{e['id']}: endorser_statement source {url} is not endorser-authored")

    def test_sept29_backfill_and_upgrades(self):
        con = db()
        rows = {r["id"]: r for r in con.execute("SELECT id, provenance, claimed_by FROM endorsements")}
        for eid in ("B1", "B2"):
            self.assertEqual(rows[eid]["provenance"], "news_report")
        for eid in ("E68", "E204"):
            self.assertEqual(rows[eid]["provenance"], "endorser_statement")
        dead = con.execute(
            "SELECT COUNT(*) FROM endorsements e JOIN sources s ON s.id=e.source_id "
            "WHERE s.url LIKE '%plan-boulder-county-endorsements%'").fetchone()[0]
        self.assertEqual(dead, 0, "the dead PLAN URL must not be cited")

    def test_richmond_board_role_historical(self):
        con = db()
        r = con.execute(
            """SELECT ol.is_current FROM org_leadership ol JOIN organizations o ON o.id=ol.org_id
               WHERE o.slug='boulder-progressives' AND ol.name='Jamillah Richmond'"""
        ).fetchone()
        self.assertEqual(r[0], 0)


class TestBuiltHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {f: f.read_text(encoding="utf-8") for f in DOCS.rglob("*.html")}

    def spans(self):
        for f, s in self.pages.items():
            p = ProvSpans()
            p.feed(s)
            for rec in p.spans:
                yield f, rec

    def test_every_campaign_claim_labeled(self):
        con = db()
        claims = {r[0]: r[1] for r in con.execute(
            "SELECT id, claimed_by FROM endorsements WHERE provenance='campaign_claim' AND status='published'")}
        seen = set()
        for f, rec in self.spans():
            if rec["prov"] == "campaign_claim":
                self.assertRegex(rec["text"], r"campaign lists ", f"{f}: {rec}")
                seen.add(rec["edge"])
            else:
                self.assertNotIn(rec["edge"], claims, f"{f}: campaign claim {rec['edge']} rendered as {rec['prov']}")
        self.assertEqual(seen, set(claims), "every campaign claim must appear somewhere, labeled")
        # each audit-held edge appears with the claimer named
        for f, rec in self.spans():
            if rec["edge"] in AUDIT_HELD:
                self.assertIn("campaign lists", rec["text"])

    def test_every_published_edge_rendered_with_provenance(self):
        con = db()
        ids = {r[0] for r in con.execute("SELECT id FROM endorsements WHERE status='published'")}
        rendered = {rec["edge"] for _, rec in self.spans()}
        self.assertEqual(ids - rendered, set())

    def test_held_statements_not_rendered(self):
        con = db()
        for (text,) in con.execute("SELECT text FROM statements WHERE status='held'"):
            snippet = " ".join(text.split())[:60]
            for f, s in self.pages.items():
                self.assertNotIn(snippet, " ".join(s.split()), f"held text leaked into {f}")

    def test_find_page_removed_from_nav(self):
        self.assertFalse((DOCS / "find.html").exists())
        for f, s in self.pages.items():
            self.assertNotRegex(s, r'href=["\'](\.\./)*find\.html', str(f))

    def test_home_intro_states_what_the_site_is(self):
        from build_2026 import HOME_INTRO
        s = self.pages[DOCS / "index.html"]
        self.assertIn(HOME_INTRO.replace("'", "&#x27;"), s)
        self.assertIn("independent, nonpartisan guide", s)
        self.assertIn("Who's running for mayor", s)
        self.assertIn("Who's running for city council", s)
        self.assertIn("What's on the ballot", s)
        self.assertIn("How to use this guide", s)

    def test_print_sheet_answers_not_folded(self):
        """A closed details element hides answers even if print CSS sets blockquote display:block."""
        s = self.pages[DOCS / "print" / "tara-winer.html"]
        self.assertNotIn("<details class='quote'>", s)
        self.assertIn("supportive services", s)
        self.assertIn("<blockquote class='answer'>", s)
        self.assertNotIn("One letter-size sheet", s)
        # The shared stylesheet (linked from every page) opens all folded answers in print.
        self.assertIn('href="../css/site.css"', s)
        css = (DOCS / "css" / "site.css").read_text(encoding="utf-8")
        self.assertIn("details::details-content { content-visibility: visible; display: block; }", css)

    def test_home_key_facts(self):
        s = self.pages[DOCS / "index.html"]
        self.assertIn("October 2", s)
        self.assertIn("7 p.m.", s)
        self.assertIn("November 3", s)
        self.assertIn("civics.html", s)
        self.assertNotRegex(s.lower(), r"\bwe recommend\b|\bscore:")

    def test_home_lists_candidates_in_ballot_order(self):
        order = json.loads((H / "ballot_order.json").read_text())
        self.assertTrue(order["source_url"].startswith("https://bouldercolorado.gov/"))
        s = self.pages[DOCS / "index.html"]
        self.assertNotIn("Alphabetical order", s)
        self.assertIn("Listed in the order they appear on your ballot", s)
        self.assertIn(order["source_url"], s)
        for race, anchor, nxt in (("mayor", "id='mayor'", "id='council'"), ("council", "id='council'", "id='measures'")):
            section = s[s.index(anchor):s.index(nxt)]
            shown = re.findall(r"<h3><a href='people/[^']+'>([^<]+)</a></h3>", section)
            self.assertEqual(shown, order["races"][race], race)
        year = self.pages[DOCS / "2026.html"]
        pos = [year.index(f">{n}<") for n in order["races"]["mayor"]]
        self.assertEqual(pos, sorted(pos))

    def test_ballot_positions_loaded(self):
        order = json.loads((H / "ballot_order.json").read_text())
        con = db()
        for race, names in order["races"].items():
            rows = con.execute(
                """SELECT p.full_name FROM candidacies c JOIN people p ON p.id=c.person_id
                   JOIN races r ON r.id=c.race_id JOIN elections e ON e.id=r.election_id
                   JOIN offices o ON o.id=r.office_id WHERE e.year=2026 AND o.slug=?
                   ORDER BY c.ballot_position""", (race,)).fetchall()
            self.assertEqual([r[0] for r in rows], names)

    def test_martus_display_name(self):
        s = self.pages[DOCS / "index.html"]
        self.assertIn("Dave Martus", s)
        self.assertNotIn("David Martus", s)

    def test_no_broken_local_links(self):
        from tools.check_links import broken_links
        self.assertEqual(broken_links(DOCS), [])

    def test_viewport_meta_everywhere(self):
        for f, s in self.pages.items():
            self.assertIn('name="viewport"', s, str(f))


if __name__ == "__main__":
    unittest.main()
