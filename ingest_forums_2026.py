"""Load 2026 candidate-forum answers from data/harvest/2026/forum_claims.json
and forums.json (both produced by tools/approve_forums_2026.py).

Nothing here is hand-typed fact. Rows:
  events            kind='forum', recording_url = first recording
  event_appearances one row per candidate quoted at that forum
  sources           one row per video (kind='video')
  questions         kind='forum', year=2026
  answers           kind='forum', verbatim = transcript quote, stance only as
                    set in FORUM_STANCES; notes carry the timestamped link,
                    attribution confidence and claim id.
Held claims (status='held') are not loaded as answers and never rendered.
"""
from __future__ import annotations

import json
from pathlib import Path

H2026 = Path(__file__).resolve().parent / "data" / "harvest" / "2026"
TRANSCRIPT_NOTE = "Automatic transcript; check the recording."


def load_forums() -> dict:
    return json.loads((H2026 / "forums.json").read_text(encoding="utf-8"))


def load_claims() -> list[dict]:
    return json.loads((H2026 / "forum_claims.json").read_text(encoding="utf-8"))


def answer_notes(c: dict) -> str:
    bits = [
        f"Watch: {c['youtube_url_with_t']}",
        f"Attribution confidence: {c['attribution_confidence']}",
        f"Claim: {c['id']}",
        f"Segment: {c['segment']}",
        f"Topic: {c['topic']}",
        "Automatic transcript (Whisper), quoted exactly",
    ]
    if c.get("measure"):
        bits.append(f"Measure: {c['measure']}")
    if c.get("note"):
        bits.append(f"Transcript note: {c['note']}")
    if c.get("stance_note"):
        bits.append(f"Stance note: {c['stance_note']}")
    return " | ".join(bits)


def ingest_forums_2026(cur, *, add_source) -> dict:
    doc = load_forums()
    claims = load_claims()

    def org_id(name: str, slug: str) -> int:
        cur.execute("SELECT id FROM organizations WHERE name=?", (name,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM organizations WHERE slug=?", (slug,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("INSERT INTO organizations (slug, name, kind) VALUES (?,?,?)", (slug, name, "forum_host"))
        return cur.lastrowid

    def slugify(s: str) -> str:
        return "".join(ch if ch.isalnum() else "-" for ch in s.lower()).strip("-").replace("--", "-")

    for i in doc["new_issues"]:
        cur.execute("INSERT OR IGNORE INTO issues (slug, name, description) VALUES (?,?,?)",
                    (i["slug"], i["name"], i["description"]))

    ev_ids, src_ids = {}, {}
    for f in doc["forums"]:
        hosts = [org_id(h, slugify(h.split(" (")[0])) for h in f["hosts"]]
        rec0 = f"https://www.youtube.com/watch?v={f['recordings'][0]['youtube_id']}"
        notes = f["notes"] + " Hosts: " + ", ".join(f["hosts"]) + ". Date: " + f["date_source"]
        cur.execute("SELECT id FROM events WHERE slug=?", (f["slug"],))
        row = cur.fetchone()
        if row:
            cur.execute("""UPDATE events SET name=?, starts_on=?, venue=COALESCE(?, venue), host_org_id=?,
                           kind='forum', recording_url=?, notes=? WHERE id=?""",
                        (f["name"], f["date"], f["venue"], hosts[0], rec0, notes, row[0]))
            ev_ids[f["slug"]] = row[0]
        else:
            cur.execute("""INSERT INTO events (slug, name, starts_on, venue, host_org_id, kind, recording_url, notes)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (f["slug"], f["name"], f["date"], f["venue"], hosts[0], "forum", rec0, notes))
            ev_ids[f["slug"]] = cur.lastrowid
        for r in f["recordings"]:
            url = f"https://www.youtube.com/watch?v={r['youtube_id']}"
            cur.execute("SELECT id FROM sources WHERE url=?", (url,))
            row = cur.fetchone()
            src_ids[r["youtube_id"]] = row[0] if row else add_source(
                url, f"{r['title']} ({r['uploader']}, YouTube)", "video", 2026, hosts[0], r["uploaded"],
                f"Recording of {f['name']}, {f['date']}. Quotes on this site come from an automatic transcript.")

    q_ids: dict[tuple[str, str], int] = {}
    for f in doc["forums"]:
        for q in f["questions"]:
            cur.execute("INSERT INTO questions (prompt, issue_slug, year, kind, is_canonical) VALUES (?,?,?,?,1)",
                        (q["prompt"], q["issue_slug"], 2026, "forum"))
            q_ids[(f["slug"], q["prompt"])] = cur.lastrowid

    def cand(name: str):
        cur.execute("""SELECT c.id, c.person_id FROM candidacies c JOIN people p ON p.id=c.person_id
                       JOIN races r ON r.id=c.race_id JOIN elections e ON e.id=r.election_id
                       WHERE p.full_name=? AND e.year=2026""", (name,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"2026 candidacy not found: {name}")
        return row

    dates = {f["slug"]: f["date"] for f in doc["forums"]}
    absent = {(f["slug"], n) for f in doc["forums"] for n in f.get("absent_statement_read", [])}
    appeared: set[tuple[str, str]] = set()
    n = 0
    for c in claims:
        cid, pid_ = cand(c["candidate"])
        if (c["event"], c["candidate"]) not in appeared:
            appeared.add((c["event"], c["candidate"]))
            gone = (c["event"], c["candidate"]) in absent
            cur.execute("""INSERT OR IGNORE INTO event_appearances (event_id, candidacy_id, person_id, attended, notes)
                           VALUES (?,?,?,?,?)""",
                        (ev_ids[c["event"]], cid, pid_, 0 if gone else 1,
                         "Did not attend; the moderator read the candidate's submitted statement." if gone
                         else "Quoted in the forum recording (automatic transcript)."))
        if c["status"] != "published":
            continue
        cur.execute(
            """INSERT INTO answers (candidacy_id, person_id, question_id, source_id, event_id, kind,
                                    stance, verbatim, answered_on, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, pid_, q_ids[(c["event"], c["question"])], src_ids[c["youtube_id"]], ev_ids[c["event"]],
             "forum", c["stance"], c["quote"], dates[c["event"]], answer_notes(c)))
        n += 1
    return {"forum_answers": n, "forum_held": sum(c["status"] == "held" for c in claims), "forum_questions": len(q_ids)}
