"""Trust-rule tests for 2026 forum answers.

Run after `python3 seed.py && python3 build.py`:
    python3 -m unittest
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "bouldervotes.db"
DOCS = ROOT / "docs"
H = ROOT / "data" / "harvest" / "2026"

from build_forums_2026 import MEDIUM_CAVEAT, TRANSCRIPT_NOTE  # noqa: E402
from tools.approve_forums_2026 import FORUM_HOLDS, FORUM_STANCES  # noqa: E402


def norm(s: str) -> str:
    s = re.sub(r"\[\d+:\d\d:\d\d\]\s*", " ", s)
    return " ".join(s.lower().split())


def forum_answers():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT a.*, p.full_name, p.slug AS pslug, s.url AS source_url, s.kind AS skind, e.kind AS ekind
           FROM answers a JOIN people p ON p.id=a.person_id JOIN sources s ON s.id=a.source_id
           LEFT JOIN events e ON e.id=a.event_id
           WHERE a.kind='forum' AND s.kind='video'"""
    ).fetchall()
    con.close()
    return rows


class TestForumData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.claims = json.loads((H / "forum_claims.json").read_text())
        cls.rows = forum_answers()

    def test_counts(self):
        self.assertEqual(len(self.claims), 330)
        held = [c for c in self.claims if c["status"] == "held"]
        self.assertEqual(len(held), len(FORUM_HOLDS))
        self.assertEqual(len(self.rows), 330 - len(held))

    def test_verbatim_in_committed_transcript(self):
        cache = {}
        for r in self.rows:
            vid = re.search(r"[?&]v=([\w-]+)", r["source_url"]).group(1)
            if vid not in cache:
                cache[vid] = norm((H / "transcripts" / f"{vid}.txt").read_text(encoding="utf-8"))
            self.assertIn(norm(r["verbatim"]), cache[vid], f"answer {r['id']} not in transcript {vid}")

    def test_event_source_timestamp(self):
        for r in self.rows:
            self.assertIsNotNone(r["event_id"], r["id"])
            self.assertEqual(r["ekind"], "forum", r["id"])
            self.assertTrue(r["source_url"].startswith("https://www.youtube.com/watch?v="), r["id"])
            self.assertRegex(r["notes"], r"Watch: https://www\.youtube\.com/watch\?v=[\w-]+&t=\d+s", r["id"])
            self.assertRegex(r["notes"], r"Attribution confidence: (high|medium)", r["id"])
            self.assertTrue(r["answered_on"], r["id"])

    def test_stance_only_from_constant(self):
        allowed = {}
        for (cand, vid, prefix), (st, _) in FORUM_STANCES.items():
            if st:
                allowed[(cand, vid, prefix)] = st
        for r in self.rows:
            vid = re.search(r"[?&]v=([\w-]+)", r["source_url"]).group(1)
            hits = [st for (c, v, p), st in allowed.items()
                    if c == r["full_name"] and v == vid and r["verbatim"].startswith(p)]
            if r["stance"] is None:
                self.assertEqual(hits, [], f"constant sets a stance not loaded: {r['id']}")
            else:
                self.assertEqual(hits, [r["stance"]], f"stance outside FORUM_STANCES: {r['id']}")
        self.assertEqual(sum(1 for r in self.rows if r["stance"]), len(allowed))

    def test_stance_only_on_binary_questions(self):
        for c in self.claims:
            if c["stance"]:
                self.assertTrue(c["stance_about"], c["id"])

    def test_held_not_loaded(self):
        held = {c["quote"] for c in self.claims if c["status"] == "held"}
        self.assertFalse(held & {r["verbatim"] for r in self.rows})

    def test_martus_name(self):
        names = {c["candidate"] for c in self.claims}
        self.assertNotIn("David Martus", names)


class TestForumHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {f: f.read_text(encoding="utf-8") for f in DOCS.rglob("*.html")}
        cls.claims = json.loads((H / "forum_claims.json").read_text())

    def cards(self, s: str):
        return re.findall(r"<div class='card forum-answer' data-claim='(FC\d+)' data-confidence='(\w+)'>(.*?)</div><!-- /forum-answer -->", s, re.S)

    def test_medium_caveat_everywhere(self):
        seen = set()
        for f, s in self.pages.items():
            for cid, conf, body in self.cards(s):
                self.assertIn(TRANSCRIPT_NOTE, body, f"{f} {cid}")
                self.assertIn("Watch at ", body, f"{f} {cid}")
                if conf == "medium":
                    self.assertIn(MEDIUM_CAVEAT, body, f"{f} {cid}")
                    seen.add(cid)
        medium = {c["id"] for c in self.claims if c["attribution_confidence"] == "medium" and c["status"] == "published"}
        self.assertEqual(seen, medium)

    def test_every_published_claim_on_candidate_page(self):
        by_person = {}
        for c in self.claims:
            if c["status"] == "published":
                by_person.setdefault(c["candidate"], set()).add(c["id"])
        for name, ids in by_person.items():
            s = self.pages[DOCS / "people" / (name.lower().replace(" ", "-") + ".html")]
            self.assertIn("At the forums, in their own words", s, name)
            got = {cid for cid, _, _ in self.cards(s)}
            self.assertEqual(got, ids, name)

    def test_held_not_rendered(self):
        for c in self.claims:
            if c["status"] == "held":
                for f, s in self.pages.items():
                    self.assertNotIn(c["id"], s, f)
                    self.assertNotIn(c["quote"][:60], s, f)

    def test_compare_grid_has_no_scores(self):
        s = self.pages[DOCS / "compare.html"]
        self.assertIn("no scores", s)
        for f, t in self.pages.items():
            if "/compare/" in str(f):
                self.assertNotRegex(t.lower(), r"\bscore:|\bwe recommend\b|\bwinner\b")
                self.assertIn(TRANSCRIPT_NOTE, t)

    def test_measure_pages_have_forum_quotes(self):
        for letter in ("2j", "2k"):
            s = self.pages[DOCS / "measures" / f"2026-{letter}.html"]
            self.assertIn("What candidates said at forums", s)
            self.assertIn(TRANSCRIPT_NOTE, s)

    def test_forum_pages_exist(self):
        for slug in ("2026-chamber-forum", "2026-votes-forum", "2026-arts-forum", "2026-lwv-forum"):
            self.assertTrue((DOCS / "forums" / f"{slug}.html").exists(), slug)
        self.assertIn("2026-09-26", (H / "forums.json").read_text())

    def test_all_19_candidate_pages(self):
        cands = json.loads((H / "candidates.json").read_text())
        self.assertEqual(len(cands), 19)
        for c in cands:
            self.assertTrue((DOCS / "people" / (c["name"].lower().replace(" ", "-") + ".html")).exists(), c["name"])


if __name__ == "__main__":
    unittest.main()
