"""Voter-facing pages must not leak pipeline vocabulary.

docs/ is generated; never hand-edit it. These tests re-check the rendered
site after `python3 seed.py && python3 build.py`:

    python3 -m unittest
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DOCS = ROOT / "docs"

# Raw enum values and ingest-pipeline jargon a voter should never see.
# Word boundaries where a substring could ride inside a longer word/number
# ("1 answers" inside "31 answers", "this pass" inside "this passes").
BANNED = (
    r"not_referred",
    r"on_ballot",
    r"campaign_site",
    r"\bingested\b",
    r"\bharvested\b",
    r"\bthis pass\b",
    r"\b1 answers\b",
)

# A snake_case word rendered as visible text, e.g. ">news_report<".
SNAKE_CASE_TEXT = re.compile(r">[a-z]+(?:_[a-z0-9]+)+<")


def html_files() -> list[Path]:
    return sorted(DOCS.rglob("*.html"))


class TestPlainLabels(unittest.TestCase):
    def test_docs_exist(self):
        self.assertTrue(html_files(), "docs/ is empty — run python3 build.py first")

    def test_no_pipeline_vocabulary(self):
        for f in html_files():
            text = f.read_text(encoding="utf-8")
            for pattern in BANNED:
                m = re.search(pattern, text)
                self.assertIsNone(
                    m, f"{f.relative_to(DOCS)} contains {m.group(0)!r}" if m else ""
                )

    def test_no_snake_case_labels(self):
        bad = []
        for f in html_files():
            text = f.read_text(encoding="utf-8")
            if f.relative_to(DOCS).parts[0] == "api":
                # API docs name JSON fields on purpose, inside <code>.
                text = re.sub(r"<code>.*?</code>", "", text)
            for m in SNAKE_CASE_TEXT.finditer(text):
                bad.append(f"{f.relative_to(DOCS)}: {m.group(0)}")
        self.assertEqual(bad, [])

    def test_human_label_maps_enums(self):
        from build import human_label

        self.assertEqual(human_label("not_referred"), "not placed on the ballot")
        self.assertEqual(human_label("on_ballot"), "on the ballot")
        self.assertEqual(human_label("campaign_site"), "campaign website")
        self.assertEqual(human_label("questionnaire"), "questionnaire")
        self.assertEqual(human_label("news_report"), "news report")
        self.assertEqual(human_label(None), "")

    def test_plural(self):
        from build import plural

        self.assertEqual(plural(1, "answer"), "1 answer")
        self.assertEqual(plural(2, "answer"), "2 answers")

    def test_quotes_stay_verbatim(self):
        from build import quote_block
        self.assertIn("harvested", quote_block("We harvested this pass of ideas.", fold=False))

    def test_page_does_not_rewrite_body(self):
        src = (ROOT / "build.py").read_text(encoding="utf-8")
        self.assertNotIn("plain(body)", src)
        self.assertNotIn("plain(title)", src)

    def test_plain_notes(self):
        from build_plain import plain
        self.assertEqual(plain("Verbatim answers harvested 2026-08-27."), "Verbatim answers collected 2026-08-27.")
        self.assertEqual(plain("Not ingested as scored stances"), "Not copied as scored stances")


if __name__ == "__main__":
    unittest.main()
