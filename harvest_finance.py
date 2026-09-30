#!/usr/bin/env python3
"""Harvest City of Boulder 2026 committee filings into data/harvest/.

The live clerk app serves HTML with no JS required for the numbers:
  committee list  → committeeFilings.php
  per-committee   → committeeFilings.php?action=04&committeeID=
  itemized CandE  → report.php?report=CandE&statementID=
  cycle totals    → report.php?report=CandESummary&electionID=25

Past electionIDs on this app all return the 2026 table. Historical Laserfiche
is a JS/cookie archive and is not harvested here.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import ssl
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "harvest" / "finance_2026.json"
BASE = "https://webapps.bouldercolorado.gov/election/"
UA = "BoulderVotes harvest (bouldervotes.org; civic record, not a campaign)"

# Clerk's candidate-name field → people.full_name in seed.py.
# Names not in seed stay person=None (filed a committee, not on our certified list).
PERSON_ALIASES = {
    "jameson goldstein": "Jameson Goldstein",
    "aaron brockett": "Aaron Brockett",
    "aquiles la grave": "Aquiles La Grave",
    "benita duran": "Benita Duran",
    "david martus": "David Martus",
    "lisa jacobs": "Lisa Ann Jacobs",
    "lisa ann jacobs": "Lisa Ann Jacobs",
    "ryan schuchard": "Ryan Schuchard",
    "michael smith": "Fred Smith",
    "fred smith": "Fred Smith",
    "ryan jamieson": "Ryan Jamieson",
    "jamillah richmond": "Jamillah Richmond",
    "jill grano": "Jill Grano",
    "lee gilbert": "Lee Gilbert",
    "rachel isaacson": "Rachel Rose Isaacson",
    "rachel rose isaacson": "Rachel Rose Isaacson",
    "david rendleman": "Scott Rendleman",
    "scott rendleman": "Scott Rendleman",
    "samuel fuqua": "Sam Fuqua",
    "sam fuqua": "Sam Fuqua",
    "lynn segal": "Lynn Segal",
    "tara winer": "Tara Winer",
    "christina marquis": "Tina Marquis",
    "tina marquis": "Tina Marquis",
    "taishya adams": "Taishya Adams",
}


# The clerk server does not send its DigiCert intermediate, so strict clients
# fail verification. Add that public intermediate (committed, from
# cacerts.digicert.com) to the normal trust store; verification stays on.
INTERMEDIATE = ROOT / "data" / "certs" / "digicert-global-g2-tls-rsa-sha256-2020-ca1.pem"


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if INTERMEDIATE.exists():
        ctx.load_verify_locations(cafile=str(INTERMEDIATE))
    return ctx


_CTX = _ssl_context()


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30, context=_CTX) as resp:
        return resp.read().decode("utf-8", errors="replace")


def money(s: str) -> float | None:
    s = (s or "").strip().replace("$", "").replace(",", "").replace("&nbsp;", "")
    if not s or s.lower() in {"date unavailable", "n/a"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def iso_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s or s.lower() == "date unavailable":
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    s = s.replace("&quot;", '"')
    return re.sub(r"\s+", " ", s).strip()


class TableParser(HTMLParser):
    """Collect tables as lists of rows of cell text.

    Clerk HTML nests <table> and sometimes never closes them. Keep a stack so
    an inner <table> does not wipe the outer rows.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._stack: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._in_cell = True
        elif tag == "br" and self._in_cell and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
            self._in_cell = False
        elif tag == "tr" and self._stack and self._row is not None:
            if any(self._row):
                self._stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._cell is not None:
            self._cell.append(data)

    def close(self) -> None:
        while self._stack:
            self.tables.append(self._stack.pop())
        super().close()


def parse_tables(html: str) -> list[list[list[str]]]:
    p = TableParser()
    p.feed(html)
    p.close()
    return p.tables


