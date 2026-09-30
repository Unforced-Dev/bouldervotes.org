"""Our own copy must not read like chatbot prose.

Quotes are exempt: candidates may say whatever they said. Everything we
write (templates, notes, labels) is checked after the build.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

TELLS = ("robust", "comprehensive", "navigate", "crucial", "delve", "seamless", "leverage",
         "in so many words", "not a quiz", "not scored")

# Verbatim material: blockquotes, <q>, folded quotes, question prompts in issue
# links, and source titles in the catalog (they are other people's words).
QUOTED = re.compile(
    r"<blockquote.*?</blockquote>|<q>.*?</q>|<details class='quote'>.*?</details>|<title>.*?</title>",
    re.S)


def own_text(html: str) -> str:
    return QUOTED.sub(" ", html)


class TestVoice(unittest.TestCase):
    def test_no_ai_tells_in_our_copy(self):
        bad = []
        for f in sorted(DOCS.rglob("*.html")):
            text = own_text(f.read_text(encoding="utf-8")).lower()
            for w in TELLS:
                if re.search(rf"\b{re.escape(w)}", text):
                    bad.append(f"{f.relative_to(DOCS)}: {w}")
        self.assertEqual(bad, [])

    def test_no_endorsement_disclaimer_said_once_not_everywhere(self):
        # Home and About say it clearly; other pages should not repeat it.
        home = (DOCS / "index.html").read_text(encoding="utf-8")
        about = (DOCS / "about.html").read_text(encoding="utf-8")
        self.assertIn("We don't endorse", home)
        self.assertIn("We don't endorse", about)
        n = sum(1 for f in DOCS.rglob("*.html")
                if "we do not endorse" in own_text(f.read_text(encoding="utf-8")).lower())
        self.assertEqual(n, 0)

    def test_filter_keeps_our_text(self):
        self.assertIn("robust", own_text("<p>robust</p><blockquote>x</blockquote>"))
        self.assertNotIn("robust", own_text("<blockquote class='answer'>robust</blockquote>"))


if __name__ == "__main__":
    unittest.main()
