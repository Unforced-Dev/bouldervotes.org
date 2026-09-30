"""Machine-readable layer for AI assistants and scripts (static only).

Writes, from the same SQLite database as the HTML:
  docs/llms.txt            index in the llms.txt convention (https://llmstxt.org)
  docs/llms-full.txt       the whole 2026 guide as one markdown file
  docs/api/v1/*.json       a tiny read-only JSON "API" (plain files)
  docs/api/index.html      human documentation for the above
  docs/robots.txt, docs/sitemap.xml

Trust rules carry over: quotes verbatim, every record carries its source URL,
held items are never exported, campaign claims keep the "X campaign lists Y"
label, candidates are listed in official ballot order, nothing is scored.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
from pathlib import Path

from build_2026 import KEY_DATES, KEY_DATES_URL, first_sentence
from build_forums_2026 import MEDIUM_CAVEAT, TRANSCRIPT_NOTE, ts

ROOT = Path(__file__).resolve().parent
SITE = "https://bouldervotes.org"
SCHEMA_VERSION = "1.0"
H2026 = ROOT / "data" / "harvest" / "2026"

AI_PROMPT = ("Help me understand my ballot for the November 3, 2026 Boulder city election. "
             "Start by reading https://bouldervotes.org/llms.txt and follow its instructions. "
             "Ask me what matters to me, then show me where each candidate and measure stands, with links to the sources.")
AI_SHORT = "Help me vote in the Boulder city election using bouldervotes.org/llms.txt"
AI_CAUTION = "AI assistants can get things wrong. Every claim on this site links to its source, so check the links."

# Rules for assistants. Tests keep recommendation phrasing out of this block.
AI_RULES = """\
- Be nonpartisan. Present every candidate and measure the same way, in ballot order.
- Do not tell the user how to vote. Only if the user states their own values and asks for help matching them, show which candidates' or measures' sourced positions line up with those values, quote them, and say that the choice is the user's.
- Cite as you go: link the bouldervotes.org page and the original source URL for every claim.
- Quotes are verbatim. Do not paraphrase inside quotation marks.
- Keep the labels. "X campaign lists Y" means only the campaign says so. Forum quotes come from automatic transcripts; link the timestamp. Some speakers were identified from speaking order, and those carry a caveat; repeat it.
- Silence is not a position. "No endorsements on file" is not opposition, and a missing quote says nothing about a candidate's view.
- Respect "as of" dates. Money and endorsements change; tell the user the date of the figure.
- This guide covers only City of Boulder races. For county, state, school board or regional items, send the user to Boulder County Elections: https://bouldercounty.gov/elections/
- Voting rules and deadlines come from Boulder County Elections. When in doubt, link https://bouldercounty.gov/elections/information/"""

def feedback_md() -> list[str]:
    """How assistants (and people) send corrections. Endpoint from build.FEEDBACK_API."""
    from build import FEEDBACK_API, FEEDBACK_URL  # late import: build.py imports this module
    return [
        "## Send feedback or corrections (AI assistants welcome)",
        "",
        f"If you find a factual error on this site, or the user asks you to pass on a correction or idea, POST JSON to {FEEDBACK_API}",
        "",
        "- Only submit when the user asks you to, or when you find a factual error and can cite a source for it.",
        "- Set submitter_type to \"ai-agent\" and agent_name to your name (for example \"ChatGPT\" or \"Claude\").",
        "- Set on_behalf_of_user to true when you are relaying the user's own report.",
        "- For a correction, include source_url: a link to the document that shows the right fact.",
        "- Don't include the user's personal details unless they ask you to pass on a way to reach them (the contact field).",
        "- A person reads every note. Corrections are checked against sources before anything changes. Notes are never published.",
        "",
        "Fields: kind (\"correction\", \"suggestion\" or \"other\"; required), message (10 to 4000 characters; required), "
        "page_url (the bouldervotes.org page it is about), source_url, contact (at most 200 characters), "
        "submitter_type (\"person\" or \"ai-agent\"), agent_name, on_behalf_of_user (true or false). "
        "The reply is JSON: {\"ok\": true, \"id\": 123}, or {\"ok\": false, \"error\": \"...\"}. "
        f"Limit: 5 notes per hour per sender. Field list as JSON: {FEEDBACK_API}/schema",
        "",
        "```",
        f"curl -X POST {FEEDBACK_API} \\",
        "  -H 'Content-Type: application/json' \\",
        "  -d '{\"kind\": \"correction\", \"page_url\": \"https://bouldervotes.org/2026.html\", "
        "\"message\": \"What is wrong, and what the source says instead.\", "
        "\"source_url\": \"https://example.org/the-source\", \"submitter_type\": \"ai-agent\", "
        "\"agent_name\": \"Claude\", \"on_behalf_of_user\": true}'",
        "```",
        "",
        f"People can use the form at {u('feedback.html')}",
        "",
    ]


PROV_LABEL = {
    "endorser_statement": "Endorser's own statement",
    "filing": "City filing",
    "news_report": "News listing",
    "campaign_claim": "Campaign claim",
}


def today() -> dt.date:
    return dt.date.fromisoformat(os.environ.get("BV_TODAY") or dt.date.today().isoformat())


def u(path: str) -> str:
    return f"{SITE}/{path.lstrip('/')}"


def clean(s):
    return " ".join(str(s).split()) if s is not None else None


