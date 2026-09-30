# bouldervotes-feedback

A Cloudflare Worker + D1 database that collects corrections and ideas for
bouldervotes.org. The site stays static; only this Worker takes input.
Submissions are stored, never shown publicly.

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
