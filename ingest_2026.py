"""Load the approved 2026 evidence graph from data/harvest/2026/*.json.

Nothing in here is hand-typed fact: every row comes from the committed JSON,
which tools/approve_2026.py produces from the research files after applying the
audit's decisions. Rows with status='held' are loaded (so the hold is on the
record) but never rendered.
"""
from __future__ import annotations

import json
from pathlib import Path

H2026 = Path(__file__).resolve().parent / "data" / "harvest" / "2026"

# research display name -> people.full_name used by other harvests
NAME_ALIASES = {"David Martus": "Dave Martus"}

MEASURE_SLUG = {
    "2J": "2026-vacancy-excise-tax",
    "2K": "2026-rec-safety-bond",
    "2L": "2026-firefighter-cba-charter",
    "2M": "2026-debt-limit-charter",
}

PROVENANCE_SOURCE_KIND = {
    "campaign_claim": "campaign_site",
    "filing": "official",
    "endorser_statement": "article",
    "news_report": "article",
}


def load(name: str):
    return json.loads((H2026 / name).read_text(encoding="utf-8"))


def _norm(url: str) -> str:
    return url.rstrip("/")


def ingest_2026_graph(cur, *, pid: dict, add_person, add_source, slugify) -> dict:
    """Returns counts for the seed summary line."""
    cands = load("candidates.json")
    stmts = load("statements.json")
    edges = load("endorsements.json")
    profiles = load("organizations.json")
    measures = load("measures.json")

    # ---- sources: one row per URL; trailing-slash variants share a row ----
    def src(url: str, title: str | None, kind: str, published_on: str | None = None) -> int:
        if not url:
            raise ValueError("source url required")
        for u in (url, _norm(url), _norm(url) + "/"):
            cur.execute("SELECT id FROM sources WHERE url=?", (u,))
            row = cur.fetchone()
            if row:
                if title:  # a real title beats a URL placeholder from a profile list
                    cur.execute("UPDATE sources SET title=? WHERE id=? AND title=url", (title, row[0]))
                return row[0]
        return add_source(url, title or url, kind, 2026, None, published_on)

    def candidacy(name: str) -> int:
        cur.execute(
            """SELECT c.id FROM candidacies c JOIN people p ON p.id=c.person_id
               JOIN races r ON r.id=c.race_id JOIN elections e ON e.id=r.election_id
               WHERE p.full_name=? AND e.year=2026""",
            (NAME_ALIASES.get(name, name),),
        )
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"2026 candidacy not found: {name}")
        return row[0]

    def person_id(name: str) -> int:
        name = NAME_ALIASES.get(name, name)
        if name not in pid:
            pid[name] = add_person(name)
        return pid[name]

    # ---- candidate profiles ----
    for c in cands:
        cid = candidacy(c["name"])
        b = c["bio"]
        cur.execute(
            """INSERT INTO candidate_profiles
               (candidacy_id, summary, occupation, years_in_boulder, prior_office, research_notes)
               VALUES (?,?,?,?,?,?)""",
            (cid, b.get("summary"), b.get("occupation"), b.get("years_in_boulder"),
             b.get("prior_office"), c.get("notes") or None),
        )
        for u in b.get("sources") or []:
            sid = src(u, f"Profile source: {c['name']}", "article")
            cur.execute("INSERT INTO profile_sources (candidacy_id, source_id) VALUES (?,?)", (cid, sid))
        if c.get("campaign_url"):
            cur.execute("UPDATE candidacies SET campaign_url=COALESCE(campaign_url, ?) WHERE id=?",
                        (c["campaign_url"], cid))

    # ---- statements ----
    for s in stmts:
        cid = candidacy(s["candidate"])
        cur.execute("SELECT person_id FROM candidacies WHERE id=?", (cid,))
        p = cur.fetchone()[0]
        sid = src(s["source_url"], s["source_title"],
                  "campaign_site" if s["kind"] == "campaign_site" else
                  "questionnaire" if s["kind"] == "questionnaire" else "article",
                  s.get("published_on"))
        cur.execute(
            """INSERT INTO statements
               (id, candidacy_id, person_id, topic, text, verbatim, speaker, speaker_is_candidate,
                publisher, source_id, published_on, kind, status, hold_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (s["id"], cid, p, s["topic"], s["text"], int(s["verbatim"]), s["speaker"],
             int(s["speaker_is_candidate"]), s["publisher"], sid, s.get("published_on"),
             s["kind"], s["status"], s.get("hold_reason")),
        )

    # ---- organizations + person endorsers ----
    org_ids: dict[str, int] = {}
    person_by_slug: dict[str, int] = {}
    for o in profiles:
        if o["kind"] == "person":
            p = person_id(o["name"])
            person_by_slug[o["slug"]] = p
            if o.get("title"):
                tsid = src(o["title_source_url"], None, "campaign_site")
                cur.execute(
                    """INSERT INTO person_titles (person_id, title, weight_group, source_id, as_of)
                       VALUES (?,?,?,?,?)""",
                    (p, o["title"], o["weight_group"], tsid, "2026-09-24"),
                )
            for u in o.get("sources") or []:
                cur.execute("INSERT INTO profile_sources (person_id, source_id) VALUES (?,?)",
                            (p, src(u, None, "article")))
            continue
        cur.execute("SELECT id FROM organizations WHERE slug=?", (o["slug"],))
        row = cur.fetchone()
        if row:
            oid = row[0]
            if o.get("website"):
                cur.execute("UPDATE organizations SET website=? WHERE id=?", (o["website"], oid))
        else:
            kind = {"committee": "committee", "newspaper": "newspaper"}.get(o["kind"], "advocacy")
            cur.execute(
                "INSERT INTO organizations (slug, name, kind, website) VALUES (?,?,?,?)",
                (o["slug"], o["name"], kind, o.get("website")),
            )
            oid = cur.lastrowid
        org_ids[o["slug"]] = oid

        def txt(block):
            if not block or not (block.get("text") or "").strip():
                return None, None
            u = block.get("source_url")
            return block["text"], (src(u, None, "article") if u else None)

        m_text, m_src = txt(o.get("mission_quote"))
        f_text, f_src = txt(o.get("funding"))
        p_text, p_src = txt(o.get("endorsement_process"))
        cur.execute(
            """INSERT INTO org_profiles
               (org_id, endorser_kind, legal_form, founded, summary, mission_text, mission_source_id,
                funding_text, funding_source_id, process_text, process_source_id, as_of)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (oid, o["kind"], o.get("legal_form"), o.get("founded"), o.get("summary"),
             m_text, m_src, f_text, f_src, p_text, p_src, "2026-09-24"),
        )
        for l in o.get("leadership") or []:
            if not l.get("source_url"):
                continue
            lp = pid.get(NAME_ALIASES.get(l["name"], l["name"]))
            cur.execute(
                """INSERT INTO org_leadership (org_id, name, person_id, role, is_current, as_of, source_id, notes)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (oid, l["name"], lp, l.get("role"), int(l.get("current", True)), l.get("as_of"),
                 src(l["source_url"], None, "article"), l.get("note")),
            )
        for pe in o.get("past_endorsements") or []:
            if not pe.get("source_url"):
                continue
            cur.execute(
                "INSERT INTO org_past_endorsements (org_id, year, label, source_id) VALUES (?,?,?,?)",
                (oid, pe["year"], pe["candidate_or_measure"], src(pe["source_url"], None, "article")),
            )
        for u in o.get("sources") or []:
            cur.execute("INSERT INTO profile_sources (org_id, source_id) VALUES (?,?)",
                        (oid, src(u, None, "article")))
    for o in profiles:
        for r in o.get("related") or []:
            if o["slug"] in org_ids and r["slug"] in org_ids:
                cur.execute(
                    "INSERT INTO org_relations (org_id, related_org_id, relation, source_id) VALUES (?,?,?,?)",
                    (org_ids[o["slug"]], org_ids[r["slug"]], r["relation"],
                     src(r["source_url"], None, "official") if r.get("source_url") else None),
                )

    # ---- city measures: fill letters, full language, details ----
    mids: dict[str, int] = {}
    for m in measures["city_measures"]:
        slug = MEASURE_SLUG[m["id"]]
        cur.execute("SELECT id FROM measures WHERE slug=?", (slug,))
        mid = cur.fetchone()[0]
        mids[m["id"]] = mid
        lang_src = src(m["ballot_language_source_url"], "2026 City of Boulder Ballot Measures", "official")
        cur.execute(
            "UPDATE measures SET letter=?, ballot_language=?, status='on_ballot' WHERE id=?",
            (m["id"], m["ballot_language"], mid),
        )
        fiscal = m.get("fiscal") or {}
        vote = m.get("council_vote") or {}
        cur.execute(
            """INSERT INTO measure_details
               (measure_id, plain_summary, yes_means, no_means, fiscal_text, fiscal_source_id,
                council_vote_text, council_vote_source_id, language_source_id, unknowns)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (mid, m.get("plain_summary"), m.get("what_yes_means"), m.get("what_no_means"),
             fiscal.get("text"), src(fiscal["source_url"], None, "official") if fiscal.get("source_url") else None,
             vote.get("text"), src(vote["source_url"], None, "article") if vote.get("source_url") else None,
             lang_src,
             json.dumps([u for u in measures.get("unknowns", []) if m["id"] in u])),
        )

    # ---- endorsement edges ----
    for e in edges:
        org = org_ids.get(e["endorser_slug"])
        per = person_by_slug.get(e["endorser_slug"]) if org is None else None
        if org is None and per is None:
            raise SystemExit(f"unknown endorser {e['endorser_slug']}")
        cand = candidacy(e["candidate"]) if e.get("candidate") else None
        mid = mids.get(e["measure_letter"]) if e.get("measure_letter") else None
        label = e.get("measure_label") if cand is None and mid is None else None
        sid = src(e["source_url"], e["source_title"], PROVENANCE_SOURCE_KIND[e["provenance"]], e.get("published_on"))
        audit = e.get("audit") or {}
        cur.execute(
            """INSERT INTO endorsements
               (id, endorser_org_id, endorser_person_id, candidacy_id, measure_id, target_label,
                position, rank, provenance, claimed_by, source_id, published_on, status,
                audit_result, audit_note, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (e["id"], org, per, cand, mid, label, e["position"], e.get("rank"), e["provenance"],
             e.get("claimed_by"), sid, e.get("published_on"), e["status"],
             audit.get("result"), audit.get("note"), e.get("notes") or None),
        )

    cur.execute("SELECT COUNT(*) FROM endorsements")
    n_e = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM statements WHERE status='published'")
    n_s = cur.fetchone()[0]
    return {"endorsements": n_e, "statements_published": n_s, "orgs": len(org_ids)}


def civics_markdown() -> str:
    return (H2026 / "civics101.md").read_text(encoding="utf-8")