def rows_from_section(html: str, heading: str) -> list[list[str]]:
    """Rows in the table that follows an <h3>heading</h3>, until the next h3.

    Regex-based because the clerk's contributions/expenditures tables are often
    left unclosed, which makes a tree parser skip or merge them.
    """
    parts = re.split(r"<h3>(.*?)</h3>", html, flags=re.I | re.S)
    chunk = None
    for i in range(1, len(parts), 2):
        if heading.lower() in clean(parts[i]).lower():
            chunk = parts[i + 1] if i + 1 < len(parts) else ""
            break
    if not chunk:
        return []
    rows: list[list[str]] = []
    for row_html in re.findall(r"<tr>(.*?)</tr>", chunk, flags=re.I | re.S):
        cells = [
            clean(c)
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.I | re.S)
        ]
        if cells:
            rows.append(cells)
    return rows


def person_for(clerk_name: str) -> str | None:
    key = re.sub(r"\s+", " ", clerk_name).strip().lower()
    key = key.strip("\"'")
    return PERSON_ALIASES.get(key)


def parse_committee_list(html: str) -> list[dict]:
    """Rows from committeeFilings.php, tagged by the section heading above them."""
    kind = "unknown"
    out: list[dict] = []
    # The list is one table; section headers are <th colspan="2">Kind</th>.
    for table in parse_tables(html):
        for row in table:
            joined = " ".join(row)
            if len(row) == 1 or (len(row) == 2 and not any("committeeID=" in (c or "") for c in row)):
                label = joined.lower()
                if "official candidate" in label:
                    kind = "official_candidate"
                elif "unofficial" in label:
                    kind = "unofficial_candidate"
                elif "independent expenditure" in label:
                    kind = "independent_expenditure"
                elif "ballot measure" in label:
                    kind = "ballot_measure"
                continue
            m = re.search(r"committeeID=(\d+)", joined)
            if not m:
                # parser may have dropped the href; look at raw later
                continue
            name = row[0].strip().strip(",")
            name = re.sub(r"\s+", " ", name)
            name = re.sub(r"\s*View Available Reports\s*", "", name).strip()
            out.append({"committee_id": int(m.group(1)), "committee_name": name, "kind": kind})
    # Fallback: regex over the raw HTML so a missed href still lands.
    if not out:
        section = "unknown"
        for chunk in re.split(r"(<th[^>]*>.*?</th>|<tr>)", html, flags=re.I | re.S):
            low = chunk.lower()
            if "official candidate" in low:
                section = "official_candidate"
            elif "unofficial" in low:
                section = "unofficial_candidate"
            elif "independent expenditure" in low:
                section = "independent_expenditure"
            elif "ballot measure" in low:
                section = "ballot_measure"
            for m in re.finditer(
                r"<td>(.*?)</td>\s*<td><a href=\"committeeFilings\.php\?action=04&committeeID=(\d+)\"",
                chunk,
                re.I | re.S,
            ):
                name = clean(m.group(1)).strip().strip(",")
                out.append({"committee_id": int(m.group(2)), "committee_name": name, "kind": section})
    return out


def parse_reports_page(html: str, committee_id: int) -> dict:
    mnum = re.search(r'id="committeeNum">([^<]+)', html)
    statements = []
    for m in re.finditer(
        r'href="(report\.php\?report=CandE&statementID=(\d+))"[^>]*>([^<]+)',
        html,
    ):
        statements.append({
            "statement_id": int(m.group(2)),
            "label": clean(m.group(3)),
            "url": BASE + m.group(1).replace("&amp;", "&"),
        })
    title = re.search(r"<h2>Available Reports for (.*?)</h2>", html, re.S)
    return {
        "committee_id": committee_id,
        "committee_number": (mnum.group(1).strip() if mnum else None),
        "committee_name_on_page": clean(title.group(1)) if title else None,
        "statements": statements,
    }


def table_after_heading(html: str, heading: str) -> list[list[str]]:
    idx = html.lower().find(heading.lower())
    if idx < 0:
        return []
    tables = parse_tables(html[idx:])
    return tables[0] if tables else []


