#!/usr/bin/env python3
"""Append supported proposals; hold ambiguity and disappearances, never edit edges."""
import hashlib
import re
from datetime import date, datetime, timezone
try:
    from .common import DATA, HERE, Fetcher, host, norm, read, slug, state_dir, write
    from .watch import html_to_text
except ImportError:
    from common import DATA, HERE, Fetcher, host, norm, read, slug, state_dir, write
    from watch import html_to_text


def contains(text, name):
    return bool(re.search(r'(?<!\w)' + re.escape(norm(name)) + r'(?!\w)', norm(text), re.I))


def provenance(proposal, candidates, orgs):
    h = host(proposal['source_url'])
    candidate = next((c for c in candidates if c['name'] == proposal.get('candidate')), None)
    if candidate and h == host(candidate.get('campaign_url')):
        return 'campaign_claim'
    profile = next((o for o in orgs if o['name'] == proposal['endorser']), None)
    if profile and profile.get('website') and h == host(profile['website']):
        return 'endorser_statement'
    if h in {'bouldercolorado.gov', 'webapps.bouldercolorado.gov'}:
        return 'filing'
    if h in {host(c.get('campaign_url')) for c in candidates}:
        raise ValueError('Source belongs to a different candidate campaign')
    if h in {host(o.get('website')) for o in orgs if o['kind'] == 'committee' and o.get('website')}:
        return 'campaign_claim'
    news = {'boulderreportinglab.org', 'yellowscene.com', 'dailycamera.com', 'boulderbeat.news', 'kgnu.org'}
    news.update(host(o.get('website')) for o in orgs if o['kind'] == 'newspaper' and o.get('website'))
    if h in news:
        return 'news_report'
    raise ValueError('Unclassified source host; human must establish ownership')


