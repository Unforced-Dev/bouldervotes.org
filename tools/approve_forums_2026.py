#!/usr/bin/env python3
"""Copy the 2026 candidate-forum claims into committed harvest files.

    python3 tools/approve_forums_2026.py [RESEARCH_DIR] [TRANSCRIPT_DIR]

RESEARCH_DIR defaults to $BV_RESEARCH or ../bv-research (reads
forum_claims_2026.json). TRANSCRIPT_DIR defaults to $BV_TRANSCRIPTS or
../bv-transcribe/transcripts (reads <youtube_id>.txt).

Writes:
  data/harvest/2026/forum_claims.json   every claim, verbatim, plus review fields
  data/harvest/2026/forums.json         event metadata, recordings, questions
  data/harvest/2026/transcripts/<id>.txt  Whisper transcripts, for offline checks

seed.py reads ONLY those committed files. Every editorial decision about the
forum quotes lives in the named constants below so it can be reviewed in one
place:

  FORUMS_2026      what each event was (date, hosts, venue, recordings). Each
                   entry cites where the fact came from.
  FORUM_QUESTIONS  which issue page a question files under, and whether it is
                   a yes/no question (the only kind that may carry a stance).
  FORUM_STANCES    the ONLY place a stance is set. Keyed by
                   (candidate, youtube_id, quote prefix). A stance is set only
                   when the quote itself says yes/no/support/oppose about the
                   thing asked. Caveated, leaning, conditional or implicit
                   answers are recorded here with stance None and a note, so
                   the decision not to label them is also on the record.
  FORUM_HOLDS      claims whose speaker attribution looked wrong on re-reading
                   the transcript. Kept in the harvest as status="held", never
                   loaded as answers, never rendered.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "harvest" / "2026"
AUDIT_DATE = "2026-09-29"
EXPECTED_CLAIMS = 330

DISPLAY_NAME = {"David Martus": "Dave Martus"}

# ---------------------------------------------------------------- events
# Sources: YouTube metadata (title, uploader, upload date, description) read
# with yt-dlp on 2026-09-29, plus the event rows already in seed.py/ingest.py.
FORUMS_2026 = [
    {
        "slug": "2026-chamber-forum",
        "name": "Boulder Chamber City Council and Mayoral Candidate Forum",
        "short": "Boulder Chamber forum",
        "date": "2026-08-26",
        "hosts": ["Boulder Chamber"],
        "venue": "eTown, 1535 Spruce St., Boulder",
        "date_source": "Boulder Chamber event listing (already in seed.py); Daily Camera Aug 27 2026 writeup.",
        "notes": "Season-opener at eTown. Council and mayoral candidates on one stage. "
                 "Daily Camera (Aug 27) reported 17 of 19 candidates present.",
        "recordings": [
            {"youtube_id": "CQlalpB7N5w", "title": "2026 | Boulder City Council Candidate Forum",
             "uploader": "Boulder Chamber", "uploaded": "2026-09-17", "part": None,
             "segments": [{"label": "Council and mayoral candidates together", "start": 0}]},
        ],
    },
    {
        "slug": "2026-votes-forum",
        "name": "Collaborative City Council and Mayoral Candidate Forum (PLAN-Boulder County / Open Boulder / Better Boulder)",
        "short": "PLAN / Open Boulder / Better Boulder forum",
        "date": "2026-09-02",
        "hosts": ["Better Boulder", "PLAN-Boulder County", "Open Boulder"],
        "venue": None,
        "date_source": "Better Boulder event page (already in ingest.py); video title 'Candidate-Forum - 090226'.",
        "notes": "Co-hosted by PLAN-Boulder County, Open Boulder and Better Boulder. Moderator: KC Becker "
                 "(Better Boulder post). Recording by greenlight studios. Several question wordings are "
                 "partly garbled in the automatic transcript and are marked as such.",
        "recordings": [
            {"youtube_id": "gdZzGJNB7g0", "title": "City of Boulder Colorado Candidate-Forum - 090226",
             "uploader": "greenlight studios", "uploaded": "2026-09-07", "part": None,
             "segments": [{"label": "Council and mayoral candidates together", "start": 0}]},
        ],
    },
    {
        "slug": "2026-arts-forum",
        "name": "2026 City Council Candidates Forum on Arts and Culture",
        "short": "Arts and culture forum",
        "date": "2026-09-15",
        "hosts": ["Boulder County Arts Alliance", "Boulder Chamber", "Create Boulder"],
        "venue": "Boulder Chamber, 2440 Pearl St., Boulder",
        "date_source": "YouTube description: 'Event Date: Tuesday, September 15th 2026 / Venue: Boulder Chamber, 2440 Pearl St.'",
        "notes": "Presented by Boulder County Arts Alliance, the Boulder Chamber and Create Boulder; moderated by "
                 "Justin Veach, BCAA board president. Posted in five parts. Written lightning-round answers are "
                 "linked from the video description and are not copied here.",
        "recordings": [
            {"youtube_id": "PlXLjT1gH5U", "title": "(Pt 1/5) 2026 City Council Candidates Forum on Arts and Culture",
             "uploader": "Boulder County Arts Alliance", "uploaded": "2026-09-16", "part": 1,
             "segments": [{"label": "Council candidates", "start": 0}]},
            {"youtube_id": "Syj4_V5cQOk", "title": "(Pt 2/5) 2026 City Council Candidates Forum on Arts and Culture",
             "uploader": "Boulder County Arts Alliance", "uploaded": "2026-09-17", "part": 2,
             "segments": [{"label": "Council candidates", "start": 0}]},
            {"youtube_id": "1At-W2cR9Mk", "title": "(Pt 3/5) 2026 City Council Candidates Forum on Arts and Culture",
             "uploader": "Boulder County Arts Alliance", "uploaded": "2026-09-17", "part": 3,
             "segments": [{"label": "Council and mayoral candidates", "start": 0}]},
            {"youtube_id": "Q1PXyt_DLqw", "title": "(Pt 4/5) 2026 City Council Candidates Forum on Arts and Culture",
             "uploader": "Boulder County Arts Alliance", "uploaded": "2026-09-17", "part": 4,
             "segments": [{"label": "Closing statements", "start": 0}]},
            {"youtube_id": "szDYv-0rIgU", "title": "(Pt 5/5) 2026 City Council Candidates Forum on Arts and Culture",
             "uploader": "Boulder County Arts Alliance", "uploaded": "2026-09-17", "part": 5,
             "segments": [], "no_quotes": True},
        ],
    },
    {
        "slug": "2026-lwv-forum",
        "name": "League of Women Voters of Boulder County City Council and Mayoral Candidate Forums",
        "short": "League of Women Voters forum",
        "date": "2026-09-26",
        "hosts": ["League of Women Voters of Boulder County", "Emergency Family Assistance Association (EFAA)"],
        "venue": None,
        "date_source": "City of Boulder YouTube title 'September 26, 2026 League of Women Voters of Boulder County "
                       "Candidate Forum' (uploaded 2026-09-28); description chapters.",
        "notes": "Sponsored by the League of Women Voters of Boulder County with co-sponsor EFAA. Moderator: "
                 "Martine Elinor (as transcribed). Recorded for Channel 8. Council forum first, then the mayoral "
                 "forum at noon. Candidates sat in ballot order. Tara Winer was out of state; by League policy the "
                 "moderator read her submitted opening statement.",
        "recordings": [
            {"youtube_id": "pT9IeGL6deg",
             "title": "September 26, 2026 League of Women Voters of Boulder County Candidate Forum",
             "uploader": "City of Boulder", "uploaded": "2026-09-28", "part": None,
             "segments": [{"label": "City Council forum", "start": 0},
                          {"label": "Mayoral forum", "start": 7504}]},
        ],
    },
]

# Candidates who did not attend but whose submitted statement was read aloud.
ABSENT_STATEMENT_READ = {("2026-lwv-forum", "Tara Winer")}

# ---------------------------------------------------------------- questions
# prompt prefix -> (issue_slug or None, stance_about or None, measure letter or None)
# stance_about is set only for the four yes/no questions named in the brief:
# 2J, 2K, the Core Arterial Network / bus lanes, and a proportional-representation
# study session.
NEW_ISSUES = [
    ("arts", "Arts and culture", "Cultural funding, creative spaces, the arts blueprint."),
    ("economy", "Business and the local economy", "Downtown, small business, recruiting employers, public-private partnerships."),
    ("land-use", "Land use and growth", "Title 9 land-use code, Area III, permitting and development review."),
    ("governance", "How the city is run", "The mayor's role, council and staff, auditing, representation."),
]

FORUM_QUESTIONS = {
    # Chamber
    "If elected, name your top three priorities. And do you believe": (None, None, None),
    "The mayor has a unique role in building consensus": ("governance", None, None),
    "Boulder Area Rental Housing Association question": ("housing", None, None),
    "What are your thoughts on the highest and best uses for Area 3": ("land-use", None, None),
    "Tell us one city issue on which you changed your position": (None, None, None),
    "What role do you see public and private partnerships": ("economy", None, None),
    "Lightning round: Boulder voters will consider authorizing up to $400 million": ("bond", "2K (the $400 million bond)", "2K"),
    "If elected, what is the single most important new initiative you would pursue in your first year to improve": ("economy", None, None),
    "Do you support continuing to prioritize alternatives to driving": ("transportation", None, None),
    "What specific strategies would you recommend that the City of Boulder initiate": ("economy", None, None),
    "What specific actions would you take to ensure Latino entrepreneurs": ("economy", None, None),
    "What specific strategies would you recommend for improving our permitting": ("land-use", None, None),
    "If elected, what specific actions would you take to support downtown": ("economy", None, None),
    "In your first two years on city council, what specific land use or housing": ("housing", None, None),
    "Choose another mayoral candidate.": (None, None, None),
    "Name one issue on which you believe you could work constructively": (None, None, None),
    # PLAN / Open / Better
    "Opening introduction (two minutes)": (None, None, None),
    "Title 9 of our city code is our land use code.": ("land-use", None, None),
    "Core Arterial Network / Iris Avenue transportation question": ("transportation", None, None),
    "Open space budget priorities question": ("budget", None, None),
    "Infrastructure bond / oversight question": ("bond", None, None),
    "A citizen group has developed a proposal for the city to hire a performance auditor": ("governance", None, None),
    "Wildfire question: mandatory home-hardening": ("wildfire", None, None),
    "Given the strong city manager / weak mayor structure": ("governance", None, None),
    # Arts and culture
    "What is one action you would prioritize during your term to strengthen Boulder's creative": ("arts", None, None),
    "How should the city use these tools": ("arts", None, None),
    "What measures would you support to ensure future CCRS": ("arts", None, None),
    "What would you do as a council member to make Boulder's budget": ("budget", None, None),
    "What changes would you support to make Boulder easier for creative": ("arts", None, None),
    "Final council-candidate arts question": ("arts", None, None),
    "If elected mayor, how would you use your leadership role": ("governance", None, None),
    "Final one-minute statement": (None, None, None),
    # League of Women Voters
    "Opening statement (one minute)": (None, None, None),
    "If elected, name your top three priorities, and do you believe the city is currently": (None, None, None),
    "What specific policies, development strategies, funding approaches": ("housing", None, None),
    "Boulder voters are being asked to authorize $400 million": ("bond", "2K (the $400 million bond)", "2K"),
    "What are your feelings about the bus-only lanes": ("transportation", "the Core Arterial Network / bus-only lanes", None),
    "Do you agree or disagree that our city council is adequately representative": ("governance", "a study session on proportional representation", None),
    "Ballot issue 2J, the residential vacancy excise tax, would be": ("housing", "2J (the vacancy tax)", "2J"),
    "Tell us about one city issue on which you changed your position": (None, None, None),
    "Mayoral opening statement (one minute)": (None, None, None),
    "What are the unique roles of the Boulder mayor": ("governance", None, None),
    "(EFA) What specific policies, development strategies": ("housing", None, None),
    "Ballot measure 2K: Boulder voters will consider authorizing": ("bond", "2K (the $400 million bond)", "2K"),
    "What types of housing would you prioritize? How are you as mayor": ("housing", None, None),
    "Ballot issue 2J, the residential vacancy excise tax (~$4,000": ("housing", "2J (the vacancy tax)", "2J"),
    "If elected, what is the single most important new initiative you would pursue during your first year as mayor": (None, None, None),
}

# ---------------------------------------------------------------- stances
# (candidate, youtube_id, quote prefix) -> (stance | None, note | None)
# Only questions with a stance_about above may appear here. Anything not listed
# has no stance. None = reviewed and deliberately left unlabelled.
L = "pT9IeGL6deg"
C = "CQlalpB7N5w"
FORUM_STANCES = {
    # --- 2K, Chamber lightning round
    ("Fred Smith", C, "with the progressive income tax"): (None, "Talks about other taxes; no yes/no on 2K in this quote."),
    ("Aquiles La Grave", C, "No plan. No budget. No trust."): (None, "Critical of the bond but does not say yes or no in these words."),
    # --- 2K, LWV council forum
    ("Jamillah Richmond", L, "Okay. Thank you. I do not support this bond"): ("no", None),
    ("Benita Duran", L, "But this one I do oppose"): ("no", "Adds that she does not oppose the investment in recreation, public safety and facilities."),
    ("Rachel Rose Isaacson", L, "I do support this measure, but"): (None, "Says 'I do support this measure' and adds that she shares concerns. Not labelled because the answer is caveated; read the quote."),
    ("Dave Martus", L, "As I mentioned earlier, I'm a no vote"): ("no", None),
    ("Scott Rendleman", L, "I don't support the bond measure."): ("no", None),
    ("Jill Grano", L, "I think we need to go back to the community"): (None, "Calls for a smaller, more targeted bond; no yes/no in this quote."),
    ("Ryan Jamieson", L, "I am against this particular bond measure"): ("no", "Adds he would support smaller, more targeted projects financed by debt."),
    ("Lynn Segal", L, "Opposed for all the reasons"): ("no", None),
    ("Tina Marquis", L, "Yeah, I support the bond"): ("yes", None),
    ("Lee Gilbert", L, "I'm also a no on the issue."): ("no", None),
    ("Sam Fuqua", L, "Yeah, I'm a reluctant yes"): (None, "Says 'a reluctant yes, but a yes.' Not labelled because the answer is caveated; read the quote."),
    ("Ryan Schuchard", L, "One, we're going to have service cuts"): (None, "Gives reasons; no yes/no in this quote."),
    # --- 2K, LWV mayoral forum
    ("Jameson Goldstein", L, "I 100 percent do not support this measure."): ("no", None),
    ("Fred Smith", L, "I think we could get a lot of fixes for half"): (None, "Suggests a smaller first step; no yes/no in this quote."),
    ("Aquiles La Grave", L, "are fully against it? So no."): ("no", None),
    ("Lisa Ann Jacobs", L, "It would be financial suicide"): (None, "Critical of the debt; no yes/no in these words."),
    ("Taishya Adams", L, "Initially, I was a yes"): (None, "Says she was initially a yes; her current position is not stated in this quote."),
    ("Aaron Brockett", L, "So I do support the bond and here's why."): ("yes", None),
    # --- 2J, LWV council forum
    ("Dave Martus", L, "No, and it's for the exact second half"): ("no", None),
    ("Scott Rendleman", L, "I do support that measure."): ("yes", None),
    ("Jill Grano", L, "Yeah, I absolutely support it."): ("yes", None),
    ("Ryan Jamieson", L, "Yeah, I'm against this"): ("no", None),
    ("Lynn Segal", L, "We should have a vacancy tax, but"): (None, "Supports a vacancy tax in principle but says it should be much higher; not labelled."),
    ("Tina Marquis", L, "Yeah, I support this tax"): ("yes", None),
    ("Lee Gilbert", L, "I lean towards the yes."): (None, "Says he leans toward yes; a lean is not labelled."),
    ("Sam Fuqua", L, "I'm a yes. I would consider raising it"): ("yes", None),
    ("Ryan Schuchard", L, "I'm also a yes."): ("yes", None),
    ("Jamillah Richmond", L, "I say yes to this."): ("yes", None),
    ("Benita Duran", L, "I am opposed to it and would be voting no."): ("no", None),
    ("Rachel Rose Isaacson", L, "I'm really happy that we finally get to make a decision"): (None, "No explicit yes or no in the transcript."),
    # --- 2J, LWV mayoral forum
    ("Lisa Ann Jacobs", L, "so absolutely not."): ("no", None),
    ("Taishya Adams", L, "I am a supporter of a residential vacancy tax."): ("yes", None),
    ("Aaron Brockett", L, "Yes, I'm absolutely a supporter of this tax."): ("yes", None),
    ("Jameson Goldstein", L, "I'm 100% in support of this vacancy tax."): ("yes", None),
    ("Fred Smith", L, "Well, I think it's a great idea."): (None, "Calls it 'a great idea' and then doubts $4,000 would make a difference; no explicit yes/no."),
    ("Aquiles La Grave", L, "I have been supportive of it."): (None, "Says he has been supportive and raises a fairness question; not labelled because caveated."),
    # --- CAN / bus-only lanes, LWV (council + mayoral)
    ("Benita Duran", L, "I believe in the principles"): (None, "Endorses the principles of the CAN; no explicit yes/no on the lanes."),
    ("Jill Grano", L, "I do support the core arterial network."): (None, "Says 'I do support' and adds a funding condition (grant dollars only). Not labelled because caveated."),
    ("Ryan Jamieson", L, "So in general, I do support the can."): (None, "Supports 'in general' with a funding condition. Not labelled because caveated."),
    ("Lynn Segal", L, "I'm opposed to the can the way it's going"): (None, "Opposed 'the way it's going'; conditional, not labelled."),
    ("Tina Marquis", L, "So first of all, I do support the dedicated bus lanes."): ("yes", None),
    ("Sam Fuqua", L, "So I am a supporter of the CAN"): ("yes", None),
    ("Jamillah Richmond", L, "I'm a yes on the can."): ("yes", None),
    ("Aquiles La Grave", L, "So I'm an absolute supporter of safer alternative"): (None, "Transcript wording is garbled ('... options than can'); not labelled."),
    ("Lisa Ann Jacobs", L, "So I am for bus lanes being driven by cars."): (None, "Wording is ambiguous in the transcript; not labelled."),
    ("Taishya Adams", L, "And so I'm a yes to continuing"): ("yes", None),
    ("Aaron Brockett", L, "Yes, I absolutely support our bus lanes"): ("yes", None),
    ("Jameson Goldstein", L, "That means completing the core arterial network."): (None, "Implicit; no explicit yes/no in this quote."),
    # --- Proportional-representation study session, LWV council
    ("Rachel Rose Isaacson", L, "I do support us having a study session"): ("yes", None),
    ("Scott Rendleman", L, "In terms of a study session, I'd be interested"): (None, "Interested in hearing more; not a yes or no."),
    ("Jill Grano", L, "We don't have proportional representation."): (None, "Not sure a study session solves it; not a yes or no."),
    ("Tina Marquis", L, "I am open to a study session"): (None, "'Open to' a study session; not labelled."),
    ("Sam Fuqua", L, "I would support a study session on this issue"): ("yes", None),
}

# ---------------------------------------------------------------- holds
# (candidate, youtube_id, quote prefix) -> reason. Held claims are not rendered.
FORUM_HOLDS = {
    ("Lee Gilbert", C, "Public-private partnerships have always kind of disturbed me"): (
        "Attribution doubtful. The moderator's cue is garbled ('Alright, Lea and Mantina' at 1:02:09) and the "
        "answer's theme (money going to war, federal spending) matches Lynn Segal's answers at this forum "
        "(0:56:58 and 1:39:36), not Lee Gilbert's transportation platform. Hold until a listener confirms the voice."
    ),
}


def _match(table: dict, cand: str, vid: str, quote: str):
    hits = [v for (c, y, p), v in table.items() if c == cand and y == vid and quote.startswith(p)]
    if len(hits) > 1:
        raise SystemExit(f"ambiguous constant key for {cand} {vid} {quote[:40]!r}")
    return hits[0] if hits else None


def question_meta(prompt: str):
    hits = [(k, v) for k, v in FORUM_QUESTIONS.items() if prompt.startswith(k)]
    if not hits:
        raise SystemExit(f"question not mapped: {prompt[:80]!r}")
    hits.sort(key=lambda kv: -len(kv[0]))  # longest prefix wins
    return hits[0][1]


def main() -> None:
    research = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("BV_RESEARCH", ROOT.parent / "bv-research"))
    tdir = Path(sys.argv[2] if len(sys.argv) > 2 else os.environ.get("BV_TRANSCRIPTS", ROOT.parent / "bv-transcribe" / "transcripts"))
    claims = json.loads((research / "forum_claims_2026.json").read_text())
    assert len(claims) == EXPECTED_CLAIMS, len(claims)

    vid_event = {r["youtube_id"]: f for f in FORUMS_2026 for r in f["recordings"]}
    (OUT / "transcripts").mkdir(parents=True, exist_ok=True)
    for vid, f in vid_event.items():
        rec = next(r for r in f["recordings"] if r["youtube_id"] == vid)
        if rec.get("no_quotes"):
            continue
        shutil.copyfile(tdir / f"{vid}.txt", OUT / "transcripts" / f"{vid}.txt")

    used_stance, used_hold = set(), set()
    out = []
    ordered = sorted(enumerate(claims), key=lambda ic: (
        [f["slug"] for f in FORUMS_2026].index(vid_event[ic[1]["youtube_id"]]["slug"]),
        [r["youtube_id"] for r in vid_event[ic[1]["youtube_id"]]["recordings"]].index(ic[1]["youtube_id"]),
        ic[1]["start_seconds"], ic[0]))
    for n, (i, c) in enumerate(ordered):
        name = DISPLAY_NAME.get(c["candidate"], c["candidate"])
        ev = vid_event[c["youtube_id"]]
        rec = next(r for r in ev["recordings"] if r["youtube_id"] == c["youtube_id"])
        seg = [s for s in rec["segments"] if s["start"] <= c["start_seconds"]][-1]["label"]
        issue, stance_about, measure = question_meta(c["question"])
        st = _match(FORUM_STANCES, name, c["youtube_id"], c["quote"])
        hold = _match(FORUM_HOLDS, name, c["youtube_id"], c["quote"])
        for table, used, v in ((FORUM_STANCES, used_stance, st), (FORUM_HOLDS, used_hold, hold)):
            if v is not None:
                used.add(next(k for k in table if k[0] == name and k[1] == c["youtube_id"] and c["quote"].startswith(k[2])))
        if st is not None and not stance_about:
            raise SystemExit(f"stance on a non-binary question: {name} {c['quote'][:40]!r}")
        out.append({
            **c,
            "candidate": name,
            "id": f"FC{n + 1:03d}",
            "research_index": i,
            "event": ev["slug"],
            "segment": seg,
            "issue_slug": issue,
            "measure": measure,
            "stance_about": stance_about,
            "stance": st[0] if st else None,
            "stance_note": st[1] if st else None,
            "status": "held" if hold else "published",
            "hold_reason": hold,
            "audited_on": AUDIT_DATE,
        })
    missing = (set(FORUM_STANCES) - used_stance) | (set(FORUM_HOLDS) - used_hold)
    if missing:
        raise SystemExit(f"constant keys matched no claim: {sorted(missing)}")

    forums = []
    for f in FORUMS_2026:
        qs = []
        for c in out:
            if c["event"] == f["slug"] and c["question"] not in [q["prompt"] for q in qs]:
                issue, about, measure = question_meta(c["question"])
                qs.append({"prompt": c["question"], "issue_slug": issue, "stance_about": about, "measure": measure})
        forums.append({
            **f,
            "absent_statement_read": sorted(n for s, n in ABSENT_STATEMENT_READ if s == f["slug"]),
            "questions": qs,
        })
    doc = {"audited_on": AUDIT_DATE, "new_issues": [dict(zip(("slug", "name", "description"), x)) for x in NEW_ISSUES],
           "forums": forums}
    (OUT / "forum_claims.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    (OUT / "forums.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")

    st = Counter(c["status"] for c in out)
    stances = Counter(c["stance"] for c in out if c["stance"])
    print(f"claims={len(out)} status={dict(st)} stances={dict(stances)} "
          f"medium={sum(c['attribution_confidence'] == 'medium' for c in out)} "
          f"questions={sum(len(f['questions']) for f in forums)}")


if __name__ == "__main__":
    main()
