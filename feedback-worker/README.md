# bouldervotes-feedback

A Cloudflare Worker + D1 database that collects corrections and ideas for
bouldervotes.org, and keeps the site's daily page counts. The site stays static;
only this Worker takes input. Submissions are stored, never shown publicly.

- Live: https://feedback.bouldervotes.org (also https://bouldervotes-feedback.unforced.workers.dev)
- D1 database: `bouldervotes-feedback` (id in `wrangler.toml`)
- The site's single pointer to it is `FEEDBACK_URL` in `build.py`.

## Endpoints

| Method + path | Who | What |
|---|---|---|
| `POST /` | the HTML form on feedback.html | form-urlencoded; 303 to `/feedback.html?sent=1#sent`, or `?error=<reason>#problem` |
| `POST /api/v1/feedback` | AI agents, scripts | JSON in, `{ok, id}` out; CORS `*`; `OPTIONS` handled |
| `GET /api/v1/feedback/schema` | anyone | JSON description of the fields, limits and error codes |
| `GET /admin/feedback?status=new` | admin | `Authorization: Bearer $ADMIN_TOKEN`; `status` = new, reviewed, fixed, declined or all |
| `POST /admin/feedback/<id>` | admin | body `{"status": "reviewed"}` etc. |
| `DELETE /admin/feedback/<id>` | admin | removes a row (test data) |
| `POST /api/v1/count` | every page on the site | `text/plain` body `{"path": "/about.html"}`; 204. Only `Origin: https://bouldervotes.org` |
| `GET /api/v1/counts?days=30` | admin | `Authorization: Bearer $ADMIN_TOKEN`; rows of `{day, path, n}`, newest day first, `days` 1 to 366 |

## Page counts (replaced Cloudflare Web Analytics, 2026-10)

Each page carries a one-line inline script (`COUNT_SNIPPET` in `build.py`) that POSTs its own
path once per load, with `credentials: "omit"` and `referrerPolicy: "no-referrer"`. The table
`page_counts` holds one row per (UTC day, path) with a count `n`, and nothing else: no IP,
user agent, referrer, cookie, visitor id or time finer than a day.

- Origin must be exactly `https://bouldervotes.org` (else 403). CORS allows that origin only, no credentials.
- Body at most 512 bytes, enforced while reading the stream (else 413, stream cancelled).
- `path` is `/`, or lowercase `[a-z0-9_.-]` segments ending in `.html` or `/`, at most 200 characters (else 400).
- A row stops at 50,000 a day; a day stops taking new paths at 2,000.

## Abuse controls (no CAPTCHA: it would block AI agents and annoy older voters)

- Honeypot field `homepage` (hidden in the form); anything in it is rejected.
- 5 notes per `ip_hash` per hour and 200 per day overall, counted in D1.
- Message 10 to 4000 characters, contact at most 200, body at most 20 KB.
- A message with more links than words is rejected.
- `ip_hash` is SHA-256(IP + `SALT`). The raw IP is never stored.

## Deploy

Credentials come from `~/.hermes/.env` (never print or commit them).

```sh
cd feedback-worker
set -a; . ~/.hermes/.env; set +a
bunx wrangler@4 d1 execute bouldervotes-feedback --remote --file=schema.sql -y   # idempotent
bunx wrangler@4 deploy
```

## Tests

Real workerd and a local D1 through miniflare (`node --test`):

```sh
cd feedback-worker
npm ci && npm test
```

Secrets (already set; to rotate, pipe a new value):

```sh
python3 -c 'import secrets;print(secrets.token_urlsafe(32))' | bunx wrangler@4 secret put ADMIN_TOKEN
```

Local copies live in `~/.hermes/.env` as `BV_FEEDBACK_ADMIN_TOKEN` and `BV_FEEDBACK_SALT`.
Rotating `SALT` resets the per-sender rate limit; that's fine.

## Review

```sh
set -a; . ~/.hermes/.env; set +a
python3 tools/feedback_digest.py            # prints nothing when there is nothing new
```

Every correction is a claim. Check it against the source before changing any data,
then mark the row `fixed`, `reviewed` or `declined`. We can only reply when the
sender left a contact.
