# Boulder Votes 2026: retrospective

Written Nov. 4, 2026, the day after the City of Boulder election. The site is now an archive. It needs no
upkeep and sends nothing.

## What we built

- **A sourced guide to the city ballot.** Mayor (ranked choice), five council seats, and measures 2J, 2K, 2L and 2M.
  One page per candidate with a short bio, their own words, endorsements and campaign money. Every quote,
  endorsement and dollar figure links to its source. Candidates appear in official ballot order.
- **Forum quotes.** Recorded candidate forums were transcribed, and quotes were checked word for word against the
  transcript. Each one links to that moment in the recording. Answers are laid side by side on the compare pages.
- **Endorsements with provenance.** Each endorsement says where it comes from: the endorser's own statement, a
  city filing, a news report, or "X campaign lists Y" when only the campaign says so.
- **Campaign money** from the city clerk's filings, refreshed after each filing date.
- **Past elections** back to 2017, results first.
- **Plain text and JSON for AI assistants**: `llms.txt`, `llms-full.txt` and a versioned JSON API, all built
  from the same database as the pages.
- **An AI chat (`/ask`)**, live Oct. 14 to Nov. 4. The model only picked an intent. Every sentence a voter
  saw came from a template filled with data, and every quote was checked by the gateway. It is off now; the code
  stays in the repo.
- **An election-night results view**, behind a flag, with "unofficial until certified" on every view and no
  winner language.
- **A freshness loop** that watched endorser and campaign pages and proposed changes. A human editorial check
  held every new endorsement before it went out.
- **A feedback form**, retired on Oct. 31 because almost everything it got was spam.
- **A privacy-light page counter**: one count per page per day, no cookies, no IP addresses.

The repo has 91 merged pull requests from Aug. 26 to Nov. 3, 2026.

## What got used

The page counter ran from Oct. 21. Through the morning of Nov. 4 it counted **3,046 page views**.

| Day | Views |
| --- | ---: |
| Oct. 21–31 (11 days) | 1,881 |
| Nov. 1 | 221 |
| Nov. 2 | 431 |
| Nov. 3 (Election Day) | 441 |
| Nov. 4 (morning) | 72 |

By page type: candidate pages 1,332, home page 847, endorsing groups 424, measure pages 262. Forums, compare
pages, printable sheets, Learn pages and past years each got under 20. The AI chat page got 6 views, and the
production chat gateway logged 9 requests in total. The results page got 2 views.

So people used the guide mostly as a lookup: open the home page, then a candidate or a measure. Traffic doubled
in the last two days before the election.

## What it cost

- **Hosting:** GitHub Pages, free.
- **Counter and feedback store:** one Cloudflare Worker and one D1 database, well inside Cloudflare's free
  limits.
- **AI chat:** $0.06 in production (9 requests). Testing on the preview gateway cost about $1.57 more, mostly
  evaluation runs. The shared gateway caps all of the free apps together at $10 a day.
- **Building it:** the work ran on flat-rate AI plans, so it wasn't metered per project.
- **The domain** is the one cost that keeps going. Check its renewal before the next election.

## What to reuse next election

- **The data flow.** Research goes into reviewed JSON in `data/harvest/`, then into SQLite, and every page, the
  llms files and the API are built from that. No facts are typed into templates. It made audits and fixes quick.
- **Provenance labels and ballot order from day one.** They answered most fairness questions before anyone asked.
- **Verified forum quotes with timestamped links.** They need hand attribution, but the result is trustworthy.
- **The results fetcher**, after a fix. It refused every election-night update because the county listed some
  candidates under different spellings (nicknames) and one name didn't match. Add the county's spellings to
  `data/harvest/2026/county_names.json`, or next year's copy of it, as soon as the county publishes its
  candidate list, and check every name against it before Election Day.
- **Start earlier.** The counter only started on Oct. 21, and ballots went out on Oct. 2. A guide that's ready when
  ballots mail reaches more voters.
- **Skip what didn't get used.** The AI chat cost little but took a lot of work and drew a handful of visits.
  The copy-paste prompt for people's own AI assistants offers similar help at no cost to us. An open feedback form drew
  spam, so plan real spam control before bringing one back.

## Turning it back on

- AI chat: build with `BV_CHAT_ENABLED=1`.
- Results updates: `BV_RESULTS_UPDATES=1` on a deliberate fetch (see `RESULTS-RUNBOOK.md`).
- The recurring jobs (nightly rebuild, daily source check, feedback digest, results updates) are paused in the
  scheduler, not deleted.
