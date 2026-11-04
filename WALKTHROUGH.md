# Walkthrough: Boulder Votes in archive mode

The earlier walkthrough (election-night results) is in git history at 1a2800d. Its images `results-*.png` stay in `walkthrough/`.

## How to run it

Live: https://bouldervotes.org/ after the merge. Locally:

```sh
python3 seed.py && python3 build.py
python3 -m http.server -d docs 8765     # open http://localhost:8765/
```

Screenshots come from that build in Chromium, at 390 and 1280 pixels wide.

## Steps

1. **Home page, phone** (`walkthrough/archive-01-home-390.png`).
   "The election is over, so every page now opens with one short note: the election was on November 3, and this guide is kept as an archive."
2. **Home page, desktop** (`walkthrough/archive-02-home-1280.png`).
   "The note links straight to Boulder County's official results and says the counts are unofficial until the county certifies them."
3. **Results page** (`walkthrough/archive-03-results-390.png`).
   "The results page keeps the unofficial caveat and now says this guide no longer updates the count. The county has the latest."
4. **A candidate page** (`walkthrough/archive-04-candidate-390.png`).
   "Every page carries the same note, including candidate pages. The AI chat link is gone from the footer and the home page; the chat page itself now returns a 404."
5. **What's off.** No screen.
   "Behind the scenes, nothing runs on a schedule any more: the AI chat is off, results updates refuse to run unless someone turns them on on purpose, and the page counter is the only thing still listening."
