"""
fetch_mda_text.py
=================
Downloads the MD&A section (Item 7) from SEC EDGAR 10-K filings for
10 US retailers and saves each year's text to mda_texts/<TICKER>_<YEAR>_MDA.txt.

Key improvements over v1
------------------------
• iXBRL / inline-XBRL stripping so namespace tags don't break extraction.
• Cascading heading patterns (full title → short title → bare "ITEM 7").
• Multi-document fallback: if the primary doc fails or produces a stub,
  we query the filing index JSON and try every listed 10-K/10-K/A document.
• Minimum section length guard (MIN_MDA_CHARS).  Stubs are rejected and
  we try the next candidate document.
• Re-run safety: existing good files are skipped automatically.
"""

import re
import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup

EMAIL   = "nirbhaychhabra1@gmail.com"
HEADERS = {"user-agent": f"Student Research Project - {EMAIL}"}

COMPANIES = {
    "WMT":  "Walmart",
    "TGT":  "Target",
    "COST": "Costco",
    "TJX":  "TJX Companies",
    "DG":   "Dollar General",
    "ROST": "Ross Stores",
    "BBY":  "Best Buy",
    "KSS":  "Kohl's",
    "DLTR": "Dollar Tree",
    "M":    "Macy's",
}

YEARS_BACK    = 5
MIN_MDA_CHARS = 5_000   # anything shorter is a stub / mis-extraction
OUTPUT_DIR    = Path(__file__).parent / "mda_texts"
OUTPUT_DIR.mkdir(exist_ok=True)


# ── CIK LOOKUP ────────────────────────────────────────────────────────────────

def get_ticker_to_cik_map() -> dict[str, str]:
    url  = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return {
        e["ticker"].upper(): str(e["cik_str"]).zfill(10)
        for e in resp.json().values()
    }


# ── FILING DISCOVERY ──────────────────────────────────────────────────────────

def get_recent_10k_filings(cik: str) -> list[dict]:
    """Return the YEARS_BACK most recent 10-K filing stubs for a CIK."""
    url  = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    filings: list[dict] = []

    def _harvest(block: dict) -> None:
        for i, form in enumerate(block.get("form", [])):
            if form == "10-K" and len(filings) < YEARS_BACK:
                filings.append({
                    "accession_number": block["accessionNumber"][i],
                    "filing_date":      block["filingDate"][i],
                    "primary_document": block["primaryDocument"][i],
                })

    _harvest(data["filings"]["recent"])

    # Walk paginated older-filings pages if we still need more
    for page_meta in data["filings"].get("files", []):
        if len(filings) >= YEARS_BACK:
            break
        if page_meta.get("name", "").startswith("submissions"):
            pr = requests.get(
                f"https://data.sec.gov/submissions/{page_meta['name']}",
                headers=HEADERS, timeout=20,
            )
            if pr.status_code == 200:
                _harvest(pr.json())
            time.sleep(0.3)

    return filings[:YEARS_BACK]


def get_candidate_urls(cik: str, accession_number: str, primary_document: str) -> list[str]:
    """
    Build an ordered list of document URLs to try for a given filing.
    Priority:
      1. Primary document from submissions API
      2. Any 10-K / 10-K/A document listed in the filing index JSON
      3. Any .htm file in the filing index that isn't an exhibit or metadata file
    """
    acc_no  = accession_number.replace("-", "")
    base    = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_no}/"
    urls    = [base + primary_document]

    idx_url = base + accession_number + "-index.json"
    try:
        ir = requests.get(idx_url, headers=HEADERS, timeout=15)
        if ir.status_code == 200:
            docs = ir.json().get("documents", [])
            for doc in docs:
                fname = doc.get("filename", "")
                dtype = doc.get("type", "")
                if not fname or fname == primary_document:
                    continue
                candidate = base + fname
                fl = fname.lower()
                # Prefer explicit 10-K type documents
                if dtype in ("10-K", "10-K/A"):
                    urls.insert(1, candidate)   # second priority
                elif fl.endswith((".htm", ".html")) and not any(
                    x in fl for x in ["ex", "exhibit", "r9999", "meta", "xsd"]
                ):
                    urls.append(candidate)
    except Exception:
        pass

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


# ── HTML → PLAIN TEXT (with iXBRL handling) ───────────────────────────────────

