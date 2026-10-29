#!/usr/bin/env python3
"""Fetch Boulder County's election-night results and keep the City of Boulder contests.

    python3 tools/fetch_results_2026.py              # fetch, save raw files, write results.json
    python3 tools/fetch_results_2026.py --dry-run    # fetch and print, write nothing
    python3 tools/fetch_results_2026.py --offline tests/fixtures/results_2023C --year 2023 --out /tmp/r.json

Where the numbers come from (checked 2026-10-29; see RESULTS-RUNBOOK.md):
- The county's results app (election.boco.solutions/ElectionResults2026G/) is mirrored to
  https://electionresults.bouldercounty.gov/. There is no CSV or JSON export: each contest's
  rows sit as JSON inside the page (kendoGrid "Data": CandidateNameResults, TotalVotes,
  CandidateOrderBy = ballot order).
- The mayor's contest on that page only links to Home/RcvContest/1.html, which links the
  county's ranked-choice "short report" PDF (round-by-round table) and an RCVis chart.
  The PDF is the county's own file, so rounds come from it (via `pdftotext -layout`).
- The mirror root still holds stale 2023 files under Home/, so every page is checked for
  the expected election title before it is used.

Raw files are saved gzipped under data/harvest/2026/results_raw/<UTC time>/ with a
manifest (URL, retrieval time, sha256). The parsed file is data/harvest/2026/results.json,
which build_results_2026.py renders when BV_RESULTS=1. If a check fails, nothing is
written and the exit code is non-zero, so a bad fetch never replaces good numbers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # build_results_2026 / ingest_2026 for shared name matching
OUT = ROOT / "data" / "harvest" / "2026" / "results.json"
RAW_DIR = ROOT / "data" / "harvest" / "2026" / "results_raw"
BALLOT_ORDER = ROOT / "data" / "harvest" / "2026" / "ballot_order.json"
DENVER = ZoneInfo("America/Denver")

# The county's own links: its results page points at the mirror; the mirror is copied from the app.
BASES = ("https://electionresults.bouldercounty.gov/",
         "https://election.boco.solutions/ElectionResults2026G/")
EXPECT_TITLE = "2026 General Election"
EXPECT_DATE = "November 3, 2026"
MEASURE_CODES_2026 = ("2J", "2K", "2L", "2M")
UA = "bouldervotes.org results reader (+https://bouldervotes.org/; nonpartisan voter guide)"
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}


class ParseError(Exception):
    pass


# ---------------------------------------------------------------- page parsing
def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _span(page: str, cls: str) -> str | None:
    m = re.search(rf'class="{cls}">(.*?)</span>', page, re.S)
    return _text(m.group(1)) if m else None


def header(page: str) -> dict:
    """Election title, date, the county's own status label and its 'Last Updated' time."""
    updated = _span(page, "EnrHeaderLastUpdatedDateTime")
    iso = None
    if updated:
        try:
            iso = dt.datetime.strptime(updated, "%m/%d/%Y %I:%M %p").replace(tzinfo=DENVER).isoformat()
        except ValueError:
            iso = None
    ballots = re.search(r"Total Ballots Counted:\s*</td>\s*<td[^>]*>\s*([\d,]+)", page)
    return {"title": _span(page, "EnrHeaderTitle"), "date": _span(page, "EnrHeaderDate"),
            "county_status": _span(page, "EnrHeaderSubtitle"), "county_updated": iso,
            "ballots_counted": int(ballots.group(1).replace(",", "")) if ballots else None}


def _office(title: str) -> str | None:
    t = title.lower()
    if not t.startswith("city of boulder"):
        return None
    if "ballot issue" in t or "ballot question" in t:  # first: a measure title may mention the council
        return "measure"
    if "mayor" in t:
        return "mayor"
    if "council" in t:
        return "council"
    return None


def _seats(title: str) -> int | None:
    m = re.search(r"(?:vote for|more than)\s+(?:not\s+|no\s+)?(?:more than\s+)?(\w+)\)?\s*$", title, re.I)
    if not m:
        return None
    w = m.group(1).lower()
    return int(w) if w.isdigit() else WORDS.get(w)


def _yes_no(choice: str) -> str | None:
    c = choice.strip().lower()
    if c.startswith(("for", "yes")):
        return "yes"
    if c.startswith(("against", "no")):
        return "no"
    return None


