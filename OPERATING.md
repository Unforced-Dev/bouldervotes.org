# Operating Boulder Votes

How to run, extend, and publish the site. The public pages are generated; the database is the record.

## What this is

A sourced map of **City of Boulder** mayor and council races (plus city ballot measures). Older voters first: large type, one column, no JavaScript required.

Three zooms:

- **Home** = the 2026 voter guide: key dates, candidates with endorser summaries, city measures.
- **Year** = that year’s ballot (`2026.html`, `2025.html`, …), with the questions asked that cycle.
- **Person** = dossier across years (`people/<slug>.html`), questions newest-first. A yes/no is an answer to that question, not a topic score.
- **Question × year** = people on *that* ballot who answered *that year’s* prompt (`issues/<slug>-<year>.html`). Do not copy an earlier year’s answer onto this year’s page.

A number or a “position” without a source is not published. Two quotes are never averaged. A dash means we do not have it.

Live: https://bouldervotes.org/ — GitHub Pages from `/docs` on `main`, custom domain `bouldervotes.org`.

## Rebuild

Python 3 stdlib only (plus the sqlite3 module). From the repo root:

```bash
python3 harvest_brl.py       # optional; hits BRL WP JSON, writes data/harvest/brl_questionnaires.json
python3 tools/refresh_finance_2026.py   # optional; re-pulls city clerk filings into data/harvest/finance_2026.json and prints before/after
python3 seed.py              # destroys and rebuilds data/bouldervotes.db
python3 build.py             # writes static HTML into docs/
```

`seed.py` is the whole load. It calls `ingest.py` (forums, measures, BRL harvest, Boulder Beat 2023 quiz, 2026 finance). The SQLite file is gitignored; the harvest JSON is committed so a rebuild does not need the network.

GitHub Pages serves `docs/` from `main`. After a merge to `main`, Pages rebuilds in ~30s. This machine’s system resolver often cannot see `bouldervotes.org`; `dig` and `curl --resolve bouldervotes.org:443:185.199.108.153 https://bouldervotes.org/` are the check.

## Adding a fact

1. Put it in `seed.py` or `ingest.py`, hanging off a `sources` row.
2. Rebuild. Confirm it on the person page **and** the matching `issues/<slug>-<year>.html`.
3. If it is a new year, add the year to `YEARS` in `build.py` and to `how` / council `seats`. Rebuild will pick up the year page from the loop.

Do not invent campaign URLs, attendance, or nos from silence. If only four people were named as endorsing a measure, store those four.

## 2026 evidence graph (endorsements, organizations, statements)

Loaded only from committed JSON in `data/harvest/2026/` by `ingest_2026.py`; no facts are typed into Python. Those files are produced by `tools/approve_2026.py` from the research folder, and every audit decision (held quotes, held edges, display names, dated board roles, ranked-choice order) is an explicit constant at the top of that script. To change a decision, edit the constant, re-run it, and review the JSON diff.

Rules the tests enforce (`tests/test_graph_2026.py`):

- Every endorsement has a source and a `provenance`: `endorser_statement` (the group's own release, or a news story reprinting it), `campaign_claim` (only source is the candidate's or ballot campaign's own site), `filing` (city committee registration), `news_report` (an outlet lists it; no endorser statement found). Campaign claims always render as “X campaign lists Y”.
- `status='held'` rows (statements or edges) are loaded but never rendered.
- A journalist's group summary goes in `reported_lines`, attributed to the outlet. Never fan it out into per-person yes/no answers.
- Every edge has an entry in the verification ledger (`data/harvest/2026/endorsement_verification.json`, copied from `bv-research/endorsement_verification_2026.json`): `PASS | CORRECTED | HOLD | REMOVE`, `checked_on`, `evidence_url`, `note`. `REMOVE` edges are kept as a record but not published; `HOLD` edges can never be `endorser_statement`.
- An `endorser_statement` edge must cite the endorser's own website, or a source listed in `AUTHORED_ELSEWHERE` in `approve_2026.py` (verbatim press-release repost, the endorser's verified social account, a signed op-ed). A campaign's listing never counts. Source replacements, provenance upgrades, roster title fixes and new edges from a verification pass are constants in `approve_2026.py` (`SOURCE_CORRECTIONS`, `PROVENANCE_UPGRADES`, `TITLE_CORRECTIONS`, `NEW_EDGES`).
- Ranked-choice endorsements keep `rank`.
- Endorser grouping (organizations / current elected / former elected / other individuals) uses only the title printed on the cited page. No title → “other individuals”. It is presentation, not a score.

### Ballot order

2026 candidates are listed in official ballot order wherever candidates are listed (home, year page, people index, issue and compare pages, print packet). The order lives only in `data/harvest/2026/ballot_order.json` with its source URL; `ingest_2026.py` writes it to `candidacies.ballot_position` and fails if a 2026 candidate is missing. Forum pages and the measure-page forum quotes stay in speaking order. Earlier years stay alphabetical (no ballot order recorded).

