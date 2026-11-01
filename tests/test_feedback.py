"""The feedback form is closed (2026-10-31): no page, no links, no endpoint advertised.

The Worker that took feedback still serves page counts (see test_counts.py)."""
import json
import re
import unittest
from pathlib import Path

import build

DOCS = Path(__file__).resolve().parent.parent / "docs"
FEEDBACK_API = "feedback.bouldervotes.org/api/v1/feedback"


class TestFeedbackOff(unittest.TestCase):
    def test_page_is_gone(self):
        self.assertFalse((DOCS / "feedback.html").exists())

    def test_no_page_links_to_feedback(self):
        pages = sorted(DOCS.rglob("*.html"))
        self.assertGreater(len(pages), 100)
        for f in pages:
            s = f.read_text(encoding="utf-8")
            with self.subTest(page=str(f.relative_to(DOCS))):
                self.assertNotIn("feedback.html", s)
                self.assertNotIn(FEEDBACK_API, s)
                self.assertNotIn("Spot a mistake? Tell us", s)

    def test_not_in_learn_section(self):
        self.assertNotIn("feedback", build.LEARN_PAGES)

    def test_ai_files_do_not_advertise_feedback(self):
        for rel in ("llms.txt", "llms-full.txt", "sitemap.xml", "api/index.html"):
            s = (DOCS / rel).read_text(encoding="utf-8")
            with self.subTest(file=rel):
                self.assertNotIn(FEEDBACK_API, s)
                self.assertNotIn("feedback.html", s)
        self.assertNotIn("feedback", json.loads((DOCS / "api" / "v1" / "index.json").read_text(encoding="utf-8")))
        self.assertIsNone(re.search(r"(?im)^#+ .*feedback", (DOCS / "llms.txt").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
