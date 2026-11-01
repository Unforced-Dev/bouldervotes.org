# Walkthrough: the feedback form is off

Aaron asked to turn feedback off because nearly all of it was spam. The repo's WALKTHROUGH.md
holds the election-night results runbook, so this one sits apart.

## How to run it

- Live: https://bouldervotes.org (any page), https://bouldervotes.org/feedback.html
- Locally: `python3 seed.py && python3 build.py && python3 -m http.server -d docs 8765`, then open http://127.0.0.1:8765/

## Steps

1. **A page footer** (`walkthrough/feedback-off-01-footer.png`).
   "The footer used to end with 'Spot a mistake? Tell us'. That link is gone, and nothing replaces it."
2. **The Learn hub** (`walkthrough/feedback-off-02-learn.png`).
   "Where our facts come from now lists Sources, About and Open data. The 'Suggest a fix' card is gone."
3. **/feedback.html** returns the site's normal 404.
   "The old form page no longer exists."
4. **The Worker**: `curl -i -X POST https://feedback.bouldervotes.org/api/v1/feedback` answers `410 Gone`
   with `{"ok": false, "error": "closed", "message": "Feedback is closed."}`.
   "Anything still posting to the old form or the agent endpoint gets a clear 'closed', and nothing is stored."
5. **Page counts still work.** Every page still sends its one count to the same Worker.
   "The visitor counts on the About page keep running as before."