# ---------------------------------------------------------------- collect
def collect(con: sqlite3.Connection, forums) -> dict:
    q = con.execute
    order = json.loads((H2026 / "ballot_order.json").read_text(encoding="utf-8"))

    def src(sid):
        r = q("SELECT url FROM sources WHERE id=?", (sid,)).fetchone() if sid else None
        return r[0] if r else None

    def prov_text(e) -> str:
        who = e["org_name"] or e["person_name"]
        if e["provenance"] == "campaign_claim":
            claimer = (e["claimed_by"] or "Campaign").removesuffix(" campaign").replace(" (ballot campaign)", " ballot")
            return f"{claimer} campaign lists {who}. Only the campaign says so."
        if e["provenance"] == "news_report":
            return f"News listing: {e['claimed_by']} lists {who}. We didn't find the endorser's own statement."
        if e["provenance"] == "filing":
            return "City filing: a committee registration with the city clerk names this."
        return "Endorser's own statement."

    edges = q("""SELECT e.*, s.url AS source_url, s.title AS source_title,
                        o.slug AS org_slug, o.name AS org_name,
                        p.slug AS person_slug, p.full_name AS person_name, pt.title AS person_title,
                        pt.weight_group, tp.slug AS cand_slug, tp.full_name AS cand_name, ofc.slug AS cand_office,
                        m.letter AS m_letter
                 FROM endorsements e JOIN sources s ON s.id=e.source_id
                 LEFT JOIN organizations o ON o.id=e.endorser_org_id
                 LEFT JOIN people p ON p.id=e.endorser_person_id
                 LEFT JOIN person_titles pt ON pt.person_id=p.id
                 LEFT JOIN candidacies c ON c.id=e.candidacy_id
                 LEFT JOIN people tp ON tp.id=c.person_id
                 LEFT JOIN races r ON r.id=c.race_id LEFT JOIN offices ofc ON ofc.id=r.office_id
                 LEFT JOIN measures m ON m.id=e.measure_id
                 WHERE e.status='published'
                 ORDER BY e.candidacy_id IS NULL, COALESCE(e.rank, 9), COALESCE(o.name, p.sort_name), e.id""").fetchall()
    endorsements = []
    for e in edges:
        if e["candidacy_id"]:
            target = {"type": "candidate", "slug": e["cand_slug"], "name": e["cand_name"], "office": e["cand_office"]}
        elif e["measure_id"]:
            target = {"type": "city_measure", "letter": e["m_letter"]}
        else:
            target = {"type": "other_ballot_item", "label": e["target_label"],
                      "note": "Not a City of Boulder measure."}
        if e["endorser_org_id"]:
            endorser = {"type": "organization", "slug": e["org_slug"], "name": e["org_name"],
                        "page_url": u(f"orgs/{e['org_slug']}.html")}
            group = "organization"
        else:
            endorser = {"type": "person", "slug": e["person_slug"], "name": e["person_name"],
                        "title_as_printed": e["person_title"], "page_url": u(f"people/{e['person_slug']}.html")}
            group = e["weight_group"] or "other_individual"
        endorsements.append({
            "id": e["id"], "endorser": endorser, "endorser_group": group, "target": target,
            "position": "oppose" if e["position"] == "oppose" else "support",
            "rank": e["rank"], "provenance": e["provenance"], "provenance_label": PROV_LABEL[e["provenance"]],
            "label": prov_text(e), "claimed_by": e["claimed_by"], "published_on": e["published_on"],
            "source_url": e["source_url"], "source_title": e["source_title"],
        })

    # forum quotes (held claims are not in the answers table)
    quotes = []
    for r in forums.rows:
        caveats = [TRANSCRIPT_NOTE]
        if r["confidence"] == "medium":
            caveats.append(MEDIUM_CAVEAT)
        if r["tnote"]:
            caveats.append("Transcript note: " + r["tnote"])
        quotes.append({
            "id": r["claim"], "candidate_slug": r["pslug"], "candidate": r["full_name"], "forum": r["event"],
            "forum_name": forums.forums[r["event"]]["name"], "date": forums.forums[r["event"]]["date"],
            "question": r["prompt"], "topic": r["topic"], "issue": r["issue_slug"], "measure": r["measure"],
            "stance": r["stance"], "stance_about": r["stance_about"] if r["stance"] else None,
            "stance_note": r["snote"], "quote": " ".join(r["verbatim"].split()),
            "watch_url": r["watch"], "timestamp": ts(r["start"]), "attribution_confidence": r["confidence"],
            "caveats": caveats, "recording_url": r["source_url"], "recording_title": r["source_title"],
            "page_url": u(f"forums/{r['event']}.html"),
        })

    measures = []
    for m in q("""SELECT m.*, md.*, s.url AS lang_url FROM measures m JOIN measure_details md ON md.measure_id=m.id
                  JOIN elections e ON e.id=m.election_id LEFT JOIN sources s ON s.id=md.language_source_id
                  WHERE e.year=2026 AND m.letter IS NOT NULL ORDER BY m.letter""").fetchall():
        letter = m["letter"]
        rl = q("""SELECT rl.reporter, rl.text, rl.reported_on, s.url FROM reported_lines rl JOIN sources s ON s.id=rl.source_id
                  WHERE rl.measure_id=?""", (m["measure_id"],)).fetchall()
        measures.append({
            "letter": letter, "slug": f"2026-{letter.lower()}", "title": m["title"], "kind": m["kind"],
            "page_url": u(f"measures/2026-{letter.lower()}.html"),
            "api_url": u("api/v1/measures.json"),
            "plain_summary": m["plain_summary"], "yes_means": m["yes_means"], "no_means": m["no_means"],
            "fiscal": {"text": m["fiscal_text"], "source_url": src(m["fiscal_source_id"])} if m["fiscal_text"] else None,
            "how_it_got_on_ballot": {"text": m["council_vote_text"], "source_url": src(m["council_vote_source_id"])}
            if m["council_vote_text"] else None,
            "official_text_url": m["lang_url"], "ballot_language": m["ballot_language"],
            "unknowns": json.loads(m["unknowns"] or "[]"),
            "reporter_summaries": [{"reporter": x["reporter"], "text": x["text"], "reported_on": x["reported_on"],
                                    "source_url": x["url"],
                                    "note": "A reporter's summary of the field, not each candidate's own answer."}
                                   for x in rl],
            "positions": [e["id"] for e in endorsements if e["target"].get("letter") == letter],
            "forum_quotes": [x["id"] for x in quotes if x["measure"] == letter],
            "source_urls": sorted({x for x in (m["lang_url"], src(m["fiscal_source_id"]),
                                               src(m["council_vote_source_id"])) if x}),
        })

    finance = []
    for f in q("""SELECT f.*, p.slug, p.full_name, s.url AS source_url FROM finance_snapshots f
                  LEFT JOIN people p ON p.id=f.person_id JOIN sources s ON s.id=f.source_id
                  WHERE f.year=2026 ORDER BY COALESCE(p.sort_name, f.committee_name)""").fetchall():
        items = q("""SELECT direction, display_name, item_type, purpose, occurred_on, amount
                     FROM finance_line_items WHERE snapshot_id=? ORDER BY direction, amount DESC, display_name""",
                  (f["id"],)).fetchall()
        finance.append({
            "committee": f["committee_name"], "committee_number": f["committee_number"],
            "committee_kind": f["committee_kind"], "candidate_slug": f["slug"], "candidate": f["full_name"],
            "contributions": f["contributions"], "expenditures": f["expenditures"],
            "matching_funds_received": f["matching_received"], "cash_on_hand": f["cash_on_hand"],
            "as_of": f["reported_on"], "report": f["report_label"], "report_url": f["report_url"],
            "retrieved_on": f["retrieved_on"],
            "reports_url": f["reports_url"], "source_url": f["source_url"],
            "notes": f["notes"],
            "line_items": [dict(i) for i in items],
        })

    candidates = []
    for office in ("mayor", "council"):
        rows = q("""SELECT c.id AS cid, c.ballot_position, c.is_incumbent, c.campaign_url, c.matching_funds,
                           p.id AS pid, p.slug, p.full_name, cp.summary, cp.occupation, cp.prior_office,
                           cp.years_in_boulder, cp.research_notes
                    FROM candidacies c JOIN people p ON p.id=c.person_id JOIN races r ON r.id=c.race_id
                    JOIN elections e ON e.id=r.election_id JOIN offices o ON o.id=r.office_id
                    LEFT JOIN candidate_profiles cp ON cp.candidacy_id=c.id
                    WHERE e.year=2026 AND o.slug=? ORDER BY c.ballot_position""", (office,)).fetchall()
        for r in rows:
            stm = q("""SELECT st.*, s.url, s.title FROM statements st JOIN sources s ON s.id=st.source_id
                       WHERE st.person_id=? AND st.status='published' ORDER BY st.topic, st.id""", (r["pid"],)).fetchall()
            held = q("SELECT COUNT(*) FROM statements WHERE person_id=? AND status='held'", (r["pid"],)).fetchone()[0]
            bio_src = [x[0] for x in q("""SELECT DISTINCT s.url FROM profile_sources ps JOIN sources s ON s.id=ps.source_id
                                          WHERE ps.candidacy_id=?""", (r["cid"],))]
            past = q("""SELECT e.year, o.slug AS office, c.status FROM candidacies c JOIN races r ON r.id=c.race_id
                        JOIN elections e ON e.id=r.election_id JOIN offices o ON o.id=r.office_id
                        WHERE c.person_id=? AND e.year<2026 ORDER BY e.year""", (r["pid"],)).fetchall()
            fin = next((f for f in finance if f["candidate_slug"] == r["slug"]
                        and f["committee_kind"] == "official_candidate"), None)
            my_edges = [e for e in endorsements if e["target"].get("slug") == r["slug"]]
            my_quotes = [x for x in quotes if x["candidate_slug"] == r["slug"]]
            candidates.append({
                "slug": r["slug"], "name": r["full_name"], "office": office,
                "office_label": "Mayor" if office == "mayor" else "City Council",
                "ballot_position": r["ballot_position"], "incumbent": bool(r["is_incumbent"]),
                "matching_funds_participant": bool(r["matching_funds"]),
                "campaign_url": r["campaign_url"],
                "page_url": u(f"people/{r['slug']}.html"), "print_url": u(f"print/{r['slug']}.html"),
                "api_url": u(f"api/v1/candidates/{r['slug']}.json"),
                "bio": {"summary": r["summary"], "occupation": r["occupation"], "public_office": r["prior_office"],
                        "in_boulder": r["years_in_boulder"], "note": r["research_notes"], "source_urls": bio_src},
                "past_city_races": [{"year": p["year"], "office": p["office"], "result": p["status"]} for p in past],
                "statements": [{"id": s["id"], "topic": s["topic"], "text": " ".join(s["text"].split()),
                                "speaker": s["speaker"], "candidate_own_words": bool(s["speaker_is_candidate"]),
                                "verbatim": bool(s["verbatim"]), "publisher": s["publisher"], "kind": s["kind"],
                                "published_on": s["published_on"], "source_url": s["url"], "source_title": s["title"]}
                               for s in stm],
                "statements_held_back": held,
                "forum_quotes": my_quotes,
                "endorsements": my_edges,
                "finance": {k: fin[k] for k in ("committee", "contributions", "expenditures",
                                                 "matching_funds_received", "cash_on_hand", "as_of",
                                                 "report", "report_url", "retrieved_on",
                                                 "reports_url", "source_url", "notes")} if fin else None,
                "source_urls": sorted({*bio_src, *(s["url"] for s in stm), *(e["source_url"] for e in my_edges),
                                       *(x["recording_url"] for x in my_quotes),
                                       *([fin["source_url"]] if fin else [])} - {None}),
            })
    names = {c["name"] for c in candidates}
    missing = [n for race in order["races"].values() for n in race if n not in names]
    if missing:
        raise SystemExit(f"build_llm: ballot_order names missing from DB: {missing}")

    forum_list = []
    for slug, f in sorted(forums.forums.items(), key=lambda kv: kv[1]["date"]):
        forum_list.append({
            "slug": slug, "name": f["name"], "date": f["date"], "hosts": f["hosts"], "venue": f["venue"],
            "page_url": u(f"forums/{slug}.html"),
            "recordings": [{"title": r["title"], "url": f"https://www.youtube.com/watch?v={r['youtube_id']}",
                            "uploader": r["uploader"]} for r in f["recordings"]],
            "quote_ids": [x["id"] for x in quotes if x["forum"] == slug],
        })

    sources = [{"id": s["id"], "url": s["url"], "title": s["title"], "kind": s["kind"], "year": s["year"],
                "published_on": s["published_on"], "publisher": s["org"]}
               for s in q("""SELECT s.*, o.name AS org FROM sources s LEFT JOIN organizations o ON o.id=s.org_id
                             ORDER BY s.year DESC, s.id""")]

    election = {
        "name": "City of Boulder general municipal election", "date": "2026-11-03",
        "jurisdiction": "City of Boulder, Colorado",
        "scope_note": "Only City of Boulder races and measures. Ballots also carry county, state, school board "
                      "and regional items, which this guide does not cover.",
        "key_dates": [{"date": iso, "label": label} for iso, _, label in KEY_DATES],
        "key_dates_source_url": KEY_DATES_URL,
        "how_to_vote": [
            "Boulder County mails ballots to registered voters starting October 2, 2026. 24-hour drop boxes open the same day.",
            "Ballots must be received (not postmarked) by 7 p.m. on Tuesday, November 3, 2026. The county recommends mailing by October 26; after that, use a drop box or Vote Center.",
            "Vote Centers open October 19 for in-person voting and same-day registration.",
            "You can register and vote through Election Day. Register by October 26 if you want a ballot mailed to you.",
            "Only registered voters who live inside Boulder city limits get these city races. Check your registration at https://www.govotecolorado.gov",
        ],
        "how_to_vote_source_urls": [KEY_DATES_URL, "https://bouldercounty.gov/elections/information/ballot-services/",
                                    "https://www.govotecolorado.gov"],
        "races": [
            {"id": "mayor", "office": "Mayor", "seats": 1, "voting_method": "ranked_choice",
             "how_to_mark": "Rank the candidates: a 1st choice, then a 2nd, 3rd and so on if you want. You don't have to rank everyone.",
             "term": "Two years", "candidates_in_ballot_order": [c["slug"] for c in candidates if c["office"] == "mayor"]},
            {"id": "council", "office": "City Council", "seats": 5, "voting_method": "plurality",
             "how_to_mark": "Vote for up to five. The five candidates with the most votes win.",
             "term": "Four years",
             "candidates_in_ballot_order": [c["slug"] for c in candidates if c["office"] == "council"]},
        ],
        "rules_source_urls": ["https://bouldercolorado.gov/guide/ranked-choice-voting-guide",
                              "https://bouldercolorado.gov/2026-city-boulder-mayoral-and-city-council-candidates",
                              "https://bouldercolorado.gov/election-guidelines"],
        "ballot_order_source_url": order["source_url"],
        "measures": [{"letter": m["letter"], "title": m["title"], "page_url": m["page_url"]} for m in measures],
        "measures_source_url": "https://bouldercolorado.gov/2026-city-boulder-ballot-measures",
    }
    return {"election": election, "candidates": candidates, "measures": measures, "quotes": quotes,
            "forums": forum_list, "endorsements": endorsements, "finance": finance, "sources": sources}