def contests(page: str, page_url: str) -> list[dict]:
    """City of Boulder contests on a results page, choices in ballot order."""
    out = []
    blocks = re.split(r'<div id="contest(\d+)">', page)
    for num, block in zip(blocks[1::2], blocks[2::2]):
        th = re.search(r'EnrContestTitleHeader[^>]*>(.*?)</th>', block, re.S)
        if not th:
            continue
        parts = [_text(p) for p in re.split(r"<br\s*/?>", th.group(1)) if _text(p)]
        title = " ".join(parts)
        office = _office(title)
        if office is None:
            continue
        url = f"{page_url}#contest{num}"
        rcv = re.search(r'href="([^"]*RcvContest/[^"]+)"', block)
        data = re.search(r'"data":\{"Data":(\[.*?\]),"Total":(\d+)', block, re.S)
        rows = sorted(json.loads(data.group(1)), key=lambda r: r["CandidateOrderBy"]) if data else []
        if data and int(data.group(2)) != len(rows):
            raise ParseError(f"{title}: grid says {data.group(2)} rows, parsed {len(rows)}")
        c = {"office": office, "name": title, "official_url": url}
        if office == "measure":
            m = re.search(r"Ballot (?:Issue|Question)\s+(\d{1,3}[A-Z]?)\b", title)
            c["code"] = m.group(1) if m else None
            c["title"] = parts[1] if len(parts) > 1 else title
            tally = {}
            for r in rows:
                side = _yes_no(r["CandidateNameResults"])
                if side is None or side in tally:
                    raise ParseError(f"{title}: unexpected choice {r['CandidateNameResults']!r}")
                tally[side] = int(r["TotalVotes"])
            if rows and set(tally) != {"yes", "no"}:
                raise ParseError(f"{title}: expected a yes and a no row, got {sorted(tally)}")
            if not rows:
                continue  # listed with no numbers yet
            c.update(yes=tally["yes"], no=tally["no"])
        else:
            c["method"] = "ranked_choice" if office == "mayor" else "plurality"
            c["seats"] = 1 if office == "mayor" else _seats(title)
            c["candidates"] = [{"name": " ".join(r["CandidateNameResults"].split()), "votes": int(r["TotalVotes"])}
                               for r in rows]
            if rcv:
                c["rcv_page_url"] = urllib.parse.urljoin(page_url, rcv.group(1))
        out.append(c)
    return out


def rcv_links(page: str, page_url: str) -> dict:
    pdf = re.search(r'href="([^"]*GetRcvFile/[^"]+\.pdf)"', page, re.I)
    vis = re.search(r'href="(https://rcvis\.com/[^"]+)"', page)
    return {"pdf_url": urllib.parse.urljoin(page_url, pdf.group(1)) if pdf else None,
            "rcvis_url": vis.group(1) if vis else None}


# ---------------------------------------------------------------- ranked-choice report
_NUM = r"-?[\d,]+(?:\.\d+)?%?"


def _nums(line: str) -> tuple[str, list[str]]:
    m = re.match(rf"\s*(.*?)\s+((?:{_NUM}\s*)+)$", line)
    if not m:
        return line.strip(), []
    return m.group(1).strip(), m.group(2).split()


def _int(tok: str) -> int:
    return int(tok.replace(",", ""))


