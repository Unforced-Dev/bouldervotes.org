"""The machine-readable layer: llms.txt, llms-full.txt, /api/v1 JSON, and
the pointers that let an assistant find them from the bare domain."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DOCS = ROOT / "docs"
API = DOCS / "api" / "v1"
H = ROOT / "data" / "harvest" / "2026"

REQUIRED = {
    "index.json": ["endpoints"],
    "election.json": ["election"],
    "candidates.json": ["candidates"],
    "measures.json": ["measures"],
    "forum_claims.json": ["forums", "quotes"],
    "endorsements.json": ["endorsements"],
    "finance.json": ["committees"],
    "sources.json": ["sources"],
}
RECOMMEND = re.compile(r"you should vote|best candidate|we recommend|vote (yes|no) on|the right choice", re.I)


def ballot_names() -> list[str]:
    o = json.loads((H / "ballot_order.json").read_text(encoding="utf-8"))
    return o["races"]["mayor"] + o["races"]["council"]


class TestLlmLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = {f.relative_to(API).as_posix(): json.loads(f.read_text(encoding="utf-8"))
                   for f in API.rglob("*.json")}
        cls.llms = (DOCS / "llms.txt").read_text(encoding="utf-8")
        cls.full = (DOCS / "llms-full.txt").read_text(encoding="utf-8")

    def test_schema(self):
        for name, keys in REQUIRED.items():
            doc = self.api[name]
            self.assertEqual(doc["schema_version"], "1.0", name)
            self.assertRegex(doc["generated_at"], r"^\d{4}-\d{2}-\d{2}$", name)
            for k in keys:
                self.assertIn(k, doc, name)
        listed = {e["path"] for e in self.api["index.json"]["endpoints"]}
        for name in REQUIRED:
            if name != "index.json":
                self.assertIn(f"/api/v1/{name}", listed)

    def test_every_record_is_sourced(self):
        for c in self.api["candidates.json"]["candidates"]:
            self.assertTrue(c["page_url"].startswith("https://bouldervotes.org/people/"))
        for slug_file, doc in self.api.items():
            if slug_file.startswith("candidates/"):
                c = doc["candidate"]
                self.assertTrue(c["source_urls"], c["slug"])
                for s in c["statements"]:
                    self.assertTrue(s["source_url"].startswith("http"))
                for q in c["forum_quotes"]:
                    self.assertRegex(q["watch_url"], r"[?&]t=\d+s")
        for e in self.api["endorsements.json"]["endorsements"]:
            self.assertTrue(e["source_url"].startswith("http"), e["id"])
            if e["provenance"] == "campaign_claim":
                self.assertIn("campaign lists", e["label"], e["id"])
        for m in self.api["measures.json"]["measures"]:
            self.assertTrue(m["yes_means"] and m["no_means"] and m["official_text_url"], m["letter"])

    def test_ballot_order_and_every_candidate(self):
        names = ballot_names()
        self.assertEqual(len(names), 19)
        got = [c["name"] for c in self.api["candidates.json"]["candidates"]]
        self.assertEqual(got, names)
        for c in self.api["candidates.json"]["candidates"]:
            self.assertIn(f"candidates/{c['slug']}.json", self.api)
        for n in names:
            self.assertIn(n, self.full)
            self.assertIn(n, self.llms)

    def test_held_items_not_exported(self):
        claims = json.loads((H / "forum_claims.json").read_text(encoding="utf-8"))
        blob = json.dumps(self.api, ensure_ascii=False) + self.full
        for c in claims:
            if c["status"] == "held":
                self.assertNotIn(c["quote"][:60], blob, c["id"])
        import sqlite3
        con = sqlite3.connect(ROOT / "data" / "bouldervotes.db")
        for (text,) in con.execute("SELECT text FROM statements WHERE status='held'"):
            self.assertNotIn(" ".join(text.split())[:60], blob)

    def test_caveats_carried(self):
        from build_forums_2026 import MEDIUM_CAVEAT, TRANSCRIPT_NOTE
        self.assertIn(TRANSCRIPT_NOTE, self.full)
        quotes = self.api["forum_claims.json"]["quotes"]
        for q in quotes:
            self.assertIn(TRANSCRIPT_NOTE, q["caveats"])
            if q["attribution_confidence"] == "medium":
                self.assertIn(MEDIUM_CAVEAT, q["caveats"])
        self.assertIn("That is not opposition.", self.full)
        self.assertIn("As of", self.full)

    def test_ai_instructions_do_not_recommend(self):
        from build_llm import AI_PROMPT, AI_RULES
        for text in (AI_RULES, AI_PROMPT, self.llms):
            self.assertIsNone(RECOMMEND.search(text), RECOMMEND.search(text))
        self.assertIn("## Instructions for AI assistants", self.llms)
        self.assertIn("nonpartisan", AI_RULES)

    def test_llms_txt_shape(self):
        self.assertTrue(self.llms.startswith("# Boulder Votes\n\n> "))
        self.assertIn("https://bouldervotes.org/llms-full.txt", self.llms)
        self.assertLess(len(self.full.encode("utf-8")), 400_000)

    def test_home_points_to_machine_layer(self):
        from build_llm import strip_html
        s = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="alternate" type="text/markdown" href="/llms-full.txt"', s)
        self.assertIn('href="/api/v1/index.json"', s)
        self.assertIn('<meta name="description"', s)
        ld = [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', s, re.S)]
        self.assertEqual({x["@type"] for x in ld[0]}, {"WebSite", "Event"})
        text = strip_html(s)[:4000]
        self.assertIn("https://bouldervotes.org/llms-full.txt", text)
        for n in ballot_names():
            self.assertIn(n, text)
        for k in ("November 3", "October 2", "7 p.m.", "2J", "2K", "2L", "2M"):
            self.assertIn(k, text)
        # the pointer is visible text, not hidden
        self.assertNotRegex(s, r"class='ai-note'[^>]*hidden|ai-note[^{]*\{[^}]*display:\s*none")

    def test_every_page_footer_points_to_llms_full(self):
        for f in DOCS.rglob("*.html"):
            self.assertIn("llms-full.txt", f.read_text(encoding="utf-8"), str(f))

    def test_robots_and_sitemap(self):
        self.assertIn("Allow: /", (DOCS / "robots.txt").read_text())
        sm = (DOCS / "sitemap.xml").read_text()
        self.assertIn("<loc>https://bouldervotes.org/people/tara-winer.html</loc>", sm)
        self.assertIn("<loc>https://bouldervotes.org/llms-full.txt</loc>", sm)


if __name__ == "__main__":
    unittest.main()
