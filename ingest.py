"""Extra seed: BRL questionnaires, forum calendar, city ballot measures."""
from __future__ import annotations

import json
from pathlib import Path

HARVEST = Path(__file__).resolve().parent / "data" / "harvest" / "brl_questionnaires.json"


def _ensure_source(cur, add_source, url, *args):
    cur.execute("SELECT id FROM sources WHERE url=?", (url,))
    row = cur.fetchone()
    if row:
        return row[0]
    return add_source(url, *args)


def _cid(cur, person: str, year: int) -> int | None:
    cur.execute(
        """SELECT c.id FROM candidacies c
           JOIN people p ON p.id=c.person_id
           JOIN races r ON r.id=c.race_id
           JOIN elections e ON e.id=r.election_id
           WHERE p.full_name=? AND e.year=?""",
        ({"David Martus": "Dave Martus"}.get(person, person), year),
    )
    row = cur.fetchone()
    return row[0] if row else None


def ingest_questionnaires(cur, *, pid: dict, add_source, org_brl: int) -> None:
    data = json.loads(HARVEST.read_text(encoding="utf-8"))
    for post in data["posts"]:
        src_id = _ensure_source(
            cur,
            add_source,
            post["url"],
            post["title"],
            "questionnaire",
            post["year"],
            org_brl,
            post["published_on"],
            "BRL candidate questionnaire. Verbatim answers harvested 2026-08-27.",
        )
        cur.execute(
            """INSERT INTO questions (prompt, issue_slug, year, kind, is_canonical)
               VALUES (?,?,?,?,1)""",
            (post["prompt"], post["issue"], post["year"], "questionnaire"),
        )
        qid = cur.lastrowid
        for ans in post["answers"]:
            person = ans["person"]
            if person not in pid:
                raise SystemExit(f"harvest person not in seed: {person}")
            cur.execute(
                """INSERT INTO answers
                   (candidacy_id, person_id, question_id, source_id, event_id, kind,
                    stance, verbatim, answered_on, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    _cid(cur, person, post["year"]),
                    pid[person],
                    qid,
                    src_id,
                    None,
                    "questionnaire",
                    ans["stance"],
                    ans["verbatim"],
                    post["published_on"],
                    "Candidate's written answer to BRL, as published.",
                ),
            )


def ingest_beat_2023(cur, *, pid: dict, add_source, org_beat: int) -> None:
    """Boulder Beat 2023 emailed yes/no questionnaire (PDF).

    Only questions where the yes/no lists were readable without guessing.
    Mixed/conflicting answers stay mixed. Names not in pid are skipped.
    """
    src = _ensure_source(
        cur,
        add_source,
        "http://boulderbeat.news/wp-content/uploads/2023/10/Quiz-_-Candidates-match.pdf",
        "Boulder Beat 2023 candidate questionnaire (emailed yes/no)",
        "questionnaire",
        2023,
        org_beat,
        "2023-10-06",
        "Questions curated from public events and council votes. Responses emailed. PDF harvested 2026-08-27.",
    )

    def add_q(prompt: str, issue: str, yes: list[str], no: list[str], mixed: dict[str, str] | None = None) -> None:
        cur.execute(
            """INSERT INTO questions (prompt, issue_slug, year, kind, is_canonical)
               VALUES (?,?,?,?,1)""",
            (prompt, issue, 2023, "questionnaire"),
        )
        qid = cur.lastrowid
        mixed = mixed or {}
        rows = [(n, "yes", None) for n in yes] + [(n, "no", None) for n in no]
        rows += [(n, "mixed", note) for n, note in mixed.items()]
        for person, stance, note in rows:
            if person not in pid:
                continue
            extra = f" Beat note: {note}" if note else ""
            cur.execute(
                """INSERT INTO answers
                   (candidacy_id, person_id, question_id, source_id, event_id, kind,
                    stance, verbatim, answered_on, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    _cid(cur, person, 2023),
                    pid[person],
                    qid,
                    src,
                    None,
                    "questionnaire",
                    stance,
                    f"Answered {stance} on Boulder Beat’s 2023 emailed candidate questionnaire.{extra}",
                    "2023-10-06",
                    "Binary grouping as published by Boulder Beat. Not a long-form quote.",
                ),
            )

    add_q(
        "Would you support rent stabilization?",
        "housing",
        ["Silas Atkins", "Jennifer Robins", "Aaron Gabriel Neyer", "Nicole Speer",
         "Ryan Schuchard", "Taishya Adams", "Aaron Brockett", "Tara Winer", "Jacques Decalo"],
        ["Terri Brncic", "Waylon Lewis"],
        {
            "Tina Marquis": "Yes, in some cases. How it is implemented is important.",
            "Bob Yates": "Twice indicated support (public event + emailed) and twice opposed (Chamber and landlord events).",
        },
    )
    add_q(
        "Do you support Boulder’s recent expansion of occupancy limits (3 to 5 unrelated adults)?",
        "housing",
        ["Silas Atkins", "Aaron Gabriel Neyer", "Nicole Speer", "Ryan Schuchard",
         "Taishya Adams", "Aaron Brockett", "Waylon Lewis"],
        ["Paul Tweedlie", "Terri Brncic", "Jennifer Robins", "Bob Yates",
         "Tara Winer", "Tina Marquis", "Jacques Decalo"],
    )
    add_q(
        "Would you continue the city’s current encampment removal strategy?",
        "homelessness",
        ["Paul Tweedlie", "Terri Brncic", "Jennifer Robins", "Bob Yates",
         "Ryan Schuchard", "Aaron Brockett", "Tara Winer", "Tina Marquis", "Waylon Lewis"],
        ["Silas Atkins", "Aaron Gabriel Neyer", "Nicole Speer", "Taishya Adams"],
    )
    add_q(
        "Should the Police Oversight Panel have more authority over discipline when officers are found guilty of misconduct?",
        "policing",
        ["Silas Atkins", "Aaron Gabriel Neyer", "Nicole Speer", "Ryan Schuchard",
         "Taishya Adams", "Aaron Brockett", "Jacques Decalo"],
        ["Paul Tweedlie", "Terri Brncic", "Jennifer Robins", "Bob Yates"],
        {
            "Waylon Lewis": "They should have a say; not sure how much they have at present. Previously yes at the Raucous Caucus.",
            "Tara Winer": "Possibly on the email questionnaire. At the Raucous Caucus: yes, later ‘a little, but not much more.’",
            "Tina Marquis": "More say is too ambiguous. Feedback yes; replacing the department process no.",
        },
    )
    add_q(
        "Do you support the sales-tax extension and arts-funding ballot measure (2023 2A)?",
        "budget",
        ["Jennifer Robins", "Terri Brncic", "Aaron Gabriel Neyer", "Bob Yates",
         "Aaron Brockett", "Tara Winer", "Tina Marquis", "Waylon Lewis", "Ryan Schuchard"],
        ["Silas Atkins", "Paul Tweedlie", "Nicole Speer", "Taishya Adams", "Jacques Decalo"],
    )
    add_q(
        "Do you support the Safe Zones 4 Kids ballot measure?",
        "homelessness",
        ["Paul Tweedlie", "Terri Brncic", "Jennifer Robins", "Bob Yates",
         "Tara Winer", "Tina Marquis", "Jacques Decalo", "Waylon Lewis"],
        ["Silas Atkins", "Aaron Gabriel Neyer", "Nicole Speer", "Ryan Schuchard",
         "Taishya Adams", "Aaron Brockett"],
    )

    # 2021: only sourced endorsements of Question 300, not invented nos.
    s300 = _ensure_source(
        cur,
        add_source,
        "https://coloradonewsline.com/2021/11/02/initial-election-results-boulder-voters-reject-raising-occupancy-limits/",
        "Boulder voters reject raising residential occupancy limits (Colorado Newsline)",
        "article",
        2021,
        None,
        "2021-11-02",
        "Names Folkerts, Williams, Speer, and Benjamin as having endorsed Question 300.",
    )
    cur.execute(
        """INSERT INTO questions (prompt, issue_slug, year, kind, is_canonical)
           VALUES (?,?,?,?,1)""",
        (
            "Did you endorse Ballot Question 300 (Bedrooms Are For People — occupancy limits tied to bedrooms + 1)?",
            "housing",
            2021,
            "other",
        ),
    )
    q300 = cur.lastrowid
    for person in ["Lauren Folkerts", "Dan Williams", "Nicole Speer", "Matt Benjamin"]:
        cur.execute(
            """INSERT INTO answers
               (candidacy_id, person_id, question_id, source_id, event_id, kind,
                stance, verbatim, answered_on, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                _cid(cur, person, 2021),
                pid[person],
                q300,
                s300,
                None,
                "other",
                "yes",
                "Named by Colorado Newsline as having endorsed Question 300.",
                "2021-11-02",
                "Only the four named endorsers are stored. Absence is not a no.",
            ),
        )


def ingest_forums(cur, *, pid: dict, add_source, orgs: dict) -> None:
    """Forum calendar. Appearances only when a published source names who showed."""

    def add_event(slug, name, date, venue, host, kind, recording, notes, source_url=None, source_title=None, year=None):
        src_id = None
        if source_url:
            src_id = _ensure_source(
                cur, add_source, source_url, source_title or name, "article", year, None, None, None
            )
        cur.execute(
            """INSERT INTO events (slug, name, starts_on, venue, host_org_id, kind, recording_url, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (slug, name, date, venue, host, kind, recording, notes),
        )
        return cur.lastrowid, src_id

    def appear(event_id, year, people_attended, people_absent=(), note=None):
        for person in people_attended:
            cur.execute(
                """INSERT INTO event_appearances (event_id, candidacy_id, person_id, attended, notes)
                   VALUES (?,?,?,?,?)""",
                (event_id, _cid(cur, person, year), pid[person], 1, note),
            )
        for person in people_absent:
            cur.execute(
                """INSERT INTO event_appearances (event_id, candidacy_id, person_id, attended, notes)
                   VALUES (?,?,?,?,?)""",
                (event_id, _cid(cur, person, year), pid[person], 0, note),
            )

    # Existing 2025 chamber row was a stub. Replace notes/venue.
    cur.execute("SELECT id FROM events WHERE slug='2025-chamber-forum'")
    row = cur.fetchone()
    if row:
        cur.execute(
            """UPDATE events SET venue=?, recording_url=?, notes=? WHERE id=?""",
            (
                "New Vista High School, 700 20th St., Boulder",
                "https://www.youtube.com/watch?v=a-6Mso1bNhA",
                "Season-opener. Ten of eleven certified candidates spoke. Palacios is not named in the Daily Camera writeup of attendees. Recording: Boulder Chamber YouTube, '2025 City Council Candidate Forum' (2h05).",
                row[0],
            ),
        )
        ev_2025_chamber = row[0]
    else:
        ev_2025_chamber, _ = add_event(
            "2025-chamber-forum",
            "Boulder Chamber candidate forum (2025 cycle)",
            "2025-08-26",
            "New Vista High School, 700 20th St., Boulder",
            orgs["chamber"],
            "forum",
            "https://www.youtube.com/watch?v=a-6Mso1bNhA",
            "Season-opener.",
        )

    add_source(
        "https://www.dailycamera.com/2025/09/04/where-boulder-city-council-candidates-key-issues/",
        "Where Boulder City Council candidates stand on key issues (Daily Camera)",
        "article",
        2025,
        orgs["camera"],
        "2025-09-04",
        "Writeup of the Aug 26 2025 Chamber forum at New Vista. Names ten speakers.",
    )
    chamber_2025_present = [
        "Lauren Folkerts",
        "Rachel Rose Isaacson",
        "Matt Benjamin",
        "Mark Wallach",
        "Aaron Stone",
        "Rob Kaplan",
        "Jennifer Robins",
        "Nicole Speer",
        "Rob Smoke",
        "Maxwell Lord",
    ]
    appear(
        ev_2025_chamber,
        2025,
        chamber_2025_present,
        ["Montserrat Palacios"],
        "Daily Camera Sept 4 2025 photo/caption + body. Palacios not listed among the ten.",
    )

    # 2025 collaborative forum
    ev, _ = add_event(
        "2025-votes-forum",
        "Boulder VOTES! Collaborative Candidate Forum",
        "2025-09-08",
        "Nomad Playhouse, 1410 Quince Ave., Boulder",
        orgs["plan"],
        "forum",
        "https://www.youtube.com/watch?v=EVPJyt2dMvc",
        "Hosted by Open Boulder, Better Boulder, and PLAN-Boulder County. 5–7:30pm at Nomad Playhouse. Questions not taken from the audience. Recording: PLAN-Boulder YouTube embed on the Sept 12 2025 forum post.",
        "https://www.dailycamera.com/2025/09/06/boulder-groups-host-city-council-candidate-forum-next-week/",
        "Boulder groups host City Council candidate forum next week (Daily Camera)",
        2025,
    )
    appear(
        ev,
        2025,
        [
            "Mark Wallach",
            "Matt Benjamin",
            "Nicole Speer",
            "Lauren Folkerts",
            "Jennifer Robins",
            "Rob Kaplan",
            "Rachel Rose Isaacson",
            "Maxwell Lord",
        ],
        ["Montserrat Palacios", "Rob Smoke", "Aaron Stone"],
        "Daily Camera Sept 6 2025: eight of eleven present; Palacios, Smoke, Stone will not be present.",
    )

    # 2023 Chamber — all 14, Speer virtual. Recording exists.
    add_source(
        "https://www.dailycamera.com/2023/08/29/boulder-city-council-and-mayoral-candidates-face-off-at-candidate-forum/",
        "Boulder City Council and mayoral candidates face off at candidate forum (Daily Camera)",
        "article",
        2023,
        orgs["camera"],
        "2023-08-29",
        "All fourteen certified candidates. Speer participated virtually.",
    )
    ev, _ = add_event(
        "2023-chamber-forum",
        "Boulder Chamber City Council and Mayoral Candidate Forum",
        "2023-08-29",
        "Boulder JCC",
        orgs["chamber"],
        "forum",
        "https://www.youtube.com/watch?v=AEkK1eSLmNk",
        "Season-opener. All 14 certified candidates. Speer virtual. Questions from Chamber, Latino Chamber, Community Cycles: public safety, rent control, transportation, business support, labor shortages, minimum wage.",
    )
    chamber_2023 = [
        "Taishya Adams",
        "Silas Atkins",
        "Terri Brncic",
        "Jacques Decalo",
        "Waylon Lewis",
        "Tina Marquis",
        "Aaron Gabriel Neyer",
        "Jennifer Robins",
        "Ryan Schuchard",
        "Tara Winer",
        "Paul Tweedlie",
        "Nicole Speer",
        "Bob Yates",
        "Aaron Brockett",
    ]
    appear(
        ev,
        2023,
        chamber_2023,
        (),
        "Daily Camera Aug 29 2023. Speer virtual. YouTube recording linked from r/boulder the next day.",
    )
    cur.execute(
        "UPDATE event_appearances SET notes=? WHERE event_id=? AND person_id=?",
        (
            "Participated virtually (Daily Camera Aug 29 2023).",
            ev,
            pid["Nicole Speer"],
        ),
    )

    add_event(
        "2023-progressives-forum",
        "Boulder Progressives candidate forum",
        "2023-06-21",
        "Elks Lodge, Boulder",
        orgs["progressives"],
        "caucus",
        None,
        "Unofficial kickoff. BRL: eight council candidates and three mayoral candidates. Housing and homelessness dominated. Full attendance list not copied into this seed beyond the article.",
        "https://boulderreportinglab.org/2023/06/23/boulder-election-forum-puts-candidates-progressive-politics-to-the-test/",
        "Boulder election forum puts candidates’ progressive politics to the test (BRL)",
        2023,
    )
    add_source(
        "https://www.planboulder.org/boulder-election-2023",
        "Boulder Election 2023 — PLAN-Boulder County",
        "official",
        2023,
        orgs["plan"],
        None,
        "PLAN's own 2023 page lists two candidate forums (Aug 23 and Aug 29) with named attendees, plus endorsements. Venue not stated on that page.",
    )
    ev, _ = add_event(
        "2023-plan-mayor-forum",
        "PLAN-Boulder County candidate forum (mayor + two council)",
        "2023-08-23",
        None,
        orgs["plan"],
        "forum",
        None,
        "PLAN-Boulder County's own page: four mayoral candidates plus council candidates Taishya Adams and Jacques Decalo. Moderator Bill Briggs. Venue not stated.",
        "https://www.planboulder.org/boulder-election-2023",
        "Boulder Election 2023 — PLAN-Boulder County",
        2023,
    )
    appear(
        ev,
        2023,
        ["Nicole Speer", "Bob Yates", "Aaron Brockett", "Paul Tweedlie", "Taishya Adams", "Jacques Decalo"],
        (),
        "Named on PLAN-Boulder County's 2023 election page as Aug 23 attendees.",
    )
    ev, _ = add_event(
        "2023-plan-council-forum",
        "PLAN-Boulder County city council forum",
        "2023-08-29",
        None,
        orgs["plan"],
        "forum",
        None,
        "Same calendar night as the Chamber forum. PLAN's page names seven council candidates. Moderator Bill Briggs. Venue not stated. Silas Atkins is not named on either PLAN forum list — absence not independently confirmed.",
        "https://www.planboulder.org/boulder-election-2023",
        "Boulder Election 2023 — PLAN-Boulder County",
        2023,
    )
    appear(
        ev,
        2023,
        [
            "Tara Winer",
            "Terri Brncic",
            "Waylon Lewis",
            "Tina Marquis",
            "Ryan Schuchard",
            "Aaron Gabriel Neyer",
            "Jennifer Robins",
        ],
        (),
        "Named on PLAN-Boulder County's 2023 election page as Aug 29 attendees.",
    )
    add_event(
        "2023-kgnu-mayor-debate",
        "BRL–KGNU mayoral debate",
        "2023-10-18",
        None,
        orgs["brl"],
        "debate",
        None,
        "All four mayoral candidates. Mentioned in BRL's Oct 27 2023 'who’s running' photo caption. Recording not independently located in this pass.",
        "https://boulderreportinglab.org/2023/10/27/whos-running-for-boulder-mayor-city-council-in-the-2023-election/",
        "Who’s running for Boulder mayor, City Council in the 2023 election (BRL)",
        2023,
    )
    add_event(
        "2023-climate-mayor-forum",
        "Climate-focused Boulder mayoral forum",
        "2023-10-05",
        None,
        None,
        "forum",
        None,
        "BRL Oct 6 2023: Xcel Energy was a central subject. Date is the day before the article.",
        "https://boulderreportinglab.org/2023/10/06/climate-focused-boulder-mayoral-forum-puts-the-heat-on-xcel-energy/",
        "Climate-focused Boulder mayoral forum puts the heat on Xcel Energy (BRL)",
        2023,
    )

    # LWV forums — City of Boulder Channel 8 recorded them; YouTube is the record.
    add_source(
        "https://www.youtube.com/watch?v=Xb83hgpphXo",
        "2023 League of Women Voters Candidate Forum (City of Boulder / Channel 8)",
        "video",
        2023,
        orgs["lwv"] if "lwv" in orgs else None,
        "2023-10-15",
        "Live recording. Council race. Co-sponsored with EFAA. Published Oct 15 2023 on the city's YouTube.",
    )
    add_event(
        "2023-lwv-council-forum",
        "League of Women Voters city council candidate forum",
        "2023-10-15",
        "City Council Chambers, Penfield Tate II Municipal Building",
        orgs["lwv"] if "lwv" in orgs else None,
        "forum",
        "https://www.youtube.com/watch?v=Xb83hgpphXo",
        "Co-sponsored with EFAA. City Channel 8 recording, 1h35. Attendance not copied name-by-name in this pass — the video is the source.",
        "https://www.youtube.com/watch?v=Xb83hgpphXo",
        "2023 League of Women Voters Candidate Forum",
        2023,
    )
    add_source(
        "https://www.youtube.com/watch?v=n89j6Wk-qc8",
        "2023 League of Women Voters Mayoral Candidate Forum (City of Boulder / Channel 8)",
        "video",
        2023,
        orgs["lwv"] if "lwv" in orgs else None,
        "2023-10-22",
        "Live recording of the mayoral forum. All four 2023 mayoral candidates appear in the transcript.",
    )
    ev, _ = add_event(
        "2023-lwv-mayor-forum",
        "League of Women Voters mayoral candidate forum",
        "2023-10-22",
        "City Council Chambers, Penfield Tate II Municipal Building",
        orgs["lwv"] if "lwv" in orgs else None,
        "forum",
        "https://www.youtube.com/watch?v=n89j6Wk-qc8",
        "Co-sponsored with EFAA. City Channel 8 recording. Transcript names Brockett, Speer, Tweedlie, and Yates.",
        "https://www.youtube.com/watch?v=n89j6Wk-qc8",
        "2023 League of Women Voters Mayoral Candidate Forum",
        2023,
    )
    appear(
        ev,
        2023,
        ["Aaron Brockett", "Nicole Speer", "Paul Tweedlie", "Bob Yates"],
        (),
        "Named in the City of Boulder YouTube auto-transcript of the Oct 22 2023 LWV mayoral forum.",
    )

    add_source(
        "https://lwvbc.clubexpress.com/content.aspx?page_id=4091&club_id=629866&item_id=2716057",
        "Boulder City Council Candidate Forum — League of Women Voters of Boulder County (event page)",
        "official",
        2025,
        orgs["lwv"] if "lwv" in orgs else None,
        "2025-09-27",
        "Sat Sept 27 2025, 10:00–11:30am, Council Chambers. Co-sponsor EFAA. Live on Boulder 8 / Comcast 880.",
    )
    add_source(
        "https://www.youtube.com/watch?v=JcJu9nd5mQk",
        "2025 League of Women Voters of Boulder County Council Candidate Forum (City of Boulder / Channel 8)",
        "video",
        2025,
        orgs["lwv"] if "lwv" in orgs else None,
        "2025-09-29",
        "Recording of the Sept 27 forum. Moderator states 8 of 11 certified candidates participated; all were invited. Name-by-name attendance not copied in this pass.",
    )
    add_event(
        "2025-lwv-council-forum",
        "League of Women Voters city council candidate forum",
        "2025-09-27",
        "City Council Chambers, Penfield Tate II Municipal Building, 1777 Broadway",
        orgs["lwv"] if "lwv" in orgs else None,
        "forum",
        "https://www.youtube.com/watch?v=JcJu9nd5mQk",
        "Co-sponsored with EFAA. 10:00–11:30am. Moderator (Josephine Porter, on the recording): 11 on the ballot, 8 able to participate, all invited. Questions from audience cards plus electronic submissions. Name-by-name list not copied here; watch the video.",
        "https://lwvbc.clubexpress.com/content.aspx?page_id=4091&club_id=629866&item_id=2716057",
        "Boulder City Council Candidate Forum — LWVBC event page",
        2025,
    )

    # 2021 forums
    add_event(
        "2021-chamber-forum",
        "Boulder Chamber City Council Candidate Forum",
        "2021-08-26",
        None,
        orgs["chamber"],
        "forum",
        "https://www.youtube.com/watch?v=HfwfRrALpTk",
        "Chamber YouTube title: 2021 Boulder City Council Candidate Forum. 1h55. CU South annexation was among the questions. Full attendance not copied name-by-name from the tape in this pass.",
        "https://www.youtube.com/watch?v=HfwfRrALpTk",
        "2021 Boulder City Council Candidate Forum (Boulder Chamber)",
        2021,
    )
    ev, _ = add_event(
        "2021-cycling-forum",
        "Cycling-themed City Council candidate forum",
        "2021-10-26",
        "virtual",
        None,
        "forum",
        None,
        "Hosted by Boulder Mountainbike Alliance, Community Cycles, and Cyclists 4 Community. Daily Camera: 150+ registered. Right-turn-on-red and bike theft were asked.",
        "https://www.dailycamera.com/2021/10/26/area-bicycle-organizations-host-inaugural-cycling-themed-city-council-candidate-forum/",
        "Area bicycle organizations host inaugural cycling-themed City Council candidate forum (Daily Camera)",
        2021,
    )
    appear(
        ev,
        2021,
        [
            "Tara Winer",
            "Matt Benjamin",
            "Nicole Speer",
            "Jacques Decalo",
            "Michael Christy",
            "Lauren Folkerts",
            "David Takahashi",
            "Dan Williams",
            "Steve Rosenblum",
        ],
        ["Mark Wallach"],
        "Daily Camera Oct 26 2021. Wallach had a conflicting council meeting.",
    )
    add_event(
        "2021-raucous-caucus",
        "Boulder Progressives Raucous Caucus (2021)",
        "2021-06-24",
        None,
        orgs["progressives"],
        "caucus",
        None,
        "Boulder Beat: at least 12 people vying for five seats. Early-cycle look; full roster not copied here.",
        "https://boulderbeat.news/2021/06/24/slightly-less-raucous-caucus-offers-look-at-potential-council-candidates/",
        "Slightly less Raucous Caucus offers look at potential council candidates (Boulder Beat)",
        2021,
    )

    # 2017 LWV — recording exists; do not invent a complete attendance list from snippets.
    add_event(
        "2017-lwv-council-forum",
        "League of Women Voters city council candidate forum",
        "2017-10-14",
        None,
        orgs["lwv"] if "lwv" in orgs else None,
        "forum",
        "https://www.youtube.com/watch?v=x18o4Ke4gvc",
        "YouTube title: Boulder City Council Candidate Forum Presented by The League of Women Voters. Published Oct 14 2017. Name-by-name attendance not copied from the tape in this pass — the video is the source.",
        "https://www.youtube.com/watch?v=x18o4Ke4gvc",
        "Boulder City Council Candidate Forum Presented by The League of Women Voters (2017)",
        2017,
    )

    add_event(
        "2025-arts-forum",
        "Boulder City Council Candidates Forum on the Arts",
        "2025-09-30",
        "Boulder Chamber, 2440 Pearl St., Boulder",
        orgs["chamber"],
        "forum",
        "https://www.youtube.com/watch?v=VHJFiM-Skh8",
        "Presented by Boulder County Arts Alliance, Create Boulder, and the Boulder Chamber. 5–7pm. Full recording split into three videos (YouTube playlist). Attendance not copied name-by-name in this pass.",
        "https://www.youtube.com/watch?v=VHJFiM-Skh8",
        "(Part 1/3) 2025 Boulder City Council Candidates Forum on the Arts",
        2025,
    )
    add_source(
        "https://www.youtube.com/playlist?list=PL28uLDYXI7hJ8dJGKAObgFccqnPVni6Pp",
        "2025 Boulder City Council Candidates Forum on the Arts (playlist)",
        "video",
        2025,
        orgs["chamber"],
        "2025-09-30",
        "Three-part recording. Parts: VHJFiM-Skh8, i6fIxjQFTLU, rVI1skKxKII.",
    )

    add_source(
        "https://www.planboulder.org/2025-city-council-candidates-forum",
        "2025 City Council Candidates Forum — PLAN-Boulder County",
        "article",
        2025,
        orgs["plan"],
        "2025-09-12",
        "PLAN post with the YouTube embed of the Sept 8 VOTES! collaborative forum.",
    )
    add_source(
        "https://www.planboulder.org/2025-mayor-and-city-council-candidate-endorsements",
        "2025 City Council Candidate Endorsements — PLAN-Boulder County",
        "article",
        2025,
        orgs["plan"],
        "2025-09-23",
        "Says the board evaluated candidates’ responses to the PLAN-Boulder questionnaire after the collaborative forum. Full questionnaire dump not independently published on this page.",
    )
    add_source(
        "https://www.boulderchamber.com/assets/pdf/2025-BCC_BallotScorecard-ExtendedResponses-FNL",
        "2025 Boulder Chamber ballot scorecard — extended candidate responses",
        "questionnaire",
        2025,
        orgs["chamber"],
        None,
        "Chamber sent written questions to 2025 council candidates and published extended responses as a PDF. Not ingested as scored stances here — the PDF is the source.",
    )
    add_source(
        "https://www.youtube.com/watch?v=XwVdRqEJkgE",
        "2025 City Council Candidate Scorecard (Boulder Chamber)",
        "video",
        2025,
        orgs["chamber"],
        "2025-10-03",
        "Chamber video announcing the 2025 candidate scorecard. Extended written answers are in the PDF, not this clip.",
    )
    add_source(
        "https://www.openboulder.org/Resources",
        "2025 Voting Resources — Open Boulder",
        "questionnaire",
        2025,
        orgs.get("open"),
        None,
        "Heading: 2025 City Council Candidate Questionnaire Responses. Individual PDFs are linked from this page /s/ paths.",
    )
    for person, fname in [
        ("Mark Wallach", "Wallach.pdf"),
        ("Matt Benjamin", "Benjamin.pdf"),
        ("Jennifer Robins", "Robins.pdf"),
        ("Rob Kaplan", "Kaplan.pdf"),
        ("Lauren Folkerts", "Folkerts.pdf"),
        ("Nicole Speer", "Speer.pdf"),
        ("Rachel Rose Isaacson", "Isaacson.pdf"),
        ("Maxwell Lord", "Lord.pdf"),
    ]:
        add_source(
            f"https://www.openboulder.org/s/{fname}",
            f"Open Boulder 2025 candidate questionnaire — {person}",
            "questionnaire",
            2025,
            orgs.get("open"),
            None,
            "Written answers hosted on Open Boulder. Smoke, Stone, and Palacios PDFs were not at the same /s/ path in this pass.",
        )
    add_source(
        "https://archives.boulderweekly.com/content-archives/voters-guide/2023-boulder-city-council-candidate-questionnaires/",
        "2023 Boulder City Council Candidate Questionnaires — Boulder Weekly",
        "questionnaire",
        2023,
        orgs.get("weekly"),
        "2023-10-04",
        "Per-candidate questionnaire pages. Index only catalogued this pass; verbatim not copied into answers.",
    )
    add_source(
        "https://bouldercolorado.gov/2025-city-council-candidate-videos",
        "2025 City Council Candidate Videos | City of Boulder",
        "video",
        2025,
        orgs.get("city"),
        None,
        "City-hosted three-minute videos, ballot order. This box received 403 fetching the page; the URL is the city’s published path.",
    )


def ingest_measures(cur, *, add_source, org_city: int, org_brl: int, org_camera: int, e2017: int, e2019: int, e2021: int, e2023: int, e2025: int, e2026: int) -> None:
    s_2017_enr = _ensure_source(
        cur,
        add_source,
        "https://electionresults.bouldercounty.gov/ElectionResults2017C/",
        "Boulder County 2017 Coordinated Election official results (ENR)",
        "results",
        2017,
        None,
        "2017-11-21",
        "Official results last updated 11/21/2017 4:23 PM.",
    )
    for slug, letter, title, kind, status, summary, yes, no, notes in [
        (
            "2017-2l-uot",
            "2L",
            "Utility occupation tax increase and extension",
            "tax",
            "passed",
            "Continued funding for the city’s municipal-electric-utility effort (separation from Xcel). City-level certified yes 51.70%.",
            15852,
            14807,
            "Certified ENR. 51.70% yes.",
        ),
        (
            "2017-2m-cip-tax",
            "2M",
            "0.3 cents capital improvement tax extension",
            "tax",
            "passed",
            "Extends the 0.3-cent capital improvement sales tax for city and nonprofit capital projects.",
            25438,
            5417,
            "Certified ENR. 82.44% yes.",
        ),
        (
            "2017-2n-cip-debt",
            "2N",
            "Debt authority for capital improvement tax",
            "bond",
            "passed",
            "Authorizes city debt paid from the 2M capital-improvement tax.",
            21433,
            8280,
            "Certified ENR. 72.13% yes.",
        ),
        (
            "2017-2o-muni-go-nogo",
            "2O",
            "Charter requirement for a vote before electric-construction debt",
            "charter",
            "passed",
            "Requires another citizen vote before Boulder issues debt to build a municipal electric utility.",
            24423,
            5084,
            "Certified ENR. 82.77% yes.",
        ),
        (
            "2017-2p-muni-executive-session",
            "2P",
            "Charter provision allowing executive sessions for municipalization",
            "charter",
            "failed",
            "Would have allowed executive sessions on municipalization negotiations. Voters rejected it.",
            12534,
            16286,
            "Certified ENR. Failed. 43.49% yes.",
        ),
        (
            "2017-2q-charter-cleanup",
            "2Q",
            "Charter clean-up",
            "charter",
            "passed",
            "Administrative charter clean-up on the 2017 city ballot.",
            19400,
            9014,
            "Certified ENR. 68.28% yes.",
        ),
    ]:
        cur.execute(
            """INSERT INTO measures
               (slug, election_id, letter, title, kind, status, summary, ballot_language, source_id, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (slug, e2017, letter, title, kind, status, summary, None, s_2017_enr, notes),
        )
        mid = cur.lastrowid
        cur.execute(
            """INSERT INTO measure_results (measure_id, yes_votes, no_votes, passed, source_id, notes)
               VALUES (?,?,?,?,?,?)""",
            (mid, yes, no, 1 if status == "passed" else 0, s_2017_enr, "Official ENR 11/21/2017."),
        )

    s_2019_enr = _ensure_source(
        cur,
        add_source,
        "https://electionresults.bouldercounty.gov/ElectionResults2019C/",
        "Boulder County 2019 Coordinated Election official results (ENR)",
        "results",
        2019,
        None,
        "2019-11-14",
        "Official results last updated 11/14/2019 4:35 PM.",
    )
    for slug, letter, title, kind, status, summary, yes, no, notes in [
        (
            "2019-2g-vape-tax",
            "2G",
            "Tax on tobacco vaping products",
            "tax",
            "passed",
            "Sales and use tax of up to 40% of the retail price of electronic smoking devices, first-year increase $2.5 million, for licensing, health promotion, and general city services.",
            27159,
            6930,
            "Certified ENR. 79.67% yes.",
        ),
        (
            "2019-2h-open-space-longs",
            "2H",
            "Sales and use tax extension for open space and Long’s Gardens",
            "tax",
            "passed",
            "Extends the existing 0.15-cent transportation sales tax to Dec 31 2039 and redirects it to open-space maintenance, restoration, acquisition, and preservation, including a first-year conservation easement at Long’s Gardens, 3240 Broadway.",
            29450,
            4867,
            "Certified ENR. 85.82% yes.",
        ),
        (
            "2019-2i-middle-income-housing",
            "2I",
            "Middle-income housing program",
            "bond",
            "passed",
            "Authorizes up to $10 million of city debt (maximum repayment $15 million), without raising taxes, for permanently affordable deed restrictions and loans to middle-income households buying homes in Boulder.",
            23358,
            10386,
            "Certified ENR. 69.22% yes.",
        ),
    ]:
        cur.execute(
            """INSERT INTO measures
               (slug, election_id, letter, title, kind, status, summary, ballot_language, source_id, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (slug, e2019, letter, title, kind, status, summary, None, s_2019_enr, notes),
        )
        mid = cur.lastrowid
        cur.execute(
            """INSERT INTO measure_results (measure_id, yes_votes, no_votes, passed, source_id, notes)
               VALUES (?,?,?,?,?,?)""",
            (mid, yes, no, 1, s_2019_enr, "Official ENR 11/14/2019."),
        )

    s_2021_sov = _ensure_source(
        cur,
        add_source,
        "https://assets.bouldercounty.gov/wp-content/uploads/2021/11/2021-Boulder-County-Coordinated-Election-Official-Summary-of-Votes.pdf",
        "2021 Coordinated Election — Official Summary of Votes",
        "results",
        2021,
        None,
        "2021-11-22",
        "Certified city measure totals.",
    )
    s_2021_city = _ensure_source(
        cur,
        add_source,
        "https://bouldercolorado.gov/news/city-boulder-november-2021-election-results",
        "City of Boulder November 2021 Election Results",
        "official",
        2021,
        org_city,
        None,
        "Unofficial night-of numbers that match the certified SOV for the contests we store.",
    )
    for slug, letter, title, kind, status, summary, yes, no, notes in [
        (
            "2021-2i-ccrs-extension",
            "2I",
            "Community, Culture, Resilience and Safety tax extension",
            "tax",
            "passed",
            "Extends the 0.3% CCRS sales and use tax from Dec 31 2021 to Dec 31 2036 without raising the rate, for capital projects.",
            27904,
            4421,
            "Certified. 86.32% yes.",
        ),
        (
            "2021-2j-ccrs-bonds",
            "2J",
            "CCRS bond issuance",
            "bond",
            "passed",
            "Bonds paid from the 2I tax extension.",
            25406,
            6159,
            "Certified. 80.49% yes.",
        ),
        (
            "2021-300-bedrooms",
            "300",
            "Bedrooms Are For People (occupancy limits)",
            "other",
            "failed",
            "Would have allowed occupancy of unrelated adults equal to legal bedrooms plus one, if health and safety codes were met. Replaced the citywide cap of 3 (or 4 in some areas).",
            15756,
            17296,
            "Citizen initiative. Failed. Certified 47.67% yes.",
        ),
        (
            "2021-301-fur-ban",
            "301",
            "Humane Clothing Act (fur sale ban)",
            "other",
            "passed",
            "Prohibits sale and manufacture for sale of certain fur products, with exemptions.",
            16163,
            15523,
            "Certified. 51.01% yes.",
        ),
        (
            "2021-302-cu-south",
            "302",
            "Let the Voters Decide on Annexation of CU South",
            "other",
            "failed",
            "Would have required voter approval of any CU South annexation agreement before city utilities (other than flood control) could be provided.",
            13871,
            18224,
            "Citizen initiative. Failed. Certified 43.22% yes.",
        ),
    ]:
        cur.execute(
            """INSERT INTO measures
               (slug, election_id, letter, title, kind, status, summary, ballot_language, source_id, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (slug, e2021, letter, title, kind, status, summary, None, s_2021_sov, notes),
        )
        mid = cur.lastrowid
        passed = 1 if status == "passed" else 0
        cur.execute(
            """INSERT INTO measure_results (measure_id, yes_votes, no_votes, passed, source_id, notes)
               VALUES (?,?,?,?,?,?)""",
            (mid, yes, no, passed, s_2021_sov, "Official Summary of Votes."),
        )

    s_city_2026 = _ensure_source(
        cur,
        add_source,
        "https://bouldercolorado.gov/2026-city-boulder-ballot-measures",
        "2026 City of Boulder Ballot Measures",
        "official",
        2026,
        org_city,
        "2026-08-21",
        "City guide. Ballot letters not yet assigned. TABOR pro/con deadline Sept 18 2026.",
    )
    s_brl_ref = add_source(
        "https://boulderreportinglab.org/2026/08/06/boulder-city-council-sends-vacancy-tax-and-400-million-bond-to-november-ballot-rejects-downtown-development-authority/",
        "Council sends vacancy tax and $400 million bond to November ballot, rejects DDA (BRL)",
        "article",
        2026,
        org_brl,
        "2026-08-06",
        "Referral night. DDA 4–4 fail. Bond unanimous. Vacancy tax 7–1 (Speer no). Companion debt-limit charter referred. Firefighters CBA also referred.",
    )
    add_source(
        "https://www.dailycamera.com/2026/08/07/boulder-tax-measures-ballot/",
        "Boulder voters to decide on vacancy tax, $400 million infrastructure bond (Daily Camera)",
        "article",
        2026,
        org_camera,
        "2026-08-07",
        "Vacancy tax 7–1 Speer dissenting (wanted a fee). Bond unanimous.",
    )
    add_source(
        "https://www.dailycamera.com/2026/08/11/boulder-firefighters-union-ballot/",
        "Boulder firefighters could have their collective bargaining rights secured in November (Daily Camera)",
        "article",
        2026,
        org_camera,
        "2026-08-11",
        "Unanimous referral of charter Sec. 73. Impasse: non-binding factfinding then city vote. No strike.",
    )

    measures = [
        (
            "2026-rec-safety-bond",
            e2026,
            None,
            "Building Boulder Together: Recreation and Safety Bond",
            "bond",
            "referred",
            "Authorizes up to $400 million of general-obligation debt (maximum repayment cost $650 million) repaid by a new property tax, up to $32.5 million a year. City example: about $400 a year on a $1 million home if the full amount is bonded. Intended projects: South Boulder Rec Center (incl. lap pool), North Boulder Rec Center + West Age Well, Fire Stations 1 and 5, Public Safety Building / 911, Penfield Tate II, Municipal Services Center. When the debt is paid, the extra tax ends.",
            "Shall City of Boulder debt be increased up to $400,000,000, with a maximum repayment cost up to $650,000,000, and shall city taxes be increased up to $32,500,000 annually … (full TABOR language on the city page).",
            s_city_2026,
            "Referred unanimously Aug 6 2026. Project list is what the city intends; BRL notes the list is not binding.",
        ),
        (
            "2026-debt-limit-charter",
            e2026,
            None,
            "Charter debt-limit calculation (actual vs. assessed value)",
            "charter",
            "referred",
            "Amends Charter §97 so the city’s debt limit is 3% of the actual value of taxable property, not the assessed value. City says this matches how most Colorado municipalities and the state calculate the cap, and would allow more debt than the current formula.",
            "Shall Section 97 of the Boulder Home Rule Charter be amended pursuant to Ordinance 8762 to modify the City’s debt limitation to be not more than three percent of the actual value of the taxable property within the City?",
            s_city_2026,
            "Companion to the rec/safety bond. Referred Aug 6 2026 (BRL).",
        ),
        (
            "2026-vacancy-excise-tax",
            e2026,
            None,
            "Vacancy excise tax",
            "tax",
            "referred",
            "About $4,000 a year on a residential property occupied 183 days or fewer, CPI-adjusted, never below $4,000, never above $7,000. Estimated $6 million in 2028, the first full collection year. Revenue is general city services (police, fire, parks, transportation), not a dedicated housing fund. Goal stated by proponents: push empty second homes onto the rental or sale market.",
            "Shall the City of Boulder taxes be increased $6,000,000 annually … by imposing a $4,000 tax on vacant homes that are occupied for 183 days or less per year …",
            s_city_2026,
            "Referred 7–1 Aug 6 2026. Speer voted no; she wanted a fee rather than a tax (Daily Camera Aug 7).",
        ),
        (
            "2026-firefighter-cba-charter",
            e2026,
            None,
            "Collective bargaining for firefighters (new Charter §73)",
            "charter",
            "referred",
            "Moves full-time firefighters’ collective-bargaining rights from contract/ordinance into the charter. Bargain over safety, wages, benefits, and terms of employment except reserved management rights. Impasse: non-binding factfinding, then if needed a vote of city electors. Strikes / work stoppages prohibited. Current CBA runs through 2027.",
            "Shall the city amend its charter by the addition of a new Sec. 73, “Collective Bargaining for Firefighters,” as described in Ordinance 8761 …",
            s_city_2026,
            "Referred unanimously (Daily Camera Aug 11 2026).",
        ),
        (
            "2026-dda",
            e2026,
            None,
            "Downtown Development Authority referral",
            "other",
            "not_referred",
            "Would have asked district electors (residents, property owners, qualified business tenants inside a downtown / Civic Area / University Hill boundary — city estimated ~2,500 electors) to form a 30-year DDA with tax-increment financing. Not a citywide vote.",
            None,
            s_brl_ref,
            "Failed 4–4 Aug 6 2026; a tie cannot refer. BRL named the four no votes: Adams, Marquis, Schuchard, Speer. The four yes votes are the other sitting members that night (Brockett, Winer, Benjamin, Kaplan) — inferred from the eight-member dais after Wallach’s resignation, not from a roll-call PDF. Staff directed to keep exploring a DDA.",
        ),
    ]
    for slug, eid, letter, title, kind, status, summary, language, src, notes in measures:
        cur.execute(
            """INSERT INTO measures
               (slug, election_id, letter, title, kind, status, summary, ballot_language, source_id, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (slug, eid, letter, title, kind, status, summary, language, src, notes),
        )

    s_2023_sov = _ensure_source(
        cur,
        add_source,
        "https://assets.bouldercounty.gov/wp-content/uploads/2023/11/2023C-Boulder-County-Official-Summary-of-Votes.pdf",
        "2023 Coordinated Election — Official Summary of Votes",
        "results",
        2023,
        None,
        "2023-11-29",
        "Certified city measure totals used here (2A, 2B, 302).",
    )
    s_2023_302 = _ensure_source(
        cur,
        add_source,
        "https://boulderreportinglab.org/2023/11/08/city-of-boulder-votes-to-pass-safe-zones-4-kids-ballot-measure/",
        "City of Boulder votes to pass Safe Zones 4 Kids ballot measure (BRL)",
        "article",
        2023,
        org_brl,
        "2023-11-08",
        "Question 302. Citizen initiative. ~61% yes.",
    )
    for slug, letter, title, kind, summary, language, yes, no, notes in [
        (
            "2023-2a-sales-tax-extension",
            "2A",
            "City sales and use tax extension",
            "tax",
            "Extends the existing 0.15% city sales and use tax from Dec 31 2024 to Dec 31 2044 without raising the rate. 50% general fund (fire, public safety, homeless services, etc.), 50% arts, culture, and heritage.",
            "WITHOUT RAISING ADDITIONAL TAXES, SHALL THE EXISTING 0.15 CENT CITY SALES AND USE TAX FOR GENERAL FUND PURPOSES … BE EXTENDED … UNTIL DECEMBER 31, 2044 …",
            24810,
            8473,
            "Certified official summary of votes. 74.54% yes.",
        ),
        (
            "2023-2b-charter-elections",
            "2B",
            "Elections administrative charter cleanup",
            "charter",
            "Amends charter sections 27, 37, 39, 46 and 57 on election administration: mayor/council petitions carried outside the municipal building, extra clerk processing time, and a clarification that state law governs charter amendments (PLAN-Boulder 2023 page).",
            None,
            26137,
            4153,
            "Certified official summary of votes. 86.29% yes (26,137 / 30,290).",
        ),
        (
            "2023-302-safe-zones-4-kids",
            "302",
            "Safe Zones 4 Kids",
            "other",
            "Citizen initiative. Amends city code §8-3-21 to prioritize removal of already-prohibited tents, temporary structures, and propane tanks within 500 feet of a school or 50 feet of a multi-use path or sidewalk.",
            "Shall Section 8-3-21, B.R.C. 1981, be amended to add a provision to prioritize removal of prohibited items, such as tents, temporary structures, or propane tanks, within five hundred feet of a school or fifty feet of any multi-use path or sidewalk pursuant to Ordinance 8586?",
            20261,
            12973,
            "Certified official summary of votes. 60.96% yes. Litmus-test issue of the 2023 council race (BRL).",
        ),
    ]:
        src = s_2023_302 if slug.endswith("302-safe-zones-4-kids") else s_2023_sov
        cur.execute(
            """INSERT INTO measures
               (slug, election_id, letter, title, kind, status, summary, ballot_language, source_id, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (slug, e2023, letter, title, kind, "passed", summary, language, src, notes),
        )
        mid = cur.lastrowid
        cur.execute(
            """INSERT INTO measure_results (measure_id, yes_votes, no_votes, passed, source_id, notes)
               VALUES (?,?,?,?,?,?)""",
            (mid, yes, no, 1, s_2023_sov, "Official Summary of Votes, Boulder County Clerk."),
        )

    s_2025_results = _ensure_source(
        cur,
        add_source,
        "https://boulderreportinglab.org/2025/11/06/boulder-2025-election-results-voters-reelect-three-incumbents-to-council-and-pass-all-tax-measures/",
        "Boulder 2025 election results (BRL)",
        "article",
        2025,
        org_brl,
        "2025-11-06",
        "2A CCRS extension and 2B CCRS debt both passed. County 1A/1B also passed.",
    )

    for slug, letter, title, kind, summary in [
        (
            "2025-2a-ccrs-extension",
            "2A",
            "Community, Culture, Resilience, and Safety (CCRS) tax extension",
            "tax",
            "Extends the existing 0.3% CCRS sales and use tax in perpetuity (it had been set to expire Dec 31 2036) without raising the rate. Funds capital work: rec centers, fire/police stations, paths, bridges, open space trailheads, etc.",
        ),
        (
            "2025-2b-ccrs-debt",
            "2B",
            "CCRS tax debt authorization",
            "bond",
            "Authorizes up to $262 million principal ($350 million maximum repayment) payable solely from the CCRS tax extension, if 2A also passed. Companion to 2A.",
        ),
    ]:
        cur.execute(
            """INSERT INTO measures
               (slug, election_id, letter, title, kind, status, summary, ballot_language, source_id, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (slug, e2025, letter, title, kind, "passed", summary, None, s_2025_results,
             "Passed Nov 4 2025 (BRL Nov 6). Yes/no vote totals not copied from the SOV in this pass."),
        )
        mid = cur.lastrowid
        cur.execute(
            """INSERT INTO measure_results (measure_id, yes_votes, no_votes, passed, source_id, notes)
               VALUES (?,?,?,?,?,?)""",
            (mid, None, None, 1, s_2025_results, "Certified as passed; raw yes/no not yet harvested from the county SOV."),
        )


FINANCE_HARVEST = Path(__file__).resolve().parent / "data" / "harvest" / "finance_2026.json"


def ingest_brl_2026_field(cur, *, pid: dict, add_source, org_brl: int, org_chamber: int, org_better: int) -> None:
    """BRL 19-candidate roundup (2026-08-30): bond stances, plus Chamber 2026 recording."""
    src = _ensure_source(
        cur,
        add_source,
        "https://boulderreportinglab.org/2026/08/30/meet-the-19-candidates-running-for-boulder-mayor-and-city-council-in-2026/",
        "Meet the 19 candidates running for Boulder mayor and City Council in 2026 (BRL)",
        "article",
        2026,
        org_brl,
        "2026-08-30",
        "Occupations, campaign sites, Boulder Progressives endorsements, and the $400 million bond divide. Lisa Ann Jacobs has no full BRL profile yet. Gilbert, Martus, and Goldstein are not named on the bond yes/no lists.",
    )
    cur.execute("INSERT OR IGNORE INTO issues (slug, name, description) VALUES (?,?,?)", (
        "bond",
        "Rec and safety bond",
        "The November 2026 $400 million general-obligation bond for rec centers and city facilities, repaid by a new property tax.",
    ))
    cur.execute(
        """INSERT INTO questions (prompt, issue_slug, year, kind, is_canonical)
           VALUES (?,?,?,?,1)""",
        (
            "Do you support the $400 million recreation and safety bond on the November 2026 ballot?",
            "bond",
            2026,
            "interview",
        ),
    )
    qid = cur.lastrowid
    # Earlier builds fanned BRL's group summary out into one yes/no per
    # candidate. A journalist's grouping is not each person's answer, and
    # "many challengers oppose" names no one. Keep it as BRL's own two lines,
    # attributed to BRL, and do not assign a stance to anyone from them.
    cur.execute("SELECT id FROM measures WHERE slug='2026-rec-safety-bond'")
    row = cur.fetchone()
    bond_mid = row[0] if row else None
    for text in (
        "All five incumbent candidates support the measure, citing more than $400 million in deferred "
        "maintenance; Sam Fuqua and Jamillah Richmond also support it.",
        "Many challengers oppose the measure, arguing voters have not received enough information about "
        "how the money would be spent.",
    ):
        cur.execute(
            """INSERT INTO reported_lines (question_id, measure_id, source_id, reporter, text, reported_on, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (qid, bond_mid, src, "Boulder Reporting Lab", text, "2026-08-30",
             "Journalist grouping (paraphrased). Not a per-candidate answer; no stance is recorded for any individual from this line."),
        )

    rec = "https://www.youtube.com/watch?v=rusBhvHOeCc"
    add_source(
        rec,
        "City Council Candidate Forum 2026 | Boulder Chamber",
        "video",
        2026,
        org_chamber,
        "2026-08-26",
        "Full Chamber forum at eTown. Camera (Aug 27) said 17 of 19 candidates appeared; name-by-name absences not copied here.",
    )
    cur.execute("SELECT id FROM events WHERE slug='2026-chamber-forum'")
    row = cur.fetchone()
    if row:
        cur.execute(
            """UPDATE events SET recording_url=?, notes=? WHERE id=?""",
            (
                rec,
                "Season-opener at eTown, 5–8pm. Camera Aug 27: 17 of 19 certified candidates. Topics: housing, transportation, public safety. Recording: Chamber YouTube.",
                row[0],
            ),
        )
    add_source(
        "https://www.dailycamera.com/2026/08/27/boulder-city-council-candidates-issues/",
        "Meet (most of) the people running for Boulder City Council and mayor (Daily Camera)",
        "article",
        2026,
        None,
        "2026-08-27",
        "Writeup of the Aug 26 Chamber forum. 17 of 19 present. Do not invent the two absences.",
    )
    cur.execute(
        """INSERT INTO events (slug, name, starts_on, venue, host_org_id, kind, recording_url, notes)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            "2026-votes-forum",
            "Collaborative City Council Candidate Forum 2026 (Open / Better / PLAN)",
            "2026-09-02",
            None,
            org_better,
            "forum",
            None,
            "Co-hosted by Open Boulder, Better Boulder, and PLAN-Boulder County. 5pm social, 6pm forum. Moderator: KC Becker. Registration closed as of the Better Boulder post. Recording not yet expected — event is Sept 2 2026.",
        ),
    )
    add_source(
        "https://betterboulder.com/collaborative-candidate-forum-2026/",
        "Collaborative Candidate Forum 2026 — Better Boulder",
        "article",
        2026,
        org_better,
        "2026-08-19",
        "Event page. First collaborative forum of the 2026 cycle (they started co-hosting in 2025).",
    )


def _finance_display_name(first: str | None, last: str | None) -> str:
    first = (first or "").strip()
    last = (last or "").strip()
    return " ".join(p for p in (first, last) if p) or "—"


def _donor_person_id(pid: dict, first: str | None, last: str | None) -> int | None:
    first = (first or "").strip()
    last = (last or "").strip()
    if not last:
        return None
    candidates = []
    if not first:
        return None
    candidates.append(f"{first} {last}")
    candidates.append(f"{last}, {first}")
    lower = {k.lower(): v for k, v in pid.items()}
    for name in candidates:
        hit = lower.get(name.lower())
        if hit:
            return hit
    return None


def ingest_finance_2026(cur, *, pid: dict, add_source, org_city: int) -> None:
    data = json.loads(FINANCE_HARVEST.read_text(encoding="utf-8"))
    src = _ensure_source(
        cur,
        add_source,
        data["summary_url"],
        data["summary_title"],
        "official",
        2026,
        org_city,
        data["retrieved_on"],
        data["notes"],
    )
    add_source(
        data["list_url"],
        "City of Boulder Election Committee Filings (live app)",
        "official",
        2026,
        org_city,
        None,
        "iframe behind bouldercolorado.gov/elections/election-committee-filings. Per-committee CandE statements are HTML, no JS required for the numbers.",
    )
    add_source(
        "https://documents.bouldercolorado.gov/WebLink/Browse.aspx?id=59131",
        "City of Boulder election records (Laserfiche)",
        "official",
        None,
        org_city,
        None,
        "Historical committee filings 2008–present. JS/cookie archive; listing not extracted this pass. 2026 dollars come from the live app, not here.",
    )
    for row in data["committees"]:
        person = row.get("person")
        if person and person not in pid:
            raise SystemExit(f"finance person not in seed: {person}")
        person_id = pid[person] if person else None
        candidacy_id = _cid(cur, person, 2026) if person else None
        loan_total = sum(
            c["amount"] for c in row.get("contributions", []) if (c.get("contrib_type") or "").lower() == "loan"
        )
        notes = None
        if not person and row.get("kind") == "official_candidate":
            notes = "Official committee on the clerk app; not on the certified 2026 candidate list."
        elif loan_total:
            notes = f"Clerk contribution total includes ${loan_total:,.2f} in loans."
        cur.execute(
            """INSERT INTO finance_snapshots
               (person_id, candidacy_id, year, committee_name, committee_number, clerk_committee_id,
                committee_kind, contributions, expenditures, matching_received, in_kind, cash_on_hand,
                reported_on, reports_url, source_id, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                person_id,
                candidacy_id,
                2026,
                row["committee_name"],
                row.get("committee_number"),
                row.get("committee_id"),
                row.get("kind") or "official_candidate",
                row.get("contributions_total") or 0,
                row.get("expenditures_total") or 0,
                row.get("matching_received") or 0,
                row.get("in_kind"),
                row.get("cash_on_hand"),
                row.get("reported_on"),
                row.get("reports_url"),
                src,
                notes,
            ),
        )
        snap_id = cur.lastrowid
        fallback_url = (row.get("statements") or [{}])[-1].get("url") if row.get("statements") else row.get("reports_url")
        for item in row.get("contributions", []):
            display = _finance_display_name(item.get("first_name"), item.get("last_name"))
            cur.execute(
                """INSERT INTO finance_line_items
                   (snapshot_id, person_id, donor_person_id, year, direction, last_name, first_name,
                    display_name, item_type, purpose, from_candidate, occurred_on, amount, match_amount,
                    clerk_item_id, statement_id, statement_url, source_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    snap_id,
                    person_id,
                    _donor_person_id(pid, item.get("first_name"), item.get("last_name")),
                    2026,
                    "contribution",
                    item.get("last_name") or "",
                    item.get("first_name") or "",
                    display,
                    item.get("contrib_type") or "Monetary",
                    None,
                    1 if item.get("from_candidate") else 0,
                    item.get("occurred_on"),
                    item.get("amount") or 0,
                    item.get("match_amount"),
                    item.get("clerk_item_id"),
                    None,
                    fallback_url,
                    src,
                ),
            )
        for item in row.get("expenditures", []):
            display = _finance_display_name(item.get("first_name"), item.get("last_name"))
            cur.execute(
                """INSERT INTO finance_line_items
                   (snapshot_id, person_id, donor_person_id, year, direction, last_name, first_name,
                    display_name, item_type, purpose, from_candidate, occurred_on, amount, match_amount,
                    clerk_item_id, statement_id, statement_url, source_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    snap_id,
                    person_id,
                    None,
                    2026,
                    "expenditure",
                    item.get("last_name") or "",
                    item.get("first_name") or "",
                    display,
                    None,
                    item.get("purpose") or "",
                    0,
                    item.get("occurred_on"),
                    item.get("amount") or 0,
                    None,
                    item.get("clerk_item_id"),
                    None,
                    fallback_url,
                    src,
                ),
            )