def validate_endorsement(p, text, candidates, orgs, edges):
    name, letter = p.get('candidate'), p.get('measure_letter')
    if bool(name) == bool(letter):
        raise ValueError('Exactly one candidate or measure is required')
    if name and name not in {c['name'] for c in candidates}:
        raise ValueError('Unknown candidate')
    if letter and letter not in {'2J', '2K', '2L', '2M'}:
        raise ValueError('Unknown city measure')
    endorser = p.get('endorser')
    if not isinstance(endorser, str) or not endorser.strip():
        raise ValueError('Endorser name required')
    if p.get('endorser_type') not in {'person', 'organization'}:
        raise ValueError('Unknown endorser type')
    profile = next((o for o in orgs if o['name'] == endorser), None)
    key = profile['slug'] if profile else slug(endorser)
    if any(e['endorser_slug'] == key and e.get('candidate') == name and e.get('measure_letter') == letter for e in edges):
        raise ValueError('Duplicate endorser + target edge')
    if any(o['slug'] == key and o['name'] != endorser for o in orgs):
        raise ValueError('Endorser slug collision')
    quote = p.get('evidence_quote')
    if not isinstance(quote, str) or not norm(quote) or norm(quote) not in norm(text):
        raise ValueError('Quote absent from current live snapshot')
    if not contains(quote, name.split()[-1] if name else letter):
        raise ValueError('Quote does not identify the target')
    prov = provenance(p, candidates, orgs)
    if prov != 'campaign_claim' and not contains(quote, endorser):
        raise ValueError('Quote does not identify the endorser')
    position = p.get('position')
    if position not in {'endorse', 'oppose'}:
        raise ValueError('Invalid position')
    # Mentions alone are not evidence of support/opposition.
    words = r'\b(endorse\w*|support\w*|back\w*|vote for|vote yes)\b' if position == 'endorse' else r'\b(oppos\w*|against|vote no)\b'
    if not re.search(words, quote, re.I):
        raise ValueError('Quote lacks explicit position language')
    rank = p.get('rank')
    if rank is not None:
        if type(rank) is not int or rank < 1 or rank > 19 or letter:
            raise ValueError('Invalid ranked-choice rank')
        rank_words = {1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth', 6: 'sixth'}
        if not (contains(quote, str(rank)) or contains(quote, rank_words.get(rank, str(rank)))):
            raise ValueError('Rank absent from quote')
    return key, prov


def validate_forum(p, text, forums, sources, orgs):
    quote = p.get('evidence_quote')
    if not isinstance(quote, str) or not norm(quote) or norm(quote) not in norm(text):
        raise ValueError('Forum quote absent from live snapshot')
    if not isinstance(p.get('id'), str) or not re.fullmatch(r'[a-z0-9-]+', p['id']):
        raise ValueError('Invalid forum id')
    if any(e['id'] == p['id'] or (e['date'] == p.get('date') and (e['title'] == p.get('title') or e['source_url'] == p['source_url'])) for e in forums):
        raise ValueError('Duplicate forum')
    day = date.fromisoformat(p['date'])
    if day.year != 2026 or day > date(2026, 11, 3):
        raise ValueError('Forum outside 2026')
    races = p.get('races')
    if not isinstance(races, list) or not races or not set(races) <= {'mayor', 'council', 'ballot measures'}:
        raise ValueError('Forum outside city races/measures')
    if not contains(quote, 'Boulder') or not re.search(r'mayor|council|2[J-M]', quote, re.I):
        raise ValueError('Forum quote lacks city election scope')
    for race in races:
        if race != 'ballot measures' and not re.search(race, quote, re.I):
            raise ValueError('Forum race absent from quote')
    if not p.get('hosts') or not isinstance(p['hosts'], list):
        raise ValueError('Forum host required')
    organizer_hosts = {host(o.get('website')) for o in orgs if o['name'] in p['hosts'] and o.get('website')}
    # Zoom is accepted only for an organizer's already watched registration URL.
    known = any(s['url'] == p['source_url'] for s in sources)
    if host(p['source_url']) not in organizer_hosts and not (known and host(p['source_url']) == 'us02web.zoom.us'):
        raise ValueError('Organizer source ownership unverified')
    # Deliberately conservative: hold natural-language dates/times for review.
    for field in ['title', 'date', 'start_time', 'end_time', 'venue_name', 'venue_address', 'cost', 'accessibility', 'recording_plan']:
        value = p.get(field)
        if value is not None and (not isinstance(value, str) or norm(value) not in norm(quote)):
            raise ValueError(f'Forum {field} absent from quote')
    if not p.get('title') or type(p.get('in_person')) is not bool:
        raise ValueError('Forum title and attendance format required')
    for value in p['hosts']:
        if not isinstance(value, str) or not contains(quote, value):
            raise ValueError('Forum host absent from quote')
    for field in ['start_time', 'end_time']:
        if p.get(field):
            datetime.strptime(p[field], '%H:%M')
    for field in ['livestream_url', 'registration_url']:
        if p.get(field) and (not p[field].startswith(('https://', 'http://')) or p[field] not in text):
            raise ValueError(f'Forum {field} absent from snapshot')
    if p.get('candidates_invited_or_confirmed') is not None:
        raise ValueError('Candidate attendance requires human review')


def apply(state, data=DATA, fetcher=None, review_only=False):
    candidates, orgs, edges, forums, ledger = [read(data / (n + '.json')) for n in
        ['candidates', 'organizations', 'endorsements', 'forums_upcoming', 'endorsement_verification']]
    proposals = read(state / 'proposals.json', [])
    if not isinstance(proposals, list):
        raise ValueError('proposals.json must be a list')
    report = read(state / 'changes.json', {})
    checked = datetime.fromisoformat(report['checked_on'])
    if (datetime.now(timezone.utc) - checked).total_seconds() > 3600:
        raise ValueError('Watch report expired; run watch again')
    fetched = {s['url']: s for s in report.get('fetched', [])}
    changed = {s['url'] for s in report.get('changes', [])}
    sources = read(state / 'sources.json', [])
    old_held = read(state / 'held.json', [])
    held = list(old_held)
    published, fresh_held = [], []
    today = date.today().isoformat()
    live = {}
    fetcher = fetcher or Fetcher()

    def hold(p, reason):
        item = {'proposal': p, 'reason': reason}
        identity = json_key(item)
        if identity not in {json_key(h) for h in held}:
            held.append(item)
            fresh_held.append(item)

    def snapshot(url):
        if url in live:
            return live[url]
        if url not in fetched:
            raise ValueError('Source was not fetched successfully this run')
        s = fetched[url]
        text = (state / 'snapshots' / (s['id'] + '.txt')).read_text(encoding='utf-8')
        if hashlib.sha256(text.encode()).hexdigest() != s['sha256']:
            raise ValueError('Snapshot changed since watch')
        # Independently refetch so a worker cannot edit the evidence it is judged on.
        current = html_to_text(fetcher.fetch(url))
        # Dynamic widgets may change unrelated text between reads. Judge the
        # proposal against the independently fetched CURRENT page instead.
        live[url] = current
        return current

    for p in proposals:
        try:
            if not isinstance(p, dict):
                raise ValueError('Proposal must be an object')
            if p.get('type') == 'flag':
                hold(p, p.get('reason') or 'Worker requested human review')
                continue
            if p.get('source_url') not in changed:
                raise ValueError('Proposal source is not a changed source')
            text = snapshot(p['source_url'])
            if p.get('type') == 'endorsement':
                key, prov = validate_endorsement(p, text, candidates, orgs, edges)
                if review_only:
                    hold(p, 'Evidence found on live page; Uni must review meaning and attribution before publishing')
                    continue
                published_on = today
                if p.get('published_on'):
                    stated = date.fromisoformat(p['published_on'])
                    spellings = {stated.isoformat()}
                    for month in (stated.strftime('%B'), stated.strftime('%b'), stated.strftime('%b') + '.'):
                        spellings.update({f'{month} {stated.day}, {stated.year}', f'{month} {stated.day} {stated.year}'})
                    if not any(contains(text, spelling) for spelling in spellings):
                        raise ValueError('Publication date absent from source')
                    published_on = p['published_on']
                profile = next((o for o in orgs if o['slug'] == key), None)
                if profile is None:
                    kind = 'person' if p['endorser_type'] == 'person' else 'organization'
                    profile = {'slug': key, 'name': p['endorser'], 'kind': kind, 'website': None,
                               'title': None, 'summary': None, 'weight_group': 'other_individual' if kind == 'person' else 'organization',
                               'sources': [p['source_url']]}
                    orgs.append(profile)
                number = max([int(e['id'][1:]) for e in edges if re.fullmatch(r'E\d+', e['id'])] + [-1]) + 1
                eid = f'E{number}'
                verification = {'result': 'AUTO', 'checked_on': today, 'evidence_url': p['source_url'], 'note': p['evidence_quote']}
                edge = {k: p.get(k) for k in ['endorser', 'candidate', 'measure_letter', 'position', 'rank', 'source_url', 'notes']}
                edge.update(id=eid, endorser_slug=key, endorser_type='person' if profile['kind'] == 'person' else 'organization',
                            measure_label=None, provenance=prov, claimed_by=(p.get('candidate') or host(p['source_url'])) if prov == 'campaign_claim' else None,
                            source_title=f"{p['endorser']} endorsement", published_on=published_on, status='published',
                            audit={'result': 'pass', 'note': f'Auto-verified {today}: quote found on the live source page.'}, verification=verification)
                edges.append(edge)
                ledger.append({'id': eid, **verification})
                published.append(edge)
            elif p.get('type') == 'forum':
                validate_forum(p, text, forums, sources, orgs)
                if review_only:
                    hold(p, 'Evidence found on live page; Uni must review event details before publishing')
                    continue
                allowed = set(read(data / 'forums_upcoming.json')[0]) | {'topic', 'measure_only', 'format'}
                forum = {k: v for k, v in p.items() if k in allowed}
                forum.update(source_quote=p['evidence_quote'], retrieved_on=today, confidence='confirmed',
                             audit={'result': 'pass', 'note': f'Auto-verified {today}: quote found on the live source page.'},
                             verification={'result': 'AUTO', 'checked_on': today, 'evidence_url': p['source_url'], 'note': p['evidence_quote']})
                forums.append(forum)
                published.append(forum)
            else:
                raise ValueError('Unknown proposal type')
        except (ValueError, KeyError, TypeError, OSError) as exc:
            hold(p, str(exc))
    # A failed fetch is not evidence of disappearance. Never remove an old edge.
    for edge in edges:
        if edge.get('status') != 'published' or edge['source_url'] not in fetched:
            continue
        try:
            text = snapshot(edge['source_url'])
            removed = '\n'.join(line for change in report.get('changes', [])
                                if change['url'] == edge['source_url']
                                for line in change.get('removed', []))
            # Absence from a first snapshot is not disappearance (JS/image-only
            # lists and aliases are common). Require the name in removed text.
            if contains(removed, edge['endorser']) and not contains(text, edge['endorser']):
                hold({'type': 'flag', 'source_url': edge['source_url'], 'edge_id': edge['id']},
                     f"Published endorsement no longer names {edge['endorser']}; review {edge['id']}")
        except Exception as exc:
            hold({'type': 'flag', 'source_url': edge['source_url']}, str(exc))
    if published:
        for name, rows in [('endorsements', edges), ('organizations', orgs), ('forums_upcoming', forums), ('endorsement_verification', ledger)]:
            if read(data / (name + '.json')) != rows:
                write(data / (name + '.json'), rows)
    write(state / 'held.json', held)
    write(state / 'result.json', {'published': published, 'held': fresh_held})
    return published, fresh_held


def json_key(item):
    import json
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


if __name__ == '__main__':
    apply(state_dir(), review_only=True)