def parse_statement(html: str, meta: dict) -> dict:
    name = None
    m = re.search(r"Name of Committee:\s*(.*?)<br", html, re.I)
    if m:
        name = clean(m.group(1))
    cid = None
    m = re.search(r"Committee ID:\s*([^<]+)<br", html, re.I)
    if m:
        cid = clean(m.group(1))
    submitted = None
    m = re.search(r"Date Submitted:\s*([^<]+)<br", html, re.I)
    if m:
        submitted = iso_date(clean(m.group(1)))

    balance = {}
    for row in table_after_heading(html, "<h3>Balance</h3>"):
        if len(row) >= 3:
            key = row[0].strip().lower()
            val = money(row[-1])
            if "total contributions" in key:
                balance["contributions"] = val
            elif "matching funds" in key:
                balance["matching_received"] = val
            elif "in-kind" in key:
                balance["in_kind"] = val
            elif "total expenditures" in key:
                balance["expenditures"] = val
            elif key == "balance":
                balance["cash_on_hand"] = val

    contrib_rows = rows_from_section(html, "Contributions")
    contributions = []
    for row in contrib_rows:
        if not row or row[0].lower() in {"last name", ""}:
            continue
        if len(row) < 6:
            continue
        # Last, First, Type, FromCandidate, Date, Amount, Match, YTD, ID, Amends
        contributions.append({
            "last_name": row[0],
            "first_name": row[1] if len(row) > 1 else "",
            "contrib_type": row[2] if len(row) > 2 else "",
            "from_candidate": bool((row[3] if len(row) > 3 else "").strip()),
            "occurred_on": iso_date(row[4] if len(row) > 4 else ""),
            "amount": money(row[5] if len(row) > 5 else "") or 0.0,
            "match_amount": money(row[6] if len(row) > 6 else ""),
            "ytd_amount": money(row[7] if len(row) > 7 else ""),
            "clerk_item_id": int(row[8]) if len(row) > 8 and row[8].isdigit() else None,
            "amends_id": int(row[9]) if len(row) > 9 and row[9].isdigit() else None,
        })

    exp_rows = rows_from_section(html, "Expenditures")
    expenditures = []
    for row in exp_rows:
        if not row or row[0].lower() in {"first name", ""}:
            # header, or first-name empty is allowed for vendors — only skip header
            if row and row[0].lower() == "first name":
                continue
        if not row or (len(row) >= 2 and row[1].lower() == "last name"):
            continue
        if len(row) < 5:
            continue
        # First, Last, Purpose, Date, Amount, ID, Amends
        expenditures.append({
            "first_name": row[0],
            "last_name": row[1] if len(row) > 1 else "",
            "purpose": row[2] if len(row) > 2 else "",
            "occurred_on": iso_date(row[3] if len(row) > 3 else ""),
            "amount": money(row[4] if len(row) > 4 else "") or 0.0,
            "clerk_item_id": int(row[5]) if len(row) > 5 and row[5].isdigit() else None,
            "amends_id": int(row[6]) if len(row) > 6 and row[6].isdigit() else None,
        })

    return {
        **meta,
        "committee_name": name,
        "committee_number": cid,
        "submitted_on": submitted,
        "balance": balance,
        "contributions": contributions,
        "expenditures": expenditures,
    }