def parse_rcv_report(text: str) -> dict:
    """The county's RcvShortReport, as text from `pdftotext -layout`.

    Each candidate row is (votes, percentage, transfer) per round. Every round must add
    up to the report's own 'Continuing Ballots Total', or the parse is rejected."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    hdr = next((ln for ln in lines if re.search(r"\bRound 1\b", ln)), None)
    if hdr is None:
        raise ParseError("no 'Round 1' header in the ranked-choice report")
    n = len(re.findall(r"\bRound \d+\b", hdr))
    stamp = re.search(r"(\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2})", text)
    start = lines.index(hdr)
    names, rows, totals, extra = [], {}, None, {}
    for ln in lines[start + 1:]:
        label, toks = _nums(ln)
        if not toks:
            continue
        if label.startswith("Continuing Ballots Total"):
            totals = [_int(t) for t in toks]
            continue
        if totals is None:
            if label in ("", "Votes") or len(toks) != 3 * n:
                if label and len(toks) not in (0,):
                    raise ParseError(f"candidate row {label!r} has {len(toks)} numbers, expected {3 * n}")
                continue
            names.append(label)
            rows[label] = [_int(toks[3 * k]) for k in range(n)]
        elif label in ("Exhausted", "Blanks", "Overvotes", "Non Transferable Total", "Threshold"):
            extra[label] = toks
    if totals is None or len(totals) != n or not names:
        raise ParseError("ranked-choice report: no candidate rows or no 'Continuing Ballots Total'")
    for k in range(n):
        s = sum(rows[nm][k] for nm in names)
        if s != totals[k]:
            raise ParseError(f"round {k + 1}: candidates add to {s:,}, report says {totals[k]:,}")
    def per_round(label: str, step: int) -> list[int] | None:
        toks = extra.get(label)
        return [_int(toks[step * k]) for k in range(n)] if toks and len(toks) == step * n else None
    inactive = per_round("Non Transferable Total", 1)  # blanks + overvotes + exhausted
    rounds = []
    for k in range(n):
        # A candidate removed in an earlier round shows 0 from then on; leave them out of later rounds.
        cands = [{"name": nm, "votes": rows[nm][k]} for nm in names if k == 0 or rows[nm][k] > 0]
        rd = {"round": k + 1, "candidates": cands, "continuing": totals[k]}
        if inactive:
            rd["inactive"] = inactive[k]
        rounds.append(rd)
    report_time = None
    if stamp:
        report_time = dt.datetime.strptime(stamp.group(1), "%m/%d/%Y %H:%M:%S").replace(tzinfo=DENVER).isoformat()
    return {"rounds": rounds, "report_time": report_time, "order": names}


def pdf_text(pdf: Path) -> str:
    if not shutil.which("pdftotext"):
        raise ParseError("pdftotext (poppler) is not installed")
    return subprocess.run(["pdftotext", "-layout", str(pdf), "-"], check=True,
                          capture_output=True, text=True).stdout


# ---------------------------------------------------------------- assemble
def assemble(index_html: str, index_url: str, *, rcv_html: str | None = None, rcv_url: str | None = None,
             rcv_report: dict | None = None, retrieved_at: str, raw_dir: str | None,
             expect_title: str | None = EXPECT_TITLE) -> dict:
    h = header(index_html)
    if expect_title and h["title"] != expect_title:
        raise ParseError(f"results page is for {h['title']!r}, expected {expect_title!r} (stale mirror?)")
    cs = contests(index_html, index_url)
    if rcv_html is not None and expect_title and header(rcv_html)["title"] != expect_title:
        # The mirror still serves an old ranked-choice page until the county posts this year's: no rounds yet.
        print(f"NOTE: ranked-choice page is for {header(rcv_html)['title']!r}; showing no rounds.", file=sys.stderr)
        rcv_html = rcv_url = rcv_report = None
    for c in cs:
        if c["office"] != "mayor":
            continue
        c["rounds"] = []
        if rcv_report:
            c["rounds"] = rcv_report["rounds"]
            c["rounds_url"] = rcv_report.get("url")
            c["rounds_page_url"] = rcv_url
            c["rounds_updated"] = rcv_report.get("report_time")
            if rcv_report.get("error"):
                c["rounds_error"] = rcv_report["error"]
        if not c["candidates"] and c["rounds"]:
            # The county's page lists no first choices for mayor; round 1 of its count is the first choices.
            c["candidates"] = [dict(r) for r in c["rounds"][0]["candidates"]]
            c["first_choices_from"] = "round 1 of the county's ranked-choice report"
            c["official_url"] = rcv_url or c["official_url"]
        elif c["candidates"]:
            c["first_choices_from"] = "the county's results page"
    election_date = None
    if h["date"]:
        try:
            election_date = dt.datetime.strptime(h["date"], "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
    return {"schema_version": 1,
            "election": {"name": f"Boulder County {h['title']}" if h["title"] else "Boulder County election",
                         "date": election_date},
            "county_status": h["county_status"], "county_updated": h["county_updated"],
            "ballots_counted_countywide": h["ballots_counted"],
            "retrieved_at": retrieved_at, "official_url": index_url, "raw_dir": raw_dir,
            "contests": cs}


def canon(name: str) -> str:
    """Same name matching as the renderer: case, punctuation and known aliases ignored."""
    from build_results_2026 import norm_name
    from ingest_2026 import NAME_ALIASES
    aliases = {norm_name(k): norm_name(v) for k, v in NAME_ALIASES.items()}
    n = norm_name(name)
    return aliases.get(n, n)


def check_2026(data: dict) -> list[str]:
    """Problems that should stop a 2026 write: missing roster names or measures."""
    order = json.loads(BALLOT_ORDER.read_text(encoding="utf-8"))["races"]
    probs = []
    for office in ("mayor", "council"):
        cs = [c for c in data["contests"] if c["office"] == office]
        if len(cs) != 1:
            probs.append(f"{office}: expected one contest, found {len(cs)}")
            continue
        got = {canon(c["name"]) for c in cs[0]["candidates"]}
        for rd in cs[0].get("rounds") or []:
            stray = [c["name"] for c in rd["candidates"] if canon(c["name"]) not in map(canon, order[office])]
            if stray:
                probs.append(f"{office} round {rd['round']}: names not on our ballot list: {stray}")
        if not got:
            continue  # posted with no numbers yet
        missing = [n for n in order[office] if canon(n) not in got]
        if missing:
            probs.append(f"{office}: names not in the county file: {missing}")
        if office == "council" and cs[0].get("seats") not in (5, None):
            probs.append(f"council: title says {cs[0]['seats']} seats, expected 5")
    codes = {c.get("code") for c in data["contests"] if c["office"] == "measure"}
    if codes and not set(MEASURE_CODES_2026) <= codes:
        probs.append(f"measures: expected {MEASURE_CODES_2026}, found {sorted(c for c in codes if c)}")
    return probs


# ---------------------------------------------------------------- network
def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def save_raw(raw_dir: Path, name: str, url: str, body: bytes, manifest: list) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    p = raw_dir / (name + ".gz")
    p.write_bytes(gzip.compress(body, mtime=0))
    manifest.append({"file": p.name, "url": url, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                     "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    return p


def fetch_rcv(rcv_url: str, raw_dir: Path, manifest: list, dry_run: bool) -> tuple[str | None, dict | None]:
    """The county's ranked-choice page and PDF. Any problem here drops only the rounds:
    (None, None) means no rounds posted yet; a report with "error" means posted but unreadable."""
    try:
        rb = get(rcv_url)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"WARNING: ranked-choice page not fetched: {e}", file=sys.stderr)
        return None, {"rounds": [], "error": f"fetch failed: {e}"}
    rcv_html = rb.decode("utf-8", "replace")
    if not dry_run:
        save_raw(raw_dir, "rcv.html", rcv_url, rb, manifest)
    links = rcv_links(rcv_html, rcv_url)
    if header(rcv_html)["title"] != EXPECT_TITLE or not links["pdf_url"]:
        return rcv_html, None  # stale copy or nothing posted yet
    try:
        pb = get(links["pdf_url"])
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"WARNING: ranked-choice PDF not fetched: {e}", file=sys.stderr)
        return rcv_html, {"rounds": [], "error": f"fetch failed: {e}", "url": links["pdf_url"]}
    tmp = Path(__import__("tempfile").mkdtemp()) / "rcv.pdf"
    tmp.write_bytes(pb)
    if not dry_run:
        save_raw(raw_dir, "rcv.pdf", links["pdf_url"], pb, manifest)
    try:
        report = parse_rcv_report(pdf_text(tmp))
    except (ParseError, subprocess.CalledProcessError) as e:
        # The rest of the results still publish; the page says the rounds couldn't be read.
        print(f"WARNING: ranked-choice report not used: {e}", file=sys.stderr)
        return rcv_html, {"rounds": [], "error": str(e), "url": links["pdf_url"]}
    if report["report_time"] and report["report_time"][:10] < "2026-11-03":
        print(f"NOTE: ranked-choice report is dated {report['report_time']} (stale copy); showing no rounds.", file=sys.stderr)
        return rcv_html, None
    report["url"] = links["pdf_url"]
    return rcv_html, report


def fetch_live(dry_run: bool) -> dict:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    raw_dir = RAW_DIR / stamp
    manifest: list = []
    errors = []
    for base in BASES:
        try:
            body = get(base)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            errors.append(f"{base}: {e}")
            continue
        page = body.decode("utf-8", "replace")
        h = header(page)
        if h["title"] != EXPECT_TITLE:
            errors.append(f"{base}: title {h['title']!r}")
            continue
        if not re.search(r'<div id="contest\d+">', page):
            print(f"{base}: {EXPECT_TITLE} page has no contests yet (county status: {h['county_status']!r}).")
            raise SystemExit(3)
        break
    else:
        raise ParseError("no usable 2026 results page: " + "; ".join(errors))
    if not dry_run:
        save_raw(raw_dir, "index.html", base, body, manifest)
    rcv_html = rcv_url = report = None
    mayor = [c for c in contests(page, base) if c["office"] == "mayor"]
    if mayor and mayor[0].get("rcv_page_url"):
        rcv_url = mayor[0]["rcv_page_url"]
        rcv_html, report = fetch_rcv(rcv_url, raw_dir, manifest, dry_run)
    data = assemble(page, base, rcv_html=rcv_html, rcv_url=rcv_url, rcv_report=report,
                    retrieved_at=now.isoformat().replace("+00:00", "Z"),
                    raw_dir=None if dry_run else raw_dir.relative_to(ROOT).as_posix())
    if not dry_run:
        (raw_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return data


def from_dir(d: Path, year: str) -> dict:
    """Parse saved pages (a fixture or a results_raw/<time>/ folder)."""
    def read(name: str) -> str | None:
        for p in (d / name, d / (name + ".gz")):
            if p.exists():
                b = p.read_bytes()
                return (gzip.decompress(b) if p.suffix == ".gz" else b).decode("utf-8", "replace")
        return None
    src = json.loads((d / "SOURCES.json").read_text()) if (d / "SOURCES.json").exists() else {}
    index = read("index.html")
    rcv = read("rcv.html") or read("RcvContest-1.html")
    report = None
    pdf = next((p for p in (d / "rcv.pdf", d / "COBMayorRCVShortPDF.pdf") if p.exists()), None)
    if pdf is None and (d / "rcv.pdf.gz").exists():
        pdf = Path(__import__("tempfile").mkdtemp()) / "rcv.pdf"
        pdf.write_bytes(gzip.decompress((d / "rcv.pdf.gz").read_bytes()))
    if pdf is not None:
        report = parse_rcv_report(pdf_text(pdf))
        report["url"] = src.get("rcv_pdf_url")
    return assemble(index, src.get("index_url", "https://electionresults.bouldercounty.gov/"),
                    rcv_html=rcv, rcv_url=src.get("rcv_page_url"), rcv_report=report,
                    retrieved_at=src.get("retrieved_at", ""), raw_dir=None,
                    expect_title=f"{year} " + src.get("title_suffix", "General Election"))


def summary(data: dict) -> str:
    L = [f"{data['election']['name']} · county says {data['county_status']!r}, last updated {data['county_updated']}"]
    for c in data["contests"]:
        if c["office"] == "measure":
            L.append(f"  {c['code']}: YES {c['yes']:,} / NO {c['no']:,}")
        else:
            L.append(f"  {c['office']} ({c['name']}): " + ", ".join(f"{x['name']} {x['votes']:,}" for x in c["candidates"]))
            for rd in c.get("rounds") or []:
                L.append(f"    round {rd['round']}: " + ", ".join(f"{x['name']} {x['votes']:,}" for x in rd["candidates"]))
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and print; save nothing")
    ap.add_argument("--offline", type=Path, help="parse a saved folder instead of fetching")
    ap.add_argument("--year", default="2026", help="with --offline: the election year the pages must show")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    try:
        data = from_dir(a.offline, a.year) if a.offline else fetch_live(a.dry_run)
    except ParseError as e:
        print(f"STOP: {e}. Nothing written.", file=sys.stderr)
        return 2
    if not a.offline or a.year == "2026":
        probs = check_2026(data)
        if probs:
            print("STOP: " + " | ".join(probs) + ". Nothing written.", file=sys.stderr)
            return 2
    print(summary(data))
    if a.dry_run:
        return 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
