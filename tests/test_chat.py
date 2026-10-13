"""The "Ask about this election" chat: grounding file, system prompt, page and script."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DOCS = ROOT / "docs"
API = DOCS / "api"
H = ROOT / "data" / "harvest" / "2026"
ASK_JS = ROOT / "static" / "chat" / "ask.js"

HARD_LIMIT = 215_000  # stays under the 100K-token price tier (measured ~2.3 bytes/token)
RECOMMEND = re.compile(r"you should vote|best candidate|we recommend|vote (yes|no) on|the right choice|"
                       r"vote for (him|her|them)|i recommend", re.I)


def ballot_names() -> list[str]:
    o = json.loads((H / "ballot_order.json").read_text(encoding="utf-8"))
    return o["races"]["mayor"] + o["races"]["council"]


class TestChatContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = (API / "chat-context.txt").read_text(encoding="utf-8")
        cls.system = (API / "chat-system.txt").read_text(encoding="utf-8")

    def test_size_cap(self):
        n = len(self.ctx.encode("utf-8"))
        self.assertLessEqual(n, HARD_LIMIT, f"chat-context.txt is {n:,} bytes; limit {HARD_LIMIT:,}")

    def test_deterministic(self):
        """Same data in, byte-identical text out (keeps the prompt cache warm)."""
        import sqlite3
        import build as B
        import build_chat_context as C
        import build_llm as L
        from build_forums_2026 import Forums2026
        con = sqlite3.connect(B.DB)
        con.row_factory = sqlite3.Row
        forums = Forums2026(con, B.OUT, B.page)
        d = L.collect(con, forums)
        con.close()
        asof = L.today().isoformat()
        a, b = C.chat_context(d, asof), C.chat_context(d, asof)
        self.assertEqual(a, b)
        self.assertEqual(a, self.ctx)

    def test_every_candidate_has_a_page_url(self):
        pages = json.loads((H / "ballot_order.json").read_text(encoding="utf-8"))
        self.assertTrue(pages)
        for name in ballot_names():
            self.assertIn(f"### {name},", self.ctx, name)
        slugs = re.findall(r"^Page: (https://bouldervotes\.org/people/[a-z0-9-]+\.html)", self.ctx, re.M)
        self.assertEqual(len(slugs), len(ballot_names()))

    def test_ballot_order(self):
        names = ballot_names()
        pos = [self.ctx.index(f"### {n},") for n in names]
        self.assertEqual(pos, sorted(pos))

    def test_every_measure_has_a_page_url(self):
        for letter in ("2J", "2K", "2L", "2M"):
            self.assertRegex(self.ctx, rf"### {letter}: .*\n\nPage: https://bouldervotes\.org/measures/2026-{letter.lower()}\.html")

    def test_quotes_carry_watch_links_and_caveat(self):
        self.assertIn("automatic transcript", self.ctx)
        self.assertGreater(self.ctx.count("  Watch: https://youtu.be/"), 100)
        self.assertIn("[speaker from speaking order]", self.ctx)

    def test_no_recommendation_language(self):
        for name, text in (("context", self.ctx), ("system", self.system)):
            m = RECOMMEND.search(text)
            self.assertIsNone(m, f"{name}: {m and m.group(0)}")

    def test_refuses_to_pick(self):
        for text in (self.ctx, self.system):
            self.assertRegex(text, r"[Nn]ever recommend")
            self.assertIn("ballot order", text)
        self.assertIn("nonpartisan", self.ctx.lower())

    def test_system_prompt_is_short(self):
        self.assertLessEqual(len(self.system), 2400)
        self.assertIn("bouldervotes.org", self.system)

    def test_review_round15_context_fixes(self):
        self.assertIn("In plain words (bouldervotes.org's summary, not the ballot text)", self.ctx)
        self.assertRegex(self.ctx, r"- F5: [^\n]* Mayoral candidates only\.")
        self.assertIn("## Side-by-side comparisons", self.ctx)
        self.assertIn("[compare budget mayor]", self.ctx)
        self.assertRegex(self.system, r"\[compare TOPIC RACE\]")
        self.assertRegex(self.system, r"Never say who is closest")

    def test_no_held_or_unpublished_text(self):
        self.assertNotIn("held back", self.ctx)


class TestChatEvalSet(unittest.TestCase):
    def test_eval_file_is_well_formed(self):
        items = json.loads((ROOT / "tools" / "chat_eval.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(items), 18)
        self.assertEqual([i["id"] for i in items], list(range(1, len(items) + 1)))
        for i in items:
            self.assertTrue(i["question"].strip() and i["expected"].strip())
        cats = {i["category"] for i in items}
        for need in ("factual", "comparison", "adversarial", "out_of_scope", "injection"):
            self.assertIn(need, cats)


class TestChatPage(unittest.TestCase):
    def test_flag_controls_page(self):
        on = os.environ.get("BV_CHAT_ENABLED") == "1"
        self.assertEqual((DOCS / "ask.html").exists(), on, "docs/ was built with a different BV_CHAT_ENABLED than this run")
        self.assertEqual((DOCS / "js" / "ask.js").exists(), on)
        home = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertEqual("ask.html" in home, on)

    def test_flag_default_off(self):
        import build_chat_context as C
        saved = os.environ.pop("BV_CHAT_ENABLED", None)
        try:
            self.assertFalse(C.chat_enabled())
            os.environ["BV_CHAT_ENABLED"] = "0"
            self.assertFalse(C.chat_enabled())
            os.environ["BV_CHAT_ENABLED"] = "1"
            self.assertTrue(C.chat_enabled())
        finally:
            os.environ.pop("BV_CHAT_ENABLED", None)
            if saved is not None:
                os.environ["BV_CHAT_ENABLED"] = saved

    def test_gateway_from_env(self):
        import build_chat_context as C
        saved = os.environ.pop("BV_CHAT_GATEWAY", None)
        try:
            self.assertEqual(C.chat_gateway(), "https://haiku-gateway.unforced.workers.dev")
            os.environ["BV_CHAT_GATEWAY"] = "https://preview.example.dev/"
            self.assertEqual(C.chat_gateway(), "https://preview.example.dev")
        finally:
            os.environ.pop("BV_CHAT_GATEWAY", None)
            if saved is not None:
                os.environ["BV_CHAT_GATEWAY"] = saved

    @unittest.skipUnless(os.environ.get("BV_CHAT_ENABLED") == "1", "ask.html is only built when BV_CHAT_ENABLED=1")
    def test_ask_page_content(self):
        s = (DOCS / "ask.html").read_text(encoding="utf-8")
        warn = "AI can be wrong. Check every answer against the linked source."
        self.assertIn(warn, s)
        self.assertLess(s.index(warn), s.index("<form"), "warning must come before the input")
        self.assertIn("<noscript>", s)
        self.assertIn('aria-live="polite"', s.replace("'", '"'))
        self.assertIn("data-gateway=", s)
        self.assertIn("js/ask.js", s)
        self.assertNotIn("<style", s)
        self.assertNotRegex(s, r"<script[^>]+src=[\"']https?://(?!static\.cloudflareinsights\.com)")

    def test_ask_js_has_no_third_party_or_cookies(self):
        js = ASK_JS.read_text(encoding="utf-8")
        self.assertNotIn("document.cookie", js)
        self.assertNotIn("localStorage", js)
        self.assertNotIn("sessionStorage", js)
        self.assertNotRegex(js, r"https?://[a-z]")  # no host is hard-coded; the gateway comes from the page


QUOTE = {"speaker": "Aquiles La Grave", "page": "https://bouldervotes.org/people/aquiles-la-grave.html", "text": "We need <b>more</b> homes.",
         "label": "League of Women Voters forum, September 26, 2026", "question": "What types of housing?", "code": "F4Q45",
         "link": "https://www.youtube.com/watch?v=abc&t=1s", "caveat": "Automatic transcript. Check the recording."}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestAskJsRendering(unittest.TestCase):
    def render(self, data: dict) -> str:
        code = ("const a=require(process.argv[1]);"
                "process.stdout.write(a.renderReply(JSON.parse(require('fs').readFileSync(0,'utf8'))));")
        r = subprocess.run(["node", "-e", code, str(ASK_JS)], input=json.dumps(data), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def reply(self, **kw) -> dict:
        base = {"say": [[{"t": "text", "text": "Short answer."}]], "compare": None, "sources": [], "next": ["One", "Two"]}
        base.update(kw)
        return {"ok": True, "answer": "x", "reply": base}

    def test_html_is_escaped_everywhere(self):
        evil = '<script>alert(1)</script><img src=x onerror=alert(1)>'
        q = dict(QUOTE, text=evil, caveat=evil, label=evil, speaker=evil)
        out = self.render(self.reply(say=[[{"t": "text", "text": evil}, {"t": "quote", "q": q}]],
                                     sources=[{"kind": "quote", "q": q}, {"kind": "text", "speaker": evil, "text": evil}],
                                     next=[evil, '"><script>x</script>']))
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;", out)

    def test_only_https_links_and_site_links_relative(self):
        q = dict(QUOTE, link="javascript:alert(1)", page="https://bouldervotes.org/people/x.html")
        out = self.render(self.reply(sources=[{"kind": "quote", "q": q}, {"kind": "note", "text": "see", "href": "http://evil.example/"}],
                                     say=[[{"t": "text", "text": "See https://bouldervotes.org/measures/2026-2j.html and https://example.org/a?b=1&c=2"}]]))
        self.assertNotIn("javascript:", out)
        self.assertNotIn('href="http://', out)
        self.assertIn('href="people/x.html"', out)
        self.assertIn('href="measures/2026-2j.html"', out)
        self.assertIn('href="https://example.org/a?b=1&amp;c=2" rel="noopener noreferrer"', out)

    def test_every_quote_has_its_caveat_beside_it(self):
        cmp = json.loads((API / "chat-compare.json").read_text(encoding="utf-8"))
        topic = next(t for t in cmp["topics"] if t["key"] == "housing")
        view = {"key": "housing", "label": topic["label"], "race": "mayor", "questions": topic["races"]["mayor"],
                "no_answer": cmp["no_answer"], "no_yesno": cmp["no_yesno"], "page": cmp["compare_page"]}
        out = self.render(self.reply(compare=view, sources=[{"kind": "quote", "q": QUOTE}],
                                     say=[[{"t": "text", "text": "La Grave said "}, {"t": "quote", "q": QUOTE}]]))
        quotes = out.count("<blockquote>") + out.count("<q>We need")
        self.assertGreater(quotes, 6)
        # each blockquote is followed by its own caveat line, before the next quote
        for chunk in out.split("<blockquote>")[1:]:
            self.assertRegex(chunk.split("<blockquote>")[0], r"class=\"cav-line\"><span class=\"cav\">(?:[^<]+\. )?(Automatic transcript|From the)")
        self.assertIn("<q>We need &lt;b&gt;more&lt;/b&gt; homes.</q> <span class=\"cav\">", out)
        self.assertIn("Show sources (1)", out)
        self.assertIn('<details class="srcs">', out)  # sources stay folded

    def test_compare_cards_gaps_and_yes_no(self):
        cmp = json.loads((API / "chat-compare.json").read_text(encoding="utf-8"))
        topic = next(t for t in cmp["topics"] if t["key"] == "housing")
        view = {"key": "housing", "label": topic["label"], "race": "mayor", "questions": topic["races"]["mayor"],
                "no_answer": cmp["no_answer"], "no_yesno": cmp["no_yesno"], "page": cmp["compare_page"]}
        out = self.render(self.reply(compare=view))
        names = re.findall(r'<p class="who"><span><a href="[^"]+">([^<]+)</a>', out)
        mayors = json.loads((H / "ballot_order.json").read_text(encoding="utf-8"))["races"]["mayor"]
        self.assertEqual(names, mayors + mayors)  # two questions, ballot order each time
        self.assertIn("No answer to this question on file.", out)  # Jacobs, Smith: no B3 answer
        self.assertIn('<span class="badge">Said YES</span>', out)
        self.assertIn("Yes. Boulder needs more housing choices", out)
        self.assertIn("Starts mid-sentence.", out)

    def test_no_yes_no_on_file_badge(self):
        cmp = json.loads((API / "chat-compare.json").read_text(encoding="utf-8"))
        topic = next(t for t in cmp["topics"] if t["key"] == "budget")
        view = {"key": "budget", "label": topic["label"], "race": "mayor", "questions": topic["races"]["mayor"], "measure": topic["measure"],
                "no_answer": cmp["no_answer"], "no_yesno": cmp["no_yesno"], "page": cmp["compare_page"]}
        out = self.render(self.reply(compare=view))
        self.assertIn('<span class="badge none">No yes/no on file</span>', out)
        self.assertIn("A yes vote:", out)

    def test_next_chips_are_buttons(self):
        out = self.render(self.reply(next=["What about 2K?", "Council on housing"]))
        self.assertEqual(out.count('<button type="button" class="chip" data-q='), 2)

    def test_plain_answer_fallback(self):
        out = self.render({"ok": True, "answer": "Line one.\n\n<b>two</b>"})
        self.assertIn("<p>Line one.</p>", out)
        self.assertNotIn("<b>two", out)


class TestCompareFile(unittest.TestCase):
    """docs/api/chat-compare.json: one shared question per comparison, every candidate, ballot order, exact lines."""

    @classmethod
    def setUpClass(cls):
        p = API / "chat-compare.json"
        if not p.exists():
            raise unittest.SkipTest("build first")
        cls.cmp = json.loads(p.read_text(encoding="utf-8"))
        cls.idx = json.loads((API / "chat-quotes.json").read_text(encoding="utf-8"))
        cls.ballot = json.loads((H / "ballot_order.json").read_text(encoding="utf-8"))["races"]

    def q(self, key, race):
        return next(t for t in self.cmp["topics"] if t["key"] == key)["races"][race]

    def test_budget_mayor_is_f4_q44_for_all_six(self):
        qs = self.q("budget", "mayor")
        self.assertEqual(len(qs), 1)
        self.assertTrue(qs[0]["question"].startswith("Ballot measure 2K"))
        self.assertRegex(qs[0]["code"], r"^F4Q\d+$")
        self.assertEqual([r["name"] for r in qs[0]["rows"]], self.ballot["mayor"])
        self.assertTrue(all(r["answered"] for r in qs[0]["rows"]))
        self.assertTrue(qs[0]["yesno"])

    def test_missing_answer_is_a_gap_never_a_substitute(self):
        qs = self.q("budget", "council")[0]
        missing = [r for r in qs["rows"] if not r["answered"]]
        self.assertTrue(missing)
        for r in missing:
            self.assertEqual(r["lines"], [])
        self.assertEqual(self.cmp["no_answer"], "No answer to this question on file.")
        self.assertEqual(self.cmp["no_yesno"], "No yes/no on file")

    def test_goldstein_b3_in_mayoral_housing(self):
        b3 = next(q for q in self.q("housing", "mayor") if q["code"] == "B3")
        g = next(r for r in b3["rows"] if r["name"] == "Jameson Goldstein")
        self.assertIn("Yes. Boulder needs more housing choices, especially duplexes and triplexes that can help families and middle-income resident stay here.",
                      [l["text"] for l in g["lines"]])
        self.assertEqual(g["badge"], "YES")
        self.assertEqual(g["lines"][0]["caveat"], "From the Better Boulder questionnaire.")

    def test_every_line_is_exact_and_from_the_same_question(self):
        recs = {(q["speaker"], q["text"], q["link"]): q for q in self.idx["quotes"]}
        for t in self.cmp["topics"]:
            for race, qs in t["races"].items():
                for q in qs:
                    self.assertEqual([r["name"] for r in q["rows"]], self.ballot[race], (t["key"], race))
                    for r in q["rows"]:
                        self.assertEqual(r["answered"], bool(r["lines"]))
                        for l in r["lines"]:
                            rec = recs.get((r["name"], l["text"], l["link"]))
                            self.assertIsNotNone(rec, (t["key"], race, r["name"], l["text"][:60]))
                            self.assertEqual(rec["code"], q["code"], (t["key"], race, r["name"]))
                            self.assertEqual(rec["caveat"], l["caveat"])

    def test_shared_question_is_the_most_answered(self):
        # Each forum question picked is one most candidates in that race answered (at least 3 in 4).
        for t in self.cmp["topics"]:
            for race, qs in t["races"].items():
                for q in qs:
                    if q["code"] != "B3" and not q["code"].startswith("B"):
                        self.assertGreaterEqual(q["answered"] / q["of"], 0.75, (t["key"], race, q["code"]))

    def test_council_not_offered_mayor_only_forum(self):
        self.assertNotIn("council", next(t for t in self.cmp["topics"] if t["key"] == "climate")["races"])


if __name__ == "__main__":
    unittest.main()


class TestQuoteIndex(unittest.TestCase):
    """docs/api/chat-quotes.json: the gateway verifies every quote in an answer against it."""

    @classmethod
    def setUpClass(cls):
        import json
        p = ROOT / "docs" / "api" / "chat-quotes.json"
        if not p.exists():
            raise unittest.SkipTest("build first")
        cls.idx = json.loads(p.read_text(encoding="utf-8"))
        cls.ctx = (ROOT / "docs" / "api" / "chat-context.txt").read_text(encoding="utf-8")

    def test_every_candidate_and_unique_aliases(self):
        names = [p["name"] for p in self.idx["people"]]
        self.assertEqual(len(names), len(set(names)))
        aliases = [a for p in self.idx["people"] for a in p["aliases"]]
        self.assertEqual(len(aliases), len(set(aliases)), "an alias must name one person")
        self.assertIn("La Grave", next(p for p in self.idx["people"] if p["name"] == "Aquiles La Grave")["aliases"])

    def test_quotes_match_context_and_speaker_section(self):
        # Each indexed quote sits under its speaker's own heading in chat-context.txt.
        sections, cur = {}, None
        for line in self.ctx.splitlines():
            if line.startswith("### "):
                cur = line[4:].split(",")[0].strip()
            if cur and line.startswith("  > "):
                sections.setdefault(cur, set()).add(line[4:].strip())
        for q in self.idx["quotes"]:
            self.assertIn(q["text"].strip(), sections.get(q["speaker"], set()), q)

    def test_labels_links_caveats_from_data(self):
        for q in self.idx["quotes"]:
            self.assertTrue(q["label"] and q["caveat"], q)
            self.assertTrue(q["link"].startswith("https://"), q)
            if re.match(r"^F\d+Q\d+$", q["code"]):
                self.assertTrue(q["caveat"].startswith("Automatic transcript. Check the recording."), q)
        g = [q for q in self.idx["quotes"] if q["speaker"] == "Jameson Goldstein" and q["code"].startswith("F3")]
        self.assertTrue(g)
        self.assertTrue(all(q["label"].startswith("Arts and culture forum, September 15") for q in g))
        smith = [q for q in self.idx["quotes"] if q["speaker"] == "Fred Smith" and q["text"].startswith("there's a thing called TABR")]
        self.assertTrue(smith[0]["question"].startswith("If elected, name your top three priorities"))
        b3 = [q for q in self.idx["quotes"] if q["code"] == "B3"]
        self.assertTrue(all(q["caveat"] == "From the Better Boulder questionnaire." for q in b3))
        for p in self.idx["people"]:
            self.assertIn(p["office"], ("mayor", "council"))

    def test_goldstein_la_grave_case(self):
        lg = [q for q in self.idx["quotes"] if "missing middle-income housing that" in q["text"]]
        self.assertTrue(lg)
        self.assertEqual({q["speaker"] for q in lg}, {"Aquiles La Grave"})

    def test_every_quote_line_names_speaker_and_topic(self):
        lines = self.ctx.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("  > ") and i and lines[i - 1].startswith("- ") and "reporting" not in lines[i - 1] and "reporter" not in lines[i - 1]:
                self.assertIn("Topic: ", lines[i - 1], lines[i - 1][:120])
