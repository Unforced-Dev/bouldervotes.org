"""Every built page counts itself with our own first-party snippet and loads no third-party script."""
import json
import pathlib
import re
import unittest

import build

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"
SNIPPET = re.compile(r"<script>try\{fetch\(\"([^\"]+)\",\{(.*?)\}\)\.catch\(function\(\)\{\}\)\}catch\(e\)\{\}</script>")


def pages():
    return sorted(DOCS.rglob("*.html"))


class CountSnippetTest(unittest.TestCase):
    def test_no_cloudflare_insights_anywhere_in_docs(self):
        hits = [str(p.relative_to(DOCS)) for p in DOCS.rglob("*") if p.is_file()
                and b"cloudflare" b"insights" in p.read_bytes()]
        self.assertEqual(hits, [])

    def test_no_third_party_script_src(self):
        bad = []
        for p in pages():
            for src in re.findall(r"<script[^>]*\ssrc=[\"']?([^\"' >]+)", p.read_text(encoding="utf-8")):
                if re.match(r"(https?:)?//", src) and not re.match(r"(https?:)?//bouldervotes\.org/", src):
                    bad.append(f"{p.relative_to(DOCS)}: {src}")
        self.assertEqual(bad, [])

    def test_every_page_counts_itself_once(self):
        self.assertTrue(pages())
        problems = []
        for p in pages():
            s = p.read_text(encoding="utf-8")
            found = SNIPPET.findall(s)
            if len(found) != 1:
                problems.append(f"{p.relative_to(DOCS)}: {len(found)} snippets")
                continue
            url, opts = found[0]
            rel = p.relative_to(DOCS).as_posix()
            want = "/" if rel == "index.html" else "/" + rel
            body = re.search(r"body:'([^']*)'", opts)
            if url != build.COUNT_URL or not body or json.loads(body.group(1)) != {"path": want}:
                problems.append(f"{p.relative_to(DOCS)}: {url} {body and body.group(1)}")
        self.assertEqual(problems, [])

    def test_snippet_sends_nothing_about_the_visitor(self):
        s = build.COUNT_SNIPPET
        for part in ('method:"POST"', "keepalive:true", 'credentials:"omit"', 'referrerPolicy:"no-referrer"',
                     '"Content-Type":"text/plain"'):
            self.assertIn(part, s)
        for banned in ("sendBeacon", "cookie", "localStorage", "sessionStorage", "navigator", "location", "referrer:"):
            self.assertNotIn(banned, s)
        self.assertTrue(build.COUNT_URL.startswith(build.FEEDBACK_URL))

    def test_about_page_describes_our_counts(self):
        s = (DOCS / "about.html").read_text(encoding="utf-8")
        self.assertNotIn("Cloudflare Web Analytics", s)
        self.assertIn("one count per page per day", s)


if __name__ == "__main__":
    unittest.main()
