# Boulder Votes

A sourced map of City of Boulder municipal elections — who is running, what they have said, which forums they showed up for, and where the underlying record lives.

**Audience, first:** older voters who want to read, not decode a dashboard. Large type, one column, citations on every number.

**Shape:** zoom a year (the ballot), zoom a person (issue × year grid), zoom an issue (that year’s field, plus labelled earlier answers from returning candidates). Sources are citations.

**Store, first:** SQLite. Cloudflare D1 is a later lift of the same schema, not a rewrite.

This is a prototype. It does not endorse anyone.

## Run it

Live: https://bouldervotes.org/ (GitHub Pages; custom domain). Mirror: https://unforcedagi.github.io/bouldervotes.org/

```bash
cd ~/REPOS/bouldervotes.org
python3 harvest_brl.py       # optional; writes data/harvest/brl_questionnaires.json
python3 harvest_finance.py   # optional; writes data/harvest/finance_2026.json from the city clerk
python3 tools/approve_2026.py ../bv-research   # optional; regenerates data/harvest/2026/*.json from research + audit
python3 seed.py              # rebuilds data/bouldervotes.db from schema + seed + harvest
python3 build.py             # writes static HTML to docs/ (GitHub Pages)
python3 -m unittest          # FK integrity, sources, trust rules, built-HTML labels, local links
python3 tools/check_links.py # broken local links under docs/
open docs/index.html
```

Python 3 stdlib only. No npm, no framework. How to extend it: [OPERATING.md](OPERATING.md).

## What’s in the database

- People who ran or held office 2017–2026 (city mayor + council)
- Certified 2017 council (five seats; fifth was a two-year term) and city measures 2L–2Q
- Certified 2019 council (six seats after Grano’s resignation) and city measures 2G/2H/2I
- Certified 2021 council (five seats; fifth was a two-year term) and city measures 2I/2J/300/301/302
- Certified 2023 mayor RCV + council (including the recount)
- Certified 2025 council totals
- Certified 2026 field (clerk list retrieved 2026-08-26)
- BRL written questionnaires: 2023 14×6 and 2025 11×6
- Boulder Beat 2023 emailed yes/no questionnaire (rent stabilization, occupancy, encampments, oversight, 2A, Safe Zones)
- Catalog of Chamber / Open Boulder / PLAN / Boulder Weekly questionnaires (linked; verbatim ingested only for BRL and Beat)
- Forum calendar 2017–2026 with recordings where they exist (including the 2025 VOTES! collaborative forum)
- One-sheet print packet for each 2026 candidate
- 2026 questions on the home page (bond, airport) — not a quiz; earlier-year answers stay on the person, not filed under 2026
- 2026 campaign-finance from the city clerk app: raised / spent / matching, itemized donors and expenditures on each dossier
- City ballot measures 2017–2026
- **2026 evidence graph** (from `data/harvest/2026/`): candidate bios and sourced statements (7 held pending verification), 237 endorsement edges with provenance (endorser's own statement / campaign claim / city filing / news listing), 24 organization and committee profiles, 63 person-endorser titles, full text and supporters/opponents for city measures 2J–2M, and a Civics 101 page

What’s *not* in it: invented positions, scored “matches,” Chamber 2026 written questionnaires (not published yet — the forum tape is), past-year finance dollar totals (Laserfiche not listed this pass), county/BVSD races, 2015 and earlier.

## Schema idea

This is an **evidence graph**, not a brochure.

`people` persist across years. `candidacies` hang on a `race`. `answers` always point at a `source`. Results keep RCV rounds. If we cannot cite it, it does not go on a page.

`schema.sql` is written so the same tables can move to D1.

## Editorial line

Quotes and reported stances stay attached to the journalist or the candidate’s own words. We do not collapse someone into a housing-score. If we later add a comparison UI, it will be “here is the question, here is each answer, here is the link.”
