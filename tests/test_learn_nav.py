"""Learn section: every child page carries the section menu and a way back to the hub."""
import re
import unittest
from pathlib import Path

import build

DOCS = Path(__file__).resolve().parent.parent / "docs"


class TestLearnNav(unittest.TestCase):
    def child_pages(self):
        pages = [(k, DOCS / href) for k, (href, _) in build.LEARN_PAGES.items() if k not in build.LEARN_LINK_ONLY]
        pages += [("orgs", p) for p in sorted((DOCS / "orgs").glob("*.html"))]
        return pages

    def test_every_child_has_subnav(self):
        pages = self.child_pages()
        self.assertGreaterEqual(len(pages), 10)
        for key, path in pages:
            html = path.read_text(encoding="utf-8")
            with self.subTest(page=str(path.relative_to(DOCS))):
                nav = re.search(r"<nav class='learn-nav'.*?</nav>", html, re.S)
                self.assertIsNotNone(nav, "missing Learn section menu")
                self.assertRegex(nav.group(0), r"href='(\.\./)?learn\.html'")
                self.assertIn("<details class='learn-menu'>", nav.group(0))
                if path.parent == DOCS / "orgs":
                    continue
                href = build.LEARN_PAGES[key][0]
                self.assertRegex(nav.group(0), rf"href='(\.\./)?{re.escape(href)}' aria-current=\"page\"")

    def test_hub_lists_every_learn_page(self):
        hub = (DOCS / "learn.html").read_text(encoding="utf-8")
        for _, (href, label) in build.LEARN_PAGES.items():
            self.assertIn(f"href='{href}'", hub)
        for title, _ in build.LEARN_GROUPS:
            self.assertIn(title.replace("'", "&#x27;"), hub)
        self.assertIn("Past elections", hub)

    def test_header_nav_stays_at_five(self):
        self.assertEqual(len(build.PRIMARY_NAV), 5)

    def test_repo_link(self):
        self.assertTrue(build.REPO_URL.startswith("https://github.com/"))
        self.assertIn(build.REPO_URL, (DOCS / "index.html").read_text(encoding="utf-8"))
        self.assertIn(build.REPO_URL, (DOCS / "about.html").read_text(encoding="utf-8"))
        self.assertIn(f"Source code and data: {build.REPO_URL}", (DOCS / "llms.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
