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

HARD_LIMIT = 300_000
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
        self.assertGreater(self.ctx.count("  Watch: https://www.youtube.com/watch?v="), 100)
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
        self.assertLessEqual(len(self.system), 2000)
        self.assertIn("bouldervotes.org", self.system)

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


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestAskJsEscaping(unittest.TestCase):
    def render(self, text: str) -> str:
        code = ("const a=require(process.argv[1]);"
                "process.stdout.write(a.renderMarkdown(require('fs').readFileSync(0,'utf8')));")
        r = subprocess.run(["node", "-e", code, str(ASK_JS)], input=text, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_html_is_escaped(self):
        out = self.render('<script>alert(1)</script> <img src=x onerror=alert(1)> "quoted" & more')
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("&amp; more", out)

    def test_only_https_links(self):
        out = self.render("[bad](javascript:alert(1)) [http](http://example.com/x) [ok](https://example.org/a?b=1&c=2)")
        self.assertNotIn('href="javascript', out)
        self.assertNotIn('href="http://', out)
        self.assertIn('href="https://example.org/a?b=1&amp;c=2"', out)
        self.assertIn('rel="noopener noreferrer"', out)

    def test_attribute_injection_blocked(self):
        out = self.render('[x](https://example.org/"onmouseover="alert(1))')
        tags = re.findall(r"<a [^>]*>", out)
        self.assertTrue(tags)
        for tag in tags:  # outside the quoted href value there may be no extra attribute
            self.assertNotRegex(re.sub(r'href="[^"]*"', "", tag), r"onmouseover")
        out = self.render('https://example.org/a"><script>alert(1)</script>')
        self.assertNotIn("<script", out)

    def test_site_links_become_relative(self):
        out = self.render("See [Prop](https://bouldervotes.org/measures/2026-2j.html) and https://bouldervotes.org/people/judy-amabile.html")
        self.assertIn('href="measures/2026-2j.html"', out)
        self.assertIn('href="people/judy-amabile.html"', out)
        self.assertNotIn('href="https://bouldervotes.org', out)

    def test_lists_bold_and_quotes(self):
        out = self.render("**Housing**\n\n- one\n- two\n\n> \"A quote\"")
        self.assertIn("<strong>Housing</strong>", out)
        self.assertIn("<ul><li>one</li><li>two</li></ul>", out)
        self.assertIn("<blockquote>", out)


if __name__ == "__main__":
    unittest.main()
