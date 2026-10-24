"""The About page names who makes the guide and links to his page, and person pages list gifts to 2026
campaigns from the clerk filings, matched to people in the guide without merging two different people."""
import re
import unittest
from pathlib import Path

from ingest import _donor_person_id

DOCS = Path(__file__).resolve().parent.parent / "docs"


class DonorMatch(unittest.TestCase):
    PID = {"Aaron Gabriel Neyer": 31, "Lisa Ann Jacobs": 17, "Sam Lee": 5, "Sam Q Lee": 6, "Sam R Lee": 7}

    def test_exact_name(self):
        self.assertEqual(_donor_person_id(self.PID, "Aaron Gabriel", "Neyer"), 31)

    def test_dropped_middle_name_matches_when_unique(self):
        self.assertEqual(_donor_person_id(self.PID, "Aaron", "Neyer"), 31)
        self.assertEqual(_donor_person_id(self.PID, "lisa", "jacobs"), 17)

    def test_ambiguous_pair_never_merges(self):
        # Two different people share first and last name: an exact two-word match still wins,
        # but nothing is guessed for a pair held by more than one middle-named person.
        self.assertEqual(_donor_person_id(self.PID, "Sam", "Lee"), 5)
        self.assertIsNone(_donor_person_id({"Sam Q Lee": 6, "Sam R Lee": 7}, "Sam", "Lee"))

    def test_unknown_or_partial(self):
        self.assertIsNone(_donor_person_id(self.PID, "Aaron", "Smith"))
        self.assertIsNone(_donor_person_id(self.PID, "", "Neyer"))


class Pages(unittest.TestCase):
    def test_about_links_maker_page(self):
        about = (DOCS / "about.html").read_text(encoding="utf-8")
        self.assertIn('<a href="people/aaron-gabriel-neyer.html">Aaron Gabriel Neyer</a>', about)
        self.assertTrue((DOCS / "people" / "aaron-gabriel-neyer.html").exists())

    def test_maker_page_lists_all_three_gifts(self):
        page = (DOCS / "people" / "aaron-gabriel-neyer.html").read_text(encoding="utf-8")
        self.assertIn("Gifts to 2026 campaigns", page)
        section = page.split("id='gifts'", 1)[1].split("</table>", 1)[0]
        for name in ("Rachel Rose Isaacson", "Jill Grano", "Ryan Schuchard"):
            self.assertIn(name, section)
        self.assertEqual(len(re.findall(r"<tr><td>", section)), 3)
