#!/usr/bin/env python3
"""Generate a hand-editable watch list; discover endorsement links on home pages."""
import argparse
from html.parser import HTMLParser
from urllib.parse import urljoin
try:
    from .common import DATA, HERE, Fetcher, host, read, source_id, state_dir, write
except ImportError:
    from common import DATA, HERE, Fetcher, host, read, source_id, state_dir, write


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = [dict(attrs).get('href', ''), '']

    def handle_data(self, data):
        if self.current:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            self.links.append(self.current)
            self.current = None


def generate(discover=True):
    candidates = read(DATA / 'candidates.json')
    orgs = read(DATA / 'organizations.json')
    rows = {}
    fetcher = Fetcher()
    errors = []

    def add(url, kind, **context):
        if url and url.startswith(('http://', 'https://')):
            rows.setdefault(url, {'id': source_id(url), 'url': url, 'kind': kind, **context})

    def kind_for(url):
        if host(url) in {host(c.get('campaign_url')) for c in candidates}:
            return 'campaign'
        if host(url) in {'bouldercolorado.gov', 'webapps.bouldercolorado.gov'}:
            return 'city'
        if host(url) in {host(o.get('website')) for o in orgs if o.get('website')}:
            return 'endorser'
        return 'news'

    for edge in read(DATA / 'endorsements.json'):
        add(edge['source_url'], kind_for(edge['source_url']), endorser_slug=edge['endorser_slug'])
    for c in candidates:
        add(c.get('campaign_url'), 'campaign', candidate=c['name'])
    for m in read(DATA / 'measures.json')['city_measures']:
        for item in m.get('committees', []) + m.get('supporters', []) + m.get('opponents', []):
            add(item.get('source_url'), kind_for(item.get('source_url')), measure_letter=m['id'])
    for o in orgs:
        if o['kind'] == 'committee':
            add(o.get('website'), 'committee', endorser_slug=o['slug'])
    for url in ['https://boulderreportinglab.org/', 'https://yellowscene.com/']:
        add(url, 'news')
    # Forum organizer pages also need watching for new events and changed facts.
    for forum in read(DATA / 'forums_upcoming.json'):
        add(forum['source_url'], kind_for(forum['source_url']))
    if discover:
        homes = [(c.get('campaign_url'), 'campaign', {'candidate': c['name']}) for c in candidates]
        homes += [(o.get('website'), 'endorser', {'endorser_slug': o['slug']}) for o in orgs if o['kind'] != 'person']
        for url, kind, context in homes:
            if not url:
                continue
            try:
                parser = Links()
                html = fetcher.fetch(url)
                parser.feed(html)
                for href, label in parser.links:
                    target = urljoin(url, href)
                    if host(target) != host(url) or 'endorse' not in (href + ' ' + label).lower():
                        continue
                    if kind == 'endorser' and '2026' not in href + label:
                        if '2026' not in fetcher.fetch(target):
                            continue
                    add(url, kind, **context)
                    add(target, kind, **context)
            except Exception as exc:
                errors.append({'url': url, 'error': str(exc)})
    # Preserve manual edits/additions in the generated file on subsequent runs.
    for row in read(HERE / 'sources.json', []) + read(HERE / 'extra_sources.json', []):
        if row.get('url'):
            rows[row['url']] = {**row, 'id': source_id(row['url'])}
    write(HERE / 'sources.json', sorted(rows.values(), key=lambda s: s['url']))
    write(state_dir() / 'discovery_errors.json', errors)
    print(f'Sources: {len(rows)}; discovery errors: {len(errors)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-discover', action='store_true', help='Generate known sources without network discovery')
    generate(not parser.parse_args().no_discover)
