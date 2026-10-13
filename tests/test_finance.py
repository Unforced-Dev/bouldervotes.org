"""2026 finance: every figure carries its report and a retrieval date."""
import json
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "bouldervotes.db"
DOCS = ROOT / "docs"


class TestFinance(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(DB)
        self.con.row_factory = sqlite3.Row

    def tearDown(self):
        self.con.close()

    def test_snapshots_sourced(self):
        rows = self.con.execute("SELECT * FROM finance_snapshots WHERE year=2026").fetchall()
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue(r["retrieved_on"], r["committee_name"])
            if r["reported_on"]:
                self.assertTrue(r["report_label"], r["committee_name"])
                self.assertIn("statementID=", r["report_url"] or "", r["committee_name"])

    def test_pages_show_retrieval_date(self):
        retrieved = json.loads((ROOT / "data/harvest/finance_2026.json").read_text())["retrieved_on"]
        y, m, d = retrieved.split("-")
        fin = (DOCS / "finance.html").read_text()
        self.assertIn(f"retrieved", fin)
        self.assertIn(f" {int(d)}, {y}", fin)
        self.assertNotIn("retrieved 2026-09-01", fin)
        api = json.loads((DOCS / "api/v1/finance.json").read_text())
        self.assertEqual(api["retrieved_on"], retrieved)

    def test_totals_follow_latest_submission(self):
        """A resubmitted earlier report can be the newest filing; totals follow it."""
        import json
        from pathlib import Path
        data = json.loads((Path(__file__).resolve().parent.parent / "data/harvest/finance_2026.json").read_text())
        for c in data["committees"]:
            sts = [s for s in c.get("statements") or [] if s.get("balance") and s.get("submitted_at")]
            if not sts or c.get("listing_omits"):
                continue
            latest = max(sts, key=lambda s: s["submitted_at"])
            self.assertEqual(c["contributions_total"], latest["balance"]["contributions"], c["committee_name"])
            self.assertEqual(c["statements"][-1]["statement_id"], latest["statement_id"], c["committee_name"])


if __name__ == "__main__":
    unittest.main()
