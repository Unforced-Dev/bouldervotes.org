#!/usr/bin/env bash
# Install a copy at ~/.hermes/scripts/bv_freshness.sh after review.
set -Eeuo pipefail
export PATH="/home/uni/.local/share/mise/shims:/usr/local/bin:/usr/bin:/bin"
export BV_STATE_DIR="${BV_STATE_DIR:-/home/uni/.hermes/state/bouldervotes}"
MAIN=/home/uni/src/bouldervotes.org
RUN=/home/uni/src/bouldervotes-freshness-run
mkdir -p "$BV_STATE_DIR"
exec 9>"$BV_STATE_DIR/run.lock"
flock -n 9 || exit 0
LOG="$BV_STATE_DIR/run-$(date +%Y%m%dT%H%M%S)-$$.log"
failure() {
    trap - ERR
    printf 'FAILED: freshness check; log: %s\n' "$LOG" >&3
    if [[ "$PWD" == "$RUN" && -f tools/freshness/digest.py ]]; then
        python3 - <<'PYFAIL' || true
from tools.freshness.common import state_dir, read, write
s = state_dir()
r = read(s / 'result.json', {})
r['published'] = []  # Accepted locally, but this run did not publish successfully.
write(s / 'result.json', r)
PYFAIL
        python3 tools/freshness/digest.py >&3 || true
    fi
    exit 1
}
trap failure ERR
exec 3>&1
exec >>"$LOG" 2>&1
# Only fetch/worktree-add operations target the production checkout.
git -C "$MAIN" fetch origin
if [[ ! -d "$RUN" ]]; then
    git -C "$MAIN" worktree add --detach "$RUN" origin/main
fi
cd "$RUN"
# Refuse to reset an unrelated checkout or a user's branch.
[[ "$(git rev-parse --path-format=absolute --git-common-dir)" == "$MAIN/.git" ]]
CURRENT=$(git symbolic-ref -q --short HEAD || true)
[[ -z "$CURRENT" || "$CURRENT" == freshness/* ]]
git switch --detach
git reset --hard origin/main
git clean -fd
python3 - <<'PY'
from tools.freshness.common import state_dir, write
s = state_dir()
write(s / 'result.json', {'published': [], 'held': []})
write(s / 'finance_changes.json', [])
(s / 'proposals.json').unlink(missing_ok=True)
PY
python3 tools/refresh_finance_2026.py >"$BV_STATE_DIR/finance.log" 2>&1
python3 tools/freshness/finance_digest.py "$BV_STATE_DIR/finance.log"
python3 tools/freshness/sources.py
python3 tools/freshness/watch.py
if python3 - <<'PY'
from tools.freshness.common import state_dir, read
raise SystemExit(0 if read(state_dir() / 'changes.json')['changes'] else 1)
PY
then
    mkdir -p "$BV_STATE_DIR/data"
    cp data/harvest/2026/{endorsements,candidates,measures,organizations,forums_upcoming}.json "$BV_STATE_DIR/data/"
    cp tools/freshness/worker_prompt.md "$BV_STATE_DIR/worker_prompt.md"
    (
        cd "$BV_STATE_DIR"
        timeout 15m /home/uni/.local/share/mise/shims/claude -p --model sonnet \
            --permission-mode acceptEdits --allowedTools "Read,Write" \
            -- "$(cat worker_prompt.md)"
    )
    test -f "$BV_STATE_DIR/proposals.json"
    python3 tools/freshness/verify_apply.py
fi
python3 seed.py
python3 build.py
python3 -m unittest
python3 tools/check_links.py
# Publish harvest or rendered changes (including forums dropping off at midnight).
if ! git diff --quiet -- data/harvest docs; then
    BRANCH="freshness/$(date +%Y%m%dT%H%M%S)-$$"
    git switch -c "$BRANCH"
    git add data/harvest docs
    git commit -m "Freshness update $(date +%F): sourced data and voter guide"
    git push -u origin "$BRANCH"
    BODY="$BV_STATE_DIR/pr-body.md"
    printf '%s\n' 'Automated freshness update. Evidence was checked against live source text; existing endorsements were preserved.' '' 'Validation: seed, build, unittest, and link checks passed.' >"$BODY"
    PR=$(gh pr create --repo Unforced-Dev/bouldervotes.org --base main --head "$BRANCH" \
        --title "Freshness update $(date +%F)" --body-file "$BODY")
    gh pr merge --repo Unforced-Dev/bouldervotes.org --merge "$PR"
    git switch --detach
fi
python3 - <<'PYACK'
from tools.freshness.common import state_dir, read, write
s = state_dir()
write(s / 'processed.json', {'checked_on': read(s / 'changes.json')['checked_on']})
PYACK
python3 tools/freshness/digest.py >&3
