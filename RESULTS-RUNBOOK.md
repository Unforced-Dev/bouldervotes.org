# Election-night results runbook (Nov 3, 2026)

The results view is built and tested behind `BV_RESULTS`. It is off by default, so merging the
code changed nothing live. This page covers turning it on and keeping the numbers current.

## Where the numbers come from

- Boulder County's results page: <https://electionresults.bouldercounty.gov/>. It is a copy of the county's
  results app at `https://election.boco.solutions/ElectionResults2026G/`. The county's landing page,
  <https://bouldercounty.gov/elections/results/>, links to it.
- There is no CSV or JSON export. Each contest's rows sit as JSON inside the page, and
  `tools/fetch_results_2026.py` reads them.
- The mayor's contest only links to `Home/RcvContest/1.html`. That page links the county's ranked-choice
  PDF, which has the round-by-round table, plus an RCVis chart. The tool reads the PDF with `pdftotext -layout`
  (poppler, installed on uni) and checks that every round adds up to the PDF's own "Continuing Ballots Total".
- If the PDF can't be read, the rest of the results still publish. The mayor section then says the county posted
  a round-by-round count and links to it.
- On Oct 29, 2026 the 2026 page was live and said "Coming Soon": `--dry-run` exited 3 ("no contests yet").
- The mirror root still serves stale 2023 files under `Home/`. The tool refuses any page whose title isn't
  "2026 General Election" and any ranked-choice PDF dated before Nov 3.

## 0. Before 7 p.m.: turn the flag on for every build (one time, clean session)

The nightly rebuild (00:10) and other workers run `build.py` without your environment. An environment
variable alone would take results down at 00:10, so flip the default in code:

```sh
cd /home/uni/src/bouldervotes.org && git fetch origin
git worktree add -b uni/results-on /home/uni/src/bouldervotes-results-on origin/main
cd /home/uni/src/bouldervotes-results-on
# build_results_2026.py: RESULTS_DEFAULT = "1"   (BV_RESULTS=0 stays the off switch)
# tests/test_results_2026.py, TestFlag: the first assert becomes assertTrue (default on)
python3 seed.py && python3 build.py && python3 -m unittest && python3 tools/check_links.py
git commit -am "Results view on by default for election night (BV_RESULTS=0 turns it off)"
git push -u origin HEAD && gh pr create -R Unforced-Dev/bouldervotes.org --fill && gh pr merge --merge
```

This is a code-only change with no web data, so a session that hasn't read web pages can merge it.
Until the first fetch, `results.html` says results come after 7 p.m. The home page stays as it is.

## 1. Each update (about 3 minutes)

```sh
cd /home/uni/src/bouldervotes.org && git fetch origin
T=$(date +%H%M); W=/home/uni/src/bouldervotes-results-$T
git worktree add -b data/results-1103-$T $W origin/main && cd $W

python3 tools/fetch_results_2026.py --dry-run    # prints the city numbers; saves nothing
python3 tools/fetch_results_2026.py              # saves raw pages + data/harvest/2026/results.json
python3 seed.py && python3 build.py
{ python3 -m unittest && python3 tools/check_links.py; } 2>&1 | tee /tmp/bv-verify-$T.log
```

Exit codes from the fetch:

- `0`: written.
- `3`: the county page has no contests yet. Wait and retry.
- `2`: STOP, nothing written. The message names the problem: wrong election title (stale copy), a
  2026 ballot name missing from the county file, a measure missing, or a round table that doesn't add up.
  Don't hand-edit around a STOP. Open the county page and see what changed.

Before publishing, look at the numbers. `--dry-run` printed them; check two or three against the county page by eye.

Publish through the reviewer. The fetch reads the web, so under T-225 this session doesn't merge its own data PR:

```sh
git add data/harvest/2026/results.json data/harvest/2026/results_raw docs
git commit -m "Results: county count as of <time from the page>"
git push -u origin HEAD
URL=$(gh pr create -R Unforced-Dev/bouldervotes.org --fill)
git diff origin/main...HEAD > /tmp/bv-diff-$T
~/Code/uni-ops/bin/bv-review --pr "$URL" --diff /tmp/bv-diff-$T --verify /tmp/bv-verify-$T.log --verified
```

After merge, check the Pages run (`gh run list -R Unforced-Dev/bouldervotes.org -L 3`), then
`curl -s https://bouldervotes.org/results.html | grep -o "count as of <strong>[^<]*"` to see the new time.
If an earlier results PR is still open, close it: each run carries the whole count, so only the newest matters.

## 2. How often

- **Nov 3:** the county posts its first drop shortly after 7 p.m. Run at about 7:15 p.m., then every
  30 minutes until about midnight, or until the county's "Last Updated" time stops changing.
- **Nov 4 to Nov 6:** the county adds batches over the next days. Run twice a day, around 10 a.m. and 5 p.m.,
  and once more whenever the county page shows a newer "Last Updated" time.
- **After that:** once a day until the county certifies. The page keeps saying "Unofficial results until
  the county certifies" throughout.
- Skip a run when the county's "Last Updated" time hasn't moved. `--dry-run` shows it on its first line.

## 3. Turning it off

`BV_RESULTS=0 python3 build.py` hides the page, the home card, the llms.txt section and `api/v1/results.json`.
For a lasting off, set `RESULTS_DEFAULT = "0"` again and merge.

## What the page does and doesn't say

- Every view carries: "Unofficial results until the county certifies. Results update as ballots are counted."
  It also shows the county's "Last Updated" time and the time we copied it.
- Every vote count links to the county's page.
- Mayor: the county's round-by-round count only when its file is posted and readable. First choices are always
  labelled "First-choice votes … not the result".
- Council: votes in ballot order (`ballot_order.json`), never sorted by votes.
- Measures: equal YES and NO panels.
- No "elected", "passed", "leading" or similar words. `tests/test_results_2026.py` checks the page,
  the home card, llms.txt and the JSON for them.
- After certification, the final numbers belong in the `results`/`measure_results` tables like past years.
  That is a separate change. Those tables have no as-of time, no unofficial status and no
  ballots-counted field, and their `elected`/`passed` columns would make calls on a partial count,
  which is why the live view reads `results.json` instead.

## Preview locally with the real 2023 county pages

```sh
BV_RESULTS=1 BV_RESULTS_FILE=tests/fixtures/results_2023C/results.json python3 build.py
python3 -m http.server -d docs 8765   # http://localhost:8765/results.html
python3 build.py                       # rebuild with the flag off before committing
```
