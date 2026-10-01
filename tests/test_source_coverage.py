"""Regression: coverage includes authoritative lists and audits newly found pages."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.freshness.watch import watch
from tools.freshness import sources
from tools.freshness.common import read, write, source_id


class CoverageTests(unittest.TestCase):
    def test_new_source_is_audited_not_silently_baselined(self):
        class Fetch:
            def fetch(self, url):
                return '<p>WFP endorses Jane Smith</p>'
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            rows = [{'id': source_id('https://example.org/list'), 'url': 'https://example.org/list'}]
            report = watch(rows, state, Fetch(), audit_initial=True)
            self.assertTrue(report['changes'][0]['initial_audit'])
            self.assertIn('WFP endorses Jane Smith', report['changes'][0]['added'])
            write(state / 'processed.json', {'checked_on': report['checked_on']})
            self.assertEqual(watch(rows, state, Fetch(), audit_initial=True)['changes'], [])

    def test_org_authoritative_sources_survive_no_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data, here, state = [base / name for name in ('data', 'here', 'state')]
            for path in (data, here, state):
                path.mkdir()
            for name in ('candidates', 'endorsements', 'forums_upcoming'):
                write(data / (name + '.json'), [])
            write(data / 'measures.json', {'city_measures': []})
            write(data / 'organizations.json', [{'slug': 'wfp', 'kind': 'organization',
                'website': 'https://example.org/state/', 'sources': ['https://example.org/candidates/']}])
            with patch.object(sources, 'DATA', data), patch.object(sources, 'HERE', here), patch.object(sources, 'state_dir', return_value=state):
                sources.generate(discover=False)
            urls = {row['url'] for row in read(here / 'sources.json')}
            self.assertIn('https://example.org/candidates/', urls)
            self.assertIn('https://example.org/state/', urls)
