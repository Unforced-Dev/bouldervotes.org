"""Archive mode (after the Nov 3, 2026 election): a note on every page, no AI chat,
results updates frozen, and county name spellings kept as data.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build  # noqa: E402
import build_results_2026 as R  # noqa: E402
import fetch_results_2026 as F  # noqa: E402

DOCS = ROOT / "docs"


class TestArchiveNote(unittest.TestCase):
    def test_every_page_carries_the_note_and_the_county_link(self):
        pages = sorted(DOCS.rglob("*.html"))
        self.assertGreater(len(pages), 100)
        missing = []
        for f in pages:
            s = f.read_text(encoding="utf-8")
            if build.ARCHIVE_TEXT not in s or f'href="{R.COUNTY_RESULTS_URL}"' not in s:
                missing.append(f.relative_to(DOCS).as_posix())
        self.assertEqual(missing, [], "pages without the archive note")

    def test_note_comes_before_the_page_content(self):
        s = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertLess(s.index('class="archive-note"'), s.index('<main id="content">'))

    def test_ai_files_say_it_is_an_archive(self):
        for name in ("llms.txt", "llms-full.txt"):
            with self.subTest(file=name):
                head = (DOCS / name).read_text(encoding="utf-8")[:1500]
                self.assertIn(build.ARCHIVE_TEXT, head)
                self.assertIn(R.COUNTY_RESULTS_URL, head)


class TestChatOff(unittest.TestCase):
    """No /ask page, no link to it and nothing that calls the AI gateway."""

    @unittest.skipIf(os.environ.get("BV_CHAT_ENABLED") == "1", "chat turned on for this build")
    def test_no_ask_page_links_or_gateway(self):
        self.assertFalse((DOCS / "ask.html").exists())
        self.assertFalse((DOCS / "js" / "ask.js").exists())
        hits = []
        for f in list(DOCS.rglob("*.html")) + [DOCS / "llms.txt", DOCS / "llms-full.txt", DOCS / "sitemap.xml"]:
            s = f.read_text(encoding="utf-8")
            if re.search(r"ask\.html|haiku-gateway", s):
                hits.append(f.relative_to(DOCS).as_posix())
        self.assertEqual(hits, [])


class TestResultsFrozen(unittest.TestCase):
    def run_main(self, *args: str) -> tuple[int, str]:
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["fetch_results_2026.py", *args]), redirect_stderr(err):
            return F.main(), err.getvalue()

    def test_a_write_stops_before_any_network_call(self):
        env = {k: v for k, v in os.environ.items() if k != "BV_RESULTS_UPDATES"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(F, "get", side_effect=AssertionError("network call while frozen")):
            code, err = self.run_main()
        self.assertEqual(code, 4)
        self.assertIn("FROZEN", err)

    def test_page_says_the_copy_is_no_longer_updated(self):
        self.assertIn("no longer updates", R.CAVEAT)
        self.assertNotIn("update as ballots", R.CAVEAT)
        if R.results_enabled():
            self.assertIn(R.CAVEAT, (DOCS / "results.html").read_text(encoding="utf-8"))


class TestCountyNames(unittest.TestCase):
    """county_names.json maps a county spelling to one 2026 ballot name and nothing else."""

    def with_file(self, aliases: dict):
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "county_names.json"
        tmp.write_text(json.dumps({"aliases": aliases}), encoding="utf-8")
        return mock.patch.object(R, "COUNTY_NAMES_JSON", tmp)

    def roster_names(self) -> dict:
        return json.loads(F.BALLOT_ORDER.read_text(encoding="utf-8"))["races"]

    def data_with(self, mayor_names: list[str]) -> dict:
        order = self.roster_names()
        return {"contests": [
            {"office": "mayor", "candidates": [{"name": n, "votes": 0} for n in mayor_names]},
            {"office": "council", "seats": 5, "candidates": [{"name": n, "votes": 0} for n in order["council"]]},
            *[{"office": "measure", "code": c} for c in F.MEASURE_CODES_2026]]}

    def test_a_county_spelling_matches_its_candidate(self):
        order = self.roster_names()["mayor"]
        county = ["SPELLED DIFFERENTLY" if n == order[0] else n for n in order]
        self.assertEqual(len(F.check_2026(self.data_with(county))), 1)
        with self.with_file({"Spelled Differently": order[0]}):
            self.assertEqual(F.check_2026(self.data_with(county)), [])
            self.assertIsNotNone(R.Roster(build_con(), 2026).lookup("mayor", "Spelled Differently"))

    def test_target_must_be_a_ballot_name(self):
        with self.with_file({"Someone": "Not On The Ballot"}):
            with self.assertRaises(ValueError):
                R.county_aliases()

    def test_a_spelling_cannot_be_another_candidates_name(self):
        order = self.roster_names()["mayor"]
        with self.with_file({order[0]: order[1]}):
            with self.assertRaises(ValueError):
                R.county_aliases()


def build_con():
    import sqlite3
    return sqlite3.connect(ROOT / "data" / "bouldervotes.db")


if __name__ == "__main__":
    unittest.main()