def parse_summary(html: str) -> list[dict]:
    """CandESummary: one cumulative row per committee (latest totals)."""
    tables = parse_tables(html)
    out: list[dict] = []
    # There are three tables: ballot measure, official candidate, unofficial.
    kinds = ["ballot_measure", "official_candidate", "unofficial_candidate"]
    # Identify by header cells.
    for table in tables:
        if not table:
            continue
        header = " ".join(table[0]).lower()
        kind = None
        # First row may be column names. Look at surrounding context instead.
        has_matching = "matching" in header or any("matching" in " ".join(r).lower() for r in table[:3])
        has_candidate = "candidate" in header
        if has_matching or has_candidate:
            kind = "official_candidate"
        else:
            kind = "other"
        # Better: walk rows. Skip headers. Detect by column count.
        # Official: Committee Name, Candidate | contrib | exp | matching | reported  (or 6 cols)
        for row in table:
            cells = [c.strip() for c in row]
            joined = " ".join(cells).lower()
            if "committee name" in joined or "contributions" in joined and "expenditures" in joined and len(cells) <= 6 and not re.search(r"\$|\d", cells[0] if cells else ""):
                if "matching" in joined:
                    kind = "official_candidate"
                elif "candidate" in joined:
                    kind = "official_candidate"
                continue
            if not cells or cells[0].lower() in {"committee name", ""}:
                continue
            # Official candidate rows often put committee + candidate in cell 0.
            name_cell = cells[0]
            clerk_candidate = None
            committee_name = name_cell
            # "Aaron Brockett for Mayor, Aaron Brockett" or two-line
            parts = [p.strip() for p in re.split(r",\s*", name_cell) if p.strip()]
            if len(parts) >= 2 and not parts[-1].startswith("$"):
                # last segment after comma may be the candidate
                maybe = parts[-1]
                if not maybe.startswith("C.F.E") and len(maybe.split()) <= 4:
                    clerk_candidate = maybe
                    committee_name = ", ".join(parts[:-1]) if len(parts) > 1 else parts[0]
            nums = [money(c) for c in cells[1:]]
            reported = None
            for c in cells[1:]:
                d = iso_date(c)
                if d:
                    reported = d
            # official: contrib, exp, matching, reported
            contrib = nums[0] if nums else None
            exp = nums[1] if len(nums) > 1 else None
            matching = nums[2] if kind == "official_candidate" and len(nums) > 2 else 0.0
            out.append({
                "committee_name": re.sub(r"\s+", " ", committee_name).strip().strip(","),
                "clerk_candidate": clerk_candidate,
                "kind": kind,
                "contributions": contrib or 0.0,
                "expenditures": exp or 0.0,
                "matching_received": matching or 0.0,
                "reported_on": reported,
            })
    return out


