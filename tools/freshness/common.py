"""Shared, stdlib-only freshness paths, JSON and HTTP helpers."""
import hashlib
import json
import os
import re
import ssl
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/harvest/2026'
HERE = Path(__file__).resolve().parent


def state_dir():
    return Path(os.environ.get('BV_STATE_DIR', '~/.hermes/state/bouldervotes')).expanduser().resolve()


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def norm(text):
    return ' '.join(text.split())


def host(url):
    return (urlparse(url or '').hostname or '').lower().removeprefix('www.')


def source_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def slug(name):
    # Keep seed.slug's existing identity convention.
    return name.lower().replace('.', '').replace("'", '').replace('—', '-').replace(' ', '-')



class Fetcher:
    """One request per second, including retries; TLS verification stays enabled."""
    def __init__(self):
        self.last = 0
        self.context = ssl.create_default_context()
        intermediate = ROOT / 'data/certs/digicert-global-g2-tls-rsa-sha256-2020-ca1.pem'
        if intermediate.exists():
            self.context.load_verify_locations(cafile=str(intermediate))

    def fetch(self, url):
        if urlparse(url).scheme not in ('http', 'https'):
            raise ValueError('Only HTTP(S) sources are allowed')
        for attempt in range(2):
            time.sleep(max(0, 1 - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'bouldervotes.org freshness check'})
                with urllib.request.urlopen(req, timeout=20, context=self.context) as response:
                    kind = response.headers.get_content_type()
                    if kind not in ('text/html', 'application/xhtml+xml', 'text/plain'):
                        raise ValueError('Unsupported source content type: ' + kind)
                    return response.read().decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
            except Exception:
                if attempt:
                    raise
