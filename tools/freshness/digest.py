#!/usr/bin/env python3
"""Print only new publications, changed finances and newly held items."""
try:
    from .common import read, state_dir
except ImportError:
    from common import read, state_dir


def digest(state):
    result = read(state / 'result.json', {})
    lines = []
    for item in result.get('published', []):
        if item.get('endorser'):
            target = item.get('candidate') or item.get('measure_letter')
            lines.append(f"Published: {item['endorser']} -> {target} ({item['position']}). {item['source_url']}")
        else:
            lines.append(f"Published forum: {item['title']} ({item['date']}). {item['source_url']}")
    for change in read(state / 'finance_changes.json', []):
        lines.append('Finance: ' + change)
    for held in result.get('held', []):
        proposal = held['proposal']
        url = proposal.get('source_url', '') if isinstance(proposal, dict) else ''
        lines.append(f"Needs review: {held['reason']}. {url}".strip())
    report = read(state / 'changes.json', {})
    previous = read(state / 'reported_errors.json', [])
    errors = [f"{e['url']}: {e['error']}" for e in report.get('errors', []) + read(state / 'discovery_errors.json', [])]
    lines.extend('Fetch needs review: ' + e for e in errors if e not in previous)
    write_errors = errors != previous
    if write_errors:
        try:
            from .common import write
        except ImportError:
            from common import write
        write(state / 'reported_errors.json', errors)
    return '\n'.join(lines)


if __name__ == '__main__':
    summary = digest(state_dir())
    if summary:
        print(summary)
