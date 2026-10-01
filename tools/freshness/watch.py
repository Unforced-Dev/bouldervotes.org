#!/usr/bin/env python3
"""Fetch source text and persist a baseline/diff outside the repository."""
import difflib
import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

try:
    from .common import HERE, Fetcher, read, state_dir, write
except ImportError:
    from common import HERE, Fetcher, read, state_dir, write


class TextParser(HTMLParser):
    blocks = set('address article aside blockquote br dd div dl dt fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hr li main ol p pre section table td th tr ul'.split())
    dropped = {'script', 'style', 'nav', 'noscript', 'template'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if self.hidden:
            if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
                self.hidden.append(tag)
        elif tag in self.dropped:
            self.hidden.append(tag)
        elif tag in self.blocks:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.hidden:
            if tag in self.hidden:
                index = len(self.hidden) - 1 - self.hidden[::-1].index(tag)
                del self.hidden[index:]
        elif tag in self.blocks:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(re.sub(r'\s+', ' ', data))


def html_to_text(html):
    parser = TextParser()
    parser.feed(html)
    return '\n'.join(' '.join(line.split()) for line in ''.join(parser.parts).splitlines() if line.strip()) + '\n'


def watch(sources, state, fetcher=None):
    fetcher = fetcher or Fetcher()
    snapshots = state / 'snapshots'
    snapshots.mkdir(parents=True, exist_ok=True)
    previous = read(state / 'changes.json', {})
    processed = read(state / 'processed.json', {})
    pending = previous.get('changes', []) if previous.get('checked_on') != processed.get('checked_on') else []
    report = {'checked_on': datetime.now(timezone.utc).isoformat(), 'changes': [], 'errors': [], 'fetched': []}
    for source in sources:
        try:
            text = html_to_text(fetcher.fetch(source['url']))
            if not text.strip():
                raise ValueError('Empty source text')
            path = snapshots / (source['id'] + '.txt')
            old = path.read_text(encoding='utf-8') if path.exists() else None
            if old is not None and old != text:
                diff = list(difflib.ndiff(old.splitlines(), text.splitlines()))
                report['changes'].append({**source, 'added': [s[2:] for s in diff if s.startswith('+ ')],
                                          'removed': [s[2:] for s in diff if s.startswith('- ')]})
            tmp = path.with_suffix('.tmp')
            tmp.write_text(text, encoding='utf-8')
            tmp.replace(path)
            report['fetched'].append({**source, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
        except Exception as exc:
            report['errors'].append({**source, 'error': str(exc)})
    current_urls = {s['url'] for s in report['changes']}
    report['changes'].extend(s for s in pending if s['url'] not in current_urls)
    write(state / 'changes.json', report)
    write(state / 'sources.json', sources)
    return report


if __name__ == '__main__':
    report = watch(read(HERE / 'sources.json', []), state_dir())
    print(f"Sources: {len(report['fetched']) + len(report['errors'])}; snapshots: {len(report['fetched'])}; fetch errors: {len(report['errors'])}; changes: {len(report['changes'])}")
