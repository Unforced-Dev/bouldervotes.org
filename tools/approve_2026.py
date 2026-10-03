#!/usr/bin/env python3
"""Convert 2026 research JSON into reviewed, committed harvest files.

    python3 tools/approve_2026.py [RESEARCH_DIR]

RESEARCH_DIR defaults to $BV_RESEARCH or ../bv-research. Writes
data/harvest/2026/{candidates,statements,endorsements,organizations,measures}.json
and civics101.md. seed.py reads ONLY those committed files; this script is the
one place where audit decisions (audit_2026.md) are applied, so every override
below is explicit and reviewable.

Binding rules applied here:
  1. Every endorsement carries provenance: endorser_statement | campaign_claim | filing.
     Anything cited only to a candidate's (or ballot campaign's) own site is a
     campaign_claim, whoever the endorser is.
  2. The seven Daily Camera passages the audit could not text-verify are HELD.
  3. Ballot-facing display name "Dave Martus" (city roster).
  4. Jamillah Richmond's Boulder Progressives board listing is dated, not current.
  5. No stance inferred from silence or journalist grouping (enforced in ingest/build).
  6. Ranked-choice endorsements keep their rank.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "harvest" / "2026"

AUDIT_DATE = "2026-09-24"

# --- rule 3: display names -------------------------------------------------
DISPLAY_NAME = {"David Martus": "Dave Martus"}

# --- rule 2: held statements (candidate name in research file, zero-based index)
HELD_STATEMENTS = {
    ("Jameson Goldstein", 6): "Daily Camera passage (privacy) not text-verified by the Sept. 24 audit.",
    ("Aquiles La Grave", 9): "Daily Camera passage (budget) not text-verified by the Sept. 24 audit.",
    ("Rachel Rose Isaacson", 7): "Daily Camera passage (housing) not text-verified by the Sept. 24 audit.",
    ("Tara Winer", 8): "Daily Camera passage (budget) not text-verified by the Sept. 24 audit.",
    ("Ryan Schuchard", 6): "Daily Camera passage (climate) not text-verified by the Sept. 24 audit.",
    ("Jill Grano", 8): "Daily Camera passage (housing) not text-verified by the Sept. 24 audit.",
    ("David Martus", 8): "Daily Camera passage (budget) not text-verified by the Sept. 24 audit.",
}

# --- rule 1: audit-held edges that must render as campaign claims -----------
# (E68 left this list on Sept. 29: the chapter's own Sept. 9 post endorses Richmond.)
AUDIT_HELD_EDGES = {
    69: "Audit HOLD: Schuchard's site says he earned this endorsement; no group-authored statement cited.",
    71: "Audit HOLD: Winer campaign displays the group's logo (image alt text); no dated group announcement.",
    77: "Audit HOLD: Brockett campaign names Neguse; the cited page is the candidate's claim, not a Neguse statement. Personal support does not imply his congressional office endorsed.",
    139: "Audit HOLD: Jamieson campaign lists Benjamin on an 'ENDORSED BY' card; not a Benjamin-authored announcement.",
    # 235 (DSA -> 2J) left Oct. 3: the chapter's Sept. 29 press release endorses 2J (news report; see harvest JSON).
}

# A news outlet lists the endorsement, but it is not a report of the endorser's
# own release and no endorser-authored statement was located (audit: "apply the
# same rule ... E70, E204"). Shown with its own visible label, never as the
# endorser's voice.
NEWS_REPORT_EDGES: dict[int, str] = {
    # E204 (DSA -> Adams) was upgraded Sept. 29; see SOURCE_CORRECTIONS.
}

# ---------------------------------------------------------------------------
# Sept. 29, 2026 full verification (bv-research/endorsement_verification_2026.json).
# Every edge has a ledger entry; the decisions that change data are below.
# ---------------------------------------------------------------------------
VERIFIED_ON = "2026-09-29"
PLAN_2026 = "https://planboulder.org/2026-city-council-candidate-endorsements"
PLAN_BALLOT_2026 = "https://planboulder.org/2026-ballot-issue-endorsements"
BP_SLATE = "https://blog.boulderprogressives.org/announcing-bps-strongest-slate-ever-for-2026-election/"
BP_MEASURES = "https://blog.boulderprogressives.org/our-2026-ballot-measure-positions/"
CHAMBER_RELEASE = "https://www.boulderchamber.com/2026/09/09/boulder-chamber-takes-measured-approach-2026/"
DSA_SEPT9 = "https://www.instagram.com/p/DdFbfKijZtU/"
BRL_SEPT16 = ("https://boulderreportinglab.org/2026/09/16/"
              "boulder-mayoral-candidate-aquiles-la-grave-faces-lawsuit-and-campaign-finance-complaint/")

# Edge index -> (source_url, source_title, published_on, replacement notes or None).
# Used when the cited page is dead, or when the endorser's own page exists
# (preferred over a repost). published_on is only what the page itself states.
SOURCE_CORRECTIONS: dict[int, tuple[str, str, str | None, str | None]] = {}
_PLAN_T = "2026 Candidate Endorsements (PLAN-Boulder County)"
SOURCE_CORRECTIONS[0] = (PLAN_2026, _PLAN_T, "2026-09-28",
                         "Mayor, ranked-choice first choice ('We are ranking Aquiles as our first and strongest choice'). "
                         "The originally cited planboulder.org/plan-boulder-county-endorsements page now returns 404 and was never archived.")
SOURCE_CORRECTIONS[1] = (PLAN_2026, _PLAN_T, "2026-09-28",
                         "Mayor, ranked-choice second choice ('and Taishya as our second choice'). "
                         "The originally cited planboulder.org/plan-boulder-county-endorsements page now returns 404 and was never archived.")
for _i in range(2, 7):
    SOURCE_CORRECTIONS[_i] = (PLAN_2026, _PLAN_T, "2026-09-28",
                              "City Council endorsement. The originally cited planboulder.org/plan-boulder-county-endorsements "
                              "page now returns 404 and was never archived.")
for _i in range(7, 13):
    SOURCE_CORRECTIONS[_i] = (BP_SLATE, "Announcing BP's Strongest Slate Ever for 2026 Election (Boulder Progressives)",
                              "2026-08-19", None)
for _i in range(14, 20):
    SOURCE_CORRECTIONS[_i] = (BP_MEASURES, "Our 2026 ballot measure positions (Boulder Progressives)", "2026-09-16",
                              "VOTE YES on the group's own ballot-measure post. BP also took statewide positions (not recorded here).")
for _i in range(26, 30):
    SOURCE_CORRECTIONS[_i] = (CHAMBER_RELEASE, "Boulder Chamber takes measured approach to 2026 ballot measures (Boulder Chamber)",
                              "2026-09-09", None)
SOURCE_CORRECTIONS[68] = (DSA_SEPT9, "@boulderdsa on Instagram: DSA endorses Taishya Adams and Jamillah Richmond", "2026-09-09",
                          "Boulder County DSA's own post: 'proud to endorse Taishya Adams ... for Boulder Mayor, Jamillah Richmond "
                          "... for Boulder City Council'. The account is the one linked from boulderdsa.org.")
SOURCE_CORRECTIONS[204] = SOURCE_CORRECTIONS[68][:3] + (
    "Boulder County DSA's own post endorses Adams for mayor. Its Sept. 15 post says 'Rank @adamsforboulder first for Mayor' "
    "(https://www.instagram.com/reel/DdUvpOWtXXN/).",)

# Edge index -> provenance forced by the verification (endorser's own source found).
PROVENANCE_UPGRADES = {68: "endorser_statement", 204: "endorser_statement"}

# Endorser-statement sources NOT on the endorser's own website, with why they
# still count as the endorser's own words. Anything else must be on the
# endorser's website (tests enforce this).
AUTHORED_ELSEWHERE = {
    "yellowscene.com/2026/08/21/": "verbatim_press_release",
    "yellowscene.com/2026/09/17/": "verbatim_press_release",
    "yellowscene.com/2026/09/19/": "verbatim_press_release",
    "yellowscene.com/2026/09/20/": "verbatim_press_release",
    "yellowscene.com/2026/09/12/": "verbatim_press_release",
    "instagram.com/p/DdFbfKijZtU": "endorser_social_account",
    "boulderreportinglab.org/2026/08/30/kc-becker": "signed_op_ed",
}

# Organization websites missing from the research file.
ORG_WEBSITE = {"boulder-county-dsa": "https://boulderdsa.org/"}

# Person-endorser titles corrected against the official government roster
# (the campaign page's wording was wrong for the kind of government).
TITLE_CORRECTIONS = {
    "kris-larsen": ("Nederland town trustee", "https://www.nederlandco.org/1231/Board-of-Trustees"),
    "emily-baer": ("Erie town councilmember", "https://erieco.gov/318/Town-Council"),
    "stephanie-miller": ("Superior town councilmember",
                         "https://www.superiorcolorado.gov/Government/Town-Council/Town-Council/Stephanie-Miller-Council-Member"),
}

# Person endorsers added by this pass (no profile in the research file).
NEW_PERSON_PROFILES = [
    ("guyleen-castriotta", "Guyleen Castriotta", "Broomfield mayor", "https://www.broomfield.org/2694/Mayor-Guyleen-Castriotta",
     "Guyleen Castriotta is listed as Mayor of Broomfield on Tara Winer's 2026 endorsement page. This is a personal endorsement, not one made by the office.",
     ["https://www.taraforboulder.com/endorsements/content/endorsers/"]),
    ("andrea-meneghel", "Andrea Meneghel", "Open Boulder board member", BRL_SEPT16,
     "Boulder Reporting Lab (Sept. 16, 2026) describes Andrea Meneghel as an Open Boulder board member who endorsed Aquiles La Grave individually. Not an elected office.",
     [BRL_SEPT16]),
]

# Edges added by this pass. The research update file supplies U1-U4.
UPDATE_EDGE_IDS = ["U1", "U2", "U3", "U4"]
NEW_EDGES = [
    {"id": "N1", "endorser": "PLAN-Boulder County", "endorser_type": "organization", "endorser_slug": "plan-boulder-county",
     "candidate": None, "measure": "Boulder County Question 200: Expand Board of Commissioners to Five", "position": "endorse",
     "provenance": "endorser_statement", "claimed_by": None, "source_url": PLAN_BALLOT_2026,
     "source_title": "2026 Ballot Issue Endorsements (PLAN-Boulder County)", "published_on": "2026-09-27",
     "notes": "PLAN-Boulder's own page: 'Boulder County Ballot Question 200 - Yes'. PLAN also says No on statewide Proposition 137 (not recorded here)."},
    {"id": "B1", "endorser": "Jan Burton", "endorser_type": "person", "endorser_slug": "jan-burton",
     "candidate": "Aquiles La Grave", "measure": None, "position": "endorse",
     "provenance": "news_report", "claimed_by": "Boulder Reporting Lab (Sept. 16 report)", "source_url": BRL_SEPT16,
     "source_title": "Boulder mayoral candidate Aquiles La Grave faces lawsuit and campaign finance complaint (Boulder Reporting Lab)",
     "published_on": "2026-09-16",
     "notes": "BRL: 'Burton and another Open Boulder board member, Andrea Meneghel, have endorsed him individually.' Burton is also a La Grave campaign adviser. Open Boulder itself made no mayoral endorsement."},
    {"id": "B2", "endorser": "Andrea Meneghel", "endorser_type": "person", "endorser_slug": "andrea-meneghel",
     "candidate": "Aquiles La Grave", "measure": None, "position": "endorse",
     "provenance": "news_report", "claimed_by": "Boulder Reporting Lab (Sept. 16 report)", "source_url": BRL_SEPT16,
     "source_title": "Boulder mayoral candidate Aquiles La Grave faces lawsuit and campaign finance complaint (Boulder Reporting Lab)",
     "published_on": "2026-09-16",
     "notes": "BRL: 'Burton and another Open Boulder board member, Andrea Meneghel, have endorsed him individually.' Open Boulder itself made no mayoral endorsement."},
]

# Measure positions that appear only in measures_2026.json (not in the edge
# file). Added as edges so the measure pages and the endorser pages agree.
EXTRA_MEASURE_EDGES = [
    {
        "id": "M1",
        "endorser": "KC Becker",
        "endorser_type": "person",
        "endorser_slug": "kc-becker",
        "measure_letter": "2K",
        "position": "oppose",
        "provenance": "endorser_statement",
        "source_url": "https://boulderreportinglab.org/2026/08/30/kc-becker-boulder-deserves-a-better-bond-proposal-not-a-400-million-blank-check",
        "source_title": "KC Becker: Boulder deserves a better bond proposal, not a $400 million blank check (opinion, Boulder Reporting Lab)",
        "published_on": "2026-08-30",
        "notes": "Signed opinion commentary by KC Becker, published by Boulder Reporting Lab. Listed as an opponent in the research measures file.",
    },
]

# Audit PASS records (sampled and verified against the live page).
AUDIT_PASS_EDGES = {0, 1, 7, 13, 14, 15, 20, 26, 27, 30, 38, 41, 46, 52}

# --- rule 6: ranked-choice order, from the source wording in each edge's notes
RANK = {0: 1, 1: 2, 46: 1, 47: 2, 204: 1}

# Extra notes the audit asked for, appended to the edge's own notes.
EXTRA_NOTES = {
    52: "The labor council's release says \"Vote No on 3to5 Commissioners\"; the Question 200 label comes from other election coverage, not the release itself.",
    20: "The release's 'nod' to Taishya Adams for additional ranked-choice picks is not a formal endorsement and is not recorded as one.",
    13: "Aug. 18 release recognized/supported her; the Sept. 12 release confers full endorsement.",
}

# Ballot campaigns (not candidates) whose support pages list third parties.
MEASURE_CAMPAIGN_DOMAINS = {
    "bouldervacancytax.org": ("Vacancy to Vitality", "vacancy-to-vitality"),
    "strongerboulder.com": ("Boulder Firefighters for a Stronger Boulder", "boulder-firefighters-stronger-boulder"),
}

FILING_DOMAINS = {"webapps.bouldercolorado.gov"}

MEASURE_LETTER = {
    "City of Boulder Ballot Issue 2J": "2J",
    "City of Boulder Ballot Issue 2K": "2K",
    "City of Boulder Ballot Question 2L": "2L",
    "City of Boulder Ballot Question 2M": "2M",
}

# Sponsoring / funding relationships between organizations (sourced to the
# committee filing or disclosure that establishes them).
ORG_RELATIONS = [
    ("boulder-progressives-ucc", "boulder-progressives", "registered candidate committee of"),
    ("open-boulder-2026-ucc", "open-boulder", "registered candidate committee of"),
    ("open-boulder-ieo", "open-boulder", "independent-expenditure filer registered under the name of"),
    ("boulder-firefighters-stronger-boulder", "boulder-firefighters-local-900", "ballot committee funded mainly by"),
]

# --- endorser weight: grouping, never scoring -------------------------------
ELECTED_WORDS = (
    "mayor", "councilmember", "senator", "representative", "commissioner",
    "district attorney", "board of education", "house speaker", "senate president",
    "rtd board", "town trustee", "town councilmember",
)


def weight_group(kind: str, title: str | None) -> str:
    """organization | current_elected | former_elected | other_individual.

    Uses only the title printed on the cited page. No title -> other_individual.
    Appointed or unclear posts (library trustee, nominee, candidate) are not
    promoted to 'elected'.
    """
    if kind != "person":
        return "organization"
    t = (title or "").lower().strip()
    if not t:
        return "other_individual"
    first = t.split(";")[0].strip()
    if "nominee" in first or first.endswith("candidate") or ("trustee" in first and "town trustee" not in first):
        return "other_individual"
    elected = any(w in first for w in ELECTED_WORDS)
    if not elected:
        return "other_individual"
    return "former_elected" if first.startswith("former") else "current_elected"


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("BV_RESEARCH", ROOT.parent / "bv-research"))
    cands = json.loads((src / "candidates_2026.json").read_text())
    edges = json.loads((src / "endorsements_2026.json").read_text())
    orgs = json.loads((src / "organizations.json").read_text())
    measures = json.loads((src / "measures_2026.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)

    assert len(cands) == 19, len(cands)
    assert len(edges) == 236, len(edges)

    # ---------------- candidates + statements ----------------
    campaign_owner: dict[str, str] = {}
    out_cands, out_stmts = [], []
    for c in cands:
        name = c["name"]
        shown = DISPLAY_NAME.get(name, name)
        if c.get("campaign_url"):
            campaign_owner[domain(c["campaign_url"])] = shown
        out_cands.append({
            "name": shown,
            "research_name": name,
            "race": c["race"],
            "campaign_url": c.get("campaign_url"),
            "bio": c["bio"],
            "notes": c.get("notes") or "",
        })
        for i, s in enumerate(c["statements"]):
            held = HELD_STATEMENTS.get((name, i))
            speaker = s["speaker_or_reporter"]
            out_stmts.append({
                "id": f"S-{shown.lower().replace(' ', '-')}-{i}",
                "candidate": shown,
                "topic": s["topic"],
                "text": s["text"],
                "verbatim": bool(s["verbatim"]),
                "speaker": speaker,
                "speaker_is_candidate": speaker == name,
                "publisher": s["publisher"],
                "source_url": s["source_url"],
                "source_title": s["source_title"],
                "published_on": s["published_on"],
                "kind": s["kind"],
                "status": "held" if held else "published",
                "hold_reason": held,
            })
    held_found = {(s["candidate"], s["id"]) for s in out_stmts if s["status"] == "held"}
    assert len(held_found) == len(HELD_STATEMENTS), held_found
    for (name, i), _ in HELD_STATEMENTS.items():
        c = next(x for x in cands if x["name"] == name)
        assert "dailycamera.com" in c["statements"][i]["source_url"], (name, i)

    # ---------------- organizations / endorser profiles ----------------
    orgs = list(orgs)
    have_slugs = {o["slug"] for o in orgs}
    for slug, name, role, role_src, summary, sources in NEW_PERSON_PROFILES:
        if slug in have_slugs:
            continue
        orgs.append({
            "slug": slug, "name": name, "kind": "person", "website": None, "legal_form": None,
            "mission_quote": {"text": "", "source_url": ""}, "founded": None,
            "leadership": [{"name": name, "role": role, "source_url": role_src}],
            "funding": None, "endorsement_process": None, "past_endorsements": [],
            "summary": summary, "sources": sources,
        })
    by_slug = {o["slug"]: o for o in orgs}
    out_orgs = []
    for o in orgs:
        o = json.loads(json.dumps(o))  # deep copy
        o["name"] = DISPLAY_NAME.get(o["name"], o["name"])
        if o["slug"] in ORG_WEBSITE and not o.get("website"):
            o["website"] = ORG_WEBSITE[o["slug"]]
        if o["slug"] in TITLE_CORRECTIONS and o["leadership"]:
            role, role_src = TITLE_CORRECTIONS[o["slug"]]
            o["summary"] = o["summary"].replace(o["leadership"][0]["role"], role, 1) + (
                f" Title corrected to the official roster ({VERIFIED_ON}); the campaign page's wording differed.")
            o["leadership"][0]["role"] = role
            o["leadership"][0]["source_url"] = role_src
        title = title_src = None
        if o["kind"] == "person":
            if o["leadership"]:
                title = o["leadership"][0].get("role") or None
                title_src = o["leadership"][0].get("source_url") or None
            o["title"] = title
            o["title_source_url"] = title_src
        # rule 4: Richmond's Boulder Progressives board role is dated, not current
        for l in o.get("leadership") or []:
            l["current"] = True
            l["as_of"] = AUDIT_DATE
            if o["slug"] == "boulder-progressives" and l["name"] == "Jamillah Richmond":
                l["current"] = False
                l["as_of"] = "2026-09-12"
                l["role"] = "Board member (as described in the group's Aug. 18 and Sept. 12, 2026 releases)"
                l["note"] = ("Not listed on the group's board page as of Sept. 24, 2026; "
                             "her present role is unconfirmed. Historical listing, not current leadership.")
        o["weight_group"] = weight_group(o["kind"], title)
        o["related"] = [
            {"slug": b, "relation": rel,
             "source_url": (o.get("mission_quote") or {}).get("source_url") or (o.get("funding") or {}).get("source_url")}
            for a, b, rel in ORG_RELATIONS if a == o["slug"]
        ]
        if o["slug"] == "boulder-firefighters-stronger-boulder" and o["related"]:
            o["related"][0]["source_url"] = (o.get("funding") or {}).get("source_url") or o["related"][0]["source_url"]
        out_orgs.append(o)

    # ---------------- endorsements ----------------
    ledger = {x["id"]: x for x in json.loads((src / "endorsement_verification_2026.json").read_text())}
    update = {f"U{k + 1}": x for k, x in enumerate(json.loads((src / "endorsements_2026_update.json").read_text()))}
    assert list(update) == UPDATE_EDGE_IDS, list(update)
    edges = [dict(e) for e in edges]
    for i, (url, title, pub, note) in SOURCE_CORRECTIONS.items():
        edges[i].update(source_url=url, source_title=title, published_on=pub)
        if note:
            edges[i]["notes"] = note
    out_edges = []
    work = [(f"E{i}", i, e) for i, e in enumerate(edges)] + [(k, None, e) for k, e in update.items()]
    for eid, i, e in work:
        d = domain(e["source_url"])
        target = e["candidate"]
        target = DISPLAY_NAME.get(target, target) if target else None
        claimed_by = None
        if d in FILING_DOMAINS:
            prov = "filing"
        elif d in campaign_owner:
            prov = "campaign_claim"
            claimed_by = f"{campaign_owner[d]} campaign"
            assert target == campaign_owner[d], (i, target, d)
        elif d in MEASURE_CAMPAIGN_DOMAINS and MEASURE_CAMPAIGN_DOMAINS[d][1] != e["endorser_slug"]:
            prov = "campaign_claim"
            claimed_by = f"{MEASURE_CAMPAIGN_DOMAINS[d][0]} (ballot campaign)"
        else:
            prov = "endorser_statement"
        if i in NEWS_REPORT_EDGES:
            prov = "news_report"
            claimed_by = NEWS_REPORT_EDGES[i]
        if i in PROVENANCE_UPGRADES:
            prov = PROVENANCE_UPGRADES[i]
            claimed_by = None
        if i is None:
            assert prov == e["provenance"], (eid, prov, e["provenance"])
        if i in AUDIT_HELD_EDGES:
            assert prov == "campaign_claim", (i, prov)
        letter = None
        label = None
        if e["measure"]:
            for k, v in MEASURE_LETTER.items():
                if e["measure"].startswith(k):
                    letter = v
            if not letter:
                label = e["measure"]
        notes = (e.get("notes") or "").strip()
        if i in EXTRA_NOTES and EXTRA_NOTES[i] not in notes:
            notes = (notes + " " + EXTRA_NOTES[i]).strip()
        audit = None
        if i in AUDIT_HELD_EDGES:
            audit = {"result": "hold_as_campaign_claim", "note": AUDIT_HELD_EDGES[i]}
        elif i in AUDIT_PASS_EDGES:
            audit = {"result": "pass", "note": "Checked against the live cited page, Sept. 24, 2026."}
        endorser = e["endorser"]
        endorser = DISPLAY_NAME.get(endorser, endorser)
        out_edges.append({
            "id": eid,
            "endorser": endorser,
            "endorser_type": e["endorser_type"],
            "endorser_slug": e["endorser_slug"],
            "candidate": target,
            "measure_letter": letter,
            "measure_label": label,
            "position": e["position"],
            "rank": RANK.get(i) if i is not None else None,
            "provenance": prov,
            "claimed_by": claimed_by,
            "source_url": e["source_url"],
            "source_title": e["source_title"],
            "published_on": e["published_on"],
            "status": "published",
            "audit": audit,
            "notes": notes,
        })
        assert e["endorser_slug"] in by_slug, e["endorser_slug"]

    have = {(x["endorser_slug"], x["measure_letter"], x["position"]) for x in out_edges if x["measure_letter"]}
    for x in EXTRA_MEASURE_EDGES:
        assert x["endorser_slug"] in by_slug
        if (x["endorser_slug"], x["measure_letter"], x["position"]) in have:
            continue
        out_edges.append({
            **{k: x[k] for k in ("id", "endorser", "endorser_type", "endorser_slug", "measure_letter",
                                 "position", "provenance", "source_url", "source_title", "published_on", "notes")},
            "candidate": None, "measure_label": None, "rank": None, "claimed_by": None,
            "status": "published", "audit": None,
        })
    for x in NEW_EDGES:
        assert x["endorser_slug"] in by_slug, x["endorser_slug"]
        letter = next((v for k, v in MEASURE_LETTER.items() if (x["measure"] or "").startswith(k)), None)
        out_edges.append({
            **{k: x[k] for k in ("id", "endorser", "endorser_type", "endorser_slug", "candidate", "position",
                                 "provenance", "claimed_by", "source_url", "source_title", "published_on", "notes")},
            "measure_letter": letter, "measure_label": None if letter or not x["measure"] else x["measure"],
            "rank": None, "status": "published", "audit": None,
        })

    # Sept. 29 verification: every edge carries its ledger entry; REMOVE drops it
    # from the published graph (kept in the ledger as the record).
    ids = [x["id"] for x in out_edges]
    assert len(ids) == len(set(ids)), "duplicate edge ids"
    assert set(ids) == set(ledger), (set(ids) ^ set(ledger))
    for x in out_edges:
        v = ledger[x["id"]]
        x["verification"] = {k: v[k] for k in ("result", "checked_on", "evidence_url", "note")}
        if v["result"] == "REMOVE":
            x["status"] = "removed"
    shutil.copyfile(src / "endorsement_verification_2026.json", OUT / "endorsement_verification.json")

    (OUT / "candidates.json").write_text(json.dumps(out_cands, indent=1, ensure_ascii=False) + "\n")
    (OUT / "statements.json").write_text(json.dumps(out_stmts, indent=1, ensure_ascii=False) + "\n")
    (OUT / "endorsements.json").write_text(json.dumps(out_edges, indent=1, ensure_ascii=False) + "\n")
    (OUT / "organizations.json").write_text(json.dumps(out_orgs, indent=1, ensure_ascii=False) + "\n")
    (OUT / "measures.json").write_text(json.dumps(measures, indent=1, ensure_ascii=False) + "\n")
    shutil.copyfile(src / "civics101.md", OUT / "civics101.md")

    prov = Counter(x["provenance"] for x in out_edges)
    groups = Counter(by_slug[x["endorser_slug"]]["kind"] for x in out_edges)
    wg = Counter(next(o for o in out_orgs if o["slug"] == x["endorser_slug"])["weight_group"] for x in out_edges)
    st = Counter(s["status"] for s in out_stmts)
    print(f"candidates={len(out_cands)} statements={dict(st)} endorsements={len(out_edges)} "
          f"provenance={dict(prov)} endorser_kind={dict(groups)} weight_group={dict(wg)} profiles={len(out_orgs)}")


if __name__ == "__main__":
    main()
