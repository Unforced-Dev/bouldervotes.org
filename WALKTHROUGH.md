# Walkthrough: election-night results, ready behind a flag

The earlier walkthrough (page counts) is in git history at 4b0a1f1. Its images `01-*.png` and `02-*.png` stay in `walkthrough/`.

## How to run it

The page is off by default. To see it with real Boulder County numbers from the 2023 election (the saved test fixture):

```sh
BV_RESULTS=1 BV_RESULTS_FILE=tests/fixtures/results_2023C/results.json python3 build.py
python3 -m http.server -d docs 8765     # open http://localhost:8765/ and /results.html
python3 build.py                         # flag off again before committing
```

Screenshots come from that build in Chromium, at 390 and 1280 pixels wide.

## Steps

1. **Home page, results card** (`walkthrough/results-01-home-card-390.png`)
   - Narration: "Once the county posts numbers, a calm results card is the first thing on the home page. It says the results are unofficial and gives the county's time."
2. **Top of the results page** (`walkthrough/results-02-top-390.png`)
   - Narration: "The page opens with the plain caveat: unofficial until the county certifies. Next comes the county's 'last updated' time, the time we copied it, and a link to the county's own page."
3. **Mayor** (`walkthrough/results-03-mayor-390.png`)
   - Narration: "For mayor, the county's round-by-round count shows only when the county has posted it. First choices are labelled as first choices, not the result. No one is called the winner."
4. **Council and measures** (`walkthrough/results-04-council-measures-390.png`)
   - Narration: "Council candidates stay in ballot order, not sorted by votes. Each measure gets two equal panels, YES and NO, in the same neutral style."
5. **Desktop** (`walkthrough/results-05-page-1280.png`)
   - Narration: "The same page on a desktop. Every vote count links to Boulder County's results page."

Nothing changes on the live site until the flag is turned on (see `RESULTS-RUNBOOK.md`).
