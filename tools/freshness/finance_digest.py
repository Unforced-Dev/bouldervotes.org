"""Reduce refresh output to actual changes; stop automatic removal of filings."""
import json
import subprocess
import sys
from pathlib import Path
try:
    from .common import ROOT, read, state_dir, write
except ImportError:
    from common import ROOT, read, state_dir, write


def main():
    relative = 'data/harvest/finance_2026.json'
    before = json.loads(subprocess.check_output(['git', 'show', f'HEAD:{relative}'], cwd=ROOT))
    after = read(ROOT / relative)
    old = {c['committee_id']: c for c in before['committees']}
    new = {c['committee_id']: c for c in after['committees']}
    messages = []
    for cid in old.keys() | new.keys():
        a, b = old.get(cid), new.get(cid)
        label = (b or a).get('person') or (b or a)['committee_name']
        if not a or not b:
            messages.append(f"{'New' if b else 'Missing'} committee: {label}")
        else:
            for field in ['contributions_total', 'matching_received', 'expenditures_total', 'cash_on_hand']:
                if a.get(field) != b.get(field):
                    messages.append(f"{label}, {field}: {a.get(field)} -> {b.get(field)}")
            if a.get('statements') != b.get('statements'):
                messages.append(f'{label}: filing reports changed')
    log = Path(sys.argv[1]).read_text()
    # Repeated 'no new report' lines are routine, not news for the digest.
    prior_flags = read(state_dir() / 'reported_finance_flags.json', [])
    current_flags = []
    for line in log.splitlines():
        if line.startswith('  -') and 'no new report:' not in line:
            message = line.strip().removeprefix('- ')
            current_flags.append(message)
            if message not in messages and message not in prior_flags:
                messages.append(message)
    write(state_dir() / 'finance_changes.json', messages)
    write(state_dir() / 'reported_finance_flags.json', current_flags)
    if old.keys() - new.keys() or any('DOWN ' in m for m in current_flags):
        raise SystemExit('Finance removal/decrease requires human review; automatic publication stopped')
    # Do not commit a date-only refresh on days with no new filing facts.
    if not messages:
        (ROOT / relative).write_text(subprocess.check_output(['git', 'show', f'HEAD:{relative}'], cwd=ROOT).decode())


if __name__ == '__main__':
    main()