## Adding a questionnaire

Preferred: harvest into `data/harvest/` (see `harvest_brl.py`) then ingest. For a small yes/no sheet, a function in `ingest.py` is fine — `ingest_beat_2023` is the pattern.

Binary `stance` (`yes` / `no` / `mixed`) only when the source is actually binary. Long BRL answers stay `stance=NULL` with `verbatim` as published.

## Adding a forum

`events` + `event_appearances`. Attendance only when a published source named who showed. Link `recording_url` when a video exists. Spoken answers become `answers` with `kind=forum` and `event_id` set — they file onto issue pages, they do not lengthen the year page.

### 2026 forum transcripts

`python3 tools/approve_forums_2026.py ../bv-research ../bv-transcribe/transcripts` copies the 330 reviewed claims to `data/harvest/2026/forum_claims.json`, event facts to `forums.json`, and the Whisper transcripts to `data/harvest/2026/transcripts/`. Editorial decisions live only in that tool's named constants: `FORUMS_2026`, `FORUM_QUESTIONS`, `FORUM_STANCES` (the only place a yes/no is set, keyed by candidate + video + quote prefix; only for 2J, 2K, CAN/bus lanes, proportional-representation study session; caveated answers stay unlabelled with a note) and `FORUM_HOLDS` (attribution doubtful; not rendered). `ingest_forums_2026.py` loads them; `build_forums_2026.py` renders candidate sections, `forums/<slug>.html`, `compare.html` + `compare/*.html` and the 2J/2K measure sections. Every quote shows "Automatic transcript; check the recording." and a watch link; speaking-order attributions show the medium-confidence caveat. `tests/test_forums_2026.py` checks every quote against the committed transcript.

## Publishing

Work in a git worktree, not on `main`. Branch, commit, PR to `unforcedagi/bouldervotes.org`, merge when the Pages tree in `docs/` is the thing you want live.

Local git identity in this repo is `unforcedagi` / `unforcedagi@users.noreply.github.com`.

## Print packet

`build.py` writes `docs/print/<slug>.html` for every 2026 candidate and `docs/print/index.html`. A short sheet (usually one or two letter pages): campaigns, up to four answers printed in full (never inside `<details>`), clerk raised/spent/matching. No JavaScript. File → Print. Site-wide print CSS also forces every closed `<details>` open (`::details-content`), so printing any page prints folded answers.

## Campaign finance

Municipal filings are the city clerk (`election-committee-filings`), not TRACER. Matching-funds flags hang on `candidacies.matching_funds`. Dollar totals and itemized contributions/expenditures for 2026 live in `finance_snapshots` / `finance_line_items`, harvested by `harvest_finance.py` from the live clerk HTML (no JS required for the numbers). $0 is a filed zero. Do not invent dollar amounts.

Refresh after each city filing date (2026: Sept. 22, Oct. 6, Oct. 13, Oct. 20, Oct. 29, Dec. 3; see bouldercolorado.gov/election-guidelines):

```bash
python3 tools/refresh_finance_2026.py        # harvest + before/after table + flags
python3 tools/refresh_finance_2026.py --compare   # table only, vs git HEAD
python3 seed.py && python3 build.py && python3 -m unittest && python3 tools/check_links.py
```

- The table compares against the committed JSON at HEAD. Read the flags: a total that went DOWN, matching above contributions, new or vanished committees, and committees with no new report. Investigate before committing; never smooth a figure. Oddities that are real get a note in `ingest_finance_2026` so the page says "as filed".
- `retrieved_on` is today's date (override with `BV_RETRIEVED_ON=YYYY-MM-DD`). Each snapshot stores the clerk's report name (`report_label`), its filing date (`reported_on`) and the statement URL (`report_url`); pages and the API show all three.
- The clerk server omits its DigiCert intermediate certificate. `harvest_finance.py` adds the public intermediate from `data/certs/` to the trust store; TLS verification stays on. Never switch verification off.
- A committee with no new report keeps its last figures, and its row names that older report.

## What is parked

- Vote411 / LWV 2026 questionnaire — when it opens.
- Chamber 2026 *written* scorecard / extended-response PDF — not published as of 2026-08-31 (policy page still says 2025). The Aug 26 forum recording is up.
- Verbatim ingest of Chamber 2025 extended PDF and Open Boulder 2025 PDFs (catalogued, not copied into `answers` yet).
- Past-year campaign-finance dollar totals (Laserfiche archive is JS/cookie; 2026 live app is harvested, including itemized donors).
- 2015 and earlier cycles.
- Forum transcripts as quotes beyond the reviewed 2026 set (do not invent spoken words from a journalist’s grouping).
