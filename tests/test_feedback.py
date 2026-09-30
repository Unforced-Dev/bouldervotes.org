"""Feedback form, footer link and llms.txt instructions for the Worker collector."""
import re
import unittest
from pathlib import Path

import build

DOCS = Path(__file__).resolve().parent.parent / "docs"


class TestFeedback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (DOCS / "feedback.html").read_text(encoding="utf-8")

    def test_endpoint_constant(self):
        self.assertTrue(build.FEEDBACK_URL.startswith("https://"))
        self.assertTrue(build.FEEDBACK_API.startswith(build.FEEDBACK_URL))

    def test_form_posts_to_feedback_url(self):
        forms = re.findall(r"<form[^>]*>", self.html)
        self.assertEqual(len(forms), 1)
        self.assertIn("method='post'", forms[0])
        self.assertIn(f"action='{build.FEEDBACK_URL}'", forms[0])

    def test_form_fields_and_honeypot(self):
        for name in ("kind", "page", "message", "source_url", "contact", "homepage"):
            self.assertIn(f"name='{name}'", self.html, name)
        for kind in ("correction", "suggestion", "other"):
            self.assertIn(f"value='{kind}'", self.html)
        self.assertIn("<h1>Suggest a fix or an idea</h1>", self.html)
        self.assertIn("We don't publish your note or share your contact.", self.html)
        # thanks and error states work without JS via :target
        self.assertIn("id='sent'", self.html)
        self.assertIn("id='problem'", self.html)

    def test_in_learn_section(self):
        self.assertIn("feedback", build.LEARN_PAGES)
        self.assertIn("<nav class='learn-nav'", self.html)
        self.assertIn("href='feedback.html'", (DOCS / "learn.html").read_text(encoding="utf-8"))

    def test_every_footer_links_to_feedback(self):
        pages = sorted(DOCS.rglob("*.html"))
        self.assertGreater(len(pages), 100)
        for f in pages:
            s = f.read_text(encoding="utf-8")
            foot = re.search(r"<footer class=\"site\">.*?</footer>", s, re.S)
            with self.subTest(page=str(f.relative_to(DOCS))):
                self.assertIsNotNone(foot)
                rel = f.relative_to(DOCS).as_posix()
                path = "/" if rel == "index.html" else "/" + rel
                prefix = "../" * rel.count("/")
                self.assertIn(f'href="{prefix}feedback.html?page={path}"', foot.group(0))
                self.assertNotIn(build.PAGE_PATH_TOKEN, s)

    def test_llms_txt_documents_endpoint(self):
        s = (DOCS / "llms.txt").read_text(encoding="utf-8")
        self.assertIn(build.FEEDBACK_API, s)
        self.assertIn("ai-agent", s)
        self.assertIn("on_behalf_of_user", s)
        self.assertIn("source_url", s)
        self.assertIn("curl -X POST", s)
        self.assertIn("Only submit when the user asks", s)
        self.assertIn(build.FEEDBACK_API, (DOCS / "llms-full.txt").read_text(encoding="utf-8"))
        self.assertIn(build.FEEDBACK_API, (DOCS / "api" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