def harvest() -> dict:
    list_html = fetch(BASE + "committeeFilings.php")
    committees = parse_committee_list(list_html)
    if not committees:
        raise SystemExit("committee list parse returned 0 rows")

    summary_url = BASE + "report.php?report=CandESummary&electionID=25"
    summary_html = fetch(summary_url)
    summary_rows = parse_summary(summary_html)

    harvested = []
    for c in committees:
        reports = parse_reports_page(
            fetch(BASE + f"committeeFilings.php?action=04&committeeID={c['committee_id']}"),
            c["committee_id"],
        )
        statements = []
        latest_balance = {}
        latest_submitted = None
        contribs: dict[int, dict] = {}
        exps: dict[int, dict] = {}
        for st in reports["statements"]:
            parsed = parse_statement(fetch(st["url"]), st)
            statements.append({
                "statement_id": parsed["statement_id"],
                "label": parsed["label"],
                "url": parsed["url"],
                "submitted_on": parsed["submitted_on"],
                "balance": parsed["balance"],
                "n_contributions": len(parsed["contributions"]),
                "n_expenditures": len(parsed["expenditures"]),
            })
            if parsed.get("balance"):
                latest_balance = parsed["balance"]
            if parsed.get("submitted_on"):
                latest_submitted = parsed["submitted_on"]
            for row in parsed["contributions"]:
                cid = row.get("clerk_item_id")
                if cid is None:
                    continue
                if row.get("amends_id"):
                    contribs.pop(row["amends_id"], None)
                contribs[cid] = row
            for row in parsed["expenditures"]:
                eid = row.get("clerk_item_id")
                if eid is None:
                    continue
                if row.get("amends_id"):
                    exps.pop(row["amends_id"], None)
                exps[eid] = row

        clerk_candidate = None
        totals = None
        # match summary row by committee name (loose)
        cname = re.sub(r"\s+", " ", c["committee_name"]).strip().lower()
        for s in summary_rows:
            sname = re.sub(r"\s+", " ", s["committee_name"]).strip().lower()
            if sname == cname or sname in cname or cname in sname:
                clerk_candidate = s.get("clerk_candidate")
                totals = s
                break

        person = person_for(clerk_candidate or "") if clerk_candidate else None
        number = reports.get("committee_number") or ""
        kind = c["kind"]
        if "-UCC-" in number:
            kind = "unofficial_candidate"
        elif "-OCC-" in number:
            kind = "official_candidate"
        elif "-BMC-" in number or "-BC-" in number:
            kind = "ballot_measure"
        # Prefer the latest statement balance (cents) over the dollar-rounded summary table.
        if latest_balance:
            contrib_total = latest_balance.get("contributions")
            exp_total = latest_balance.get("expenditures")
            matching_total = latest_balance.get("matching_received")
        else:
            contrib_total = (totals or {}).get("contributions")
            exp_total = (totals or {}).get("expenditures")
            matching_total = (totals or {}).get("matching_received")
        harvested.append({
            "committee_id": c["committee_id"],
            "committee_number": reports.get("committee_number"),
            "committee_name": reports.get("committee_name_on_page") or c["committee_name"],
            "kind": kind,
            "clerk_candidate": clerk_candidate,
            "person": person,
            "reports_url": BASE + f"committeeFilings.php?action=04&committeeID={c['committee_id']}",
            "contributions_total": contrib_total,
            "expenditures_total": exp_total,
            "matching_received": matching_total,
            "in_kind": latest_balance.get("in_kind"),
            "cash_on_hand": latest_balance.get("cash_on_hand"),
            "reported_on": (totals or {}).get("reported_on") or latest_submitted,
            "statements": statements,
            "contributions": sorted(contribs.values(), key=lambda r: (r.get("occurred_on") or "", r.get("clerk_item_id") or 0)),
            "expenditures": sorted(exps.values(), key=lambda r: (r.get("occurred_on") or "", r.get("clerk_item_id") or 0)),
        })

    return {
        "retrieved_on": os.environ.get("BV_RETRIEVED_ON") or datetime.date.today().isoformat(),
        "summary_url": summary_url,
        "summary_title": "City of Boulder Election Finance — Summary of Contributions and Expenditures (2026)",
        "list_url": BASE + "committeeFilings.php",
        "notes": (
            "Live city clerk app. electionID=25 is the 2026 municipal cycle. Other electionIDs "
            "returned this same 2026 table (checked 1 and 10–30). Historical Laserfiche at "
            "documents.bouldercolorado.gov/WebLink/Browse.aspx?id=59131 is a cookie/JS archive; "
            "not listed this pass. Alejandro De Varona has an official committee but is not on "
            "the certified clerk candidate list — stored with person=null. Itemized rows are "
            "unioned across statements by clerk item id; an amends_id drops the amended row."
        ),
        "committees": harvested,
    }


def _round_money(obj):
    if isinstance(obj, float):
        return round(obj, 2)
    if isinstance(obj, dict):
        return {k: _round_money(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_money(v) for v in obj]
    return obj


def main() -> None:
    data = _round_money(harvest())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    n = len(data["committees"])
    mapped = sum(1 for c in data["committees"] if c.get("person"))
    donors = sum(len(c["contributions"]) for c in data["committees"])
    spent = sum(len(c["expenditures"]) for c in data["committees"])
    print(f"wrote {OUT}  committees={n} mapped_people={mapped} contribution_rows={donors} expenditure_rows={spent}")
    for c in data["committees"]:
        print(
            f"  {c['kind']:24} {c.get('person') or '—':24} "
            f"${c.get('contributions_total') or 0:>10,.2f}  "
            f"n={len(c['contributions']):3}  {c['committee_name'][:50]}"
        )


if __name__ == "__main__":
    main()
