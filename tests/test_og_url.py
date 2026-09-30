import pathlib, re, unittest

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"


class OgUrlTest(unittest.TestCase):
    def test_every_page_has_its_own_og_url(self):
        pages = [f for f in DOCS.rglob("*.html") if 'property="og:type"' in f.read_text(encoding="utf-8")]
        self.assertGreater(len(pages), 20)
        for f in pages:
            html = f.read_text(encoding="utf-8")
            m = re.findall(r'<meta property="og:url" content="([^"]+)">', html)
            self.assertEqual(len(m), 1, f)
            rel = f.relative_to(DOCS).as_posix()
            want = "https://bouldervotes.org/" + ("" if rel == "index.html" else rel)
            self.assertEqual(m[0], want)
            self.assertIn(f'<link rel="canonical" href="{want}">', html)
