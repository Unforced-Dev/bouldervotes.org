# Walkthrough: our own page counts replace Cloudflare Web Analytics

## How to run it

```sh
cd feedback-worker && npm ci
npm run e2e -- ../walkthrough     # local only: built docs/ + the Worker in local workerd + headless Chromium
```

Live check (already done once at deploy; adds one count to `/`):

```sh
curl -si -X POST https://feedback.bouldervotes.org/api/v1/count \
  -H 'Origin: https://bouldervotes.org' -H 'Content-Type: text/plain' --data '{"path":"/"}'
```

## Steps

1. **View source of any page, bottom of the file.**
   Show: the last `<script>` line, a single `fetch` to `feedback.bouldervotes.org/api/v1/count` with `{"path":"/about.html"}`.
   Say: "Every page used to load a script from Cloudflare. Now it sends one line to our own counter: plus one for this page today."

2. **The About page, "Visitor counts".** Screenshot: `walkthrough/01-about-visitor-counts.png`.
   Say: "The About page now says exactly what we keep: the date, the page, and a number. No cookies, no IP address, nothing about the visitor."

3. **The browser test output.**
   Show: `page_counts: [{"path":"/","n":1},{"path":"/about.html","n":2}]` then `OK: three page loads, three counts`.
   Say: "A real browser opened About twice and the home page once. The counter has three counts and nothing else."

4. **A foreign site tries to count.**
   Show: the same curl with `Origin: https://evil.example` returns `HTTP/2 403`.
   Say: "Only bouldervotes.org can add counts. Other sites get turned away."

5. **The admin read.**
   Show: `GET /api/v1/counts?days=7` with the admin token, returning `{day, path, n}` rows; without the token, 401.
   Say: "We read the totals with the same admin key as the feedback inbox."

The home page (`walkthrough/02-home.png`) looks the same as before; nothing visible changed there.
