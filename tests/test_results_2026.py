"""Election-night results (BV_RESULTS): parser, wording rules, ballot order, caveat, flag.

The parser is tested on real Boulder County pages from the Nov 2023 election
(tests/fixtures/results_2023C, saved unmodified), cross-checked against the
recount-certified numbers already in the guide's database.
"""
from __future__ import annotations

import copy
import filecmp
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_results_2026 as R  # noqa: E402
import fetch_results_2026 as F  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
F2023 = FIX / "results_2023C"
DOCS = ROOT / "docs"
HAVE_PDFTOTEXT = shutil.which("pdftotext") is not None

# Words that call a race, project one, or rank by votes. None may appear in a results view.
CALL_WORDS = re.compile(r"\b(won|wins?|winners?|winning|lead|leads|leading|leader|ahead|trails?|trailing|"
                        r"elected|victory|victorious|defeat(?:ed|s)?|projected|projection|passed|passes|passing|"
                        r"failed|fails|failing|landslide|front-?runner|declared?|clinch(?:ed)?)\b", re.I)


def fixture_results() -> dict:
    return json.loads((F2023 / "results.json").read_text(encoding="utf-8"))


def visible(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


class TestParserOnRealCountyPages(unittest.TestCase):
    """tools/fetch_results_2026.py against the county's own 2023 and 2025 pages."""

    @classmethod
    def setUpClass(cls):
        cls.index = (F2023 / "index.html").read_text(encoding="utf-8")
        cls.con = sqlite3.connect(ROOT / "data" / "bouldervotes.db")

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_header(self):
        h = F.header(self.index)
        self.assertEqual(h["title"], "2023 Coordinated Election")
        self.assertEqual(h["county_status"], "Official Results")
        self.assertEqual(h["county_updated"], "2023-12-06T16:50:00-07:00")
        self.assertEqual(h["ballots_counted"], 119772)

    def test_only_city_contests_in_county_order(self):
        cs = F.contests(self.index, "https://example/")
        self.assertEqual([c["office"] for c in cs], ["mayor", "council", "measure", "measure", "measure"])
        council = cs[1]
        self.assertEqual(council["seats"], 4)
        self.assertEqual(council["official_url"], "https://example/#contest2")
        self.assertEqual([c["name"] for c in council["candidates"]][:3], ["Terri Brncic", "Jenny Robins", "Aaron Gabriel Neyer"])
        self.assertEqual(cs[0]["candidates"], [], "2023 mayor contest carries only a link to the ranked-choice page")
        self.assertTrue(cs[0]["rcv_page_url"].endswith("Home/RcvContest/1.html"))
        self.assertEqual([(m["code"], m["yes"], m["no"]) for m in cs[2:]],
                         [("2A", 24810, 8473), ("2B", 26137, 4153), ("302", 20261, 12973)])

    def test_council_matches_certified_numbers_in_db(self):
        cs = F.contests(self.index, "https://example/")
        parsed = {c["name"]: c["votes"] for c in cs[1]["candidates"]}
        db = dict(self.con.execute(
            """SELECT p.full_name, res.votes FROM results res JOIN candidacies c ON c.id=res.candidacy_id
               JOIN people p ON p.id=c.person_id JOIN races r ON r.id=c.race_id
               JOIN elections e ON e.id=r.election_id JOIN offices o ON o.id=r.office_id
               WHERE e.year=2023 AND o.slug='council'""").fetchall())
        db["Jenny Robins"] = db.pop("Jennifer Robins")  # the county lists her ballot name
        self.assertEqual(parsed, db)

    @unittest.skipUnless(HAVE_PDFTOTEXT, "pdftotext not installed")
    def test_rcv_report_pdf_matches_certified_rounds(self):
        rep = F.parse_rcv_report(F.pdf_text(F2023 / "COBMayorRCVShortPDF.pdf"))
        self.assertEqual(rep["report_time"], "2023-11-16T14:26:33-07:00")
        r1, r2 = rep["rounds"]
        self.assertEqual({c["name"]: c["votes"] for c in r1["candidates"]},
                         {"Aaron Brockett": 11504, "Nicole Speer": 6369, "Bob Yates": 14271, "Paul Tweedlie": 749})
        # Removed candidates drop out of later rounds instead of showing as 0.
        self.assertEqual({c["name"]: c["votes"] for c in r2["candidates"]}, {"Aaron Brockett": 16823, "Bob Yates": 15592})
        self.assertEqual((r1["continuing"], r2["continuing"], r1["inactive"], r2["inactive"]), (32893, 32415, 1356, 1834))

    @unittest.skipUnless(HAVE_PDFTOTEXT, "pdftotext not installed")
    def test_rcv_report_that_does_not_add_up_is_rejected(self):
        text = F.pdf_text(F2023 / "COBMayorRCVShortPDF.pdf").replace("16,823", "16,833")
        with self.assertRaises(F.ParseError):
            F.parse_rcv_report(text)

    @unittest.skipUnless(HAVE_PDFTOTEXT, "pdftotext not installed")
    def test_committed_fixture_json_is_the_parser_output(self):
        self.assertEqual(F.from_dir(F2023, "2023"), fixture_results())

    def test_stale_mirror_is_refused(self):
        # The county's mirror root still serves 2023 pages under Home/; a 2026 run must not use them.
        with self.assertRaises(F.ParseError):
            F.assemble(self.index, "https://example/", retrieved_at="x", raw_dir=None)

    def test_2025_page_format(self):
        cs = F.contests((FIX / "results_2025C_index.html").read_text(encoding="utf-8"), "https://example/")
        council = next(c for c in cs if c["office"] == "council")
        self.assertEqual(council["seats"], 4)  # "Vote for no more than Four", no parentheses
        self.assertEqual(len(council["candidates"]), 11)
        self.assertEqual([m["code"] for m in cs if m["office"] == "measure"], ["2A", "2B"])

    def test_2026_coming_soon_page_has_no_contests(self):
        page = (FIX / "results_2026G_coming_soon.html").read_text(encoding="utf-8")
        self.assertEqual(F.header(page)["title"], F.EXPECT_TITLE)
        self.assertEqual(F.contests(page, "https://example/"), [])

    def test_2026_check_wants_every_ballot_name(self):
        order = json.loads(F.BALLOT_ORDER.read_text())["races"]
        data = {"contests": [
            {"office": "mayor", "candidates": [{"name": n, "votes": 0} for n in order["mayor"]]},
            {"office": "council", "seats": 5, "candidates": [{"name": n, "votes": 0} for n in order["council"][1:]]},
            *[{"office": "measure", "code": c} for c in F.MEASURE_CODES_2026]]}
        probs = F.check_2026(data)
        self.assertEqual(len(probs), 1)
        self.assertIn(order["council"][0], probs[0])


class TestElectionNightFailureModes(unittest.TestCase):
    """Regressions from review: one bad piece must not stop or scramble the whole count."""

    @classmethod
    def setUpClass(cls):
        page = (F2023 / "index.html").read_text(encoding="utf-8")
        # The real 2023 page with this year's title: the shape the 2026 page will have.
        cls.page26 = page.replace('class="EnrHeaderTitle">2023 Coordinated Election', 'class="EnrHeaderTitle">2026 General Election')
        cls.rcv23 = (F2023 / "RcvContest-1.html").read_text(encoding="utf-8")

    def test_stale_ranked_choice_page_means_no_rounds_not_a_stop(self):
        d = F.assemble(self.page26, "https://example/", rcv_html=self.rcv23, rcv_url="https://example/rcv",
                       rcv_report={"rounds": [{"round": 1, "candidates": []}]}, retrieved_at="x", raw_dir=None)
        mayor = d["contests"][0]
        self.assertEqual(mayor["rounds"], [])
        self.assertEqual(len(d["contests"][1]["candidates"]), 10)

    def test_network_errors_fall_back_and_keep_the_rest(self):
        import urllib.error
        calls = []

        def fake_get(url):  # the county's servers are outside our control: fake them
            calls.append(url)
            if url == F.BASES[0]:
                raise urllib.error.URLError("mirror down")
            if url == F.BASES[1]:
                return self.page26.encode()
            raise urllib.error.HTTPError(url, 404, "not found", None, None)
        saved = F.get
        F.get = fake_get
        try:
            d = F.fetch_live(dry_run=True)
        finally:
            F.get = saved
        self.assertEqual(calls[:2], list(F.BASES))
        self.assertEqual(d["official_url"], F.BASES[1])
        self.assertEqual(d["contests"][0]["rounds"], [])
        self.assertIn("fetch failed", d["contests"][0]["rounds_error"])
        self.assertEqual([m["code"] for m in d["contests"] if m["office"] == "measure"], ["2A", "2B", "302"])

    def test_known_alias_is_not_a_missing_name(self):
        order = json.loads(F.BALLOT_ORDER.read_text())["races"]
        council = [{"name": "DAVID MARTUS" if n == "Dave Martus" else n, "votes": 0} for n in order["council"]]
        data = {"contests": [
            {"office": "mayor", "candidates": [{"name": n, "votes": 0} for n in order["mayor"]]},
            {"office": "council", "seats": 5, "candidates": council},
            *[{"office": "measure", "code": c} for c in F.MEASURE_CODES_2026]]}
        self.assertEqual(F.check_2026(data), [])

    def test_measure_title_naming_the_council_is_a_measure(self):
        page = self.page26.replace("Elections Administrative Charter Cleanup", "City Council Districts")
        self.assertNotEqual(page, self.page26)
        cs = F.contests(page, "https://example/")
        self.assertEqual([c["office"] for c in cs].count("council"), 1)
        self.assertIn("2B", [c.get("code") for c in cs])


def synthetic_2026(con, rounds: bool) -> dict:
    """2026 names in a scrambled order with zero votes: tests ordering, never published."""
    order = json.loads((ROOT / "data" / "harvest" / "2026" / "ballot_order.json").read_text())["races"]
    mayor = [{"name": n, "votes": 0} for n in reversed(order["mayor"])]
    council = [{"name": n, "votes": 0} for n in sorted(order["council"])]
    return {"election": {"name": "Boulder County 2026 General Election", "date": "2026-11-03"},
            "county_status": "Unofficial Results", "county_updated": "2026-11-03T21:42:00-07:00",
            "retrieved_at": "2026-11-04T04:45:00Z", "official_url": "https://electionresults.bouldercounty.gov/",
            "contests": [
                {"office": "mayor", "name": "City of Boulder Mayor", "candidates": mayor, "official_url": "u",
                 "rounds": ([{"round": 1, "candidates": list(reversed(mayor)), "continuing": 0}] if rounds else [])},
                {"office": "council", "name": "City of Boulder Council", "seats": 5, "candidates": council, "official_url": "u"},
                {"office": "measure", "code": "2K", "name": "x", "yes": 0, "no": 0},
                {"office": "measure", "code": "2J", "name": "y", "yes": 0, "no": 0}]}


class TestResultsViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(ROOT / "data" / "bouldervotes.db")
        cls.order = json.loads((ROOT / "data" / "harvest" / "2026" / "ballot_order.json").read_text())["races"]

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def views(self, data: dict) -> dict[str, str]:
        roster = R.roster_for(self.con, data)
        return {"page": R.results_body(data, roster),
                "home": R.home_card(data),
                "llms": "\n".join(R.results_md(data, roster, "https://bouldervotes.org")),
                "api": json.dumps(R.results_api(data, roster))}

    def test_rounds_only_when_recorded(self):
        data = fixture_results()
        page = R.mayor_section(data, R.roster_for(self.con, data))
        self.assertIn("Round 1", page)
        self.assertIn("Round 2", page)
        self.assertNotIn(R.NO_ROUNDS_NOTE, page)
        data["contests"][0]["rounds"] = []
        for name, v in self.views(data).items():
            if name == "api":
                self.assertEqual(json.loads(v)["contests"][0]["rounds"], [])
                continue
            with self.subTest(view=name):
                self.assertNotIn("Round 1", v)
                self.assertNotIn("round 1", v)
        self.assertIn(R.NO_ROUNDS_NOTE, self.views(data)["page"])
        self.assertNotIn("round by round", self.views(data)["page"])
        data["contests"][0]["rounds_error"] = "unreadable"
        page = R.mayor_section(data, R.roster_for(self.con, data))
        self.assertIn(R.ROUNDS_UNREAD_NOTE, page)
        self.assertNotIn("Round 1", page)

    def test_first_choices_never_labelled_as_a_winner(self):
        for data in (fixture_results(), synthetic_2026(self.con, rounds=False), synthetic_2026(self.con, rounds=True)):
            views = self.views(data)
            for name, v in views.items():
                with self.subTest(view=name, election=data["election"]["name"]):
                    text = visible(v) if name in ("page", "home") else v
                    self.assertIsNone(CALL_WORDS.search(text), CALL_WORDS.search(text))
            mayor = R.mayor_section(data, R.roster_for(self.con, data))
            self.assertIn("First-choice votes", mayor)
            self.assertIn("These are first choices only, not the result", mayor)
            self.assertIn("first-choice votes only", views["llms"])
            self.assertIn("not the ranked-choice result", views["api"])

    def test_ballot_order(self):
        for rounds in (False, True):
            data = synthetic_2026(self.con, rounds)
            roster = R.roster_for(self.con, data)
            page = R.results_body(data, roster)
            for office, sec in (("mayor", R.mayor_section(data, roster)), ("council", R.council_section(data, roster))):
                with self.subTest(office=office, rounds=rounds):
                    pos = [sec.index(f">{n}</a>") for n in self.order[office]]
                    self.assertEqual(pos, sorted(pos), f"{office} not in ballot order")
            self.assertIn("Listed in ballot order.", page)
            # Measures in code order; candidates in the JSON and llms block in ballot order too.
            self.assertLess(page.index(">2J<"), page.index(">2K<"))
            api = R.results_api(data, roster)
            self.assertEqual([c["name"] for c in api["contests"][1]["candidates"]], self.order["council"])
            md = "\n".join(R.results_md(data, roster, ""))
            pos = [md.index(f"- {n}:") for n in self.order["mayor"]]
            self.assertEqual(pos, sorted(pos))

    def test_other_years_do_not_claim_ballot_order(self):
        data = fixture_results()  # 2023: the guide has no sourced ballot order for that year
        page = R.results_body(data, R.roster_for(self.con, data))
        self.assertNotIn("ballot order", page)
        self.assertIn("up to four", page)

    def test_one_unmatched_spelling_keeps_the_county_order(self):
        data = synthetic_2026(self.con, rounds=False)
        county = [{"name": n, "votes": 0} for n in self.order["council"]]
        county[0]["name"] = "Lee Gilbertson"  # a spelling we can't match
        data["contests"][1]["candidates"] = list(reversed(county))
        roster = R.roster_for(self.con, data)
        sec = R.council_section(data, roster)
        self.assertEqual(roster.ballot_sorted("council", data["contests"][1]["candidates"]), data["contests"][1]["candidates"])
        self.assertNotIn("Listed in ballot order", sec)
        self.assertIn("the order the county lists them", sec)

    def test_as_of_never_passes_our_copy_time_off_as_the_county_time(self):
        data = synthetic_2026(self.con, rounds=False)
        data["county_updated"] = None
        for v in (R.home_card(data), "\n".join(R.results_md(data, R.roster_for(self.con, data), ""))):
            self.assertNotIn("count as of", v)
            self.assertIn("Copied from Boulder County at", v)

    def test_measures_are_equal_neutral_panels(self):
        page = R.measures_section(fixture_results(), R.roster_for(self.con, fixture_results()))
        self.assertEqual(page.count("<dt>Yes</dt>"), page.count("<dt>No</dt>"))
        self.assertNotIn("Passed", page)
        css = (ROOT / "static" / "results" / "results.css").read_text()
        self.assertNotRegex(css, r"res-yes\b|res-no\b|\.yes\b|\.no\b", "YES and NO must share one style")

    def test_every_number_links_to_the_county(self):
        data = fixture_results()
        page = R.results_body(data, R.roster_for(self.con, data))
        nums = re.findall(r"<td class='num'>([^<]*<[^>]*>)?[\d,]+", page)
        self.assertTrue(nums)
        for cell in re.findall(r"<td class='num'>(.*?)</td>", page):
            if "%" in cell or cell == "–":
                continue
            self.assertRegex(cell, r"^<a class='res-num' href='https://electionresults\.bouldercounty\.gov/")

    def test_fetched_strings_are_escaped_and_links_stay_https(self):
        """Names, titles and links come from a web page; none may become markup or script."""
        data = fixture_results()
        bad = "<script>alert(1)</script>"
        data["official_url"] = "javascript:alert(1)"
        data["county_status"] = bad
        mayor = next(c for c in data["contests"] if c["office"] == "mayor")
        mayor["candidates"].append({"name": "Write-in " + bad, "votes": 1})
        mayor["rounds"] = []
        mayor["rounds_error"] = bad
        mayor["rounds_url"] = "data:text/html,<b>x</b>"
        council = next(c for c in data["contests"] if c["office"] == "council")
        council["official_url"] = "javascript:alert(2)"
        measure = next(c for c in data["contests"] if c["office"] == "measure")
        measure["name"] = bad
        measure["code"] = "'><img src=x onerror=alert(3)>"
        html = "\n".join([R.results_body(data, R.roster_for(self.con, data)), R.home_card(data)])
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("data:", html)
        for link in re.findall(r"href='([^']*)'", html):
            self.assertRegex(link, r"^(https://|people/|measures/|results\.html|#)", link)

    def test_unofficial_caveat_on_every_results_view(self):
        for data in (fixture_results(), synthetic_2026(self.con, rounds=False)):
            for name, v in self.views(data).items():
                with self.subTest(view=name):
                    self.assertIn(R.CAVEAT, v)
            self.assertIn("as of", visible(self.views(data)["page"]))
        self.assertIn(R.CAVEAT, R.results_body(None, R.Roster(None, 2026)))

    def test_built_docs_follow_the_flag(self):
        on = R.results_enabled()
        self.assertEqual((DOCS / "results.html").exists(), on, "docs/ was built with a different BV_RESULTS than this run")
        self.assertEqual((DOCS / "css" / "results.css").exists(), on)
        home = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertEqual("results.html" in home, on)
        if not on:
            self.assertFalse((DOCS / "api" / "v1" / "results.json").exists())
            self.assertNotIn("results.json", (DOCS / "llms.txt").read_text(encoding="utf-8"))
            return
        self.assertIn(R.CAVEAT, (DOCS / "results.html").read_text(encoding="utf-8"))
        if R.load_results() is not None:
            for f in ("index.html", "llms.txt", "llms-full.txt", "api/v1/results.json"):
                with self.subTest(file=f):
                    self.assertIn(R.CAVEAT, (DOCS / f).read_text(encoding="utf-8"))


class TestFlag(unittest.TestCase):
    def test_default_off_with_explicit_switch(self):
        saved = os.environ.pop("BV_RESULTS", None)
        try:
            self.assertFalse(R.results_enabled(), "default flips to on only on election night (RESULTS-RUNBOOK.md)")
            os.environ["BV_RESULTS"] = "1"
            self.assertTrue(R.results_enabled())
            os.environ["BV_RESULTS"] = "0"
            self.assertFalse(R.results_enabled())
        finally:
            os.environ.pop("BV_RESULTS", None)
            if saved is not None:
                os.environ["BV_RESULTS"] = saved


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipIf(os.environ.get("BV_SKIP_SLOW") == "1", "BV_SKIP_SLOW=1")
class TestFlagOffMatchesMain(unittest.TestCase):
    """With BV_RESULTS off, a results.json changes nothing in docs/. Builds this tree twice
    from scratch in temp folders (~20 s): once without results.json, once with the fixture.
    Set BV_BASE_REF to compare against a git ref's build instead (for results-code PRs);
    the default is the tree itself, so data PRs, which rightly change docs/, still pass."""

    def test_flag_off_build_is_byte_identical_to_main(self):
        try:
            ref = os.environ.get("BV_BASE_REF")
            base = _git("merge-base", "HEAD", ref) if ref else "HEAD"
            files = _git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.skipTest(f"git unavailable: {e}")
        with tempfile.TemporaryDirectory() as tmp:
            main_dir, head_dir = Path(tmp) / "main", Path(tmp) / "head"
            main_dir.mkdir()
            if ref:
                archive = subprocess.run(["git", "archive", base], cwd=ROOT, check=True, capture_output=True).stdout
                subprocess.run(["tar", "-x", "-C", str(main_dir)], input=archive, check=True)
            for f in files:
                if f and (ROOT / f).is_file():
                    for d in ((head_dir,) if ref else (head_dir, main_dir)):
                        (d / f).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(ROOT / f, d / f)
            if not ref:
                (main_dir / "data" / "harvest" / "2026" / "results.json").unlink(missing_ok=True)
            shutil.copy2(F2023 / "results.json", head_dir / "data" / "harvest" / "2026" / "results.json")
            env = {k: v for k, v in os.environ.items() if not k.startswith("BV_RESULTS")}
            env["BV_TODAY"] = "2026-11-01"
            # BV_RESULTS=0 on both sides keeps this true after the election-night default flip.
            for d, extra in ((main_dir, {"BV_RESULTS": "0"}), (head_dir, {"BV_RESULTS": "0"})):
                for script in ("seed.py", "build.py"):
                    subprocess.run([sys.executable, script], cwd=d, env={**env, **extra}, check=True, capture_output=True)
            diffs = []

            def walk(c: filecmp.dircmp, rel: str = "") -> None:
                diffs.extend(f"{rel}{x}" for x in c.left_only + c.right_only + c.funny_files)
                _, mismatch, errors = filecmp.cmpfiles(c.left, c.right, c.common_files, shallow=False)
                diffs.extend(f"{rel}{x}" for x in mismatch + errors)
                for name, sub in c.subdirs.items():
                    walk(sub, f"{rel}{name}/")
            walk(filecmp.dircmp(main_dir / "docs", head_dir / "docs"))
            self.assertEqual(diffs, [], f"flag-off docs/ differ from main ({base[:8]})")


if __name__ == "__main__":
    unittest.main()
