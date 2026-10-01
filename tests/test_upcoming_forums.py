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
        known_future = {
            "2026-10-06-eof-plan-mayoral-climate",
            "2026-10-13-eof-plan-council-climate",
            "2026-10-14-brl-kgnu-mayoral-debate",
            "2026-10-14-lwv-ballot-issues-pearl",
            "2026-10-15-lwv-ballot-issues-frasier",
        }
        after = {e["id"] for e in upcoming(dt.date(2026, 10, 1))}
        before = {e["id"] for e in upcoming(dt.date(2026, 9, 30))}
        self.assertTrue(known_future <= after)
        self.assertTrue(known_future <= before)
        self.assertIn("2026-09-30-bolo-barha-council-mayor", before)
        self.assertNotIn("2026-09-30-bolo-barha-council-mayor", after)

    def test_rendered_on_forums_page_and_llms(self):
        s = (DOCS / "forums.html").read_text(encoding="utf-8")
        self.assertIn("Upcoming forums you can attend", s)
        self.assertIn("Upcoming forums", (DOCS / "llms.txt").read_text(encoding="utf-8"))
        self.assertIn("Upcoming forums you can attend", (DOCS / "llms-full.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
