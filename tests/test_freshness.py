import tempfile
import unittest
from pathlib import Path

from tools.freshness.common import source_id, write, read, slug
from tools.freshness.watch import html_to_text, watch
from tools.freshness.verify_apply import apply, validate_endorsement, provenance, validate_forum
from tools.freshness.digest import digest


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url):
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [{'name': 'Jane Smith', 'campaign_url': 'https://smith.example/'}]
        self.orgs = [{'name': 'Good Group', 'slug': 'good-group', 'kind': 'organization', 'website': 'https://group.example/'}]
        self.url = 'https://group.example/2026'
        self.quote = 'Good Group endorses Jane Smith for Boulder mayor in 2026.'
        self.p = {'type': 'endorsement', 'endorser': 'Good Group', 'endorser_type': 'organization',
                  'candidate': 'Jane Smith', 'measure_letter': None, 'position': 'endorse', 'rank': None,
                  'source_url': self.url, 'evidence_quote': self.quote, 'notes': ''}

    def validate(self, p=None, text=None, edges=None):
        return validate_endorsement(p or self.p, text or self.quote, self.candidates, self.orgs, edges or [])

    def test_accepts_verbatim_quote(self):
        self.assertEqual(self.validate(), ('good-group', 'endorser_statement'))
        self.assertEqual(self.validate(text=self.quote.replace(' ', '\n')), ('good-group', 'endorser_statement'))

    def test_rejects_paraphrase(self):
        with self.assertRaisesRegex(ValueError, 'Quote absent'):
            self.validate({**self.p, 'evidence_quote': 'Good Group supports Jane Smith.'})

    def test_rejects_duplicate_even_if_opposite_position(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.validate(edges=[{'endorser_slug': 'good-group', 'candidate': 'Jane Smith', 'measure_letter': None, 'position': 'oppose'}])

    def test_rejects_unknown_candidate(self):
        with self.assertRaisesRegex(ValueError, 'Unknown candidate'):
            self.validate({**self.p, 'candidate': 'Nobody Else'})

    def test_provenance_by_host(self):
        cases = [('https://www.smith.example/end', 'campaign_claim'), (self.url, 'endorser_statement'),
                 ('https://bouldercolorado.gov/filing', 'filing'), ('https://boulderreportinglab.org/story', 'news_report')]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(provenance({**self.p, 'source_url': url}, self.candidates, self.orgs), expected)
        with self.assertRaises(ValueError):
            provenance({**self.p, 'source_url': 'https://group.example.evil.test/'}, self.candidates, self.orgs)

    def test_rejects_missing_target_or_endorser(self):
        for quote in ['Good Group endorses someone.', 'We endorse Jane Smith.']:
            with self.subTest(quote=quote), self.assertRaises(ValueError):
                self.validate({**self.p, 'evidence_quote': quote}, text=quote)

    def test_rejects_mentions_without_position(self):
        quote = 'Good Group interviewed Jane Smith.'
        with self.assertRaisesRegex(ValueError, 'position language'):
            self.validate({**self.p, 'evidence_quote': quote}, text=quote)

    def test_measure_and_rank(self):
        quote = 'Good Group opposes Boulder measure 2K.'
        self.validate({**self.p, 'candidate': None, 'measure_letter': '2K', 'position': 'oppose', 'evidence_quote': quote}, text=quote)
        with self.assertRaisesRegex(ValueError, 'Rank absent'):
            self.validate({**self.p, 'rank': 2})
        with self.assertRaisesRegex(ValueError, 'Unknown city measure'):
            self.validate({**self.p, 'candidate': None, 'measure_letter': '1A'})

    def test_html_to_text(self):
        html = '<nav>menu <div>links</div></nav><h1>A &amp; B</h1><p>Jane <b>Smith</b>\n wins.</p><script>bad()</script><style>.bad{}</style><div>Next<br>line</div>'
        self.assertEqual(html_to_text(html), 'A & B\nJane Smith wins.\nNext\nline\n')

    def test_slug_matches_existing_convention(self):
        self.assertEqual(slug("K.C. O'Brien"), 'kc-obrien')

    def test_watch_baseline_changes_and_errors(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            state = Path(tmp)
            sources = [{'id': source_id(self.url), 'url': self.url, 'kind': 'endorser'}]
            first = watch(sources, state, FakeFetcher({self.url: '<p>Old</p>'}))
            self.assertEqual(first['changes'], [])
            second = watch(sources, state, FakeFetcher({self.url: '<p>New</p>'}))
            self.assertEqual(second['changes'][0]['added'], ['New'])
            self.assertEqual(second['changes'][0]['removed'], ['Old'])
            write(state / 'processed.json', {'checked_on': second['checked_on']})
            failure = watch(sources, state, FakeFetcher({self.url: OSError('offline')}))
            self.assertEqual(failure['changes'], [])
            self.assertEqual(len(failure['errors']), 1)
            self.assertEqual((state / 'snapshots' / (sources[0]['id'] + '.txt')).read_text(), 'New\n')

    def test_pending_changes_survive_worker_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            state = Path(tmp)
            sources = [{'id': source_id(self.url), 'url': self.url, 'kind': 'endorser'}]
            watch(sources, state, FakeFetcher({self.url: '<p>Old</p>'}))
            second = watch(sources, state, FakeFetcher({self.url: '<p>New</p>'}))
            third = watch(sources, state, FakeFetcher({self.url: '<p>New</p>'}))
            self.assertEqual(third['changes'], second['changes'])
            write(state / 'processed.json', {'checked_on': third['checked_on']})
            self.assertEqual(watch(sources, state, FakeFetcher({self.url: '<p>New</p>'}))['changes'], [])

    def setup_apply(self, state):
        data = state / 'harvest'
        for name, rows in [('candidates', self.candidates), ('organizations', self.orgs), ('endorsements', []),
                           ('forums_upcoming', [{'id': 'existing', 'title': 'Old', 'date': '2026-10-01', 'source_url': 'https://old.example'}]),
                           ('endorsement_verification', [])]:
            write(data / (name + '.json'), rows)
        source = {'id': source_id(self.url), 'url': self.url, 'kind': 'endorser'}
        watch([source], state, FakeFetcher({self.url: '<p>Old</p>'}))
        watch([source], state, FakeFetcher({self.url: '<p>' + self.quote + '</p>'}))
        write(state / 'proposals.json', [self.p])
        return data, FakeFetcher({self.url: '<p>' + self.quote + '</p>'})

    def test_apply_appends_ledger_and_holds_duplicates_once(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            state = Path(tmp)
            data, fetcher = self.setup_apply(state)
            published, held = apply(state, data, fetcher)
            self.assertEqual(len(published), 1)
            self.assertEqual(held, [])
            self.assertEqual(published[0]['verification']['result'], 'AUTO')
            self.assertEqual(read(data / 'endorsement_verification.json')[0]['id'], 'E0')
            original = read(data / 'endorsements.json')
            published, held = apply(state, data, fetcher)
            self.assertEqual(len(held), 1)
            self.assertEqual(read(data / 'endorsements.json'), original)
            self.assertEqual(apply(state, data, fetcher), ([], []))

    def test_uses_explicit_page_publication_date(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            state = Path(tmp)
            data, _ = self.setup_apply(state)
            html = '<p>September 28, 2026</p><p>' + self.quote + '</p>'
            watch(read(state / 'sources.json'), state, FakeFetcher({self.url: html}))
            write(state / 'proposals.json', [{**self.p, 'published_on': '2026-09-28'}])
            published, held = apply(state, data, FakeFetcher({self.url: html}))
            self.assertEqual(held, [])
            self.assertEqual(published[0]['published_on'], '2026-09-28')

    def test_live_change_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            state = Path(tmp)
            data, _ = self.setup_apply(state)
            published, held = apply(state, data, FakeFetcher({self.url: '<p>Changed again</p>'}))
            self.assertEqual(published, [])
            self.assertIn('Live page changed', held[0]['reason'])
            self.assertEqual(read(data / 'endorsements.json'), [])

    def test_disappearance_flag_preserves_record(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            state = Path(tmp)
            data, _ = self.setup_apply(state)
            edge = {**self.p, 'id': 'E3', 'endorser_slug': 'good-group', 'status': 'published'}
            write(data / 'endorsements.json', [edge])
            write(state / 'proposals.json', [])
            watch(read(state / 'sources.json'), state, FakeFetcher({self.url: '<p>Unrelated text</p>'}))
            published, held = apply(state, data, FakeFetcher({self.url: '<p>Unrelated text</p>'}))
            self.assertEqual(published, [])
            self.assertEqual(len(held), 1)
            self.assertEqual(read(data / 'endorsements.json'), [edge])
            self.assertEqual(apply(state, data, FakeFetcher({self.url: '<p>Unrelated text</p>'})), ([], []))

    def test_digest_empty_and_new_items(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            state = Path(tmp)
            self.assertEqual(digest(state), '')
            write(state / 'result.json', {'published': [self.p], 'held': []})
            self.assertIn('Good Group -> Jane Smith', digest(state))

    def test_forum_gate_requires_organizer_and_printed_details(self):
        p = {'id': '2026-test', 'source_url': self.url, 'title': 'Boulder Council Forum', 'hosts': ['Good Group'],
             'date': '2026-10-06', 'races': ['council'], 'in_person': True, 'start_time': '18:00'}
        text = 'Good Group Boulder Council Forum 2026-10-06 18:00'
        p['evidence_quote'] = text
        validate_forum(p, text, [], [], self.orgs)
        with self.assertRaisesRegex(ValueError, 'start_time absent'):
            validate_forum({**p, 'start_time': '19:00'}, text, [], [], self.orgs)
        with self.assertRaisesRegex(ValueError, 'ownership'):
            validate_forum({**p, 'source_url': 'https://elsewhere.example'}, text, [], [], self.orgs)