def html_to_text(html: str) -> str:
    """
    Parse HTML (including inline XBRL / iXBRL documents) to plain text.
    Namespace-prefixed tags (ix:*, xbrli:*, etc.) are unwrapped so their
    text content is preserved but the tags don't disrupt text flow.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Unwrap any XML-namespace tags — keeps content, removes wrapper
    for ns_tag in soup.find_all(re.compile(r"^\w+:\w+")):
        try:
            ns_tag.unwrap()
        except Exception:
            pass

    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{2,}", "\n", text)   # collapse blank lines
    return text


# ── MD&A EXTRACTION ───────────────────────────────────────────────────────────

# Ordered from most-specific to most-general; we stop at the first pattern
# that yields a section of at least MIN_MDA_CHARS characters.
_HEADING_PATTERNS = [
    # Full SEC-standard title (handles curly apostrophe and straight apostrophe)
    re.compile(
        r"\nItem\s+7\s*[.\-\u2014]?\s*Management['\u2019]s\s+Discussion\s+and\s+"
        r"Analysis\s+of\s+Financial\s+Condition\s+and\s+Results\s+of\s+Operations",
        re.IGNORECASE,
    ),
    # Shorter variant: "Management's Discussion and Analysis"
    re.compile(
        r"\nItem\s+7\s*[.\-\u2014]?\s*Management['\u2019]s\s+Discussion\s+and\s+Analysis",
        re.IGNORECASE,
    ),
    # Bare item marker (last resort — more false-positive-prone)
    re.compile(r"\nITEM\s+7\b", re.IGNORECASE),
]

_END_PATTERN = re.compile(r"\nItem\s+(7A|8)\s*[.\-\u2014]", re.IGNORECASE)


def _extract_from_text(text: str) -> str | None:
    """Try each heading pattern and return the first section ≥ MIN_MDA_CHARS."""
    for heading_pat in _HEADING_PATTERNS:
        candidates = []
        for m in heading_pat.finditer(text):
            before = text[max(0, m.start() - 40): m.start()].lower()
            after  = text[m.end(): m.end() + 30].lstrip("\n ")

            is_toc       = bool(re.match(r"^\d{1,4}\s*\n", after))
            is_xref      = ("titled" in before
                            or after[:1] in ('"', "'", "\u201c", "\u201d"))
            if is_toc or is_xref:
                continue
            candidates.append(m)

        if not candidates:
            continue

        real_heading = candidates[-1]
        end_match    = _END_PATTERN.search(text, real_heading.end())
        section = (
            text[real_heading.start(): end_match.start()]
            if end_match
            else text[real_heading.start():]
        )
        section = section.strip()

        if len(section) >= MIN_MDA_CHARS:
            return section

    return None


def extract_mda(html: str) -> str | None:
    """Convert HTML → text and attempt MD&A extraction."""
    return _extract_from_text(html_to_text(html))


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Fetching MD&A for {len(COMPANIES)} companies, "
          f"last {YEARS_BACK} 10-K filings each.")
    print(f"Output → {OUTPUT_DIR.resolve()}\n")

    ticker_map = get_ticker_to_cik_map()
    failures: list[tuple] = []

    for ticker, name in COMPANIES.items():
        cik = ticker_map.get(ticker)
        if not cik:
            print(f"[SKIP] CIK not found for {ticker}")
            failures.append((ticker, "N/A", "CIK not found"))
            continue

        print(f"\n{'─'*55}")
        print(f"  {name} ({ticker})  •  CIK {cik}")
        print(f"{'─'*55}")

        filings = get_recent_10k_filings(cik)
        print(f"  Found {len(filings)} 10-K filings to process.")

        for filing in filings:
            year     = filing["filing_date"][:4]
            out_path = OUTPUT_DIR / f"{ticker}_{year}_MDA.txt"

            # Skip good existing files; delete stubs so we retry them
            if out_path.exists():
                if out_path.stat().st_size >= MIN_MDA_CHARS:
                    print(f"    [{year}] ✓ Already saved ({out_path.stat().st_size:,} chars) — skipping.")
                    continue
                else:
                    print(f"    [{year}] ⚠ Stub file found — will retry.")
                    out_path.unlink()

            print(f"    [{year}] Fetching {filing['filing_date']} 10-K...")

            candidate_urls = get_candidate_urls(
                cik, filing["accession_number"], filing["primary_document"]
            )

            mda = None
            for url in candidate_urls:
                resp = requests.get(url, headers=HEADERS, timeout=30)
                time.sleep(0.35)   # polite EDGAR rate

                if resp.status_code != 200:
                    continue

                mda = extract_mda(resp.text)
                if mda:
                    print(f"           (used: .../{url.split('/')[-1]})")
                    break   # found a good extraction — stop trying

            if mda:
                out_path.write_text(mda, encoding="utf-8")
                print(f"    [{year}] ✓ Saved {len(mda):,} chars → {out_path.name}")
            else:
                failures.append((ticker, filing["filing_date"], "MD&A not found"))
                print(f"    [{year}] ✗ Could not extract MD&A — flagged for review.")

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  Done.  Files in: {OUTPUT_DIR.resolve()}")
    total = len(list(OUTPUT_DIR.glob("*.txt")))
    good  = sum(1 for f in OUTPUT_DIR.glob("*.txt") if f.stat().st_size >= MIN_MDA_CHARS)
    print(f"  Total files: {total}  •  Good (≥{MIN_MDA_CHARS:,} chars): {good}")

    if failures:
        print(f"\n  {len(failures)} filing(s) still need manual review:")
        for t, d, r in failures:
            print(f"    {t} ({d}): {r}")
        print("\n  Tip: open the EDGAR filing in a browser and copy Item 7 manually.")


if __name__ == "__main__":
    main()