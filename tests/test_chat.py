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
        self.assertIn("- compare budget mayor:", self.ctx)
        self.assertIn("[intent compare TOPIC RACE]", self.system)

    def test_fix_round3_model_only_classifies(self):
        # The model writes nothing the voter reads: two bracketed lines, an intent and chip ids.
        self.assertIn("You never write anything the voter reads", self.system)
        for k in ("[intent measure LETTER]", "[intent basics TOPIC]", "[intent candidate NAME]", "[intent decline pick]",
                  "[intent decline label]", "[intent decline closest]", "[intent decline opinion]", "[intent unknown]", "[chips ID ID ID]"):
            self.assertIn(k, self.system)
        self.assertNotIn("[sources]", self.system)
        self.assertNotIn("[next]", self.system)
        self.assertNotIn("tally", self.ctx.split("## Side-by-side comparisons")[1].split("##")[0])
        self.assertIn("recorded excerpts", self.ctx)
        self.assertNotIn("full answer", self.ctx)
        self.assertNotIn("(copy BOTH lists", self.ctx)
        self.assertNotIn("(copy this whole list", self.ctx)

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


class TestAskJsRendering(unittest.TestCase):
    """static/chat/ask.js renders only the gateway's structured reply: escaped, data links, caveats beside quotes."""

    def render(self, data: dict) -> str:
        code = ("const a=require(process.argv[1]);"
                "process.stdout.write(a.renderReply(JSON.parse(require('fs').readFileSync(0,'utf8'))));")
        r = subprocess.run(["node", "-e", code, str(ASK_JS)], input=json.dumps(data), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def reply(self, **kw) -> dict:
        base = {"intent": "unknown", "say": [[{"t": "text", "text": "Short answer."}]], "compare": None, "candidate": None, "measure": None, "pages": [], "next": ["One", "Two"]}
        base.update(kw)
        return {"ok": True, "answer": "x", "reply": base}

    def view(self, key, race="mayor"):
        cmp = json.loads((API / "chat-compare.json").read_text(encoding="utf-8"))
        topic = next(t for t in cmp["topics"] if t["key"] == key)
        return {"key": key, "label": topic["label"], "race": race, "questions": topic["races"][race],
                "no_answer": cmp["no_answer"], "page": cmp["compare_page"]}

    def measure(self, letter):
        cmp = json.loads((API / "chat-compare.json").read_text(encoding="utf-8"))
        return next(m for m in cmp["measures"] if m["letter"] == letter)

    def test_html_is_escaped_everywhere(self):
        evil = '<script>alert(1)</script><img src=x onerror=alert(1)>'
        m = dict(self.measure("2K"), title=evil, yes_means=evil, money={"text": evil, "link": "https://bouldercolorado.gov/x"},
                 groups={"supports": [{"name": evil, "date": evil, "link": "https://x.org/", "note": evil}], "opposes": []})
        cand = {"name": evil, "page": "https://bouldervotes.org/p.html", "race": "mayor", "no_answer": evil,
                "items": [{"key": "housing", "noun": evil, "code": "F4Q45", "label": evil, "question": evil,
                           "lines": [{"text": evil, "caveat": evil, "link": "https://youtu.be/x", "short": True, "more": "Short excerpt. " + evil}]}]}
        out = self.render(self.reply(say=[[{"t": "text", "text": evil}, {"t": "link", "text": evil, "href": "https://bouldervotes.org/"}]],
                                     measure=m, candidate=cand, pages=[{"name": evil, "page": "https://bouldervotes.org/p.html"}],
                                     next=[evil, '"><script>x</script>']))
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;", out)

    def test_links_https_only_say_links_only_on_allowlisted_sites(self):
        m = dict(self.measure("2K"), official="javascript:alert(1)", page="https://bouldervotes.org/measures/2026-2k.html")
        out = self.render(self.reply(measure=m, say=[[{"t": "text", "text": "See https://bouldervotes.org/measures/2026-2j.html"}],
                                                     [{"t": "link", "text": "ok", "href": "https://bouldercolorado.gov/a?b=1&c=2"},
                                                      {"t": "link", "text": "yt", "href": "https://www.youtube.com/watch?v=evil"},
                                                      {"t": "link", "text": "bad", "href": "http://evil.example/"},
                                                      {"t": "link", "text": "evil", "href": "https://evil.example.org/x"}]]))
        self.assertNotIn("javascript:", out)
        self.assertNotIn('href="http://', out)
        self.assertIn('href="measures/2026-2k.html"', out)
        self.assertNotIn('href="measures/2026-2j.html"', out)  # text is never turned into a link
        self.assertIn('href="https://bouldercolorado.gov/a?b=1&amp;c=2" rel="noopener noreferrer"', out)
        self.assertNotIn('href="https://evil.example.org', out)
        self.assertNotIn('href="https://www.youtube.com/watch?v=evil"', out)  # not every youtube link: only card data

    def test_no_reply_object_is_a_neutral_error_never_raw_text(self):
        out = self.render({"ok": True, "answer": "Brockett said yes and Adams opposed it."})
        self.assertNotIn("Brockett", out)
        self.assertIn("Something went wrong with that answer", out)
        src = ASK_JS.read_text(encoding="utf-8")
        self.assertIn("data.reply && data.reply.say", src)  # a response without a reply is treated as an error

    def test_a_card_line_without_a_caveat_never_prints_undefined(self):
        v = self.view("housing")
        for q in v["questions"]:
            for r in q["rows"]:
                for l in r["lines"]:
                    l.pop("caveat", None)
        out = self.render(self.reply(compare=v))
        self.assertNotIn("undefined", out)
        self.assertIn("Check the source.", out)

    def test_every_card_quote_has_its_caveat_beside_it(self):
        out = self.render(self.reply(compare=self.view("housing")))
        self.assertGreater(out.count("<blockquote>"), 6)
        for chunk in out.split("<blockquote>")[1:]:
            self.assertRegex(chunk.split("<blockquote>")[0], r"class=\"cav-line\"><span class=\"cav\">(Automatic transcript|From the)")
        self.assertIn("recorded excerpts", out)
        # "full answer" only as the way to it from a short excerpt, never as a claim about what the card is.
        self.assertNotIn("full answer", re.sub(r"(watch|read) the full answer|not full answers", "", out.lower()))

    def test_compare_cards_gaps_no_badges_and_short_excerpts(self):
        out = self.render(self.reply(compare=self.view("housing")))
        names = re.findall(r'<p class="who"><span><a href="[^"]+">([^<]+)</a>', out)
        mayors = json.loads((H / "ballot_order.json").read_text(encoding="utf-8"))["races"]["mayor"]
        self.assertEqual(names, mayors + mayors)  # two questions, ballot order each time
        self.assertIn("No answer to this question on file.", out)  # Jacobs, Smith: no B3 answer
        self.assertNotIn("badge", out)
        self.assertNotRegex(out, r"Said (YES|NO)|No yes/no")
        self.assertIn("Yes. Boulder needs more housing choices", out)
        # Goldstein's "is to implement this vacancy tax." is a short excerpt, with the way to the full answer.
        self.assertRegex(out, r"is to implement this vacancy tax\.\u201d</p></blockquote><p class=\"cav-line\"><span class=\"cav\">Automatic transcript\. Check the recording\. "
                              r"Short excerpt\. <a href=\"https://[^\"]+\" rel=\"noopener noreferrer\">Watch the full answer\.</a>")
        out2 = self.render(self.reply(compare=self.view("downtown")))
        self.assertIn("Short excerpt. <a", out2)
        self.assertIn("Read the full answer.</a>", out2)  # questionnaire lines are read, not watched

    def test_mid_sentence_flags_render_as_short_excerpts(self):
        """Fix round 4 (D4): a line flagged mid_sentence or ends_mid always shows the short-excerpt label, even
        if the reply lost its short/more fields; connectives and dangling ends count as mid-sentence."""
        from build_chat_context import ends_mid, short_excerpt, starts_mid
        la_grave = "So I'm an absolute supporter of safer alternative transiting options than can."
        self.assertTrue(starts_mid(la_grave))
        self.assertTrue(short_excerpt(la_grave, "https://youtu.be/x")["short"])
        for t in ("That means completing the core arterial network.", "Because we need homes.", "And I'm against it.", "But not yet."):
            self.assertTrue(starts_mid(t), t)
        self.assertFalse(starts_mid("Sofia and I think so."))
        self.assertTrue(ends_mid("families that want to stay in the."))
        self.assertTrue(ends_mid("more homes than"))
        self.assertFalse(ends_mid("I think so."))
        line = {"text": la_grave, "caveat": "Automatic transcript. Check the recording.", "link": "https://youtu.be/x",
                "label": "LWV", "mid_sentence": True, "ends_mid": False}
        v = {"key": "transportation", "label": "Bus lanes", "race": "mayor", "no_answer": "No answer to this question on file.", "page": "compare.html",
             "questions": [{"code": "F4Q37", "label": "LWV", "question": "Q?", "rows": [
                 {"name": "Aquiles La Grave", "page": "https://bouldervotes.org/p.html", "ballot_position": 6, "answered": True, "lines": [line]},
                 {"name": "B", "page": "https://bouldervotes.org/b.html", "ballot_position": 7, "answered": True,
                  "lines": [dict(line, text="x y z.", mid_sentence=False, ends_mid=True, link="https://betterboulder.com/q")]}]}]}
        out = self.render(self.reply(compare=v))
        self.assertIn("Short excerpt. <a href=\"https://youtu.be/x\" rel=\"noopener noreferrer\">Watch the full answer.</a>", out)
        self.assertIn("Short excerpt. <a href=\"https://betterboulder.com/q\" rel=\"noopener noreferrer\">Read the full answer.</a>", out)
        # And in the data: every flagged line carries the label.
        for t in json.loads((API / "chat-compare.json").read_text(encoding="utf-8"))["topics"]:
            for qs in t["races"].values():
                for q in qs:
                    for r in q["rows"]:
                        for l in r["lines"]:
                            if l["mid_sentence"] or l["ends_mid"]:
                                self.assertTrue(l.get("short"), l["text"][:60])

    def test_question_header_is_neutral_and_whole(self):
        """Fix round 4 (D5): not "Asked of every candidate" (nothing shows every candidate was there); the
        question is shown whole, not cut at 220 characters."""
        v = self.view("housing")
        out = self.render(self.reply(compare=v))
        self.assertNotIn("Asked of every candidate", out)
        self.assertNotIn("every candidate was asked", out)
        self.assertIn("The question put to candidates (", out)
        b3 = next(q for q in v["questions"] if q["code"] == "B3")["question"]
        self.assertGreater(len(b3), 220)
        self.assertIn("did you vote to make it easier to build duplexes and triplexes?]", out)
        src = ASK_JS.read_text(encoding="utf-8")
        self.assertNotIn("truncate(", src)
        self.assertNotRegex(src, r"every group on each side|Asked of every")

    def test_candidate_view_renders_their_excerpts_with_caveats(self):
        cmp = json.loads((API / "chat-compare.json").read_text(encoding="utf-8"))
        items = []
        for t in cmp["topics"]:
            for q in t["races"].get("mayor", []):
                row = next(r for r in q["rows"] if r["name"] == "Fred Smith")
                items.append({"key": t["key"], "noun": t["noun"], "code": q["code"], "label": q["label"], "question": q["question"], "lines": row["lines"]})
        out = self.render(self.reply(candidate={"name": "Fred Smith", "page": "https://bouldervotes.org/people/fred-smith.html", "race": "mayor",
                                                "items": items, "no_answer": cmp["no_answer"]}))
        self.assertIn("recorded excerpts on the questions put to the candidates", out)
        self.assertIn("No answer to this question on file.", out)
        for chunk in out.split("<blockquote>")[1:]:
            self.assertIn('class="cav-line"><span class="cav">', chunk)
        self.assertIn('href="people/fred-smith.html"', out)

    def test_measure_card_from_data_with_sources_folded(self):
        m = self.measure("2K")
        out = self.render(self.reply(measure=m))
        self.assertIn("In plain words: bouldervotes.org's summary".replace("'", "&#39;"), out)
        self.assertIn('<details class="srcs"><summary>Show sources</summary>', out)
        self.assertIn("maximum total repayment $650 million", out)
        for g in m["groups"]["supports"] + m["groups"]["opposes"]:
            self.assertIn(g["name"].replace("&", "&amp;"), out)

    def test_next_chips_are_buttons(self):
        out = self.render(self.reply(next=["What about 2K?", "Council on housing"]))
        self.assertEqual(out.count('<button type="button" class="chip" data-q='), 2)


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
        self.assertNotIn("yesno", qs[0])

    def test_missing_answer_is_a_gap_never_a_substitute(self):
        qs = self.q("budget", "council")[0]
        missing = [r for r in qs["rows"] if not r["answered"]]
        self.assertTrue(missing)
        for r in missing:
            self.assertEqual(r["lines"], [])
        self.assertEqual(self.cmp["no_answer"], "No answer to this question on file.")
        self.assertNotIn("no_yesno", self.cmp)

    def test_goldstein_b3_in_mayoral_housing(self):
        b3 = next(q for q in self.q("housing", "mayor") if q["code"] == "B3")
        g = next(r for r in b3["rows"] if r["name"] == "Jameson Goldstein")
        self.assertIn("Yes. Boulder needs more housing choices, especially duplexes and triplexes that can help families and middle-income resident stay here.",
                      [l["text"] for l in g["lines"]])
        self.assertNotIn("badge", g)
        self.assertEqual(g["lines"][0]["caveat"], "From the Better Boulder questionnaire.")

    def test_one_answer_per_questionnaire_question(self):
        """Fix round 4 (D1): Duran's and Marquis's Core Arterial Network answers were filed under the
        duplex question (B3). Each questionnaire row now has at most one line, and the build stops if not."""
        from build_chat_context import check_one_answer_per_question
        check_one_answer_per_question(self.idx, self.cmp)
        for t in self.cmp["topics"]:
            for race, qs in t["races"].items():
                for q in qs:
                    for r in q["rows"]:
                        texts = [l["text"] for l in r["lines"]]
                        self.assertEqual(len(texts), len(set(texts)), (t["key"], race, q["code"], r["name"]))
                        if q["code"].startswith("B"):
                            self.assertLessEqual(len(texts), 1, (t["key"], race, q["code"], r["name"]))
        b3 = {r["name"]: [l["text"] for l in r["lines"]]
              for r in next(q for q in self.q("housing", "council") if q["code"] == "B3")["rows"]}
        self.assertEqual(b3["Tina Marquis"], ["No. While I did vote no in 2025, I did support allowing duplexes and triplexes in more areas during the comp plan process."])
        self.assertEqual(b3["Benita Duran"], ["Yes. It helps."])
        b2 = {r["name"]: [l["text"] for l in r["lines"]]
              for r in next(q for q in self.q("transportation", "council") if q["code"] == "B2")["rows"]}
        self.assertEqual(b2["Tina Marquis"], ["Yes. No additional comment submitted."])
        self.assertEqual(b2["Benita Duran"], ["Yes. No additional comment submitted."])
        # Fix round 5: the four CAN answers the research harvest deduplicated away are back.
        for name in ("Sam Fuqua", "Jill Grano", "Rachel Rose Isaacson", "Jamillah Richmond"):
            self.assertEqual(b2[name], ["Yes. No additional comment submitted."], name)
        self.assertEqual([n for n, t in b2.items() if not t], ["Lynn Segal"])  # not on the questionnaire page
        b4 = {r["name"]: [l["text"] for l in r["lines"]]
              for r in next(q for q in self.q("downtown", "council") if q["code"] == "B4")["rows"]}
        self.assertTrue(b4["Ryan Schuchard"][0].startswith("No. I don’t think it’s right to hand the decision"))
        self.assertEqual([n for n, t in b4.items() if not t], ["Lynn Segal"])

    def test_build_stops_on_two_answers_to_one_questionnaire_question(self):
        from build_chat_context import check_one_answer_per_question
        rec = {"speaker": "A B", "kind": "own", "code": "B3", "text": "Yes."}
        with self.assertRaises(SystemExit):
            check_one_answer_per_question({"quotes": [rec, {**rec, "text": "No."}]}, {"topics": []})
        row = {"name": "A B", "lines": [{"text": "Yes."}, {"text": "No."}]}
        cmp = {"topics": [{"key": "housing", "races": {"council": [{"code": "B3", "rows": [row]}]}}]}
        with self.assertRaises(SystemExit):
            check_one_answer_per_question({"quotes": [rec]}, cmp)
        # Two excerpts of one forum answer are fine; the same excerpt twice is not.
        cmp["topics"][0]["races"]["council"][0]["code"] = "F4Q35"
        check_one_answer_per_question({"quotes": [rec]}, cmp)
        row["lines"][1]["text"] = "Yes."
        with self.assertRaises(SystemExit):
            check_one_answer_per_question({"quotes": [rec]}, cmp)

    def test_every_line_is_exact_and_from_the_same_question(self):
        # Keyed by question code too: one candidate can give the same words to two questions
        # ("Yes. No additional comment submitted." to both B2 and B3), and each is its own record.
        recs = {(q["speaker"], q["text"], q["link"], q["code"]): q for q in self.idx["quotes"]}
        for t in self.cmp["topics"]:
            for race, qs in t["races"].items():
                for q in qs:
                    self.assertEqual([r["name"] for r in q["rows"]], self.ballot[race], (t["key"], race))
                    for r in q["rows"]:
                        self.assertEqual(r["answered"], bool(r["lines"]))
                        for l in r["lines"]:
                            rec = recs.get((r["name"], l["text"], l["link"], q["code"]))
                            self.assertIsNotNone(rec, (t["key"], race, q["code"], r["name"], l["text"][:60]))
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

    def test_every_question_has_a_short_name_and_no_efa_prefix(self):
        for t in self.cmp["topics"]:
            for race, qs in t["races"].items():
                for q in qs:
                    self.assertTrue(q["short"], (t["key"], race))
                    self.assertFalse(q["question"].startswith("(EFA)"), (t["key"], race))
        for x in self.idx["quotes"]:
            self.assertFalse((x.get("question") or "").startswith("(EFA)"), x["text"][:60])

    def test_no_badges_or_yesno_until_stances_are_hand_reviewed(self):
        # Fix round 3: yes/no badges and tallies were uneven for plain-language answers, so none are shipped.
        self.assertNotRegex(json.dumps(self.cmp), r'"badge"|"yesno"|"no_yesno"')
        for x in self.idx["quotes"]:
            if x["kind"] == "reporter":
                self.assertNotIn("stance", x, x["text"][:60])

    def test_short_excerpts_by_one_rule(self):
        n = 0
        for t in self.cmp["topics"]:
            for qs in t["races"].values():
                for q in qs:
                    for r in q["rows"]:
                        for l in r["lines"]:
                            thin = l["mid_sentence"] or l["ends_mid"] or len(l["text"].split()) < 12
                            self.assertEqual(bool(l.get("short")), thin, l["text"][:60])
                            if thin:
                                n += 1
                                video = "youtu" in (l["link"] or "")
                                self.assertEqual(l["more"], "Short excerpt. " + ("Watch" if video else "Read") + " the full answer.")
        self.assertGreater(n, 10)

    def test_measure_yes_no_symmetric(self):
        # Fix round 3: the same words with and without "not"; no consequence clause on one side only.
        for m in self.cmp["measures"]:
            self.assertEqual(m["yes_means"], f"A yes vote would {m['change']}.")
            self.assertEqual(m["no_means"], f"A no vote would not {m['change']}.")
            self.assertNotRegex(m["change"], r";|, increasing|existing building needs|may not be issuable")
            self.assertIn("summary of the city's ballot information", m["plain"])

    def test_basics_from_data(self):
        b = self.cmp["basics"]
        self.assertIn("7 p.m.", b["deadline"])
        self.assertTrue(b["rcv_count"].startswith("If nobody has more than half"))
        self.assertEqual(b["rcv_source"], "https://bouldercolorado.gov/guide/ranked-choice-voting-guide")
        self.assertEqual(b["mayor"]["count"], len(self.ballot["mayor"]))
        self.assertEqual(b["council"]["count"], len(self.ballot["council"]))
        self.assertEqual([d["date"] for d in b["key_dates"]], ["October 2", "October 19", "October 26", "November 3"])
        self.assertFalse(any("http" in x for x in b["how_to_vote"] + b["register"]))
        for t in self.cmp["topics"]:
            self.assertTrue(t["noun"], t["key"])

    def test_lines_flag_mid_sentence_at_both_ends(self):
        for t in self.cmp["topics"]:
            for qs in t["races"].values():
                for q in qs:
                    for r in q["rows"]:
                        for l in r["lines"]:
                            t_ = l["text"].rstrip()
                            self.assertEqual(l["ends_mid"], not t_.endswith(tuple(".!?…\"”'’)")) or
                                             bool(re.search(r"\b(?:the|a|an|and|or|but|of|than|because)\W*$", t_, re.I)), t_[-30:])
                            self.assertEqual(l["mid_sentence"], t_[:1].islower() or
                                             bool(re.match(r"(?:that means|because|so|and|but|or)\b", t_, re.I)), t_[:30])
        adams = next(r for r in self.q("budget", "mayor")[0]["rows"] if r["name"] == "Taishya Adams")
        self.assertTrue(any(l["ends_mid"] for l in adams["lines"]))

    def test_measure_facts_and_groups_from_data(self):
        ms = {m["letter"]: m for m in self.cmp["measures"]}
        self.assertEqual(sorted(ms), ["2J", "2K", "2L", "2M"])
        k = ms["2K"]
        # Checked against the city's ballot text ("maximum repayment cost up to $650,000,000") and bond guide.
        self.assertIn("maximum total repayment $650 million", k["money"]["text"])
        self.assertEqual(k["money"]["link"], "https://bouldercolorado.gov/guide/recreation-and-safety-bond")
        self.assertTrue(k["groups"]["supports"] and k["groups"]["opposes"])
        for m in ms.values():
            for g in m["groups"]["supports"] + m["groups"]["opposes"]:
                self.assertTrue(g["name"] and g["link"].startswith("https://"), g)

    def test_measure_groups_are_organizations_only(self):
        """Fix round 6 (Sonnet D1): the 2L card listed five candidates from the pro-2L campaign page. One rule for all
        four measures: group lists name organizations, never a candidate or any other individual."""
        people = {p["name"] for p in json.loads((DOCS / "api" / "chat-quotes.json").read_text())["people"]}
        self.assertGreaterEqual(len(people), 19)
        edges = json.loads((DOCS / "api" / "v1" / "endorsements.json").read_text())["endorsements"]
        persons = {e["endorser"]["name"] for e in edges if e["endorser"]["type"] == "person"}
        orgs = {e["endorser"]["name"] for e in edges if e["endorser"]["type"] == "organization"}
        for m in self.cmp["measures"]:
            names = [g["name"] for g in m["groups"]["supports"] + m["groups"]["opposes"]]
            self.assertFalse(set(names) & people, m["letter"])
            self.assertFalse(set(names) & persons, m["letter"])
            self.assertTrue(set(names) <= orgs, m["letter"])
            self.assertFalse(any(g.get("note") == "listed by a campaign" for g in m["groups"]["supports"] + m["groups"]["opposes"]))
        l2 = next(m for m in self.cmp["measures"] if m["letter"] == "2L")
        for who in ("Taishya Adams", "Aaron Brockett", "Tina Marquis", "Ryan Schuchard", "Tara Winer", "Kim Monson"):
            self.assertNotIn(who, json.dumps(l2["groups"]))
        self.assertIn("Boulder Firefighters for a Stronger Boulder", [g["name"] for g in l2["groups"]["supports"]])


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

    def test_no_shown_caveat_states_a_position(self):
        """Fix round 4 (D2): Isaacson's 2J line showed "Transcript note: Supports implicitly; no explicit
        yes/no". A caveat beside a quote says where it came from and who spoke, never a position."""
        stance = re.compile(r"\b(supports?|supported|supporting|supporter|oppos\w*|in favou?r|implicit\w*|stance|"
                            r"endors\w*|yes|yes/no|agrees?|disagrees?)\b|\b(said|says|votes?|voted|a|on) no\b|"
                            r"\bno (vote|on)\b", re.I)
        caveats = [(q["speaker"], q["caveat"]) for q in self.idx["quotes"]]
        cmp = json.loads((API / "chat-compare.json").read_text(encoding="utf-8"))
        caveats += [(r["name"], l["caveat"]) for t in cmp["topics"] for qs in t["races"].values()
                    for q in qs for r in q["rows"] for l in r["lines"]]
        self.assertGreater(len(caveats), 600)
        for who, c in caveats:
            self.assertNotRegex(c, stance, who)
            note = c.split("Transcript note: ", 1)[1] if "Transcript note: " in c else ""
            if note:  # speaker-attribution notes only: no glosses or context on one candidate's line
                self.assertRegex(note, r"(?i)drawn|moderator|respondent|speaker|name|called|order|sequence|"
                                       r"identif|transcribed|garbled|absent|^Pt \d", who)
        for q in self.idx["quotes"]:
            self.assertNotIn("stance", q, q["text"][:60])
        isaacson = [q for q in self.idx["quotes"] if q["text"].startswith("I'm really happy that we finally get to make a decision")]
        self.assertEqual([q["caveat"] for q in isaacson],
                         ["Automatic transcript. Check the recording. Speaker identified from speaking order."])

    def test_goldstein_la_grave_case(self):
        lg = [q for q in self.idx["quotes"] if "missing middle-income housing that" in q["text"]]
        self.assertTrue(lg)
        self.assertEqual({q["speaker"] for q in lg}, {"Aquiles La Grave"})

    def test_every_quote_line_names_speaker_and_topic(self):
        lines = self.ctx.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("  > ") and i and lines[i - 1].startswith("- ") and "reporting" not in lines[i - 1] and "reporter" not in lines[i - 1]:
                self.assertIn("Topic: ", lines[i - 1], lines[i - 1][:120])
