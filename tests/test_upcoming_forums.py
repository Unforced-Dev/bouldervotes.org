import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DOCS = ROOT / "docs"


class TestUpcomingForums(unittest.TestCase):
    def test_data_is_sourced(self):
        rows = json.loads((ROOT / "data/harvest/2026/forums_upcoming.json").read_text())
        self.assertTrue(rows)
        for e in rows:
            self.assertTrue(e["source_url"].startswith("https://"), e["id"])
            self.assertEqual(e["confidence"], "confirmed", e["id"])
            dt.date.fromisoformat(e["date"])

    def test_past_events_drop_off(self):
        from build_upcoming import upcoming
        self.assertEqual(upcoming(dt.date(2026, 11, 4)), [])
        self.assertEqual(len(upcoming(dt.date(2026, 10, 1))), 5)

    def test_rendered_on_forums_page_and_llms(self):
        s = (DOCS / "forums.html").read_text(encoding="utf-8")
        self.assertIn("Upcoming forums you can attend", s)
        self.assertIn("Upcoming forums", (DOCS / "llms.txt").read_text(encoding="utf-8"))
        self.assertIn("Upcoming forums you can attend", (DOCS / "llms-full.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