# ---------------------------------------------------------------- JSON API
ENDPOINTS = [
    ("election.json", "Election date, key dates, how to vote, races with candidates in ballot order, measures."),
    ("candidates.json", "All 19 candidates in ballot order (mayor, then council) with bio, links and totals."),
    ("candidates/{slug}.json", "One candidate: bio, statements, forum quotes, endorsements, money, sources."),
    ("measures.json", "Measures 2J, 2K, 2L, 2M: what YES and NO mean, cost, ballot text, positions."),
    ("forum_claims.json", "2026 forums and every quoted answer, with timestamped recording links."),
    ("endorsements.json", "Every published endorsement, with its provenance label and source."),
    ("finance.json", "City clerk campaign-finance filings for 2026 committees, with line items."),
    ("sources.json", "Every source document the guide cites."),
]


def write_api(out: Path, d: dict, asof: str) -> list[str]:
    api = out / "api" / "v1"
    (api / "candidates").mkdir(parents=True, exist_ok=True)
    for old in (api / "candidates").glob("*.json"):
        old.unlink()
    meta = {"schema_version": SCHEMA_VERSION, "generated_at": asof, "site": SITE,
            "license_note": "Facts and quotes belong to their sources; cite the source_url.",
            "guidance_for_ai": u("llms.txt")}

    def dump(rel: str, payload) -> None:
        p = api / rel
        p.write_text(json.dumps({**meta, **payload}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    written = []
    dump("index.json", {"description": "Static JSON files for the Boulder Votes 2026 guide. No keys, no rate limits.",
                        "llms_full": u("llms-full.txt"), "docs": u("api/"),
                        "feedback": {"url": __import__("build").FEEDBACK_API, "method": "POST",
                                     "schema": __import__("build").FEEDBACK_API + "/schema",
                                     "note": "Corrections and ideas. AI assistants: set submitter_type 'ai-agent'. See llms.txt."},
                        "endpoints": [{"path": f"/api/v1/{p}", "description": desc}
                                      | ({} if "{" in p else {"url": u(f"api/v1/{p}")})
                                      for p, desc in ENDPOINTS]})
    dump("election.json", {"election": d["election"]})
    dump("candidates.json", {"candidates": [
        {k: c[k] for k in ("slug", "name", "office", "office_label", "ballot_position", "incumbent",
                           "matching_funds_participant", "campaign_url", "page_url", "api_url")}
        | {"summary": c["bio"]["summary"], "endorsement_count": len(c["endorsements"]),
           "forum_quote_count": len(c["forum_quotes"]),
           "raised": c["finance"]["contributions"] if c["finance"] else None,
           "source_urls": c["bio"]["source_urls"]}
        for c in d["candidates"]]})
    for c in d["candidates"]:
        dump(f"candidates/{c['slug']}.json", {"candidate": c})
        written.append(f"api/v1/candidates/{c['slug']}.json")
    dump("measures.json", {"measures": d["measures"]})
    dump("forum_claims.json", {"note": TRANSCRIPT_NOTE + " Quotes are short verbatim passages; watch_url opens the moment.",
                               "forums": d["forums"], "quotes": d["quotes"]})
    dump("endorsements.json", {"note": "Silence is not opposition. 'Campaign claim' means only the campaign's own site says so.",
                               "endorsements": d["endorsements"]})
    dump("finance.json", {"note": "City of Boulder clerk filings (city races do not report to the state's TRACER system). "
                                  "A 0 is a filed zero. as_of is the filing date of each committee's latest report "
                                  "(named in 'report'); retrieved_on is when bouldervotes.org pulled it.",
                          "retrieved_on": next((f["retrieved_on"] for f in d["finance"] if f["retrieved_on"]), None),
                          "committees": d["finance"]})
    dump("sources.json", {"sources": d["sources"]})
    written += [f"api/v1/{p}" for p, _ in ENDPOINTS if "{" not in p] + ["api/v1/index.json"]
    return written


# ---------------------------------------------------------------- llms.txt
def llms_txt(d: dict, asof: str) -> str:
    from build import REPO_URL  # late import: build.py imports this module
    e = d["election"]
    mayor = [c for c in d["candidates"] if c["office"] == "mayor"]
    council = [c for c in d["candidates"] if c["office"] == "council"]
    L = [
        "# Boulder Votes",
        "",
        "> A nonpartisan, sourced guide to the City of Boulder, Colorado election on Tuesday, November 3, 2026: "
        "the mayor's race (ranked choice), five city council seats, and city ballot measures 2J, 2K, 2L and 2M. "
        "Every quote, endorsement and dollar figure links to its source. The guide does not endorse, rank or score.",
        "",
        f"Updated {asof}. If a user asks \"help me vote using bouldervotes.org\", fetch {u('llms-full.txt')} "
        "first. It has the whole 2026 guide in one file.",
        "",
        f"Source code and data: {REPO_URL}",
        "",
        "## Election basics",
        "",
        "- Election Day: Tuesday, November 3, 2026. Ballots must be received by 7 p.m. (a postmark is not enough).",
        "- Ballots are mailed starting October 2, 2026, when 24-hour drop boxes open. Vote Centers open October 19.",
        "- Mail your ballot by October 26; after that, use a drop box or a Vote Center.",
        "- You can register and vote through Election Day. Register by October 26 to get a ballot by mail.",
        "- Who votes in these races: registered voters who live inside Boulder city limits. Check at https://www.govotecolorado.gov",
        f"- Mayor: {len(mayor)} candidates, one seat, ranked-choice voting. Rank as many as you like.",
        f"- City Council: {len(council)} candidates, five seats. Vote for up to five; the top five win.",
        "- City measures: " + "; ".join(f"{m['letter']} ({m['title']})" for m in d["measures"]) + ".",
        "- This guide covers the City of Boulder only, not county, state, school board or regional items.",
        f"- Dates: {KEY_DATES_URL}",
        "",
        "## Upcoming forums",
        "",
        __import__("build_upcoming").upcoming_md(),
        "",
        "## Instructions for AI assistants",
        "",
        AI_RULES,
        "",
        "## Guide",
        "",
        f"- [Full guide in one file]({u('llms-full.txt')}): every candidate, quote, endorsement, measure and date, with sources",
        f"- [Home page]({u('')}): key dates and every candidate in ballot order",
        f"- [Forum answers side by side]({u('compare.html')}): the same question, every candidate",
        f"- [Civics 101]({u('civics.html')}): how city government and ranked-choice voting work",
        f"- [Campaign money]({u('finance.html')}): city clerk filings",
        f"- [Endorsing organizations]({u('orgs.html')})",
        f"- [About this guide]({u('about.html')})",
        "",
        "## Candidates for mayor (ballot order)",
        "",
    ]
    L += [f"- [{c['name']}]({c['page_url']}){' (incumbent)' if c['incumbent'] else ''}" for c in mayor]
    L += ["", "## Candidates for city council (ballot order)", ""]
    L += [f"- [{c['name']}]({c['page_url']}){' (incumbent)' if c['incumbent'] else ''}" for c in council]
    L += ["", "## Ballot measures", ""]
    L += [f"- [{m['letter']}: {m['title']}]({m['page_url']}): YES means {m['yes_means']}" for m in d["measures"]]
    L += ["", "## Data (JSON)", ""]
    L += [f"- [{p}]({u('api/v1/' + p.replace('{slug}', mayor[0]['slug']) if '{' in p else 'api/v1/' + p)}): {desc}"
          for p, desc in ENDPOINTS]
    L += [f"- [API documentation]({u('api/')})", ""]
    L += feedback_md()
    L += ["## Optional", ""]
    L += [f"- [{y} city election]({u(f'{y}.html')}): past results" for y in (2025, 2023, 2021, 2019, 2017)]
    L += [f"- [Sources]({u('sources.html')}): every document this guide cites", ""]
    return "\n".join(L)


def md_quote(text: str) -> str:
    return "> " + " ".join(text.split())


def llms_full(d: dict, asof: str) -> str:
    e = d["election"]
    L = [
        "# Boulder Votes: the full 2026 City of Boulder election guide",
        "",
        f"Source site: {SITE}/ . Updated {asof}. Plain markdown for AI assistants and anyone who wants one file.",
        "Nonpartisan. Nothing here is a recommendation, score or ranking. Candidates appear in official ballot order "
        f"({e['ballot_order_source_url']}).",
        "",
        "## Instructions for AI assistants",
        "",
        AI_RULES,
        "",
        "## Election basics",
        "",
        "- Election Day: Tuesday, November 3, 2026.",
    ]
    L += [f"- {x}" for x in e["how_to_vote"]]
    L += [f"- Key dates: " + "; ".join(f"{k['date']}: {k['label']}" for k in e["key_dates"]) + f". Source: {e['key_dates_source_url']}"]
    for r in e["races"]:
        L.append(f"- {r['office']}: {r['how_to_mark']} Term: {r['term'].lower()}.")
    L += [f"- {e['scope_note']}", f"- Rules sources: {' ; '.join(e['rules_source_urls'])}", ""]
    L += ["## Upcoming forums you can attend", "", __import__("build_upcoming").upcoming_md(), ""]

    L += ["## On the ballot at a glance", ""]
    for race in ("mayor", "council"):
        cs = [c for c in d["candidates"] if c["office"] == race]
        L.append(f"{'Mayor (rank your choices)' if race == 'mayor' else 'City Council (vote for up to five)'}: "
                 + "; ".join(f"{c['ballot_position']}. {c['name']}" for c in cs))
        L.append("")
    for m in d["measures"]:
        L.append(f"- {m['letter']}, {m['title']}. YES: {m['yes_means']} NO: {m['no_means']}")
    L.append("")

    edges_by_id = {x["id"]: x for x in d["endorsements"]}
    quotes_by_id = {x["id"]: x for x in d["quotes"]}
    for race in ("mayor", "council"):
        L += [f"## {'Mayor' if race == 'mayor' else 'City Council'} candidates", ""]
        for c in [c for c in d["candidates"] if c["office"] == race]:
            b = c["bio"]
            L += [f"### {c['name']}, {c['office_label']}, ballot position {c['ballot_position']}"
                  + (" (incumbent)" if c["incumbent"] else ""), ""]
            L.append(f"Page: {c['page_url']} | Data: {c['api_url']}"
                     + (f" | Campaign site: {c['campaign_url']}" if c["campaign_url"] else ""))
            L.append("")
            if b["summary"]:
                L.append(clean(b["summary"]))
            for k, lab in (("occupation", "Occupation"), ("public_office", "Public office"), ("in_boulder", "In Boulder")):
                if b[k]:
                    L.append(f"- {lab}: {clean(b[k])}")
            if b["note"]:
                L.append(f"- Note: {clean(b['note'])}")
            if b["source_urls"]:
                L.append(f"- Bio sources: {' ; '.join(b['source_urls'])}")
            if c["past_city_races"]:
                L.append("- Earlier city races: " + ", ".join(f"{p['year']} {p['office']} ({p['result']})"
                                                             for p in c["past_city_races"]))
            L.append(f"- Matching-funds participant (city clerk list): {'yes' if c['matching_funds_participant'] else 'no'}")
            L.append("")
            f = c["finance"]
            L.append("#### Money")
            L.append("")
            if f:
                L.append(f"Raised ${f['contributions']:,.2f}; spent ${f['expenditures']:,.2f}; matching funds received "
                         f"${f['matching_funds_received']:,.2f}"
                         + (f"; cash on hand ${f['cash_on_hand']:,.2f}" if f["cash_on_hand"] is not None else "")
                         + f". As of {f['as_of']}, the {f['report'] or 'latest'} report ({f['committee']}); "
                         f"retrieved {f['retrieved_on']}. City clerk filing: {f['report_url'] or f['reports_url']}")
                if f["notes"]:
                    L.append(f"Note: {clean(f['notes'])}")
            else:
                L.append("No city clerk filing on file.")
            L.append("")
            L.append("#### In their own words (statements)")
            L.append("")
            own = [s for s in c["statements"] if s["candidate_own_words"]]
            rep = [s for s in c["statements"] if not s["candidate_own_words"]]
            if not own:
                L.append("No first-person statements on file.")
            for s in own:
                L.append(f"- Topic: {s['topic']}. {s['publisher']}, {s['kind']}"
                         + (f", {s['published_on']}" if s["published_on"] else "") + f". Source: {s['source_url']}")
                L.append("  " + md_quote(s["text"]))
            if rep:
                L.append("")
                L.append("What reporters wrote (the reporter's words, not the candidate's):")
                for s in rep:
                    L.append(f"- {s['speaker']} on {s['topic']}. {s['publisher']}"
                             + (f", {s['published_on']}" if s["published_on"] else "") + f". Source: {s['source_url']}")
                    L.append("  " + md_quote(s["text"]))
            if c["statements_held_back"]:
                L.append(f"({c['statements_held_back']} further passage(s) held back until the quoted words can be "
                         "matched to the source. Not included.)")
            L.append("")
            L.append("#### At the 2026 forums")
            L.append("")
            if not c["forum_quotes"]:
                L.append("No forum quotes on file.")
            for x in c["forum_quotes"]:
                st = ""
                if x["stance"]:
                    st = f" Said {x['stance'].upper()} on {x['stance_about']}."
                    if x["stance_note"]:
                        st += f" ({x['stance_note']})"
                L.append(f"- {x['forum_name']}, {x['date']}. Q: {clean(x['question'])}{st}")
                L.append("  " + md_quote(x["quote"]))
                L.append(f"  Watch at {x['timestamp']}: {x['watch_url']} . " + " ".join(x["caveats"]))
            L.append("")
            L.append("#### Endorsements")
            L.append("")
            if not c["endorsements"]:
                L.append("No endorsements on file. That is not opposition.")
            for x in c["endorsements"]:
                who = x["endorser"]["name"] + (f", {x['endorser']['title_as_printed']}"
                                               if x["endorser"].get("title_as_printed") else "")
                rank = f" ({x['rank']} choice, ranked-choice)" if x["rank"] else ""
                L.append(f"- {who}{rank}. {x['label']} Source: {x['source_url']}"
                         + (f" ({x['published_on']})" if x["published_on"] else ""))
            L.append("")

    L += ["## City ballot measures", ""]
    for m in d["measures"]:
        L += [f"### {m['letter']}: {m['title']}", "", f"Page: {m['page_url']}", "",
              f"A YES vote means: {m['yes_means']}", "", f"A NO vote means: {m['no_means']}", "",
              f"In plain words: {clean(m['plain_summary'])}", ""]
        if m["fiscal"]:
            L += [f"Money: {clean(m['fiscal']['text'])} Source: {m['fiscal']['source_url']}", ""]
        if m["how_it_got_on_ballot"]:
            L += [f"How it got on the ballot: {clean(m['how_it_got_on_ballot']['text'])} "
                  f"Source: {m['how_it_got_on_ballot']['source_url']}", ""]
        L.append("Who supports or opposes it:")
        pos = [edges_by_id[i] for i in m["positions"]]
        if not pos:
            L.append("- None found so far.")
        for x in pos:
            L.append(f"- {'Opposes' if x['position'] == 'oppose' else 'Supports'}: {x['endorser']['name']}. "
                     f"{x['label']} Source: {x['source_url']}")
        for r in m["reporter_summaries"]:
            L.append(f"- Reporter summary ({r['reporter']}, {r['reported_on']}): {r['text']} {r['note']} Source: {r['source_url']}")
        if m["forum_quotes"]:
            L += ["", f"What candidates said about {m['letter']} at forums (speaking order):"]
            for i in m["forum_quotes"]:
                x = quotes_by_id[i]
                st = f" Said {x['stance'].upper()}." if x["stance"] else " No yes/no label."
                L.append(f"- {x['candidate']}, {x['forum_name']}.{st}")
                L.append("  " + md_quote(x["quote"]))
                L.append(f"  Watch at {x['timestamp']}: {x['watch_url']} . " + " ".join(x["caveats"]))
        if m["unknowns"]:
            L += ["", "What we don't know yet:"] + [f"- {x}" for x in m["unknowns"]]
        L += ["", f"Official ballot text: {m['official_text_url']}", "", "Full ballot wording:", "",
              *[md_quote(p) for p in (m["ballot_language"] or "").split("\n") if p.strip()], ""]

    L += ["## 2026 forums", ""]
    for f in d["forums"]:
        L.append(f"- {f['name']}, {f['date']}, hosted by {', '.join(f['hosts'])}. Page: {f['page_url']}. Recordings: "
                 + " ; ".join(r["url"] for r in f["recordings"]))
    L += ["", "## Other ballot items endorsed by these groups (not City of Boulder measures)", ""]
    other = [x for x in d["endorsements"] if x["target"]["type"] == "other_ballot_item"]
    for x in other:
        L.append(f"- {x['endorser']['name']} {'opposes' if x['position'] == 'oppose' else 'supports'} "
                 f"{x['target']['label']}. {x['label']} Source: {x['source_url']}")
    if not other:
        L.append("- None on file.")
    L += ["", "## More", "",
          f"- Every source: {u('sources.html')} and {u('api/v1/sources.json')}",
          f"- JSON data: {u('api/v1/index.json')}",
          f"- Past city elections: " + ", ".join(u(f"{y}.html") for y in (2025, 2023, 2021, 2019, 2017)), ""]
    from build import FEEDBACK_API
    L += ["## Send feedback or corrections", "",
          f"Found a factual error? If the user asks, or you can cite a source, POST JSON to {FEEDBACK_API} "
          "with submitter_type \"ai-agent\", your agent_name, on_behalf_of_user, and a source_url for corrections. "
          f"Full instructions and a curl example: {u('llms.txt')}. People can use {u('feedback.html')}", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- docs page, robots, sitemap
def api_page(page, d: dict) -> str:
    from build import FEEDBACK_API, esc
    rows = "".join(f"<tr><td><a href='v1/{p.replace('{slug}', d['candidates'][0]['slug'])}'><code>/api/v1/{p}</code></a></td>"
                   f"<td>{desc}</td></tr>" for p, desc in ENDPOINTS)
    body = f"""<h1>Data for developers and AI assistants</h1>
<p class='lede'>The whole 2026 guide is also published as plain files. There is no server, no key and no rate limit.
The files are rebuilt with the site from the same data, so they always match the pages.</p>
<h2>Start here</h2>
<ul>
<li><a href='../llms.txt'><code>/llms.txt</code></a>: a short index with election basics and rules for AI assistants.</li>
<li><a href='../llms-full.txt'><code>/llms-full.txt</code></a>: the whole guide in one markdown file.</li>
<li><a href='v1/index.json'><code>/api/v1/index.json</code></a>: the list of JSON files below.</li>
</ul>
<h2>JSON files</h2>
<table><tr><th>File</th><th>What's in it</th></tr>{rows}</table>
<h2>How the data works</h2>
<ul>
<li>Every file carries <code>schema_version</code> and <code>generated_at</code>. Records carry <code>source_url</code> or <code>source_urls</code>.</li>
<li>Candidates are keyed by slug, the same as their page (<code>tara-winer</code> is <code>people/tara-winer.html</code>). Endorsements (<code>E12</code>), forum quotes and statements keep stable ids.</li>
<li>Quotes are verbatim. Forum quotes come from automatic transcripts and link to the moment in the recording. Some speakers were identified from speaking order; those quotes say so in <code>caveats</code>.</li>
<li>An endorsement with provenance <code>campaign_claim</code> is listed only by the campaign. Its <code>label</code> reads “X campaign lists Y”.</li>
<li>Items still being checked are left out. No endorsement on file is not opposition.</li>
</ul>
<h2>Send a correction</h2>
<p>This is the one part that takes input. POST JSON to <code>{esc(FEEDBACK_API)}</code>. AI assistants should set
<code>submitter_type</code> to <code>ai-agent</code> and give <code>agent_name</code>, and include a <code>source_url</code> for corrections.
Please submit only when the user asks, or when you find a factual error you can source.
The fields are listed at <a href='{esc(FEEDBACK_API)}/schema'><code>/api/v1/feedback/schema</code></a>, and <a href='../llms.txt'>llms.txt</a> has a curl example.
People can use the <a href='../feedback.html'>feedback form</a>. A person reads every note, and notes are never published.</p>
<p class='note'>Facts and quotes belong to their sources. If you reuse them, cite the source URL.</p>"""
    return page("Data and API", body, prefix="../", year=2026, learn="api")


def write_all(con: sqlite3.Connection, out: Path, forums, page) -> dict:
    asof = today().isoformat()
    d = collect(con, forums)
    written = write_api(out, d, asof)
    (out / "llms.txt").write_text(llms_txt(d, asof), encoding="utf-8")
    full = llms_full(d, asof)
    (out / "llms-full.txt").write_text(full, encoding="utf-8")
    (out / "api" / "index.html").write_text(api_page(page, d), encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {u('sitemap.xml')}\n", encoding="utf-8")
    pages = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.html"))
    locs = [u("")] + [u(p) for p in pages if p != "index.html"] + [u("llms.txt"), u("llms-full.txt")]
    (out / "sitemap.xml").write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
        + "".join(f"<url><loc>{x}</loc><lastmod>{asof}</lastmod></url>\n" for x in locs) + "</urlset>\n",
        encoding="utf-8")
    return {"full_bytes": len(full.encode("utf-8")), "api_files": len(written)}


def home_head() -> str:
    """<head> additions for the home page: alternates, description, JSON-LD."""
    ld = [
        {"@context": "https://schema.org", "@type": "WebSite", "name": "Boulder Votes", "url": SITE + "/",
         "description": "A nonpartisan, sourced guide to the City of Boulder, Colorado election on November 3, 2026."},
        {"@context": "https://schema.org", "@type": "Event",
         "name": "City of Boulder general municipal election 2026",
         "startDate": "2026-11-03T07:00:00-07:00", "endDate": "2026-11-03T19:00:00-07:00",
         "eventStatus": "https://schema.org/EventScheduled",
         "eventAttendanceMode": "https://schema.org/MixedEventAttendanceMode",
         "location": {"@type": "Place", "name": "Boulder, Colorado",
                      "address": {"@type": "PostalAddress", "addressLocality": "Boulder",
                                  "addressRegion": "CO", "addressCountry": "US"}},
         "description": "Mayor (ranked choice), five City Council seats, and city measures 2J, 2K, 2L and 2M. "
                        "Ballots mailed from October 2; must be received by 7 p.m. November 3.",
         "url": SITE + "/"},
    ]
    return (
        '<meta name="description" content="Nonpartisan guide to the November 3, 2026 City of Boulder election: '
        'every mayor and council candidate in ballot order, measures 2J to 2M, key dates, with a source for every fact.">\n'
        '<link rel="alternate" type="application/json" href="/api/v1/index.json" title="Boulder Votes data">\n'
        '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>\n"
    )


def strip_html(html: str) -> str:
    """Rough text rendering (what a fetch tool that drops markup sees)."""
    html = re.sub(r"<head>.*?</head>|<script.*?</script>", " ", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())
