import pathlib, unittest

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"
TOKEN = "7a452d8fccb54d1aa4bc55d6bb758f6d"


class AnalyticsBeaconTest(unittest.TestCase):
    def test_every_html_page_has_one_beacon(self):
        pages = [p for p in DOCS.rglob("*.html")]
        self.assertTrue(pages)
        missing = [str(p.relative_to(DOCS)) for p in pages
                   if p.read_text(encoding="utf-8").count("static.cloudflareinsights.com/beacon.min.js") != 1
                   or TOKEN not in p.read_text(encoding="utf-8")]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
