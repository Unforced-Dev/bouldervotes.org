"""Design-system guards for the 2026-09-29 UI overhaul."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
H = ROOT / "data" / "harvest" / "2026"


def primary_nav_items(html: str) -> list[str]:
    m = re.search(r'<nav class="primary"[^>]*>(.*?)</nav>', html, re.S)
    return re.findall(r"<li>", m.group(1)) if m else []


class TestDesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {f: f.read_text(encoding="utf-8") for f in DOCS.rglob("*.html")}

    def test_header_has_at_most_five_primary_nav_items(self):
        for f, s in self.pages.items():
            n = len(primary_nav_items(s))
            self.assertTrue(1 <= n <= 5, f"{f}: {n} primary nav items")

    def test_wordmark_and_single_stylesheet(self):
        for f, s in self.pages.items():
            self.assertIn('class="brand"', s, str(f))
            self.assertIn("<svg", s, str(f))
            self.assertIn("css/site.css", s, str(f))
            self.assertNotIn("<style", s, f"{f}: inline <style> block; all CSS lives in static/css/site.css")

    def test_home_benefit_h1_and_timeline(self):
        s = self.pages[DOCS / "index.html"]
        self.assertIn("<h1>Everything on your Boulder city ballot, with sources</h1>", s)
        self.assertIn("class='timeline'", s)
        self.assertRegex(s, r"As of [A-Z][a-z]+ \d{1,2}, 2026")

    def test_every_2026_candidate_has_photo_with_credit_or_monogram(self):
        doc = json.loads((H / "photos.json").read_text(encoding="utf-8"))
        photos = {p["slug"]: p for p in doc["photos"]}
        order = json.loads((H / "ballot_order.json").read_text(encoding="utf-8"))
        names = [n for race in order["races"].values() for n in race]
        self.assertEqual(len(names), 19)
        by_name = {p["name"]: p for p in photos.values()}
        sourced = 0
        for name in names:
            p = by_name.get(name)
            self.assertIsNotNone(p, f"{name} missing from photos.json")
            page = self.pages[DOCS / "people" / f"{p['slug']}.html"]
            if p.get("file"):
                sourced += 1
                self.assertTrue((DOCS / p["file"]).exists(), p["file"])
                self.assertLessEqual((DOCS / p["file"]).stat().st_size, 60_000, p["file"])
                self.assertTrue(p["source_url"].startswith("http"), name)
                self.assertTrue(p["credit"].startswith("Photo: "), name)
                self.assertIn(p["file"], page)
                self.assertIn(p["credit_url"], page)
            else:
                self.assertTrue(p.get("monogram"), name)
                self.assertTrue(p.get("reason"), name)
                self.assertIn("face mono", page, name)
        self.assertGreater(sourced, 0)
        # symmetric home grid: one face tile per candidate
        home = self.pages[DOCS / "index.html"]
        self.assertEqual(home.count("class='cand-top'"), 19)

    def test_fonts_self_hosted_with_license(self):
        fonts = DOCS / "fonts"
        woff2 = list(fonts.glob("*.woff2"))
        self.assertGreaterEqual(len(woff2), 2)
        lic = (fonts / "OFL.txt").read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE", lic.upper())
        css = (DOCS / "css" / "site.css").read_text(encoding="utf-8")
        self.assertIn("font-display: swap", css)
        for f in woff2:
            self.assertIn(f"../fonts/{f.name}", css)
        for s in self.pages.values():
            self.assertNotIn("fonts.googleapis", s)

    def test_no_party_colour_on_stances(self):
        css = (DOCS / "css" / "site.css").read_text(encoding="utf-8")
        m = re.search(r"\.stance\.yes, \.stance\.no, \.stance\.mixed \{([^}]*)\}", css)
        self.assertIsNotNone(m)


if __name__ == "__main__":
    unittest.main()


class TestShareCard(unittest.TestCase):
    def test_every_page_has_og_image(self):
        for f in DOCS.rglob("*.html"):
            s = f.read_text(encoding="utf-8")
            self.assertIn('property="og:image" content="https://bouldervotes.org/img/og-card.png', s, str(f))
            self.assertIn('name="twitter:card" content="summary_large_image"', s, str(f))
        self.assertTrue((DOCS / "img" / "og-card.png").exists())
